import argparse
from pathlib import Path

from sqlalchemy import text

from app.db.connection import get_engine
from app.utils.logging import configure_logging


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def run_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> None:
    engine = get_engine()
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        raise FileNotFoundError(f"No migrations found in {migrations_dir}")

    with engine.begin() as connection:
        for migration in files:
            sql = migration.read_text(encoding="utf-8")
            connection.exec_driver_sql(sql)
            print(f"Applied {migration.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SQL migrations.")
    parser.add_argument("--dir", type=Path, default=MIGRATIONS_DIR)
    args = parser.parse_args()
    configure_logging()
    run_migrations(args.dir)


if __name__ == "__main__":
    main()
