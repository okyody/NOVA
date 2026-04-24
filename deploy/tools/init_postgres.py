"""Initialize NOVA Postgres runtime tables from SQL file."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SQL_PATH = ROOT / "init_postgres.sql"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres-url", required=True)
    args = parser.parse_args()

    import asyncpg

    sql = SQL_PATH.read_text(encoding="utf-8")
    conn = await asyncpg.connect(args.postgres_url)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()

    print("postgres_init_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
