"""
Remote Canvas MCP server — OAuth-protected, cloud-hostable.

Wraps the stdio `canvas-lms-mcp` package in a FastMCP proxy and re-serves it
over Streamable HTTP with GitHub OAuth in front, so claude.ai / Cowork can
reach it with this machine off.

Why the odd-looking settings (all three are load-bearing for claude.ai web):
  - stateless_http=True + json_response=True : claude.ai web needs these
  - MCP mounted at "/" not "/mcp"             : claude.ai POSTs to the root
  - OAuthProxy under the hood (GitHubProvider): GitHub has no Dynamic Client
    Registration, and MCP clients require DCR; the proxy fakes a DCR-compliant
    face and forwards to GitHub.

Env vars (see .env.example):
  CANVAS_API_TOKEN, CANVAS_BASE_URL   -> passed to the upstream canvas server
  GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET
  BASE_URL                            -> public https URL of THIS server
  ALLOWED_GITHUB_USERS                -> comma-separated logins allowed in
  PORT                                -> injected by host (Fly/Railway/Render)
"""

import os

from fastmcp import FastMCP  # noqa: F401  (kept for type/context clarity)
from fastmcp.server import create_proxy
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.types import ToolAnnotations  # noqa: F401  (kept for typing clarity)


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


CANVAS_API_TOKEN = _require("CANVAS_API_TOKEN")
CANVAS_BASE_URL = _require("CANVAS_BASE_URL")
BASE_URL = _require("BASE_URL").rstrip("/")
GITHUB_CLIENT_ID = _require("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = _require("GITHUB_CLIENT_SECRET")

ALLOWED_USERS = {
    u.strip().lower()
    for u in os.environ.get("ALLOWED_GITHUB_USERS", "").split(",")
    if u.strip()
}
if not ALLOWED_USERS:
    raise RuntimeError(
        "ALLOWED_GITHUB_USERS is empty — refusing to start. Without an "
        "allowlist ANY GitHub user could drive your Canvas account."
    )

PORT = int(os.environ.get("PORT", "8000"))


class GitHubAllowlist(Middleware):
    """Second gate after OAuth: authenticating proves *a* GitHub identity,
    not that it's an identity we want. Reject everyone not on the allowlist."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        token = get_access_token()
        login = None
        if token is not None:
            claims = getattr(token, "claims", None) or {}
            login = claims.get("login") or claims.get("preferred_username")
        if not login or login.lower() not in ALLOWED_USERS:
            raise ValueError(
                f"Access denied for GitHub user {login!r}. "
                "This server is restricted to its owner."
            )
        return await call_next(context)


def _oauth_storage():
    """Where the OAuth proxy keeps Claude's client registration + tokens.

    Default (None) is a folder on local disk. Hosts with ephemeral disks
    (Render free) wipe it on every spin-down, which is what kept putting the
    connector into "needs reconnect". Set REDIS_URL (e.g. free Upstash) and
    the state lives there instead, encrypted with a key derived from the
    GitHub client secret.
    """
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        return None
    from cryptography.fernet import Fernet
    from fastmcp.server.auth.jwt_issuer import derive_jwt_key
    from key_value.aio.stores.redis import RedisStore
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

    key = derive_jwt_key(
        low_entropy_material=GITHUB_CLIENT_SECRET, salt="canvas-remote-mcp-storage"
    )
    return FernetEncryptionWrapper(
        key_value=RedisStore(url=redis_url),
        fernet=Fernet(key=key),
        raise_on_decryption_error=False,
    )


auth = GitHubProvider(
    client_id=GITHUB_CLIENT_ID,
    client_secret=GITHUB_CLIENT_SECRET,
    base_url=BASE_URL,
    client_storage=_oauth_storage(),
)

# Proxy the upstream stdio canvas server. Its Canvas creds come from env here,
# so the token lives only in this process — never in the MCP conversation.
upstream = {
    "mcpServers": {
        "canvas": {
            "command": "canvas-lms-mcp",
            "args": [],
            "env": {
                "CANVAS_API_TOKEN": CANVAS_API_TOKEN,
                "CANVAS_BASE_URL": CANVAS_BASE_URL,
            },
        }
    }
}

mcp = create_proxy(
    upstream,
    name="Canvas (remote)",
    auth=auth,
)
mcp.add_middleware(GitHubAllowlist())


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    """Unauthenticated liveness check for the keep-awake pinger. Returns no data."""
    from starlette.responses import PlainTextResponse

    return PlainTextResponse("ok")


if __name__ == "__main__":
    # NOTE: stateless_http / json_response are http_app() options in FastMCP v3
    # (NOT constructor options) — they're forwarded via run()'s transport kwargs.
    # Both are required for claude.ai web to talk to a custom connector.
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=PORT,
        path="/",  # claude.ai posts to the root, not /mcp
        stateless_http=True,
        json_response=True,
    )
