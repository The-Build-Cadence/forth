# Forth

Your next move, fully staffed. Forth is a private, agentic career operating system for candidate intelligence, compliant sourcing, explainable matching, application operations, and evidence-backed materials.

The stack intentionally follows the sibling Drawing Algorithms project:

- Angular 21 frontend
- Django / Django REST Framework backend
- PostgreSQL with pgvector and HNSW cosine indexes
- Redis
- Celery workers and beat
- Django Channels realtime updates
- Gotenberg PDF rendering
- Docker Compose and Nginx
- OpenAI API called from the backend only

## MVP Capabilities

- Upload a current PDF, Word, HTML, ODT, RTF, Markdown, or text resume (including OCR for scanned PDFs).
- Analyze resume evidence with an LLM, surface genuine ambiguity, and run a dynamically planned onboarding interview.
- Extract profile facts and confirm or correct uncertain claims before activation.
- Manually import job descriptions or job URLs.
- Extract structured job metadata.
- Embed canonical candidate and job profiles with OpenAI `text-embedding-3-large`.
- Search and rank stored jobs with pgvector cosine distance, then compute transparent match scores with evidence and gaps.
- Generate tailored resume drafts from verified/profile facts and canonical resume content.
- Review validation notes, weak claims, and unsupported claims.
- Export resume markdown.
- Create application records from jobs.
- Move applications through a pipeline.
- Maintain a living search brief with target roles, industries, authorization, work modes, compensation, and explicit preference strength.
- Run Jobicy, Arbeitnow, Greenhouse, Lever, Ashby, and RSS discovery connectors with durable source-run history.
- Review decomposed fit signals separately from hard eligibility gates.
- Collaborate with six bounded specialist workflows through the Forth Concierge.
- Approve consequential actions through a durable human-in-the-loop queue.
- Generate both resumes and cover letters, validate claims, and render final PDFs through Gotenberg.
- View strategy recommendations based on matches, profile quality, and application history.

## Product Loop

```text
Candidate evidence + explicit preferences
  -> scheduled compliant discovery
  -> freshness, versioning, normalization, and dedupe
  -> OpenAI candidate/job embeddings + pgvector retrieval
  -> eligibility gate + semantic and evidence-based fit score + citations
  -> user approves an opportunity
  -> resume + cover-letter plan and draft
  -> claim review and document approval
  -> HTML + Gotenberg PDF artifacts
  -> tracked application, follow-up, interview, and outcome
```

The specialist roles are Profile Steward, Sourcing Scout, Match Analyst, Application Coach, Document Tailor, and Forth Concierge. They are durable workflows over typed Django domain operations—not independent services with private state.

The Profile Steward is evidence-led rather than a fixed wizard. It analyzes the
candidate's current resume, stores clear claims as proposed evidence, identifies a
small set of meaningful ambiguities, and replans the next typed question after every
answer until the candidate's direction, constraints, capabilities, impact, and work
preferences are ready for use.

## Local Docker Run

Clone the repository and configure your own local credentials:

```bash
git clone git@github.com:The-Build-Cadence/forth.git
cd forth
cp .env.example .env
```

Set your OpenAI key and Django settings in `.env` before starting the app.

```bash
docker compose up --build
```

Open the app at:

```text
http://localhost:8021
```

Choose **Create your workspace** to register with an email address and password.
Forth signs you in immediately and opens the Profile Steward onboarding flow; local
development does not require email verification.

Default local admin user created by the container:

```text
username: admin
password: adminpass
```

## Demo Data

Hydrate the local app with representative demo data:

```bash
docker compose exec web python manage.py seed_demo --username admin
```

The command is idempotent for demo rows. It clears only rows tagged as demo data for the selected user, then recreates:

- profile source material
- verified and unverified profile facts
- job sources
- imported job postings
- match scores with evidence and gaps
- canonical and tailored resumes
- application pipeline records
- activity events
- markdown artifacts

## Local Development

Backend:

```bash
cd backend
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Frontend:

```bash
cd frontend
npm install
npm start
```

The Angular dev server runs on `http://localhost:4200`. For full API access in development, use the Docker/Nginx entrypoint or add a local proxy configuration.

## Important Constraints

- OpenAI keys must stay in backend environment variables.
- Generated resume claims should be reviewed before use.
- Discovery is limited to manual imports and compliant public job-feed/ATS/RSS endpoints; the system does not bypass authentication, anti-bot controls, or site terms.
- The deterministic fallback path keeps the app usable even if OpenAI calls fail.

## Semantic Search and Matching

Candidate profiles, individual profile facts, and normalized job profiles are stored
as full-width 3,072-dimensional pgvector `halfvec` values. Embeddings are content-hashed and model-versioned,
so edits only regenerate stale vectors. PostgreSQL uses cosine distance for candidate
to-job ranking and nearest-evidence retrieval; the final score remains explainable and
also includes skills, evidence quality, stated direction, domain, and logistics.

Rebuild all vectors and matches after changing the embedding model or dimensions:

```bash
docker compose exec web python manage.py rebuild_search_embeddings --force
```

If a previous rebuild completed candidate facts but not jobs, resume only the job
portion with `--jobs-only --force`.

The jobs API accepts `semantic_query=<natural language intent>` for vector search.

## Primary Experience

```text
Today
  -> review a short priority queue and due actions
Concierge
  -> ask questions, delegate bounded work, decide approvals
Opportunities
  -> inspect eligibility, score signals, evidence, and gaps
Candidate Profile
  -> maintain search brief, preferences, facts, and source evidence
Applications
  -> move through stages with versioned events and next actions
Document Studio
  -> review resume and cover letter, approve claims, render PDF bundle
```

## User Guide

The standalone, responsive guide is available in the running app at
`/forth-user-guide.html` and in the repository at
[`frontend/src/forth-user-guide.html`](frontend/src/forth-user-guide.html).

## Quality Checks

### Application document readability

Material preparation asks for evidence-backed qualifications summaries, standard section
names, and explicit employer, date, location, and contact labels wherever those details
are supplied. Missing facts are not filled in. The offline fallback preserves the
source resume and adds supported summary points and skills; it does not reconstruct
employment history.

PDF exports use selectable text in a single-column reading order, semantic headings
and lists, document language, clickable links, accessibility tags, and a heading
outline. These use Gotenberg's [tagged PDF and outline options](https://gotenberg.dev/docs/convert-with-chromium/convert-html-to-pdf).
The same semantic content is retained in the HTML fallback when the renderer is
unavailable. No hidden hiring-agent instructions are added. Tags improve navigation
and extraction but are not a certification of PDF/UA compliance or a guarantee of any
particular hiring system's parsing behavior.

Re-prepare drafts to use the new content guidance; re-export existing drafts to use
the new PDF structure. Existing saved artifacts are not rewritten.

In **Resume Studio → Contact details**, save a phone number, email address, and
HTTPS LinkedIn profile URL. Each has an independent inclusion checkbox; empty
or unchecked fields are omitted from newly generated resumes. Configured contacts
replace conventional source contact details and are inserted directly below the
candidate name, so both AI and offline drafts use the same values. The generated
Markdown, preview, PDF, and application bundle share that saved version. Changes
apply on generation, not retroactively to reviewed or approved resumes. Until
settings are first saved, the existing source-contact behavior is preserved.

Deployment requires the `0014_candidateprofile_resume_contact` migration and a
rebuild of the backend and frontend.

Run document tests with a reachable renderer to verify actual PDF text order, tags,
language, outline, metadata, and links across all three templates:

```bash
TEST_GOTENBERG_URL=http://localhost:3000 python backend/manage.py test core.tests.test_document_accessibility
```

Without `TEST_GOTENBERG_URL`, only the real-renderer test is skipped.

### General checks

```bash
# Backend unit and integration coverage
python backend/manage.py test core.tests

# Production frontend build
npm --prefix frontend run build

# Browser journeys at desktop, tablet, and mobile sizes
npm --prefix frontend run test:e2e

# Production dependency audit
npm --prefix frontend audit --omit=dev
```

## MCP integration

Forth supports credential-authenticated local MCP and per-account OAuth remote MCP at `/mcp/` for browser-assisted job research, explainable matching, and claim-validated application drafts. See [the MCP integration guide](docs/mcp-integration.md) for setup and the confirmation boundaries around external applications.

The browser suite expects the Docker stack at `http://127.0.0.1:8021` and the
local `admin` / `adminpass` account. Override the origin with `E2E_BASE_URL`.

## Persistent storage and project name

Compose uses the project name `forth`, so containers are named `forth-<service>-1`
regardless of the checkout directory. Uploaded files live in `./data`; PostgreSQL
and Redis use named volumes. Redis snapshots its state when data changes.

New installations use `forth_db_data` and `forth_redis_data`. Existing installations
can set `FORTH_DB_VOLUME` and `FORTH_REDIS_VOLUME` in their private `.env` to reuse
previous volumes. The local override marks migrated volumes as external so Compose
does not manage their lifecycle. Keep these settings and `data/` when moving the
checkout. Do not use `docker compose down -v` when you need to retain managed data.

The original database and role names remain `job_seeker` for compatibility with
existing data; changing the repository or container names does not require a
database rename.

## External beta and first-use flow

### Job and application journey

Open a job workspace from Jobs or Applications to save a role, prepare a resume
and cover letter, review both documents, draft employer-form answers, and track
progress without switching workspaces. Saving creates an internal tracking record;
it does not generate documents or submit anything. Preparation creates drafts and
keeps its progress across reloads. Documents have separate states: not created,
generating, needs review, reviewed, or generation failed. Reviewed means both
current documents have been reviewed; generating another version requires a fresh
review. Older exported files remain available under Documents.

Apply on the employer's site, then use **Mark as applied** to confirm the submission
date. **I already applied** works without generated documents. Opening a form link
never changes application status. Applications groups existing records into Saved,
Preparing, Applied, Interviewing, Offer and Closed; older detailed statuses remain
stored and visible in Tracking. Follow-up due is a reminder, not a stage. Legacy
job and application links open the same workspace. The document library remains
available for source resumes, contact settings and historical document versions.

New accounts start at `/start`: choose discovery or an existing job, optionally
upload a resume, then confirm roles, location and work modes. **Save & finish later**
persists incomplete preferences to the account. Quick setup never verifies career
claims. The detailed evidence interview remains available under **My Profile →
Review my experience**. Discovery starts once on request; daily searches are opt-in
and can be paused in **Job search settings**. A failed search preserves preferences
and offers retry or manual job import.

In **Job search settings → Advanced search settings**, enable **Automatically adapt
searches to my profile** and save to regenerate discovery queries each run from
current target roles, work preferences, authorized locations and up to three
profile skills (verified skills first; low-confidence, rejected and archived skills
are excluded). Adaptive searches ignore saved focused queries and the static
country bias, retaining the existing query budget, cooldowns, fit thresholds and
eligibility checks. They aim to improve discovery relevance, without guaranteeing
higher match scores or changing the profile. No additional LLM calls are used.
The option defaults off. Static mode uses saved focused queries, or a snapshot of
role/location preferences captured at configuration time. Existing searches receive
that snapshot in migration `0020`; turning adaptation off restores those criteria.
Edit focused queries to change a static search.

For an external beta, configure `FORTH_BETA_INVITE_CODE` and share it only with
invited testers. The public signup form requests the code when configured. Shared
AI/search provider charges are paid by the operator; the cost display is an estimate,
not billing or a subscription allowance. Invitation gating and request throttles do
not replace a provider spending limit. Set spending limits in provider accounts.

Configure an HTTPS `FORTH_PUBLIC_URL`, explicit `DJANGO_ALLOWED_HOSTS`, matching
`DJANGO_CSRF_TRUSTED_ORIGINS`, a unique `DJANGO_SECRET_KEY`, and `DJANGO_DEBUG=0`.
The reverse proxy must terminate TLS and overwrite forwarded headers before enabling
`DJANGO_TRUST_PROXY_HEADERS`. Keep database, Redis and renderer ports private.
Set `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` for password recovery. Reset links use the
canonical public URL, expire after an hour, and are single-use. Resetting a password
invalidates previously issued browser access tokens through the password-hash check.

The current SES sender is `Forth <forth@mahfouz.ca>` in `us-east-2`, using
`email-smtp.us-east-2.amazonaws.com:587` with STARTTLS and the existing verified
`mahfouz.ca` domain identity with DKIM. The dedicated `forth-ses-smtp` IAM user can
only send raw email from that address using that identity. SMTP credentials are kept
in the ignored, owner-readable `.env`; never commit or reuse them for other apps.
The separately verified `forth.mahfouz.ca` identity is currently unused. When moving
to a dedicated domain for cloud deployment, verify that domain and update both the
sender setting and the restricted IAM policy before switching mail delivery.
Rotate credentials by creating a new access key for that user, deriving the regional
SES SMTP password, updating `.env`, recreating the application services, then
deleting the old key after a successful check. SES production access is already
enabled in this region. This configures outgoing mail only; it does not create an inbox.

Run this on the deployment host before sharing access:

```bash
docker compose exec web python manage.py check_launch
docker compose exec web python manage.py check --deploy
```

Then verify a real recovery email, HTTPS access from outside the network, and a backup
restore. Publish the operator's contact, actual beta access terms, and backup retention
policy before collecting external users' resumes. The `/privacy` page describes the
implemented data flow; it does not establish those operator-specific policies.
Account deletion requires the current password and `DELETE`, and removes account rows
and associated uploaded/artifact files from active storage. Backups need their own
retention policy. Do not expose an installation with the known local demo credentials.

### Reproducible regression tests

The PostgreSQL test settings disable real provider calls and isolate test usage writes
inside the test transaction. The dedicated durability test still exercises the separate
usage connection and verifies that provider accounting survives workflow rollback.

```bash
docker compose run --rm --no-deps --entrypoint python web manage.py test core.tests --settings=forth.test_settings --noinput
npm --prefix frontend run test:auth
npm --prefix frontend run test:e2e
npm --prefix frontend audit
```

Browser integration tests create disposable accounts and remove their workspace after
completion. Run them against a local test deployment with invitation gating disabled;
never point the suite at production. Provider-backed import and the detailed interview
use synthetic career data; other browser tests use controlled API responses to cover
loading, failures, narrow screens and application review.

## Host containment and security review (2026-10-20)

The web app, workers and scheduler run as UID/GID `10001`, with all Linux
capabilities dropped, privilege escalation disabled and a read-only root filesystem.
Only `/app/data` and bounded temporary storage are writable. Nginx runs as UID 101
with the same restrictions and no access to uploaded files. No service mounts the
Docker socket, host home directory or AWS credentials. All services have memory,
CPU, process and log-rotation limits. Database/cache traffic uses a private internal
network; PDF rendering uses a separate internal network. Neither network service
has a published port. The default HTTP listener binds only to localhost.

Public-page downloads reject non-public destinations (including cloud metadata,
loopback and shared address space), credentials and custom ports. Connections are
pinned to the validated IP and retain original TLS hostname verification. Redirects
are handled explicitly and responses are bounded. Gotenberg blocks public/private
outbound requests and JavaScript, and unused LibreOffice routes are disabled. Local
HTML-to-PDF remains supported. Resume archives have decompression limits; PDFs have
a page limit; files and pasted text have size limits. Persistent file writes reserve
1 GiB of filesystem headroom. Login/recovery endpoints have proxy throttles on both
HTTP and HTTPS, plus connection and request limits. WebSocket origins are checked
against allowed hosts. Proxy access logs omit query strings, and duplicate backend
access logging is disabled so reset/WebSocket tokens do not enter routine logs. These are abuse controls, not a
volumetric DDoS defense or a hard storage quota.

For a fresh deployment, provision the data directory for UID/GID 10001 before
starting the services. Keep `.secrets` mode 0700 and `.env` mode 0600. The provider
secret now uses `.secrets/openai_api_key` rather than an environment-backed Docker
secret; make the file readable by the container UID (the current file is 0444 inside
the private host directory). The TLS install hook preserves access for non-root
Nginx while keeping the parent directory private. Back up the data directory,
including its account encryption key. MCP is an on-demand `tools` profile.

The review includes application boundary tests, account-ownership regressions,
real renderer rejection checks and Python/JavaScript dependency audits. Python's
packaging tooling was updated. The audit still reports
[CVE-2026-106454](https://github.com/twisted/twisted/security/advisories/GHSA-8pqf-f4m5-798g)
in Twisted 26.4.0: an authenticated IMAP regular-expression denial of service with
no published fixed release. Forth uses Twisted through Daphne for HTTP/WebSockets,
not an IMAP server; that protocol path is not exposed. Recheck upstream releases.
This review is not an independent penetration test or a complete OS-image CVE scan.

**Public hosting should use a dedicated VM/account with no access to your home LAN
or unrelated workloads.** Containers share the host kernel; these protections cannot
guarantee containment after a kernel/runtime exploit. Keep the host and Docker patched,
restrict ingress to the TLS proxy, block private-network/cloud-metadata egress at the
cloud firewall where possible, and avoid attaching a broad instance role. Put database
and file storage on capacity-limited disks with alerts and tested backups: app checks
cannot prevent every concurrent write or database-growth scenario. Network flood
protection and provider spending caps are separate deployment requirements.

References: [Docker service controls](https://docs.docker.com/reference/compose-file/services/)
and [Gotenberg outbound filtering](https://gotenberg.dev/docs/outbound-url-filtering).
