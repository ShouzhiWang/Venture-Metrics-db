#!/usr/bin/env bash
# =============================================================================
# data-center-agent runner script
# Stable entrypoints for Hermes to call workers consistently.
# Usage: ./run.sh <command> [args...]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PROJECT_DIR="$SCRIPT_DIR"

# Activate virtual environment
if [ -f "$VENV/bin/activate" ]; then
    source "$VENV/bin/activate"
else
    echo "ERROR: Virtual environment not found at $VENV" >&2
    exit 1
fi

# Change to project directory
cd "$PROJECT_DIR"

# Ensure .env is loaded
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

COMMAND="${1:-help}"
shift 2>/dev/null || true

case "$COMMAND" in
    migrate)
        echo "Running database migrations..."
        python -m app.db.migrate "$@"
        ;;
    ingest-excel)
        if [ $# -lt 1 ]; then
            echo "Usage: ./run.sh ingest-excel --path <excel-file>" >&2
            exit 1
        fi
        echo "Ingesting Excel: $*"
        python -m app.workers.ingest_excel "$@"
        ;;
    process-source)
        if [ $# -lt 1 ]; then
            echo "Usage: ./run.sh process-source --source-id <uuid>" >&2
            exit 1
        fi
        echo "Processing source: $*"
        python -m app.workers.process_source "$@"
        ;;
    process-report)
        if [ $# -lt 1 ]; then
            echo "Usage: ./run.sh process-report --report-id <uuid>" >&2
            exit 1
        fi
        echo "Processing report: $*"
        python -m app.workers.process_report "$@"
        ;;
    generate-codebook)
        if [ $# -lt 1 ]; then
            echo "Usage: ./run.sh generate-codebook --report-id <uuid>" >&2
            exit 1
        fi
        echo "Generating codebook: $*"
        python -m app.workers.generate_codebook "$@"
        ;;
    ask)
        if [ $# -lt 1 ]; then
            echo "Usage: ./run.sh ask \"<question>\"" >&2
            exit 1
        fi
        echo "Asking: $*"
        python -m app.workers.ask "$@"
        ;;
    backup)
        BACKUP_DIR="${BACKUP_DIR:-/data/hermes/backups}"
        TIMESTAMP=$(date +%F_%H%M%S)
        BACKUP_FILE="$BACKUP_DIR/dca_${TIMESTAMP}.dump"
        CONTAINER="${PG_CONTAINER:-data-center-agent-postgres}"
        mkdir -p "$BACKUP_DIR"
        echo "Backing up to $BACKUP_FILE..."
        sg docker -c "docker exec $CONTAINER \
            pg_dump -U postgres -d data_center_agent -Fc" \
            > "$BACKUP_FILE"
        echo "Backup complete: $BACKUP_FILE"
        ls -lh "$BACKUP_FILE"
        ;;
    tests)
        echo "Running tests..."
        python -m pytest tests/ -v "$@"
        ;;
    help|*)
        echo "data-center-agent runner"
        echo ""
        echo "Commands:"
        echo "  migrate                         Run database migrations"
        echo "  ingest-excel   <args>           Ingest Excel source list"
        echo "  process-source <args>           Fetch and store a source"
        echo "  process-report <args>           Parse a report into chunks"
        echo "  generate-codebook <args>        Generate variable codebook"
        echo "  ask            <args>           Keyword search over data"
        echo "  backup                          Dump PostgreSQL to /data/hermes/backups/"
        echo "  tests           [args]          Run pytest suite"
        echo ""
        echo "Examples:"
        echo "  ./run.sh migrate"
        echo "  ./run.sh ingest-excel --path data/input/reports.xlsx"
        echo "  ./run.sh process-source --source-id <uuid>"
        echo "  ./run.sh process-report --report-id <uuid>"
        echo "  ./run.sh generate-codebook --report-id <uuid>"
        echo "  ./run.sh ask \"employment rate definition\""
        echo "  ./run.sh backup"
        ;;
esac
