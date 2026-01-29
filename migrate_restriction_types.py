"""
Migration: Simplify restriction types from BLOCKED/CONDITIONAL/REGULATED to RESTRICTED/REGULATED.
- BLOCKED -> RESTRICTED
- CONDITIONAL -> RESTRICTED
- REGULATED stays REGULATED

Run once to update existing database.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path("db") / "database.sqlite"

def migrate():
    print("Migrating restriction types...")
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = OFF;")

    # Check current data
    cur = con.execute("SELECT restriction_type, COUNT(*) FROM restrictions GROUP BY restriction_type")
    counts = dict(cur.fetchall())
    print(f"Current counts: {counts}")

    # Count what will be migrated
    blocked = counts.get("BLOCKED", 0)
    conditional = counts.get("CONDITIONAL", 0)
    regulated = counts.get("REGULATED", 0)

    if blocked == 0 and conditional == 0:
        print("No BLOCKED or CONDITIONAL records to migrate.")
        # Check if already using RESTRICTED
        restricted = counts.get("RESTRICTED", 0)
        if restricted > 0:
            print(f"Already using RESTRICTED ({restricted} records). Migration not needed.")
            con.close()
            return

    # Step 1: Create new table with updated constraint
    print("Creating new table with updated constraint...")
    con.execute("""
        CREATE TABLE restrictions_new (
            provider_id       INTEGER NOT NULL,
            country_code      TEXT NOT NULL,
            restriction_type  TEXT NOT NULL DEFAULT 'RESTRICTED' CHECK(restriction_type IN ('RESTRICTED','REGULATED')),
            source            TEXT,
            PRIMARY KEY (provider_id, country_code),
            FOREIGN KEY (provider_id) REFERENCES providers(provider_id) ON DELETE CASCADE
        )
    """)

    # Step 2: Copy data, converting BLOCKED/CONDITIONAL to RESTRICTED
    print("Migrating data...")
    con.execute("""
        INSERT INTO restrictions_new (provider_id, country_code, restriction_type, source)
        SELECT
            provider_id,
            country_code,
            CASE
                WHEN restriction_type IN ('BLOCKED', 'CONDITIONAL') THEN 'RESTRICTED'
                ELSE restriction_type
            END,
            source
        FROM restrictions
    """)

    # Step 3: Drop old table and rename new
    print("Replacing old table...")
    con.execute("DROP TABLE restrictions")
    con.execute("ALTER TABLE restrictions_new RENAME TO restrictions")

    con.execute("PRAGMA foreign_keys = ON;")
    con.commit()

    # Verify
    cur = con.execute("SELECT restriction_type, COUNT(*) FROM restrictions GROUP BY restriction_type")
    new_counts = dict(cur.fetchall())
    print(f"After migration: {new_counts}")

    con.close()
    print(f"Migration complete! Converted {blocked} BLOCKED + {conditional} CONDITIONAL -> RESTRICTED")

if __name__ == "__main__":
    migrate()
