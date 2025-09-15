import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from datetime import datetime

# ------------------- CONFIG -------------------
st.set_page_config(page_title="📊 Profit & Loss Dashboard", layout="wide")

WEBHOOK_URL = "https://hook.eu2.make.com/5naam9qq4wr6ttvesd9cn3sdzvxaxu3d" 
 #             https://hook.eu2.make.com/5naam9qq4wr6ttvesd9cn3sdzvxaxu3d

# ------------------- FETCH DATA -------------------
def fetch_pl_data(from_date=None, to_date=None):
    """Fetch both Accrual and Cash P&L JSON from webhook with date filters"""
    try:
        if not (from_date and to_date):
            return {"Accrual": [], "Cash": []}

        # Payloads for both bases
        accrual_payload = {
            "from_date": from_date.strftime("%Y-%m-%d"),
            "to_date": to_date.strftime("%Y-%m-%d"),
            "cash_basis": "false"
        }
        cash_payload = {
            "from_date": from_date.strftime("%Y-%m-%d"),
            "to_date": to_date.strftime("%Y-%m-%d"),
            "cash_basis": "true"
        }

        # Debug logs
        #st.write("📤 Sending Accrual payload:", accrual_payload)
        #t.write("📤 Sending Cash payload:", cash_payload)

        # Send both requests
        accrual_resp = requests.post(WEBHOOK_URL, json=accrual_payload, timeout=20)
        cash_resp = requests.post(WEBHOOK_URL, json=cash_payload, timeout=20)

        # Parse responses safely
        accrual_data = accrual_resp.json() if accrual_resp.status_code == 200 else []
        cash_data = cash_resp.json() if cash_resp.status_code == 200 else []

        return {"Accrual": accrual_data, "Cash": cash_data}

    except Exception as e:
        st.error(f"❌ Error fetching data: {e}")
        return {"Accrual": [], "Cash": []}


# ------------------- PROCESS DATA -------------------
def process_pl_data(pl_sections):
    """Extract Sales, COGS, Gross Profit, Operating Profit, Expenses, Net Profit safely"""
    if not pl_sections or not isinstance(pl_sections, list):
        return {}, pd.DataFrame()

    metrics = {
        "Sales": 0,
        "COGS": 0,
        "Gross Profit": 0,
        "Operating Expenses": 0,
        "Operating Profit": 0,
        "Net Profit": 0,
    }
    expenses_df = pd.DataFrame()

    try:
        for section in pl_sections:
            name = (section.get("name") or "").lower()

            # --- GROSS PROFIT SECTION ---
            if "gross profit" in name:
                metrics["Gross Profit"] = section.get("total", 0)

                for sub in section.get("account_transactions", []):
                    sub_name = (sub.get("name") or "").lower()

                    if "operating income" in sub_name:
                        for item in sub.get("account_transactions", []):
                            if (item.get("name") or "").lower() == "sales":
                                metrics["Sales"] = item.get("total", 0)

                    elif "cost of goods" in sub_name:
                        for item in sub.get("account_transactions", []):
                            if (item.get("name") or "").lower() == "cost of goods sold":
                                metrics["COGS"] = item.get("total", 0)

            # --- OPERATING PROFIT SECTION ---
            elif "operating profit" in name:
                metrics["Operating Profit"] = section.get("total", 0)

                for sub in section.get("account_transactions", []):
                    if (sub.get("name") or "").lower() == "operating expense":
                        expenses = sub.get("account_transactions", [])
                        expenses_df = pd.DataFrame(
                            [{"Name": e.get("name", "Unknown"), "Amount": e.get("total", 0)} for e in expenses]
                        )
                        metrics["Operating Expenses"] = sub.get("total", 0)

            # --- NET PROFIT SECTION ---
            elif "net profit" in name:
                metrics["Net Profit"] = section.get("total", 0)

        return metrics, expenses_df

    except Exception as e:
        st.error(f"⚠️ Error processing data: {e}")
        return metrics, pd.DataFrame()

# ------------------- DISPLAY SECTION -------------------
def display_section(metrics, exp_df, basis):
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Sales", f"AED {metrics.get('Sales', 0):,.2f}")
    col2.metric("COGS", f"AED {metrics.get('COGS', 0):,.2f}")
    col3.metric("Gross Profit", f"AED {metrics.get('Gross Profit', 0):,.2f}")
    col4.metric("Operating Expenses", f"AED {metrics.get('Operating Expenses', 0):,.2f}")
    col5.metric("Operating Profit", f"AED {metrics.get('Operating Profit', 0):,.2f}")
    col6.metric("Net Profit", f"AED {metrics.get('Net Profit', 0):,.2f}")

    if not exp_df.empty:
        st.subheader(f"📊 Operating Expenses ({basis})")
        st.dataframe(exp_df, use_container_width=True)

        fig_expenses = px.bar(
            exp_df, x="Name", y="Amount",
            title=f"Expenses by Category ({basis})",
            color="Amount", color_continuous_scale="Viridis"
        )
        st.plotly_chart(fig_expenses, use_container_width=True)

# ------------------- MAIN APP -------------------
def main():
    st.markdown('<h1 class="main-header">💰 Profit & Loss Dashboard</h1>', unsafe_allow_html=True)

    # Sidebar Date filter
    st.sidebar.header("📅 Date Filter")
    default_start = datetime(datetime.today().year, 1, 1)
    default_end = datetime.today()

    date_range = st.sidebar.date_input(
        "Select Date Range",
        value=[default_start, default_end],
        min_value=datetime(2023, 1, 1).date(),
        max_value=datetime.today().date()
    )

    from_date, to_date = None, None
    if len(date_range) == 2:
        # Convert to datetime so strftime works correctly
        from_date = datetime.combine(date_range[0], datetime.min.time())
        to_date = datetime.combine(date_range[1], datetime.min.time())

    # Fetch filtered data
    data = fetch_pl_data(from_date, to_date)

    if not data:
        st.warning("⚠️ No data returned for this period.")
        return

    # Detect whether webhook returned dict or list
    if isinstance(data, dict):
        accrual_sections = data.get("Accrual", [])
        cash_sections = data.get("Cash", [])
    elif isinstance(data, list):
        accrual_sections = data
        cash_sections = []
    else:
        st.error("❌ Unexpected data format.")
        return

    # Process accrual and cash
    accrual_metrics, accrual_exp = process_pl_data(accrual_sections)
    cash_metrics, cash_exp = process_pl_data(cash_sections)

    st.subheader("📂 Accrual Basis")
    if accrual_metrics:
        display_section(accrual_metrics, accrual_exp, "Accrual")
    else:
        st.error("❌ No accrual data available.")

    st.markdown("---")

    st.subheader("📂 Cash Basis")
    if cash_metrics:
        display_section(cash_metrics, cash_exp, "Cash")
    else:
        st.error("❌ No cash data available.")

if __name__ == "__main__":
    main()
