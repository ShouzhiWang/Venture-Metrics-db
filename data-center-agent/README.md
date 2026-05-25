# Data Center Agent

Internal research/data integration pipeline for ingesting government reports and related datasets from spreadsheet links. The MVP stores raw files on local disk, keeps PostgreSQL as the source of truth, and creates deterministic worker entrypoints that Hermes can run from Slack or scheduled jobs.

## Architecture

- PostgreSQL + pgvector stores source metadata, reports, parsed chunks, datasets, variable codebooks, and future embeddings.
- Local filesystem storage keeps PDFs, HTML, tables, extracted text, and parsed JSON outside the database.
- Repository classes isolate SQL from agents and workers.
- Agents perform source classification, fetching, parsing, report reading placeholders, codebook extraction stubs, and keyword search.
- CLI workers are stable runtime entrypoints for Hermes.
- LLM-dependent extraction is intentionally stubbed so the first version runs without API keys.

## Local Setup

```bash
cd data-center-agent
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

For OpenAI Batch extraction, set `OPENAI_API_KEY` in `.env`. Optional batch settings include `OPENAI_BATCH_MODEL`, `OPENAI_BATCH_REVIEW_MODEL`, `OPENAI_BATCH_MAX_INPUT_TOKENS_PER_REPORT`, and `OPENAI_BATCH_PROMPT_VERSION`.

For local embedding-powered search, install the embeddings extra:

```bash
pip install -e ".[embeddings]"
```

Configure one active embedding model at a time:

```bash
EMBEDDING_PROVIDER=local
LOCAL_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
LOCAL_EMBEDDING_FALLBACK_MODEL=BAAI/bge-m3
EMBEDDING_DIMENSION=1024
EMBEDDING_NORMALIZE=true
```

The retrieval layer does not require `OPENAI_API_KEY`, and it does not call OpenAI for embeddings. If you switch `LOCAL_EMBEDDING_MODEL`, rebuild the `search_index` embeddings before semantic search so a query is never compared against vectors from a different model.

## Docker PostgreSQL

```bash
docker compose up -d
python -m app.db.migrate
```

The default `DATABASE_URL` is:

```bash
postgresql+psycopg://postgres:postgres@localhost:5432/data_center_agent
```

## Workers

Ingest Excel links. The sheet must contain at least one column named `url`, `link`, `source_url`, `original_url`, or `href`.
The Excel file is treated only as a seed list: the worker reads and normalizes URLs, guesses an initial source type from the URL, and creates minimal `sources` rows with `crawl_status='pending'`. Titles, publishers, report years, article text, and other metadata are filled by later workers when evidence is available.

```bash
python -m app.workers.ingest_excel --path data/input/reports.xlsx
```

Fetch and store one source:

```bash
python -m app.workers.process_source --source-id <uuid>
```

`process_source` detects actual content type from headers and file signatures. Direct PDF URLs still create sparse `reports` rows; CSV/XLSX sources create `datasets` rows. HTML sources are resolved by default: if the page contains a verified downloadable PDF/report or dataset link, the worker creates or reuses a child `sources` row and marks the HTML source as a `landing_page` with `resolution_status='resolved'`. The child is not processed recursively unless explicitly requested:

```bash
python -m app.workers.process_source --source-id <uuid> --process-resolved
```

For selected sources that need rendered JavaScript, opt into browser resolution:

```bash
python -m app.workers.process_source --source-id <uuid> --resolve-mode auto
python -m app.workers.process_source --source-id <uuid> --resolve-mode browser --no-clicks
```

Resolve one HTML source without changing the database:

```bash
python -m app.workers.resolve_source --source-id <uuid> --dry-run --mode auto
```

Create or reuse a child PDF/dataset source from a landing page:

```bash
python -m app.workers.resolve_source --source-id <uuid>
```

Resolve and immediately process the child source:

```bash
python -m app.workers.resolve_source --source-id <uuid> --process-resolved
```

Resolution modes:

- `static`: parse saved/fetched HTML with BeautifulSoup only. This remains the default for `process_source`.
- `auto`: try static resolution first, then render the page with Playwright if static HTML has no verified artifact and the page looks unresolved or browser-dependent. This is the default for `resolve_source`.
- `browser`: render with Playwright and inspect rendered DOM, network responses, and safe download clicks.

Browser resolution requires the optional browser extra and Playwright browsers:

```bash
pip install -e ".[browser]"
playwright install chromium
```

The resolver follows direct links and only clicks safe download/report controls when browser mode is enabled. Gated pages, login pages, email forms, and subscription walls are classified as `gated_or_paywalled` or `needs_browser`; the pipeline does not submit forms, use credentials, or bypass access controls. Manual download or provider-specific public API integration is still required for those sources.

Parse one report into extracted text and chunks:

```bash
python -m app.workers.process_report --report-id <uuid>
```

`process_report` parses the raw file, writes `raw_text.txt`, `parsed.json`, and `pages.json`, inserts `document_chunks`, enriches report metadata where possible, and marks the source `parsed`.

Generate rule-based placeholder codebook entries:

```bash
python -m app.workers.generate_codebook --report-id <uuid>
```

Create an OpenAI Batch JSONL for LLM codebook extraction without submitting it:

```bash
python -m app.workers.create_extraction_batch --limit 5 --dry-run
```

Submit a small OpenAI Batch extraction job:

```bash
python -m app.workers.create_extraction_batch --limit 5 --submit
```

Check an asynchronous batch job. OpenAI Batch jobs can take up to 24 hours:

```bash
python -m app.workers.batch_status --batch-id <db_uuid_or_openai_batch_id>
```

Import completed extraction results and export review CSVs. By default this does not insert variables:

```bash
python -m app.workers.import_extraction_batch \
  --batch-id <db_uuid_or_openai_batch_id> \
  --review-csv /data/hermes/reviews/codebook_review_llm.csv \
  --export-rejected
```

Optionally create and import a second LLM reviewer batch over parsed extraction outputs:

```bash
python -m app.workers.create_review_batch --batch-id <extraction_batch_id> --submit
python -m app.workers.import_review_batch \
  --batch-id <review_batch_id> \
  --review-csv /data/hermes/reviews/codebook_review_llm_decisions.csv
```

Insert only after review when you explicitly opt in:

```bash
python -m app.workers.import_extraction_batch \
  --batch-id <db_uuid_or_openai_batch_id> \
  --review-csv /data/hermes/reviews/codebook_review_llm.csv \
  --insert \
  --min-confidence 0.75
```

The LLM batch pipeline sends selected high-signal chunks, not full PDFs. It excludes reference-like chunks before prompt creation, verifies evidence quotes after import, and never marks variables approved automatically. Accepted and rejected rows remain reviewable in CSV outputs.

Run keyword search over chunks and report variables:

```bash
python -m app.workers.ask "employment rate definition"
```

Build the rebuildable retrieval index without embedding anything:

```bash
python -m app.workers.build_search_index --object-types variable,report,source --limit 100 --dry-run
python -m app.workers.build_search_index --object-types variable,report,source,dataset --limit 100
```

Embed a small pending batch with the active local model:

```bash
python -m app.workers.embed_search_index --limit 20
```

The embedding worker loads `LOCAL_EMBEDDING_MODEL`, probes the actual dimension, validates it against `EMBEDDING_DIMENSION`, normalizes vectors when `EMBEDDING_NORMALIZE=true`, and stores provider/model/dimension metadata alongside `vector(1024)` embeddings. If Qwen3 loading fails and `LOCAL_EMBEDDING_FALLBACK_MODEL` is configured, it tries BGE-M3 and records the actual model used.

Run semantic or hybrid search. If no compatible embeddings exist, the worker falls back to keyword search and prints a warning:

```bash
python -m app.workers.semantic_search "startup funding in Singapore" --limit 10 --hybrid --json
```

Ask the data discovery worker for user-style requests:

```bash
python -m app.workers.find_data "I want data about SME digital adoption in Singapore" --limit 10 --json
python -m app.workers.find_data "VC deal count by stage" --public-only --json
```

## Demo-safe tools

The demo chatbot must call only the allowlisted tool surface in `app.tools.demo`. It does not expose arbitrary shell commands, ingestion, deletion, migrations, embedding rebuilds, report parsing, LLM batch creation/import, or other batch-processing workers.

Read tools use `DEMO_READ_DATABASE_URL` when set, otherwise `DATABASE_URL`, and run inside a read-only transaction where supported by the database. `submit_feedback` is the only demo-safe write tool.

Run a tool from CLI:

```bash
python -m app.tools.demo find_data --args '{"query":"startup funding in Singapore","limit":3,"public_only":true}'
python -m app.tools.demo semantic_search --args '{"query":"VC deal count","object_types":["variable","dataset"],"limit":3}'
python -m app.tools.demo get_variable_detail --args '{"variable_id":"<variable_uuid>"}'
python -m app.tools.demo get_report_detail --args '{"report_id":"<report_uuid>"}'
python -m app.tools.demo get_source_detail --args '{"source_id":"<source_uuid>"}'
python -m app.tools.demo get_organization_detail --args '{"organization_id":"<organization_uuid>"}'
python -m app.tools.demo compare_concepts --args '{"query_or_concept_id":"venture funding","report_ids":["<report_uuid>"]}'
python -m app.tools.demo compare_concepts_auto --args '{"query":"Compare startup funding definitions across reports","limit_reports":5}'
python -m app.tools.demo list_available_filters --args '{}'
python -m app.tools.demo job_status --args '{"job_id":"<job_uuid>"}'
python -m app.tools.demo submit_feedback --args '{"answer_id":"answer-123","feedback_type":"thumbs_up","comment":"Useful result."}'
python -m app.tools.demo readiness_report
```

Every tool returns structured JSON:

```json
{"ok": true, "tool": "find_data", "data": {}}
```

Errors use a stable shape:

```json
{"ok": false, "tool": "find_data", "error": {"code": "invalid_args", "message": "query is required."}}
```

The registries in `app/tools/registry.py` and `app/tools/registry.json` document each tool name, arguments, return shape, read/write risk, and demo-safe status. The readiness report is in `DEMO_TOOL_READINESS_REPORT.md`.

`compare_concepts_auto` is intended for demo/chatbot concept-comparison questions where users do not know report IDs. It is read-only: it searches existing indexed variables/reports first, auto-selects a small set of relevant reports, then delegates to the existing `compare_concepts` logic. It does not ingest sources, extract codebooks, run embeddings, or modify the database. The demo chatbot should prefer `compare_concepts_auto` for natural-language comparison requests; raw `compare_concepts` is for cases where report IDs are already known.

Examples:

```bash
python -m app.workers.compare_concepts_auto "Compare startup funding definitions across reports"
python -m app.workers.compare_concepts_auto "How do reports define VC investment differently?" --debug
python -m app.workers.compare_concepts_auto "Compare R&D expenditure metrics" --public-only
python -m app.workers.compare_concepts_auto "Are startup funding metrics comparable across reports?" --json
```

Export fixed retrieval evaluation queries for manual inspection:

```bash
python -m app.workers.evaluate_search_quality --limit 10
```

## MVP demo website

The MVP website is a separate demo app under `web/`. It exposes a small API and a single React page for the future data robot experience. Chat uses a guarded MiMo LLM layer: the model plans a strict JSON tool request, the backend validates it against the demo-safe allowlist, and the model then summarizes only the returned tool results. It does not expose ingestion, parsing, extraction, migrations, embedding jobs, file uploads, deletion, or shell commands.

Install web backend dependencies:

```bash
pip install -e ".[web]"
```

Run the API locally:

```bash
cd data-center-agent
uvicorn web.backend.app:app --host 127.0.0.1 --port 8000
```

Run the frontend locally:

```bash
cd data-center-agent/web/frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` requests to `http://127.0.0.1:8000`.

Frontend routes:

- `/`: redirects to `/data`.
- `/about`: product methodology, source availability, and limitations.
- `/data`: main data discovery chat/search page.
- `/login` and `/register`: placeholder auth pages for the MVP.
- `/history`: placeholder protected history page.
- `/projects` and `/projects/:id`: placeholder research project pages.
- `/map`: placeholder dynamic map page.

Useful API calls:

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Startup funding in Singapore"}'

curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Compare startup funding definitions across reports"}'
```

Example demo queries:

- Startup funding in Singapore
- VC deal count by stage
- R&D expenditure as percentage of GDP
- SME digital adoption
- Compare startup funding definitions across reports
- Shenzhen startup organizations

Environment variables:

- `DATABASE_URL`: primary database URL.
- `DEMO_READ_DATABASE_URL`: optional read-only database URL for demo read tools.
- `LOG_LEVEL`: backend logging level.
- `DEMO_LLM_API_KEY`: required MiMo API key for `/api/chat`.
- `DEMO_LLM_BASE_URL`: OpenAI-compatible MiMo base URL, default `https://api.mimo-v2.com/v1`.
- `DEMO_LLM_MODEL`: demo chat model, default `mimo-v2.5`.
- `DEMO_LLM_TIMEOUT_SECONDS`: provider timeout, default `30`.
- `DEMO_LLM_MAX_OUTPUT_TOKENS`: max planner/answer output tokens, default `900`.
- `AUTH_SESSION_SECRET`: required secret for signed login sessions. Generate a long random value for any shared deployment.
- `AUTH_COOKIE_SECURE`: set to `true` when serving over HTTPS.
- `AUTH_SESSION_TTL_SECONDS`: login session lifetime, default `1209600` seconds.

Before using login/register on an existing database, apply migrations:

```bash
python -m app.db.migrate
```

Deployment notes for Hermes:

- Run the API and frontend as separate services behind Nginx.
- Put Basic Auth or another access control layer in front of the demo if it is internet-accessible.
- Do not expose Postgres directly.
- Keep secrets only on the backend host; the frontend has no database credentials.
- Keep the API route allowlist limited to `web/backend/services/tool_client.py`.

Docker deployment:

```bash
cd data-center-agent
cp web/.env.demo.example web/.env.demo
docker compose --env-file web/.env.demo -f docker-compose.yml -f docker-compose.demo.yml up -d --build
```

This starts:

- `postgres`: existing pgvector database.
- `web-api`: FastAPI demo API, reachable only inside the Compose network.
- `web`: Nginx serving the built React app and proxying `/api/*` to `web-api`.

By default the public demo listens on `http://127.0.0.1:8080` if run locally, or port `8080` on the server unless `WEB_PORT` is changed.

For public exposure, put your server-level Nginx or load balancer in front of the `web` service. The frontend Nginx config is at `web/frontend/nginx.conf`; it includes security headers and commented Basic Auth directives. To enable Basic Auth inside the container, mount an htpasswd file at `/etc/nginx/.htpasswd` and uncomment the `auth_basic` lines.

Current limitations:

- `/api/chat` requires `DEMO_LLM_API_KEY`; if it is missing, the API returns a structured configuration error.
- Result quality depends on the existing `search_index` and embedded/keyword retrieval state.
- The site is intentionally read-only except for lightweight feedback.

`search_index` is additive and rebuildable. Core records stay in `sources`, `reports`, `report_variables`, `datasets`, and `document_chunks`. Chunk indexing is intentionally limited to high-value chunks or evidence-linked chunks; the default build indexes variables, reports, sources, and datasets. Embeddings improve retrieval quality but are not required for ingestion, parsing, source resolution, or codebook extraction.

## Data Layout

- `data/raw/<source_id>/...`: fetched raw files and pages.
- `data/parsed/<report_id>/raw_text.txt`: extracted report text.
- `data/parsed/<report_id>/parsed.json`: lightweight parser output.

Do not store large PDFs, tables, or parsed blobs directly in PostgreSQL. Store paths and checksums in the database.

## Source Statuses

- `pending`: seed URL exists but has not been fetched.
- `fetched`: raw content was fetched and stored.
- `parsed`: a report source was parsed into text/chunks.
- `failed`: fetch or local file read failed.
- `needs_browser`: reserved for pages requiring browser automation.
- `inaccessible`: URL appears unavailable, such as a 404.
- `private_or_paywalled`: source appears gated, private, or paywalled.

## Source Resolution Metadata

- `source_role`: semantic role of a row, such as `seed_url`, `landing_page`, `report_pdf`, `dataset_file`, `html_report_body`, or `gated_or_paywalled`.
- `resolution_status`: resolution state for landing/seed URLs, such as `not_needed`, `resolved`, `unresolved`, `needs_browser`, `gated_or_paywalled`, or `failed`.
- `parent_source_id`: parent landing/seed source when a child artifact source was discovered.
- `resolved_source_id`: child source selected as the best verified artifact for a landing page.
- `discovered_artifacts`: ranked resolver candidates and verification metadata.

Child source creation is duplicate-safe by `sources.original_url`; if the resolved PDF or dataset URL already exists, the landing page points to that existing source instead of creating a duplicate.

## Backup

```bash
mkdir -p backups
pg_dump "$DATABASE_URL" -Fc -f backups/hermes_$(date +%F).dump
```

If `pg_dump` does not accept the SQLAlchemy `postgresql+psycopg://` URL, export a libpq URL first:

```bash
export PG_DUMP_URL=postgresql://postgres:postgres@localhost:5432/data_center_agent
pg_dump "$PG_DUMP_URL" -Fc -f backups/hermes_$(date +%F).dump
```

## Production Safety Notes

- Do not expose PostgreSQL publicly.
- Keep secrets in `.env` or a server secret manager, never in git.
- Use scheduled backups and restore drills.
- Keep raw files outside PostgreSQL and back up storage separately.
- Run migrations from version-controlled SQL files.
- Keep Hermes limited to fixed worker commands rather than arbitrary code-writing or schema changes.
- Keep the storage adapter boundary intact so local paths can later move to Aliyun OSS, Tencent COS, Huawei OBS, or another object store.

## Tests

```bash
pytest
```
