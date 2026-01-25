import os
import io
import json
import re
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
            st.session_state["is_admin"] = False
            st.session_state["admin_password"] = ""
            st.session_state["admin_user"] = ""
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
        if df.empty:
            return pd.DataFrame(columns=["iso3", "name", "label"])
        df["label"] = df["name"] + " (" + df["iso3"] + ")"
        return df
    except Exception:
        return pd.DataFrame(columns=["iso3", "name", "label"])


def get_provider_details(pid):
    prov = qdf(
        "SELECT provider_id, provider_name, currency_mode FROM providers WHERE provider_id=?",
        (pid,),
    )
    if prov.empty:
        return None

    restrictions = qdf(
        "SELECT country_code FROM restrictions WHERE provider_id=? ORDER BY country_code",
        (pid,),
    )["country_code"].tolist()

    currencies = qdf(
        "SELECT currency_code, currency_type FROM currencies WHERE provider_id=? ORDER BY currency_type, currency_code",
        (pid,),
    )

    return {
        "provider": prov.iloc[0],
        "restrictions": restrictions,
        "currencies": currencies,
    }


def chips(items, color):
    if not items:
        st.write("None ✅")
        return

    html = ""
    for i in items:
        html += (
            f"<span style='display:inline-block;"
            f"margin:4px;padding:6px 10px;"
            f"border-radius:12px;"
            f"background:{color};"
            f"font-size:0.85rem'>{i}</span>"
        )
    st.markdown(html, unsafe_allow_html=True)

# =================================================
# AI helpers
# =================================================
def get_openai_client():
    if "OPENAI_API_KEY" in st.secrets:
        return OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    api_key = os.getenv("OPENAI_API_KEY", "")
    if api_key:
        return OpenAI(api_key=api_key)
    return None


ISO3_RE = re.compile(r"\b[A-Z]{3}\b")


def read_excel_preview(file_bytes: bytes):
    """
    Read minimal info from Excel:
    - sheet names
    - first ~80 lines from 'Restricted countries' if present
    - first ~40 lines from 'Supported currencies' if present
    """
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    sheet_names = xls.sheet_names

    restricted_lines = []
    if "Restricted countries" in sheet_names:
        df = pd.read_excel(xls, sheet_name="Restricted countries", header=None)
        col0 = df.iloc[:, 0].dropna().astype(str).tolist()
        restricted_lines = col0[:80]

    currency_lines = []
    if "Supported currencies" in sheet_names:
        df = pd.read_excel(xls, sheet_name="Supported currencies", header=None)
        flat = df.dropna().astype(str).values.flatten().tolist()
        currency_lines = flat[:40]

    return {
        "sheet_names": sheet_names,
        "restricted_lines": restricted_lines,
        "currency_lines": currency_lines,
    }


def ai_extract_plan(file_name: str, preview: dict, allowed_iso3: list[str]):
    """
    Ask AI to return a JSON plan. Keep it simple & safe.
    """
    client = get_openai_client()
    if not client:
        return {"error": "OPENAI_API_KEY missing. Add it in Streamlit Secrets."}

    payload = {
        "file_name": file_name,
        "sheet_names": preview.get("sheet_names", []),
        "restricted_lines": preview.get("restricted_lines", []),
        "currency_lines": preview.get("currency_lines", []),
        "allowed_iso3_sample": allowed_iso3[:80],
        "instructions": """
Return ONLY JSON with:
{
  "provider_name": "string",
  "currency_mode": "ALL_FIAT" or "LIST",
  "restricted_iso3": ["ISO3", ...],
  "notes": "string"
}

Use only ISO3 codes from the allowed list sample. If unsure, skip.
""",
    }

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You extract data carefully. Return only valid JSON, no extra text."},
            {"role": "user", "content": json.dumps(payload)},
        ],
        temperature=0.2,
    )

    text = resp.choices[0].message.content.strip()

    # Try parse JSON
    try:
        plan = json.loads(text)
    except Exception:
        return {"error": "AI response was not valid JSON. Try again."}

    # Safety filter: keep only ISO3 codes that exist in our DB list
    allowed = set(allowed_iso3)
    raw_list = plan.get("restricted_iso3", [])
    plan["restricted_iso3"] = sorted({c for c in raw_list if c in allowed})

    # Defaults
    if plan.get("currency_mode") not in ("ALL_FIAT", "LIST"):
        plan["currency_mode"] = "LIST"
    if not plan.get("provider_name"):
        plan["provider_name"] = Path(file_name).stem

    return plan


def upsert_provider_by_name(provider_name: str, currency_mode: str) -> int:
    with db() as con:
        cur = con.execute("SELECT provider_id FROM providers WHERE provider_name=?", (provider_name,))
        row = cur.fetchone()
        if row:
            pid = int(row[0])
            con.execute("UPDATE providers SET currency_mode=? WHERE provider_id=?", (currency_mode, pid))
            con.commit()
            return pid

        cur2 = con.execute(
            "INSERT INTO providers(provider_name, currency_mode, status) VALUES(?, ?, 'ACTIVE')",
            (provider_name, currency_mode),
        )
        con.commit()
        return int(cur2.lastrowid)


def replace_ai_restrictions(provider_id: int, iso3_list: list[str]):
    with db() as con:
        con.execute("DELETE FROM restrictions WHERE provider_id=? AND source='ai_import'", (provider_id,))
        con.executemany(
            "INSERT OR IGNORE INTO restrictions(provider_id, country_code, source) VALUES (?, ?, 'ai_import')",
            [(provider_id, code) for code in iso3_list],
        )
        con.commit()

# =================================================
# App start
# =================================================
login_box()

st.markdown("## Game Providers")
st.caption("Browse providers by country restriction and supported FIAT currency.")

if not DB_PATH.exists():
    st.error("Database not found. Make sure db/database.sqlite exists.")
    st.stop()

countries_df = load_countries()
country_labels = countries_df["label"].tolist()
label_to_iso = dict(zip(countries_df["label"], countries_df["iso3"]))
allowed_iso3 = countries_df["iso3"].dropna().tolist()

fiat = qdf(
    "SELECT DISTINCT currency_code FROM currencies WHERE currency_type='FIAT' ORDER BY currency_code"
)["currency_code"].tolist()

# =================================================
# Filters
# =================================================
with st.container(border=True):
    h1, h2 = st.columns([3, 1])
    h1.subheader("Filters")

    if h2.button("Clear filters", key="btn_clear_filters"):
        st.session_state["f_country"] = ""
        st.session_state["f_currency"] = ""
        st.session_state["f_search"] = ""

    f1, f2, f3 = st.columns([2, 1, 1])

    country_label = f1.selectbox("Country", [""] + country_labels, key="f_country")
    country_iso = label_to_iso.get(country_label, "")

    currency = f2.selectbox("Currency (FIAT)", [""] + fiat, key="f_currency")
    search = f3.text_input("Search provider", key="f_search")

st.caption(
    "Rules: providers with currency_mode=ALL_FIAT match any FIAT currency (even if not listed). "
    "Crypto is hidden by default."
)

# =================================================
# Query building
# =================================================
where = []
params = []

if search:
    where.append("LOWER(p.provider_name) LIKE ?")
    params.append(f"%{search.lower()}%")

# exclude providers restricted in selected country
if country_iso:
    where.append("p.provider_id NOT IN (SELECT provider_id FROM restrictions WHERE country_code=?)")
    params.append(country_iso)

# currency matching
if currency:
    where.append(
        """
        (
            p.currency_mode='ALL_FIAT'
            OR EXISTS (
                SELECT 1 FROM currencies c
                WHERE c.provider_id=p.provider_id
                AND c.currency_type='FIAT'
                AND c.currency_code=?
            )
        )
        """
    )
    params.append(currency)

where_sql = "WHERE " + " AND ".join(where) if where else ""

df = qdf(
    f"""
    SELECT provider_id AS ID, provider_name AS "Game Provider"
    FROM providers p
    {where_sql}
    ORDER BY provider_name
    """,
    tuple(params),
)

# =================================================
# Summary cards
# =================================================
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Providers", int(qdf("SELECT COUNT(*) c FROM providers")["c"][0]))
c2.metric("Matching", len(df))
c3.metric("Country", country_label or "Any")
c4.metric("Currency", currency or "Any")

# =================================================
# Results + Export
# =================================================
r1, r2 = st.columns([3, 1])
r1.subheader("Results")
r2.download_button(
    "Export CSV",
    data=df.to_csv(index=False).encode("utf-8"),
    file_name="game_providers_results.csv",
    mime="text/csv",
    key="btn_export_csv",
)

st.dataframe(
    df,
    hide_index=True,
    use_container_width=True,
    column_config={
        "ID": st.column_config.NumberColumn("ID", width="small"),
        "Game Provider": st.column_config.TextColumn("Game Provider"),
    },
)

# =================================================
# Provider details panel
# =================================================
st.markdown("### Provider details")

if df.empty:
    st.info("No providers match your filters.")
else:
    options = [f"{row['ID']} — {row['Game Provider']}" for _, row in df.iterrows()]
    pick = st.selectbox("Select provider", [""] + options, key="pick_provider_details")

    if pick:
        pid = int(pick.split("—")[0].strip())
        details = get_provider_details(pid)

        if details:
            p = details["provider"]
            restrictions = details["restrictions"]
            currencies_df = details["currencies"]

            with st.container(border=True):
                a, b, d = st.columns([2, 1, 1])
                a.markdown(f"**Game Provider:** {p.provider_name}")
                b.markdown(f"**ID:** {p.provider_id}")
                d.markdown(f"**Currency Mode:** {p.currency_mode}")

                st.markdown("#### Restricted countries")
                chips(restrictions, "#4B1E2F")

                st.markdown("#### Currencies")
                if currencies_df.empty:
                    st.write("None ✅")
                else:
                    fiat_list = currencies_df[currencies_df["currency_type"] == "FIAT"]["currency_code"].tolist()
                    crypto_list = currencies_df[currencies_df["currency_type"] == "CRYPTO"]["currency_code"].tolist()
                    if fiat_list:
                        st.markdown("**FIAT**")
                        chips(fiat_list, "#1F6F43")
                    if crypto_list:
                        st.markdown("**CRYPTO**")
                        chips(crypto_list, "#3A3A3A")

# =================================================
# Admin: AI Agent — Import provider from Excel
# =================================================
if is_admin():
    with st.expander("Admin: AI Agent — Import provider from Excel", expanded=False):
        st.caption("Upload an Excel provider pack. AI suggests provider name, currency mode, and restricted countries. You review before applying.")

        client = get_openai_client()
        if not client:
            st.warning("OPENAI_API_KEY is missing. Add it to Streamlit Secrets to use AI import.")
        else:
            up = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"], key="ai_import_uploader")

            if up is not None:
                file_bytes = up.getvalue()
                preview = read_excel_preview(file_bytes)

                st.write("Detected sheets:")
                st.write(preview["sheet_names"])

                if preview["restricted_lines"]:
                    with st.expander("Preview: Restricted countries text", expanded=False):
                        st.write(preview["restricted_lines"][:40])

                if preview["currency_lines"]:
                    with st.expander("Preview: Supported currencies text", expanded=False):
                        st.write(preview["currency_lines"][:40])

                if st.button("Run AI extraction", key="btn_run_ai"):
                    plan = ai_extract_plan(up.name, preview, allowed_iso3)
                    st.session_state["ai_plan"] = plan

                plan = st.session_state.get("ai_plan", None)
                if isinstance(plan, dict) and plan:
                    if "error" in plan:
                        st.error(plan["error"])
                    else:
                        st.success("AI plan ready. Review and apply if correct.")
                        st.json(plan)

                        provider_name = st.text_input(
                            "Provider name (edit if needed)",
                            value=plan.get("provider_name", ""),
                            key="ai_provider_name",
                        )
                        currency_mode = st.selectbox(
                            "Currency mode",
                            ["ALL_FIAT", "LIST"],
                            index=0 if plan.get("currency_mode") == "ALL_FIAT" else 1,
                            key="ai_currency_mode",
                        )

                        st.markdown("Restricted countries (AI)")
                        chips(plan.get("restricted_iso3", []), "#4B1E2F")

                        if st.button("Apply AI import to database", type="primary", key="btn_apply_ai"):
                            pid = upsert_provider_by_name(provider_name, currency_mode)
                            replace_ai_restrictions(pid, plan.get("restricted_iso3", []))
                            st.success(f"Imported ✅ {provider_name} (ID: {pid})")
                            st.cache_data.clear()

st.caption("Tip: Always review AI results before applying.")
