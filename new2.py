import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from datetime import datetime, date, timedelta
import time
import json

# =================== CONFIG ===================
st.set_page_config(page_title="📊 Profit & Loss Dashboard", layout="wide")
WEBHOOK_URL = "https://hook.eu2.make.com/5naam9qq4wr6ttvesd9cn3sdzvxaxu3d"

# =================== SIDEBAR (controls) ===================
st.sidebar.header("⚙️ Controls")
DEBUG = st.sidebar.toggle("🔧 Debug mode", value=False, help="Show raw shapes, section names, and monthly call results.")
if st.sidebar.button("🧹 Clear cache"):
    st.cache_data.clear()
    st.sidebar.success("Cache cleared. Re-run to fetch fresh data.")

# =================== HELPERS ===================
def _f(x):
    try:
        return float(x or 0)
    except Exception:
        return 0.0

def month_start(d: date) -> date:
    return date(d.year, d.month, 1)

def next_month(d: date) -> date:
    return date(d.year + (1 if d.month == 12 else 0), 1 if d.month == 12 else d.month + 1, 1)

def month_end(d: date) -> date:
    return next_month(d) - timedelta(days=1)

def month_range(from_date: date, to_date: date):
    """Yield (label 'YYYY-MM', start_date, end_date) for each month overlapping the range."""
    cur = month_start(from_date)
    last = month_start(to_date)
    while cur <= last:
        start = max(cur, from_date)
        end = min(month_end(cur), to_date)
        yield (cur.strftime("%Y-%m"), start, end)
        cur = next_month(cur)

def _section_names(sections):
    try:
        return [str((s.get("name") or "")).strip() for s in sections] if isinstance(sections, list) else []
    except Exception:
        return []

# =================== NETWORK (safe fetch with retries) ===================
def _post_json(url, payload, timeout=30, retries=2, backoff=0.8):
    last_err = None
    for i in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
            else:
                # Some hooks return text that is JSON; guard parse.
                try:
                    return resp.json(), None
                except Exception as je:
                    last_err = f"JSON parse error: {je}\nRaw: {resp.text[:300]}"
        except Exception as e:
            last_err = f"Request error: {e}"
        if i < retries:
            time.sleep(backoff * (i + 1))
    return None, last_err

def fetch_pl_data_once(from_dt: date | datetime, to_dt: date | datetime, cash_basis: bool):
    """Fetch one basis; returns (sections_list, error_str_or_None, debug_info_dict)."""
    if isinstance(from_dt, date) and not isinstance(from_dt, datetime):
        from_dt = datetime.combine(from_dt, datetime.min.time())
    if isinstance(to_dt, date) and not isinstance(to_dt, datetime):
        to_dt = datetime.combine(to_dt, datetime.min.time())

    payload = {
        "from_date": from_dt.strftime("%Y-%m-%d"),
        "to_date": to_dt.strftime("%Y-%m-%d"),
        "cash_basis": "true" if cash_basis else "false",
    }
    data, err = _post_json(WEBHOOK_URL, payload)
    dbg = {"payload": payload, "raw_type": type(data).__name__ if data is not None else None}
    if err:
        return [], err, dbg

    # Expect list of sections or dict; normalize to list of sections
    if isinstance(data, list):
        sections = data
    elif isinstance(data, dict):
        # Sometimes your earlier hook returned {"Accrual":[...], "Cash":[...]}.
        key = "Cash" if cash_basis else "Accrual"
        sections = data.get(key, [])
    else:
        return [], f"Unexpected JSON root type: {type(data).__name__}", dbg

    dbg["section_names"] = _section_names(sections)
    return sections, None, dbg

def fetch_pl_data(from_dt: date | datetime, to_dt: date | datetime):
    """Returns dict with 'Accrual' and 'Cash' each a list of sections; plus a debug dict."""
    accrual_sec, accr_err, dbg_a = fetch_pl_data_once(from_dt, to_dt, cash_basis=False)
    cash_sec, cash_err, dbg_c = fetch_pl_data_once(from_dt, to_dt, cash_basis=True)
    dbg = {"accrual": dbg_a, "cash": dbg_c, "errors": {"accrual": accr_err, "cash": cash_err}}
    return {"Accrual": accrual_sec, "Cash": cash_sec}, dbg

# =================== PROCESS (robust) ===================
def process_pl_data(pl_sections):
    """
    Extract Sales, COGS, Gross Profit, Operating Expenses, Operating Profit, Net Profit.
    Prefers 'Net Profit/Loss' if present; otherwise derives:
      Net Profit = Operating Profit + Non-Op Income - Non-Op Expense
      Operating Profit derived if missing: Gross Profit - Operating Expenses
    Returns: (metrics, expenses_df, meta)
    """
    if not pl_sections or not isinstance(pl_sections, list):
        return {}, pd.DataFrame(), {"net_source": "Missing"}

    metrics = {
        "Sales": 0.0,
        "COGS": 0.0,
        "Gross Profit": 0.0,
        "Operating Expenses": 0.0,
        "Operating Profit": 0.0,
        "Net Profit": 0.0,
    }
    expenses_df = pd.DataFrame()
    meta = {"net_source": "Derived"}

    non_op_income = 0.0
    non_op_expense = 0.0
    saw_net = False
    saw_op = False

    try:
        for section in pl_sections:
            name = (section.get("name") or "").lower()
            total = _f(section.get("total"))

            if "gross profit" in name:
                metrics["Gross Profit"] = total
                for sub in (section.get("account_transactions") or []):
                    sname = (sub.get("name") or "").lower()
                    if "operating income" in sname:
                        for item in (sub.get("account_transactions") or []):
                            if (item.get("name") or "").lower() == "sales":
                                metrics["Sales"] = _f(item.get("total"))
                    elif "cost of goods" in sname:
                        for item in (sub.get("account_transactions") or []):
                            if (item.get("name") or "").lower() == "cost of goods sold":
                                metrics["COGS"] = _f(item.get("total"))

            elif "operating profit" in name:
                saw_op = True
                metrics["Operating Profit"] = total
                for sub in (section.get("account_transactions") or []):
                    if (sub.get("name") or "").lower() in ["operating expense", "operating expenses"]:
                        expenses = sub.get("account_transactions") or []
                        expenses_df = pd.DataFrame(
                            [{"Name": e.get("name", "Unknown"), "Amount": _f(e.get("total"))} for e in expenses]
                        )
                        metrics["Operating Expenses"] = _f(sub.get("total"))

            elif "non operating income" in name or "other income" in name:
                non_op_income += total
            elif "non operating expense" in name or "other expense" in name:
                non_op_expense += total

            if "net profit" in name:  # "Net Profit/Loss"
                saw_net = True
                meta["net_source"] = "Direct Net Profit/Loss"
                metrics["Net Profit"] = total

        if not saw_op:
            metrics["Operating Profit"] = metrics["Gross Profit"] - metrics["Operating Expenses"]
        if not saw_net:
            metrics["Net Profit"] = metrics["Operating Profit"] + non_op_income - non_op_expense

    except Exception as e:
        meta["net_source"] = f"Error: {e}"

    return metrics, expenses_df, meta

# =================== UI RENDERERS ===================
def display_section(metrics, exp_df, basis_label):
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Sales", f"AED {metrics.get('Sales', 0):,.2f}")
    col2.metric("COGS", f"AED {metrics.get('COGS', 0):,.2f}")
    col3.metric("Gross Profit", f"AED {metrics.get('Gross Profit', 0):,.2f}")
    col4.metric("Operating Expenses", f"AED {metrics.get('Operating Expenses', 0):,.2f}")
    col5.metric("Operating Profit", f"AED {metrics.get('Operating Profit', 0):,.2f}")
    col6.metric("Net Profit", f"AED {metrics.get('Net Profit', 0):,.2f}")

    if not exp_df.empty:
        st.subheader(f"📊 Operating Expenses ({basis_label})")
        st.dataframe(exp_df, use_container_width=True)
        fig_expenses = px.bar(
            exp_df, x="Name", y="Amount",
            title=f"Expenses by Category ({basis_label})",
            color="Amount", color_continuous_scale="Viridis"
        )
        st.plotly_chart(fig_expenses, use_container_width=True)

def display_comparison_graph(accrual_metrics, cash_metrics):
    df = pd.DataFrame({
        "Metric": ["Sales", "COGS", "Gross Profit", "Operating Expenses", "Operating Profit", "Net Profit"],
        "Accrual": [
            accrual_metrics.get("Sales", 0), accrual_metrics.get("COGS", 0), accrual_metrics.get("Gross Profit", 0),
            accrual_metrics.get("Operating Expenses", 0), accrual_metrics.get("Operating Profit", 0),
            accrual_metrics.get("Net Profit", 0)
        ],
        "Cash": [
            cash_metrics.get("Sales", 0), cash_metrics.get("COGS", 0), cash_metrics.get("Gross Profit", 0),
            cash_metrics.get("Operating Expenses", 0), cash_metrics.get("Operating Profit", 0),
            cash_metrics.get("Net Profit", 0)
        ],
    })
    fig = px.bar(
        df, x="Metric", y=["Accrual", "Cash"],
        title="📊 Accrual vs Cash (Selected Period)",
        barmode="group", labels={"Metric": "Financial Metric", "value": "Amount (AED)"},
        color_discrete_sequence=["#636EFA", "#EF553B"]
    )
    st.plotly_chart(fig, use_container_width=True)

def display_monthly_profit_chart(df_monthly: pd.DataFrame):
    if df_monthly.empty:
        st.warning("⚠️ No monthly data available for the selected range.")
        return

    bases = df_monthly["Basis"].unique().tolist()
    title = "📈 Profit Over Months"
    if len(bases) > 1:
        fig = px.line(df_monthly, x="Month", y="Net Profit", color="Basis", markers=True,
                      title=title, labels={"Net Profit": "Net Profit (AED)"})
    else:
        fig = px.line(df_monthly, x="Month", y="Net Profit", markers=True,
                      title=title, labels={"Net Profit": "Net Profit (AED)"})
    st.plotly_chart(fig, use_container_width=True)

# =================== MONTHLY SERIES ===================
@st.cache_data(show_spinner=False)
def get_monthly_profit_series(from_dt: date, to_dt: date, include_accrual: bool, include_cash: bool, debug: bool):
    rows = []
    statuses = []  # for debug table
    for label, start_d, end_d in month_range(from_dt, to_dt):
        month_info = {"Month": label, "Start": str(start_d), "End": str(end_d)}

        # Cash
        if include_cash:
            cash_sections, cash_err, dbg = fetch_pl_data_once(start_d, end_d, cash_basis=True)
            status = "OK" if (cash_sections and isinstance(cash_sections, list)) else ("ERR" if cash_err else "EMPTY")
            month_info["Cash Status"] = status
            month_info["Cash Sections"] = ", ".join(_section_names(cash_sections))[:120]
            if cash_err:
                month_info["Cash Error"] = cash_err[:180]
            cash_metrics, _, cash_meta = process_pl_data(cash_sections)
            rows.append({"Month": label, "Basis": "Cash",
                         "Net Profit": cash_metrics.get("Net Profit", 0.0),
                         "Source": cash_meta.get("net_source", "Derived")})

            if debug:
                month_info["Cash Payload"] = json.dumps(dbg.get("payload", {}))

        # Accrual
        if include_accrual:
            accrual_sections, accr_err, dbg = fetch_pl_data_once(start_d, end_d, cash_basis=False)
            status = "OK" if (accrual_sections and isinstance(accrual_sections, list)) else ("ERR" if accr_err else "EMPTY")
            month_info["Accrual Status"] = status
            month_info["Accrual Sections"] = ", ".join(_section_names(accrual_sections))[:120]
            if accr_err:
                month_info["Accrual Error"] = accr_err[:180]
            accrual_metrics, _, accrual_meta = process_pl_data(accrual_sections)
            rows.append({"Month": label, "Basis": "Accrual",
                         "Net Profit": accrual_metrics.get("Net Profit", 0.0),
                         "Source": accrual_meta.get("net_source", "Derived")})

            if debug:
                month_info["Accrual Payload"] = json.dumps(dbg.get("payload", {}))

        statuses.append(month_info)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Month", "Basis"]).reset_index(drop=True)
    status_df = pd.DataFrame(statuses)
    return df, status_df

# =================== MAIN APP ===================
def main():
    st.markdown('<h1 class="main-header">💰 Profit & Loss Dashboard</h1>', unsafe_allow_html=True)

    st.sidebar.header("📅 Date Filter")
    default_start = date(datetime.today().year, 1, 1)
    default_end = date.today()

    date_range = st.sidebar.date_input(
        "Select Date Range",
        value=[default_start, default_end],
        min_value=date(2023, 1, 1),
        max_value=date.today()
    )
    if len(date_range) != 2:
        st.info("Please select a start and end date.")
        return
    from_date, to_date = date_range[0], date_range[1]

    # Quick test button to see what the webhook returns for the whole range
    if st.sidebar.button("🔎 Test current range (one call per basis)"):
        with st.spinner("Testing webhook…"):
            data, dbg = fetch_pl_data(from_date, to_date)
        st.write("### Test result (shape only)")
        st.write({
            "accrual_sections_count": len(data.get("Accrual", [])),
            "cash_sections_count": len(data.get("Cash", [])),
            "errors": dbg.get("errors"),
        })
        if DEBUG:
            st.write("**Accrual section names:**", _section_names(data.get("Accrual", [])))
            st.write("**Cash section names:**", _section_names(data.get("Cash", [])))

    # Fetch once for overview
    with st.spinner("Fetching overview…"):
        data, dbg_overview = fetch_pl_data(from_date, to_date)
    if not data:
        st.error("No data returned at all.")
        return

    accrual_sections = data.get("Accrual", [])
    cash_sections = data.get("Cash", [])

    if DEBUG:
        st.info("Overview debug")
        st.write("Errors:", dbg_overview.get("errors"))
        st.write("Accrual section names:", _section_names(accrual_sections))
        st.write("Cash section names:", _section_names(cash_sections))

    accrual_metrics, accrual_exp, _ = process_pl_data(accrual_sections)
    cash_metrics, cash_exp, _ = process_pl_data(cash_sections)

    tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Accrual", "Cash", "Profit Over Months"])

    with tab1:
        st.subheader("📊 Accrual vs Cash (Selected Period)")
        if (not accrual_sections) and (not cash_sections):
            st.error("❌ No sections found for either basis in the selected period.")
        else:
            display_comparison_graph(accrual_metrics, cash_metrics)

    with tab2:
        st.subheader("📂 Accrual Basis (Selected Period)")
        if accrual_sections:
            display_section(accrual_metrics, accrual_exp, "Accrual")
        else:
            st.warning("No accrual sections returned for this period.")

    with tab3:
        st.subheader("📂 Cash Basis (Selected Period)")
        if cash_sections:
            display_section(cash_metrics, cash_exp, "Cash")
        else:
            st.warning("No cash sections returned for this period.")

    with tab4:
        st.subheader("📅 Profit Over Months")
        st.caption("Uses monthly Net Profit/Loss when available; derives otherwise.")
        colA, colB = st.columns(2)
        include_cash = colA.toggle("Include Cash", value=True)
        include_accrual = colB.toggle("Include Accrual", value=True)

        if not include_cash and not include_accrual:
            st.info("Select at least one basis to display.")
        else:
            with st.spinner("Building monthly series…"):
                df_monthly, status_df = get_monthly_profit_series(from_date, to_date, include_accrual, include_cash, DEBUG)
            display_monthly_profit_chart(df_monthly)

            st.markdown("#### Monthly values used in the chart")
            if not df_monthly.empty:
                df_show = df_monthly.copy()
                df_show["Net Profit (AED)"] = df_show["Net Profit"].round(2)
                st.dataframe(df_show[["Month", "Basis", "Net Profit (AED)", "Source"]], use_container_width=True)
            else:
                st.warning("No monthly values produced.")

            if DEBUG:
                st.markdown("#### Monthly call status (debug)")
                if not status_df.empty:
                    st.dataframe(status_df, use_container_width=True)
                else:
                    st.info("No status to show.")

if __name__ == "__main__":
    main()
