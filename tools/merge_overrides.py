"""Merge the per-section AI-audit fragments into spec/overrides.json.

This is a ONE-TIME / occasional dev step (run after `tools/` audit agents write
tools/cache/enrichment/<slug>.json). The resulting overrides.json is committed
and treated as static input by the deterministic build — CI never runs AI.

    python -m tools.merge_overrides
"""

from __future__ import annotations

import json
from pathlib import Path

from .common import IR_PATH, SPEC_DIR, read_json, write_json

ENRICH_DIR = Path(__file__).resolve().parent / "cache" / "enrichment"
OVERRIDES_PATH = SPEC_DIR / "overrides.json"

VALID_PERMISSIONS = {
    "settings",
    "contacts",
    "calls",
    "explorer",
    "downloader",
    "parental",
    "pvr",
    "camera",
    "home",
    "profile",
    "player",
    "tv",
    "vm",
    "wdo",
}
VALID_KINDS = {"object", "array", "primitive", "none", "inline"}
ALIASES = {"VPNClientConfigPPTP": "VPNClientConfig"}


def main() -> int:
    ir = read_json(IR_PATH)
    known_ops = {o["operation_id"]: o for o in ir["operations"]}
    known_schemas = set(ir["schemas"])

    def valid_ref(ref):
        if not ref:
            return None
        ref = ALIASES.get(ref, ref)
        return ref if ref in known_schemas else None

    operations: dict[str, dict] = {}
    stats = {"fragments": 0, "ops": 0, "unknown_resolved": 0, "dropped_refs": 0, "unknown_ops": 0}
    baseline_unknown = {
        o["operation_id"] for o in ir["operations"] if o["response_kind"] == "unknown"
    }

    for frag_path in sorted(ENRICH_DIR.glob("*.json")):
        if frag_path.name.startswith("_"):
            continue
        try:
            frag = json.loads(frag_path.read_text())
        except json.JSONDecodeError as exc:
            print(f"  ! {frag_path.name}: invalid JSON ({exc}); skipped")
            continue
        stats["fragments"] += 1
        for op in frag.get("operations", []):
            op_id = op.get("operation_id")
            if op_id not in known_ops:
                stats["unknown_ops"] += 1
                continue
            entry: dict = {}

            resp = op.get("response") or {}
            kind = resp.get("kind")
            if kind in VALID_KINDS:
                ref = valid_ref(resp.get("ref"))
                if resp.get("ref") and ref is None:
                    stats["dropped_refs"] += 1
                entry["response"] = {"kind": kind, "ref": ref}
                if op_id in baseline_unknown and kind != "unknown":
                    stats["unknown_resolved"] += 1

            req = op.get("request") or {}
            if req.get("kind") in VALID_KINDS:
                entry["request"] = {"kind": req["kind"], "ref": valid_ref(req.get("ref"))}

            perm = op.get("permission")
            if perm in VALID_PERMISSIONS:
                entry["permission"] = perm

            params = []
            for p in op.get("parameters", []) or []:
                if p.get("name") and p.get("in") in ("path", "query"):
                    params.append(
                        {
                            "name": p["name"],
                            "in": p["in"],
                            "type": p.get("type", "string"),
                            "required": bool(p.get("required", p["in"] == "path")),
                            "description": p.get("description", ""),
                        }
                    )
            if params:
                entry["parameters"] = params

            if entry:
                operations[op_id] = entry
                stats["ops"] += 1

    overrides = {
        "_comment": (
            "Generated once by the AI audit (tools/merge_overrides + the audit workflow) "
            "and committed as static data. The deterministic build merges this; CI never runs AI."
        ),
        "_source": "tools/cache/enrichment/*.json",
        "aliases": ALIASES,
        "operations": operations,
    }
    write_json(OVERRIDES_PATH, overrides)

    still_unknown = sorted(baseline_unknown - set(operations.keys()))
    print(f"fragments merged: {stats['fragments']}/29")
    print(f"operations with overrides: {stats['ops']}")
    print(f"baseline unknowns resolved: {stats['unknown_resolved']}/{len(baseline_unknown)}")
    print(
        f"invalid refs dropped: {stats['dropped_refs']}; unknown op_ids ignored: {stats['unknown_ops']}"
    )
    if still_unknown:
        print(f"STILL UNKNOWN ({len(still_unknown)}): {still_unknown}")
    print(f"-> {OVERRIDES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
