import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from datetime import datetime, date, timedelta

# ------------------- CONFIG -------------------
st.set_page_config(page_title="📊 Profit & Loss Dashboard", layout="wide")
WEBHOOK_URL = "https://hook.eu2.make.com/5naam9qq4wr6ttvesd9cn3sdzvxaxu3d"

# ------------------- FETCH DATA (single period, both bases) -------------------
def fetch_pl_data(from_dt: datetime | date = None, to_dt: datetime | date = None):
    """Fetch both Accrual and Cash P&L JSON from webhook for a given period."""
    try:
        if not (from_dt and to_dt):
            return {"Accrual": [], "Cash": []}

        # Normalize to datetime (handles if date objects passed)
        if isinstance(from_dt, date) and not isinstance(from_dt, datetime):
            from_dt = datetime.combine(from_dt, datetime.min.time())
        if isinstance(to_dt, date) and not isinstance(to_dt, datetime):
            to_dt = datetime.combine(to_dt, datetime.min.time())

        accrual_payload = {
            "from_date": from_dt.strftime("%Y-%m-%d"),
            "to_date": to_dt.strftime("%Y-%m-%d"),
            "cash_basis": "false",
        }
        cash_payload = {
            "from_date": from_dt.strftime("%Y-%m-%d"),
            "to_date": to_dt.strftime("%Y-%m-%d"),
            "cash_basis": "true",
        }

        accrual_resp = requests.post(WEBHOOK_URL, json=accrual_payload, timeout=20)
        cash_resp = requests.post(WEBHOOK_URL, json=cash_payload, timeout=20)

        accrual_data = accrual_resp.json() if accrual_resp.status_code == 200 else []
        cash_data = cash_resp.json() if cash_resp.status_code == 200 else []

        return {"Accrual": accrual_data, "Cash": cash_data}
    except Exception as e:
        st.error(f"❌ Error fetching data: {e}")
        return {"Accrual": [], "Cash": []}

# ------------------- PROCESS DATA (extract metrics) -------------------
def process_pl_data(pl_sections):
    """
    Extract Sales, COGS, Gross Profit, Operating Profit, Operating Expenses, Net Profit.
    Expects Zoho-like section list with 'name', 'total', 'account_transactions'.
    """
    if not pl_sections or not isinstance(pl_sections, list):
        return {}, pd.DataFrame()

    metrics = {
        "Sales": 0.0,
        "COGS": 0.0,
        "Gross Profit": 0.0,
        "Operating Expenses": 0.0,
        "Operating Profit": 0.0,
        "Net Profit": 0.0,
    }
    expenses_df = pd.DataFrame()

    try:
        for section in pl_sections:
            name = (section.get("name") or "").lower()

            # Gross Profit block holds Operating Income & COGS
            if "gross profit" in name:
                metrics["Gross Profit"] = float(section.get("total", 0) or 0)
                for sub in section.get("account_transactions", []) or []:
                    sub_name = (sub.get("name") or "").lower()

                    if "operating income" in sub_name:
                        for item in sub.get("account_transactions", []) or []:
                            if (item.get("name") or "").lower() == "sales":
                                metrics["Sales"] = float(item.get("total", 0) or 0)

                    elif "cost of goods" in sub_name:
                        for item in sub.get("account_transactions", []) or []:
                            if (item.get("name") or "").lower() == "cost of goods sold":
                                metrics["COGS"] = float(item.get("total", 0) or 0)

            elif "operating profit" in name:
                metrics["Operating Profit"] = float(section.get("total", 0) or 0)
                for sub in section.get("account_transactions", []) or []:
                    if (sub.get("name") or "").lower() == "operating expense":
                        expenses = sub.get("account_transactions", []) or []
                        expenses_df = pd.DataFrame(
                            [{"Name": e.get("name", "Unknown"), "Amount": float(e.get("total", 0) or 0)} for e in expenses]
                        )
                        metrics["Operating Expenses"] = float(sub.get("total", 0) or 0)

            elif "net profit" in name:  # covers "Net Profit/Loss"
                metrics["Net Profit"] = float(section.get("total", 0) or 0)

    except Exception as e:
        st.error(f"⚠️ Error processing data: {e}")
        return metrics, pd.DataFrame()

    return metrics, expenses_df

# ------------------- DISPLAY METRICS BOXES -------------------
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

# ------------------- COMPARISON GRAPH (period total) -------------------
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

# ------------------- MONTH HELPERS -------------------
def month_start(d: date) -> date:
    return date(d.year, d.month, 1)

def next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)

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

# ------------------- MONTHLY PROFIT (calls webhook per month) -------------------
@st.cache_data(show_spinner=False)
def get_monthly_profit_series(from_dt: date, to_dt: date, include_accrual: bool = True, include_cash: bool = True) -> pd.DataFrame:
    """
    Call the webhook month-by-month, process sections, and return a long-form DataFrame:
    columns: Month, Basis, Net Profit
    """
    rows = []
    for label, start_d, end_d in month_range(from_dt, to_dt):
        data = fetch_pl_data(start_d, end_d)

        # Extract & append Cash
        if include_cash:
            cash_sections = data.get("Cash", []) if isinstance(data, dict) else []
            cash_metrics, _ = process_pl_data(cash_sections)
            rows.append({"Month": label, "Basis": "Cash", "Net Profit": cash_metrics.get("Net Profit", 0.0)})

        # Extract & append Accrual
        if include_accrual:
            accrual_sections = data.get("Accrual", []) if isinstance(data, dict) else []
            accrual_metrics, _ = process_pl_data(accrual_sections)
            rows.append({"Month": label, "Basis": "Accrual", "Net Profit": accrual_metrics.get("Net Profit", 0.0)})

    df = pd.DataFrame(rows)
    if not df.empty:
        # Ensure chronological order
        df = df.sort_values(["Month", "Basis"]).reset_index(drop=True)
    return df

def display_monthly_profit_chart(df_monthly: pd.DataFrame):
    if df_monthly.empty:
        st.warning("⚠️ No monthly data available for the selected range.")
        return

    # Nice chart: show both bases if present, else single line
    bases = df_monthly["Basis"].unique().tolist()
    title = "📈 Profit Over Months"
    if len(bases) > 1:
        fig = px.line(
            df_monthly, x="Month", y="Net Profit", color="Basis", markers=True,
            title=title, labels={"Net Profit": "Net Profit (AED)"}
        )
    else:
        fig = px.line(
            df_monthly, x="Month", y="Net Profit", markers=True,
            title=title, labels={"Net Profit": "Net Profit (AED)"}
        )
    st.plotly_chart(fig, use_container_width=True)

# ------------------- MAIN APP -------------------
def main():
    st.markdown('<h1 class="main-header">💰 Profit & Loss Dashboard</h1>', unsafe_allow_html=True)

    # Sidebar Date filter
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

    # Fetch for overall period (one call returns both bases)
    data = fetch_pl_data(from_date, to_date)
    if not data:
        st.warning("⚠️ No data returned for this period.")
        return

    # Split sections
    if isinstance(data, dict):
        accrual_sections = data.get("Accrual", [])
        cash_sections = data.get("Cash", [])
    elif isinstance(data, list):  # Very unlikely for this webhook, but safe-guard
        accrual_sections = data
        cash_sections = []
    else:
        st.error("❌ Unexpected data format.")
        return

    # Process
    accrual_metrics, accrual_exp = process_pl_data(accrual_sections)
    cash_metrics, cash_exp = process_pl_data(cash_sections)

    # Tabs for a clean UI
    tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Accrual", "Cash", "Profit Over Months"])

    with tab1:
        st.subheader("📊 Accrual vs Cash (Selected Period)")
        display_comparison_graph(accrual_metrics, cash_metrics)

    with tab2:
        st.subheader("📂 Accrual Basis (Selected Period)")
        if accrual_metrics:
            display_section(accrual_metrics, accrual_exp, "Accrual")
        else:
            st.error("❌ No accrual data available.")

    with tab3:
        st.subheader("📂 Cash Basis (Selected Period)")
        if cash_metrics:
            display_section(cash_metrics, cash_exp, "Cash")
        else:
            st.error("❌ No cash data available.")

    with tab4:
        st.subheader("📅 Profit Over Months")
        st.caption("This chart calls the webhook for each month in your selected range and plots Net Profit.")
        # Choose which bases to include
        colA, colB = st.columns(2)
        include_cash = colA.toggle("Include Cash", value=True)
        include_accrual = colB.toggle("Include Accrual", value=True)

        if not include_cash and not include_accrual:
            st.info("Select at least one basis to display.")
        else:
            df_monthly = get_monthly_profit_series(from_date, to_date, include_accrual, include_cash)
            display_monthly_profit_chart(df_monthly)

if __name__ == "__main__":
    main()
