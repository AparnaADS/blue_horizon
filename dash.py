import streamlit as st
import pandas as pd
import requests
import plotly.express as px
from datetime import datetime, date, timedelta
import time
import json


# =================== Zoho OAuth Configuration ===================
CLIENT_ID = "1000.6RGKF8DHKXLGDXFU9V0XL86JMM2WTF"  # Replace with your client ID
CLIENT_SECRET = "3433f4449427eef162583c39b6628a5f797cb99f2a"  # Replace with your client secret
REFRESH_TOKEN = "1000.eb9bcd7fd754f1540af1a070bfd29f05.5fa5d1aac61594aec72d4d574b1d76d7"  # Replace with your refresh token

BASE_URL = "https://www.zohoapis.com/books/v3"

# =================== Fetch Access Token ===================
def get_access_token():
    """Retrieve a new access token using the refresh token, or reuse the existing one if valid."""
    if 'access_token' in st.session_state and 'expires_at' in st.session_state:
        if datetime.now() < st.session_state['expires_at']:
            return st.session_state['access_token']  # Reuse the existing token if it's still valid

    token_url = "https://accounts.zoho.com/oauth/v2/token"
    params = {
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token"
    }

    response = requests.post(token_url, params=params)

    if response.status_code == 200:
        access_token = response.json()["access_token"]
        expires_in = response.json()["expires_in"]  # Get the expiration time for the token
        expires_at = datetime.now() + timedelta(seconds=expires_in)  # Calculate expiration datetime

        # Store the access token and its expiration time in session state
        st.session_state['access_token'] = access_token
        st.session_state['expires_at'] = expires_at

        return access_token
    else:
        raise Exception(f"Failed to refresh token: {response.text}")

# =================== Fetch Profit & Loss Data ===================
def get_profit_and_loss(from_date, to_date, cash_based="true"):
    """Fetch profit and loss data from Zoho Books."""
    access_token = get_access_token()  # Get fresh access token or reuse the existing one
    url = f"{BASE_URL}/reports/profitandloss"
    params = {
        "organization_id": "890601593",  # Replace with your Zoho organization ID
        "from_date": from_date,
        "to_date": to_date,
        "cash_based": cash_based
    }
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}"
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Error {response.status_code}: {response.text}")

# =================== Process Data for Display (Original from first code) ===================
def process_data_original(data):
    """Process the profit and loss data (original method from first code)."""
    metrics = {
        "Sales": 0.0,
        "COGS": 0.0,
        "Gross Profit": 0.0,
        "Operating Expenses": 0.0,
        "Operating Profit": 0.0,
        "Net Profit": 0.0,
    }

    for section in data.get('profit_and_loss', []):
        for transaction in section.get('account_transactions', []):
            name = transaction.get('name')
            total = transaction.get('total', 0.0)

            if name == "Operating Income":
                metrics["Sales"] = total
            elif name == "Cost of Goods Sold":
                metrics["COGS"] = total
            elif name == "Gross Profit":
                metrics["Gross Profit"] = total  # Update if data is directly available, otherwise calculate it
            elif name == "Operating Expense":
                metrics["Operating Expenses"] = total
            elif name == "Operating Profit":
                metrics["Operating Profit"] = total
            elif name == "Net Profit/Loss":
                metrics["Net Profit"] = total

    # Calculate missing metrics
    if metrics["Gross Profit"] == 0:
        metrics["Gross Profit"] = metrics["Sales"] - metrics["COGS"]
    
    if metrics["Operating Profit"] == 0:
        metrics["Operating Profit"] = metrics["Gross Profit"] - metrics["Operating Expenses"]
    
    if metrics["Net Profit"] == 0:
        metrics["Net Profit"] = metrics["Operating Profit"]

    return metrics

# =================== Process Data for Display (Enhanced from second code) ===================
def process_data(data):
    """Process the profit and loss data."""
    metrics = {
        "Sales": 0.0,
        "COGS": 0.0,
        "Gross Profit": 0.0,
        "Operating Expenses": 0.0,
        "Operating Profit": 0.0,
        "Net Profit": 0.0,
    }

    operating_expenses = []
    non_operating_income = 0.0
    non_operating_expenses = 0.0

    for section in data.get('profit_and_loss', []):
        for transaction in section.get('account_transactions', []):
            name = transaction.get('name')
            total = transaction.get('total', 0.0)

            if name == "Operating Income":
                metrics["Sales"] = total
            elif name == "Cost of Goods Sold":
                metrics["COGS"] = total
            elif name == "Gross Profit":
                metrics["Gross Profit"] = total  # Update if data is directly available, otherwise calculate it
            elif name == "Operating Expense":
                metrics["Operating Expenses"] = total
                # Add detailed expense data here
                operating_expenses = [
                    {"Name": sub.get('name'), "Amount": sub.get('total', 0.0)}
                    for sub in transaction.get('account_transactions', [])
                ]
            elif name == "Operating Profit":
                metrics["Operating Profit"] = total
            elif name == "Non Operating Income":
                non_operating_income += total
            elif name == "Non Operating Expense":
                non_operating_expenses += total
            elif name == "Net Profit/Loss":
                metrics["Net Profit"] = total

    # Calculate Gross Profit if not present directly
    if metrics["Gross Profit"] == 0:
        metrics["Gross Profit"] = metrics["Sales"] - metrics["COGS"]

    # Calculate Operating Profit if not present directly
    if metrics["Operating Profit"] == 0:
        metrics["Operating Profit"] = metrics["Gross Profit"] - metrics["Operating Expenses"]

    # Calculate Net Profit if not present directly
    if metrics["Net Profit"] == 0:
        metrics["Net Profit"] = metrics["Operating Profit"] + non_operating_income - non_operating_expenses

    return metrics, operating_expenses

# =================== Monthly Data Functions (from first code) ===================
def fetch_monthly_data(from_date, to_date):
    """Fetch data for a specific month using the original processing logic."""
    try:
        cash_data = get_profit_and_loss(from_date, to_date, cash_based="true")
        cash_metrics = process_data_original(cash_data)

        accrual_data = get_profit_and_loss(from_date, to_date, cash_based="false")
        accrual_metrics = process_data_original(accrual_data)

        return cash_metrics, accrual_metrics

    except Exception as e:
        st.error(f"Error fetching data for {from_date} to {to_date}: {e}")
        return None, None

def get_monthly_data_jan_to_sep():
    """Fetch monthly data from January to September 2025 (from first code logic)."""
    months_data = []
    
    # Define months with their date ranges
    months = [
        ("January 2025", "2025-01-01", "2025-01-31"),
        ("February 2025", "2025-02-01", "2025-02-28"),
        ("March 2025", "2025-03-01", "2025-03-31"),
        ("April 2025", "2025-04-01", "2025-04-30"),
        ("May 2025", "2025-05-01", "2025-05-31"),
        ("June 2025", "2025-06-01", "2025-06-30"),
        ("July 2025", "2025-07-01", "2025-07-31"),
        ("August 2025", "2025-08-01", "2025-08-31"),
        ("September 2025", "2025-09-01", "2025-09-30")
    ]
    
    for month_name, from_date, to_date in months:
        with st.spinner(f"Fetching {month_name} profit data..."):
            cash_metrics, accrual_metrics = fetch_monthly_data(from_date, to_date)
            
            if cash_metrics and accrual_metrics:
                months_data.append({
                    "Month": month_name,
                    "Cash Net Profit": cash_metrics["Net Profit"],
                    "Accrual Net Profit": accrual_metrics["Net Profit"]
                })
            else:
                # Add zero values if data fetch failed
                months_data.append({
                    "Month": month_name,
                    "Cash Net Profit": 0.0,
                    "Accrual Net Profit": 0.0
                })
            
            # Add delay to avoid rate limiting
            time.sleep(1)
    
    return pd.DataFrame(months_data)

def plot_jan_to_sep_profit(df_monthly):
    """Plot the net profit for January to September 2025 for both Cash and Accrual."""
    if df_monthly.empty:
        st.warning("⚠️ No monthly data available.")
        return
    
    # Melt the DataFrame to make it suitable for plotly line chart
    df_melted = df_monthly.melt(
        id_vars=['Month'], 
        value_vars=['Cash Net Profit', 'Accrual Net Profit'],
        var_name='Basis', 
        value_name='Net Profit'
    )
    
    fig = px.line(df_melted, 
                  x="Month", 
                  y="Net Profit",
                  color="Basis",
                  title="Net Profit for January to September 2025 (Cash vs Accrual)",
                  labels={"Net Profit": "Net Profit (AED)", "Month": "Month"},
                  markers=True)
    
    # Rotate x-axis labels for better readability
    fig.update_layout(xaxis_tickangle=-45)
    
    st.plotly_chart(fig, use_container_width=True)

# =================== Helper Functions for Second Code ===================
def month_start(d: date) -> date:
    """Return the start of the month for a given date."""
    return date(d.year, d.month, 1)

def next_month(d: date) -> date:
    """Return the start of the next month for a given date."""
    return date(d.year + (1 if d.month == 12 else 0), 1 if d.month == 12 else d.month + 1, 1)

def month_end(d: date) -> date:
    """Return the end of the month for a given date."""
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
    """Extract the names of sections."""
    try:
        return [str((s.get("name") or "")).strip() for s in sections] if isinstance(sections, list) else []
    except Exception:
        return []

def _f(x):
    """Safely convert values to floats."""
    try:
        return float(x or 0)
    except Exception:
        return 0.0

# =================== Streamlit Dashboard ===================
def main():
    st.title("💰 Profit & Loss Dashboard")

    # Date range picker for the user to select
    from_date = st.date_input("Select Start Date", value=datetime(2025, 1, 1))
    to_date = st.date_input("Select End Date", value=datetime.today())

    # Fetch data for Cash and Accrual basis
    try:
        # Add a delay to avoid hitting the rate limit
        cash_data = get_profit_and_loss(str(from_date), str(to_date), cash_based="true")
        time.sleep(2)  # Adding a 2-second delay between the requests to avoid hitting the rate limit
        
        accrual_data = get_profit_and_loss(str(from_date), str(to_date), cash_based="false")
        
        cash_metrics, cash_expenses = process_data(cash_data)
        accrual_metrics, accrual_expenses = process_data(accrual_data)

        # Create DataFrame for Plotly chart
        df = {
            "Metric": ["Sales", "COGS", "Gross Profit", "Operating Expenses", "Operating Profit", "Net Profit"],
            "Accrual": [
                accrual_metrics["Sales"], accrual_metrics["COGS"], accrual_metrics["Gross Profit"],
                accrual_metrics["Operating Expenses"], accrual_metrics["Operating Profit"], accrual_metrics["Net Profit"]
            ],
            "Cash": [
                cash_metrics["Sales"], cash_metrics["COGS"], cash_metrics["Gross Profit"],
                cash_metrics["Operating Expenses"], cash_metrics["Operating Profit"], cash_metrics["Net Profit"]
            ],
        }

        # Create tabs for the dashboard
        tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Accrual", "Cash", "Monthly Profits"])

        with tab1:
            st.write("### 📊 Overview")
            st.write(f"From: {from_date} To: {to_date}")
            fig = px.bar(df, x="Metric", y=["Accrual", "Cash"], 
                         title="📊 Accrual vs Cash (Selected Period)", 
                         labels={"value": "Amount (AED)", "Metric": "Financial Metric"},
                         barmode="group")
            st.plotly_chart(fig)

        with tab2:
            st.write("### 📂 Accrual Basis (Selected Period)")
            st.write(f"Sales: AED {accrual_metrics['Sales']}, COGS: AED {accrual_metrics['COGS']}")
            st.write(f"Gross Profit: AED {accrual_metrics['Gross Profit']}, Operating Profit: AED {accrual_metrics['Operating Profit']}")
            st.write(f"Operating Expenses: AED {accrual_metrics['Operating Expenses']}, Net Profit: AED {accrual_metrics['Net Profit']}")
            st.write("### Operating Expenses (Accrual)")
            if accrual_expenses:
                expense_df = pd.DataFrame(accrual_expenses)
                st.dataframe(expense_df)

        with tab3:
            st.write("### 📂 Cash Basis (Selected Period)")
            st.write(f"Sales: AED {cash_metrics['Sales']}, COGS: AED {cash_metrics['COGS']}")
            st.write(f"Gross Profit: AED {cash_metrics['Gross Profit']}, Operating Profit: AED {cash_metrics['Operating Profit']}")
            st.write(f"Operating Expenses: AED {cash_metrics['Operating Expenses']}, Net Profit: AED {cash_metrics['Net Profit']}")
            st.write("### Operating Expenses (Cash)")
            if cash_expenses:
                expense_df = pd.DataFrame(cash_expenses)
                st.dataframe(expense_df)

        with tab4:
            st.write("### 📅 Monthly Profit Analysis")
            
            # Add option to choose between different monthly views
            monthly_view = st.selectbox(
                "Choose Monthly View:",
                ["January to September 2025 (Fixed)", "Custom Date Range Monthly"]
            )
            
            if monthly_view == "January to September 2025 (Fixed)":
                st.write("#### Fixed Period: January to September 2025")
                # Use the original first code logic
                df_monthly_fixed = get_monthly_data_jan_to_sep()
                plot_jan_to_sep_profit(df_monthly_fixed)
                
                # Show the data table
                if not df_monthly_fixed.empty:
                    st.write("### Monthly Net Profit Values")
                    st.dataframe(df_monthly_fixed)
            
            else:
                st.write(f"#### Custom Range: {from_date} to {to_date}")
                st.info("This feature uses a different data processing method and may show different results.")
                # You can implement the custom range monthly analysis here if needed
                st.write("Custom monthly range analysis coming soon...")
    
    except Exception as e:
        st.error(f"Error: {e}")

# Run the Streamlit app
if __name__ == "__main__":
    main()