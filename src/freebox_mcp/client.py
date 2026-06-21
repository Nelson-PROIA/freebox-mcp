"""The authenticated httpx client that FastMCP drives.

Responsibilities layered on a plain httpx.AsyncClient:
  * prepend ``/api/v{major}`` (from discovery) to every spec-relative path;
  * inject the ``X-Fbx-App-Auth`` session header, opening/refreshing the session
    lazily and transparently retrying once on ``auth_required``;
  * unwrap the Freebox ``APIResponse`` envelope so tools return ``result`` and
    surface ``success: false`` as a clean error.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

from .auth import FreeboxError, Session, TokenStore, open_session
from .config import Settings
from .discovery import Endpoint
from .tls import freebox_ssl_context

log = logging.getLogger("freebox_mcp.client")


class SessionManager:
    """Lazily opens and caches a Freebox session, refreshing on demand."""

    def __init__(self, raw: httpx.AsyncClient, prefix: str, app_id: str, app_token: str | None):
        self._raw = raw
        self._prefix = prefix
        self._app_id = app_id
        self._app_token = app_token
        self._token: str | None = None
        self.permissions: dict = {}
        self._lock = asyncio.Lock()

    @property
    def registered(self) -> bool:
        return bool(self._app_token)

    def set_app_token(self, app_token: str, app_id: str | None = None) -> None:
        self._app_token = app_token
        if app_id:
            self._app_id = app_id
        self._token = None  # force a fresh session next call

    async def get_token(self) -> str:
        if self._token:
            return self._token
        return await self.refresh()

    async def refresh(self) -> str:
        if not self._app_token:
            raise FreeboxError(
                "This app is not authorized on the Freebox yet. Run `freebox-mcp authorize` "
                "and press the button on the Freebox front panel.",
                error_code="not_registered",
            )
        async with self._lock:
            session: Session = await open_session(
                self._raw, self._prefix, self._app_id, self._app_token
            )
            self._token = session.session_token
            self.permissions = session.permissions
            log.debug("opened Freebox session (permissions: %s)", sorted(session.permissions))
            return self._token


class FreeboxTransport(httpx.AsyncBaseTransport):
    """Unwraps the APIResponse envelope and retries once on auth_required."""

    def __init__(self, inner: httpx.AsyncBaseTransport, session: SessionManager):
        self._inner = inner
        self._session = session

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        await response.aread()
        unwrapped, retry = self._process(response, request, allow_retry=True)
        if retry:
            # refresh session, re-inject header, resend once
            token = await self._session.refresh()
            request.headers["X-Fbx-App-Auth"] = token
            response = await self._inner.handle_async_request(request)
            await response.aread()
            unwrapped, _ = self._process(response, request, allow_retry=False)
        return unwrapped

    def _process(
        self, response: httpx.Response, request: httpx.Request, allow_retry: bool
    ) -> tuple[httpx.Response, bool]:
        ctype = response.headers.get("content-type", "")
        if "json" not in ctype:
            return response, False  # binary payloads (downloads) pass through
        try:
            body = json.loads(response.content)
        except (json.JSONDecodeError, ValueError):
            return response, False
        if not isinstance(body, dict) or "success" not in body:
            return response, False

        if body["success"]:
            result = body.get("result", {"success": True})
            return _json_response(200, result, request), False

        error_code = body.get("error_code")
        if error_code == "auth_required" and allow_retry and self._session.registered:
            return response, True
        payload = {
            "freebox_error": True,
            "error_code": error_code,
            "msg": body.get("msg", "Freebox API error"),
        }
        return _json_response(409, payload, request), False


def _json_response(status: int, data: object, request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers={"content-type": "application/json"},
        content=json.dumps(data).encode(),
        request=request,
    )


def _make_request_hook(session: SessionManager, prefix: str):
    async def hook(request: httpx.Request) -> None:
        path = request.url.path
        if not path.startswith(prefix + "/") and not path.startswith("/api/"):
            request.url = request.url.copy_with(path=prefix + path)
            path = request.url.path
        if "/login/" not in path:
            request.headers["X-Fbx-App-Auth"] = await session.get_token()

    return hook


def _verify(settings: Settings, endpoint: Endpoint):
    if endpoint.secure:
        return freebox_ssl_context(str(settings.cert_bundle))
    return True


def build_session_manager(
    settings: Settings, endpoint: Endpoint, store: TokenStore
) -> SessionManager:
    creds = store.get(endpoint.discovery.uid)
    app_token = creds.app_token if creds else None
    app_id = creds.app_id if creds else settings.app_id
    raw = httpx.AsyncClient(
        base_url=endpoint.base_url,
        verify=_verify(settings, endpoint),
        timeout=settings.request_timeout,
    )
    return SessionManager(raw, endpoint.api_path_prefix, app_id, app_token)


def build_client(
    settings: Settings, endpoint: Endpoint, session: SessionManager
) -> httpx.AsyncClient:
    inner = httpx.AsyncHTTPTransport(verify=_verify(settings, endpoint), retries=1)
    transport = FreeboxTransport(inner, session)
    return httpx.AsyncClient(
        base_url=endpoint.base_url,
        transport=transport,
        timeout=settings.request_timeout,
        event_hooks={"request": [_make_request_hook(session, endpoint.api_path_prefix)]},
    )
