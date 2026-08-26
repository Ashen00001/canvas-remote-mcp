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

## Deploy (Fly.io)

### 1. GitHub OAuth App — DONE

Created 2026-08-26: **"Canvas Remote MCP"** (app id `3818524`), owner `Ashen00001`.

- Client ID: `Ov23linmhs7OYZsyGdG1`
- Client secret: in `.env` (gitignored). GitHub shows it once — it's captured there.
- Callback URL: `https://canvas-remote-mcp.fly.dev/auth/callback`

Manage it at <https://github.com/settings/applications/3818524>.

> **If your Fly app name ends up different from `canvas-remote-mcp`**, edit the
> callback URL on that page to match — it must be exact, and update `BASE_URL` too.

(For reference: GitHub has no REST API for creating OAuth Apps — `user/oauth_apps`
and `applications` both 404. It's web-UI only.)

### 2. Launch and set secrets

```bash
fly launch --no-deploy --copy-config
```

All values are already in `.env` — read them from there:

```bash
fly secrets import < .env
```

(`fly secrets import` reads KEY=VALUE lines from stdin, so this sets all six at once
without pasting secrets into your shell history.)

### 3. Deploy

```bash
fly deploy
```

### 4. Verify before wiring it up

```bash
curl -s https://<your-app>.fly.dev/.well-known/oauth-authorization-server
```

Should return JSON with `authorization_endpoint` / `token_endpoint` / `registration_endpoint`.

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://<your-app>.fly.dev/ -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Must print **401**. If it prints 200, stop — the server is unprotected.

### 5. Add to claude.ai

Settings → Connectors → **Add custom connector** → URL: `https://<your-app>.fly.dev`

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

Fly `shared-cpu-1x` / 512MB with one warm machine ≈ **$2–4/mo**. Set
`min_machines_running = 0` in `fly.toml` to cut that to near zero, at the cost of
occasional cold starts (which can time out claude.ai's handshake).

## Rotating the Canvas token

```bash
fly secrets set CANVAS_API_TOKEN='19324~newtoken'
```

Triggers a rolling restart. Revoke the old one in Canvas → Account → Settings →
Approved Integrations.

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
