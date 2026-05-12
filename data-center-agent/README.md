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

```bash
python -m app.workers.ingest_excel --path data/input/reports.xlsx
```

Fetch and store one source:

```bash
python -m app.workers.process_source --source-id <uuid>
```

Parse one report into extracted text and chunks:

```bash
python -m app.workers.process_report --report-id <uuid>
```

Generate rule-based placeholder codebook entries:

```bash
python -m app.workers.generate_codebook --report-id <uuid>
```

Run keyword search over chunks and report variables:

```bash
python -m app.workers.ask "employment rate definition"
```

## Data Layout

- `data/raw/<source_id>/...`: fetched raw files and pages.
- `data/parsed/<report_id>/raw_text.txt`: extracted report text.
- `data/parsed/<report_id>/parsed.json`: lightweight parser output.

Do not store large PDFs, tables, or parsed blobs directly in PostgreSQL. Store paths and checksums in the database.

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
