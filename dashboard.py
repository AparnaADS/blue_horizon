import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
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

# =================== Fetch Bank Accounts ===================
def get_bank_accounts():
    """Fetch bank accounts and their balances from Zoho Books."""
    access_token = get_access_token()
    url = f"{BASE_URL}/bankaccounts"
    params = {
        "organization_id": "890601593",  # Replace with your Zoho organization ID
    }
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}"
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Error fetching bank accounts {response.status_code}: {response.text}")

# =================== Fetch Cash Flow Statement ===================
def get_cash_flow(from_date, to_date):
    """Fetch cash flow statement from Zoho Books."""
    access_token = get_access_token()
    url = f"{BASE_URL}/reports/cashflow"
    params = {
        "organization_id": "890601593",  # Replace with your Zoho organization ID
        "from_date": from_date,
        "to_date": to_date,
    }
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}"
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        st.warning(f"Cash flow data not available: {response.status_code}")
        return {}

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

# =================== Process Bank Data ===================
def process_bank_data(bank_data):
    """Process bank account data to get total balance."""
    total_balance = 0.0
    bank_details = []
    
    if 'bankaccounts' in bank_data:
        for account in bank_data['bankaccounts']:
            account_name = account.get('account_name', 'Unknown Account')
            balance = float(account.get('balance', 0.0))
            currency = account.get('currency_code', 'AED')
            
            bank_details.append({
                'Account Name': account_name,
                'Balance': balance,
                'Currency': currency,
                'Account Type': account.get('account_type', 'Bank')
            })
            
            total_balance += balance
    
    return total_balance, bank_details

# =================== Calculate Profit Available for Withdrawal ===================
def calculate_available_profit(cash_net_profit, total_bank_balance, minimum_reserve=10000):
    """
    Calculate profit available for withdrawal.
    
    Parameters:
    - cash_net_profit: Net profit from cash-based P&L
    - total_bank_balance: Current bank balance
    - minimum_reserve: Minimum amount to keep in bank (default 10,000 AED)
    """
    
    # Basic calculation: Available = Min(Cash Net Profit, Bank Balance - Reserve)
    available_from_balance = max(0, total_bank_balance - minimum_reserve)
    available_profit = min(max(0, cash_net_profit), available_from_balance)
    
    return {
        'available_profit': available_profit,
        'cash_net_profit': cash_net_profit,
        'bank_balance': total_bank_balance,
        'minimum_reserve': minimum_reserve,
        'available_from_balance': available_from_balance
    }

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

# =================== Display Cash Flow Summary ===================
def display_cash_flow_summary(cash_data, from_date, to_date):
    """Display cash flow summary if available."""
    if not cash_data:
        st.info("💡 Cash flow data not available for the selected period.")
        return
    
    st.write("### 💰 Cash Flow Summary")
    
    # This is a simplified version - you might need to adjust based on Zoho's actual response structure
    if 'cash_flow' in cash_data:
        for section in cash_data['cash_flow']:
            section_name = section.get('section_name', 'Unknown Section')
            total = section.get('total', 0.0)
            
            if 'operating' in section_name.lower():
                st.metric("Cash from Operations", f"AED {total:,.2f}")
            elif 'investing' in section_name.lower():
                st.metric("Cash from Investing", f"AED {total:,.2f}")
            elif 'financing' in section_name.lower():
                st.metric("Cash from Financing", f"AED {total:,.2f}")

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

# =================== Streamlit Dashboard ===================
def main():
    st.set_page_config(page_title="Cash-Based Profit Dashboard", page_icon="💰", layout="wide")
    
    st.title("💰 Cash-Based Profit & Loss Dashboard")
    st.markdown("*Focus on actual cash inflows and outflows for business decision making*")

    # Date range picker for the user to select
    col1, col2 = st.columns(2)
    with col1:
        from_date = st.date_input("Select Start Date", value=datetime(2025, 1, 1))
    with col2:
        to_date = st.date_input("Select End Date", value=datetime.today())

    try:
        # Fetch all required data
        with st.spinner("Fetching financial data..."):
            # Fetch P&L data
            cash_data = get_profit_and_loss(str(from_date), str(to_date), cash_based="true")
            time.sleep(1)  # Rate limiting
            
            accrual_data = get_profit_and_loss(str(from_date), str(to_date), cash_based="false")
            time.sleep(1)  # Rate limiting
            
            # Fetch bank data
            bank_data = get_bank_accounts()
            time.sleep(1)  # Rate limiting
            
            # Fetch cash flow (optional)
            cash_flow_data = get_cash_flow(str(from_date), str(to_date))
        
        # Process the data
        cash_metrics, cash_expenses = process_data(cash_data)
        accrual_metrics, accrual_expenses = process_data(accrual_data)
        total_bank_balance, bank_details = process_bank_data(bank_data)
        
        # Calculate profit available for withdrawal
        withdrawal_info = calculate_available_profit(
            cash_metrics["Net Profit"], 
            total_bank_balance,
            minimum_reserve=10000  # You can make this configurable
        )

        # =================== MAIN DASHBOARD - Cash-Based Focus ===================
        st.markdown("---")
        st.subheader("🎯 Cash-Based Financial Overview")
        
        # Key Metrics Row
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                label="💵 Cash Net Profit", 
                value=f"AED {cash_metrics['Net Profit']:,.2f}",
                delta=f"vs Accrual: AED {cash_metrics['Net Profit'] - accrual_metrics['Net Profit']:,.2f}"
            )
        
        with col2:
            st.metric(
                label="🏦 Total Bank Balance", 
                value=f"AED {total_bank_balance:,.2f}"
            )
        
        with col3:
            st.metric(
                label="💰 Available for Withdrawal", 
                value=f"AED {withdrawal_info['available_profit']:,.2f}",
                help="Based on cash profit and maintaining minimum reserve"
            )
        
        with col4:
            cash_margin = (cash_metrics['Net Profit'] / cash_metrics['Sales'] * 100) if cash_metrics['Sales'] != 0 else 0
            st.metric(
                label="📊 Cash Profit Margin", 
                value=f"{cash_margin:.1f}%"
            )

        # =================== DETAILED SECTIONS ===================
        
        # Bank Balance Details
        st.markdown("---")
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("🏦 Bank Account Details")
            if bank_details:
                bank_df = pd.DataFrame(bank_details)
                st.dataframe(bank_df, use_container_width=True)
                
                # Bank balance chart
                fig_bank = px.pie(bank_df, values='Balance', names='Account Name', 
                                title="Bank Balance Distribution")
                st.plotly_chart(fig_bank, use_container_width=True)
            else:
                st.warning("No bank account data available")
        
        with col2:
            st.subheader("💵 Profit Withdrawal Analysis")
            
            st.write("**Withdrawal Calculation:**")
            st.write(f"• Cash Net Profit: AED {withdrawal_info['cash_net_profit']:,.2f}")
            st.write(f"• Current Bank Balance: AED {withdrawal_info['bank_balance']:,.2f}")
            st.write(f"• Minimum Reserve: AED {withdrawal_info['minimum_reserve']:,.2f}")
            st.write(f"• Available from Balance: AED {withdrawal_info['available_from_balance']:,.2f}")
            st.success(f"**💰 Available for Withdrawal: AED {withdrawal_info['available_profit']:,.2f}**")
            
            # Withdrawal safety indicator
            safety_ratio = withdrawal_info['available_profit'] / withdrawal_info['bank_balance'] if withdrawal_info['bank_balance'] > 0 else 0
            
            if safety_ratio > 0.8:
                st.error("⚠️ High withdrawal ratio - consider keeping more reserves")
            elif safety_ratio > 0.6:
                st.warning("⚠️ Moderate withdrawal ratio - monitor cash flow")
            else:
                st.success("✅ Safe withdrawal amount")

        # Cash Flow Summary
        if cash_flow_data:
            display_cash_flow_summary(cash_flow_data, from_date, to_date)

        # =================== TABBED DETAILED ANALYSIS ===================
        st.markdown("---")
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "💵 Cash-Based P&L", 
            "📊 Cash vs Accrual Comparison", 
            "📈 Monthly Trends",
            "💼 Operating Expenses",
            "📋 Detailed Reports"
        ])

        with tab1:
            st.subheader("💵 Cash-Based Profit & Loss Statement")
            st.write(f"**Period:** {from_date} to {to_date}")
            
            # Cash-based P&L breakdown
            cash_breakdown = pd.DataFrame({
                'Item': ['Sales', 'Cost of Goods Sold', 'Gross Profit', 'Operating Expenses', 'Operating Profit', 'Net Profit'],
                'Amount (AED)': [
                    cash_metrics['Sales'],
                    -cash_metrics['COGS'],  # Show as negative
                    cash_metrics['Gross Profit'],
                    -cash_metrics['Operating Expenses'],  # Show as negative
                    cash_metrics['Operating Profit'],
                    cash_metrics['Net Profit']
                ]
            })
            
            # Color-code the dataframe
            def color_amounts(val):
                color = 'red' if val < 0 else 'green' if val > 0 else 'black'
                return f'color: {color}'
            
            styled_df = cash_breakdown.style.applymap(color_amounts, subset=['Amount (AED)'])
            st.dataframe(styled_df, use_container_width=True)
            
            # Visual representation using bar chart (compatible with older Plotly versions)
            waterfall_data = pd.DataFrame({
                'Category': ['Sales', 'COGS', 'Operating Expenses', 'Net Profit'],
                'Amount': [cash_metrics['Sales'], -cash_metrics['COGS'], -cash_metrics['Operating Expenses'], cash_metrics['Net Profit']],
                'Color': ['green', 'red', 'red', 'blue']
            })
            
            fig_cash = px.bar(
                waterfall_data,
                x='Category',
                y='Amount',
                color='Color',
                title="Cash-Based Profit Flow",
                labels={'Amount': 'Amount (AED)', 'Category': 'Financial Component'},
                color_discrete_map={'green': '#2E8B57', 'red': '#DC143C', 'blue': '#1E90FF'}
            )
            fig_cash.update_layout(showlegend=False)
            st.plotly_chart(fig_cash, use_container_width=True)

        with tab2:
            st.subheader("📊 Cash vs Accrual Comparison")
            
            # Side-by-side comparison
            comparison_df = pd.DataFrame({
                'Metric': ['Sales', 'COGS', 'Gross Profit', 'Operating Expenses', 'Operating Profit', 'Net Profit'],
                'Cash Basis (AED)': [
                    cash_metrics['Sales'], cash_metrics['COGS'], cash_metrics['Gross Profit'],
                    cash_metrics['Operating Expenses'], cash_metrics['Operating Profit'], cash_metrics['Net Profit']
                ],
                'Accrual Basis (AED)': [
                    accrual_metrics['Sales'], accrual_metrics['COGS'], accrual_metrics['Gross Profit'],
                    accrual_metrics['Operating Expenses'], accrual_metrics['Operating Profit'], accrual_metrics['Net Profit']
                ]
            })
            
            comparison_df['Difference (AED)'] = comparison_df['Cash Basis (AED)'] - comparison_df['Accrual Basis (AED)']
            comparison_df['% Difference'] = (comparison_df['Difference (AED)'] / comparison_df['Accrual Basis (AED)'] * 100).round(2)
            
            st.dataframe(comparison_df, use_container_width=True)
            
            # Chart comparison
            fig_comp = px.bar(comparison_df, x='Metric', y=['Cash Basis (AED)', 'Accrual Basis (AED)'], 
                            title="Cash vs Accrual Comparison", barmode='group')
            st.plotly_chart(fig_comp, use_container_width=True)

        with tab3:
            st.subheader("📈 Monthly Profit Trends")
            
            # Monthly analysis options
            monthly_view = st.selectbox(
                "Choose Monthly Analysis:",
                ["January to September 2025", "Custom Period Analysis"]
            )
            
            if monthly_view == "January to September 2025":
                df_monthly_fixed = get_monthly_data_jan_to_sep()
                plot_jan_to_sep_profit(df_monthly_fixed)
                
                if not df_monthly_fixed.empty:
                    st.subheader("📋 Monthly Data Summary")
                    
                    # Add some analytics
                    cash_avg = df_monthly_fixed['Cash Net Profit'].mean()
                    accrual_avg = df_monthly_fixed['Accrual Net Profit'].mean()
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Average Cash Profit", f"AED {cash_avg:,.2f}")
                    with col2:
                        st.metric("Average Accrual Profit", f"AED {accrual_avg:,.2f}")
                    with col3:
                        st.metric("Average Difference", f"AED {cash_avg - accrual_avg:,.2f}")
                    
                    st.dataframe(df_monthly_fixed, use_container_width=True)
            
            else:
                st.info("Custom period monthly analysis - This would break down your selected period into months")

        with tab4:
            st.subheader("💼 Operating Expenses Breakdown")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("#### Cash-Based Operating Expenses")
                if cash_expenses:
                    cash_exp_df = pd.DataFrame(cash_expenses)
                    cash_exp_df = cash_exp_df[cash_exp_df['Amount'] != 0]  # Remove zero amounts
                    if not cash_exp_df.empty:
                        st.dataframe(cash_exp_df, use_container_width=True)
                        
                        fig_cash_exp = px.pie(cash_exp_df, values='Amount', names='Name', 
                                            title="Cash-Based Expenses Distribution")
                        st.plotly_chart(fig_cash_exp, use_container_width=True)
                    else:
                        st.info("No detailed expense data available")
                else:
                    st.info("No cash-based expense details available")
            
            with col2:
                st.write("#### Accrual-Based Operating Expenses")
                if accrual_expenses:
                    accrual_exp_df = pd.DataFrame(accrual_expenses)
                    accrual_exp_df = accrual_exp_df[accrual_exp_df['Amount'] != 0]  # Remove zero amounts
                    if not accrual_exp_df.empty:
                        st.dataframe(accrual_exp_df, use_container_width=True)
                        
                        fig_accrual_exp = px.pie(accrual_exp_df, values='Amount', names='Name', 
                                               title="Accrual-Based Expenses Distribution")
                        st.plotly_chart(fig_accrual_exp, use_container_width=True)
                    else:
                        st.info("No detailed expense data available")
                else:
                    st.info("No accrual-based expense details available")

        with tab5:
            st.subheader("📋 Detailed Financial Reports")
            
            # Summary report
            st.write("### Executive Summary")
            st.write(f"""
            **Cash-Based Performance Summary** ({from_date} to {to_date})
            
            • **Total Sales (Cash):** AED {cash_metrics['Sales']:,.2f}
            • **Total Expenses (Cash):** AED {cash_metrics['COGS'] + cash_metrics['Operating Expenses']:,.2f}
            • **Net Profit (Cash):** AED {cash_metrics['Net Profit']:,.2f}
            • **Current Bank Balance:** AED {total_bank_balance:,.2f}
            • **Available for Withdrawal:** AED {withdrawal_info['available_profit']:,.2f}
            
            **Key Insights:**
            • Cash profit margin: {(cash_metrics['Net Profit'] / cash_metrics['Sales'] * 100) if cash_metrics['Sales'] != 0 else 0:.1f}%
            • Bank balance covers {(total_bank_balance / (cash_metrics['Operating Expenses'] / 30)) if cash_metrics['Operating Expenses'] != 0 else 0:.1f} days of average daily expenses
            • Cash vs Accrual profit difference: AED {cash_metrics['Net Profit'] - accrual_metrics['Net Profit']:,.2f}
            """)
            
            # Export options
            st.write("### Export Data")
            col1, col2 = st.columns(2)
            
            with col1:
                # Prepare cash report for download
                cash_report = pd.DataFrame({
                    'Metric': ['Sales', 'COGS', 'Gross Profit', 'Operating Expenses', 'Operating Profit', 'Net Profit'],
                    'Cash Basis (AED)': [
                        cash_metrics['Sales'], cash_metrics['COGS'], cash_metrics['Gross Profit'],
                        cash_metrics['Operating Expenses'], cash_metrics['Operating Profit'], cash_metrics['Net Profit']
                    ],
                    'Period': [f"{from_date} to {to_date}"] * 6
                })
                
                csv = cash_report.to_csv(index=False)
                st.download_button(
                    label="📥 Download Cash P&L Report",
                    data=csv,
                    file_name=f"cash_pl_report_{from_date}_to_{to_date}.csv",
                    mime="text/csv"
                )
            
            with col2:
                # Bank balance report
                if bank_details:
                    bank_df = pd.DataFrame(bank_details)
                    bank_csv = bank_df.to_csv(index=False)
                    st.download_button(
                        label="📥 Download Bank Balance Report",
                        data=bank_csv,
                        file_name=f"bank_balance_report_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("No bank data available for download")

    except Exception as e:
        st.error(f"❌ Error loading financial data: {str(e)}")
        st.info("Please check your Zoho Books API credentials and organization ID")
        
        # Show debug information if needed
        with st.expander("🔍 Debug Information"):
            st.write("**Possible Issues:**")
            st.write("1. Invalid API credentials")
            st.write("2. Incorrect organization ID")
            st.write("3. Network connectivity issues")
            st.write("4. API rate limiting")
            st.write("5. Insufficient permissions for the API token")

# =================== Additional Helper Functions ===================
def format_currency(amount, currency="AED"):
    """Format currency with proper symbols and commas."""
    return f"{currency} {amount:,.2f}"

def get_profit_trend_indicator(current_profit, previous_profit):
    """Get trend indicator for profit comparison."""
    if previous_profit == 0:
        return "📊 No comparison data"
    
    change_percent = ((current_profit - previous_profit) / abs(previous_profit)) * 100
    
    if change_percent > 10:
        return f"📈 Strong Growth (+{change_percent:.1f}%)"
    elif change_percent > 0:
        return f"📈 Growth (+{change_percent:.1f}%)"
    elif change_percent > -10:
        return f"📉 Decline ({change_percent:.1f}%)"
    else:
        return f"📉 Significant Decline ({change_percent:.1f}%)"

# =================== Run the App ===================
if __name__ == "__main__":
    main()