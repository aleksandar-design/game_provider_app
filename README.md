# Game Providers App

A Streamlit web application for managing game provider data, including country restrictions and supported currencies. The app allows filtering providers by country and currency, viewing detailed provider information, and importing provider data from Excel files.

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema)
- [Setup](#setup)
- [Running the App](#running-the-app)
- [Importing Data](#importing-data)
- [Admin Features](#admin-features)
- [Configuration](#configuration)
- [Scripts Reference](#scripts-reference)

---

## Features

- **Browse Providers**: View all game providers in a searchable, filterable table
- **Filter by Country**: Find providers that are NOT restricted in a specific country
- **Filter by Currency**: Find providers that support a specific FIAT or Crypto currency
- **Provider Details**: View restricted countries and supported currencies for each provider
- **Export to Excel**: Download filtered results as Excel file
- **Admin Panel**: AI-assisted import of provider data from Excel files
- **Google Sheets Sync**: Automatic import from Google Drive folder
- **Three-tier Restrictions**: Distinguishes BLOCKED, CONDITIONAL, and REGULATED countries
- **Separate Currency Tables**: FIAT and Crypto currencies stored in separate tables
- **Database Backups**: Automatic backups before each sync
- **Persistent Login**: "Keep me signed in" option to stay logged in across page refreshes
- **Light/Dark Theme**: Toggle between light and dark modes (preference persists in URL)

---

## Tech Stack

| Category | Technology | Version/Details |
|----------|------------|-----------------|
| **Language** | Python | 3.11+ |
| **Web Framework** | Streamlit | Web UI framework for data apps |
| **Database** | SQLite | Lightweight, file-based relational database |
| **Data Processing** | Pandas | Data manipulation and analysis |
| **Excel Handling** | openpyxl | Read/write Excel files (.xlsx) |
| **AI Integration** | OpenAI API | gpt-4o-mini for AI-assisted imports |
| **Google Services** | Google Drive API | Folder/file access for sync |
| | Google Sheets API | Spreadsheet data extraction |
| | google-auth | Service account authentication |
| **Country Data** | pycountry | ISO 3166 country codes (optional) |

---

## Project Structure

```
game_provider_app/
├── app.py                  # Main Streamlit application
├── db_init.py              # Database schema initialization
├── google_sync.py          # Google Sheets sync script (NEW)
├── importer.py             # Batch import from Excel via config.csv
├── create_countries.py     # Populate countries table (basic list)
├── create_full_countries.py # Populate countries table (full ISO list)
├── generate_config.py      # Auto-generate config.csv from Excel files
├── inspect_xlsx.py         # Debug tool to inspect Excel structure
├── config.csv              # Configuration for batch import
├── requirements.txt        # Python dependencies
├── service_account.json    # Google service account key (not in git)
├── .env.example            # Environment variables template
├── .gitignore              # Git ignore rules
├── .streamlit/
│   ├── config.toml         # Streamlit theme configuration
│   └── secrets.toml        # Secrets (not in git)
├── .devcontainer/
│   └── devcontainer.json   # VS Code / GitHub Codespaces config
├── db/
│   ├── database.sqlite     # Main database (production)
│   ├── staging.sqlite      # Staging database (safe import target)
│   └── backups/            # Automatic database backups
└── data_sources/           # Excel files for import (.xlsx)
```

---

## Database Schema

The app uses SQLite with the following tables:

### `providers`
| Column | Type | Description |
|--------|------|-------------|
| provider_id | INTEGER | Primary key |
| provider_name | TEXT | Provider display name |
| status | TEXT | DRAFT or ACTIVE |
| currency_mode | TEXT | LIST (specific currencies) or ALL_FIAT (supports all) |
| google_sheet_id | TEXT | Google Sheet ID (for sync tracking) |
| last_synced | TEXT | Last sync timestamp |
| notes | TEXT | Optional notes |

### `restrictions`
| Column | Type | Description |
|--------|------|-------------|
| provider_id | INTEGER | Foreign key to providers |
| country_code | TEXT | ISO3 country code (e.g., USA, GBR) |
| restriction_type | TEXT | **BLOCKED** (fully blocked), **CONDITIONAL** (can open with docs), or **REGULATED** (requires license) |
| source | TEXT | Import source identifier |

### `fiat_currencies`
| Column | Type | Description |
|--------|------|-------------|
| provider_id | INTEGER | Foreign key to providers |
| currency_code | TEXT | ISO4217 code (e.g., USD, EUR, GBP) |
| display | INTEGER | 1 = visible, 0 = hidden |
| source | TEXT | Import source identifier |

### `crypto_currencies`
| Column | Type | Description |
|--------|------|-------------|
| provider_id | INTEGER | Foreign key to providers |
| currency_code | TEXT | Crypto symbol (e.g., BTC, ETH, USDT) |
| display | INTEGER | 1 = visible, 0 = hidden |
| source | TEXT | Import source identifier |

### `currencies` (Legacy)
| Column | Type | Description |
|--------|------|-------------|
| provider_id | INTEGER | Foreign key to providers |
| currency_code | TEXT | ISO4217 code or crypto symbol |
| currency_type | TEXT | FIAT or CRYPTO |
| display | INTEGER | 1 = visible, 0 = hidden |
| source | TEXT | Import source identifier |

> **Note**: The `currencies` table is kept for backwards compatibility. New data is written to both the new separate tables and the legacy table.

### `countries`
| Column | Type | Description |
|--------|------|-------------|
| iso3 | TEXT | ISO 3166-1 alpha-3 code (primary key) |
| iso2 | TEXT | ISO 3166-1 alpha-2 code |
| name | TEXT | Country name |

### `overrides_log`
Audit log for tracking changes (timestamp, action, details).

### `sync_log`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| ts | TEXT | Timestamp |
| provider_name | TEXT | Provider that was synced |
| sheet_id | TEXT | Google Sheet ID |
| status | TEXT | SUCCESS or FAILED |
| message | TEXT | Status message |
| restrictions_count | INTEGER | Number of restrictions imported |
| currencies_count | INTEGER | Number of currencies imported |

### `backups`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| ts | TEXT | Backup timestamp |
| filename | TEXT | Backup filename |
| size_bytes | INTEGER | File size |

---

## Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd game_provider_app
```

### 2. Create virtual environment (optional but recommended)

```bash
python -m venv venv
venv\Scripts\activate  # Windows
# or
source venv/bin/activate  # macOS/Linux
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure secrets

**Option A - Streamlit secrets (recommended):**

Copy the example file and fill in your values:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit `.streamlit/secrets.toml`:
```toml
ADMIN_PASSWORD = "your_secure_password_here"
OPENAI_API_KEY = "sk-your-openai-api-key-here"
```

**Option B - Environment variables:**

```bash
cp .env.example .env
```

Edit `.env`:
```
ADMIN_PASSWORD=your_secure_password_here
OPENAI_API_KEY=sk-your-openai-api-key-here
```

**Keys:**
- `ADMIN_PASSWORD`: Required for admin login in the app
- `OPENAI_API_KEY`: Required for AI-assisted Excel import (optional feature)

### 5. Initialize the database

```bash
python db_init.py
```

This creates `db/database.sqlite` with the schema.

### 6. Populate countries table

Option A - Full ISO country list (recommended):
```bash
pip install pycountry
python create_full_countries.py
```

Option B - Basic country list:
```bash
python create_countries.py
```

### 7. Import provider data (optional)

If you have Excel files in `data_sources/`:
```bash
python importer.py
```

---

## Running the App

```bash
streamlit run app.py
```

The app opens at **http://localhost:8501**

### Using GitHub Codespaces / DevContainer

The project includes a `.devcontainer` configuration. Opening in VS Code with the Dev Containers extension or in GitHub Codespaces will:
- Install Python 3.11
- Install dependencies
- Auto-start the Streamlit server on port 8501

---

## Importing Data

There are three ways to import provider data:

### Method 1: Admin UI (AI-Assisted)

1. Log in as admin (sidebar)
2. Expand "Admin: AI Agent - Import provider from Excel"
3. Upload an Excel file (.xlsx)
4. Click "Run extraction" - the app will:
   - Detect sheets named like "Restricted areas" or "Supported currencies"
   - Extract ISO3 country codes and currency codes
   - Use OpenAI to suggest a clean provider name
5. Review the extracted data
6. Click "Apply import to database"

### Method 2: Batch Import via config.csv

For bulk imports with precise control:

1. Place Excel files in `data_sources/`

2. Run the config generator (optional helper):
   ```bash
   python generate_config.py
   ```
   This creates `config_generated.csv` with detected sheets/ranges.

3. Edit `config.csv` with your provider mappings:
   ```csv
   provider_id,provider_name,file_name,status,currency_mode,restrictions_sheet,restrictions_range,currencies_sheet,fiat_range,crypto_range,notes
   1,Ela Games,Ela Games Main Data.xlsx,ACTIVE,LIST,Restricted areas,A2:A,Supported currencies,A2:A,,,
   ```

4. Run the importer:
   ```bash
   python importer.py
   ```

### Config.csv Columns

| Column | Description |
|--------|-------------|
| provider_id | Unique integer ID |
| provider_name | Display name |
| file_name | Excel filename in data_sources/ |
| status | DRAFT or ACTIVE |
| currency_mode | LIST (specific list) or ALL_FIAT (supports all FIAT) |
| restrictions_sheet | Sheet name containing restricted countries |
| restrictions_range | Cell range, e.g., A2:A (column A, starting row 2) |
| currencies_sheet | Sheet name containing currencies |
| fiat_range | Cell range for FIAT currencies |
| crypto_range | Cell range for crypto currencies (optional) |
| notes | Optional notes |

### Method 3: Google Sheets Sync (Recommended)

Automatically sync from a Google Drive folder containing provider sheets.

#### Setup Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (e.g., `game-providers-app`)
3. Enable **Google Drive API** and **Google Sheets API**
4. Go to **Credentials** → **Create Credentials** → **Service Account**
5. Download the JSON key and save as `service_account.json` in project root
6. Share your Google Drive folder with the service account email

#### Configure

Add to `.streamlit/secrets.toml`:
```toml
GOOGLE_DRIVE_FOLDER_ID = "your_folder_id_here"
```

Get folder ID from URL: `https://drive.google.com/drive/folders/ABC123...` → `ABC123...`

#### Safe Sync Workflow

The sync uses a **staging database** first - it never directly modifies your main database.

```bash
# Step 1: Sync from Google Sheets to STAGING database
python google_sync.py

# Step 2: Preview what was imported
python google_sync.py --preview

# Step 3: Compare staging vs main (see what changed)
python google_sync.py --compare

# Step 4: When happy, promote staging to main
python google_sync.py --promote
```

#### How It Works

```
Google Sheets  ──sync──►  db/staging.sqlite  ──promote──►  db/database.sqlite
                              (safe)                           (main)
                                │                                  │
                                └── preview/compare ───────────────┘
```

- `--preview`: Shows all providers in staging with counts
- `--compare`: Shows new/removed/changed providers vs main
- `--promote`: Backs up main DB, then copies staging to main

#### Backup Management

```bash
# List all backups
python google_sync.py --list

# Restore main DB from latest backup
python google_sync.py --restore

# Restore from specific backup
python google_sync.py --restore database_backup_20240115_143022.sqlite
```

Features:
- **Staging database** - sync never touches main DB directly
- **Automatic backups** - created before every promote
- **Duplicate detection** - skips unchanged providers
- **Data deduplication** - removes duplicate codes
- **10 backups retained** - older backups auto-deleted

#### Expected Folder Structure

```
Google Drive: "Providers Data"
├── DreamTech LGD/
│   └── DreamTech LGD Main DATA (Google Sheet)
├── Mascot Gaming/
│   └── Mascot Gaming Main DATA (Google Sheet)
└── ...
```

Each sheet should have tabs like:
- **Restricted countries** - with sections:
  - "Blocked Countries" → fully blocked
  - "Restricted Countries" → conditional (can open with docs)
  - "Regulated Countries" → requires license
- **Supported currencies** - with sections:
  - FIAT currencies (e.g., USD, EUR, GBP)
  - Crypto currencies (e.g., BTC, ETH, USDT)

---

## Admin Features

### Login

The app has a dedicated login page. Enter your password to access the dashboard:
- Password: Value from `ADMIN_PASSWORD` environment variable or Streamlit secrets

**Persistent Session**: Check "Keep me signed in" to stay logged in across page refreshes. This stores a secure session token in the URL query parameters.

### AI Import

The admin panel includes an AI-assisted importer that:
1. Reads Excel files and detects relevant sheets
2. Extracts ISO3 country codes from restriction sheets
3. Extracts currency codes from currency sheets
4. Uses OpenAI (gpt-4o-mini) to suggest a clean provider name
5. Allows review before committing to database

---

## Configuration

### Streamlit Theme

The app includes a built-in theme toggle (☀️/🌙 button) that switches between light and dark modes. The preference is stored in the URL query parameters and persists across sessions.

Base theme in `.streamlit/config.toml`:
```toml
[theme]
base="dark"
primaryColor="#3B82F6"
backgroundColor="#0F172A"
secondaryBackgroundColor="#1E293B"
textColor="#F1F5F9"
font="sans serif"
```

Note: The app's custom CSS handles theming dynamically, so the config.toml serves as a fallback.

### Currency Mode Logic

- **LIST**: Provider supports only the currencies explicitly listed
- **ALL_FIAT**: Provider supports ALL FIAT currencies (matches any currency filter)

---

## Scripts Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `app.py` | Main Streamlit application | `streamlit run app.py` |
| `db_init.py` | Create database schema | `python db_init.py` |
| `google_sync.py` | Sync from Google Sheets | `python google_sync.py` / `--list` / `--restore` |
| `importer.py` | Batch import from config.csv | `python importer.py` |
| `create_countries.py` | Add basic country list | `python create_countries.py` |
| `create_full_countries.py` | Add full ISO country list | `python create_full_countries.py` |
| `generate_config.py` | Auto-generate config from Excel | `python generate_config.py` |
| `inspect_xlsx.py` | Debug: inspect Excel structure | `python inspect_xlsx.py` |

---

## Troubleshooting

### "Database not found"
Run `python db_init.py` to create the database.

### "No countries in dropdown"
Run `python create_full_countries.py` (requires `pip install pycountry`).

### "AI disabled (missing API key)"
Set `OPENAI_API_KEY` in your `.env` file.

### Excel import finds no data
Use `python inspect_xlsx.py` to see the Excel structure and verify sheet names match your config.

---

## Dependencies

- **streamlit**: Web UI framework
- **pandas**: Data manipulation and Excel reading
- **openai**: AI-assisted import (optional)
- **google-api-python-client**: Google Drive and Sheets API
- **google-auth**: Google authentication
- **pycountry**: Full ISO country list (optional, for create_full_countries.py)

---

## License

[Add your license here]
