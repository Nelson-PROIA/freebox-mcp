# freebox-mcp

A **spec-driven** [Model Context Protocol](https://modelcontextprotocol.io) server for the
**Freebox OS API** — exposing the *entire* local API of your Freebox Server to any MCP client
(Claude, etc.) as ready-to-call tools.

Every tool is generated from an **OpenAPI 3.1** document that is itself **auto-generated from the
official Freebox documentation** (<https://dev.freebox.fr/sdk/os/>). When Free ships a new API
version, a weekly job regenerates the spec and ships a release — **no hand-written tool code to
maintain**.

### Three bricks, one contract

```
  ┌── 1. SCRAPER ──┐   ┌──── 2. GENERATOR ────┐   ┌─── 3. GENERATED CLIENT ───┐
  official docs  ─►   tools/cache  ─────────►   spec/freebox-openapi.json ─►  FastMCP.from_openapi() ─► ~230 MCP tools
  (dev.freebox.fr)    (html + objects.inv)      (+ committed overrides.json)   (raw output — no edits)
```

**The generated client is the verbatim output of `FastMCP.from_openapi(spec)`** — no tool is
hand-added, edited, pre-processed, or post-processed. A CI test (`test_tools_are_raw_generated_output`)
enforces it: every exposed tool must be an `operationId` from the generated spec, or the build fails.

The only hand-written code is the authenticated transport the generated client *runs on*
(discovery · HMAC session · TLS · envelope unwrap) — things no API spec can express. It is generic,
never edited per-endpoint, and app registration / login live in the CLI, not as injected tools.

- **Exhaustive** — 220 documented operations across 29 sections (wifi, lan, connection, calls,
  contacts, downloads, fs, nat, dhcp, vpn server + client, pvr, parental control, airmedia,
  system, …) ⇒ ~230 MCP tools.
- **Self-maintaining** — the spec regenerates from the docs deterministically; CI does it weekly
  and auto-releases on change.
- **Secure** — app-token never leaves your machine, HMAC-SHA1 sessions, TLS verified against the
  bundled Freebox root CAs, `0600` credential store. See [SECURITY.md](SECURITY.md).

## Quick start

```bash
# 1. Authorize the app on your Freebox (one time — press the button on the box).
uvx freebox-mcp authorize

# 2. Point your MCP client at it (stdio).
uvx freebox-mcp
```

`authorize` is a **one-time** physical confirmation (Freebox anti-hijack design). After it, the
token is saved and every later session opens automatically — you never touch the box again.

### MCP client config (Claude Desktop / Claude Code)

```json
{
  "mcpServers": {
    "freebox": { "command": "uvx", "args": ["freebox-mcp"] }
  }
}
```

### Docker

```bash
docker run -i --rm -v ~/.config/freebox-mcp:/home/app/.config/freebox-mcp \
  ghcr.io/nelson-proia/freebox-mcp
```

(The container needs LAN access to the box; on Linux add `--network host`.)

### Run from source, no install

```bash
uvx --from git+https://github.com/Nelson-PROIA/freebox-mcp freebox-mcp discover
```

## What you can do

Because the whole API is exposed, an LLM can chain real tasks:

- List every device on the LAN, then **reboot the box**.
- Set up a **port-forward / NAT redirect** for a self-hosted service.
- **Schedule a TV recording** on the PVR and manage existing recordings.
- **Toggle wifi**, change the SSID/passphrase, split 2.4/5 GHz bands.
- Read live **xDSL / FTTH line stats** (rate, SNR, attenuation).
- Apply **per-device parental controls** and time schedules.
- Configure the built-in **VPN server** and provision **VPN client** tunnels.
- Manage **downloads + RSS feeds**, FTP, network shares, Freeplug & switch ports.

## CLI

```
freebox-mcp                 run the MCP server over stdio (default)
freebox-mcp --http          run over streamable-HTTP (--host/--port)
freebox-mcp authorize       register the app (press the button on the box)
freebox-mcp login           open a session and print granted permissions
freebox-mcp discover        print discovery info and the chosen transport
freebox-mcp tools           list the generated MCP tools
freebox-mcp call OP [JSON]  invoke one operation, e.g. `freebox-mcp call get_system`
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `FREEBOX_TRANSPORT` | `auto` | `auto` (verified HTTPS, else LAN HTTP), `https`, or `http`. |
| `FREEBOX_API_BASE_URL` | — | Force a base URL, e.g. `https://xxxx.fbxos.fr:55688` (TLS). |
| `FREEBOX_SECTIONS` | — | Comma list to expose only some sections, e.g. `wifi,lan,system`. |
| `FREEBOX_EXCLUDE_SECTIONS` | — | Comma list of sections to hide. |
| `FREEBOX_APP_ID` / `FREEBOX_APP_NAME` | `freebox-mcp` / `Freebox MCP` | App identity on the box. |

Scoping the sections keeps the tool surface small when you only care about a few areas.

> **Permissions.** Configuration-changing tools need the `settings` permission. Grant it (and
> `parental`, etc.) for this app in the Freebox OS web UI: *Paramètres ▸ Gestion des accès ▸
> Applications* — no walking to the box.

## Regenerating the spec

```bash
python -m tools.build            # scrape live docs → parse → emit spec/freebox-openapi.json
python -m tools.build --offline  # rebuild from the committed cache (deterministic; what CI verifies)
```

The CI `regenerate` workflow runs this weekly; on any spec change it bumps the version, commits,
tags, and releases automatically.

## Development

```bash
uv sync --group dev
uv run pytest                 # unit + integration (mocked); add FREEBOX_TEST=1 for live
uv run ruff check . && uv run ruff format .
```

## License

MIT — see [LICENSE](LICENSE). Not affiliated with Free / Iliad.
