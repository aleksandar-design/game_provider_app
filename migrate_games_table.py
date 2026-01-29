"""
Migration script to update games table schema for API sync.
Run this once to add new columns to existing database.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path("db") / "database.sqlite"

def migrate():
    print("Migrating games table...")
    con = sqlite3.connect(DB_PATH)

    # Check current columns
    cur = con.execute("PRAGMA table_info(games)")
    existing_cols = {row[1] for row in cur.fetchall()}
    print(f"Existing columns: {existing_cols}")

    # New columns to add
    new_columns = [
        ("game_id", "INTEGER"),
        ("title", "TEXT"),
        ("platform", "TEXT"),
        ("subtype", "TEXT"),
        ("enabled", "INTEGER DEFAULT 1"),
        ("fun_mode", "INTEGER DEFAULT 0"),
        ("rtp", "REAL"),
        ("volatility", "TEXT"),
        ("features", "TEXT"),
        ("themes", "TEXT"),
        ("tags", "TEXT"),
        ("thumbnail", "TEXT"),
        ("api_provider", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_cols:
            print(f"  Adding column: {col_name}")
            con.execute(f"ALTER TABLE games ADD COLUMN {col_name} {col_type}")

    # Rename old columns if they exist (migrate data)
    if "game_title" in existing_cols and "title" not in existing_cols:
        print("  Copying game_title -> title")
        con.execute("UPDATE games SET title = game_title WHERE title IS NULL")

    if "wallet_game_id" in existing_cols and "game_id" not in existing_cols:
        print("  Copying wallet_game_id -> game_id (where numeric)")
        # Only copy if it's numeric
        con.execute("""
            UPDATE games
            SET game_id = CAST(wallet_game_id AS INTEGER)
            WHERE wallet_game_id IS NOT NULL
            AND wallet_game_id GLOB '[0-9]*'
            AND game_id IS NULL
        """)

    # Create index if not exists
    con.execute("CREATE INDEX IF NOT EXISTS idx_games_game_id ON games(game_id)")

    con.commit()
    con.close()
    print("Migration complete!")

if __name__ == "__main__":
    migrate()
