"""Pipeline correctness: inventory decode, IR completeness, OpenAPI validity.

These guard the core promise — every documented operation/object/property is
present, every reference resolves, and the emitted spec is valid OpenAPI 3.1.
"""

from __future__ import annotations

from tools.inventory import load_inventory
from tools.parse import build_ir


def test_inventory_counts():
    inv = load_inventory()
    assert inv.version  # e.g. "9ba63963"
    methods = {}
    for op in inv.operations:
        methods[op.method] = methods.get(op.method, 0) + 1
    assert len(inv.operations) == 220
    assert methods == {"get": 107, "put": 49, "post": 40, "delete": 24}
    assert len(inv.objects) == 117
    assert len(inv.properties) == 814


def test_ir_is_complete():
    """No documented object or property may be dropped by the parser."""
    inv = load_inventory()
    ir = build_ir(inv)
    inv_props = {(p.object, p.path) for p in inv.properties}
    parsed_props = {(n, p["name"]) for n, s in ir["schemas"].items() for p in s["properties"]}
    missing_objs = [o.name for o in inv.objects if o.name not in ir["schemas"]]
    missing_props = inv_props - parsed_props
    assert missing_objs == [], f"objects dropped: {missing_objs}"
    assert missing_props == set(), f"properties dropped: {sorted(missing_props)[:10]}"
    assert ir["counts"]["operations"] == 220
    assert ir["counts"]["error_codes"] > 250


def test_response_kinds_classified():
    ir = build_ir(load_inventory())
    allowed = {"object", "array", "primitive", "none", "unknown"}
    kinds = {o["response_kind"] for o in ir["operations"]}
    assert kinds <= allowed
    # endpoints whose result the docs don't express machine-readably (no linked
    # object, no parseable example) stay honestly untyped — we don't invent a
    # schema for them. This is Free's doc gap, not something we patch.
    unknown = [o for o in ir["operations"] if o["response_kind"] == "unknown"]
    assert len(unknown) <= 20


def test_openapi_is_valid_3_1(spec):
    from openapi_spec_validator import validate

    validate(spec)  # raises on any 3.1 violation
    assert spec["openapi"] == "3.1.0"


def test_every_ref_resolves(spec):
    schemas = set(spec["components"]["schemas"])
    bad = []

    def walk(node, where):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if ref and ref.startswith("#/components/schemas/"):
                if ref.rsplit("/", 1)[-1] not in schemas:
                    bad.append((where, ref))
            for k, v in node.items():
                walk(v, f"{where}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{where}[{i}]")

    walk(spec["paths"], "paths")
    walk(spec["components"]["schemas"], "schemas")
    assert bad == [], f"dangling $refs: {bad[:10]}"


def test_paths_and_security(spec):
    assert all(p.startswith("/") for p in spec["paths"])
    assert "FreeboxSession" in spec["components"]["securitySchemes"]
    # security is declared once, globally — no per-op/per-section tweaks in the spec
    assert spec.get("security") == [{"FreeboxSession": []}]
    assert all(
        "security" not in op
        for item in spec["paths"].values()
        for m, op in item.items()
        if m in ("get", "post", "put", "delete")
    )
    n_ops = sum(
        1 for item in spec["paths"].values() for m in item if m in ("get", "post", "put", "delete")
    )
    assert n_ops == 232
