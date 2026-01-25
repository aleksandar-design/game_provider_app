import sqlite3

DB_PATH = "db/database.sqlite"

countries = [
    ("GBR", "GB", "United Kingdom"),
    ("USA", "US", "United States"),
    ("DEU", "DE", "Germany"),
    ("FRA", "FR", "France"),
    ("ESP", "ES", "Spain"),
    ("ITA", "IT", "Italy"),
    ("NLD", "NL", "Netherlands"),
    ("SWE", "SE", "Sweden"),
    ("NOR", "NO", "Norway"),
    ("FIN", "FI", "Finland"),
    ("DNK", "DK", "Denmark"),
    ("POL", "PL", "Poland"),
    ("CZE", "CZ", "Czech Republic"),
    ("ROU", "RO", "Romania"),
    ("BGR", "BG", "Bulgaria"),
    ("HRV", "HR", "Croatia"),
    ("HUN", "HU", "Hungary"),
    ("PRT", "PT", "Portugal"),
    ("IRL", "IE", "Ireland"),
    ("CHE", "CH", "Switzerland"),
]

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS countries (
    iso3 TEXT PRIMARY KEY,
    iso2 TEXT,
    name TEXT
)
""")

cur.executemany(
    "INSERT OR IGNORE INTO countries (iso3, iso2, name) VALUES (?, ?, ?)",
    countries
)

conn.commit()
conn.close()

print("✅ Countries table created and populated")
