"""Parse the cached Freebox docs HTML into an intermediate representation (IR).

The IR is doc-shaped, not yet OpenAPI: a list of operations and a dict of named
schemas. ``build_openapi`` turns it into a real spec. Fully deterministic.

Robustness strategy: operation method/path come from the authoritative
``objects.inv`` (joined by HTML anchor), never guessed from rendered markup.
The HTML supplies descriptions, object references, and embedded example JSON.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from bs4 import BeautifulSoup, Tag

from .common import HTML_DIR, IR_PATH, write_json
from .inventory import Inventory, load_inventory

PRIMITIVES = {
    "int": "integer",
    "integer": "integer",
    "uint": "integer",
    "int64": "integer",
    "long": "integer",
    "timestamp": "integer",
    "string": "string",
    "str": "string",
    "bool": "boolean",
    "boolean": "boolean",
    "enum": "string",
    "ipv4": "string",
    "ipv6": "string",
    "mac": "string",
    "dict": "object",
    "map": "object",
    "object": "object",
    "float": "number",
    "double": "number",
}
# Type tokens that carry an extra semantic hint we keep as OpenAPI `format`.
FORMAT_HINT = {"timestamp": "unix-timestamp", "ipv4": "ipv4", "ipv6": "ipv6", "mac": "mac"}

_VERSION_PREFIX = re.compile(r"^/api/(v\d+)/")
_RST_OBJ = re.compile(r":json:object:`(\w+)`")
_FIXED_ARRAY = re.compile(r"^(.*?)\[(\d+)\]$")
_OPEN_ARRAY = re.compile(r"^(.*?)\[\]$")


@dataclass
class TypeSpec:
    """Normalized type descriptor for a property (JSON-schema-ish, pre-OpenAPI)."""

    kind: str  # primitive | ref | array | object
    json_type: str | None = None  # for primitive/object: integer/string/.../object
    ref: str | None = None  # for ref: target object name
    format: str | None = None  # unix-timestamp / ipv4 / ipv6 / mac
    items: "TypeSpec | None" = None  # for array
    min_items: int | None = None
    max_items: int | None = None
    raw: str = ""  # original rendered type text (audit trail)

    def to_dict(self) -> dict:
        d: dict = {"kind": self.kind, "raw": self.raw}
        for k in ("json_type", "ref", "format", "min_items", "max_items"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        if self.items is not None:
            d["items"] = self.items.to_dict()
        return d


@dataclass
class EnumValue:
    value: str
    description: str = ""


@dataclass
class Property:
    name: str
    type: dict  # TypeSpec.to_dict()
    description: str = ""
    readonly: bool = False
    writeonly: bool = False
    optional: bool = False
    enum: list[dict] = field(default_factory=list)


@dataclass
class Schema:
    name: str
    page: str
    description: str = ""
    properties: list[dict] = field(default_factory=list)


@dataclass
class Operation:
    operation_id: str
    method: str
    path: str  # version-stripped, e.g. "wifi/config/"
    path_doc: str  # as documented, e.g. "/api/v2/wifi/config/"
    doc_version_prefix: str | None  # "v2" / "v4" / None
    page: str
    anchor: str
    summary: str = ""
    description: str = ""
    path_params: list[str] = field(default_factory=list)
    query_params: list[str] = field(default_factory=list)
    referenced_objects: list[str] = field(default_factory=list)
    request_object: str | None = None
    response_object: str | None = None
    # Result resolution: every operation gets a concrete answer here.
    #   object | array | primitive | none | unknown
    response_kind: str = "unknown"
    response_inferred_schema: dict | None = None
    templated_alternatives: list[str] = field(default_factory=list)
    example_request: object = None
    example_response: object = None
    example_response_raw: str | None = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _clean_text(node: Tag | None) -> str:
    if node is None:
        return ""
    txt = node.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", txt).strip()


def operation_id(method: str, path: str) -> str:
    slug = path.strip("/")
    slug = slug.replace("{", "").replace("}", "")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", slug).strip("_").lower()
    slug = re.sub(r"_+", "_", slug)
    return f"{method}_{slug}" if slug else method


def strip_version(path_doc: str) -> tuple[str, str | None]:
    m = _VERSION_PREFIX.match(path_doc)
    if m:
        return path_doc[m.end() :], m.group(1)
    return path_doc.lstrip("/"), None


def path_param_names(path: str) -> list[str]:
    return re.findall(r"\{([^}]+)\}", path)


def infer_schema(value: object, depth: int = 0) -> dict:
    """Infer a JSON Schema fragment from an example JSON value (for endpoints whose
    result is not a documented named object — logs, ad-hoc dicts, arrays)."""
    if depth > 6:
        return {}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if value is None:
        return {}
    if isinstance(value, list):
        items = infer_schema(value[0], depth + 1) if value else {}
        return {"type": "array", "items": items}
    if isinstance(value, dict):
        props = {k: infer_schema(v, depth + 1) for k, v in value.items()}
        return {"type": "object", "properties": props}
    return {}


# --------------------------------------------------------------------------- #
# Property type parsing
# --------------------------------------------------------------------------- #
def _resolve_token(token: str, known_objects: set[str]) -> TypeSpec:
    token = token.strip()
    raw = token
    rst = _RST_OBJ.search(token)
    if rst:
        token = rst.group(1)
    base = token.strip()
    low = base.lower()
    if base in known_objects:
        return TypeSpec(kind="ref", ref=base, raw=raw)
    if low in PRIMITIVES:
        return TypeSpec(
            kind="primitive", json_type=PRIMITIVES[low], format=FORMAT_HINT.get(low), raw=raw
        )
    # Unknown bareword: if it is CamelCase it is most likely an (unlisted) object ref.
    if re.match(r"^[A-Z][A-Za-z0-9]+$", base):
        return TypeSpec(kind="ref", ref=base, raw=raw)
    # Fallback: treat as opaque string.
    return TypeSpec(kind="primitive", json_type="string", raw=raw or "unknown")


def parse_property_type(dt: Tag, known_objects: set[str]) -> TypeSpec:
    descname = dt.find("code", class_="descname")
    # Walk dt children after descname, splitting modifiers (<em class=property>) out.
    type_parts: list[str] = []
    link_refs: list[str] = []
    array_marker = False
    started = descname is None
    for el in dt.children:
        if el is descname:
            started = True
            continue
        if not started:
            continue
        if isinstance(el, Tag):
            cls = el.get("class") or []
            if "headerlink" in cls:
                break
            if el.name == "em" and "property" in cls:
                continue  # modifier, handled separately below
            if el.name == "a" and "reference" in cls:
                href = el.get("href", "")
                frag = href.split("#")[-1] if "#" in href else _clean_text(el)
                link_refs.append(frag)
                type_parts.append(el.get_text())
                continue
            text = el.get_text()
            if "array of" in text.lower():
                array_marker = True
            type_parts.append(text)
        else:  # NavigableString
            text = str(el)
            if "array of" in text.lower():
                array_marker = True
            type_parts.append(text)

    type_expr = re.sub(r"\s+", " ", "".join(type_parts)).strip()
    # Prefer an explicit linked object reference for the item/base type.
    linked = link_refs[0] if link_refs else None

    # Array forms ----------------------------------------------------------
    if array_marker or "array of" in type_expr.lower():
        item_token = re.split(r"array of", type_expr, flags=re.I)[-1].strip(" []")
        item = (
            TypeSpec(kind="ref", ref=linked, raw=linked)
            if linked
            else _resolve_token(item_token, known_objects)
        )
        return TypeSpec(kind="array", items=item, raw=type_expr)

    fixed = _FIXED_ARRAY.match(type_expr)
    if fixed:
        base, n = fixed.group(1), int(fixed.group(2))
        item = (
            TypeSpec(kind="ref", ref=linked, raw=linked)
            if linked
            else _resolve_token(base, known_objects)
        )
        return TypeSpec(kind="array", items=item, min_items=n, max_items=n, raw=type_expr)

    open_arr = _OPEN_ARRAY.match(type_expr)
    if open_arr:
        base = open_arr.group(1)
        item = (
            TypeSpec(kind="ref", ref=linked, raw=linked)
            if linked
            else _resolve_token(base, known_objects)
        )
        return TypeSpec(kind="array", items=item, raw=type_expr)

    if linked:
        return TypeSpec(kind="ref", ref=linked, raw=type_expr)
    return _resolve_token(type_expr, known_objects)


def _modifiers(dt: Tag) -> tuple[bool, bool, bool]:
    mod_text = " ".join(em.get_text() for em in dt.find_all("em", class_="property"))
    full = (dt.get_text() or "").lower()
    readonly = "read-only" in mod_text.lower() or "[ro]" in full
    writeonly = "write-only" in mod_text.lower() or "[wo]" in full
    optional = "option" in mod_text.lower()  # matches "Optionnal" (sic) and "Optional"
    return readonly, writeonly, optional


def _enum_table(dd: Tag | None) -> list[EnumValue]:
    if dd is None:
        return []
    out: list[EnumValue] = []
    table = dd.find("table")
    if not table:
        return out
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        value = _clean_text(cells[0])
        desc = _clean_text(cells[1]) if len(cells) > 1 else ""
        if value:
            out.append(EnumValue(value=value, description=desc))
    return out


def parse_property(dl: Tag, known_objects: set[str]) -> Property:
    dt = dl.find("dt", recursive=False)
    dd = dl.find("dd", recursive=False)
    code = dt.find("code", class_="descname") if dt else None
    name = _clean_text(code) if code else "?"
    tspec = (
        parse_property_type(dt, known_objects)
        if dt
        else TypeSpec(kind="primitive", json_type="string")
    )
    readonly, writeonly, optional = _modifiers(dt) if dt else (False, False, False)
    enums = _enum_table(dd)
    # description = dd text minus any enum table content
    desc = ""
    if dd:
        p = dd.find("p", recursive=False)
        desc = _clean_text(p) if p else ""
        if not desc and not enums:
            desc = _clean_text(dd)
    return Property(
        name=name,
        type=tspec.to_dict(),
        description=desc,
        readonly=readonly,
        writeonly=writeonly,
        optional=optional,
        enum=[asdict(e) for e in enums],
    )


def extract_error_codes(soup: BeautifulSoup) -> list[dict]:
    """Extract per-section error codes from any 'error_code | Description' table."""
    out: list[dict] = []
    seen: set[str] = set()
    for table in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True).lower() for th in table.select("thead th")]
        if not headers or "error" not in headers[0].replace("_", " "):
            continue
        for tr in table.select("tbody tr"):
            cells = tr.find_all("td")
            if not cells:
                continue
            code = _clean_text(cells[0])
            desc = _clean_text(cells[1]) if len(cells) > 1 else ""
            if code and code not in seen:
                seen.add(code)
                out.append({"code": code, "description": desc})
    return out


def parse_object(dl: Tag, page: str, known_objects: set[str]) -> Schema:
    dt = dl.find("dt", recursive=False)
    dd = dl.find("dd", recursive=False)
    name = dt.get("id") if dt and dt.get("id") else _clean_text(dt.find("code") if dt else None)
    # Object-level description: a <p> immediately preceding the dl, if any.
    desc = ""
    prev = dl.find_previous_sibling("p")
    if prev:
        desc = _clean_text(prev)
    props: list[Property] = []
    if dd:
        for pdl in dd.find_all("dl", class_="property"):
            # only direct-ish properties; nested ones are captured too (depth-1 rare cases)
            props.append(parse_property(pdl, known_objects))
    return Schema(name=name, page=page, description=desc, properties=[asdict(p) for p in props])


# --------------------------------------------------------------------------- #
# Operation parsing
# --------------------------------------------------------------------------- #
def _example_blocks(dd: Tag) -> tuple[object, object, str | None]:
    """Extract (request_body_json, response_json, response_raw) from a dd."""
    mode = None
    req = resp = None
    resp_raw = None
    for el in dd.descendants:
        if not isinstance(el, Tag):
            continue
        if el.name in ("p", "strong"):
            t = el.get_text(" ", strip=True).lower()
            if "example request" in t:
                mode = "request"
            elif "example response" in t:
                mode = "response"
        cls = el.get("class") or []
        if "highlight-javascript" in cls or "highlight-json" in cls:
            pre = el.find("pre")
            if not pre:
                continue
            raw = pre.get_text()
            try:
                parsed = json.loads(raw)
            except Exception:  # noqa: BLE001
                parsed = None
            if mode == "request" and req is None:
                req = parsed
            elif mode == "response" and resp is None:
                resp = parsed
                if parsed is None:
                    resp_raw = raw.strip()[:4000]
    return req, resp, resp_raw


def _referenced_objects(dd: Tag, known_objects: set[str]) -> list[str]:
    refs: list[str] = []
    # Only look at prose before the first example block.
    for el in dd.descendants:
        if isinstance(el, Tag):
            cls = el.get("class") or []
            if "highlight-http" in cls or "highlight-javascript" in cls:
                break
            if el.name == "a" and "reference" in cls:
                frag = el.get("href", "").split("#")[-1]
                if frag in known_objects and frag not in refs:
                    refs.append(frag)
    return refs


def _all_object_refs(dd: Tag, known_objects: set[str]) -> list[str]:
    """Every documented-object reference anywhere in the dd, in document order."""
    refs: list[str] = []
    for a in dd.find_all("a", class_="reference"):
        frag = a.get("href", "").split("#")[-1]
        if frag in known_objects and frag not in refs:
            refs.append(frag)
    return refs


def _resolve_response(
    method: str, refs_before: list[str], all_refs: list[str], resp_ex: object
) -> tuple[str, str | None, dict | None]:
    """Decide the result schema for an operation, using only what the docs
    deterministically provide: the example response's `result`, or an object the
    prose links to. Anything else stays 'unknown' — no name-matching guesses.
    Returns (kind, object_name, inferred)."""
    result_val = resp_ex.get("result") if isinstance(resp_ex, dict) else None
    has_result_key = isinstance(resp_ex, dict) and "result" in resp_ex
    ref = refs_before[0] if refs_before else (all_refs[0] if all_refs else None)

    if isinstance(result_val, list):
        if ref:
            return "array", ref, None
        item = infer_schema(result_val[0]) if result_val else {}
        return "array", None, {"type": "array", "items": item}
    if isinstance(result_val, dict):
        if ref:
            return "object", ref, None
        return "object", None, infer_schema(result_val)
    if isinstance(result_val, (str, int, float, bool)):
        return "primitive", None, infer_schema(result_val)
    # result key present but null/empty, or an action with no result body
    if has_result_key or method in ("post", "put", "delete"):
        if ref and not has_result_key:
            return "object", ref, None
        return "none", None, None
    # No example: a linked object reference if the docs gave one, else unknown.
    if ref:
        return "object", ref, None
    return "unknown", None, None


def _query_from_example(dd: Tag) -> list[str]:
    http = dd.find("div", class_="highlight-http")
    if not http:
        return []
    first_line = http.get_text("\n").strip().splitlines()[0] if http.get_text().strip() else ""
    m = re.search(r"\?(\S+)\s", first_line + " ")
    if not m:
        return []
    qs = m.group(1)
    return [kv.split("=")[0] for kv in qs.split("&") if kv]


def parse_operation(dt: Tag, inv_op, known_objects: set[str]) -> Operation:
    dd = dt.find_next_sibling("dd")
    path_doc = inv_op.path
    path, vprefix = strip_version(path_doc)
    refs = _referenced_objects(dd, known_objects) if dd else []
    summary = ""
    description = ""
    if dd:
        # Collect prose <p> up to the first example block, skipping the example
        # labels themselves ("Example request:", an HTTP line, ...) so they never
        # become the operation's summary/description.
        prose = []
        for p in dd.find_all("p", recursive=False):
            t = _clean_text(p)
            low = t.lower()
            if low.startswith("example") or low.startswith("http/") or "http/1.1" in low:
                break
            if t:
                prose.append(t)
        summary = prose[0] if prose else ""
        description = " ".join(prose).strip()
    req_ex, resp_ex, resp_raw = _example_blocks(dd) if dd else (None, None, None)

    # Templated multi-endpoint paths e.g. /api/v4/[number,address,url,email]/
    alts: list[str] = []
    m = re.search(r"\[([^\]]+)\]", path)
    if m and "," in m.group(1):
        alts = [path.replace(m.group(0), opt.strip()) for opt in m.group(1).split(",")]

    method = inv_op.method
    all_refs = _all_object_refs(dd, known_objects) if dd else []
    kind, response_object, inferred = _resolve_response(method, refs, all_refs, resp_ex)

    # Request body object: prefer an object confirmed by the example request body.
    request_object = None
    if method in ("put", "post"):
        if isinstance(req_ex, dict) and refs:
            request_object = refs[0]
        elif refs:
            request_object = refs[0]

    return Operation(
        operation_id=operation_id(method, path),
        method=method,
        path=path,
        path_doc=path_doc,
        doc_version_prefix=vprefix,
        page=inv_op.page,
        anchor=inv_op.anchor,
        summary=summary,
        description=description,
        path_params=path_param_names(path),
        query_params=_query_from_example(dd) if dd else [],
        referenced_objects=all_refs,
        request_object=request_object,
        response_object=response_object,
        response_kind=kind,
        response_inferred_schema=inferred,
        templated_alternatives=alts,
        example_request=req_ex,
        example_response=resp_ex,
        example_response_raw=resp_raw,
    )


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def build_ir(inv: Inventory) -> dict:
    known_objects = {o.name for o in inv.objects}
    # group inventory operations by page
    ops_by_page: dict[str, list] = {}
    for op in inv.operations:
        ops_by_page.setdefault(op.page, []).append(op)

    operations: list[dict] = []
    schemas: dict[str, dict] = {}
    sections: dict[str, dict] = {}

    # Objects/ops with an empty page in the inventory live on the root index page
    # (e.g. APIResponse, the WebSocket* protocol objects).
    pages = sorted({o.page for o in inv.operations} | {o.page for o in inv.objects})
    for page in pages:
        html_name = page if page else "index"
        html_file = HTML_DIR / f"{html_name}.html"
        if not html_file.exists():
            continue
        soup = BeautifulSoup(html_file.read_text(), "html.parser")
        title_tag = soup.find("h1")
        sections[page or "index"] = {
            "slug": page or "index",
            "title": (_clean_text(title_tag).rstrip("¶").strip() if title_tag else page),
            "error_codes": extract_error_codes(soup),
        }

        # operations
        for inv_op in ops_by_page.get(page, []):
            dt = soup.find("dt", id=inv_op.anchor)
            if dt is None:
                # anchor not found in HTML — keep a stub from inventory so nothing is lost
                path, vprefix = strip_version(inv_op.path)
                operations.append(
                    asdict(
                        Operation(
                            operation_id=operation_id(inv_op.method, path),
                            method=inv_op.method,
                            path=path,
                            path_doc=inv_op.path,
                            doc_version_prefix=vprefix,
                            page=page,
                            anchor=inv_op.anchor,
                            summary="(anchor not found in HTML)",
                            path_params=path_param_names(path),
                        )
                    )
                )
                continue
            operations.append(asdict(parse_operation(dt, inv_op, known_objects)))

        # objects (an object may be documented across several dl.object blocks,
        # e.g. VPNClientConfig base fields + variant fields — merge their properties)
        for dl in soup.select("dl.object"):
            schema = parse_object(dl, page, known_objects)
            if not schema.name:
                continue
            sd = asdict(schema)
            if schema.name in schemas:
                existing = schemas[schema.name]
                have = {p["name"] for p in existing["properties"]}
                for p in sd["properties"]:
                    if p["name"] not in have:
                        existing["properties"].append(p)
                        have.add(p["name"])
                if not existing.get("description") and sd.get("description"):
                    existing["description"] = sd["description"]
            else:
                schemas[schema.name] = sd

    operations.sort(key=lambda o: (o["page"], o["path"], o["method"]))
    return {
        "doc_version": inv.version,
        "project": inv.project,
        "counts": {
            "operations": len(operations),
            "schemas": len(schemas),
            "properties": sum(len(s["properties"]) for s in schemas.values()),
            "error_codes": sum(len(s["error_codes"]) for s in sections.values()),
        },
        "sections": sections,
        "operations": operations,
        "schemas": schemas,
    }


def main() -> int:
    inv = load_inventory()
    ir = build_ir(inv)
    write_json(IR_PATH, ir)

    from collections import Counter

    print(f"doc_version={ir['doc_version']}")
    print(f"operations: parsed={ir['counts']['operations']} inventory={len(inv.operations)}")
    print(f"schemas:    parsed={ir['counts']['schemas']} inventory={len(inv.objects)}")
    print(f"properties: parsed={ir['counts']['properties']} inventory={len(inv.properties)}")

    # completeness check vs the authoritative inventory
    inv_props = {(p.object, p.path) for p in inv.properties}
    parsed_props = {(name, p["name"]) for name, s in ir["schemas"].items() for p in s["properties"]}
    missing_objs = [o.name for o in inv.objects if o.name not in ir["schemas"]]
    missing_props = sorted(inv_props - parsed_props)
    print(f"MISSING objects:    {len(missing_objs)} {missing_objs if missing_objs else ''}")
    print(f"MISSING properties: {len(missing_props)} {missing_props[:10] if missing_props else ''}")

    # response resolution coverage
    kinds = Counter(o["response_kind"] for o in ir["operations"])
    unknown = [o["operation_id"] for o in ir["operations"] if o["response_kind"] == "unknown"]
    print(f"response_kind: {dict(kinds)}")
    print(f"UNKNOWN response ops: {len(unknown)}")
    for oid in unknown:
        print("   ?", oid)

    # unresolved object refs
    refs = set()
    for s in ir["schemas"].values():
        for p in s["properties"]:
            t = p["type"]
            for tt in (t, t.get("items") or {}):
                if isinstance(tt, dict) and tt.get("ref"):
                    refs.add(tt["ref"])
    for o in ir["operations"]:
        if o["response_object"]:
            refs.add(o["response_object"])
        if o["request_object"]:
            refs.add(o["request_object"])
    unresolved = sorted(r for r in refs if r not in ir["schemas"])
    print(
        f"object refs used: {len(refs)}; unresolved (no schema): {len(unresolved)} {unresolved[:20]}"
    )
    print(f"IR -> {IR_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
