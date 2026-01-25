import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path("db") / "database.sqlite"

# -------------------------------------------------
# Page config + styling
# -------------------------------------------------
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

# -------------------------------------------------
# Auth
# -------------------------------------------------
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
        if st.sidebar.button("Logout"):
            st.session_state.clear()
        return

    st.sidebar.text_input("Username", key="admin_user")
    st.sidebar.text_input("Password", type="password", key="admin_password")

    if st.sidebar.button("Login"):
        if st.session_state.get("admin_password") == get_admin_password():
            st.session_state["is_admin"] = True
        else:
            st.sidebar.error("Wrong password")

# -------------------------------------------------
# DB helpers
# -------------------------------------------------
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
        return pd.DataFrame(columns=["iso3", "label"])


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
        "SELECT currency_code, currency_type FROM currencies WHERE provider_id=?",
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

# -------------------------------------------------
# App start
# -------------------------------------------------
login_box()

st.markdown("## Game Providers")
st.caption("Browse providers by country restriction and supported FIAT currency.")

if not DB_PATH.exists():
    st.error("Database not found")
    st.stop()

countries_df = load_countries()
country_labels = countries_df["label"].tolist()
label_to_iso = dict(zip(countries_df["label"], countries_df["iso3"]))

fiat = qdf(
    "SELECT DISTINCT currency_code FROM currencies WHERE currency_type='FIAT' ORDER BY currency_code"
)["currency_code"].tolist()

# -------------------------------------------------
# Filters
# -------------------------------------------------
with st.container(border=True):
    h1, h2 = st.columns([3, 1])
    h1.subheader("Filters")

    if h2.button("Clear filters"):
        st.session_state["f_country"] = ""
        st.session_state["f_currency"] = ""
        st.session_state["f_search"] = ""

    f1, f2, f3 = st.columns([2, 1, 1])

    country_label = f1.selectbox(
        "Country", [""] + country_labels, key="f_country"
    )
    country_iso = label_to_iso.get(country_label, "")

    currency = f2.selectbox(
        "Currency (FIAT)", [""] + fiat, key="f_currency"
    )

    search = f3.text_input(
        "Search provider", key="f_search"
    )

# -------------------------------------------------
# Query
# -------------------------------------------------
where = []
params = []

if search:
    where.append("LOWER(p.provider_name) LIKE ?")
    params.append(f"%{search.lower()}%")

if country_iso:
    where.append(
        "p.provider_id NOT IN (SELECT provider_id FROM restrictions WHERE country_code=?)"
    )
    params.append(country_iso)

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

# -------------------------------------------------
# Summary
# -------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Providers", int(qdf("SELECT COUNT(*) c FROM providers")["c"][0]))
c2.metric("Matching", len(df))
c3.metric("Country", country_label or "Any")
c4.metric("Currency", currency or "Any")

# -------------------------------------------------
# Results
# -------------------------------------------------
st.subheader("Results")

st.dataframe(
    df,
    hide_index=True,
    use_container_width=True,
    column_config={
        "ID": st.column_config.NumberColumn("ID", width="small"),
        "Game Provider": st.column_config.TextColumn("Game Provider"),
    },
)

# -------------------------------------------------
# Provider details
# -------------------------------------------------
st.markdown("### Provider details")

if not df.empty:
    options = [f"{r.ID} — {r['Game Provider']}" for _, r in df.iterrows()]
    pick = st.selectbox("Select provider", [""] + options)

    if pick:
        pid = int(pick.split("—")[0].strip())
        details = get_provider_details(pid)

        if details:
            p = details["provider"]
            r = details["restrictions"]
            c = details["currencies"]

            with st.container(border=True):
                a, b, d = st.columns([2, 1, 1])
                a.markdown(f"**Game Provider:** {p.provider_name}")
                b.markdown(f"**ID:** {p.provider_id}")
                d.markdown(f"**Currency Mode:** {p.currency_mode}")

                st.markdown("#### Restricted countries")
                chips(r, "#4B1E2F")

                st.markdown("#### Currencies")
                if c.empty:
                    st.write("None")
                else:
                    chips(c["currency_code"].tolist(), "#1F6F43")

# -------------------------------------------------
# Admin
# -------------------------------------------------
if is_admin():
    with st.expander("Admin: Edit provider data"):
        providers = qdf("SELECT provider_id, provider_name FROM providers ORDER BY provider_name")
        opts = [f"{x.provider_id} — {x.provider_name}" for _, x in providers.iterrows()]
        sel = st.selectbox("Select provider", [""] + opts)

        if sel:
            pid = int(sel.split("—")[0].strip())
            st.write(qdf("SELECT * FROM providers WHERE provider_id=?", (pid,)))

st.caption("Re-import from files by running: py importer.py")
