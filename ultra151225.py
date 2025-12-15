import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

BASE_URL = "https://www.zohoapis.com/books/v3"
RATE_LIMIT_DELAY = 2.0
CACHE_TTL_SECONDS = 3600


# -----------------------------
# AUTH & LOW-LEVEL API HELPERS
# -----------------------------
def load_zoho_settings() -> Dict[str, str]:
    # 👉 Put your real values in secrets.toml:
    # [zoho]
    # client_id = "..."
    # client_secret = "..."
    # refresh_token = "..."
    # organization_id = "..."
    # or temporarily fill the fallback dict below.
    fallback = {
        "client_id": "1000.YX3UM2TC6CMW4805WK1SYI0M94ALGA",
        "client_secret": "32f9dd97942e6a631db4f7f2f08d6ee72c1adf4bfe",
        "refresh_token": "1000.f260cfffbba2725db26245994715639f.a2cc654ced2e5f5db549d7b996a0001d",
        "organization_id": "766216447",
    }

    try:
        secrets_block = st.secrets.get("zoho", {})
    except Exception:
        secrets_block = {}

    cfg = {
        "client_id": secrets_block.get("client_id") or fallback["client_id"],
        "client_secret": secrets_block.get("client_secret") or fallback["client_secret"],
        "refresh_token": secrets_block.get("refresh_token") or fallback["refresh_token"],
        "organization_id": secrets_block.get("organization_id") or fallback["organization_id"],
    }
    if not all(cfg.values()):
        raise RuntimeError(
            "Add Zoho credentials to .streamlit/secrets.toml "
            "(client_id, client_secret, refresh_token, organization_id)."
        )
    return cfg


def _get_access_token(cfg: Dict[str, str]) -> str:
    token = st.session_state.get("access_token")
    expiry = st.session_state.get("token_expires")
    if token and expiry and datetime.now() < expiry:
        return token

    resp = requests.post(
        "https://accounts.zoho.com/oauth/v2/token",
        params={
            "refresh_token": cfg["refresh_token"],
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload["access_token"]
    st.session_state["access_token"] = token
    st.session_state["token_expires"] = datetime.now() + timedelta(seconds=int(payload.get("expires_in", 3600)))
    return token


def _rate_limited_call(func, *args, **kwargs):
    last = st.session_state.get("last_call")
    if last:
        elapsed = (datetime.now() - last).total_seconds()
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
    result = func(*args, **kwargs)
    st.session_state["last_call"] = datetime.now()
    return result


def zoho_get(cfg: Dict[str, str], endpoint: str, params: Dict[str, str] | None = None) -> Dict:
    token = _get_access_token(cfg)
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    params = params.copy() if params else {}
    params["organization_id"] = cfg["organization_id"]
    resp = requests.get(f"{BASE_URL}/{endpoint}", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_api(cfg: Dict[str, str], endpoint: str, params: Dict[str, str] | None = None) -> Dict:
    params = params.copy() if params else {}
    params = {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in params.items()}
    cache_key = (endpoint, tuple(sorted(params.items())))
    cache = st.session_state.setdefault("api_cache", {})
    cached = cache.get(cache_key)
    if cached and datetime.now() - cached["timestamp"] < timedelta(seconds=CACHE_TTL_SECONDS):
        return cached["data"]
    data = _rate_limited_call(zoho_get, cfg, endpoint, params)
    cache[cache_key] = {"timestamp": datetime.now(), "data": data}
    return data


def _format_http_error(error: requests.HTTPError) -> str:
    response = error.response
    if response is None:
        return str(error)
    detail = ""
    try:
        payload = response.json()
        detail = payload.get("message") or payload.get("error") or payload.get("code") or ""
    except ValueError:
        detail = response.text
    status = f"{response.status_code}"
    return f"{status} {detail}".strip()


def safe_fetch_api(
    cfg: Dict[str, str],
    endpoint: str,
    params: Dict[str, str] | None,
    label: str,
    *,
    required: bool = False,
) -> Dict:
    try:
        return fetch_api(cfg, endpoint, params)
    except requests.HTTPError as err:
        st.warning(f"{label} unavailable ({endpoint}): {_format_http_error(err)}")
        if required:
            st.stop()
        return {}
    except Exception as exc:
        st.warning(f"{label} unavailable ({endpoint}): {exc}")
        if required:
            st.stop()
        return {}


# -----------------------------
# GENERIC HELPERS
# -----------------------------
def to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_date(value) -> date | None:
    if not value:
        return None
    value = str(value)
    if "T" in value:
        value = value.split("T", 1)[0]
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def filter_by_date(records: List[Dict], date_fields: List[str] | str, start_date: date, end_date: date) -> List[Dict]:
    if isinstance(date_fields, str):
        date_fields = [date_fields]
    results = []
    for rec in records:
        rec_date = None
        for field in date_fields:
            rec_date = _coerce_date(rec.get(field) or rec.get("date"))
            if rec_date:
                break
        if not rec_date:
            continue
        if start_date <= rec_date <= end_date:
            results.append(rec)
    return results


def sum_amount(records: List[Dict], amount_field: str, date_fields: List[str] | str, start_date: date, end_date: date) -> float:
    filtered = filter_by_date(records, date_fields, start_date, end_date)
    return sum(to_float(r.get(amount_field) or r.get("amount") or r.get("total")) for r in filtered)


# -----------------------------
# PARSERS FOR REPORTS
# -----------------------------
def parse_profit_and_loss(report: Dict) -> Dict[str, float]:
    metrics = {
        "revenue": 0.0,
        "cogs": 0.0,
        "gross_profit": 0.0,
        "operating_expenses": 0.0,
        "operating_income": 0.0,
        "net_profit": 0.0,
    }

    def traverse(nodes: List[Dict]):
        for node in nodes:
            name = (node.get("name") or node.get("label") or "").lower()
            total = to_float(node.get("total") or node.get("amount"))
            if "total income" in name or "sales" in name or "operating income" in name:
                metrics["revenue"] = max(metrics["revenue"], total)
            if "cost of goods" in name or "cogs" in name:
                metrics["cogs"] = max(metrics["cogs"], total)
            if "gross profit" in name:
                metrics["gross_profit"] = max(metrics["gross_profit"], total)
            if "operating expense" in name:
                metrics["operating_expenses"] = max(metrics["operating_expenses"], total)
            if "operating profit" in name or "ebit" in name:
                metrics["operating_income"] = max(metrics["operating_income"], total)
            if "net" in name and ("profit" in name or "income" in name or "profit/loss" in name):
                metrics["net_profit"] = max(metrics["net_profit"], total)
            children = node.get("account_transactions") or node.get("sub_rows") or []
            if children:
                traverse(children)

    traverse(report.get("profit_and_loss", []))

    if not metrics["gross_profit"]:
        metrics["gross_profit"] = metrics["revenue"] - metrics["cogs"]

    return metrics


def parse_balance_sheet(report: Dict) -> Dict[str, float]:
    totals = {"cash": 0.0, "ar": 0.0, "ap": 0.0, "current_assets": 0.0, "current_liabilities": 0.0}

    def traverse(nodes: List[Dict], section: str):
        for node in nodes:
            name = (node.get("name") or "").lower()
            total = to_float(node.get("total") or node.get("amount"))
            if section == "assets":
                if "cash" in name or "bank" in name:
                    totals["cash"] += total
                if "accounts receivable" in name or "debtors" in name:
                    totals["ar"] += total
                if "current assets" == name:
                    totals["current_assets"] = total
            elif section == "liabilities":
                if "payable" in name:
                    totals["ap"] += abs(total)
                if "current liabilities" == name:
                    totals["current_liabilities"] = abs(total)
            children = node.get("account_transactions") or []
            if children:
                traverse(children, section)

    for group in report.get("balance_sheet", []):
        name = (group.get("name") or "").lower()
        if "asset" in name:
            traverse(group.get("account_transactions", []), "assets")
        elif "liabilit" in name:
            traverse(group.get("account_transactions", []), "liabilities")

    totals["working_capital"] = totals["current_assets"] - totals["current_liabilities"]
    totals["current_ratio"] = (
        totals["current_assets"] / totals["current_liabilities"] if totals["current_liabilities"] else 0.0
    )
    return totals


# -----------------------------
# AGING & OUTSTANDING HELPERS
# -----------------------------
def calculate_outstanding_invoices(invoices: List[Dict]) -> Dict[str, float]:
    today = datetime.now().date()
    total_outstanding = 0.0
    overdue = 0.0
    for inv in invoices:
        amount_due = to_float(inv.get("total")) - to_float(inv.get("amount_paid"))
        if amount_due <= 0:
            continue
        total_outstanding += amount_due
        due_date = _coerce_date(inv.get("due_date") or inv.get("date"))
        if due_date and due_date < today:
            overdue += amount_due
    return {"total": total_outstanding, "overdue": overdue}


def calculate_outstanding_bills(bills: List[Dict]) -> Dict[str, float]:
    today = datetime.now().date()
    total_outstanding = 0.0
    overdue = 0.0
    for bill in bills:
        amount_due = to_float(bill.get("total")) - to_float(bill.get("amount_paid"))
        if amount_due <= 0:
            continue
        total_outstanding += amount_due
        due_date = _coerce_date(bill.get("due_date") or bill.get("date"))
        if due_date and due_date < today:
            overdue += amount_due
    return {"total": total_outstanding, "overdue": overdue}


def aging_from_invoices(invoices: List[Dict]) -> Tuple[pd.DataFrame, Dict[str, float]]:
    buckets = {"0-30": 0.0, "30-60": 0.0, "60-90": 0.0, "90+": 0.0}
    rows = []
    today = datetime.now().date()
    for inv in invoices:
        due_date = _coerce_date(inv.get("due_date") or inv.get("date"))
        if not due_date:
            continue
        amount_due = to_float(inv.get("total")) - to_float(inv.get("amount_paid"))
        if amount_due <= 0:
            continue
        days = max((today - due_date).days, 0)
        if days <= 30:
            bucket = "0-30"
        elif days <= 60:
            bucket = "30-60"
        elif days <= 90:
            bucket = "60-90"
        else:
            bucket = "90+"
        buckets[bucket] += amount_due
        rows.append({"Customer": inv.get("customer_name"), "Amount": amount_due, "Bucket": bucket})
    return pd.DataFrame(rows), buckets


def aging_from_bills(bills: List[Dict]) -> Tuple[pd.DataFrame, Dict[str, float]]:
    buckets = {"0-30": 0.0, "30-60": 0.0, "60-90": 0.0, "90+": 0.0}
    rows = []
    today = datetime.now().date()
    for bill in bills:
        due_date = _coerce_date(bill.get("due_date") or bill.get("date"))
        if not due_date:
            continue
        amount_due = to_float(bill.get("total")) - to_float(bill.get("amount_paid"))
        if amount_due <= 0:
            continue
        days = max((today - due_date).days, 0)
        if days <= 30:
            bucket = "0-30"
        elif days <= 60:
            bucket = "30-60"
        elif days <= 90:
            bucket = "60-90"
        else:
            bucket = "90+"
        buckets[bucket] += amount_due
        rows.append({"Vendor": bill.get("vendor_name"), "Amount": amount_due, "Bucket": bucket})
    return pd.DataFrame(rows), buckets


# -----------------------------
# CASHFLOW & LIQUIDITY ENGINE
# -----------------------------
def calculate_cashflow_engine(
    customer_payments: List[Dict],
    vendor_payments: List[Dict],
    expenses: List[Dict],
    bank_transactions: List[Dict],
    start_date: date,
    end_date: date,
) -> Dict[str, float]:
    def filter_txns(keywords: List[str]):
        subset = []
        for txn in bank_transactions:
            txn_type = (txn.get("transaction_type") or "").lower()
            if any(keyword in txn_type for keyword in keywords):
                subset.append(txn)
        return subset

    operating_inflow = sum_amount(customer_payments, "amount", ["payment_date", "date"], start_date, end_date)
    refunds = sum_amount(filter_txns(["refund"]), "amount", "date", start_date, end_date)
    other_income = sum_amount(filter_txns(["deposit", "interest", "other_income"]), "amount", "date", start_date, end_date)
    operating_inflow_total = operating_inflow + refunds + other_income

    vendor_out = sum_amount(vendor_payments, "amount", ["payment_date", "date"], start_date, end_date)
    expense_out = sum_amount(expenses, "amount", ["date", "expense_date"], start_date, end_date)
    bank_charge_out = sum_amount(filter_txns(["bank_charge", "fee"]), "amount", "date", start_date, end_date)
    operating_outflow_total = vendor_out + expense_out + bank_charge_out

    investing = sum_amount(filter_txns(["asset", "capital"]), "amount", "date", start_date, end_date)
    financing_in = sum_amount(filter_txns(["owner", "loan", "equity", "investment"]), "amount", "date", start_date, end_date)
    financing_out = sum_amount(filter_txns(["withdrawal", "dividend", "repayment"]), "amount", "date", start_date, end_date)
    financing = financing_in - financing_out

    operating = operating_inflow_total - operating_outflow_total
    net_change = operating + investing + financing
    return {
        "operating_inflow": operating_inflow_total,
        "operating_outflow": operating_outflow_total,
        "operating": operating,
        "investing": investing,
        "financing": financing,
        "net_change": net_change,
        "customer_collections": operating_inflow,
        "vendor_payments": vendor_out,
        "expense_cash": expense_out,
    }


def calculate_burn_and_runway(
    cash_on_hand: float,
    operating_inflow: float,
    operating_outflow: float,
    start_date: date,
    end_date: date,
) -> Dict[str, float]:
    net_burn = max(operating_outflow - operating_inflow, 0.0)
    period_days = max((end_date - start_date).days, 1)
    daily_burn = net_burn / period_days if period_days else 0.0
    monthly_burn = daily_burn * 30
    runway_months = cash_on_hand / monthly_burn if monthly_burn else 0.0
    return {"burn_rate": monthly_burn, "cash_runway_months": runway_months}


def aggregate_bank_accounts(bank_accounts: List[Dict]) -> pd.DataFrame:
    rows = [{"Account": acc.get("account_name"), "Balance": to_float(acc.get("balance"))} for acc in bank_accounts]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Balance", ascending=False)
    return df


def summarize_bank_transactions(bank_transactions: List[Dict], start_date: date, end_date: date) -> Dict[str, float]:
    inflow_keywords = ["deposit", "refund", "interest", "owner", "loan", "capital", "receive"]
    outflow_keywords = ["payment", "charge", "fee", "withdrawal", "transfer", "payout"]

    inflow = 0.0
    outflow = 0.0
    for txn in filter_by_date(bank_transactions, "date", start_date, end_date):
        amount = to_float(txn.get("amount"))
        txn_type = (txn.get("transaction_type") or "").lower()
        is_credit = txn.get("is_credit")
        if any(keyword in txn_type for keyword in inflow_keywords) or is_credit:
            inflow += amount
        elif any(keyword in txn_type for keyword in outflow_keywords):
            outflow += amount
        else:
            if amount >= 0:
                inflow += amount
            else:
                outflow += abs(amount)
    return {"inflow": inflow, "outflow": outflow, "net": inflow - outflow}


# -----------------------------
# CUSTOMER & VENDOR INSIGHTS
# -----------------------------
def top_n_dataframe(records: Dict[str, float], column_label: str) -> pd.DataFrame:
    df = pd.DataFrame([{"Name": k, column_label: v} for k, v in records.items()])
    if not df.empty:
        df = df.sort_values(column_label, ascending=False).head(10)
    return df


def aggregate_vendor_spend(bills: List[Dict], expenses: List[Dict], start_date: date, end_date: date) -> Dict[str, float]:
    totals: Dict[str, float] = {}
    for bill in filter_by_date(bills, ["date", "bill_date"], start_date, end_date):
        vendor = bill.get("vendor_name") or "Unknown Vendor"
        totals[vendor] = totals.get(vendor, 0.0) + to_float(bill.get("total"))
    for exp in filter_by_date(expenses, ["date", "expense_date"], start_date, end_date):
        vendor = exp.get("vendor_name") or exp.get("payee_name") or exp.get("account_name") or "Expenses"
        totals[vendor] = totals.get(vendor, 0.0) + to_float(exp.get("amount") or exp.get("total"))
    return totals


def calculate_customer_overdue_details(invoices: List[Dict]) -> pd.DataFrame:
    rows = []
    today = datetime.now().date()
    for inv in invoices:
        outstanding = to_float(inv.get("total")) - to_float(inv.get("amount_paid"))
        if outstanding <= 0:
            continue
        due_date = _coerce_date(inv.get("due_date") or inv.get("date"))
        if due_date and due_date < today:
            days_overdue = (today - due_date).days
            rows.append(
                {
                    "Customer": inv.get("customer_name"),
                    "Invoice": inv.get("invoice_number"),
                    "Amount": outstanding,
                    "Days Overdue": days_overdue,
                }
            )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Days Overdue", "Amount"], ascending=False).head(10)
    return df


def summarize_contacts(contacts: List[Dict]) -> Dict[str, int]:
    total = len(contacts)
    active = sum(1 for c in contacts if (c.get("status") or "").lower() == "active")
    return {"total": total, "active": active}


def calculate_customer_insights(customers: List[Dict], invoices: List[Dict], start_date: date, end_date: date) -> Dict[str, float]:
    stats = summarize_contacts(customers)
    revenue_period = sum_amount(invoices, "total", "date", start_date, end_date)
    outstanding = calculate_outstanding_invoices(invoices)
    overdue_customers = len(
        {
            inv.get("customer_id")
            for inv in invoices
            if _coerce_date(inv.get("due_date") or inv.get("date"))
            and _coerce_date(inv.get("due_date") or inv.get("date")) < datetime.now().date()
            and (to_float(inv.get("total")) - to_float(inv.get("amount_paid"))) > 0
        }
    )
    avg_invoice = 0.0
    filtered = filter_by_date(invoices, "date", start_date, end_date)
    if filtered:
        avg_invoice = revenue_period / len(filtered)
    return {
        "total_customers": stats["total"],
        "active_customers": stats["active"],
        "revenue_period": revenue_period,
        "outstanding": outstanding["total"],
        "overdue_customers": overdue_customers,
        "avg_invoice": avg_invoice,
    }


def calculate_vendor_insights(vendors: List[Dict], bills: List[Dict], expenses: List[Dict], start_date: date, end_date: date) -> Dict[str, float]:
    stats = summarize_contacts(vendors)
    ap_out = calculate_outstanding_bills(bills)
    spend_period = sum_amount(bills, "total", "date", start_date, end_date) + sum_amount(
        expenses, "amount", ["date", "expense_date"], start_date, end_date
    )
    return {
        "total_vendors": stats["total"],
        "active_vendors": stats["active"],
        "ap_outstanding": ap_out["total"],
        "ap_overdue": ap_out["overdue"],
        "spend_period": spend_period,
    }


def summarize_orders(records: List[Dict], amount_field: str) -> Dict[str, float]:
    summary = {"open_count": 0, "open_amount": 0.0, "total_amount": 0.0, "count": len(records)}
    open_statuses = {"draft", "submitted", "open", "pending", "approved"}
    for rec in records:
        amount = to_float(rec.get(amount_field) or rec.get("total"))
        summary["total_amount"] += amount
        status = (rec.get("status") or "").lower()
        if status in open_statuses:
            summary["open_count"] += 1
            summary["open_amount"] += amount
    return summary


# -----------------------------
# MAIN STREAMLIT APP
# -----------------------------
def main():
    st.set_page_config(page_title="Ultraleap FZC – Financial Dashboard", page_icon="📊", layout="wide")
    st.title("📊 Ultraleap FZC – Financial Dashboard")
    st.caption("Reports powered by Zoho Books core APIs + Profit & Loss / Balance Sheet reports.")

    cfg = load_zoho_settings()
    st.session_state.setdefault("reports_loaded_key_v2", None)

    col_left, col_right = st.columns([2, 1])
    period_choice = col_left.selectbox("Period", ["Year to Date", "Quarter to Date", "Month to Date", "Custom Range"])
    run_pressed = col_right.button("▶ Run Dashboard", type="primary")

    today = datetime.today().date()
    if period_choice == "Year to Date":
        start_date = today.replace(month=1, day=1)
        end_date = today
    elif period_choice == "Quarter to Date":
        quarter = (today.month - 1) // 3 + 1
        start_date = date(today.year, 3 * (quarter - 1) + 1, 1)
        end_date = today
    elif period_choice == "Month to Date":
        start_date = today.replace(day=1)
        end_date = today
    else:
        custom = st.date_input("Custom range", value=[today.replace(day=1), today])
        if len(custom) != 2:
            st.warning("Select a valid date range.")
            st.stop()
        start_date, end_date = custom

    st.caption(f"Period: {start_date} → {end_date}")
    range_key = f"{start_date.isoformat()}_{end_date.isoformat()}"
    if not run_pressed and st.session_state.get("reports_loaded_key_v2") != range_key:
        st.info("Select a period and click ▶ Run Dashboard to fetch data.")
        st.stop()
    if run_pressed:
        st.session_state.pop("api_cache", None)

    with st.spinner("Fetching Zoho data..."):
        pl_report = safe_fetch_api(
            cfg,
            "reports/profitandloss",
            {"from_date": start_date, "to_date": end_date, "cash_based": "false"},
            "Profit & Loss",
            required=True,
        )
        balance_report = safe_fetch_api(
            cfg,
            "reports/balancesheet",
            {"to_date": end_date, "show_rows": "non_zero"},
            "Balance Sheet",
            required=True,
        )
        invoices_data = safe_fetch_api(cfg, "invoices", {"per_page": 200}, "Invoices")
        bills_data = safe_fetch_api(cfg, "bills", {"per_page": 200}, "Bills")
        expenses_data = safe_fetch_api(
            cfg,
            "expenses",
            {"from_date": start_date, "to_date": end_date, "per_page": 200},
            "Expenses",
        )
        customer_payments_data = safe_fetch_api(cfg, "customerpayments", {"per_page": 200}, "Customer Payments")
        vendor_payments_data = safe_fetch_api(cfg, "vendorpayments", {"per_page": 200}, "Vendor Payments")
        try:
            credit_notes_data = fetch_api(cfg, "creditnotes", {"per_page": 200})
        except Exception:
            credit_notes_data = {}
        try:
            bank_accounts_data = fetch_api(cfg, "bankaccounts", {})
        except Exception:
            bank_accounts_data = {}
        bank_transactions_data = safe_fetch_api(
            cfg,
            "banktransactions",
            {"from_date": start_date, "to_date": end_date, "per_page": 200},
            "Bank Transactions",
        )
        customers_data = safe_fetch_api(
            cfg,
            "contacts",
            {"contact_type": "customer", "per_page": 200},
            "Customers",
        )
        vendors_data = safe_fetch_api(
            cfg,
            "contacts",
            {"contact_type": "vendor", "per_page": 200},
            "Vendors",
        )
        purchase_orders_data = safe_fetch_api(cfg, "purchaseorders", {"per_page": 200}, "Purchase Orders")
        sales_orders_data = safe_fetch_api(cfg, "salesorders", {"per_page": 200}, "Sales Orders")

    st.session_state["reports_loaded_key_v2"] = range_key

    pl_metrics = parse_profit_and_loss(pl_report)
    balance_metrics = parse_balance_sheet(balance_report)

    invoices = (invoices_data or {}).get("invoices", [])
    bills = (bills_data or {}).get("bills", [])
    expenses = (expenses_data or {}).get("expenses", [])
    customer_payments = (customer_payments_data or {}).get("customerpayments", [])
    vendor_payments = (vendor_payments_data or {}).get("vendorpayments", [])
    credit_notes = (credit_notes_data or {}).get("creditnotes", [])
    bank_accounts = (bank_accounts_data or {}).get("bankaccounts", [])
    bank_transactions = (bank_transactions_data or {}).get("banktransactions", [])
    customers = (customers_data or {}).get("contacts", [])
    vendors = (vendors_data or {}).get("contacts", [])
    purchase_orders = (purchase_orders_data or {}).get("purchaseorders", [])
    sales_orders = (sales_orders_data or {}).get("salesorders", [])

    expense_totals: Dict[str, float] = {}
    for exp in expenses:
        category = exp.get("expense_account_name") or exp.get("account_name") or "Other"
        amount = to_float(exp.get("amount") or exp.get("total"))
        expense_totals[category] = expense_totals.get(category, 0.0) + amount
    if expense_totals:
        expense_df = pd.DataFrame([{"Category": k, "Amount": v} for k, v in expense_totals.items()]).sort_values(
            "Amount", ascending=False
        )
    else:
        expense_df = pd.DataFrame(columns=["Category", "Amount"])

    ar_df, ar_buckets = aging_from_invoices(invoices)
    ap_df, ap_buckets = aging_from_bills(bills)

    expense_period_total = float(expense_df["Amount"].sum())
    ar_overview = calculate_outstanding_invoices(invoices)
    ap_overview = calculate_outstanding_bills(bills)
    cash_on_hand = (
        sum(to_float(acc.get("balance")) for acc in bank_accounts)
        or balance_metrics["cash"]
    )
    ar_balance = balance_metrics["ar"]
    ap_balance = balance_metrics["ap"]

    cashflow_engine = calculate_cashflow_engine(
        customer_payments,
        vendor_payments,
        expenses,
        bank_transactions,
        start_date,
        end_date,
    )
    burn_stats = calculate_burn_and_runway(
        cash_on_hand,
        cashflow_engine["operating_inflow"],
        cashflow_engine["operating_outflow"],
        start_date,
        end_date,
    )
    bank_df = aggregate_bank_accounts(bank_accounts)
    bank_tx_summary = summarize_bank_transactions(bank_transactions, start_date, end_date)
    vendor_spend = aggregate_vendor_spend(bills, expenses, start_date, end_date)
    vendor_spend_df = top_n_dataframe(vendor_spend, "Spend")
    overdue_customers_df = calculate_customer_overdue_details(invoices)
    customer_insights = calculate_customer_insights(customers, invoices, start_date, end_date)
    vendor_insights = calculate_vendor_insights(vendors, bills, expenses, start_date, end_date)
    po_summary = summarize_orders(purchase_orders, "total")
    so_summary = summarize_orders(sales_orders, "total")

    period_days = max((end_date - start_date).days, 1)
    revenue = pl_metrics["revenue"]
    dso = (ar_balance / revenue * period_days) if revenue else 0.0
    dpo = (ap_balance / expense_period_total * period_days) if expense_period_total else 0.0
    profitability_index = (revenue / expense_period_total) if expense_period_total else 0.0
    credit_notes_total = sum_amount(credit_notes, "total", "date", start_date, end_date)

    # ---------------- EXECUTIVE KPIs ----------------
    st.subheader("Executive KPIs")
    col1, col2, col3 = st.columns(3)
    col1.metric("Revenue", f"AED {revenue:,.0f}")
    col2.metric("Net Profit", f"AED {pl_metrics['net_profit']:,.0f}")
    col3.metric("Operating Cash Flow", f"AED {cashflow_engine['operating']:,.0f}")

    col4, col5, col6 = st.columns(3)
    col4.metric("Cash", f"AED {balance_metrics['cash']:,.0f}")
    col5.metric("Working Capital", f"AED {balance_metrics['working_capital']:,.0f}")
    col6.metric("Operating Expenses", f"AED {pl_metrics['operating_expenses']:,.0f}")

    tab_exec, tab_profit, tab_cash, tab_collections, tab_operations, tab_bank, tab_relationships = st.tabs(
        [
            "Executive Summary",
            "Profitability",
            "Cash Flow",
            "Collections (AR)",
            "Operations (AP & Expenses)",
            "Bank & Liquidity",
            "Customer & Vendor Insights",
        ]
    )

    # ---------------- EXECUTIVE TAB ----------------
    with tab_exec:
        st.subheader("Key KPIs")
        row1 = st.columns(4)
        net_margin = (pl_metrics["net_profit"] / revenue * 100) if revenue else 0.0
        gross_margin = (pl_metrics["gross_profit"] / revenue * 100) if revenue else 0.0
        op_margin = (pl_metrics["operating_income"] / revenue * 100) if revenue else 0.0
        row1[0].metric("Revenue", f"AED {revenue:,.0f}")
        row1[1].metric("Net Profit", f"AED {pl_metrics['net_profit']:,.0f}", f"{net_margin:.1f}% margin")
        row1[2].metric("Gross Margin %", f"{gross_margin:.1f}%")
        row1[3].metric("Operating Margin %", f"{op_margin:.1f}%")

        row2 = st.columns(4)
        row2[0].metric("Cash on Hand", f"AED {cash_on_hand:,.0f}")
        row2[1].metric("Working Capital", f"AED {balance_metrics['working_capital']:,.0f}")
        row2[2].metric("Current Ratio", f"{balance_metrics['current_ratio']:.2f}")
        row2[3].metric("Operating Cash Flow", f"AED {cashflow_engine['operating']:,.0f}")

        row3 = st.columns(4)
        row3[0].metric("Accounts Receivable", f"AED {ar_balance:,.0f}", f"Overdue AED {ar_overview['overdue']:,.0f}")
        row3[1].metric("Payables", f"AED {ap_balance:,.0f}", f"Overdue AED {ap_overview['overdue']:,.0f}")
        row3[2].metric(
            "Cash Runway",
            f"{burn_stats['cash_runway_months']:.1f} months" if burn_stats["cash_runway_months"] else "∞",
            f"Burn AED {burn_stats['burn_rate']:,.0f}/month",
        )
        collection_eff = (cashflow_engine["customer_collections"] / revenue * 100) if revenue else 0.0
        row3[3].metric("Collection Efficiency", f"{collection_eff:.1f}%")
        st.caption(f"DSO {dso:.1f} days · DPO {dpo:.1f} days · Profitability Index {profitability_index:.2f}")

        summary_df = pd.DataFrame(
            {
                "Metric": ["Revenue", "Gross Profit", "Operating Expense", "Net Profit"],
                "Amount": [
                    revenue,
                    pl_metrics["gross_profit"],
                    pl_metrics["operating_expenses"],
                    pl_metrics["net_profit"],
                ],
            }
        )
        st.plotly_chart(px.bar(summary_df, x="Metric", y="Amount", text_auto=".2s", color="Metric"), use_container_width=True)

    # ---------------- PROFITABILITY TAB ----------------
    with tab_profit:
        st.subheader("Revenue vs Expense Trend")

        revenue_trend_records = []
        for inv in filter_by_date(invoices, "date", start_date, end_date):
            inv_date = _coerce_date(inv.get("date"))
            if inv_date:
                revenue_trend_records.append({"Date": inv_date, "Revenue": to_float(inv.get("total"))})
        expense_trend_records = []
        for exp in filter_by_date(expenses, ["date", "expense_date"], start_date, end_date):
            exp_date = _coerce_date(exp.get("date") or exp.get("expense_date"))
            if exp_date:
                expense_trend_records.append(
                    {"Date": exp_date, "Expenses": to_float(exp.get("amount") or exp.get("total"))}
                )

        revenue_trend_df = (
            pd.DataFrame(revenue_trend_records).groupby("Date", as_index=False).sum() if revenue_trend_records else pd.DataFrame()
        )
        expense_trend_df = (
            pd.DataFrame(expense_trend_records).groupby("Date", as_index=False).sum() if expense_trend_records else pd.DataFrame()
        )

        if not revenue_trend_df.empty and not expense_trend_df.empty:
            trend_df = pd.merge(revenue_trend_df, expense_trend_df, on="Date", how="outer").fillna(0)
            trend_df = trend_df.sort_values("Date")
            st.plotly_chart(px.line(trend_df, x="Date", y=["Revenue", "Expenses"], markers=True), use_container_width=True)
        elif not revenue_trend_df.empty:
            tmp = revenue_trend_df.rename(columns={"Revenue": "Amount"})
            tmp["Type"] = "Revenue"
            st.plotly_chart(px.line(tmp, x="Date", y="Amount", color="Type", markers=True), use_container_width=True)
        elif not expense_trend_df.empty:
            tmp = expense_trend_df.rename(columns={"Expenses": "Amount"})
            tmp["Type"] = "Expenses"
            st.plotly_chart(px.line(tmp, x="Date", y="Amount", color="Type", markers=True), use_container_width=True)
        else:
            st.info("No revenue or expense activity for this period.")

        pi_cols = st.columns(3)
        pi_cols[0].metric("Gross Profit", f"AED {pl_metrics['gross_profit']:,.0f}")
        expense_runrate = (expense_period_total / period_days * 30) if period_days else 0.0
        pi_cols[1].metric("Expense Run-rate", f"AED {expense_runrate:,.0f}/month")
        pi_cols[2].metric("Profitability Index", f"{profitability_index:.2f}")

        st.subheader("Expense Breakdown by Account")
        if expense_df.empty:
            st.info("No expense data for this period.")
        else:
            st.plotly_chart(
                px.pie(expense_df, values="Amount", names="Category", hole=0.4),
                use_container_width=True,
            )

    # ---------------- CASH FLOW TAB ----------------
    with tab_cash:
        st.subheader("Cash Flow Activities")
        cf_df = pd.DataFrame(
            {
                "Activity": ["Operating", "Investing", "Financing"],
                "Amount": [
                    cashflow_engine["operating"],
                    cashflow_engine["investing"],
                    cashflow_engine["financing"],
                ],
            }
        )
        st.plotly_chart(px.bar(cf_df, x="Activity", y="Amount", text_auto=".2s"), use_container_width=True)

        cf_cols = st.columns(4)
        cf_cols[0].metric("Customer Collections", f"AED {cashflow_engine['customer_collections']:,.0f}")
        cf_cols[1].metric("Vendor Payments", f"AED {cashflow_engine['vendor_payments']:,.0f}")
        cf_cols[2].metric("Expense Cash", f"AED {cashflow_engine['expense_cash']:,.0f}")
        cf_cols[3].metric("Net Change", f"AED {cashflow_engine['net_change']:,.0f}")

        st.subheader("Inflow vs Outflow Trend (Payments)")
        inflow_records = []
        for p in filter_by_date(customer_payments, ["payment_date", "date"], start_date, end_date):
            d = _coerce_date(p.get("payment_date") or p.get("date"))
            if d:
                inflow_records.append({"Date": d, "Direction": "Inflow", "Amount": to_float(p.get("amount"))})
        outflow_records = []
        for p in filter_by_date(vendor_payments, ["payment_date", "date"], start_date, end_date):
            d = _coerce_date(p.get("payment_date") or p.get("date"))
            if d:
                outflow_records.append({"Date": d, "Direction": "Outflow", "Amount": to_float(p.get("amount"))})
        pay_df = pd.DataFrame(inflow_records + outflow_records)
        if not pay_df.empty:
            pay_summary = pay_df.groupby(["Date", "Direction"], as_index=False).sum()
            st.plotly_chart(px.bar(pay_summary, x="Date", y="Amount", color="Direction"), use_container_width=True)
        else:
            st.info("No payment movement for the selected period.")

        col_cf1, col_cf2 = st.columns(2)
        col_cf1.metric("Ending Cash", f"AED {cash_on_hand:,.0f}")
        col_cf2.metric(
            "Runway",
            f"{burn_stats['cash_runway_months']:.1f} months" if burn_stats["cash_runway_months"] else "∞",
            f"Burn AED {burn_stats['burn_rate']:,.0f}/month",
        )

    # ---------------- COLLECTIONS TAB ----------------
    with tab_collections:
        st.subheader("Collections KPIs")
        col_col1, col_col2, col_col3, col_col4 = st.columns(4)
        col_col1.metric("Accounts Receivable", f"AED {ar_balance:,.0f}")
        col_col2.metric("Overdue AR", f"AED {ar_overview['overdue']:,.0f}")
        col_col3.metric("Collected This Period", f"AED {cashflow_engine['customer_collections']:,.0f}")
        col_col4.metric("Credit Notes", f"AED {credit_notes_total:,.0f}")

        st.subheader("AR Aging Buckets")
        if ar_df.empty:
            st.info("No AR data.")
        else:
            ar_chart = pd.DataFrame({"Bucket": list(ar_buckets.keys()), "Amount": list(ar_buckets.values())})
            st.plotly_chart(px.bar(ar_chart, x="Bucket", y="Amount", text_auto=".2s"), use_container_width=True)

        st.subheader("Top Overdue Customers")
        if overdue_customers_df.empty:
            st.info("No overdue customers 🎉")
        else:
            st.dataframe(overdue_customers_df, use_container_width=True, hide_index=True)

    # ---------------- OPERATIONS TAB ----------------
    with tab_operations:
        st.subheader("AP & Expense KPIs")
        ops_cols = st.columns(4)
        ops_cols[0].metric("Payables", f"AED {ap_balance:,.0f}")
        ops_cols[1].metric("AP Overdue", f"AED {ap_overview['overdue']:,.0f}")
        ops_cols[2].metric("Period Spend", f"AED {vendor_insights['spend_period']:,.0f}")
        expense_runrate = (expense_period_total / period_days * 30) if period_days else 0.0
        ops_cols[3].metric("Expense Run-rate", f"AED {expense_runrate:,.0f}/month")

        st.subheader("AP Aging Buckets")
        if ap_df.empty:
            st.info("No AP data.")
        else:
            ap_chart = pd.DataFrame({"Bucket": list(ap_buckets.keys()), "Amount": list(ap_buckets.values())})
            st.plotly_chart(px.bar(ap_chart, x="Bucket", y="Amount", text_auto=".2s"), use_container_width=True)

        st.subheader("Expenses by Vendor")
        if vendor_spend_df.empty:
            st.info("Vendor spend not available.")
        else:
            fig_vendor = px.pie(
                vendor_spend_df,
                values="Spend",
                names="Name",
                hole=0.5,
            )
            fig_vendor.update_traces(textposition="inside", texttemplate="%{percent:.1%}")
            st.plotly_chart(fig_vendor, use_container_width=True)
            st.dataframe(
                vendor_spend_df.rename(columns={"Name": "Vendor"}),
                use_container_width=True,
                hide_index=True,
            )

        st.subheader("Expense Breakdown")
        st.caption(f"Expense rows: {len(expense_df)}, total AED {expense_period_total:,.2f}")
        if expense_df.empty:
            st.info("No expense data available for this period to show a breakdown.")
        else:
            exp_top = (
                expense_df.sort_values("Amount", ascending=False)
                .head(10)
                .reset_index(drop=True)
            )
            fig_exp = px.pie(
                exp_top,
                values="Amount",
                names="Category",
                hole=0.5,
            )
            fig_exp.update_traces(textposition="inside", texttemplate="%{percent:.1%}")
            st.plotly_chart(fig_exp, use_container_width=True)
            st.dataframe(
                expense_df.sort_values("Amount", ascending=False).reset_index(drop=True),
                use_container_width=True,
                hide_index=True,
            )

        st.subheader("Orders Pipeline (PO/SO)")
        order_cols = st.columns(2)
        order_cols[0].metric(
            "Purchase Orders - Open",
            f"{po_summary['open_count']} orders",
            f"AED {po_summary['open_amount']:,.0f}",
        )
        order_cols[1].metric(
            "Sales Orders - Open",
            f"{so_summary['open_count']} orders",
            f"AED {so_summary['open_amount']:,.0f}",
        )

    # ---------------- BANK & LIQUIDITY TAB ----------------
    with tab_bank:
        st.subheader("Liquidity KPIs")
        bank_cols = st.columns(4)
        bank_cols[0].metric("Cash on Hand", f"AED {cash_on_hand:,.0f}")
        bank_cols[1].metric("Bank Inflow", f"AED {bank_tx_summary['inflow']:,.0f}")
        bank_cols[2].metric("Bank Outflow", f"AED {bank_tx_summary['outflow']:,.0f}")
        bank_cols[3].metric(
            "Net Movement",
            f"AED {bank_tx_summary['net']:,.0f}",
            f"Runway {burn_stats['cash_runway_months']:.1f} months" if burn_stats["cash_runway_months"] else "∞",
        )

        st.subheader("Bank Accounts")
        if bank_df.empty:
            st.info("No linked bank accounts.")
        else:
            st.plotly_chart(px.bar(bank_df, x="Account", y="Balance", text_auto=".2s"), use_container_width=True)
            st.dataframe(bank_df, use_container_width=True, hide_index=True)

    # ---------------- RELATIONSHIPS TAB ----------------
    with tab_relationships:
        st.subheader("Customer Insights")
        cust_cols = st.columns(4)
        cust_cols[0].metric("Customers", f"{customer_insights['total_customers']}")
        cust_cols[1].metric("Active Customers", f"{customer_insights['active_customers']}")
        cust_cols[2].metric("Avg Invoice", f"AED {customer_insights['avg_invoice']:,.0f}")
        cust_cols[3].metric("Customers with Overdue", f"{customer_insights['overdue_customers']}")

        st.subheader("Vendor Insights")
        v_cols = st.columns(4)
        v_cols[0].metric("Vendors", f"{vendor_insights['total_vendors']}")
        v_cols[1].metric("Active Vendors", f"{vendor_insights['active_vendors']}")
        v_cols[2].metric("AP Outstanding", f"AED {vendor_insights['ap_outstanding']:,.0f}")
        v_cols[3].metric("AP Overdue", f"AED {vendor_insights['ap_overdue']:,.0f}")


if __name__ == "__main__":
    main()
