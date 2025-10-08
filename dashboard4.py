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

# Rate limiting
RATE_LIMIT_DELAY = 2

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

# =================== Rate-Limited API Call ===================
def rate_limited_api_call(func, *args, **kwargs):
    """Wrapper to add rate limiting to API calls"""
    if 'last_api_call' in st.session_state:
        elapsed = (datetime.now() - st.session_state['last_api_call']).total_seconds()
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
    
    result = func(*args, **kwargs)
    st.session_state['last_api_call'] = datetime.now()
    return result

# =================== Fetch Functions ===================
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

# =================== Extract Functions ===================
def extract_bank_and_ap(balance_data):
    """Extract bank balance, AP, and bank account details"""
    bank_total = 0.0
    ap_total = 0.0
    bank_details = []

    for section in balance_data.get("balance_sheet", []):
        if section.get("name") == "Assets":
            for asset in section.get("account_transactions", []):
                if asset.get("name") == "Current Assets":
                    for sub in asset.get("account_transactions", []):
                        sub_name = sub.get("name", "").lower()
                        if sub_name in ["cash", "bank", "cash and cash equivalents"]:
                            for acc in sub.get("account_transactions", []):
                                amount = float(acc.get("total", 0))
                                bank_total += amount
                                bank_details.append({
                                    "Account Name": acc.get("name", "Unknown"),
                                    "Balance": round(amount, 1)
                                })

        if section.get("name") == "Liabilities & Equities":
            for liab in section.get("account_transactions", []):
                if liab.get("name") == "Liabilities":
                    for sub in liab.get("account_transactions", []):
                        if sub.get("name") == "Current Liabilities":
                            for acc in sub.get("account_transactions", []):
                                if "accounts payable" in acc.get("name", "").lower():
                                    ap_total = float(acc.get("total", 0))
                                    break

    return round(bank_total, 1), round(ap_total, 1), bank_details

def extract_balance_components(balance_data):
    """Extract Bank, AR, Prepaid, and AP"""
    bank_total = 0.0
    ar_total = 0.0
    prepaid_total = 0.0
    ap_total = None

    def traverse_accounts(account_list, section_type):
        nonlocal bank_total, ar_total, prepaid_total, ap_total
        for acc in account_list:
            name = acc.get("name", "").strip()
            lname = name.lower()
            total = float(acc.get("total", 0.0))

            if section_type == "Assets":
                if any(k in lname for k in ["bank", "cash", "cash and cash equivalents"]):
                    bank_total += total
                elif "accounts receivable" in lname:
                    ar_total += total
                elif name == "Prepaid Expenses":
                    prepaid_total = total
            elif section_type == "Liabilities & Equities":
                #if "accounts payable" in lname and ap_total is None:
                    #ap_total = total
                if "accounts payable" in lname:
                    ap_total = (ap_total or 0) + total
            if "account_transactions" in acc:
                traverse_accounts(acc["account_transactions"], section_type)

    for section in balance_data.get("balance_sheet", []):
        section_name = section.get("name", "")
        if section_name in ["Assets", "Liabilities & Equities"]:
            traverse_accounts(section.get("account_transactions", []), section_name)

    return round(bank_total, 1), round(ar_total, 1), round(prepaid_total, 1), round(ap_total or 0.0, 1)

def get_operating_cashflow(cashflow_data):
    if not cashflow_data or "cash_flow" not in cashflow_data:
        return 0.0
    for section in cashflow_data.get("cash_flow", []):
        if section.get("section_name") == "Operating Activities":
            return round(float(section.get("total", 0)), 1)
    return 0.0

# =================== Process Functions ===================
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

    # Round all values
    return {k: round(v, 1) for k, v in metrics.items()}

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
                    {"Name": sub.get('name'), "Amount": round(float(sub.get('total', 0.0)), 1)}
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

    return {k: round(v, 1) for k, v in metrics.items()}, operating_expenses

# =================== Calculate Functions ===================
def calculate_cash_available(cash_profit, ar_total, prepaid_total, ap_total, min_reserve):
    """Cash Available = Cash Profit + AR + Prepaid - AP - Reserve"""
    cash_available = cash_profit + ar_total + prepaid_total - ap_total - min_reserve
    
    return {
        'cash_available': round(max(0, cash_available), 1),
        'cash_profit': round(cash_profit, 1),
        'ar_total': round(ar_total, 1),
        'prepaid_total': round(prepaid_total, 1),
        'ap_total': round(ap_total, 1),
        'min_reserve': round(min_reserve, 1)
    }

# =================== Monthly Data Functions ===================
def fetch_monthly_data(from_date, to_date):
    try:
        cash_data = rate_limited_api_call(get_profit_and_loss, from_date, to_date, "true")
        cash_metrics = process_data_original(cash_data)
        accrual_data = rate_limited_api_call(get_profit_and_loss, from_date, to_date, "false")
        accrual_metrics = process_data_original(accrual_data)
        return cash_metrics, accrual_metrics
    except Exception as e:
        st.error(f"Error: {e}")
        return None, None

def get_monthly_data_jan_to_sep():
    months_data = []
    months = [
        ("Jan 2025", "2025-01-01", "2025-01-31"),
        ("Feb 2025", "2025-02-01", "2025-02-28"),
        ("Mar 2025", "2025-03-01", "2025-03-31"),
        ("Apr 2025", "2025-04-01", "2025-04-30"),
        ("May 2025", "2025-05-01", "2025-05-31"),
        ("Jun 2025", "2025-06-01", "2025-06-30"),
        ("Jul 2025", "2025-07-01", "2025-07-31"),
        ("Aug 2025", "2025-08-01", "2025-08-31"),
        ("Sep 2025", "2025-09-01", "2025-09-30")
    ]
    
    progress_bar = st.progress(0)
    for idx, (month_name, from_date, to_date) in enumerate(months):
        cash_metrics, accrual_metrics = fetch_monthly_data(from_date, to_date)
        if cash_metrics and accrual_metrics:
            months_data.append({
                "Month": month_name,
                "Cash Net Profit": cash_metrics["Net Profit"],
                "Accrual Net Profit": accrual_metrics["Net Profit"]
            })
        progress_bar.progress((idx + 1) / len(months))
    
    progress_bar.empty()
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
                  title="Net Profit: January to September 2025",
                  labels={"Net Profit": "Net Profit (AED)", "Month": ""},
                  markers=True)
    
    fig.update_layout(xaxis_tickangle=-45, hovermode='x unified')
    st.plotly_chart(fig, use_container_width=True)

# =================== Main Dashboard ===================
def main():
    st.set_page_config(page_title="Cash-Based Profit Dashboard", page_icon="💰", layout="wide")
    
    st.title("💰 Cash-Based Profit & Loss Dashboard")
    st.markdown("*Professional financial analysis with real-time data from Zoho Books*")

    # Date range with Run button
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        from_date = st.date_input("📅 Start Date", value=datetime(2025, 1, 1))
    with col2:
        to_date = st.date_input("📅 End Date", value=datetime.today())
    with col3:
        st.markdown("<br>", unsafe_allow_html=True)
        run_analysis = st.button("🚀 Run Analysis", type="primary", use_container_width=True)

    if not run_analysis:
        st.info("👆 **Select your date range and click 'Run Analysis' to load financial data**")
        st.markdown("---")
        st.markdown("""
        ### 📊 Dashboard Features:
        - **Cash-Based P&L Analysis** - Real cash flow tracking
        - **Cash vs Accrual Comparison** - Understanding the difference
        - **Monthly Profit Trends** - Historical performance
        - **Operating Expenses Breakdown** - Detailed cost analysis
        - **Operating Cash Flow** - Business operations analysis
        - **Comprehensive Reports** - Export and detailed summaries
        """)
        st.stop()

    try:
        with st.spinner("⏳ Fetching data from Zoho Books... (Rate-limited for API safety)"):
            progress_text = st.empty()
            
            progress_text.text("📊 Fetching cash-based P&L...")
            cash_data = rate_limited_api_call(get_profit_and_loss, str(from_date), str(to_date), "true")
            
            progress_text.text("📈 Fetching accrual-based P&L...")
            accrual_data = rate_limited_api_call(get_profit_and_loss, str(from_date), str(to_date), "false")
            
            progress_text.text("🏦 Fetching balance sheet...")
            balance_data = rate_limited_api_call(get_balance_sheet, str(to_date))
            
            progress_text.text("💰 Fetching cash flow statement...")
            cash_flow_data = rate_limited_api_call(get_cash_flow, str(from_date), str(to_date))
            
            progress_text.empty()
        
        st.success("✅ **Data loaded successfully!**")
        
        # Process data
        cash_metrics, cash_expenses = process_data(cash_data)
        accrual_metrics, accrual_expenses = process_data(accrual_data)
        total_bank_balance, accounts_payable, bank_details = extract_bank_and_ap(balance_data)
        bank_total, ar_total, prepaid_total, ap_total = extract_balance_components(balance_data)
        operating_cf = get_operating_cashflow(cash_flow_data)

        # =================== CASH AVAILABILITY ===================
        st.markdown("---")
        st.subheader("💰 Cash Availability Analysis")

        min_reserve = st.number_input("🔒 Minimum Reserve (AED)", value=10000, step=1000, min_value=0)

        cash_available_info = calculate_cash_available(
            cash_metrics["Net Profit"], ar_total, prepaid_total, ap_total, min_reserve
        )

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("💵 Cash Net Profit", f"AED {cash_available_info['cash_profit']:,.1f}")
        with col2:
            st.metric("📄 Accounts Receivable", f"AED {cash_available_info['ar_total']:,.1f}")
        with col3:
            st.metric("📦 Prepaid Expenses", f"AED {cash_available_info['prepaid_total']:,.1f}")
        with col4:
            st.metric("📉 Accounts Payable", f"AED {cash_available_info['ap_total']:,.1f}")
        with col5:
            st.metric(
                "💰 Cash Available", 
                f"AED {cash_available_info['cash_available']:,.1f}",
                help="Profit + AR + Prepaid - AP - Reserve"
            )

        if cash_available_info['cash_available'] <= 0:
            st.error("⚠️ **No cash available for withdrawal** - Liabilities exceed available assets")
        elif cash_available_info['cash_available'] < 50000:
            st.warning("⚠️ **Limited cash available** - Monitor cash flow closely")
        else:
            st.success("✅ **Healthy cash position** - Funds available for strategic use")

        with st.expander("💡 View Calculation Details"):
            st.write(f"""
            **Formula:** Cash Available = Cash Profit + AR + Prepaid - AP - Reserve
            
            **Calculation:**
            - Cash Profit: AED {cash_available_info['cash_profit']:,.1f}
            - + Accounts Receivable: AED {cash_available_info['ar_total']:,.1f}
            - + Prepaid Expenses: AED {cash_available_info['prepaid_total']:,.1f}
            - - Accounts Payable: AED {cash_available_info['ap_total']:,.1f}
            - - Minimum Reserve: AED {cash_available_info['min_reserve']:,.1f}
            
            **= AED {cash_available_info['cash_available']:,.1f}**
            """)

        # =================== BANK & WORKING CAPITAL ===================
        st.markdown("---")
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🏦 Bank Accounts")
            st.caption(f"As of {to_date.strftime('%B %d, %Y')}")
            
            if bank_details:
                bank_df = pd.DataFrame(bank_details)
                st.dataframe(bank_df, use_container_width=True, hide_index=True)
                
                fig_bank = px.pie(
                    bank_df, 
                    values='Balance', 
                    names='Account Name',
                    title="Bank Balance Distribution",
                    hole=0.3
                )
                st.plotly_chart(fig_bank, use_container_width=True)
            else:
                st.warning("No bank account data available")
        
        with col2:
            st.subheader("💼 Working Capital")
            st.caption(f"As of {to_date.strftime('%B %d, %Y')}")
            
            wc_data = pd.DataFrame({
                'Component': ['Bank Balance', 'Accounts Receivable', 'Prepaid Expenses', 'Accounts Payable'],
                'Amount (AED)': [bank_total, ar_total, prepaid_total, -ap_total],
                'Type': ['Asset', 'Asset', 'Asset', 'Liability']
            })
            
            st.dataframe(wc_data, use_container_width=True, hide_index=True)
            
            fig_wc = go.Figure()
            colors = ['#2E8B57' if x > 0 else '#DC143C' for x in wc_data['Amount (AED)']]
            
            fig_wc.add_trace(go.Bar(
                x=wc_data['Component'],
                y=wc_data['Amount (AED)'],
                marker_color=colors,
                text=wc_data['Amount (AED)'].apply(lambda x: f'AED {abs(x):,.0f}'),
                textposition='outside'
            ))
            
            fig_wc.update_layout(
                title="Working Capital Components",
                showlegend=False,
                yaxis_title="Amount (AED)"
            )
            st.plotly_chart(fig_wc, use_container_width=True)

        # =================== DETAILED TABS ===================
        st.markdown("---")
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "💵 Cash P&L", 
            "📊 Cash vs Accrual", 
            "📈 Monthly Trends",
            "💼 Operating Expenses",
            "💧 Cash Flow",
            "📋 Reports"
        ])

        with tab1:
            st.subheader("💵 Cash-Based Profit & Loss Statement")
            st.caption(f"Period: {from_date.strftime('%b %d, %Y')} to {to_date.strftime('%b %d, %Y')}")
            
            cash_breakdown = pd.DataFrame({
                'Line Item': ['Sales', 'Cost of Goods Sold', 'Gross Profit', 'Operating Expenses', 'Operating Profit', 'Net Profit'],
                'Amount (AED)': [
                    cash_metrics['Sales'],
                    -cash_metrics['COGS'],
                    cash_metrics['Gross Profit'],
                    -cash_metrics['Operating Expenses'],
                    cash_metrics['Operating Profit'],
                    cash_metrics['Net Profit']
                ]
            })
            
            st.dataframe(cash_breakdown, use_container_width=True, hide_index=True)
            
            waterfall_data = pd.DataFrame({
                'Category': ['Sales', 'COGS', 'OpEx', 'Net Profit'],
                'Amount': [cash_metrics['Sales'], -cash_metrics['COGS'], 
                          -cash_metrics['Operating Expenses'], cash_metrics['Net Profit']],
                'Color': ['green', 'red', 'red', 'blue']
            })
            
            fig_cash = px.bar(
                waterfall_data,
                x='Category',
                y='Amount',
                color='Color',
                title="Cash-Based Profit Waterfall",
                labels={'Amount': 'Amount (AED)'},
                color_discrete_map={'green': '#2E8B57', 'red': '#DC143C', 'blue': '#1E90FF'}
            )
            fig_cash.update_layout(showlegend=False)
            st.plotly_chart(fig_cash, use_container_width=True)
            
            # Key ratios
            col1, col2, col3 = st.columns(3)
            with col1:
                gross_margin = (cash_metrics['Gross Profit'] / cash_metrics['Sales'] * 100) if cash_metrics['Sales'] != 0 else 0
                st.metric("Gross Margin", f"{gross_margin:.1f}%")
            with col2:
                operating_margin = (cash_metrics['Operating Profit'] / cash_metrics['Sales'] * 100) if cash_metrics['Sales'] != 0 else 0
                st.metric("Operating Margin", f"{operating_margin:.1f}%")
            with col3:
                net_margin = (cash_metrics['Net Profit'] / cash_metrics['Sales'] * 100) if cash_metrics['Sales'] != 0 else 0
                st.metric("Net Margin", f"{net_margin:.1f}%")

        with tab2:
            st.subheader("📊 Cash vs Accrual Comparison")
            st.caption("Understanding the difference between accounting methods")
            
            comparison_df = pd.DataFrame({
                'Metric': ['Sales', 'COGS', 'Gross Profit', 'Operating Expenses', 'Operating Profit', 'Net Profit'],
                'Cash Basis': [
                    cash_metrics['Sales'], cash_metrics['COGS'], cash_metrics['Gross Profit'],
                    cash_metrics['Operating Expenses'], cash_metrics['Operating Profit'], cash_metrics['Net Profit']
                ],
                'Accrual Basis': [
                    accrual_metrics['Sales'], accrual_metrics['COGS'], accrual_metrics['Gross Profit'],
                    accrual_metrics['Operating Expenses'], accrual_metrics['Operating Profit'], accrual_metrics['Net Profit']
                ]
            })
            
            comparison_df['Difference'] = comparison_df['Cash Basis'] - comparison_df['Accrual Basis']
            comparison_df['% Variance'] = ((comparison_df['Difference'] / comparison_df['Accrual Basis'].abs()) * 100).round(1)
            
            st.dataframe(comparison_df, use_container_width=True, hide_index=True)
            
            fig_comp = px.bar(
                comparison_df, 
                x='Metric', 
                y=['Cash Basis', 'Accrual Basis'],
                title="Cash vs Accrual Comparison",
                barmode='group',
                labels={'value': 'Amount (AED)'}
            )
            st.plotly_chart(fig_comp, use_container_width=True)
            
            st.info("""
            **Key Differences:**
            - **Cash Basis:** Records transactions when cash changes hands
            - **Accrual Basis:** Records transactions when earned/incurred regardless of cash movement
            - **Difference:** Shows timing differences in revenue and expense recognition
            """)

        with tab3:
            st.subheader("📈 Monthly Profit Trends")
            
            if st.button("📊 Load Monthly Data (Jan-Sep 2025)", type="secondary"):
                with st.spinner("Loading 9 months of data... (~18 seconds)"):
                    df_monthly = get_monthly_data_jan_to_sep()
                    
                if not df_monthly.empty:
                    plot_jan_to_sep_profit(df_monthly)
                    
                    st.markdown("---")
                    col1, col2, col3 = st.columns(3)
                    
                    cash_avg = df_monthly['Cash Net Profit'].mean()
                    accrual_avg = df_monthly['Accrual Net Profit'].mean()
                    
                    with col1:
                        st.metric("💵 Avg Cash Profit", f"AED {cash_avg:,.1f}")
                    with col2:
                        st.metric("📊 Avg Accrual Profit", f"AED {accrual_avg:,.1f}")
                    with col3:
                        st.metric("📉 Avg Difference", f"AED {(cash_avg - accrual_avg):,.1f}")
                    
                    st.dataframe(df_monthly, use_container_width=True, hide_index=True)
            else:
                st.info("Click the button above to load historical monthly data (this makes 18 API calls)")

        with tab4:
            st.subheader("💼 Operating Expenses Breakdown")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### Cash-Based Expenses")
                if cash_expenses:
                    cash_exp_df = pd.DataFrame(cash_expenses)
                    cash_exp_df = cash_exp_df[cash_exp_df['Amount'] != 0]
                    if not cash_exp_df.empty:
                        st.dataframe(cash_exp_df, use_container_width=True, hide_index=True)
                        
                        fig_cash_exp = px.pie(
                            cash_exp_df, 
                            values='Amount', 
                            names='Name',
                            title="Cash Expenses Distribution",
                            hole=0.3
                        )
                        st.plotly_chart(fig_cash_exp, use_container_width=True)
                    else:
                        st.info("No detailed expense data available")
                else:
                    st.info("No cash-based expense details available")
            
            with col2:
                st.markdown("#### Accrual-Based Expenses")
                if accrual_expenses:
                    accrual_exp_df = pd.DataFrame(accrual_expenses)
                    accrual_exp_df = accrual_exp_df[accrual_exp_df['Amount'] != 0]
                    if not accrual_exp_df.empty:
                        st.dataframe(accrual_exp_df, use_container_width=True, hide_index=True)
                        
                        fig_accrual_exp = px.pie(
                            accrual_exp_df, 
                            values='Amount', 
                            names='Name',
                            title="Accrual Expenses Distribution",
                            hole=0.3
                        )
                        st.plotly_chart(fig_accrual_exp, use_container_width=True)
                    else:
                        st.info("No detailed expense data available")
                else:
                    st.info("No accrual-based expense details available")

        with tab5:
            st.subheader("💧 Operating Cash Flow Analysis")
            st.caption(f"Period: {from_date.strftime('%b %d, %Y')} to {to_date.strftime('%b %d, %Y')}")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric(
                    "💼 Operating Cash Flow",
                    f"AED {operating_cf:,.1f}",
                    help="Cash from core operations"
                )
            
            with col2:
                st.metric(
                    "💵 Cash Net Profit",
                    f"AED {cash_metrics['Net Profit']:,.1f}"
                )
            
            with col3:
                ocf_diff = operating_cf - cash_metrics['Net Profit']
                delta_pct = (ocf_diff / abs(cash_metrics['Net Profit']) * 100) if cash_metrics['Net Profit'] != 0 else 0
                st.metric(
                    "📊 OCF vs Net Profit",
                    f"AED {ocf_diff:,.1f}",
                    delta=f"{delta_pct:.1f}%"
                )
            
            st.markdown("---")
            
            st.markdown("### 📚 Understanding Operating Cash Flow")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("""
                **What is Operating Cash Flow (OCF)?**
                
                Operating Cash Flow represents the actual cash generated from your core business operations. It excludes:
                - 🏦 Financing activities (loans, dividends)
                - 🏗️ Investing activities (asset purchases/sales)
                
                **Why it matters:**
                - Shows true cash-generating ability
                - Indicates business sustainability
                - Helps predict future cash needs
                """)
            
            with col2:
                st.markdown("""
                **Why OCF differs from Net Profit:**
                
                1. **Non-cash items** - Depreciation, amortization
                2. **Working capital changes** - AR, AP, inventory movements
                3. **Timing differences** - When cash actually moves
                
                **Interpretation:**
                - ✅ OCF > Net Profit = Strong cash conversion
                - ⚠️ OCF < Net Profit = Check working capital
                """)
            
            if operating_cf > cash_metrics['Net Profit']:
                st.success("✅ **Excellent:** Operating cash flow exceeds net profit - Strong cash conversion efficiency")
            elif operating_cf < cash_metrics['Net Profit']:
                st.warning("⚠️ **Monitor:** Net profit higher than cash flow - Review working capital management")
            else:
                st.info("ℹ️ Operating cash flow matches net profit")
            
            # Cash flow breakdown
            if cash_flow_data and 'cash_flow' in cash_flow_data:
                st.markdown("---")
                st.markdown("### 📊 Complete Cash Flow Statement")
                
                cf_breakdown = []
                for section in cash_flow_data['cash_flow']:
                    section_name = section.get('section_name', 'Unknown')
                    total = round(float(section.get('total', 0)), 1)
                    cf_breakdown.append({
                        'Activity Type': section_name,
                        'Amount (AED)': total
                    })
                
                if cf_breakdown:
                    cf_df = pd.DataFrame(cf_breakdown)
                    st.dataframe(cf_df, use_container_width=True, hide_index=True)
                    
                    fig_cf = px.bar(
                        cf_df,
                        x='Activity Type',
                        y='Amount (AED)',
                        title='Cash Flow by Activity Type',
                        color='Amount (AED)',
                        color_continuous_scale=['#DC143C', '#FFD700', '#2E8B57']
                    )
                    st.plotly_chart(fig_cf, use_container_width=True)

        with tab6:
            st.subheader("📋 Comprehensive Financial Reports")
            
            st.markdown("### 📊 Executive Summary")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 💰 Profit & Loss Summary")
                st.write(f"""
                - **Total Sales (Cash):** AED {cash_metrics['Sales']:,.1f}
                - **Total COGS:** AED {cash_metrics['COGS']:,.1f}
                - **Gross Profit:** AED {cash_metrics['Gross Profit']:,.1f}
                - **Operating Expenses:** AED {cash_metrics['Operating Expenses']:,.1f}
                - **Operating Profit:** AED {cash_metrics['Operating Profit']:,.1f}
                - **Net Profit (Cash):** AED {cash_metrics['Net Profit']:,.1f}
                """)
                
                st.markdown("#### 💼 Cash Flow Summary")
                st.write(f"""
                - **Operating Cash Flow:** AED {operating_cf:,.1f}
                - **OCF to Net Profit Ratio:** {(operating_cf / cash_metrics['Net Profit'] * 100) if cash_metrics['Net Profit'] != 0 else 0:.1f}%
                """)
            
            with col2:
                st.markdown("#### 🏦 Balance Sheet Summary")
                st.write(f"""
                - **Bank Balance:** AED {total_bank_balance:,.1f}
                - **Accounts Receivable:** AED {ar_total:,.1f}
                - **Prepaid Expenses:** AED {prepaid_total:,.1f}
                - **Accounts Payable:** AED {ap_total:,.1f}
                - **Net Working Capital:** AED {(bank_total + ar_total + prepaid_total - ap_total):,.1f}
                """)
                
                st.markdown("#### 💰 Cash Availability")
                st.write(f"""
                - **Available for Withdrawal:** AED {cash_available_info['cash_available']:,.1f}
                - **Minimum Reserve:** AED {min_reserve:,.1f}
                """)
            
            st.markdown("---")
            st.markdown("### 📈 Key Performance Indicators")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                gross_margin = (cash_metrics['Gross Profit'] / cash_metrics['Sales'] * 100) if cash_metrics['Sales'] != 0 else 0
                st.metric("Gross Margin", f"{gross_margin:.1f}%")
            
            with col2:
                operating_margin = (cash_metrics['Operating Profit'] / cash_metrics['Sales'] * 100) if cash_metrics['Sales'] != 0 else 0
                st.metric("Operating Margin", f"{operating_margin:.1f}%")
            
            with col3:
                net_margin = (cash_metrics['Net Profit'] / cash_metrics['Sales'] * 100) if cash_metrics['Sales'] != 0 else 0
                st.metric("Net Margin", f"{net_margin:.1f}%")
            
            with col4:
                ap_ratio = (ap_total / total_bank_balance * 100) if total_bank_balance != 0 else 0
                st.metric("AP to Bank %", f"{ap_ratio:.1f}%")
            
            st.markdown("---")
            st.markdown("### 📥 Export Financial Data")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Comprehensive P&L Report
                pl_report = pd.DataFrame({
                    'Metric': [
                        'Sales', 'COGS', 'Gross Profit', 'Operating Expenses', 
                        'Operating Profit', 'Net Profit', 'Operating Cash Flow',
                        'Bank Balance', 'Accounts Receivable', 'Prepaid Expenses',
                        'Accounts Payable', 'Cash Available for Withdrawal'
                    ],
                    'Amount (AED)': [
                        cash_metrics['Sales'], cash_metrics['COGS'], cash_metrics['Gross Profit'],
                        cash_metrics['Operating Expenses'], cash_metrics['Operating Profit'], 
                        cash_metrics['Net Profit'], operating_cf, total_bank_balance,
                        ar_total, prepaid_total, ap_total, cash_available_info['cash_available']
                    ],
                    'Period': [f"{from_date} to {to_date}"] * 12
                })
                
                csv_pl = pl_report.to_csv(index=False)
                st.download_button(
                    label="📥 Download Complete P&L Report",
                    data=csv_pl,
                    file_name=f"cash_pl_report_{from_date}_{to_date}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            
            with col2:
                # Balance Sheet Report
                balance_report = pd.DataFrame({
                    'Component': [
                        'Bank Balance', 'Accounts Receivable', 'Prepaid Expenses',
                        'Total Current Assets', 'Accounts Payable', 'Net Working Capital',
                        'Cash Available', 'Minimum Reserve'
                    ],
                    'Amount (AED)': [
                        total_bank_balance, ar_total, prepaid_total,
                        total_bank_balance + ar_total + prepaid_total,
                        ap_total, 
                        total_bank_balance + ar_total + prepaid_total - ap_total,
                        cash_available_info['cash_available'], min_reserve
                    ],
                    'As of Date': [str(to_date)] * 8
                })
                
                csv_balance = balance_report.to_csv(index=False)
                st.download_button(
                    label="📥 Download Balance Sheet Summary",
                    data=csv_balance,
                    file_name=f"balance_summary_{to_date}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
            
            st.markdown("---")
            st.markdown("### 💡 Financial Insights")
            
            insights = []
            
            # Cash position insights
            if cash_available_info['cash_available'] > 100000:
                insights.append("✅ **Strong cash position** - Consider strategic investments or expansion opportunities")
            elif cash_available_info['cash_available'] > 50000:
                insights.append("👍 **Healthy cash reserves** - Maintain current financial discipline")
            elif cash_available_info['cash_available'] > 0:
                insights.append("⚠️ **Limited liquidity** - Focus on improving cash collection and managing payables")
            else:
                insights.append("🚨 **Critical cash shortage** - Immediate action required to improve cash position")
            
            # Profitability insights
            if net_margin > 15:
                insights.append("💰 **Excellent profitability** - Net margin exceeds 15%, indicating strong operational efficiency")
            elif net_margin > 5:
                insights.append("📊 **Moderate profitability** - Room for improvement in cost management")
            elif net_margin > 0:
                insights.append("⚠️ **Low profitability** - Review pricing strategy and cost structure")
            else:
                insights.append("🚨 **Operating at a loss** - Urgent strategic review needed")
            
            # Cash flow insights
            if operating_cf > cash_metrics['Net Profit'] * 1.1:
                insights.append("💪 **Strong cash conversion** - Operating cash flow significantly exceeds net profit")
            elif operating_cf < cash_metrics['Net Profit'] * 0.8:
                insights.append("⚠️ **Working capital concerns** - Cash flow lagging behind reported profit")
            
            # AP/AR insights
            if ar_total > ap_total * 1.5:
                insights.append("📈 **High receivables** - Focus on accelerating collection to improve cash flow")
            if ap_total > total_bank_balance:
                insights.append("🚨 **Payables exceed bank balance** - Potential liquidity crisis, immediate attention required")
            
            for insight in insights:
                st.markdown(insight)
            
            st.markdown("---")
            st.info("""
            📌 **Note:** This dashboard provides real-time financial analysis based on your Zoho Books data. 
            All calculations use cash-basis accounting for accurate cash flow visibility. 
            For strategic decisions, consider consulting with your financial advisor.
            """)

    except Exception as e:
        st.error(f"❌ **Error loading financial data:** {str(e)}")
        
        with st.expander("🔧 Troubleshooting"):
            st.markdown("""
            **Common Issues:**
            
            1. **Rate Limiting** - Wait 60 seconds before trying again
            2. **API Credentials** - Verify CLIENT_ID, CLIENT_SECRET, and REFRESH_TOKEN
            3. **Organization ID** - Confirm ORG_ID matches your Zoho Books account
            4. **Network Issues** - Check your internet connection
            5. **Permissions** - Ensure API token has required access rights
            
            **Error Details:**
            """)
            st.code(str(e))
            
            st.markdown("""
            **Need Help?**
            - Check Zoho Books API documentation
            - Verify your API credentials in Zoho Developer Console
            - Ensure your subscription includes API access
            """)

if __name__ == "__main__":
    main()