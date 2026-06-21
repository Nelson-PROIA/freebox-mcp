"""Render each cached section into agent-friendly inputs for the verify workflow.

For every section we emit:
  tools/cache/sections/<slug>.md    full doc body as faithful markdown (incl. tables)
  tools/cache/sections/<slug>.json  the IR slice (operations + schemas for that page)

The markdown keeps everything an LLM verifier needs that the IR can't capture:
section-level error-code tables, permission notes, and per-endpoint prose.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup, NavigableString, Tag

from .common import CACHE_DIR, HTML_DIR, IR_PATH, write_json

SECTIONS_DIR = CACHE_DIR / "sections"


def _inline(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if node.name == "code":
        return f"`{node.get_text()}`"
    if node.name in ("strong", "b"):
        return f"**{node.get_text()}**"
    if node.name in ("em", "i"):
        return f"_{node.get_text()}_"
    if node.name == "a":
        txt = node.get_text()
        href = node.get("href", "")
        if href.startswith("#"):
            return f"{txt}"
        return f"[{txt}]({href})"
    return "".join(_inline(c) for c in node.children)


def _table_md(table: Tag) -> str:
    rows = []
    headers = [th.get_text(" ", strip=True) for th in table.select("thead th")]
    if headers:
        rows.append("| " + " | ".join(headers) + " |")
        rows.append("| " + " | ".join("---" for _ in headers) + " |")
    for tr in table.select("tbody tr"):
        cells = [
            re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all(("td", "th"))
        ]
        if cells:
            rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _to_md(node: Tag, depth: int = 0, out: list[str] | None = None) -> list[str]:
    out = out if out is not None else []
    for child in node.children:
        if isinstance(child, NavigableString):
            continue
        name = child.name
        cls = child.get("class") or []
        if name in ("h1", "h2", "h3", "h4", "h5"):
            level = int(name[1])
            out.append(f"\n{'#' * level} {child.get_text(' ', strip=True).rstrip('¶')}\n")
        elif name == "p":
            txt = re.sub(r"\s+", " ", _inline(child)).strip()
            if txt:
                out.append(txt + "\n")
        elif name == "table":
            out.append(_table_md(child) + "\n")
        elif name in ("ul", "ol"):
            for li in child.find_all("li", recursive=False):
                item = re.sub(r"\s+", " ", _inline(li)).strip()
                out.append(f"- {item}")
            out.append("")
        elif name == "pre":
            out.append("```\n" + child.get_text() + "\n```\n")
        elif "highlight" in " ".join(cls):
            pre = child.find("pre")
            if pre:
                out.append("```\n" + pre.get_text() + "\n```\n")
        elif name == "dl":
            kind = "object" if "object" in cls else "property" if "property" in cls else "def"
            dt = child.find("dt", recursive=False)
            dd = child.find("dd", recursive=False)
            if dt:
                term = re.sub(r"\s+", " ", dt.get_text(" ", strip=True)).rstrip("¶").strip()
                prefix = {"object": "**object** ", "property": "- ", "def": "**"}.get(kind, "")
                suffix = "**" if kind == "def" else ""
                out.append(f"{prefix}{term}{suffix}")
            if dd:
                _to_md(dd, depth + 1, out)
        elif name == "div":
            _to_md(child, depth, out)
        else:
            _to_md(child, depth, out)
    return out


def render_section(slug: str, html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("div", attrs={"role": "main"}) or soup.find("div", class_="body") or soup
    md = _to_md(body)
    text = "\n".join(md)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def main() -> int:
    SECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    ir = json.loads(IR_PATH.read_text())
    ops_by_page: dict[str, list] = {}
    for o in ir["operations"]:
        ops_by_page.setdefault(o["page"], []).append(o)
    schemas_by_page: dict[str, dict] = {}
    for name, s in ir["schemas"].items():
        schemas_by_page.setdefault(s["page"], {})[name] = s

    pages = sorted(set(ops_by_page) | set(schemas_by_page))
    for slug in pages:
        html_name = slug if slug else "index"
        html_file = HTML_DIR / f"{html_name}.html"
        if not html_file.exists():
            continue
        (SECTIONS_DIR / f"{html_name}.md").write_text(render_section(slug, html_file.read_text()))
        write_json(
            SECTIONS_DIR / f"{html_name}.json",
            {
                "slug": slug or "index",
                "operations": ops_by_page.get(slug, []),
                "schemas": schemas_by_page.get(slug, {}),
            },
        )
    print(f"rendered {len(pages)} sections -> {SECTIONS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
