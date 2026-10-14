# Forth MCP integration

`backend/mcp_server.py` exposes Forth as a local stdio Model Context Protocol server. It directly invokes the owner-scoped Django domain operations, so recording a browser-found job uses the same normalization, deduplication, matching, application, and document-validation logic as the app.

## Register a local server

Configure an MCP client to run the following command from the repository root. Replace the email with the owner of the private Forth workspace.

```json
{
  "mcpServers": {
    "forth-job-seeker": {
      "command": "docker",
      "args": [
        "compose",
        "-f", "/absolute/path/to/forth/docker-compose.yml",
        "run", "--rm", "-i",
        "-e", "FORTH_MCP_OWNER_EMAIL=you@example.com",
        "mcp"
      ],
      "env": {
        "COMPOSE_PROJECT_NAME": "forth"
      }
    }
  }
}
```

The adapter refuses to start work if neither `FORTH_MCP_OWNER_EMAIL` nor `FORTH_MCP_OWNER_ID` is set. Do not place passwords, API keys, or resume files in the MCP configuration.

For deployed environments, include `backend/mcp_server.py` in the normal Forth image build. Local Docker Compose mounts the adapter into the existing Forth image automatically.

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
