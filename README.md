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

Forth can be used as an owner-scoped local MCP server for browser-assisted job research, explainable matching, and claim-validated application drafts. See [the MCP integration guide](docs/mcp-integration.md) for setup and the confirmation boundaries around external applications.

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
