import textwrap
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =========================================================
# Core compound interest logic
# =========================================================
def compound_schedule(
    start_balance,
    years,
    monthly_contrib_by_year,
    annual_expense_by_year,
    annual_rate=None,
    annual_rate_by_year=None,
    use_yearly_compounding=False
):
    if annual_rate_by_year is not None and len(annual_rate_by_year) != years:
        raise ValueError("annual_rate_by_year length must equal 'years'")

    balance = start_balance
    cum_contrib = 0.0
    cum_expense_abs = 0.0

    rows = []

    for year_idx in range(years):
        if annual_rate_by_year is not None:
            r = annual_rate_by_year[year_idx]
        else:
            r = annual_rate if annual_rate is not None else 0.0

        # --- START OF YEAR SNAPSHOT ---
        # This is the balance available on Day 1 of the year
        balance_start_year = balance
        
        contrib_year = 0.0
        growth_year_sum = 0.0

        if use_yearly_compounding:
            # --- YEARLY COMPOUNDING LOGIC ---
            # Growth based on start balance
            growth_year_sum = balance * r
            balance += growth_year_sum
            
            monthly_val = monthly_contrib_by_year[year_idx]
            annual_contrib = monthly_val * 12.0
            balance += annual_contrib
            
            contrib_year = annual_contrib
            cum_contrib += annual_contrib
        else:
            # --- MONTHLY COMPOUNDING LOGIC ---
            # We assume contributions happen during the year, but we still track
            # start balance as the anchor.
            m = 12
            for _ in range(m):
                monthly_contrib = monthly_contrib_by_year[year_idx]
                balance += monthly_contrib
                cum_contrib += monthly_contrib
                contrib_year += monthly_contrib

                growth_month = balance * (r / m)
                balance += growth_month
                growth_year_sum += growth_month

        balance_before_expense = balance
        annual_expense = annual_expense_by_year[year_idx]

        # Deduct Annual Expense at Year End (or throughout, simplified here as net deduction)
        balance = balance_before_expense - annual_expense
        cum_expense_abs += annual_expense

        # GROWTH CALCULATION (The "Plug"):
        net_growth_cum = balance - (start_balance + cum_contrib)
        
        # We record both Start and End balance.
        # For the requested "Start of Year" view, 'StartBalance' is the key metric.
        rows.append(
            {
                "Year": year_idx + 1,
                "StartBalance": balance_start_year,
                "EndBalance": balance,
                "CumContributions": cum_contrib,
                "ContribYear": contrib_year,
                "InvestGrowth": net_growth_cum,
                "InvestGrowthYear": growth_year_sum, 
                "AnnualRate": r,
                "ExpenseDrag": 0.0,      
                "NetGrowth": net_growth_cum,
                "AnnualExpense": annual_expense,
                "CumulativeExpense": cum_expense_abs,
            }
        )

    return pd.DataFrame(rows)


# =========================================================
# FI Simulation Helpers
# =========================================================

def simulate_period_exact(
    start_balance_nominal,
    start_age,
    end_age,
    current_age,
    annual_rates_full,
    annual_expense_real,
    monthly_contrib_real,
    infl_rate,
    tax_rate=0.0,
    early_withdrawal_tax_rate=0.0,
    use_yearly_compounding=False
):
    balance = start_balance_nominal
    
    # Loop simulates years passing.
    # If start_age=50 and end_age=60, we simulate 10 years of growth.
    # The result 'balance' is the End-of-Year balance of the final year.
    # End-of-Year 59 is effectively Start-of-Year 60.
    for age in range(start_age, end_age):
        year_idx = age - current_age
        
        if year_idx < 0 or year_idx >= len(annual_rates_full):
            break
            
        r_nominal = annual_rates_full[year_idx]
        
        years_from_now = year_idx + 1 
        infl_factor = (1 + infl_rate) ** years_from_now
        
        # 1. Income / Contributions
        contrib_nominal = monthly_contrib_real * infl_factor
        
        # 2. Base Expense Calculation
        base_expense_nominal = annual_expense_real * infl_factor
        if tax_rate > 0:
            base_expense_nominal = base_expense_nominal / (1.0 - tax_rate)

        # 3. Net Draw Needed
        net_draw_nominal = base_expense_nominal
        
        # 4. Early Withdrawal Penalty Logic (Age < 60)
        final_withdrawal_nominal = 0.0
        
        if net_draw_nominal > 0:
            if age < 60 and early_withdrawal_tax_rate > 0:
                final_withdrawal_nominal = net_draw_nominal / (1.0 - early_withdrawal_tax_rate)
            else:
                final_withdrawal_nominal = net_draw_nominal 

        if use_yearly_compounding:
            growth = balance * r_nominal
            balance += growth
            balance += (contrib_nominal * 12.0)
            balance -= final_withdrawal_nominal
        else:
            monthly_rate = r_nominal / 12.0
            for _ in range(12):
                balance += contrib_nominal
                balance += balance * monthly_rate
            balance -= final_withdrawal_nominal
        
        if balance < 0:
            balance = 0.0
            break
            
    return balance

# Helper to calculate Nominal Target for a specific year
def get_nominal_target(real_target, years_passed, infl_rate):
    return real_target * ((1 + infl_rate) ** years_passed)

def get_dynamic_swr(age, base_swr):
    """
    Adjust SWR based on retirement horizon.
    Earlier retirement = Longer horizon = Lower SWR needed.
    """
    if age >= 60:
        return base_swr
    elif age >= 50:
        # e.g., 4.0% -> 3.75%
        return max(0.01, base_swr - 0.0025)
    elif age >= 40:
        # e.g., 4.0% -> 3.50%
        return max(0.01, base_swr - 0.0050)
    else:
        # e.g., 4.0% -> 3.25%
        return max(0.01, base_swr - 0.0075)

def compute_regular_fi_age(
    df_full, current_age, start_balance_input, fi_annual_spend_today,
    infl_rate, base_swr
):
    if fi_annual_spend_today <= 0 or base_swr <= 0 or df_full is None:
        return None, None
        
    final_target_real = 0.0
    
    # Iterate and find first crossover using Dynamic SWR
    for row in df_full.itertuples():
        age = row.Age
        
        # Determine SWR for this specific age
        current_swr = get_dynamic_swr(age, base_swr)
        
        # Calculate Target for this specific age
        target_real_at_age = fi_annual_spend_today / current_swr
        
        years_passed = age - current_age
        
        # Nominal Target for this specific year
        target_nominal = get_nominal_target(target_real_at_age, years_passed, infl_rate)
        
        if row.StartBalance >= target_nominal:
            return age, target_real_at_age
            
    # If not found, return the target implied by the last age checked (usually 90)
    # or just the standard target. Let's return the standard 4% target for display fallback.
    return None, fi_annual_spend_today / base_swr

def compute_barista_fi_age(
    df_full, current_age, start_balance_input, fi_annual_spend_today, barista_income_today, barista_spend_today,
    infl_rate, base_swr, barista_until_age, annual_rates_by_year_full, early_withdrawal_tax_rate, use_yearly_compounding
):
    # Updated Barista FIRE Definition:
    # 1. Start Barista Job at Age X.
    # 2. Withdraw (BaristaSpend - BaristaIncome) annually from Age X to 'barista_until_age'.
    # 3. CRITICAL: At 'barista_until_age', the remaining balance MUST equal the Full FI Number 
    #    (FullExpenses / SWR_at_that_age).
    
    # Calculate GAP based on Barista Spend, not Full Retirement Spend
    gap = max(0, barista_spend_today - barista_income_today)
    
    if base_swr <= 0 or df_full is None:
        return None, None

    # Calculate the Target we need to hit at the END of the Barista Phase (e.g. at 60)
    # This target is based on FULL RETIREMENT SPENDING
    final_swr = get_dynamic_swr(barista_until_age, base_swr)
    target_real_at_finish = fi_annual_spend_today / final_swr
    
    # Map start balances
    balance_map = {row.Age: row.StartBalance for row in df_full.itertuples()}
    balance_map[current_age] = start_balance_input
    
    # We iterate through candidate start ages
    # Checking current_age is allowed (immediate transition)
    for age in range(current_age, barista_until_age + 1):
        if age not in balance_map: continue
        
        start_bal = balance_map[age]
        
        # Determine the target in Nominal terms at the finish line
        years_total_horizon = barista_until_age - current_age
        target_nominal_finish = target_real_at_finish * ((1 + infl_rate) ** years_total_horizon)
        
        # Simulate the bridge period (Barista phase)
        # We withdraw ONLY the gap. Contributions are 0 (assuming Barista covers living + gap draw)
        final_bal = simulate_period_exact(
            start_balance_nominal=start_bal,
            start_age=age,
            end_age=barista_until_age,
            current_age=current_age,
            annual_rates_full=annual_rates_by_year_full,
            annual_expense_real=gap, # Withdrawal is just the gap (Spend - Income)
            monthly_contrib_real=0.0,
            infl_rate=infl_rate,
            tax_rate=0.0, # Simplified
            early_withdrawal_tax_rate=early_withdrawal_tax_rate,
            use_yearly_compounding=use_yearly_compounding
        )
        
        if final_bal >= target_nominal_finish:
            return age, target_real_at_finish # Return the Full Target they hit at the end
            
    return None, target_real_at_finish

def compute_coast_fi_age(
    df_full, current_age, start_balance_input, fi_annual_spend_today,
    infl_rate, base_swr, retirement_age, annual_rates_by_year_full
):
    # Coast FIRE Definition:
    # If I stop contributing NOW, will my current balance grow to hit my FI Number by Age 60 (or Retirement Age)?
    
    if fi_annual_spend_today <= 0 or base_swr <= 0 or df_full is None:
        return None, None, None, None
        
    target_real = fi_annual_spend_today / base_swr
    target_access_age = 60 # Standard FIRE access
    years_to_access = target_access_age - current_age
    
    # Target Nominal at Age 60
    target_nominal_at_60 = target_real * ((1 + infl_rate) ** years_to_access)
    
    # Map Age -> Nominal Start Balance (from Working Scenario)
    balance_map = {row.Age: row.StartBalance for row in df_full.itertuples()}
    balance_map[current_age] = start_balance_input
    
    for age in range(current_age, retirement_age + 1):
        if age not in balance_map: continue
        
        start_bal = balance_map[age]
        
        # Simulate purely purely growth (no contribs, no draws) from 'age' to '60'
        # We assume Coast means you cover expenses with active income, so net draw is 0.
        
        sim_years = target_access_age - age
        if sim_years <= 0:
            # We are past 60. Check if we hit it.
            if start_bal >= target_nominal_at_60: # Actually this check is complex if infl continues. Simplified:
                return age, start_bal, target_real, base_swr
            continue

        # Simple Compounding for simulation to check Coast
        # Using average rate roughly or iterating annual rates
        
        bal_sim = start_bal
        for k in range(sim_years):
            # year index in global array
            y_idx = (age - current_age) + k
            if y_idx < len(annual_rates_by_year_full):
                r = annual_rates_by_year_full[y_idx]
                bal_sim *= (1 + r)
        
        if bal_sim >= target_nominal_at_60:
            return age, start_bal, target_real, base_swr
            
    return None, None, None, None


# =========================================================
# Tax model
# =========================================================
def federal_tax_single_approx(income):
    if income <= 0: return 0.0
    brackets = [
        (0.0, 11600.0, 0.10),
        (11600.0, 47150.0, 0.12),
        (47150.0, 100525.0, 0.22),
        (100525.0, 191950.0, 0.24),
        (191950.0, 243725.0, 0.32),
        (243725.0, 609350.0, 0.35),
    ]
    top_rate = 0.37
    tax = 0.0
    for lower, upper, rate in brackets:
        if income <= lower: break
        span = min(income, upper) - lower
        if span > 0: tax += span * rate
        if income <= upper: break
    if income > brackets[-1][1]:
        tax += (income - brackets[-1][1]) * top_rate
    return max(tax, 0.0)

def total_tax_on_earned(income, state_tax_rate):
    if income <= 0: return 0.0
    federal = federal_tax_single_approx(income)
    ss_tax = 0.062 * min(income, 168600.0)
    medicare_tax = 0.0145 * income
    state_tax = max(state_tax_rate, 0.0) * income
    return federal + ss_tax + medicare_tax + state_tax


# =========================================================
# Income / expense schedule
# =========================================================
def build_income_schedule(
    current_age,
    retirement_age,
    start_income,
    income_growth_rate,
    expense_today,
    expense_growth_rate,
    infl_rate,
    savings_rate_override=0.0,
    show_real=True,
    state_tax_rate=0.0,
    promotions=None 
):
    years = retirement_age - current_age
    rows = []
    
    current_nominal_income = start_income

    for y in range(years):
        age = current_age + y
        
        if y > 0: 
            current_nominal_income *= (1 + income_growth_rate)
            
        if promotions and age in promotions:
            bump = promotions[age]
            current_nominal_income *= (1 + bump)

        if infl_rate > 0:
            df_y = (1 + infl_rate) ** y
            income_real_economic = current_nominal_income / df_y
        else:
            df_y = 1.0
            income_real_economic = current_nominal_income

        tax_real_economic = total_tax_on_earned(income_real_economic, state_tax_rate)
        after_tax_income_real_economic = max(income_real_economic - tax_real_economic, 0.0)
        expense_real_base_economic = expense_today * ((1 + expense_growth_rate) ** y)

        if savings_rate_override > 0:
            investable_real_economic = after_tax_income_real_economic * savings_rate_override
            implied_expense_real_economic = after_tax_income_real_economic - investable_real_economic
        else:
            implied_expense_real_economic = expense_real_base_economic
            investable_real_economic = max(after_tax_income_real_economic - implied_expense_real_economic, 0.0)

        if show_real and infl_rate > 0:
            display_income_pre = income_real_economic
            display_tax = tax_real_economic
            display_income_post = after_tax_income_real_economic
            display_expense = implied_expense_real_economic
            display_investable = investable_real_economic
        else:
            display_income_pre = income_real_economic * df_y
            display_tax = tax_real_economic * df_y
            display_income_post = after_tax_income_real_economic * df_y
            display_expense = implied_expense_real_economic * df_y
            display_investable = investable_real_economic * df_y

        if after_tax_income_real_economic > 0:
            savings_rate_actual = investable_real_economic / after_tax_income_real_economic
        else:
            savings_rate_actual = 0.0

        rows.append(
            {
                "YearIndex": y,
                "Age": age,
                "IncomeRealBeforeTax": display_income_pre,
                "TaxReal": display_tax,
                "IncomeRealAfterTax": display_income_post,
                "ExpensesReal": display_expense,
                "InvestableRealAnnual": display_investable,
                "InvestableRealMonthly": display_investable / 12.0,
                "SavingsRate": savings_rate_actual,
            }
        )

    return pd.DataFrame(rows)


# =========================================================
# Glide path
# =========================================================
def glide_path_return(age, base_return):
    if age <= 35: return base_return + 0.01
    elif age <= 45: return base_return + 0.005
    elif age <= 55: return base_return
    elif age <= 65: return base_return - 0.01
    else: return base_return - 0.015


# =========================================================
# Main app (REDESIGNED)
# =========================================================
def main():
    st.set_page_config(page_title="FIRE Planner", layout="wide")
    
    # Custom CSS for "Cards" styling
    st.markdown("""
    <style>
    .kpi-card {
        background-color: #F8F9FA;
        border: 1px solid #E9ECEF;
        border-radius: 8px;
        padding: 8px 4px;
        text-align: center;
        margin-bottom: 5px;
        height: 100%;
        min-height: 90px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .kpi-title {
        font-size: 11px;
        color: #6C757D;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 2px;
    }
    .kpi-value {
        font-size: 18px;
        font-weight: 700;
        color: #212529;
        margin: 0;
        line-height: 1.2;
    }
    .kpi-subtitle {
        font-size: 10px;
        color: #495057;
        margin-top: 4px;
        line-height: 1.3;
    }
    .kpi-highlight {
        color: #0D47A1;
    }
    .section-header {
        font-size: 16px;
        font-weight: 600;
        margin-top: 0px;
        margin-bottom: 5px;
        padding-bottom: 0px;
        border-bottom: 2px solid #f0f0f0;
    }
    .compact-header {
        font-size: 14px;
        font-weight: 700;
        margin-bottom: 5px;
        color: #333;
    }
    </style>
    """, unsafe_allow_html=True)

    # Description of purpose (Make it small)
    c_head_1, c_head_2 = st.columns([3, 1])
    with c_head_1:
        st.markdown("##### 🔮 FIRE & Retirement Forecaster")
    with c_head_2:
        show_real = st.checkbox("Show Real Dollars", True, help="Adjust all values for inflation")

    # Container for Verdict Cards (We will populate this AFTER calculations)
    kpi_container = st.container()
    
    # --- SIDEBAR: Grouped & Organized ---
    
    # Global Settings (Age affects defaults)
    current_age = st.sidebar.number_input("Current Age", 20, 100, 30)
    
    # 1. Profile & Income (Reordered First)
    with st.sidebar.expander("1. Income & Expenses", expanded=True):
        start_income = st.number_input("Pre-tax Income ($)", 0, 1000000, 100000, step=5000)
        expense_today = st.number_input("Current Expenses ($/yr)", 0, 500000, 40000, step=1000)
        state_tax_rate = st.number_input("State Tax Rate (%)", 0.0, 15.0, 0.0, 0.5) / 100.0

        st.markdown("**Income Growth & Adjustments**")
        st.caption("Use positive % for raises, negative % (e.g. -50) for pay cuts (e.g. partner quitting).")
        income_growth_rate = st.number_input("Annual Income Growth (%)", 0.0, 20.0, 3.0, 0.5) / 100.0
        promotions = {}
        c1, c2 = st.columns(2)
        with c1:
            p1_default = max(35, current_age + 1)
            p1_age = st.number_input("Event 1 Age", current_age+1, 90, p1_default)
            
            p2_default = max(40, current_age + 1)
            p2_age = st.number_input("Event 2 Age", current_age+1, 90, p2_default)
        with c2:
            p1_pct = st.number_input("Event 1 % Change", -100.0, 500.0, 0.0, step=5.0) / 100.0
            p2_pct = st.number_input("Event 2 % Change", -100.0, 500.0, 0.0, step=5.0) / 100.0
        if p1_pct != 0: promotions[p1_age] = p1_pct
        if p2_pct != 0: promotions[p2_age] = p2_pct

    # 2. Future Goals (Reordered Second)
    with st.sidebar.expander("2. Future Goals", expanded=True):
        ret_default = max(60, current_age + 1)
        retirement_age = st.number_input("Full Retirement Age", current_age+1, 90, ret_default, help="The age you plan to stop working if you DON'T retire early (Traditional path).")
        
        fi_annual_spend_today = st.number_input("Retirement Spend ($)", 0, 500000, 60000, step=5000)
        barista_income_today = st.number_input("Barista Income Goal ($)", 0, 200000, 30000, step=5000)
        # ADDED NEW INPUT HERE
        barista_spend_today = st.number_input("Barista Annual Spend ($)", 0, 500000, 50000, step=5000, help="Spending specifically during Barista years. Often lower than full retirement.")
        barista_until_age = st.number_input("Work Barista Until Age", min_value=current_age+1, max_value=100, value=max(60, retirement_age))

    # 3. Assets & Housing (Reordered Third)
    with st.sidebar.expander("3. Assets & Housing", expanded=True):
        start_balance_input = st.number_input("Invested Assets ($)", 0, 10000000, 100000, step=5000)
        
        include_home = st.checkbox("Include Home Strategy", False) # Default OFF
        # Default Home vars
        home_price_today = 0
        home_equity_by_year_full = [] 
        
        # Home Inputs logic
        if include_home:
            home_status = st.radio("Status", ["Own", "Plan to Buy"], index=1)
            
            if home_status == "Own":
                current_home_value_today = st.number_input("Home Value", value=400000)
                equity_amount_now = st.number_input("Current Equity", value=120000)
                years_remaining_loan = st.number_input("Years Left on Loan", value=25)
                mortgage_rate = st.number_input("Rate (%)", value=6.5) / 100.0
                # Derived for logic below
                base_price = current_home_value_today
                purchase_idx = 0
                loan = max(base_price - equity_amount_now, 0.0)
                np = years_remaining_loan * 12
                mp = (loan * (mortgage_rate/12) / (1 - (1+mortgage_rate/12)**(-np))) if mortgage_rate > 0 else loan/np
            else:
                home_price_today = st.number_input("Target Price ($)", value=350000)
                planned_purchase_age = st.number_input("Buy Age", value=current_age+2, min_value=current_age)
                down_payment_pct = st.number_input("Down Payment %", value=20.0) / 100.0
                mortgage_rate = st.number_input("Rate (%)", value=5.8) / 100.0
                mortgage_term_years = st.number_input("Term (Years)", value=15)
                # Derived
                base_price = home_price_today
                purchase_idx = max(0, planned_purchase_age - current_age - 1)
                purch_price = base_price
                loan = purch_price * (1.0 - down_payment_pct)
                np = mortgage_term_years * 12
                mp = (loan * (mortgage_rate/12) / (1 - (1+mortgage_rate/12)**(-np))) if mortgage_rate > 0 else 0.0
            
            # Maintenance & Apprec defaults
            maintenance_pct = 0.01
            home_app_rate = 0.03
            current_rent = st.number_input("Current Rent/Mortgage (Planning to Buy ONLY)", value=1500, help="This rent amount is removed from your annual expenses if you buy a home, helping offset the new mortgage cost.") 
            est_prop_tax_monthly = st.number_input("Property Tax/Ins ($/mo)", value=300)

    # 4. Assumptions
    with st.sidebar.expander("4. Assumptions & Adjustments", expanded=False):
        compounding_type = st.radio("Compounding Frequency", ["Monthly", "Yearly"], index=0, help="Monthly is more precise. Yearly is easier to calculate by hand.")
        use_yearly = (compounding_type == "Yearly")
        
        # --- NEW INVESTMENT STYLE SELECTOR (RENAMED) ---
        st.markdown("**Investment Strategy**")
        
        # Map style to the "Anchor Rate" (Return at age 45-55).
        style_map = {
            "Aggressive": 0.09,   # Renamed from "Aggressive (100% Stocks)"
            "Balanced": 0.07,     # Renamed from "Balanced (60/40 Split)"
            "Conservative": 0.05, # Renamed from "Conservative (Heavy Bonds)"
            "Custom": None
        }
        
        invest_style = st.selectbox(
            "Portfolio Style", 
            options=list(style_map.keys()), 
            index=1, # Default Balanced
            help="Sets the baseline return. Rates decrease automatically as you age (Glide Path)."
        )
        
        if invest_style == "Custom":
            annual_rate_base = st.slider("Anchor Return (%)", 0.0, 15.0, 9.0, 0.5, help="This is the return at age 50. Younger years will be higher (+1%), older years lower (-1.5%).") / 100.0
        else:
            annual_rate_base = style_map[invest_style]
            # Show feedback on what this means for today
            current_rate_display = glide_path_return(current_age, annual_rate_base) * 100
            st.caption(f"Current Return (Age {current_age}): **{current_rate_display:.1f}%**")
            st.caption(f"Retirement Return (Age 65+): **{(annual_rate_base - 0.015)*100:.1f}%**")

        infl_rate = st.number_input("Inflation (%)", 0.0, 10.0, 3.0, 0.1) / 100.0
        base_swr_30yr = st.number_input("Safe Withdrawal Rate (%)", 1.0, 10.0, 4.0, 0.1) / 100.0
        # state_tax_rate MOVED TO INCOME SECTION
        expense_growth_rate = st.number_input("Expense Growth > Inflation (%)", 0.0, 10.0, 0.0, 0.5) / 100.0
        savings_rate_override = 0.0 
        
        st.markdown("---")
        st.markdown("**Early Withdrawal Taxes**")
        st.caption("Effective tax/penalty rate on withdrawals before age 60.")
        early_withdrawal_tax_rate = st.number_input("Early Tax Rate (%)", 0.0, 50.0, 15.0, 1.0) / 100.0

        st.markdown("---")
        st.markdown("**One-time Expenses**")
        use_kid = st.checkbox("Include Kids Expenses", False) # Default OFF
        if use_kid:
            k1, k2 = st.columns(2)
            kids_start_age = k1.number_input("Parent Age at First Kid", value=current_age+2)
            num_kids = k2.number_input("Number of Kids", value=2)
            kid_spacing = k1.number_input("Spacing (Years)", value=2)
            support_years = k2.number_input("Years of Support per Kid", value=22)
            annual_cost_per_kid_today = st.number_input("Cost/Kid/Yr ($)", value=6000)
        else:
            kids_start_age, num_kids, kid_spacing, support_years, annual_cost_per_kid_today = 0,0,0,0,0

        use_car = st.checkbox("Include Car Replacement", False) # Default OFF
        if use_car:
            c1, c2 = st.columns(2)
            car_cost_today = c1.number_input("Car Cost ($)", value=30000)
            first_car_age = c2.number_input("First Purchase Age", value=current_age+5)
            car_interval_years = c1.number_input("Replace Every (Yrs)", value=10)
        else:
            car_cost_today, first_car_age, car_interval_years = 0,0,0

    # --- CALCULATION ENGINE (Running BEFORE Dashboard Controls) ---
    
    df_income = build_income_schedule(
        current_age, retirement_age, start_income, income_growth_rate,
        expense_today, expense_growth_rate, infl_rate, savings_rate_override, show_real, state_tax_rate,
        promotions=promotions
    )

    max_sim_age = 90
    years_full = max_sim_age - current_age
    annual_rates_by_year_full = [glide_path_return(current_age + y, annual_rate_base) for y in range(years_full)]

    # Contributions
    monthly_contrib_by_year_full = []
    for y in range(years_full):
        if (current_age + y) < retirement_age and y < len(df_income):
            c_real = df_income.loc[y, "InvestableRealMonthly"]
            val = c_real * ((1 + infl_rate) ** y) if (show_real and infl_rate > 0) else c_real
        else:
            val = 0.0
        monthly_contrib_by_year_full.append(val)

    # Base Expenses (Kids, Cars, Housing)
    annual_expense_by_year_nominal_full = [0.0] * years_full
    
    # Tracking specific expense buckets
    exp_kids_nominal = [0.0] * years_full
    exp_cars_nominal = [0.0] * years_full
    exp_housing_nominal = [0.0] * years_full

    home_price_by_year_full = [0.0] * years_full
    home_equity_by_year_full = [0.0] * years_full
    housing_adj_by_year_full = [0.0] * years_full
    start_balance_effective = start_balance_input

    # Expense Injection Logic
    for y in range(years_full):
        age = current_age + y + 1
        
        # Kids Logic
        if use_kid:
            total_kids_cost_now = 0.0
            for k in range(int(num_kids)):
                k_start = kids_start_age + (k * kid_spacing)
                k_end = k_start + support_years
                if k_start <= age < k_end:
                    total_kids_cost_now += annual_cost_per_kid_today
            
            if total_kids_cost_now > 0:
                cost_nom = total_kids_cost_now * ((1+infl_rate)**(y+1))
                annual_expense_by_year_nominal_full[y] += cost_nom
                exp_kids_nominal[y] += cost_nom

        if use_car and (age >= first_car_age) and (age - first_car_age) % car_interval_years == 0:
            cost_nom = car_cost_today * ((1+infl_rate)**(y+1))
            annual_expense_by_year_nominal_full[y] += cost_nom
            exp_cars_nominal[y] += cost_nom

    # Home Logic Execution
    if include_home:
        # Re-calc Purchase logic for loop
        if home_status == "Plan to Buy":
            purch_price = home_price_today * ((1+home_app_rate)**(purchase_idx+1))
            if planned_purchase_age == current_age:
                start_balance_effective = max(0.0, start_balance_effective - (purch_price * down_payment_pct))
            else:
                if purchase_idx < years_full:
                    cost_nom = (purch_price * down_payment_pct)
                    annual_expense_by_year_nominal_full[purchase_idx] += cost_nom
                    exp_housing_nominal[purchase_idx] += cost_nom
            
            if mp > 0:
                housing_delta = (mp + est_prop_tax_monthly - current_rent) * 12
                for y in range(purchase_idx, years_full):
                    housing_adj_by_year_full[y] = housing_delta
        
        # Loop for equity
        for y in range(years_full):
            # For START OF YEAR view, we use 'y' instead of 'y+1' for appreciation
            # Start of Year 0 = Base Price (No growth yet)
            years_from_now = y 
            price_nom = base_price * ((1 + home_app_rate) ** years_from_now) if y >= purchase_idx else 0.0
            home_price_by_year_full[y] = price_nom
            
            # Simple Equity Calc
            if loan <= 0 or np == 0:
                equity = price_nom if y >= purchase_idx else 0.0
            else:
                if y < purchase_idx: equity = 0.0
                else:
                    k = min((y - purchase_idx) * 12, np) # Start of year means k payments made previously
                    outstanding = (loan * (1+mortgage_rate/12)**k - mp*((1+mortgage_rate/12)**k - 1)/(mortgage_rate/12)) if (mortgage_rate > 0 and k > 0) else max(loan - mp*k, 0.0)
                    if k >= np: outstanding = 0.0
                    equity = max(price_nom - outstanding, 0.0)
            home_equity_by_year_full[y] = equity
            
            # Maintenance
            if y >= purchase_idx:
                # Maintenance is paid during the year, based on value
                maint_cost = price_nom * maintenance_pct
                annual_expense_by_year_nominal_full[y] += maint_cost
                annual_expense_by_year_nominal_full[y] += maint_cost
                exp_housing_nominal[y] += maint_cost

    for y in range(years_full):
        annual_expense_by_year_nominal_full[y] += housing_adj_by_year_full[y]
        exp_housing_nominal[y] += housing_adj_by_year_full[y]

    # Full Simulation (Baseline)
    df_full = compound_schedule(
        start_balance_effective, years_full, monthly_contrib_by_year_full,
        annual_expense_by_year_nominal_full, annual_rate_by_year=annual_rates_by_year_full,
        use_yearly_compounding=use_yearly
    )
    df_full["Age"] = current_age + df_full["Year"] - 1
    # KEY CHANGE: "Balance" in our visuals will now map to "StartBalance"
    # This aligns the chart with "Start of Year" expectations.
    # We keep 'EndBalance' for logic that might need it.
    
    # --- KPI CALCS (Calculated HERE, before Dashboard Controls) ---
    coast_age, _, _, _ = compute_coast_fi_age(
        df_full, current_age, start_balance_effective, fi_annual_spend_today, 
        infl_rate, base_swr_30yr, retirement_age, annual_rates_by_year_full
    )
    fi_age_regular, fi_target_bal = compute_regular_fi_age(
        df_full, current_age, start_balance_effective, fi_annual_spend_today, 
        infl_rate, base_swr_30yr
    )
    barista_age, _ = compute_barista_fi_age(
        df_full, current_age, start_balance_effective, fi_annual_spend_today, barista_income_today, barista_spend_today, 
        infl_rate, base_swr_30yr, barista_until_age, annual_rates_by_year_full, early_withdrawal_tax_rate, use_yearly
    )

    # --- DASHBOARD VISUALIZATION CONTROLS ---
    
    # Use st.markdown to create a small vertical spacer instead of "---" if needed
    st.markdown("<div style='margin-bottom: 5px;'></div>", unsafe_allow_html=True)
    
    viz_col, control_col = st.columns([3, 1])
    
    # 5. Simulation Scenario (MOVED TO DASHBOARD)
    with control_col:
        st.markdown("**Visualize Scenario**")
        
        use_barista_mode = st.checkbox("Simulate Barista FIRE?", False, help="If checked, custom early retirement assumes Barista income.")
        
        # Custom Early Retirement Slider
        # Now fi_age_regular is defined!
        default_exit = fi_age_regular if fi_age_regular else 55
        custom_exit_age = st.slider("Custom Early Ret. Age", min_value=current_age+1, max_value=retirement_age, value=default_exit)
        
        # Scenario Selector
        # Define the available keys (internal IDs) and their display labels
        scenario_options = ["Work"]
        display_map = {"Work": "Work until Full Retirement"}
        
        # Only add Barista if valid
        if barista_age:
            scenario_options.append("Barista")
            display_map["Barista"] = f"Barista FIRE (Age {barista_age})"
            
        scenario_options.append("Custom")
        display_map["Custom"] = f"Custom (Age {custom_exit_age})"
        
        # --- ROBUST STATE MANAGEMENT ---
        # 1. Get current state, default to "Work"
        current_selection = st.session_state.get("scenario_selector", "Work")
        
        # 2. Check if current state is valid in the NEW options list
        if current_selection not in scenario_options:
            # If invalid (e.g. Barista no longer possible), fall back to Work
            current_selection = "Work"
            # Force update session state immediately so the widget renders correctly
            st.session_state.scenario_selector = current_selection
            
        # 3. Determine the index for the widget
        try:
            default_ix = scenario_options.index(current_selection)
        except ValueError:
            default_ix = 0
        
        # 4. Render widget
        selected_key = st.selectbox(
            "Select Scenario:", 
            options=scenario_options, 
            format_func=lambda x: display_map[x],
            index=default_ix,
            key="scenario_selector"
        )

    # --- DETERMINE SCENARIO LOGIC (Moved up for Chart & KPI) ---
    stop_age = retirement_age # Default
    is_coast, is_barista, is_early = False, False, False
    scenario_label = display_map[selected_key]
    
    if selected_key == "Barista":
        stop_age = barista_age
        is_barista = True
    elif selected_key == "Custom":
        stop_age = custom_exit_age
        if use_barista_mode:
            is_barista = True
        else:
            is_early = True

    # --- BUILD CHART DATA (Now available for KPIs) ---
    monthly_contrib_chart = []
    annual_expense_chart = list(annual_expense_by_year_nominal_full) 
    
    detailed_income_active = []
    detailed_expense_total = []
    
    det_living_withdrawal = []
    det_tax_penalty = []
    det_kids = []
    det_cars = []
    det_housing = []
    det_total_portfolio_draw = []
    detailed_total_spending = []

    def to_nom(val, y_idx):
        return val * ((1+infl_rate)**(y_idx)) if (show_real and infl_rate > 0) else val

    # RE-CALC CHART EXPENSES TO INCLUDE EARLY TAX
    for y in range(years_full):
        age = current_age + y
        
        # 1. Contributions
        val = monthly_contrib_by_year_full[y] if age < stop_age else 0.0
        monthly_contrib_chart.append(val)
        
        active_income_this_year = 0.0
        base_need = 0.0
        
        # 2. Retirement Phase Expenses
        if age >= stop_age:
            if is_barista:
                 if age < barista_until_age:
                     # BARISTA PHASE
                     active_income_this_year = barista_income_today
                     # Use Barista specific spend
                     base_need = max(0, barista_spend_today - barista_income_today) * ((1+infl_rate)**(y+1))
                 else:
                     # FULL RETIREMENT PHASE (After Barista)
                     base_need = fi_annual_spend_today * ((1+infl_rate)**(y+1))
                     active_income_this_year = 0.0
            elif is_early:
                 base_need = fi_annual_spend_today * ((1+infl_rate)**(y+1))
            else:
                 # Standard retirement
                 if age < retirement_age: base_need = 0.0
                 else: base_need = fi_annual_spend_today * ((1+infl_rate)**(y+1))

            net_draw = base_need
            
            gross_withdrawal = net_draw
            tax_penalty_amount = 0.0
            
            if net_draw > 0:
                if age < 60 and early_withdrawal_tax_rate > 0:
                    gross_withdrawal = net_draw / (1.0 - early_withdrawal_tax_rate)
                    tax_penalty_amount = gross_withdrawal - net_draw
            
            annual_expense_chart[y] += gross_withdrawal
            
            detailed_expense_total.append(gross_withdrawal + to_nom(active_income_this_year, y))
            detailed_income_active.append(to_nom(active_income_this_year, y))
            
            det_living_withdrawal.append(net_draw)
            det_tax_penalty.append(tax_penalty_amount)
            det_total_portfolio_draw.append(annual_expense_chart[y])

        else:
            det_total_portfolio_draw.append(annual_expense_chart[y]) 
            
            if y < len(df_income):
                val_from_table = df_income.loc[y, "IncomeRealAfterTax"]
                if show_real and infl_rate > 0:
                        val_nominal = val_from_table * ((1 + infl_rate) ** y)
                else:
                        val_nominal = val_from_table
                
                detailed_income_active.append(val_nominal)
            else:
                detailed_income_active.append(0.0)
                
            detailed_expense_total.append(annual_expense_chart[y])
            det_living_withdrawal.append(0.0)
            det_tax_penalty.append(0.0)

        det_kids.append(exp_kids_nominal[y])
        det_cars.append(exp_cars_nominal[y])
        det_housing.append(exp_housing_nominal[y])
        
        # --- TOTAL SPENDING CALCULATION (Independent of Income Source) ---
        # Calculate nominal base spending first
        base_spending_nom = 0.0
        
        # Inflation factor for manual calc
        inf_f = (1 + infl_rate) ** y
        
        if age < stop_age:
             # Accumulation Phase: Use Current Expenses + Growth
             base_spending_nom = expense_today * ((1 + expense_growth_rate) ** y) * inf_f
        elif is_barista and age < barista_until_age:
             # Barista Phase
             base_spending_nom = barista_spend_today * inf_f
        else:
             # Retirement Phase
             base_spending_nom = fi_annual_spend_today * inf_f
             
        # Add Lumpy Expenses (Already nominal) + Tax Penalty
        # Note: TaxPenalty is calculated above in retirement logic (0 otherwise)
        lumpy_total = exp_kids_nominal[y] + exp_cars_nominal[y] + exp_housing_nominal[y] + (det_tax_penalty[-1] if det_tax_penalty else 0.0)
        
        detailed_total_spending.append(base_spending_nom + lumpy_total)

    # 4. Generate Chart DF
    df_chart = compound_schedule(
        start_balance_effective, years_full, monthly_contrib_chart,
        annual_expense_chart, annual_rate_by_year=annual_rates_by_year_full,
        use_yearly_compounding=use_yearly
    )
    df_chart["Age"] = current_age + df_chart["Year"] - 1
    df_chart["Balance"] = df_chart["StartBalance"]
    
    df_chart["HomeEquity"] = home_equity_by_year_full
    df_chart["NetWorth"] = df_chart["Balance"] + df_chart["HomeEquity"]
    
    df_chart["ScenarioActiveIncome"] = detailed_income_active
    df_chart["TotalPortfolioDraw"] = det_total_portfolio_draw
    df_chart["LivingWithdrawal"] = det_living_withdrawal
    df_chart["TaxPenalty"] = det_tax_penalty
    df_chart["KidCost"] = det_kids
    df_chart["CarCost"] = det_cars
    df_chart["HomeCost"] = det_housing
    df_chart["TotalSpending"] = detailed_total_spending

    # Real Adjustment
    if show_real and infl_rate > 0:
        # For Start of Year adjustments, we deflate by (1+inf)^year_idx
        df_chart["DF"] = (1+infl_rate)**(df_chart["Year"] - 1)
        for c in ["Balance", "HomeEquity", "NetWorth", "AnnualExpense", "StartBalance", "EndBalance"]:
            df_chart[c] /= df_chart["DF"]
        for c in ["ScenarioActiveIncome", "TotalPortfolioDraw", "LivingWithdrawal", "TaxPenalty", "KidCost", "CarCost", "HomeCost", "InvestGrowthYear", "ContribYear", "TotalSpending"]:
            df_chart[c] /= df_chart["DF"]

    # --- DYNAMIC FUTURE INCOME KPI ---
    
    # 1. Determine "Full Retirement Start Age" for the selected scenario
    full_ret_start_age = retirement_age # Default Work
    if is_barista:
        full_ret_start_age = barista_until_age
    elif is_early:
        full_ret_start_age = stop_age
    
    # 2. Get Balance at that age from df_chart
    # We look for the row where Age == full_ret_start_age
    row_at_ret = df_chart[df_chart["Age"] == full_ret_start_age]
    
    future_income_val = 0.0
    future_swr_used = 0.0
    
    if not row_at_ret.empty:
        final_balance = row_at_ret.iloc[0]["Balance"] # Already Real/Nominal adjusted by loop above
        future_swr_used = get_dynamic_swr(full_ret_start_age, base_swr_30yr)
        future_income_val = final_balance * future_swr_used
        
    # --- TOP ROW: THE VERDICT (Redesigned for Single Screen) ---
    
    def render_card(col, title, value, desc, sub_value=None):
        sub_html = f"<div style='font-size:12px; font-weight:600; color:#2E7D32; margin-top:2px;'>{sub_value}</div>" if sub_value else ""
        
        html_content = (
            f'<div class="kpi-card">'
            f'<div class="kpi-title">{title}</div>'
            f'<div class="kpi-value">{value}</div>'
            f'{sub_html}'
            f'<div class="kpi-subtitle">{textwrap.shorten(desc, width=60, placeholder="...")}</div>'
            f'</div>'
        )
        
        with col:
            st.markdown(html_content, unsafe_allow_html=True)

    with kpi_container:
        # Layout: 3 Equal Columns
        c1, c2, c3 = st.columns(3)
        
        # 1. Regular FIRE
        val_reg = str(fi_age_regular) if fi_age_regular else "N/A"
        color_reg = "#0D47A1" if fi_age_regular else "#CC0000"
        if fi_age_regular:
            swr_r = get_dynamic_swr(fi_age_regular, base_swr_30yr)
            desc_reg = f"Based on {swr_r*100:.2f}% SWR."
        else:
            desc_reg = "Target not reached."
        render_card(c1, "Regular FIRE Age", f"<span style='color:{color_reg}'>{val_reg}</span>", desc_reg)

        # 2. Barista FIRE
        val_bar = str(barista_age) if barista_age else "N/A"
        color_bar = "#0D47A1" if barista_age else "#CC0000"
        if barista_age:
            row_b = df_full[df_full["Age"] == barista_age]
            if not row_b.empty:
                # Calculate Nominal Gap
                gap_real = max(0, barista_spend_today - barista_income_today)
                y_idx = barista_age - current_age
                gap_nom = gap_real * ((1 + infl_rate) ** y_idx)
                
                # Nominal Balance at start of that year
                bal_nom = row_b.iloc[0]["StartBalance"]
                
                eff_swr = (gap_nom / bal_nom) if bal_nom > 0 else 0.0
                desc_bar = f"Gap SWR: {eff_swr*100:.2f}%. Work until {barista_until_age}."
            else:
                desc_bar = f"Work until {barista_until_age}."
        else:
            desc_bar = "N/A"
        render_card(c2, "Barista FIRE Age", f"<span style='color:{color_bar}'>{val_bar}</span>", desc_bar)
        
        # 3. Future Income (Dynamic)
        scen_name = "Work"
        if is_barista: scen_name = "Barista"
        elif is_early: scen_name = "Custom"
        
        render_card(
            c3, 
            f"Future Income ({scen_name})", 
            f"${future_income_val:,.0f}", 
            f"Safe draw at age {full_ret_start_age}.",
            sub_value=f"(${future_income_val/12:,.0f}/mo)"
        )

    # 5. Plot (In Left Column)
    with viz_col:
        # We plot a bit past the "Full Retirement Start" to show the safe phase
        # User requested: "until retirement age always"
        # We ensure it shows at least up to retirement_age, or the scenario end if later.
        plot_end = max(retirement_age, full_ret_start_age)
        if plot_end > max_sim_age: plot_end = max_sim_age
        
        df_p = df_chart[df_chart["Age"] <= plot_end].reset_index(drop=True)
        
        fig = go.Figure()
        # Main Balance
        fig.add_trace(go.Bar(
            x=df_p["Age"], y=df_p["Balance"], 
            name="Invested Assets (Start of Year)",
            marker_color='rgba(58, 110, 165, 0.8)', # Strong Blue
            hovertemplate="$%{y:,.0f}"
        ))
        # Home Equity
        fig.add_trace(go.Bar(
            x=df_p["Age"], y=df_p["HomeEquity"], 
            name="Home Equity (Start of Year)",
            marker_color='rgba(167, 173, 178, 0.5)', # Grey
            hovertemplate="$%{y:,.0f}"
        ))
        
        milestone = df_p[df_p["NetWorth"] >= 1000000]
        if not milestone.empty:
            m_row = milestone.iloc[0]
            fig.add_trace(go.Scatter(
                x=[m_row["Age"]],
                y=[m_row["NetWorth"]],
                mode="markers+text",
                name="Hit $1M",
                text=["Hit $1M!"],
                textposition="top center",
                marker=dict(color="#D32F2F", size=15, symbol="circle"),
                showlegend=False
            ))
        
        if not df_p.empty:
            final_row = df_p.iloc[-1]
            fig.add_annotation(
                x=final_row["Age"],
                y=final_row["NetWorth"],
                text=f"<b>${final_row['NetWorth']:,.0f}</b>",
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=2,
                ax=0,
                ay=-40,
                font=dict(size=16, color="black"),
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="black",
                borderwidth=1
            )
        
        target_val = fi_target_bal
        if show_real and infl_rate > 0: target_val = fi_annual_spend_today / base_swr_30yr
        
        fig.update_layout(
            # UPDATED TITLE SIZE AND BOLDNESS
            title=dict(text="<b>Net Worth Projection (Start of Year)</b>", font=dict(size=20)),
            xaxis_title="Age (Start of Year)", yaxis_title="Value ($)",
            barmode='stack',
            hovermode="x unified",
            legend=dict(orientation="h", y=1.02, x=0.01),
            margin=dict(l=20, r=20, t=40, b=20),
            height=380, # Slightly smaller height to ensure fit
            yaxis=dict(tickformat=",.0f")
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
    with control_col:
        st.info(f"Viewing: **{scenario_label}**")
        if is_barista:
            st.caption(f"Barista Phase: Age {stop_age} to {barista_until_age}")
            st.caption(f"Full Retire: Age {barista_until_age}+")
        elif is_early:
            st.caption(f"Early Retire: Age {stop_age}+")
        else:
            st.caption(f"Work until: Age {retirement_age}")

    # --- TABS FOR DETAILS ---
    tab1, tab2, tab3, tab4 = st.tabs(["Risk Analysis", "Cash Flow Details", "Net Worth Table", "Audit Table"])
    
    with tab1:
        st.caption("How market volatility (+/- 1% annual return) impacts your outcome.")
        rates_bear = [r - 0.01 for r in annual_rates_by_year_full]
        rates_bull = [r + 0.01 for r in annual_rates_by_year_full]
        
        df_bear = compound_schedule(start_balance_effective, years_full, monthly_contrib_chart, annual_expense_chart, annual_rate_by_year=rates_bear, use_yearly_compounding=use_yearly)
        df_bull = compound_schedule(start_balance_effective, years_full, monthly_contrib_chart, annual_expense_chart, annual_rate_by_year=rates_bull, use_yearly_compounding=use_yearly)
        
        for df_ in [df_bear, df_bull]:
            df_["Age"] = current_age + df_["Year"] - 1
            df_["NW"] = df_["StartBalance"] + home_equity_by_year_full
            if show_real and infl_rate > 0:
                df_["NW"] /= ((1+infl_rate)**(df_["Year"]-1))
        
        df_bear_p = df_bear[df_bear["Age"] <= plot_end]
        df_bull_p = df_bull[df_bull["Age"] <= plot_end]
        
        fig_cone = go.Figure()
        fig_cone.add_trace(go.Scatter(x=df_bull_p["Age"], y=df_bull_p["NW"], mode='lines', line=dict(width=0), name="Bull (+1%)", showlegend=False, hovertemplate="$%{y:,.0f}"))
        fig_cone.add_trace(go.Scatter(x=df_bear_p["Age"], y=df_bear_p["NW"], mode='lines', line=dict(width=0), fill='tonexty', fillcolor='rgba(200,200,200,0.3)', name="Range", hovertemplate="$%{y:,.0f}"))
        fig_cone.add_trace(go.Scatter(x=df_p["Age"], y=df_p["NetWorth"], mode='lines', line=dict(color='#3A6EA5', width=2), name="Base Case", hovertemplate="$%{y:,.0f}"))
        
        fig_cone.update_layout(height=300, margin=dict(t=20, b=20, l=20, r=20), hovermode="x unified", yaxis=dict(tickformat=",.0f"))
        st.plotly_chart(fig_cone, use_container_width=True)

    with tab2:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Income vs Expenses (Scenario)**")
            
            # --- CUSTOM LOGIC FOR GRAPH INCOME & EXPENSES ---
            # We reconstruct the lines based on the SCENARIO (Work vs Barista vs Early),
            # ensuring Barista income is treated as Pre-Tax.
            
            base_expenses_plot = []
            graph_gross_income = []
            graph_net_income = []
            
            for i, row in df_chart.iterrows():
                age = row["Age"]
                idx = int(row["Year"] - 1) # 0-based index
                
                # Inflation factor for manual adjustments if needed (Nominal conversion)
                infl_factor_nominal = (1 + infl_rate) ** idx
                
                # --- 1. INCOME LOGIC ---
                if age < stop_age:
                    # WORKING PHASE
                    if idx < len(df_income):
                        # df_income cols are already adjusted for show_real/nominal preference
                        g_val = df_income.loc[idx, "IncomeRealBeforeTax"]
                        n_val = df_income.loc[idx, "IncomeRealAfterTax"]
                        graph_gross_income.append(g_val)
                        graph_net_income.append(n_val)
                    else:
                        graph_gross_income.append(0.0)
                        graph_net_income.append(0.0)
                        
                elif is_barista and age < barista_until_age:
                    # BARISTA PHASE
                    # User input 'barista_income_today' is treated as PRE-TAX Real (Today's $)
                    
                    gross_real = barista_income_today
                    tax_real = total_tax_on_earned(gross_real, state_tax_rate)
                    net_real = max(0, gross_real - tax_real)
                    
                    if show_real and infl_rate > 0:
                        graph_gross_income.append(gross_real)
                        graph_net_income.append(net_real)
                    else:
                        graph_gross_income.append(gross_real * infl_factor_nominal)
                        graph_net_income.append(net_real * infl_factor_nominal)
                        
                else:
                    # FULL RETIREMENT PHASE
                    graph_gross_income.append(0.0)
                    graph_net_income.append(0.0)

                # --- 2. EXPENSE LOGIC ---
                if age < stop_age:
                    # Working Phase: Expense grows from 'Current Expenses'
                    val_nom = expense_today * ((1 + expense_growth_rate) ** idx) * infl_factor_nominal
                    base_expenses_plot.append(val_nom)
                elif is_barista and age < barista_until_age:
                     # Barista Phase: Use specific barista spend
                     val_nom = barista_spend_today * infl_factor_nominal
                     base_expenses_plot.append(val_nom)
                else:
                    # Retirement/Barista Phase: Expense is 'Retirement Spend' Target
                    val_nom = fi_annual_spend_today * infl_factor_nominal
                    base_expenses_plot.append(val_nom)
            
            # --- PREPARE PLOTTING DATA ---
            s_base_expenses = pd.Series(base_expenses_plot)
            
            # Adjust Expenses for Real/Nominal settings (using the DF column created in main)
            if show_real and infl_rate > 0:
                s_base_expenses /= df_chart["DF"]
                
            # Add Lumpy Expenses (Kid, Car, Home) to the Base
            total_scenario_expenses = (
                s_base_expenses + 
                df_chart["KidCost"] + 
                df_chart["CarCost"] + 
                df_chart["HomeCost"] + 
                df_chart["TaxPenalty"]
            )
            
            # Slice to match the plotting range
            df_p_graph = df_chart[df_chart["Age"] <= plot_end].reset_index(drop=True)
            y_gross = graph_gross_income[:len(df_p_graph)]
            y_net = graph_net_income[:len(df_p_graph)]
            y_expenses = total_scenario_expenses[:len(df_p_graph)]
            
            fig_i = go.Figure()
            
            # Gross Income Line
            fig_i.add_trace(go.Scatter(
                x=df_p_graph["Age"], 
                y=y_gross, 
                name="Gross Income", 
                line=dict(color="#B0BEC5", dash="dot", width=2), 
                hovertemplate="$%{y:,.0f}"
            ))
            
            # Net Income Line
            fig_i.add_trace(go.Scatter(
                x=df_p_graph["Age"], 
                y=y_net, 
                name="Net Income", 
                line=dict(color="#66BB6A", width=3), 
                hovertemplate="$%{y:,.0f}"
            ))
            
            # Expense Line
            fig_i.add_trace(go.Scatter(
                x=df_p_graph["Age"], 
                y=y_expenses, 
                name="Total Spending", 
                line=dict(color="#EF5350", width=3), 
                hovertemplate="$%{y:,.0f}"
            ))
            
            # Visual marker for Barista/Retirement transition
            if stop_age < plot_end:
                 fig_i.add_vline(x=stop_age, line_width=1, line_dash="dash", line_color="grey")

            fig_i.update_layout(
                height=300, 
                margin=dict(t=30, b=20, l=20, r=20), 
                yaxis=dict(tickformat=",.0f"),
                legend=dict(orientation="h", y=1.1, x=0)
            )
            st.plotly_chart(fig_i, use_container_width=True)
            
        with c2:
            st.markdown("**Investment Returns Glide Path**")
            fig_r = go.Figure()
            pcts = [r*100 for r in annual_rates_by_year_full]
            fig_r.add_trace(go.Scatter(x=df_p["Age"], y=pcts[:len(df_p)], mode='lines', name="Return %", hovertemplate="%{y:.1f}%"))
            fig_r.update_layout(height=250, margin=dict(t=20, b=20, l=20, r=20), yaxis_title="% Return", yaxis=dict(tickformat=".1f"))
            st.plotly_chart(fig_r, use_container_width=True)

        st.markdown("**Savings Rate (Accumulation Phase)**")
        # Keep original savings rate chart but limit to working years to avoid confusion
        df_savings_plot = df_income[df_income["Age"] < stop_age]
        
        fig_s = go.Figure()
        fig_s.add_trace(go.Scatter(
            x=df_savings_plot["Age"], 
            y=df_savings_plot["SavingsRate"] * 100, 
            mode='lines', 
            name="Savings Rate", 
            line=dict(color="#42A5F5"),
            hovertemplate="%{y:.1f}%"
        ))
        fig_s.update_layout(
            height=250, 
            margin=dict(t=20, b=20, l=20, r=20), 
            yaxis_title="Savings Rate (%)",
            yaxis=dict(tickformat=".1f")
        )
        st.plotly_chart(fig_s, use_container_width=True)

    with tab3:
        st.markdown("### Net Worth Summary (Start of Year)")
        st.caption("Simplified overview of your projected wealth at the start of each age.")
        
        format_dict = {
            "Balance": "${:,.0f}",
            "HomeEquity": "${:,.0f}", 
            "NetWorth": "${:,.0f}",
            "AnnualExpense": "${:,.0f}",
            "Age": "{:.0f}"
        }
        st.dataframe(
            df_p[["Age", "Balance", "HomeEquity", "NetWorth"]].style.format(format_dict), 
            use_container_width=True,
            hide_index=True
        )
        
    with tab4:
        st.markdown(f"**Audit Table: {scenario_label}**")
        st.caption("Detailed view of Start Balance to End Balance flow.")

        st.markdown("""
        #### 🧮 Flow Logic
        
        $$
        \\text{EndBalance} = \\text{StartBalance} + \\text{Growth} + \\text{AnnualSavings} - \\text{Withdrawals}
        $$
        
        Note: The **StartBalance** of the next row (Age + 1) equals the **EndBalance** of the current row.
        """)
        
        # Add Total Spending Column (Portfolio Draws + Active Income Used)
        # This reflects the total lifestyle cost (Spending).
        # Note: We use the pre-calculated detailed_total_spending to ensure it matches
        # consumption rather than just Income + Withdrawal.

        format_dict_d = {
            "StartBalance": "${:,.0f}",
            "EndBalance": "${:,.0f}",
            "LivingWithdrawal": "${:,.0f}",
            "TaxPenalty": "${:,.0f}",
            "KidCost": "${:,.0f}",
            "CarCost": "${:,.0f}",
            "HomeCost": "${:,.0f}",
            "TotalPortfolioDraw": "${:,.0f}",
            "ScenarioActiveIncome": "${:,.0f}",
            "InvestGrowthYear": "${:,.0f}",
            "ContribYear": "${:,.0f}",
            "TotalSpending": "${:,.0f}",
            "AnnualRate": "{:.2%}",
            "Age": "{:.0f}"
        }
        
        # UPDATED COLUMN ORDERING AS REQUESTED
        cols = [
            "Age", 
            "StartBalance",
            "AnnualRate",
            "InvestGrowthYear",
            "ContribYear", 
            # "TotalPortfolioDraw", # Removed to reduce clutter in favor of itemized list
            "EndBalance",
            "TotalSpending",
            "LivingWithdrawal", 
            "TaxPenalty", 
            "KidCost", 
            "CarCost", 
            "HomeCost",
            "ScenarioActiveIncome"
        ]
        
        st.dataframe(
            df_p[cols].style.format(format_dict_d),
            use_container_width=True,
            hide_index=True
        )

if __name__ == "__main__":
    main()
