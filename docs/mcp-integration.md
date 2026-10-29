# Forth MCP integration

Forth exposes the same account-scoped tools through local stdio and remote Streamable HTTP at `/mcp/`. Profiles, sources, job boards/opportunities, matches, applications, documents, conversations, approvals and events belong to the authenticated Forth user. Tool arguments cannot select an account. Operators with database/server or Django administrator access remain privileged; this is application-level isolation in a shared database, not separate infrastructure per user.

## Remote connection from ChatGPT

`get_candidate_context` exposes the account's saved raw fit threshold as `profile.minimum_match_score`. Job results include `match.score` (raw), `normalized_score` (display score), `profile_minimum_score`, and `meets_profile_threshold`. The saved threshold maps to 80 on the normalized scale. `search_jobs.min_score` filters raw scores; pass the saved threshold explicitly to exclude jobs below it.

Each person connects the same HTTPS MCP URL from their own ChatGPT account. Forth sends them to its browser login page, where they enter their **Forth email and password**, then approve access to their own workspace. ChatGPT receives a scoped, expiring OAuth token; the password never goes through a tool call or chat message.

The implementation uses Django OAuth Toolkit with authorization code + S256 PKCE, resource-bound tokens, rotating refresh tokens, revocation, and explicit consent. It publishes:

- `/.well-known/oauth-protected-resource`
- `/.well-known/oauth-authorization-server`
- `/oauth/authorize/`, `/oauth/token/`, `/oauth/revoke_token/`
- `/oauth/authorized_tokens/` for signed-in users to revoke connections

ChatGPT client metadata discovery (CIMD) is enabled for `chatgpt.com` only. Other clients can use a pre-registered public authorization-code application created by an administrator in Django admin; register their exact callback URL and use `none` token endpoint authentication. Dynamic client registration is not enabled. All grants require the `forth:access` scope and `resource=https://YOUR-HOST/mcp/`. Access tokens last one hour. Remote MCP does not accept browser JWTs or a shared owner selector.

The CIMD fetcher supports ChatGPT's plural `token_endpoint_auth_methods_supported` field: it selects `none` only when explicitly advertised, even if the legacy singular preference is `private_key_jwt`. Forth does not advertise or implement signed client assertions. Documents without a supported public-client method are rejected; the library still validates the client identity and redirect URIs and enforces S256 PKCE. See [OpenAI client registration](https://developers.openai.com/plugins/build/auth#client-registration).

### Deploy and connect

1. Set `FORTH_PUBLIC_URL=https://YOUR-HOST` (no path), `DJANGO_ALLOWED_HOSTS=YOUR-HOST`, `DJANGO_CSRF_TRUSTED_ORIGINS=https://YOUR-HOST`, `DJANGO_DEBUG=0`, and a strong private `DJANGO_SECRET_KEY` in deployment configuration.
2. Serve the app through HTTPS. If TLS terminates upstream, configure the trusted proxy to overwrite `X-Forwarded-Proto` correctly, then set `DJANGO_TRUST_PROXY_HEADERS=1`. The supplied nginx config uses its own `$scheme`; adjust it when placing it behind a separate TLS proxy. Do not trust arbitrary forwarded headers from the internet.
3. Rebuild and deploy the web/worker/beat images. Startup applies OAuth Toolkit's database migrations. Existing Forth accounts and data remain in place. Local MCP also needs the rebuilt image for its new authentication backend.
4. Run `python manage.py audit_account_isolation`. This read-only command checks persisted owner-bearing relationships and fails if any link crosses accounts.
5. Configure the ChatGPT MCP connection with `https://YOUR-HOST/mcp/`, OAuth, and CIMD. Sign in to Forth and consent. Use the callback/client metadata shown by ChatGPT if configuring a pre-registered client instead.
6. Verify with two separate accounts: each must return its own profile and jobs, and a job ID from the other account must fail.

The OAuth round trip is covered by integration tests; actual ChatGPT connection verification also requires the deployed public URL.

### This host's HTTPS deployment

This host is **LAN-only** at `https://forth.mahfouz.ca:8443`. UniFi DNS resolves the name to `192.168.3.105`; no public A record or WAN port-forward is used. Compose binds HTTPS to that private IPv4 address and the old HTTP listener to `127.0.0.1:8021`. Host port 443 belongs to the existing Kubernetes ingress. Reserve the LAN address so the binding and DNS remain valid.

OpenAI Secure MCP Tunnel provides outbound-only MCP access. Tunnel `tunnel_6acf84fdd5e0819180223c181567272b` is associated with the Personal Platform organization and the selected ChatGPT workspace. The supported v0.0.16 client is installed under `~/.local/share/forth-tunnel`; its profile is `~/.config/tunnel-client/forth-private.yaml`. The `forth-private-tunnel.service` user service runs `deploy/run-private-tunnel.py`, which loads Forth's existing runtime OpenAI credential from the running web container into the tunnel process environment without duplicating it in the profile or command arguments. This credential must retain Tunnels Read + Use access.

Check the service with `systemctl --user status forth-private-tunnel.service` and readiness with `curl http://127.0.0.1:18081/readyz`. The local operator UI is `http://127.0.0.1:18081/ui`. Stop tunnel access with `systemctl --user stop forth-private-tunnel.service` (and disable the service to prevent restart on login). The host's user manager has lingering enabled for unattended operation.

In ChatGPT, add a custom MCP server, select Tunnel and Forth private MCP, OAuth and CIMD. Keep the discovered tunnel token endpoint, but set the Resource explicitly to `https://forth.mahfouz.ca:8443/mcp/` to match Forth's resource-bound tokens. Request `forth:access`. Browser login remains at the private Forth authorization URL, so users must be on the LAN or an appropriately configured VPN to authorize. The tunnel routes the OAuth token exchange without publishing Forth. Each additional ChatGPT workspace must be explicitly associated with the tunnel; it does not become available to arbitrary ChatGPT accounts.

The Let's Encrypt certificate uses Route53 DNS validation. Its private state is under `~/.local/state/forth/letsencrypt`, and nginx reads copied certificates from ignored `.secrets/tls/`. The host's `~/.local/share/forth-certbot` virtual environment contains Certbot and its Route53 plugin; renewal uses the host's AWS credentials. Keep those credentials available with permission to manage the validation TXT record.

The user systemd timer `forth-cert-renew.timer` checks twice daily. `deploy/renew-certificate.sh` renews when needed and calls `deploy/install-certificate.sh` to copy the certificate, validate nginx configuration, and reload nginx. Inspect it with `systemctl --user status forth-cert-renew.timer` and `journalctl --user -u forth-cert-renew.service`. The timer and Certbot installation are host configuration, not provisioned automatically by Compose. The rebuild script includes the local Compose override so subsequent deployments retain HTTPS.

The previous Compose configuration automatically created `admin` with a known default password. That bootstrap default has been removed. **Change the password or disable any existing default administrator before exposing this deployment publicly.** Existing passwords are not changed automatically. Server-wide OpenAI/Brave credentials are operator credentials; all accounts currently share those service quotas/billing.

## Local stdio clients

Supply `FORTH_MCP_USERNAME` (email or legacy username) and `FORTH_MCP_PASSWORD` through the client’s secret/environment mechanism. Passwords are checked with Django and inactive accounts are rejected. `FORTH_MCP_OWNER_EMAIL` and `FORTH_MCP_OWNER_ID` no longer grant access.

```json
{
  "mcpServers": {
    "forth-job-seeker": {
      "command": "docker",
      "args": [
        "compose", "-f", "/absolute/path/to/forth/docker-compose.yml",
        "run", "--rm", "-T",
        "-e", "FORTH_MCP_USERNAME", "-e", "FORTH_MCP_PASSWORD", "mcp"
      ]
    }
  }
}
```

This inherits credentials from the launching environment. Do not place literal passwords in command arguments or committed client configuration. Local Docker/database access is privileged; use OAuth HTTP for other users rather than giving them Docker access.

## Direct “Continue with ChatGPT” sign-in

OpenAI documents this as a separate identity integration. Its hosted website/plugin sign-in is currently available to selected commercial partners through a limited trial. It needs an OpenAI-issued client ID and registered callback. The open-source local-client flow for ChatGPT plan usage is a different integration and does not automatically establish a remote Forth MCP connection.

Once approved, OpenAI sign-in can be added inside Forth's existing OAuth login flow: validate the upstream ID token, map its issuer/client/subject to a Forth account, then finish the outer MCP authorization flow. Existing account linking must require explicit confirmation, rather than silently linking by email. This upstream sign-in is **not implemented or enabled** by this change.

References: [MCP authentication](https://developers.openai.com/plugins/build/auth), [website sign-in](https://developers.openai.com/siwc/website), [ChatGPT plugin sign-in](https://developers.openai.com/siwc/chatgpt-plugin).

## Tools

- `get_candidate_context` reads profile evidence and preferences to guide sourcing.
- `search_jobs` ranks jobs already stored in Forth with fit explanations and gaps.
- `record_job` normalizes, deduplicates, stores, and matches a public job posting found in the browser.
- `prepare_application` creates an application plus unapproved tailored resume and cover-letter drafts.
- `get_application_materials` returns the latest drafts and their claim-validation state.
- `record_submitted_application` records a submission only after the browser visibly confirms it.

## Browser-assisted workflow

1. Read `get_candidate_context` before searching.
2. Find public opportunities with the browser; do not bypass job-board restrictions.
3. Call `record_job` with the visible posting text and its public canonical URL.
4. Use the returned match score, supporting evidence, and gaps to decide whether to proceed.
5. Call `prepare_application`, then review the resume and cover-letter drafts and unsupported-claim warnings.
6. Only after the user explicitly approves the drafts, use the browser to prepare an application. Confirm immediately before entering personal information into a third-party form and again before submitting it.
7. Once the site visibly confirms success, call `record_submitted_application` with that confirmation.

Forth intentionally has no tool that approves a draft or submits an external application. Those remain deliberate human decisions.

### Second personal account tunnel

A separate profile, `forth-secondary`, targets the same private MCP server using tunnel `tunnel_6ad14fb78ac081919cc984a0377726da`. Its user service is `forth-secondary-tunnel.service`, and its loopback health endpoint is `http://127.0.0.1:18082/readyz`. It uses a separate credential reference at `~/.local/state/forth/tunnel-secondary.key`; the original tunnel credential is not reused.

On the server, run `python3 deploy/activate-secondary-tunnel.py` in an interactive terminal to enter a runtime API key authorized for the second tunnel. Input is hidden, the key is saved with owner-only permissions outside the repository, and the service is enabled and started. Check readiness and control-plane connectivity before configuring the second ChatGPT account. Until this credential step is completed, the second tunnel is only prepared, not connected.

### Materials and pipeline tools

The authenticated workspace now also exposes:

- `get_opportunity(job_id)`: full posting, requirements, match reasons/signals,
  linked applications and effective material instructions.
- `list_applications(status?, query?, offset?, limit?)`: paginated pipeline records
  with follow-up and submission dates; use `next_offset` until it is null.
- `get_application(application_id)`: notes, activity, contacts, all linked material
  versions and authenticated artifact download paths.
- `update_application(application_id, changes)`: update tracking status, notes,
  follow-up date, outcome or recruiter contact. Read before replacing notes.
  Marking Applied records a user-reported submission; it does not submit anything.
- `set_material_instructions(instructions, job_id?)`: save account defaults or an
  opportunity override. Omit `job_id` for account defaults. For an opportunity,
  `null` inherits defaults and `""` explicitly uses no custom instructions.
- `get_workspace_status()`: recent ingestion, sourcing and agent runs, plus
  queued/running/failed material jobs.

`get_candidate_context` includes resume contact choices and default material
instructions. Material responses include their saved instruction snapshot and
visual design. Instructions apply to future resume and cover-letter versions;
existing versions remain unchanged. Supported designs use modern/classic/minimal
layouts, compact/balanced/spacious density, Letter/A4 paper and six-digit hex
accent colors. Custom prose directions depend on AI availability; fallback drafts
include a review note. All tools remain scoped to the authenticated account.

### Reboot readiness for OAuth tunnels

Both local tunnel services have an `oauth-readiness.conf` systemd drop-in. It runs
`deploy/wait-for-mcp-oauth.py https://forth.mahfouz.ca:8443` as `ExecStartPre`, with
`TimeoutStartSec=150`. The script waits up to 120 seconds for valid protected-resource
and authorization-server metadata; failure lets the services' existing
`Restart=on-failure` retry startup. Keep this drop-in when reinstalling either service.

On 2026-10-29 the secondary tunnel rejected OAuth requests with `unsupported channel
"harpoon"`: its previous boot had attempted discovery before nginx was listening,
leaving an empty OAuth target catalog even after Forth recovered. Restarting the
tunnel restored discovery and all eight routes. Check `/health?details=true` on
ports 18081 and 18082: `oauth` should be `complete`, `harpoon` should be `settled`
with targets present, and control-plane polling should be healthy. A running
systemd process alone does not establish readiness. Full recovery also requires a
successful retry from the affected user's authenticated client.

Validate the startup gate with `python -m unittest discover -s deploy/tests`.
