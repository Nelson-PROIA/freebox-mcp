# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's **"Report a vulnerability"**
(Security ▸ Advisories) on this repository. Do not open a public issue for
suspected vulnerabilities.

## Threat model & design

This server talks to a Freebox on your local network and holds credentials that
grant access to it. Security choices:

- **No long-lived secrets in CI.** Publishing uses OIDC: PyPI **Trusted
  Publishing** and GHCR via the ephemeral `GITHUB_TOKEN`. Nothing to leak.
- **Supply chain.** All GitHub Actions are pinned to full commit SHAs; release
  artifacts and the container image carry **SLSA build-provenance attestations**;
  the image is **cosign keyless-signed**. CodeQL and `pip-audit` run in CI.
- **The `app_token` never transits the network.** Only `HMAC-SHA1(app_token,
  challenge)` is sent when opening a session. The token is stored at
  `~/.config/freebox-mcp/credentials.json` with `0600` permissions and is never
  logged.
- **TLS.** When the box is reachable over HTTPS, the certificate is verified
  against the **bundled Freebox root CAs** (`src/freebox_mcp/certs/`).
- **LAN HTTP fallback.** If only LAN HTTP is reachable, the session token transits
  your local network in cleartext (the app_token still does not). The server logs
  a warning. For TLS, enable remote HTTPS access on the box or set
  `FREEBOX_API_BASE_URL` to an HTTPS endpoint.

## Permissions

The app requests only what you approve on the Freebox. Configuration-changing
tools require the `settings` permission, which you grant in the Freebox OS web UI
(*Paramètres ▸ Gestion des accès ▸ Applications*). Granting nothing still allows
read-only discovery and the lifecycle tools.
