import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import time

# =================== Zoho OAuth Configuration ===================
CLIENT_ID = "1000.6RGKF8DHKXLGDXFU9V0XL86JMM2WTF"
CLIENT_SECRET = "3433f4449427eef162583c39b6628a5f797cb99f2a"
REFRESH_TOKEN = "1000.eb9bcd7fd754f1540af1a070bfd29f05.5fa5d1aac61594aec72d4d574b1d76d7"
BASE_URL = "https://www.zohoapis.com/books/v3"
ORG_ID = "890601593"

# =================== Fetch Access Token ===================
def get_access_token():
    if 'access_token' in st.session_state and 'expires_at' in st.session_state:
        if datetime.now() < st.session_state['expires_at']:
            return st.session_state['access_token']

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
        expires_in = response.json()["expires_in"]
        expires_at = datetime.now() + timedelta(seconds=expires_in)
        
        st.session_state['access_token'] = access_token
        st.session_state['expires_at'] = expires_at
        return access_token
    else:
        raise Exception(f"Failed to refresh token: {response.text}")

# =================== Fetch Profit & Loss Data ===================
def get_profit_and_loss(from_date, to_date, cash_based="true"):
    access_token = get_access_token()
    url = f"{BASE_URL}/reports/profitandloss"
    params = {
        "organization_id": ORG_ID,
        "from_date": from_date,
        "to_date": to_date,
        "cash_based": cash_based
    }
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else {}

# =================== Fetch Balance Sheet (for period-specific bank & AP) ===================
def get_balance_sheet(to_date):
    access_token = get_access_token()
    url = f"{BASE_URL}/reports/balancesheet"
    params = {
        "organization_id": ORG_ID,
        "to_date": to_date,
        "show_rows": "non_zero"
    }
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else {}

# =================== Fetch Cash Flow Statement ===================
def get_cash_flow(from_date, to_date):
    access_token = get_access_token()
    url = f"{BASE_URL}/reports/cashflow"
    params = {
        "organization_id": ORG_ID,
        "from_date": from_date,
        "to_date": to_date
    }
    headers = {"Authorization": f"Zoho-oauthtoken {access_token}"}
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else {}

# =================== Extract Bank Balance and AP from Balance Sheet ===================
def extract_bank_and_ap(balance_data):
    bank_total = 0.0
    ap_total = 0.0
    bank_details = []

    for section in balance_data.get("balance_sheet", []):
        if section.get("name") == "Assets":
            for asset in section.get("account_transactions", []):
                if asset.get("name") == "Current Assets":
                    for sub in asset.get("account_transactions", []):
                        if sub.get("name") in ["Cash", "Bank", "Cash and Cash Equivalents"]:
                            for acc in sub.get("account_transactions", []):
                                balance = float(acc.get("total", 0))
                                bank_total += balance
                                bank_details.append({
                                    "Account Name": acc.get("name", "Unknown"),
                                    "Balance": balance,
                                    "Currency": "AED",
                                    "Account Type": "Bank"
                                })

        if section.get("name") == "Liabilities & Equities":
            for liab in section.get("account_transactions", []):
                if liab.get("name") == "Liabilities":
                    for sub in liab.get("account_transactions", []):
                        if sub.get("name") == "Current Liabilities":
                            for acc in sub.get("account_transactions", []):
                                name = acc.get("name", "").strip().lower()
                                # ✅ Match all variants like "Accounts Payable", "Accounts Payable.", etc.
                                if "accounts payable" in name:
                                    ap_value = float(acc.get("total", 0))
                                    ap_total += ap_value
                                    print(f"✅ Adding AP: {ap_value} → Running Total: {ap_total}")

    # ✅ Round to nearest whole AED to remove decimals
    ap_total = round(ap_total, 0)
    bank_total = round(bank_total, 0)

    return bank_total, ap_total, bank_details



    
# =================== Extract Operating Cash Flow ===================
def get_operating_cashflow(cashflow_data):
    if not cashflow_data or "cash_flow" not in cashflow_data:
        return 0.0
    for section in cashflow_data.get("cash_flow", []):
        if section.get("section_name") == "Operating Activities":
            return float(section.get("total", 0))
    return 0.0

# =================== Process P&L Data ===================
def process_data_original(data):
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
            total = float(transaction.get('total', 0.0))

            if name == "Operating Income":
                metrics["Sales"] = total
            elif name == "Cost of Goods Sold":
                metrics["COGS"] = total
            elif name == "Gross Profit":
                metrics["Gross Profit"] = total
            elif name == "Operating Expense":
                metrics["Operating Expenses"] = total
            elif name == "Operating Profit":
                metrics["Operating Profit"] = total
            elif name == "Net Profit/Loss":
                metrics["Net Profit"] = total

    if metrics["Gross Profit"] == 0:
        metrics["Gross Profit"] = metrics["Sales"] - metrics["COGS"]
    if metrics["Operating Profit"] == 0:
        metrics["Operating Profit"] = metrics["Gross Profit"] - metrics["Operating Expenses"]
    if metrics["Net Profit"] == 0:
        metrics["Net Profit"] = metrics["Operating Profit"]

    return metrics

def process_data(data):
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
            total = float(transaction.get('total', 0.0))

            if name == "Operating Income":
                metrics["Sales"] = total
            elif name == "Cost of Goods Sold":
                metrics["COGS"] = total
            elif name == "Gross Profit":
                metrics["Gross Profit"] = total
            elif name == "Operating Expense":
                metrics["Operating Expenses"] = total
                operating_expenses = [
                    {"Name": sub.get('name'), "Amount": float(sub.get('total', 0.0))}
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

    if metrics["Gross Profit"] == 0:
        metrics["Gross Profit"] = metrics["Sales"] - metrics["COGS"]
    if metrics["Operating Profit"] == 0:
        metrics["Operating Profit"] = metrics["Gross Profit"] - metrics["Operating Expenses"]
    if metrics["Net Profit"] == 0:
        metrics["Net Profit"] = metrics["Operating Profit"] + non_operating_income - non_operating_expenses

    return metrics, operating_expenses

# =================== CORRECTED: Calculate Profit Available for Withdrawal ===================
def calculate_available_profit(cash_net_profit, total_bank_balance, accounts_payable, minimum_reserve=10000):
    # Correct calculation: Cash Profit - AP - Reserve
    available_from_profit = max(0, cash_net_profit - accounts_payable - minimum_reserve)
    print(accounts_payable)
    # But also can't withdraw more than what's in the bank
    available_profit = min(available_from_profit, total_bank_balance - minimum_reserve)
    # Ensure it's never negative
    available_profit = max(0, available_profit)
    
    return {
        'available_profit': available_profit,
        'cash_net_profit': cash_net_profit,
        'bank_balance': total_bank_balance,
        'accounts_payable': accounts_payable,
        'minimum_reserve': minimum_reserve,
        'available_from_profit': available_from_profit
    }

# =================== Monthly Data Functions ===================
def fetch_monthly_data(from_date, to_date):
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
    months_data = []
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
                months_data.append({
                    "Month": month_name,
                    "Cash Net Profit": 0.0,
                    "Accrual Net Profit": 0.0
                })
            time.sleep(1)
    
    return pd.DataFrame(months_data)

def plot_jan_to_sep_profit(df_monthly):
    if df_monthly.empty:
        st.warning("No monthly data available.")
        return
    
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
    
    fig.update_layout(xaxis_tickangle=-45)
    st.plotly_chart(fig, use_container_width=True)

# =================== Main Dashboard ===================
def main():
    st.set_page_config(page_title="Cash-Based Profit Dashboard", page_icon="💰", layout="wide")
    
    st.title("💰 Cash-Based Profit & Loss Dashboard")
    st.markdown("*Focus on actual cash inflows and outflows for business decision making*")

    # Date range picker
    col1, col2 = st.columns(2)
    with col1:
        from_date = st.date_input("Select Start Date", value=datetime(2025, 1, 1))
    with col2:
        to_date = st.date_input("Select End Date", value=datetime.today())

    try:
        # Fetch all required data
        with st.spinner("Fetching financial data..."):
            cash_data = get_profit_and_loss(str(from_date), str(to_date), cash_based="true")
            time.sleep(1)
            
            accrual_data = get_profit_and_loss(str(from_date), str(to_date), cash_based="false")
            time.sleep(1)
            
            # Get balance sheet for period-specific bank balance and AP
            balance_data = get_balance_sheet(str(to_date))
            time.sleep(1)
            
            # Get cash flow for operating cash flow
            cash_flow_data = get_cash_flow(str(from_date), str(to_date))
        
        # Process the data
        cash_metrics, cash_expenses = process_data(cash_data)
        accrual_metrics, accrual_expenses = process_data(accrual_data)
        
        # Extract bank balance and AP from balance sheet (period-specific)
        total_bank_balance, accounts_payable, bank_details = extract_bank_and_ap(balance_data)
        
        # Extract operating cash flow
        operating_cf = get_operating_cashflow(cash_flow_data)
        
        # Calculate profit available for withdrawal with CORRECTED formula
        withdrawal_info = calculate_available_profit(
            cash_metrics["Net Profit"], 
            total_bank_balance,
            accounts_payable,
            minimum_reserve=10000
        )

        # =================== MAIN DASHBOARD ===================
        # === 🏦 Get Opening Bank Balance (previous period) ===
        previous_month_end = (from_date - timedelta(days=1)).strftime("%Y-%m-%d")
        opening_balance_data = get_balance_sheet(previous_month_end)
        opening_bank_balance, _, _ = extract_bank_and_ap(opening_balance_data)
        print("✅ Opening Bank Balance:", opening_bank_balance)

        # === 💵 Define variables for new formula ===
        cash_based_profit = cash_metrics["Net Profit"]
        pending_payables = accounts_payable
        reserve_amount = 10000  # You can make this a Streamlit input later

        # === 🧮 Apply new formula ===
        cash_available_for_withdrawal = (
        opening_bank_balance + cash_based_profit - pending_payables - reserve_amount
        )

        # === 🧾 Debugging print ===
        print("✅ Cash-Based Profit:", cash_based_profit)
        print("✅ Pending Payables:", pending_payables)
        print("✅ Reserve Amount:", reserve_amount)
        print("✅ Cash Available for Withdrawal:", cash_available_for_withdrawal)

        # === 📊 Display results on Streamlit ===
        st.markdown("---")
        st.subheader("💰 Cash Availability Summary (New Formula)")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("🏦 Opening Bank Balance", f"AED {opening_bank_balance:,.0f}")

        with col2:
            st.metric("💵 Cash-Based Profit (Loss)", f"AED {cash_based_profit:,.0f}")

        with col3:
            st.metric("📄 Pending Payables", f"AED {pending_payables:,.0f}")

        with col4:
            st.metric("💰 Cash Available for Withdrawal", f"AED {cash_available_for_withdrawal:,.0f}",
                    help="Formula: Opening Bank + Cash Profit − Payables − Reserve")


        # =================== DETAILED SECTIONS ===================
        st.markdown("---")
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("🏦 Bank Account Details")
            st.caption(f"As of {to_date}")
            if bank_details:
                bank_df = pd.DataFrame(bank_details)
                st.dataframe(bank_df, use_container_width=True)
                
                fig_bank = px.pie(bank_df, values='Balance', names='Account Name', 
                                title="Bank Balance Distribution")
                st.plotly_chart(fig_bank, use_container_width=True)
            else:
                st.warning("No bank account data available")
        
        with col2:
            st.subheader("💵 Profit Withdrawal Analysis")
            
            st.write("**Withdrawal Calculation:**")
            st.write(f"• Cash Net Profit: AED {withdrawal_info['cash_net_profit']:,.2f}")
            st.write(f"• Accounts Payable: AED {withdrawal_info['accounts_payable']:,.2f}")
            st.write(f"• Minimum Reserve: AED {withdrawal_info['minimum_reserve']:,.2f}")
            st.write(f"• Calculation: {withdrawal_info['cash_net_profit']:,.2f} - {withdrawal_info['accounts_payable']:,.2f} - {withdrawal_info['minimum_reserve']:,.2f}")
            st.write(f"• Available from Profit: AED {withdrawal_info['available_from_profit']:,.2f}")
            st.write(f"• Current Bank Balance: AED {withdrawal_info['bank_balance']:,.2f}")
            st.success(f"**💰 Available for Withdrawal: AED {withdrawal_info['available_profit']:,.2f}**")
            st.caption("(Limited by available cash profit after paying obligations and reserves)")
            
            # Withdrawal safety indicator
            if withdrawal_info['bank_balance'] > 0:
                safety_ratio = withdrawal_info['available_profit'] / withdrawal_info['bank_balance']
                
                if accounts_payable > total_bank_balance:
                    st.error("⚠️ CRITICAL: AP exceeds bank balance - negative cash position!")
                elif safety_ratio > 0.8:
                    st.error("⚠️ High withdrawal ratio - consider keeping more reserves")
                elif safety_ratio > 0.6:
                    st.warning("⚠️ Moderate withdrawal ratio - monitor cash flow")
                else:
                    st.success("✅ Safe withdrawal amount")

        # =================== TABBED DETAILED ANALYSIS ===================
        st.markdown("---")
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "💵 Cash-Based P&L", 
            "📊 Cash vs Accrual", 
            "📈 Monthly Trends",
            "💼 Operating Expenses",
            "💧 Operating Cash Flow",
            "📋 Detailed Reports"
        ])

        with tab1:
            st.subheader("💵 Cash-Based Profit & Loss Statement")
            st.write(f"**Period:** {from_date} to {to_date}")
            
            cash_breakdown = pd.DataFrame({
                'Item': ['Sales', 'Cost of Goods Sold', 'Gross Profit', 'Operating Expenses', 'Operating Profit', 'Net Profit'],
                'Amount (AED)': [
                    cash_metrics['Sales'],
                    -cash_metrics['COGS'],
                    cash_metrics['Gross Profit'],
                    -cash_metrics['Operating Expenses'],
                    cash_metrics['Operating Profit'],
                    cash_metrics['Net Profit']
                ]
            })
            
            st.dataframe(cash_breakdown, use_container_width=True)
            
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
            
            fig_comp = px.bar(comparison_df, x='Metric', y=['Cash Basis (AED)', 'Accrual Basis (AED)'], 
                            title="Cash vs Accrual Comparison", barmode='group')
            st.plotly_chart(fig_comp, use_container_width=True)

        with tab3:
            st.subheader("📈 Monthly Profit Trends")
            
            monthly_view = st.selectbox(
                "Choose Monthly Analysis:",
                ["January to September 2025", "Custom Period Analysis"]
            )
            
            if monthly_view == "January to September 2025":
                df_monthly_fixed = get_monthly_data_jan_to_sep()
                plot_jan_to_sep_profit(df_monthly_fixed)
                
                if not df_monthly_fixed.empty:
                    st.subheader("📋 Monthly Data Summary")
                    
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
                    cash_exp_df = cash_exp_df[cash_exp_df['Amount'] != 0]
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
                    accrual_exp_df = accrual_exp_df[accrual_exp_df['Amount'] != 0]
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
            st.subheader("💧 Operating Cash Flow Analysis")
            st.write(f"**Period:** {from_date} to {to_date}")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric(
                    label="💼 Operating Cash Flow",
                    value=f"AED {operating_cf:,.2f}",
                    help="Cash generated from core business operations"
                )
            
            with col2:
                st.metric(
                    label="💵 Cash Net Profit",
                    value=f"AED {cash_metrics['Net Profit']:,.2f}"
                )
            
            with col3:
                ocf_diff = operating_cf - cash_metrics['Net Profit']
                st.metric(
                    label="📊 OCF vs Net Profit",
                    value=f"AED {ocf_diff:,.2f}",
                    delta=f"{(ocf_diff / cash_metrics['Net Profit'] * 100) if cash_metrics['Net Profit'] != 0 else 0:.1f}%"
                )
            
            st.markdown("---")
            
            st.write("### Understanding Operating Cash Flow")
            st.write("""
            **Operating Cash Flow (OCF)** shows the actual cash generated from your business operations, excluding:
            - Financing activities (loans, dividends)
            - Investing activities (buying/selling assets)
            
            **Why OCF differs from Net Profit:**
            - Net Profit includes non-cash items (depreciation, amortization)
            - OCF accounts for changes in working capital (receivables, payables, inventory)
            - OCF shows actual cash in/out, Net Profit shows accounting profit
            """)
            
            if operating_cf > cash_metrics['Net Profit']:
                st.success("✅ Positive: Operating cash flow exceeds net profit - strong cash conversion")
            elif operating_cf < cash_metrics['Net Profit']:
                st.warning("⚠️ Caution: Net profit higher than operating cash flow - check working capital")
            else:
                st.info("ℹ️ Operating cash flow matches net profit")
            
            # Cash flow breakdown if available
            if cash_flow_data and 'cash_flow' in cash_flow_data:
                st.write("### Cash Flow Statement Breakdown")
                
                cf_breakdown = []
                for section in cash_flow_data['cash_flow']:
                    section_name = section.get('section_name', 'Unknown')
                    total = float(section.get('total', 0))
                    cf_breakdown.append({
                        'Activity': section_name,
                        'Amount (AED)': total
                    })
                
                if cf_breakdown:
                    cf_df = pd.DataFrame(cf_breakdown)
                    st.dataframe(cf_df, use_container_width=True)
                    
                    fig_cf = px.bar(
                        cf_df,
                        x='Activity',
                        y='Amount (AED)',
                        title='Cash Flow by Activity Type',
                        color='Amount (AED)',
                        color_continuous_scale=['red', 'yellow', 'green']
                    )
                    st.plotly_chart(fig_cf, use_container_width=True)

        with tab6:
            st.subheader("📋 Detailed Financial Reports")
            
            st.write("### Executive Summary")
            st.write(f"""
            **Cash-Based Performance Summary** ({from_date} to {to_date})
            
            • **Total Sales (Cash):** AED {cash_metrics['Sales']:,.2f}
            • **Total Expenses (Cash):** AED {cash_metrics['COGS'] + cash_metrics['Operating Expenses']:,.2f}
            • **Net Profit (Cash):** AED {cash_metrics['Net Profit']:,.2f}
            • **Operating Cash Flow:** AED {operating_cf:,.2f}
            • **Current Bank Balance:** AED {total_bank_balance:,.2f}
            • **Accounts Payable:** AED {accounts_payable:,.2f}
            • **Available for Withdrawal:** AED {withdrawal_info['available_profit']:,.2f}
            
            **Key Insights:**
            • Cash profit margin: {(cash_metrics['Net Profit'] / cash_metrics['Sales'] * 100) if cash_metrics['Sales'] != 0 else 0:.1f}%
            • Operating cash flow to net profit ratio: {(operating_cf / cash_metrics['Net Profit'] * 100) if cash_metrics['Net Profit'] != 0 else 0:.1f}%
            • Bank balance covers {(total_bank_balance / (cash_metrics['Operating Expenses'] / 30)) if cash_metrics['Operating Expenses'] != 0 else 0:.1f} days of average daily expenses
            • Cash vs Accrual profit difference: AED {cash_metrics['Net Profit'] - accrual_metrics['Net Profit']:,.2f}
            • AP to Bank Balance ratio: {(accounts_payable / total_bank_balance * 100) if total_bank_balance != 0 else 0:.1f}%
            """)
            
            # Export options
            st.write("### Export Data")
            col1, col2 = st.columns(2)
            
            with col1:
                # Prepare cash report for download
                cash_report = pd.DataFrame({
                    'Metric': ['Sales', 'COGS', 'Gross Profit', 'Operating Expenses', 'Operating Profit', 'Net Profit', 'Operating Cash Flow'],
                    'Cash Basis (AED)': [
                        cash_metrics['Sales'], cash_metrics['COGS'], cash_metrics['Gross Profit'],
                        cash_metrics['Operating Expenses'], cash_metrics['Operating Profit'], 
                        cash_metrics['Net Profit'], operating_cf
                    ],
                    'Period': [f"{from_date} to {to_date}"] * 7
                })
                
                csv = cash_report.to_csv(index=False)
                st.download_button(
                    label="Download Cash P&L Report",
                    data=csv,
                    file_name=f"cash_pl_report_{from_date}_to_{to_date}.csv",
                    mime="text/csv"
                )
            
            with col2:
                # Bank balance report
                if bank_details:
                    bank_df = pd.DataFrame(bank_details)
                    bank_df['Period End Date'] = str(to_date)
                    bank_df['Accounts Payable'] = accounts_payable
                    bank_df['Available for Withdrawal'] = withdrawal_info['available_profit']
                    
                    bank_csv = bank_df.to_csv(index=False)
                    st.download_button(
                        label="Download Bank Balance Report",
                        data=bank_csv,
                        file_name=f"bank_balance_report_{to_date}_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv"
                    )
                else:
                    st.info("No bank data available for download")

    except Exception as e:
        st.error(f"Error loading financial data: {str(e)}")
        st.info("Please check your Zoho Books API credentials and organization ID")
        
        # Show debug information if needed
        with st.expander("Debug Information"):
            st.write("**Possible Issues:**")
            st.write("1. Invalid API credentials")
            st.write("2. Incorrect organization ID")
            st.write("3. Network connectivity issues")
            st.write("4. API rate limiting")
            st.write("5. Insufficient permissions for the API token")
            st.write(f"**Error details:** {str(e)}")

if __name__ == "__main__":
    main()