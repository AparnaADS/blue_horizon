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

# =================== Rate Limiting Management ===================
def rate_limited_api_call(func, *args, **kwargs):
    """Wrapper to handle rate limiting and retries."""
    max_retries = 3
    base_wait_time = 10
    
    for attempt in range(max_retries):
        try:
            # Add delay between requests
            if 'last_api_call' in st.session_state:
                time_since_last = time.time() - st.session_state['last_api_call']
                if time_since_last < 2:  # Minimum 2 seconds between calls
                    wait_time = 2 - time_since_last
                    st.info(f"Rate limiting: waiting {wait_time:.1f} seconds...")
                    time.sleep(wait_time)
            
            result = func(*args, **kwargs)
            st.session_state['last_api_call'] = time.time()
            return result
            
        except Exception as e:
            if "429" in str(e) or "rate limit" in str(e).lower():
                wait_time = base_wait_time * (2 ** attempt)  # Exponential backoff
                st.warning(f"Rate limit hit. Waiting {wait_time} seconds before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait_time)
                if attempt == max_retries - 1:
                    st.error("Maximum retries reached. Please try again in a few minutes.")
                    raise e
            else:
                raise e

# =================== Access Token ===================
def get_access_token():
    if 'access_token' in st.session_state and 'expires_at' in st.session_state:
        if datetime.now() < st.session_state['expires_at']:
            return st.session_state['access_token']

    def _get_token():
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

    return rate_limited_api_call(_get_token)

# =================== Fetch Bills with Date Filter ===================
def get_bills_detail(from_date=None, to_date=None):
    """Fetch bills with optional date filtering."""
    def _fetch_bills():
        access_token = get_access_token()
        url = f"{BASE_URL}/bills"
        params = {
            "organization_id": "890601593",
            "per_page": 200
        }
        
        # Add date filters if provided
        if from_date:
            params["date_start"] = from_date.strftime("%Y-%m-%d")
        if to_date:
            params["date_end"] = to_date.strftime("%Y-%m-%d")
        
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            return data
        elif response.status_code == 429:
            raise Exception("Rate limit exceeded - too many requests")
        else:
            raise Exception(f"API Error {response.status_code}: {response.text}")

    return rate_limited_api_call(_fetch_bills)

# =================== Fetch Bank Balance ===================
def get_bank_balance():
    """Get current bank balance."""
    def _fetch_balance():
        access_token = get_access_token()
        url = f"{BASE_URL}/bankaccounts"
        params = {
            "organization_id": "890601593"
        }
        
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}"
        }

        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            total_balance = 0.0
            if 'bankaccounts' in data:
                for account in data['bankaccounts']:
                    total_balance += float(account.get('balance', 0.0))
            return total_balance
        elif response.status_code == 429:
            raise Exception("Rate limit exceeded - too many requests")
        else:
            st.warning("Could not fetch bank balance, using default")
            return 100000.0

    return rate_limited_api_call(_fetch_balance)

# =================== Process AP Aging Data ===================
def process_ap_aging_data(bills_data, selected_from_date, selected_to_date):
    """Process bills data into aging buckets with date filtering."""
    vendors_forecast = []
    
    if 'bills' not in bills_data or not bills_data['bills']:
        st.warning("No bills found in response")
        return pd.DataFrame()
    
    # Group by vendor and calculate aging
    vendor_aging = {}
    today = datetime.now().date()
    
    processed_count = 0
    filtered_count = 0
    
    for bill in bills_data['bills']:
        vendor_name = bill.get('vendor_name', 'Unknown Vendor')
        bill_number = bill.get('bill_number', 'N/A')
        due_date_str = bill.get('due_date', '')
        bill_date_str = bill.get('date', '')
        bill_status = bill.get('status', 'unknown')
        
        # Apply date filtering
        bill_date = None
        if bill_date_str:
            try:
                bill_date = datetime.strptime(bill_date_str, '%Y-%m-%d').date()
                if selected_from_date and bill_date < selected_from_date:
                    filtered_count += 1
                    continue
                if selected_to_date and bill_date > selected_to_date:
                    filtered_count += 1
                    continue
            except ValueError:
                pass
        
        # Get the outstanding balance
        balance = 0.0
        currency_code = bill.get('currency_code', 'AED')
        
        if bill.get('balance'):
            balance = float(bill.get('balance', 0.0))
        elif bill.get('total'):
            balance = float(bill.get('total', 0.0))
        elif bill.get('amount_due'):
            balance = float(bill.get('amount_due', 0.0))
        
        # Convert USD to AED if needed
        if currency_code == "USD":
            exchange_rate = 3.6725  # USD to AED conversion
            balance = balance * exchange_rate
        
        if balance <= 0:
            continue  # Skip paid or zero balance bills
        
        processed_count += 1
        
        # Initialize vendor if not exists
        if vendor_name not in vendor_aging:
            vendor_aging[vendor_name] = {
                'Current (Due Now)': 0.0,
                '1-15 Days': 0.0,
                '16-30 Days': 0.0,
                '31-45 Days': 0.0,
                '45+ Days': 0.0,
                'Total Amount': 0.0
            }
        
        # Calculate aging based on due date
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
                days_overdue = (today - due_date).days
                
                # Categorize based on how overdue the bill is
                if days_overdue <= 0:
                    vendor_aging[vendor_name]['Current (Due Now)'] += balance
                elif days_overdue <= 15:
                    vendor_aging[vendor_name]['1-15 Days'] += balance
                elif days_overdue <= 30:
                    vendor_aging[vendor_name]['16-30 Days'] += balance
                elif days_overdue <= 45:
                    vendor_aging[vendor_name]['31-45 Days'] += balance
                else:
                    vendor_aging[vendor_name]['45+ Days'] += balance
                    
            except ValueError:
                # If due date parsing fails, assume it's current
                vendor_aging[vendor_name]['Current (Due Now)'] += balance
        else:
            # No due date, treat as current
            vendor_aging[vendor_name]['Current (Due Now)'] += balance
        
        vendor_aging[vendor_name]['Total Amount'] += balance
    
    # Convert to DataFrame
    for vendor_name, aging_data in vendor_aging.items():
        if aging_data['Total Amount'] > 0:
            vendors_forecast.append({
                'Vendor': vendor_name,
                **aging_data
            })
    
    # Show processing summary
    if filtered_count > 0:
        st.info(f"Processed {processed_count} bills, filtered out {filtered_count} bills outside date range")
    else:
        st.success(f"Processed {processed_count} bills for aging analysis")
    
    return pd.DataFrame(vendors_forecast)

# =================== Create Payment Schedule ===================
def create_payment_schedule(vendors_df, forecast_days=60):
    """Create a payment schedule based on aging periods."""
    
    if vendors_df.empty:
        return pd.DataFrame()
    
    payment_schedule = []
    today = datetime.now().date()
    
    for _, vendor in vendors_df.iterrows():
        vendor_name = vendor['Vendor']
        
        # Schedule payments based on aging buckets
        payments = [
            (today, vendor['Current (Due Now)'], 'Overdue/Current'),
            (today + timedelta(days=7), vendor['1-15 Days'], '1-15 Days'),
            (today + timedelta(days=23), vendor['16-30 Days'], '16-30 Days'),
            (today + timedelta(days=38), vendor['31-45 Days'], '31-45 Days'),
            (today + timedelta(days=60), vendor['45+ Days'], '45+ Days')
        ]
        
        for payment_date, amount, period in payments:
            if amount > 0 and payment_date <= today + timedelta(days=forecast_days):
                payment_schedule.append({
                    'Date': payment_date,
                    'Vendor': vendor_name,
                    'Amount': amount,
                    'Period': period,
                    'Days from Today': (payment_date - today).days
                })
    
    return pd.DataFrame(payment_schedule).sort_values('Date')

# =================== Create Cash Flow Forecast ===================
def create_cash_flow_forecast(payment_schedule_df, starting_balance, forecast_days=60):
    """Create cash flow forecast based on payment schedule."""
    
    if payment_schedule_df.empty:
        return pd.DataFrame()
    
    # Create daily forecast
    today = datetime.now().date()
    forecast_dates = [today + timedelta(days=i) for i in range(forecast_days + 1)]
    
    forecast_data = []
    running_balance = starting_balance
    
    for forecast_date in forecast_dates:
        # Find payments due on this date
        daily_payments = payment_schedule_df[payment_schedule_df['Date'] == forecast_date]
        daily_outflow = daily_payments['Amount'].sum() if not daily_payments.empty else 0.0
        
        # For this simplified version, assume no inflows
        daily_inflow = 0.0
        
        net_flow = daily_inflow - daily_outflow
        running_balance += net_flow
        
        forecast_data.append({
            'Date': forecast_date,
            'Daily Outflow': daily_outflow,
            'Daily Inflow': daily_inflow,
            'Net Flow': net_flow,
            'Running Balance': running_balance,
            'Days from Today': (forecast_date - today).days
        })
    
    return pd.DataFrame(forecast_data)

# =================== Display Functions ===================
def display_ap_summary(vendors_df):
    """Display AP summary metrics."""
    if vendors_df.empty:
        st.warning("No accounts payable data available")
        return
    
    total_ap = vendors_df['Total Amount'].sum()
    current_due = vendors_df['Current (Due Now)'].sum()
    due_30_days = vendors_df['1-15 Days'].sum() + vendors_df['16-30 Days'].sum()
    due_45_days = vendors_df['31-45 Days'].sum()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total AP", f"AED {total_ap:,.2f}")
    with col2:
        st.metric("Due Now", f"AED {current_due:,.2f}")
    with col3:
        st.metric("Due in 30 Days", f"AED {due_30_days:,.2f}")
    with col4:
        st.metric("Due in 31-45 Days", f"AED {due_45_days:,.2f}")

def display_payment_forecast_chart(forecast_df):
    """Display payment forecast chart."""
    if forecast_df.empty:
        st.warning("No forecast data to display")
        return
    
    fig = go.Figure()
    
    # Add running balance line
    fig.add_trace(go.Scatter(
        x=forecast_df['Date'],
        y=forecast_df['Running Balance'],
        mode='lines+markers',
        name='Projected Cash Balance',
        line=dict(color='blue', width=3)
    ))
    
    # Add daily outflows as red bars
    fig.add_trace(go.Bar(
        x=forecast_df['Date'],
        y=-forecast_df['Daily Outflow'],  # Negative to show as outflow
        name='Daily Payments',
        marker_color='red',
        opacity=0.6
    ))
    
    # Add zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    
    fig.update_layout(
        title='Cash Flow Forecast - Accounts Payable Impact',
        xaxis_title='Date',
        yaxis_title='Amount (AED)',
        hovermode='x unified'
    )
    
    st.plotly_chart(fig, use_container_width=True)

def display_aging_analysis(vendors_df):
    """Display aging analysis charts."""
    if vendors_df.empty:
        return
    
    # Create aging summary
    aging_summary = {
        'Current': vendors_df['Current (Due Now)'].sum(),
        '1-15 Days': vendors_df['1-15 Days'].sum(),
        '16-30 Days': vendors_df['16-30 Days'].sum(),
        '31-45 Days': vendors_df['31-45 Days'].sum(),
        '45+ Days': vendors_df['45+ Days'].sum()
    }
    
    aging_df = pd.DataFrame(list(aging_summary.items()), columns=['Period', 'Amount'])
    aging_df = aging_df[aging_df['Amount'] > 0]  # Only show non-zero amounts
    
    if not aging_df.empty:
        fig = px.pie(aging_df, values='Amount', names='Period', 
                    title='Accounts Payable by Aging Period')
        st.plotly_chart(fig, use_container_width=True)

# =================== Main Dashboard ===================
def main():
    st.set_page_config(page_title="AP & Cash Flow Forecast", layout="wide")
    st.title("Accounts Payable & Cash Flow Forecast")
    
    # Date range and forecast period selectors
    col1, col2, col3 = st.columns(3)
    
    with col1:
        from_date = st.date_input(
            "From Date", 
            value=datetime(2025, 1, 1),
            help="Filter bills from this date"
        )
    
    with col2:
        to_date = st.date_input(
            "To Date", 
            value=datetime.now(),
            help="Filter bills up to this date"
        )
    
    with col3:
        forecast_days = st.selectbox("Forecast Period", [30, 45, 60, 90], index=2)
    
    # Validate date range
    if from_date > to_date:
        st.error("From Date must be before To Date")
        return
    
    try:
        with st.spinner("Loading accounts payable data..."):
            # Fetch bills data with date filtering
            bills_data = get_bills_detail(from_date, to_date)
            
            # Fetch bank balance
            bank_balance = get_bank_balance()
        
        # Debug: Show raw data structure
        with st.expander("Debug: Raw Bills Data"):
            if bills_data and 'bills' in bills_data:
                st.write(f"Found {len(bills_data['bills'])} bills in date range")
                if bills_data['bills']:
                    st.write("Sample bill structure:")
                    st.json(bills_data['bills'][0])
            else:
                st.write("No bills data found")
                st.json(bills_data)
        
        # Process bills into aging analysis with date filtering
        vendors_df = process_ap_aging_data(bills_data, from_date, to_date)
        detailed_schedule = create_payment_schedule(vendors_df, forecast_days)
        
        if vendors_df.empty:
            st.warning("No unpaid bills found in the selected date range")
            st.info("This could mean:")
            st.write("• All bills in this period are already paid")
            st.write("• No bills were created in this date range")
            st.write("• Try expanding the date range")
            return
        
        # Display summary with date range info
        st.subheader(f"Accounts Payable Summary ({from_date} to {to_date})")
        display_ap_summary(vendors_df)
        
        # Create cash flow forecast using detailed schedule
        forecast_df = create_cash_flow_forecast(detailed_schedule, bank_balance, forecast_days)
        
        # Display forecast
        st.subheader(f"Cash Flow Forecast - Next {forecast_days} Days")
        if not forecast_df.empty:
            display_payment_forecast_chart(forecast_df)
        else:
            st.info("No payment forecast available - no bills due in forecast period")
        
        # Critical insights
        if not forecast_df.empty:
            min_balance = forecast_df['Running Balance'].min()
            min_date = forecast_df.loc[forecast_df['Running Balance'].idxmin(), 'Date']
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Current Bank Balance", f"AED {bank_balance:,.2f}")
            with col2:
                st.metric("Lowest Projected Balance", f"AED {min_balance:,.2f}")
            with col3:
                st.metric("Date of Lowest Balance", str(min_date))
            
            if min_balance < 0:
                st.error(f"WARNING: Cash shortage projected on {min_date}")
            elif min_balance < 50000:
                st.warning("CAUTION: Low cash balance projected")
            else:
                st.success("Healthy cash flow projected")
        
        # Detailed tables
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Detailed Payment Schedule")
            if not detailed_schedule.empty:
                upcoming_payments = detailed_schedule[detailed_schedule['Days from Today'] <= 45]
                st.dataframe(upcoming_payments.style.format({'Amount': 'AED {:,.2f}'}), 
                           use_container_width=True)
                
                # Export option
                csv = upcoming_payments.to_csv(index=False)
                st.download_button(
                    label="Download Payment Schedule",
                    data=csv,
                    file_name=f"payment_schedule_{from_date}_to_{to_date}_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
            else:
                st.info("No detailed payment schedule available")
        
        with col2:
            st.subheader("Aging Analysis by Vendor")
            if not vendors_df.empty:
                display_aging_analysis(vendors_df)
                
                # Vendor details table
                st.subheader("Vendor Summary")
                formatted_vendors = vendors_df.style.format({
                    'Current (Due Now)': 'AED {:,.2f}',
                    '1-15 Days': 'AED {:,.2f}',
                    '16-30 Days': 'AED {:,.2f}',
                    '31-45 Days': 'AED {:,.2f}',
                    '45+ Days': 'AED {:,.2f}',
                    'Total Amount': 'AED {:,.2f}'
                })
                st.dataframe(formatted_vendors, use_container_width=True)
        
        # Action items and recommendations
        st.subheader("Recommended Actions")
        
        if not vendors_df.empty:
            overdue_amount = vendors_df['Current (Due Now)'].sum()
            due_soon = vendors_df['1-15 Days'].sum()
            
            action_items = []
            
            if overdue_amount > 0:
                overdue_count = len(vendors_df[vendors_df['Current (Due Now)'] > 0])
                action_items.append(f"URGENT: AED {overdue_amount:,.2f} overdue across {overdue_count} vendors")
            
            if due_soon > 0:
                due_soon_count = len(vendors_df[vendors_df['1-15 Days'] > 0])
                action_items.append(f"UPCOMING: AED {due_soon:,.2f} due in next 15 days from {due_soon_count} vendors")
            
            if not forecast_df.empty:
                negative_days = forecast_df[forecast_df['Running Balance'] < 0]
                if not negative_days.empty:
                    first_negative = negative_days.iloc[0]['Date']
                    action_items.append(f"CASH SHORTAGE: Projected to occur on {first_negative}")
            
            if action_items:
                for item in action_items:
                    if "URGENT" in item:
                        st.error(item)
                    elif "CASH SHORTAGE" in item:
                        st.error(item)
                    else:
                        st.warning(item)
            else:
                st.success("No immediate payment actions required")
        
    except Exception as e:
        st.error(f"Error loading AP data: {str(e)}")
        
        # Show specific guidance for rate limiting
        if "429" in str(e) or "rate limit" in str(e).lower():
            st.error("RATE LIMIT EXCEEDED: You've made too many requests too quickly.")
            st.info("Solutions:")
            st.write("1. Wait 5-10 minutes before refreshing")
            st.write("2. Use date filters to reduce data volume") 
            st.write("3. Avoid rapid refreshes of the page")
            st.write("4. Consider upgrading your Zoho Books API plan for higher limits")
        else:
            with st.expander("Troubleshooting Guide"):
                st.write("**Common solutions:**")
                st.write("1. **Rate Limiting**: Wait a few minutes between requests")
                st.write("2. **Check API credentials**: Ensure all tokens are valid")
                st.write("3. **Verify organization ID**: Confirm '890601593' is correct")
                st.write("4. **Date range**: Try smaller date ranges to reduce load")
                st.write("5. **Network issues**: Check internet connection")

if __name__ == "__main__":
    main()