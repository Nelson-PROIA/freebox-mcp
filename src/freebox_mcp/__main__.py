"""freebox-mcp command line.

freebox-mcp                 run the MCP server over stdio (default)
freebox-mcp --http          run over streamable-HTTP (--host/--port)
freebox-mcp authorize       register the app (press the button on the box)
freebox-mcp login           open a session and print granted permissions
freebox-mcp discover        print discovery info and the chosen transport
freebox-mcp tools           list the generated MCP tools
freebox-mcp call OP [JSON]  invoke one operation (for testing)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

import httpx

from . import __version__
from .auth import (
    BoxCredentials,
    FreeboxError,
    TokenStore,
    request_authorization,
    wait_for_authorization,
)
from .client import build_client, build_session_manager
from .config import load_settings
from .discovery import choose_endpoint
from .server import create_server
from .spec import load_spec


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def cmd_discover(args) -> int:
    settings = load_settings()
    endpoint = choose_endpoint(settings)
    d = endpoint.discovery
    print(
        json.dumps(
            {
                "box_model": d.box_model_name,
                "api_version": d.api_version,
                "api_major": d.api_major,
                "uid": d.uid,
                "api_domain": d.api_domain,
                "https_port": d.https_port,
                "https_available": d.https_available,
                "chosen_base_url": endpoint.base_url,
                "api_path_prefix": endpoint.api_path_prefix,
                "transport": "https" if endpoint.secure else "http",
            },
            indent=2,
        )
    )
    return 0


def cmd_authorize(args) -> int:
    settings = load_settings()
    endpoint = choose_endpoint(settings)
    from .tls import freebox_ssl_context

    verify = freebox_ssl_context(str(settings.cert_bundle)) if endpoint.secure else True
    with httpx.Client(
        base_url=endpoint.base_url, verify=verify, timeout=settings.request_timeout
    ) as http:
        req = request_authorization(
            http,
            endpoint.api_path_prefix,
            settings.app_id,
            settings.app_name,
            settings.app_version,
            settings.device_name,
        )
        print(">>> Press the button (►) on the front panel of the Freebox to grant access.")
        print(
            f"    app_id={settings.app_id}  track_id={req.track_id}  (waiting up to {args.timeout}s)"
        )
        status = wait_for_authorization(
            http, endpoint.api_path_prefix, req.track_id, timeout=args.timeout
        )
    if status == "granted":
        store = TokenStore(settings.credentials_path)
        store.set(
            endpoint.discovery.uid,
            BoxCredentials(
                app_id=settings.app_id,
                app_token=req.app_token,
                track_id=req.track_id,
                box_model=endpoint.discovery.box_model_name,
            ),
        )
        print(f"✓ Authorized. Credentials saved to {settings.credentials_path} (0600).")
        return 0
    print(f"✗ Authorization {status}. Re-run and press the button in time.", file=sys.stderr)
    return 1


async def _login() -> dict:
    settings = load_settings()
    endpoint = choose_endpoint(settings)
    store = TokenStore(settings.credentials_path)
    session = build_session_manager(settings, endpoint, store)
    await session.refresh()
    return {
        "box": endpoint.discovery.box_model_name,
        "transport": "https" if endpoint.secure else "http",
        "permissions": session.permissions,
    }


def cmd_login(args) -> int:
    try:
        info = asyncio.run(_login())
    except FreeboxError as e:
        print(f"✗ {e} (error_code={e.error_code})", file=sys.stderr)
        return 1
    print(json.dumps(info, indent=2))
    return 0


def _find_operation(spec: dict, op_id: str):
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method in ("get", "post", "put", "delete") and op.get("operationId") == op_id:
                return method, path, op
    return None


async def _call(op_id: str, payload: dict | None, params: dict) -> object:
    settings = load_settings()
    spec = load_spec()
    found = _find_operation(spec, op_id)
    if not found:
        raise SystemExit(f"unknown operationId: {op_id}")
    method, path, op = found
    # substitute path params from params/payload
    for name in [p["name"] for p in op.get("parameters", []) if p["in"] == "path"]:
        if name not in params:
            raise SystemExit(f"missing path param: {name}")
        path = path.replace("{" + name + "}", str(params.pop(name)))
    endpoint = choose_endpoint(settings)
    store = TokenStore(settings.credentials_path)
    session = build_session_manager(settings, endpoint, store)
    client = build_client(settings, endpoint, session)
    try:
        r = await client.request(method.upper(), path, params=params or None, json=payload)
        try:
            return r.json()
        except Exception:  # noqa: BLE001
            return {"status_code": r.status_code, "text": r.text[:2000]}
    finally:
        await client.aclose()


def cmd_call(args) -> int:
    payload = json.loads(args.data) if args.data else None
    params = dict(kv.split("=", 1) for kv in args.param)
    result = asyncio.run(_call(args.operation, payload, params))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_tools(args) -> int:
    async def _list():
        mcp = create_server()
        tools = await mcp.list_tools()
        return sorted(t.name for t in tools)

    names = asyncio.run(_list())
    for n in names:
        print(n)
    print(f"\n{len(names)} tools", file=sys.stderr)
    return 0


def cmd_sections(args) -> int:
    """List the API sections (tool groups) — derived from the generated spec, not
    hardcoded. Use any subset as FREEBOX_SECTIONS to scope the server."""
    from collections import Counter

    spec = load_spec()
    counts: Counter[str] = Counter()
    for item in spec["paths"].values():
        for method, op in item.items():
            if method in ("get", "post", "put", "delete"):
                for tag in op.get("tags", []):
                    if tag == "login":
                        continue  # auth handshake, not an exposed tool group
                    counts[tag] += 1
    titles = {t["name"]: t.get("description", "") for t in spec.get("tags", [])}
    for name in sorted(counts):
        print(f"{name:16} {counts[name]:3} tools   {titles.get(name, '')}")
    print(
        f"\n{len(counts)} sections, {sum(counts.values())} tools. "
        f"Scope with e.g. FREEBOX_SECTIONS={','.join(sorted(counts)[:3])}",
        file=sys.stderr,
    )
    return 0


def cmd_run(args) -> int:
    mcp = create_server()
    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="freebox-mcp", description="MCP server for the Freebox OS API."
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"freebox-mcp {__version__}")
    p.add_argument(
        "--http", action="store_true", help="serve over streamable-HTTP instead of stdio"
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_run)

    sub = p.add_subparsers()
    sub.add_parser("discover", help="print discovery + transport").set_defaults(func=cmd_discover)
    a = sub.add_parser("authorize", help="register the app (press the button)")
    a.add_argument("--timeout", type=int, default=90)
    a.set_defaults(func=cmd_authorize)
    sub.add_parser("login", help="open a session, print permissions").set_defaults(func=cmd_login)
    sub.add_parser("tools", help="list generated tools").set_defaults(func=cmd_tools)
    sub.add_parser(
        "sections", help="list API sections (FREEBOX_SECTIONS values), derived from the spec"
    ).set_defaults(func=cmd_sections)
    c = sub.add_parser("call", help="invoke one operation")
    c.add_argument("operation")
    c.add_argument("data", nargs="?", help="JSON request body")
    c.add_argument("-p", "--param", action="append", default=[], help="path/query param key=value")
    c.set_defaults(func=cmd_call)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
