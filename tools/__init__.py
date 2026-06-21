"""Regeneration pipeline for freebox-mcp.

Turns the official Freebox OS Sphinx documentation (https://dev.freebox.fr/sdk/os/)
into an OpenAPI 3.1 document that drives the MCP server.

Stages:
    scrape       download all section HTML + objects.inv  -> tools/cache/
    inventory    decode objects.inv                       -> authoritative index
    parse        httpdomain/jsondomain HTML -> IR          -> tools/cache/ir.json
    build_openapi  IR -> spec/freebox-openapi.json

Run the whole thing with `python -m tools.build`.
"""
