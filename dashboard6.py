import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time

# =================== Config ===================
CLIENT_ID = "1000.6RGKF8DHKXLGDXFU9V0XL86JMM2WTF"
CLIENT_SECRET = "3433f4449427eef162583c39b6628a5f797cb99f2a"
REFRESH_TOKEN = "1000.eb9bcd7fd754f1540af1a070bfd29f05.5fa5d1aac61594aec72d4d574b1d76d7"
BASE_URL = "https://www.zohoapis.com/books/v3"
ORG_ID = "890601593"

RATE_LIMIT_DELAY = 2
USD_TO_AED = 3.67  # USD bank balances converted to AED

# =================== Auth & rate limit ===================
def get_access_token():
    if "access_token" in st.session_state and "expires_at" in st.session_state:
        if datetime.now() < st.session_state["expires_at"]:
            return st.session_state["access_token"]

    token_url = "https://accounts.zoho.com/oauth/v2/token"
    params = {
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
    }
    resp = requests.post(token_url, params=params)
    resp.raise_for_status()
    data = resp.json()
    access_token = data["access_token"]
    expires_in = data.get("expires_in", 3600)
    st.session_state["access_token"] = access_token
    st.session_state["expires_at"] = datetime.now() + timedelta(seconds=expires_in)
    return access_token

def rate_limited_api_call(func, *args, **kwargs):
    last = st.session_state.get("last_api_call")
    if last:
        elapsed = (datetime.now() - last).total_seconds()
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
    result = func(*args, **kwargs)
    st.session_state["last_api_call"] = datetime.now()
    return result

# =================== API Calls ===================
def get_profit_and_loss(from_date, to_date, cash_based="true"):
    token = get_access_token()
    url = f"{BASE_URL}/reports/profitandloss"
    params = {
        "organization_id": ORG_ID,
        "from_date": from_date,
        "to_date": to_date,
        "cash_based": cash_based,
    }
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    r = requests.get(url, headers=headers, params=params)
    return r.json() if r.status_code == 200 else {}

def get_balance_sheet(to_date):
    token = get_access_token()
    url = f"{BASE_URL}/reports/balancesheet"
    params = {
        "organization_id": ORG_ID,
        "to_date": to_date,
        "show_rows": "non_zero",
    }
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    r = requests.get(url, headers=headers, params=params)
    return r.json() if r.status_code == 200 else {}

def get_cash_flow(from_date, to_date):
    token = get_access_token()
    url = f"{BASE_URL}/reports/cashflow"
    params = {
        "organization_id": ORG_ID,
        "from_date": from_date,
        "to_date": to_date,
    }
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    r = requests.get(url, headers=headers, params=params)
    return r.json() if r.status_code == 200 else {}

# =================== Helpers (USD -> AED for bank) ===================
def _to_aed(total: float, node: dict) -> float:
    """Convert bank account amount to AED if account appears USD."""
    name = (node.get("name") or "").upper()
    code = (node.get("currency_code") or node.get("currency") or "").upper()
    is_usd = code == "USD" or "USD" in name or "$" in name
    return total * USD_TO_AED if is_usd else total

# =================== Extractors ===================
def extract_bank_and_ap(balance_data):
    bank_total = 0.0
    ap_total = 0.0
    bank_details = []

    for section in balance_data.get("balance_sheet", []):
        if section.get("name") == "Assets":
            for asset in section.get("account_transactions", []):
                if asset.get("name") == "Current Assets":
                    for sub in asset.get("account_transactions", []):
                        sub_name = (sub.get("name") or "").lower()
                        if sub_name in ["cash", "bank", "cash and cash equivalents"]:
                            for acc in sub.get("account_transactions", []):
                                amt_raw = float(acc.get("total", 0))
                                amt_aed = _to_aed(amt_raw, acc)
                                bank_total += amt_aed
                                bank_details.append({
                                    "Account Name": acc.get("name", "Unknown"),
                                    "Balance (AED)": round(amt_aed, 1),
                                    "Note": "USD→AED x3.67" if amt_aed != amt_raw else ""
                                })

        if section.get("name") == "Liabilities & Equities":
            for liab in section.get("account_transactions", []):
                if liab.get("name") == "Liabilities":
                    for sub in liab.get("account_transactions", []):
                        if sub.get("name") == "Current Liabilities":
                            for acc in sub.get("account_transactions", []):
                                if "accounts payable" in (acc.get("name", "").lower()):
                                    ap_total = float(acc.get("total", 0))
                                    break
    return round(bank_total, 1), round(ap_total, 1), bank_details

def extract_balance_components(balance_data):
    bank_total = 0.0
    ar_total = 0.0
    prepaid_total = 0.0
    ap_total = 0.0

    def traverse(nodes, section_type):
        nonlocal bank_total, ar_total, prepaid_total, ap_total
        for n in nodes:
            name = (n.get("name") or "").strip()
            lname = name.lower()
            total = float(n.get("total", 0.0))

            if section_type == "Assets":
                if any(k in lname for k in ["bank", "cash", "cash and cash equivalents"]):
                    total_aed = _to_aed(total, n)
                    bank_total += total_aed
                elif "accounts receivable" in lname:
                    ar_total += total
                elif name == "Prepaid Expenses":
                    prepaid_total = total
            elif section_type == "Liabilities & Equities":
                if "accounts payable" in lname:
                    ap_total += total

            if "account_transactions" in n:
                traverse(n["account_transactions"], section_type)

    for section in balance_data.get("balance_sheet", []):
        sname = section.get("name", "")
        if sname in ["Assets", "Liabilities & Equities"]:
            traverse(section.get("account_transactions", []), sname)

    return round(bank_total, 1), round(ar_total, 1), round(prepaid_total, 1), round(ap_total, 1)

def get_operating_cashflow(cashflow_data):
    if not cashflow_data or "cash_flow" not in cashflow_data:
        return 0.0
    for section in cashflow_data.get("cash_flow", []):
        if section.get("section_name") == "Operating Activities":
            return round(float(section.get("total", 0)), 1)
    return 0.0

# =================== P&L Processing ===================
def process_data_original(data):
    metrics = {"Sales": 0.0, "COGS": 0.0, "Gross Profit": 0.0,
               "Operating Expenses": 0.0, "Operating Profit": 0.0, "Net Profit": 0.0}
    for section in data.get("profit_and_loss", []):
        for tr in section.get("account_transactions", []):
            name, total = tr.get("name"), float(tr.get("total", 0.0))
            if name == "Operating Income": metrics["Sales"] = total
            elif name == "Cost of Goods Sold": metrics["COGS"] = total
            elif name == "Gross Profit": metrics["Gross Profit"] = total
            elif name == "Operating Expense": metrics["Operating Expenses"] = total
            elif name == "Operating Profit": metrics["Operating Profit"] = total
            elif name == "Net Profit/Loss": metrics["Net Profit"] = total

    if metrics["Gross Profit"] == 0: metrics["Gross Profit"] = metrics["Sales"] - metrics["COGS"]
    if metrics["Operating Profit"] == 0: metrics["Operating Profit"] = metrics["Gross Profit"] - metrics["Operating Expenses"]
    if metrics["Net Profit"] == 0: metrics["Net Profit"] = metrics["Operating Profit"]
    return {k: round(v, 1) for k, v in metrics.items()}

def process_data(data):
    metrics = {"Sales": 0.0, "COGS": 0.0, "Gross Profit": 0.0,
               "Operating Expenses": 0.0, "Operating Profit": 0.0, "Net Profit": 0.0}
    operating_expenses = []
    non_oper_income = 0.0
    non_oper_exp = 0.0

    for section in data.get("profit_and_loss", []):
        for tr in section.get("account_transactions", []):
            name, total = tr.get("name"), float(tr.get("total", 0.0))
            if name == "Operating Income":
                metrics["Sales"] = total
            elif name == "Cost of Goods Sold":
                metrics["COGS"] = total
            elif name == "Gross Profit":
                metrics["Gross Profit"] = total
            elif name == "Operating Expense":
                metrics["Operating Expenses"] = total
                operating_expenses = [
                    {"Name": sub.get("name"), "Amount": round(float(sub.get("total", 0.0)), 1)}
                    for sub in tr.get("account_transactions", [])
                ]
            elif name == "Operating Profit":
                metrics["Operating Profit"] = total
            elif name == "Non Operating Income":
                non_oper_income += total
            elif name == "Non Operating Expense":
                non_oper_exp += total
            elif name == "Net Profit/Loss":
                metrics["Net Profit"] = total

    if metrics["Gross Profit"] == 0: metrics["Gross Profit"] = metrics["Sales"] - metrics["COGS"]
    if metrics["Operating Profit"] == 0: metrics["Operating Profit"] = metrics["Gross Profit"] - metrics["Operating Expenses"]
    if metrics["Net Profit"] == 0: metrics["Net Profit"] = metrics["Operating Profit"] + non_oper_income - non_oper_exp
    return {k: round(v, 1) for k, v in metrics.items()}, operating_expenses

# =================== Cash Available (UPDATED) ===================
def calculate_cash_available(cash_profit, ap_total, min_reserve):
    """Cash Available = Cash Net Profit − Accounts Payable − Minimum Reserve"""
    cash_available = cash_profit - ap_total - min_reserve
    return {
        "cash_available": round(cash_available, 1),  # allow negative values
        "cash_profit": round(cash_profit, 1),
        "ap_total": round(ap_total, 1),
        "min_reserve": round(min_reserve, 1),
    }

# =================== Monthly helpers (unchanged) ===================
def fetch_monthly_data(from_date, to_date):
    try:
        cash_data = rate_limited_api_call(get_profit_and_loss, from_date, to_date, "true")
        cash_metrics = process_data_original(cash_data)
        accrual_data = rate_limited_api_call(get_profit_and_loss, from_date, to_date, "false")
        accrual_metrics = process_data_original(accrual_data)
        return cash_metrics, accrual_metrics
    except Exception as e:
        st.error(f"Error fetching monthly data: {e}")
        return None, None

def get_monthly_data_jan_to_sep():
    months = [
        ("Jan 2025", "2025-01-01", "2025-01-31"),
        ("Feb 2025", "2025-02-01", "2025-02-28"),
        ("Mar 2025", "2025-03-01", "2025-03-31"),
        ("Apr 2025", "2025-04-01", "2025-04-30"),
        ("May 2025", "2025-05-01", "2025-05-31"),
        ("Jun 2025", "2025-06-01", "2025-06-30"),
        ("Jul 2025", "2025-07-01", "2025-07-31"),
        ("Aug 2025", "2025-08-01", "2025-08-31"),
        ("Sep 2025", "2025-09-01", "2025-09-30"),
    ]
    rows = []
    p = st.progress(0)
    for i, (label, f, t) in enumerate(months):
        cash_m, accrual_m = fetch_monthly_data(f, t)
        if cash_m and accrual_m:
            rows.append({"Month": label, "Cash Net Profit": cash_m["Net Profit"], "Accrual Net Profit": accrual_m["Net Profit"]})
        p.progress((i + 1) / len(months))
    p.empty()
    return pd.DataFrame(rows)

def plot_jan_to_sep_profit(df_monthly):
    if df_monthly.empty:
        st.warning("No monthly data available.")
        return
    df_m = df_monthly.melt(id_vars=["Month"], value_vars=["Cash Net Profit", "Accrual Net Profit"],
                           var_name="Basis", value_name="Net Profit")
    fig = px.line(df_m, x="Month", y="Net Profit", color="Basis",
                  title="Net Profit: January to September 2025",
                  labels={"Net Profit": "Net Profit (AED)", "Month": ""}, markers=True)
    fig.update_layout(xaxis_tickangle=-45, hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

# =================== Main ===================
def main():
    st.set_page_config(page_title="Cash-Based Profit Dashboard", page_icon="💰", layout="wide")

    # ---- session state defaults ----
    if "analysis_started" not in st.session_state:
        st.session_state.analysis_started = False
    if "committed_from" not in st.session_state:
        st.session_state.committed_from = datetime(2025, 1, 1).date()
    if "committed_to" not in st.session_state:
        st.session_state.committed_to = datetime.today().date()
    if "data_cache" not in st.session_state:
        st.session_state.data_cache = None
    if "monthly_data_loaded" not in st.session_state:
        st.session_state.monthly_data_loaded = False
    if "monthly_df" not in st.session_state:
        st.session_state.monthly_df = pd.DataFrame()

    st.title("💰 Cash-Based Profit & Loss Dashboard")
    st.markdown("*Professional financial analysis with real-time data from Zoho Books*")

    # ---- Controls: form so date changes don't auto-run APIs ----
    with st.form("run_controls", clear_on_submit=False):
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            pending_from = st.date_input("📅 Start Date", value=st.session_state.committed_from)
        with c2:
            pending_to = st.date_input("📅 End Date", value=st.session_state.committed_to)
        with c3:
            st.markdown("<br>", unsafe_allow_html=True)
            submitted = st.form_submit_button("🚀 Run Analysis", type="primary", use_container_width=True)

    # Commit dates and invalidate cache only when button is clicked
    if submitted:
        st.session_state.committed_from = pending_from
        st.session_state.committed_to = pending_to
        st.session_state.data_cache = None
        st.session_state.analysis_started = True

    # If user hasn't run once yet
    if not st.session_state.analysis_started and st.session_state.data_cache is None:
        st.info("👆 Select your date range and click **Run Analysis**.")
        st.stop()

    # Short names for committed dates
    from_date = st.session_state.committed_from
    to_date = st.session_state.committed_to

    # ---- Fetch only when cache is empty (i.e., after Run Analysis) ----
    def fetch_all(from_date, to_date):
        progress_text = st.empty()
        with st.spinner("⏳ Fetching data from Zoho Books..."):
            progress_text.text("📊 Cash-based P&L...")
            cash_data = rate_limited_api_call(get_profit_and_loss, str(from_date), str(to_date), "true")

            progress_text.text("📈 Accrual-based P&L...")
            accrual_data = rate_limited_api_call(get_profit_and_loss, str(from_date), str(to_date), "false")

            progress_text.text("🏦 Balance sheet...")
            balance_data = rate_limited_api_call(get_balance_sheet, str(to_date))

            progress_text.text("💧 Cash flow statement...")
            cash_flow_data = rate_limited_api_call(get_cash_flow, str(from_date), str(to_date))

            progress_text.empty()
        return {
            "cash_data": cash_data,
            "accrual_data": accrual_data,
            "balance_data": balance_data,
            "cash_flow_data": cash_flow_data,
        }

    if st.session_state.data_cache is None:
        st.session_state.data_cache = fetch_all(from_date, to_date)
        st.success("✅ Data loaded successfully!")
    else:
        st.caption(f"Using data for **{from_date} → {to_date}**. Change dates and click **Run Analysis** to refresh.")

    # ---- Unpack cached data ----
    data = st.session_state.data_cache
    cash_data = data["cash_data"]
    accrual_data = data["accrual_data"]
    balance_data = data["balance_data"]
    cash_flow_data = data["cash_flow_data"]

    # ---- Process ----
    cash_metrics, cash_expenses = process_data(cash_data)
    accrual_metrics, accrual_expenses = process_data(accrual_data)
    total_bank_balance, first_ap_item, bank_details = extract_bank_and_ap(balance_data)
    bank_total, ar_total, prepaid_total, ap_total = extract_balance_components(balance_data)
    operating_cf = get_operating_cashflow(cash_flow_data)

    # ----- Cash Availability (UPDATED) -----
    st.markdown("---")
    st.subheader("💰 Cash Availability Analysis")

    min_reserve = st.number_input("🔒 Minimum Reserve (AED)", value=10000, step=1000, min_value=0)

    cash_available_info = calculate_cash_available(
        cash_metrics["Net Profit"],
        ap_total,
        min_reserve,
    )

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("💵 Cash Net Profit", f"AED {cash_available_info['cash_profit']:,.1f}")
    mc2.metric("📉 Accounts Payable", f"AED {cash_available_info['ap_total']:,.1f}")
    mc3.metric("🔒 Minimum Reserve", f"AED {cash_available_info['min_reserve']:,.1f}")
    mc4.metric("💰 Cash Available", f"AED {cash_available_info['cash_available']:,.1f}",
               help="Cash Net Profit − AP − Minimum Reserve")

    with st.expander("💡 View Calculation Details"):
        st.write(f"""
**Formula:** Cash Available = Cash Net Profit − Accounts Payable − Minimum Reserve

- Cash Net Profit: AED {cash_available_info['cash_profit']:,.1f}  
- − Accounts Payable: AED {cash_available_info['ap_total']:,.1f}  
- − Minimum Reserve: AED {cash_available_info['min_reserve']:,.1f}  

**= AED {cash_available_info['cash_available']:,.1f}**
""")

    # ----- Bank & Working Capital -----
    st.markdown("---")
    b1, b2 = st.columns(2)
    with b1:
        st.subheader("🏦 Bank Accounts")
        st.caption(f"As of {to_date.strftime('%B %d, %Y')}")
        if bank_details:
            bank_df = pd.DataFrame(bank_details)
            st.dataframe(bank_df, use_container_width=True, hide_index=True)
            fig_bank = px.pie(bank_df, values="Balance (AED)", names="Account Name",
                              title="Bank Balance Distribution", hole=0.3)
            st.plotly_chart(fig_bank, use_container_width=True)
        else:
            st.warning("No bank account data available.")
    with b2:
        st.subheader("💼 Working Capital")
        wc = pd.DataFrame({
            "Component": ["Bank Balance", "Accounts Receivable", "Prepaid Expenses", "Accounts Payable"],
            "Amount (AED)": [bank_total, ar_total, prepaid_total, -ap_total],
            "Type": ["Asset", "Asset", "Asset", "Liability"],
        })
        st.dataframe(wc, use_container_width=True, hide_index=True)
        colors = ["#2E8B57" if x > 0 else "#DC143C" for x in wc["Amount (AED)"]]
        fig_wc = go.Figure(data=[go.Bar(
            x=wc["Component"], y=wc["Amount (AED)"], marker_color=colors,
            text=wc["Amount (AED)"].apply(lambda v: f"AED {abs(v):,.0f}"),
            textposition="outside"
        )])
        fig_wc.update_layout(title="Working Capital Components", showlegend=False, yaxis_title="Amount (AED)")
        st.plotly_chart(fig_wc, use_container_width=True)

    # ----- Tabs -----
    st.markdown("---")
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        ["💵 Cash P&L", "📊 Cash vs Accrual", "📈 Monthly Trends", "💼 Operating Expenses", "💧 Cash Flow", "📋 Reports"]
    )

    with tab1:
        st.subheader("💵 Cash-Based Profit & Loss Statement")
        st.caption(f"Period: {from_date.strftime('%b %d, %Y')} → {to_date.strftime('%b %d, %Y')}")
        cash_breakdown = pd.DataFrame({
            "Line Item": ["Sales", "Cost of Goods Sold", "Gross Profit", "Operating Expenses", "Operating Profit", "Net Profit"],
            "Amount (AED)": [cash_metrics["Sales"], -cash_metrics["COGS"], cash_metrics["Gross Profit"],
                             -cash_metrics["Operating Expenses"], cash_metrics["Operating Profit"], cash_metrics["Net Profit"]],
        })
        st.dataframe(cash_breakdown, use_container_width=True, hide_index=True)

        wf = pd.DataFrame({
            "Category": ["Sales", "COGS", "OpEx", "Net Profit"],
            "Amount": [cash_metrics["Sales"], -cash_metrics["COGS"],
                       -cash_metrics["Operating Expenses"], cash_metrics["Net Profit"]],
            "Color": ["green", "red", "red", "blue"],
        })
        fig_cash = px.bar(wf, x="Category", y="Amount", color="Color",
                          title="Cash-Based Profit Waterfall",
                          labels={"Amount": "Amount (AED)"},
                          color_discrete_map={"green": "#2E8B57", "red": "#DC143C", "blue": "#1E90FF"})
        fig_cash.update_layout(showlegend=False)
        st.plotly_chart(fig_cash, use_container_width=True)

        k1, k2, k3 = st.columns(3)
        gm = (cash_metrics["Gross Profit"] / cash_metrics["Sales"] * 100) if cash_metrics["Sales"] else 0
        om = (cash_metrics["Operating Profit"] / cash_metrics["Sales"] * 100) if cash_metrics["Sales"] else 0
        nm = (cash_metrics["Net Profit"] / cash_metrics["Sales"] * 100) if cash_metrics["Sales"] else 0
        k1.metric("Gross Margin", f"{gm:.1f}%")
        k2.metric("Operating Margin", f"{om:.1f}%")
        k3.metric("Net Margin", f"{nm:.1f}%")

    with tab2:
        st.subheader("📊 Cash vs Accrual Comparison")
        comp = pd.DataFrame({
            "Metric": ["Sales", "COGS", "Gross Profit", "Operating Expenses", "Operating Profit", "Net Profit"],
            "Cash Basis": [cash_metrics["Sales"], cash_metrics["COGS"], cash_metrics["Gross Profit"],
                           cash_metrics["Operating Expenses"], cash_metrics["Operating Profit"], cash_metrics["Net Profit"]],
            "Accrual Basis": [accrual_metrics["Sales"], accrual_metrics["COGS"], accrual_metrics["Gross Profit"],
                              accrual_metrics["Operating Expenses"], accrual_metrics["Operating Profit"], accrual_metrics["Net Profit"]],
        })
        comp["Difference"] = comp["Cash Basis"] - comp["Accrual Basis"]
        comp["% Variance"] = ((comp["Difference"] / comp["Accrual Basis"].abs()) * 100).replace([pd.NA], 0).fillna(0).round(1)
        st.dataframe(comp, use_container_width=True, hide_index=True)
        fig_comp = px.bar(comp, x="Metric", y=["Cash Basis", "Accrual Basis"], barmode="group",
                          title="Cash vs Accrual Comparison", labels={"value": "Amount (AED)"})
        st.plotly_chart(fig_comp, use_container_width=True)

    with tab3:
        st.subheader("📈 Monthly Profit Trends")
        if st.button("📊 Load Monthly Data (Jan–Sep 2025)", type="secondary"):
            with st.spinner("Loading 9 months of data... (~18 seconds)"):
                df_monthly = get_monthly_data_jan_to_sep()
                if not df_monthly.empty:
                    st.session_state.monthly_df = df_monthly
                    st.session_state.monthly_data_loaded = True
                    st.success("✅ Monthly data loaded!")
        if st.session_state.monthly_data_loaded and not st.session_state.monthly_df.empty:
            plot_jan_to_sep_profit(st.session_state.monthly_df)
            st.markdown("---")
            c1, c2, c3 = st.columns(3)
            cash_avg = float(st.session_state.monthly_df["Cash Net Profit"].mean())
            accrual_avg = float(st.session_state.monthly_df["Accrual Net Profit"].mean())
            c1.metric("💵 Avg Cash Profit", f"AED {cash_avg:,.1f}")
            c2.metric("📊 Avg Accrual Profit", f"AED {accrual_avg:,.1f}")
            c3.metric("📉 Avg Difference", f"AED {(cash_avg - accrual_avg):,.1f}")
            st.dataframe(st.session_state.monthly_df, use_container_width=True, hide_index=True)

            if st.button("🔄 Clear Monthly Data", type="secondary"):
                st.session_state.monthly_data_loaded = False
                st.session_state.monthly_df = pd.DataFrame()
                st.experimental_rerun()
        else:
            st.info("Click **Load Monthly Data** above to fetch Jan–Sep 2025 results (18 API calls).")

    with tab4:
        st.subheader("💼 Operating Expenses Breakdown")
        c1, c2 = st.columns(2)
        if cash_expenses:
            cash_exp_df = pd.DataFrame(cash_expenses)
            cash_exp_df = cash_exp_df[cash_exp_df["Amount"] != 0]
            c1.markdown("#### Cash-Based Expenses")
            c1.dataframe(cash_exp_df, use_container_width=True, hide_index=True)
            c1.plotly_chart(px.pie(cash_exp_df, values="Amount", names="Name",
                                   title="Cash Expenses Distribution", hole=0.3),
                            use_container_width=True)
        if accrual_expenses:
            accrual_exp_df = pd.DataFrame(accrual_expenses)
            accrual_exp_df = accrual_exp_df[accrual_exp_df["Amount"] != 0]
            c2.markdown("#### Accrual-Based Expenses")
            c2.dataframe(accrual_exp_df, use_container_width=True, hide_index=True)
            c2.plotly_chart(px.pie(accrual_exp_df, values="Amount", names="Name",
                                   title="Accrual Expenses Distribution", hole=0.3),
                            use_container_width=True)

    with tab5:
        st.subheader("💧 Operating Cash Flow Analysis")
        c1, c2, c3 = st.columns(3)
        c1.metric("💼 Operating Cash Flow", f"AED {operating_cf:,.1f}")
        c2.metric("💵 Cash Net Profit", f"AED {cash_metrics['Net Profit']:,.1f}")
        diff = operating_cf - cash_metrics["Net Profit"]
        pct = (diff / abs(cash_metrics["Net Profit"]) * 100) if cash_metrics["Net Profit"] else 0
        c3.metric("📊 OCF − Net Profit", f"AED {diff:,.1f}", delta=f"{pct:.1f}%")

        if cash_flow_data and "cash_flow" in cash_flow_data:
            cf_rows = [{"Activity Type": s.get("section_name", "Unknown"),
                        "Amount (AED)": round(float(s.get("total", 0)), 1)}
                       for s in cash_flow_data["cash_flow"]]
            cf_df = pd.DataFrame(cf_rows)
            st.dataframe(cf_df, use_container_width=True, hide_index=True)
            st.plotly_chart(px.bar(cf_df, x="Activity Type", y="Amount (AED)",
                                   title="Cash Flow by Activity Type",
                                   color="Amount (AED)",
                                   color_continuous_scale=["#DC143C", "#FFD700", "#2E8B57"]),
                            use_container_width=True)

    with tab6:
        st.subheader("📋 Comprehensive Financial Reports")
        nwc = bank_total + ar_total + prepaid_total - ap_total
        st.markdown("### Executive Summary")
        c1, c2 = st.columns(2)
        c1.write(f"""
- Total Sales (Cash): AED {cash_metrics['Sales']:,.1f}
- COGS: AED {cash_metrics['COGS']:,.1f}
- Gross Profit: AED {cash_metrics['Gross Profit']:,.1f}
- Operating Expenses: AED {cash_metrics['Operating Expenses']:,.1f}
- Operating Profit: AED {cash_metrics['Operating Profit']:,.1f}
- Net Profit (Cash): AED {cash_metrics['Net Profit']:,.1f}
""")
        ratio = (operating_cf / cash_metrics["Net Profit"] * 100) if cash_metrics["Net Profit"] else 0
        c1.write(f"- Operating Cash Flow: AED {operating_cf:,.1f}\n- OCF / Net Profit: {ratio:.1f}%")
        c2.write(f"""
- Bank Balance: AED {total_bank_balance:,.1f}
- Accounts Receivable: AED {ar_total:,.1f}
- Prepaid Expenses: AED {prepaid_total:,.1f}
- Accounts Payable: AED {ap_total:,.1f}
- Net Working Capital: AED {nwc:,.1f}
- Cash Available (after reserve): AED {cash_available_info['cash_available']:,.1f}
""")

        st.markdown("---")
        st.markdown("### Export")
        r1, r2 = st.columns(2)
        pl_report = pd.DataFrame({
            "Metric": ["Sales", "COGS", "Gross Profit", "Operating Expenses", "Operating Profit", "Net Profit",
                       "Operating Cash Flow", "Bank Balance", "Accounts Receivable", "Prepaid Expenses",
                       "Accounts Payable", "Cash Available"],
            "Amount (AED)": [cash_metrics["Sales"], cash_metrics["COGS"], cash_metrics["Gross Profit"],
                             cash_metrics["Operating Expenses"], cash_metrics["Operating Profit"], cash_metrics["Net Profit"],
                             operating_cf, total_bank_balance, ar_total, prepaid_total, ap_total,
                             cash_available_info["cash_available"]],
            "Period": [f"{from_date} to {to_date}"] * 12,
        })
        r1.download_button("📥 Download P&L Summary (CSV)", pl_report.to_csv(index=False),
                           file_name=f"pl_summary_{from_date}_{to_date}.csv", mime="text/csv", use_container_width=True)

        bs_report = pd.DataFrame({
            "Component": ["Bank Balance", "Accounts Receivable", "Prepaid Expenses", "Accounts Payable",
                          "Net Working Capital", "Minimum Reserve", "Cash Available"],
            "Amount (AED)": [total_bank_balance, ar_total, prepaid_total, ap_total,
                             nwc, cash_available_info["min_reserve"], cash_available_info["cash_available"]],
            "As of": [str(to_date)] * 7,
        })
        r2.download_button("📥 Download Balance Summary (CSV)", bs_report.to_csv(index=False),
                           file_name=f"balance_summary_{to_date}.csv", mime="text/csv", use_container_width=True)

if __name__ == "__main__":
    main()
