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

`process_source` detects actual content type from headers and file signatures. PDF/HTML sources create sparse `reports` rows; CSV/XLSX sources create `datasets` rows.

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
