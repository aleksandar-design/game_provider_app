import sqlite3
from pathlib import Path

import pycountry

DB_PATH = Path("db") / "database.sqlite"

def main():
    if not DB_PATH.exists():
        raise SystemExit("Database not found. Run: py db_init.py then py importer.py")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Create table if not exists
    cur.execute("""
    CREATE TABLE IF NOT EXISTS countries (
        iso3 TEXT PRIMARY KEY,
        iso2 TEXT,
        name TEXT
    )
    """)

    # Build full ISO list
    rows = []
    for c in pycountry.countries:
        iso2 = getattr(c, "alpha_2", None)
        iso3 = getattr(c, "alpha_3", None)
        name = getattr(c, "name", None)

        if iso3 and name:
            rows.append((iso3, iso2, name))

    # Upsert (insert if new, update if exists)
    cur.executemany("""
    INSERT INTO countries (iso3, iso2, name)
    VALUES (?, ?, ?)
    ON CONFLICT(iso3) DO UPDATE SET
        iso2=excluded.iso2,
        name=excluded.name
    """, rows)

    conn.commit()

    # Show summary
    count = cur.execute("SELECT COUNT(*) FROM countries").fetchone()[0]
    conn.close()

    print(f"✅ Loaded {count} ISO countries into countries table.")

if __name__ == "__main__":
    main()
