"""Decode the Sphinx ``objects.inv`` inventory.

This is the *authoritative* API surface: every HTTP operation, every documented
JSON object, and every property, each with the page + anchor where its full
description lives. The HTML parser later fills in the details; the inventory
guarantees we never miss an operation or schema.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import asdict, dataclass

from .common import INVENTORY_PATH

# A decompressed inventory line:
#   name  domain:role  priority  uri  dispname
_LINE = re.compile(
    r"^(?P<name>.+?)\s+(?P<role>\S+)\s+(?P<prio>-?\d+)\s+(?P<uri>\S*)\s+(?P<disp>.*)$"
)


@dataclass
class Operation:
    method: str  # get/post/put/delete
    path: str  # as documented, e.g. /api/v2/wifi/ap/{id}
    page: str  # section slug, e.g. wifi
    anchor: str  # html anchor, e.g. get--api-v2-wifi-ap-id


@dataclass
class JsonObject:
    name: str
    page: str
    anchor: str


@dataclass
class JsonProperty:
    object: str  # owning object name (before first dot)
    path: str  # full dotted property path after the object, e.g. "lan_config.ip"
    name: str  # full dotted name as documented, e.g. Object.lan_config.ip
    page: str
    anchor: str


@dataclass
class Inventory:
    project: str
    version: str
    operations: list[Operation]
    objects: list[JsonObject]
    properties: list[JsonProperty]

    def as_dict(self) -> dict:
        return {
            "project": self.project,
            "version": self.version,
            "operations": [asdict(o) for o in self.operations],
            "objects": [asdict(o) for o in self.objects],
            "properties": [asdict(p) for p in self.properties],
        }


def _split_uri(uri: str, name: str) -> tuple[str, str]:
    """Return (page_slug, anchor) from a Sphinx inventory uri like 'wifi/#anchor'."""
    if uri.endswith("$"):
        uri = uri[:-1] + name
    page, _, anchor = uri.partition("#")
    page = page.rstrip("/")
    return page, anchor


def parse_inventory(raw: bytes) -> Inventory:
    head, _, _ = raw.partition(b"\n# The remainder")
    header_lines = head.split(b"\n")
    project = version = "unknown"
    for line in header_lines:
        if line.startswith(b"# Project:"):
            project = line.split(b":", 1)[1].strip().decode("utf-8", "replace")
        elif line.startswith(b"# Version:"):
            version = line.split(b":", 1)[1].strip().decode("utf-8", "replace")

    # The 4 header lines are plain text; the rest is zlib-compressed.
    parts = raw.split(b"\n", 4)
    body = zlib.decompress(parts[4]).decode("utf-8", "replace")

    operations: list[Operation] = []
    objects: list[JsonObject] = []
    properties: list[JsonProperty] = []

    for line in body.splitlines():
        if not line.strip():
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name, role, uri = m["name"], m["role"], m["uri"]
        page, anchor = _split_uri(uri, name)
        domain, _, kind = role.partition(":")

        if domain == "http":
            operations.append(Operation(method=kind, path=name, page=page, anchor=anchor))
        elif domain == "json" and kind == "object":
            objects.append(JsonObject(name=name, page=page, anchor=anchor))
        elif domain == "json" and kind == "property":
            obj, _, prop_path = name.partition(".")
            properties.append(
                JsonProperty(object=obj, path=prop_path, name=name, page=page, anchor=anchor)
            )

    operations.sort(key=lambda o: (o.path, o.method))
    objects.sort(key=lambda o: o.name)
    properties.sort(key=lambda p: p.name)
    return Inventory(project, version, operations, objects, properties)


def load_inventory() -> Inventory:
    return parse_inventory(INVENTORY_PATH.read_bytes())


def main() -> int:
    inv = parse_inventory(INVENTORY_PATH.read_bytes())
    from collections import Counter

    methods = Counter(o.method for o in inv.operations)
    print(f"project={inv.project!r} version={inv.version!r}")
    print(f"operations={len(inv.operations)} {dict(methods)}")
    print(f"objects={len(inv.objects)} properties={len(inv.properties)}")
    pages = Counter(o.page for o in inv.operations)
    print("operations per page:")
    for page, n in sorted(pages.items()):
        print(f"  {page:18} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
