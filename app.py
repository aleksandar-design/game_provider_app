import os
import io
import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st
from openai import OpenAI

DB_PATH = Path("db") / "database.sqlite"

# =================================================
# Page config + styling
# =================================================
st.set_page_config(page_title="Game Providers", layout="wide")

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.25rem; padding-bottom: 2.5rem; }
      header[data-testid="stHeader"] { height: 0rem; }

      section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #111A33 0%, #0B1020 100%);
        border-right: 1px solid rgba(255,255,255,0.06);
      }

      div[data-testid="stVerticalBlockBorderWrapper"] {
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        background: rgba(255,255,255,0.02);
      }

      .stButton>button {
        border-radius: 12px;
        padding: 0.55rem 0.95rem;
      }

      div[data-testid="stDataFrame"] {
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,0.08);
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# =================================================
# Auth
# =================================================
def get_admin_password():
    if "ADMIN_PASSWORD" in st.secrets:
        return str(st.secrets["ADMIN_PASSWORD"])
    return os.getenv("ADMIN_PASSWORD", "")


def is_admin():
    return bool(st.session_state.get("is_admin", False))


def login_box():
    st.sidebar.markdown("## Access")

    if is_admin():
        st.sidebar.success("Logged in as Admin")
        if st.sidebar.button("Logout", key="btn_logout"):
            st.session_state.clear()
        return

    st.sidebar.text_input("Username", key="admin_user")
    st.sidebar.text_input("Password", type="password", key="admin_password")

    if st.sidebar.button("Login", key="btn_login"):
        if st.session_state.get("admin_password") == get_admin_password():
            st.session_state["is_admin"] = True
        else:
            st.sidebar.error("Wrong password")

# =================================================
# DB helpers
# =================================================
def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON;")
    return con


def qdf(sql, params=()):
    with db() as con:
        return pd.read_sql_query(sql, con, params=params)


@st.cache_data
def load_countries():
    try:
        df = qdf("SELECT iso3, name FROM countries ORDER BY name")
        df["label"] = df["name"] + " (" + df["iso3"] + ")"
        return df
    except Exception:
        return pd.DataFrame(columns=["iso3", "name", "label"])


def upsert_provider(provider_name: str, currency_mode: str) -> int:
    with db() as con:
        cur = con.execute(
            "SELECT provider_id FROM providers WHERE provider_name=?",
            (provider_name,),
        )
        row = cur.fetchone()
        if row:
            pid = int(row[0])
            con.execute(
                "UPDATE providers SET currency_mode=? WHERE provider_id=?",
                (currency_mode, pid),
            )
            con.commit()
            return pid
        else:
            cur = con.execute(
                "INSERT INTO providers(provider_name, currency_mode, status) VALUES(?, ?, 'ACTIVE')",
                (provider_name, currency_mode),
            )
            con.commit()
            return int(cur.lastrowid)


def replace_ai_restrictions(provider_id: int, iso3_list: list[str]):
    with db() as con:
        con.execute(
            "DELETE FROM restrictions WHERE provider_id=? AND source='ai_import'",
            (provider_id,),
        )
        con.executemany(
            "INSERT OR IGNORE INTO restrictions(provider_id, country_code, source) VALUES (?, ?, 'ai_import')",
            [(provider_id, c) for c in iso3_list],
        )
        con.commit()

# =================================================
# AI helpers
# =================================================
def get_openai_client():
    if "OPENAI_API_KEY" not in st.secrets:
        return None
    return OpenAI(api_key=st.secrets["OPENAI_API_KEY"])


def read_excel_preview(file_bytes: bytes):
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    sheets = xls.sheet_names

    preview = []
    for s in sheets[:2]:
        df = pd.read_excel(xls, sheet_name=s)
        preview.append(
            {
                "sheet": s,
                "sample": df.head(20).astype(str).values.tolist(),
            }
        )
    return preview


def ai_extract_plan(file_name: str, preview, iso3_list):
    client = get_openai_client()
    if not client:
        return {"error": "OPENAI_API_KEY missing in secrets"}

    prompt = {
        "file_name": file_name,
        "preview": preview,
        "allowed_iso3": iso3_list,
        "instructions": """
You are extracting data from a game provider Excel file.

Return ONLY valid JSON with:
{
  provider_name: string,
  currency_mode: "ALL_FIAT" or "LIST",
  restricted_iso3: [ISO3 country codes],
  notes: string
}

Use only ISO3 codes from allowed_iso3.
""",
    }

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a precise data extraction assistant."},
            {"role": "user", "content": json.dumps(prompt)},
        ],
    )

    try:
        return json.loads(response.choices[0].message.content)
    except Exception:
        return {"error": "AI returned invalid JSON"}

# =================================================
# App start
# =================================================
login_box()

st.markdown("## Game Providers")
st.caption("Browse providers by country restriction and supported FIAT currency.")

if not DB_PATH.exists():
    st.error("Database not found")
    st.stop()

countries = load_countries()
iso3_list = countries["iso3"].tolist()

# =================================================
# Results (simple)
# =================================================
df = qdf("SELECT provider_id AS ID, provider_name AS Provider FROM providers ORDER BY provider_name")
st.dataframe(df, hide_index=True, use_container_width=True)

st.download_button(
    "Export CSV",
    data=df.to_csv(index=False),
    file_name="providers.csv",
    mime="text/csv",
)

# =================================================
# Admin AI Agent
# =================================================
if is_admin():
    with st.expander("Admin: AI Agent — Import provider from Excel", expanded=True):
        st.caption("Upload an Excel file. AI will extract provider name and restricted countries.")

        if "OPENAI_API_KEY" not in st.secrets:
            st.error("OPENAI_API_KEY is missing in Streamlit Secrets.")
        else:
            uploaded = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"])

            if uploaded:
                preview = read_excel_preview(uploaded.getvalue())
                st.write("Excel preview:")
                st.json(preview)

                if st.button("Run AI extraction"):
                    plan = ai_extract_plan(uploaded.name, preview, iso3_list)
                    st.session_state["ai_plan"] = plan

                plan = st.session_state.get("ai_plan")
                if plan:
                    if "error" in plan:
                        st.error(plan["error"])
                    else:
                        st.success("AI extraction successful")
                        st.json(plan)

                        provider_name = st.text_input(
                            "Provider name",
                            value=plan["provider_name"],
                        )
                        currency_mode = st.selectbox(
                            "Currency mode",
                            ["ALL_FIAT", "LIST"],
                            index=0 if plan["currency_mode"] == "ALL_FIAT" else 1,
                        )

                        if st.button("Apply AI Import", type="primary"):
                            pid = upsert_provider(provider_name, currency_mode)
                            replace_ai_restrictions(pid, plan["restricted_iso3"])
                            st.success(f"Imported provider {provider_name} (ID {pid})")
                            st.cache_data.clear()
