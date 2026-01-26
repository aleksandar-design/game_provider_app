# Game Providers App

A Streamlit web application for managing game provider data, including country restrictions and supported currencies. The app allows filtering providers by country and currency, viewing detailed provider information, and importing provider data from Excel files.

## Table of Contents

- [Features](#features)
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
- **Filter by Currency**: Find providers that support a specific FIAT currency
- **Provider Details**: View restricted countries and supported currencies for each provider
- **Export to CSV**: Download filtered results as CSV
- **Admin Panel**: AI-assisted import of provider data from Excel files
- **Dark Theme**: Modern dark UI with purple accents

---

## Project Structure

```
game_provider_app/
├── app.py                  # Main Streamlit application
├── db_init.py              # Database schema initialization
├── importer.py             # Batch import from Excel via config.csv
├── create_countries.py     # Populate countries table (basic list)
├── create_full_countries.py # Populate countries table (full ISO list)
├── generate_config.py      # Auto-generate config.csv from Excel files
├── inspect_xlsx.py         # Debug tool to inspect Excel structure
├── config.csv              # Configuration for batch import
├── config_generated.csv    # Auto-generated config (template)
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (secrets)
├── .env.example            # Environment variables template
├── .gitignore              # Git ignore rules
├── .streamlit/
│   └── config.toml         # Streamlit theme configuration
├── .devcontainer/
│   └── devcontainer.json   # VS Code / GitHub Codespaces config
├── db/
│   └── database.sqlite     # SQLite database (created on init)
└── data_sources/           # Excel files for import (.xlsx)
    ├── Ela Games Main Data.xlsx
    ├── Mascot Gaming Main DATA.xlsx
    └── Pragmatic Play Main DATA.xlsx
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
| notes | TEXT | Optional notes |

### `restrictions`
| Column | Type | Description |
|--------|------|-------------|
| provider_id | INTEGER | Foreign key to providers |
| country_code | TEXT | ISO3 country code (e.g., USA, GBR) |
| source | TEXT | Import source identifier |

### `currencies`
| Column | Type | Description |
|--------|------|-------------|
| provider_id | INTEGER | Foreign key to providers |
| currency_code | TEXT | ISO4217 code (e.g., USD, EUR) or crypto symbol |
| currency_type | TEXT | FIAT or CRYPTO |
| display | INTEGER | 1 = visible, 0 = hidden |
| source | TEXT | Import source identifier |

### `countries`
| Column | Type | Description |
|--------|------|-------------|
| iso3 | TEXT | ISO 3166-1 alpha-3 code (primary key) |
| iso2 | TEXT | ISO 3166-1 alpha-2 code |
| name | TEXT | Country name |

### `overrides_log`
Audit log for tracking changes (timestamp, action, details).

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

### 4. Configure environment variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:
```
ADMIN_PASSWORD=your_secure_password_here
OPENAI_API_KEY=sk-your-openai-api-key-here
```

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

There are two ways to import provider data:

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

---

## Admin Features

### Login

Enter credentials in the sidebar:
- Username: (any value)
- Password: Value from `ADMIN_PASSWORD` environment variable

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

Edit `.streamlit/config.toml`:
```toml
[theme]
base="dark"
primaryColor="#7C5CFF"
backgroundColor="#0B1020"
secondaryBackgroundColor="#111A33"
textColor="#EAF0FF"
```

### Currency Mode Logic

- **LIST**: Provider supports only the currencies explicitly listed
- **ALL_FIAT**: Provider supports ALL FIAT currencies (matches any currency filter)

---

## Scripts Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `app.py` | Main Streamlit application | `streamlit run app.py` |
| `db_init.py` | Create database schema | `python db_init.py` |
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
- **pycountry**: Full ISO country list (optional, for create_full_countries.py)

---

## License

[Add your license here]
