# Canvas Remote MCP — OAuth-protected

Runs your Canvas MCP server in the cloud so **Cowork / claude.ai can use it with your rig off**.

It wraps the stdio `canvas-lms-mcp` package in a FastMCP proxy, re-serves it over
Streamable HTTP, and puts **GitHub OAuth + a username allowlist** in front.

## Why OAuth and not a shared secret

- Canvas personal access tokens are **full access** — Canvas's own docs say storing one is
  "in many ways equivalent to storing the user's password." Scoped tokens need
  institution-admin developer keys, which students can't create.
- claude.ai custom connectors only support **OAuth or no-auth** — the UI won't send a
  custom `Authorization: Bearer` header.

So: no-auth would mean anyone with the URL controls your Canvas account. Hence OAuth.

## Two layers of protection

1. **OAuth** — you must log in with GitHub to get a token.
2. **Allowlist** — `ALLOWED_GITHUB_USERS` gates every tool call. Logging in proves *an*
   identity, not a wanted one. Server refuses to boot with an empty allowlist.

---

## Deploy (Render)

### 1. GitHub OAuth App — DONE

Created 2026-08-26: **"Canvas Remote MCP"** (app id `3818524`), owner `Ashen00001`.

- Client ID: `Ov23linmhs7OYZsyGdG1`
- Client secret: in `.env` (gitignored). GitHub shows it once — it's captured there.
- Callback URL: `https://canvas-remote-mcp.onrender.com/auth/callback`

Manage it at <https://github.com/settings/applications/3818524>.

> The callback URL must **exactly** match `<BASE_URL>/auth/callback`. If the service
> is ever renamed or moved, update both this and the `BASE_URL` env var.

(For reference: GitHub has no REST API for creating OAuth Apps — `user/oauth_apps`
and `applications` both 404. It's web-UI only.)

### 2. Deploy via Blueprint — DONE

Render dashboard → **New → Blueprint** → connect `Ashen00001/canvas-remote-mcp`.
`render.yaml` is auto-detected; Render prompts for the six `sync: false` env vars
(values live in local `.env`). Auto-deploys on every push to `main` thereafter.

Requires the Render GitHub App installed on this repo (scoped to it only).

### 3. Verify before wiring it up

```bash
curl -s https://canvas-remote-mcp.onrender.com/.well-known/oauth-authorization-server
```

Should return JSON with `authorization_endpoint` / `token_endpoint` / `registration_endpoint`.

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://canvas-remote-mcp.onrender.com/ -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Must print **401**. If it prints 200, stop — the server is unprotected.

### 4. Add to claude.ai

Settings → Connectors → **Add custom connector** → URL: `https://canvas-remote-mcp.onrender.com`

Claude auto-registers via DCR, bounces you through GitHub, and the tools appear.

---

## Local testing

```bash
pip install -r requirements.txt
cp .env.example .env   # fill it in
python server.py
```

## Gotchas already handled

| Gotcha | Handling |
|---|---|
| claude.ai POSTs to `/`, not `/mcp` | `path="/"` in `run()` |
| claude.ai web needs stateless + JSON | `stateless_http=True, json_response=True` |
| These are `http_app()` opts in v3, not constructor opts | passed via `run()` transport kwargs |
| GitHub has no DCR; MCP clients require it | `GitHubProvider` wraps `OAuthProxy` |
| OAuth proves identity, not authorization | `GitHubAllowlist` middleware |

## Cost

Render free plan: **$0**, but the instance spins down after ~15 min idle and the next
request takes ~50s to wake — which can time out claude.ai's connector handshake.

If that gets annoying: Render **Starter** (~$7/mo) removes sleep entirely. Fly
`shared-cpu-1x`/512MB with a warm machine (~$2–4/mo) is cheaper, but Fly requires
payment info before it will create an app at all.

## Rotating the Canvas token

Render dashboard → **canvas-remote-mcp** → **Environment** → edit `CANVAS_API_TOKEN`
→ Save. Render redeploys automatically.

Then revoke the old one in Canvas → Account → Settings → Approved Integrations.

---

## Deployed (2026-08-26)

**Live:** https://canvas-remote-mcp.onrender.com
Render free plan, Docker runtime, Oregon. Blueprint: `render.yaml`, auto-deploys on push to `main`.

Verified from the public internet:
- `/.well-known/oauth-authorization-server` serves real HTTPS endpoints
- Unauthenticated `tools/list` -> **401** with correct `WWW-Authenticate` header
- DCR `/register` + `/authorize` -> 302 into consent -> GitHub

**Known limitation:** the free plan spins down after ~15 min idle; the next request
takes ~50s to wake. That can time out claude.ai's connector handshake — retry usually
works. Upgrade to Render Starter (no sleep) if it proves annoying.

Deployed to Render rather than Fly because Fly now requires payment info before
creating any app. `fly.toml` was removed to avoid implying otherwise.
