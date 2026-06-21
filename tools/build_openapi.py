"""Turn the intermediate representation into an OpenAPI 3.1 document.

Pure, deterministic transform: ``tools/cache/ir.json`` -> ``spec/freebox-openapi.json``.
No network, no AI, no curated data. This is the step CI runs on every regeneration.

Design notes
------------
* Freebox wraps every JSON reply in an ``APIResponse`` envelope
  ``{success, result, error_code, msg}``. The server unwraps ``result`` on
  success and raises on failure, so each operation's 200 schema describes the
  *unwrapped* result, while ``APIResponse`` stays documented in components.
* Paths are version-stripped (``/wifi/config/`` not ``/api/v2/wifi/config/``).
  The running server prepends ``/api/v{major}`` from live discovery, so the
  static spec is independent of the box's firmware version.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .common import (
    IR_PATH,
    MANIFEST_PATH,
    OPENAPI_PATH,
    SPEC_META_PATH,
    read_json,
    write_json,
)

# Object reference aliases (doc inconsistencies where a property names a type
# that is documented under a slightly different object name).
DEFAULT_ALIASES = {"VPNClientConfigPPTP": "VPNClientConfig"}

# Deterministic section -> Freebox permission map. The docs don't encode the
# required permission machine-readably, but it is uniform per section, so it is a small
# committed config table. login carries no permission.
SECTION_PERMISSION = {
    "airmedia": "settings",
    "call": "calls",
    "connection": "settings",
    "contacts": "contacts",
    "dhcp": "settings",
    "download": "downloader",
    "download_config": "downloader",
    "download_feeds": "downloader",
    "freeplug": "settings",
    "fs": "explorer",
    "ftp": "settings",
    "igd": "settings",
    "lan": "settings",
    "lcd": "settings",
    "nat": "settings",
    "network_share": "settings",
    "parental": "parental",
    "pvr": "pvr",
    "rrd": "settings",
    "share": "explorer",
    "storage": "settings",
    "switch": "settings",
    "system": "settings",
    "upload": "explorer",
    "upnpav": "settings",
    "vpn": "settings",
    "vpn_client": "settings",
    "wifi": "settings",
}


def _ref(name: str, aliases: dict[str, str]) -> dict:
    target = aliases.get(name, name)
    return {"$ref": f"#/components/schemas/{target}"}


def schema_from_typespec(t: dict, aliases: dict[str, str], known: set[str]) -> dict:
    kind = t.get("kind")
    if kind == "ref":
        ref = t.get("ref")
        if ref and (aliases.get(ref, ref) in known):
            return _ref(ref, aliases)
        return {"type": "object", "additionalProperties": True}
    if kind == "array":
        items = t.get("items") or {}
        sch: dict[str, Any] = {
            "type": "array",
            "items": schema_from_typespec(items, aliases, known),
        }
        if t.get("min_items") is not None:
            sch["minItems"] = t["min_items"]
        if t.get("max_items") is not None:
            sch["maxItems"] = t["max_items"]
        return sch
    if kind == "object":
        return {"type": "object", "additionalProperties": True}
    # primitive
    out: dict[str, Any] = {"type": t.get("json_type", "string")}
    fmt = t.get("format")
    if fmt == "unix-timestamp":
        out["description"] = "Unix timestamp (seconds since epoch)."
    elif fmt in ("ipv4", "ipv6"):
        out["format"] = fmt
    elif fmt == "mac":
        out["format"] = "mac"
    return out


def property_schema(prop: dict, aliases: dict[str, str], known: set[str]) -> dict:
    sch = schema_from_typespec(prop["type"], aliases, known)
    desc_parts = []
    if prop.get("description"):
        desc_parts.append(prop["description"])
    if prop.get("enum"):
        values = [e["value"] for e in prop["enum"]]
        # cast to int if the field is integer-typed and all values look numeric
        if sch.get("type") == "integer" and all(v.lstrip("-").isdigit() for v in values):
            sch["enum"] = [int(v) for v in values]
        else:
            sch["enum"] = values
        labelled = [
            f"`{e['value']}`: {e['description']}" for e in prop["enum"] if e.get("description")
        ]
        if labelled:
            desc_parts.append("Values: " + "; ".join(labelled))
    if desc_parts:
        existing = sch.pop("description", None)
        if existing:
            desc_parts.append(existing)
        sch["description"] = " — ".join(desc_parts)
    if prop.get("readonly"):
        sch["readOnly"] = True
    if prop.get("writeonly"):
        sch["writeOnly"] = True
    return sch


def build_components(ir: dict, aliases: dict[str, str]) -> dict:
    known = set(ir["schemas"])
    schemas: dict[str, Any] = {}
    for name, s in ir["schemas"].items():
        props = {p["name"]: property_schema(p, aliases, known) for p in s["properties"]}
        obj: dict[str, Any] = {"type": "object", "properties": props}
        if s.get("description"):
            obj["description"] = s["description"]
        schemas[name] = obj

    # The universal response envelope.
    schemas.setdefault(
        "APIResponse",
        {
            "type": "object",
            "description": "Standard Freebox response envelope. The server unwraps `result`.",
            "properties": {
                "success": {"type": "boolean"},
                "result": {"description": "Endpoint-specific payload."},
                "error_code": {"type": "string"},
                "msg": {"type": "string"},
                "uid": {"type": "string"},
            },
            "required": ["success"],
        },
    )
    return schemas


def result_schema(op: dict, aliases: dict[str, str], known: set[str]) -> dict | None:
    """The *unwrapped* result schema for an operation's 200 response."""
    kind = op.get("response_kind")
    ref = op.get("response_object")
    inferred = op.get("response_inferred_schema")
    if kind == "object" and ref:
        return _ref(ref, aliases) if aliases.get(ref, ref) in known else {"type": "object"}
    if kind == "array":
        if ref:
            items = _ref(ref, aliases) if aliases.get(ref, ref) in known else {"type": "object"}
            return {"type": "array", "items": items}
        return inferred or {"type": "array", "items": {}}
    if kind in ("object", "primitive") and inferred:
        return inferred
    if kind == "none":
        return None
    # unknown -> permissive
    return {"description": "Result payload (schema not documented)."}


def _resource_words(path: str) -> str:
    segs = [s for s in path.strip("/").split("/") if s and not s.startswith("{")]
    return " ".join(segs).replace("_", " ").strip()


def synth_summary(op: dict, kind: str | None, ref: str | None) -> str:
    """A readable summary when the docs gave no prose (avoids 'Example request :')."""
    method = op["method"].upper()
    resource = _resource_words(op["path"]) or op["path"].strip("/")
    if method == "GET":
        lead = "List" if kind == "array" else "Get"
        return f"{lead} {resource}".strip()
    # Don't guess create/update/delete semantics for non-GET (Freebox uses POST for
    # queries too, e.g. rrd) — name the resource unambiguously instead.
    return f"{method} /{op['path'].strip('/')}/".replace("//", "/")


def synth_description(op: dict, kind: str | None, ref: str | None) -> str:
    if op["method"] == "get" and ref:
        return f"Returns {'a list of ' if kind == 'array' else ''}`{ref}`."
    return ""


def operation_object(op: dict, ir: dict, aliases: dict[str, str]) -> dict:
    known = set(ir["schemas"])
    page = op["page"]
    section = ir.get("sections", {}).get(page, {})
    permission = SECTION_PERMISSION.get(page)
    is_login = page == "login"

    parameters = []
    seen_params = set()
    for name in op.get("path_params", []):
        seen_params.add(name)
        parameters.append(
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": {"type": "integer" if name.endswith("id") else "string"},
            }
        )
    for name in op.get("query_params", []):
        if name in seen_params:
            continue
        seen_params.add(name)
        parameters.append(
            {"name": name, "in": "query", "required": False, "schema": {"type": "string"}}
        )

    # request body
    request_body = None
    req_ref = op.get("request_object")
    if req_ref and (aliases.get(req_ref, req_ref) in known):
        request_body = {
            "required": True,
            "content": {"application/json": {"schema": _ref(req_ref, aliases)}},
        }
    elif op["method"] in ("post", "put") and isinstance(op.get("example_request"), (dict, list)):
        request_body = {
            "content": {
                "application/json": {
                    "schema": {"type": "object", "additionalProperties": True},
                    "example": op["example_request"],
                }
            }
        }

    # responses
    res = result_schema(op, aliases, known)
    ok_content = {"application/json": {"schema": res}} if res is not None else None
    responses: dict[str, Any] = {
        "200": {
            "description": "Success. Body is the unwrapped `result` of the Freebox APIResponse.",
            **({"content": ok_content} if ok_content else {}),
        },
        "default": {
            "description": "Freebox error (APIResponse with success=false).",
            "content": {"application/json": {"schema": _ref("APIResponse", aliases)}},
        },
    }

    res_kind = op.get("response_kind")
    res_ref = op.get("response_object")
    summary = op.get("summary") or synth_summary(op, res_kind, res_ref)
    lead = op.get("description") or synth_description(op, res_kind, res_ref)

    desc_parts = [lead or summary]
    if permission:
        desc_parts.append(f"Requires the `{permission}` permission.")
    err_codes = section.get("error_codes", [])
    if err_codes:
        desc_parts.append("Error codes: " + ", ".join(f"`{e['code']}`" for e in err_codes[:30]))

    obj: dict[str, Any] = {
        "operationId": op["operation_id"],
        "summary": summary[:120],
        "description": "\n\n".join(p for p in desc_parts if p).strip(),
        "tags": [page],
        "responses": responses,
        "security": [] if is_login else [{"FreeboxSession": []}],
        "x-freebox": {
            "page": page,
            "doc_anchor": op.get("anchor"),
            "doc_version_prefix": op.get("doc_version_prefix"),
            "permission": permission,
            "envelope": True,
            "error_codes": err_codes,
        },
    }
    if parameters:
        obj["parameters"] = parameters
    if request_body:
        obj["requestBody"] = request_body
    return obj


def expand_paths(ir: dict, aliases: dict[str, str]) -> dict:
    paths: dict[str, Any] = {}
    for op in ir["operations"]:
        targets = op.get("templated_alternatives") or [op["path"]]
        for idx, raw_path in enumerate(targets):
            path = "/" + raw_path.lstrip("/")
            opobj = operation_object(op, ir, aliases)
            if len(targets) > 1:
                # disambiguate operationId per expanded alternative
                suffix = raw_path.strip("/").split("/")[0]
                opobj = dict(opobj)
                opobj["operationId"] = (
                    f"{op['method']}_{suffix}_{op['operation_id'].split('_', 1)[-1]}"
                )
            paths.setdefault(path, {})[op["method"]] = opobj
    return paths


def build_openapi(ir: dict, version: str) -> dict:
    known = set(ir["schemas"])
    aliases = {k: v for k, v in DEFAULT_ALIASES.items() if v in known}
    components_schemas = build_components(ir, aliases)

    tags = [
        {"name": s["slug"], "description": s.get("title", s["slug"])}
        for s in sorted(ir.get("sections", {}).values(), key=lambda s: s["slug"])
        if s["slug"] != "index"
    ]

    spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "Freebox OS API",
            "version": version,
            "summary": "Local API of the Freebox Server gateway.",
            "description": (
                "Generated from the official Freebox OS documentation "
                "(https://dev.freebox.fr/sdk/os/). Paths are version-stripped; the "
                "server prepends `/api/v{major}` from live discovery. Every reply is "
                "wrapped in an APIResponse envelope which the server unwraps to `result`."
            ),
            "license": {"name": "MIT", "identifier": "MIT"},
            "x-freebox-doc-version": ir["doc_version"],
            "x-freebox-doc-source": "https://dev.freebox.fr/sdk/os/",
        },
        "servers": [
            {
                "url": "https://{api_domain}:{https_port}/api/{api_major}",
                "description": "Discovered at runtime from http://mafreebox.freebox.fr/api_version",
                "variables": {
                    "api_domain": {"default": "mafreebox.freebox.fr"},
                    "https_port": {"default": "443"},
                    "api_major": {"default": "v8"},
                },
            }
        ],
        "security": [{"FreeboxSession": []}],
        "tags": tags,
        "paths": expand_paths(ir, aliases),
        "components": {
            "securitySchemes": {
                "FreeboxSession": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Fbx-App-Auth",
                    "description": "Session token from POST /login/session/ (challenge + HMAC-SHA1).",
                }
            },
            "schemas": components_schemas,
        },
    }
    return spec


def main() -> int:
    ir = read_json(IR_PATH)
    version = os.environ.get("FREEBOX_MCP_SPEC_VERSION") or ir["doc_version"]

    spec = build_openapi(ir, version)
    write_json(OPENAPI_PATH, spec)

    manifest = read_json(MANIFEST_PATH) if Path(MANIFEST_PATH).exists() else {}
    n_ops = sum(
        len([m for m in v if m in ("get", "post", "put", "delete")]) for v in spec["paths"].values()
    )
    untyped = sum(
        1
        for item in spec["paths"].values()
        for m, op in item.items()
        if m in ("get", "post", "put", "delete")
        and op["responses"]["200"]
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("description", "")
        .startswith("Result payload")
    )
    meta = {
        "doc_version": ir["doc_version"],
        "doc_source": "https://dev.freebox.fr/sdk/os/",
        "scraped_at": manifest.get("scraped_at"),
        "spec_version": version,
        "counts": {
            "paths": len(spec["paths"]),
            "operations": n_ops,
            "schemas": len(spec["components"]["schemas"]),
            "error_codes": ir["counts"].get("error_codes", 0),
            "untyped_results": untyped,
        },
    }
    write_json(SPEC_META_PATH, meta)

    print(f"OpenAPI {spec['openapi']}  version={version}  doc={ir['doc_version']}")
    print(
        f"paths={meta['counts']['paths']} operations={n_ops} "
        f"schemas={meta['counts']['schemas']} error_codes={meta['counts']['error_codes']} "
        f"untyped_results={untyped}"
    )
    print(f"-> {OPENAPI_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
