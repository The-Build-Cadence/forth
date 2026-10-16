# Account usage monitoring

The sidebar shows estimated gross USD costs for OpenAI (text generation and embeddings) and Brave web search. The compact widget displays only the two all-time totals, with estimate and currency information on hover. Totals refresh every 15 seconds. Monthly totals, request counts, background requests and unknown-cost counts remain available through the API and MCP. Only the authenticated account's usage is available at `GET /api/usage/` or the MCP `get_usage_summary` tool.

Tracking starts when this feature is installed. Existing provider invoices cannot be attributed retrospectively from a shared API key. Estimates exclude provider credits, tax, discounts and negotiated pricing. Brave requests are charged per search call, not per result returned; fetched employer pages and local cache/fallback operations do not count as provider requests.

Default rates (verified October 16, 2026):

- [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini): $0.40 input, $0.10 cached input, $1.60 output per million tokens.
- [text-embedding-3-large](https://developers.openai.com/api/docs/models/text-embedding-3-large): $0.13 per million input tokens.
- [Brave Search](https://brave.com/search/api/): $5 per 1,000 requests before credits.

Set `BRAVE_COST_PER_1000_REQUESTS` to match your subscription. `OPENAI_USAGE_RATES_JSON` adds/overrides model entries with `[input, cached_input, output]` rates per million tokens. For example, `{"my-model":["1","0.25","4"]}`. Dated OpenAI snapshots use their base model's rates. Unknown models and responses without usage remain explicitly unpriced. Rates are saved with each request; changing configuration never reprices history.

Every request requires an owner. HTTP middleware resolves the DRF-authenticated user; MCP dispatch resolves its authenticated owner; task decorators resolve ownership from the stored document, job, run, or profile. Beat marks source runs as scheduled. Background actions started by a user also count toward that user. When adding a new provider or worker entry point, use `usage_context` / `metered_task` and the metered provider wrappers. Do not pass account IDs from unauthenticated input.

A pending ledger row is inserted before each provider call. Successful responses record actual reported tokens, including cached input, and estimated cost before downstream parsing. Failed/timeout calls retain an unknown cost; interrupted workers leave pending rows, also counted as unknown. SDK retries are disabled so attempts cannot happen invisibly. A user retry is a new request.

On PostgreSQL, the `usage` database alias points to the same database using a separate autocommit connection. Usage survives workflow transaction rollbacks and worker termination. Migrate the default database normally; there is no separate usage database to migrate. SQLite development/testing uses the default connection and does not offer independent accounting commits inside workflow transactions. Ledger records contain metadata and counts, never prompts, resume text, search queries, or credentials.
