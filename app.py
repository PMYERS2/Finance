import textwrap
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =========================================================
# Core compound interest logic (UNCHANGED)
# =========================================================
def compound_schedule(
    start_balance,
    years,
    monthly_contrib_by_year,
    annual_expense_by_year,
    annual_rate=None,
    annual_rate_by_year=None,
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

        m = 12
        balance_start_year = balance
        contrib_year = 0.0
        growth_year_sum = 0.0

        # Monthly Compounding Loop
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

        # Deduct Annual Expense at Year End
        balance = balance_before_expense - annual_expense
        cum_expense_abs += annual_expense

        # GROWTH CALCULATION (The "Plug"):
        net_growth_cum = balance - (start_balance + cum_contrib)

        rows.append(
            {
                "Year": year_idx + 1,
                "Balance": balance,
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
    early_withdrawal_tax_rate=0.0
):
    balance = start_balance_nominal
    
    for age in range(start_age, end_age):
        year_idx = age - current_age
        
        if year_idx < 0 or year_idx >= len(annual_rates_full):
            break
            
        r_nominal = annual_rates_full[year_idx]
        monthly_rate = r_nominal / 12.0
        
        years_from_now = year_idx + 1 
        infl_factor = (1 + infl_rate) ** years_from_now
        
        # 1. Income / Contributions
        contrib_nominal = monthly_contrib_real * infl_factor
        
        # 2. Base Expense Calculation
        base_expense_nominal = annual_expense_real * infl_factor
        if tax_rate > 0:
            # General tax adjustment if used
            base_expense_nominal = base_expense_nominal / (1.0 - tax_rate)

        # 3. Net Draw Needed
        net_draw_nominal = base_expense_nominal
        
        # 4. Early Withdrawal Penalty Logic (Age < 60)
        # If we are withdrawing (net_draw > 0) and under 60, we gross up the withdrawal
        final_withdrawal_nominal = 0.0
        
        if net_draw_nominal > 0:
            if age < 60 and early_withdrawal_tax_rate > 0:
                final_withdrawal_nominal = net_draw_nominal / (1.0 - early_withdrawal_tax_rate)
            else:
                final_withdrawal_nominal = net_draw_nominal
        else:
            # We have a surplus, add it to balance (negative withdrawal)
            final_withdrawal_nominal = net_draw_nominal 

        # Compounding
        for _ in range(12):
            balance += contrib_nominal
            balance += balance * monthly_rate
            
        balance -= final_withdrawal_nominal
        
        if balance < 0:
            balance = 0.0
            break
            
    return balance

def compute_bridge_age(
    df_full,
    current_age,
    retirement_age,
    start_balance_input,
    annual_rates_by_year_full,
    infl_rate,
    show_real,
    withdrawal_needed_real,
    terminal_target_real_at_60,
    early_withdrawal_tax_rate
):
    # 1. Map Age -> Nominal Baseline Balance
    balance_nominal_by_age = {}
    balance_nominal_by_age[current_age] = start_balance_input 

    for row in df_full.itertuples():
        age = row.Age
        bal = row.Balance 
        bal_nom = bal 
        balance_nominal_by_age[age] = bal_nom

    # 2. Determine Nominal Target at 60
    years_to_ret = retirement_age - current_age
    infl_factor_at_ret = (1 + infl_rate) ** years_to_ret
    
    target_nominal_at_60 = terminal_target_real_at_60 * infl_factor_at_ret
    
    start_age_candidate = current_age + 1
    
    for age0 in range(start_age_candidate, retirement_age + 1):
        start_node = age0 - 1
        if start_node not in balance_nominal_by_age:
            continue
        start_bal = balance_nominal_by_age[start_node]
        
        proj_bal_at_60_nominal = simulate_period_exact(
            start_balance_nominal=start_bal,
            start_age=age0,
            end_age=retirement_age, 
            current_age=current_age,
            annual_rates_full=annual_rates_by_year_full,
            annual_expense_real=withdrawal_needed_real,
            monthly_contrib_real=0.0,
            infl_rate=infl_rate,
            tax_rate=0.0,
            early_withdrawal_tax_rate=early_withdrawal_tax_rate
        )

        if proj_bal_at_60_nominal >= target_nominal_at_60:
            final_real_bal = proj_bal_at_60_nominal / infl_factor_at_ret
            return age0, final_real_bal
            
    return None, None


def compute_coast_fi_age(
    df_full, current_age, start_balance_input, fi_annual_spend_today,
    infl_rate, show_real, base_30yr_swr, retirement_age, annual_rates_by_year_full,
    early_withdrawal_tax_rate
):
    if fi_annual_spend_today <= 0 or base_30yr_swr <= 0 or df_full is None:
        return None, None, None, None
        
    target_at_60 = fi_annual_spend_today / base_30yr_swr
    
    age, bal = compute_bridge_age(
        df_full, current_age, retirement_age, start_balance_input, annual_rates_by_year_full,
        infl_rate, show_real, 0.0, target_at_60,
        early_withdrawal_tax_rate
    )
    
    return age, bal, target_at_60, base_30yr_swr


def compute_regular_fi_age(
    df_full, current_age, start_balance_input, fi_annual_spend_today,
    infl_rate, show_real, base_swr, retirement_age, annual_rates_by_year_full,
    early_withdrawal_tax_rate
):
    if fi_annual_spend_today <= 0 or base_swr <= 0 or df_full is None:
        return None, None
        
    target_at_60 = fi_annual_spend_today / base_swr
    
    age, bal = compute_bridge_age(
        df_full, current_age, retirement_age, start_balance_input, annual_rates_by_year_full,
        infl_rate, show_real, fi_annual_spend_today, target_at_60,
        early_withdrawal_tax_rate
    )
    
    return age, target_at_60


def compute_barista_fi_age(
    df_full, current_age, start_balance_input, fi_annual_spend_today, barista_income_today,
    infl_rate, show_real, base_swr, retirement_age, annual_rates_by_year_full,
    early_withdrawal_tax_rate
):
    gap = max(0, fi_annual_spend_today - barista_income_today)
    if gap == 0:
        return current_age, 0 
        
    if base_swr <= 0 or df_full is None:
        return None, None

    target_at_60 = fi_annual_spend_today / base_swr
    
    age, bal = compute_bridge_age(
        df_full, current_age, retirement_age, start_balance_input, annual_rates_by_year_full,
        infl_rate, show_real, gap, target_at_60,
        early_withdrawal_tax_rate
    )
    
    return age, target_at_60


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
        padding: 10px 15px;
        text-align: center;
        margin-bottom: 10px;
        height: 100%;
    }
    .kpi-title {
        font-size: 13px;
        color: #6C757D;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 2px;
    }
    .kpi-value {
        font-size: 26px;
        font-weight: 700;
        color: #212529;
        margin: 0;
        line-height: 1.2;
    }
    .kpi-subtitle {
        font-size: 12px;
        color: #495057;
        margin-top: 5px;
        line-height: 1.4;
    }
    .kpi-highlight {
        color: #0D47A1;
    }
    .section-header {
        font-size: 18px;
        font-weight: 600;
        margin-top: 10px;
        margin-bottom: 10px;
        padding-bottom: 5px;
        border-bottom: 2px solid #f0f0f0;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("Financial Independence Planner")
    
    # Container for Verdict Cards (so they can be populated after we define dashboard controls below)
    kpi_container = st.container()
    
    # --- SIDEBAR: Grouped & Organized ---
    with st.sidebar.expander("1. Profile & Current State", expanded=True):
        current_age = st.number_input("Current Age", 20, 100, 30)
        start_income = st.number_input("Pre-tax Income ($)", 0, 1000000, 90000, step=5000)
        expense_today = st.number_input("Current Expenses ($/yr)", 0, 500000, 36000, step=1000)
    
        st.markdown("**Income Growth & Adjustments**")
        st.caption("Use positive % for raises, negative % (e.g. -50) for pay cuts (e.g. partner quitting).")
        income_growth_rate = st.number_input("Annual Income Growth (%)", 0.0, 20.0, 3.0, 0.5) / 100.0
        promotions = {}
        c1, c2 = st.columns(2)
        with c1:
            # FIX: Use max() to ensure the default value never falls below the dynamic min_value (current_age + 1)
            p1_default = max(35, current_age + 1)
            p1_age = st.number_input("Event 1 Age", current_age+1, 90, p1_default)
            
            p2_default = max(40, current_age + 1)
            p2_age = st.number_input("Event 2 Age", current_age+1, 90, p2_default)
        with c2:
            p1_pct = st.number_input("Event 1 % Change", -100.0, 500.0, 0.0, step=5.0) / 100.0
            p2_pct = st.number_input("Event 2 % Change", -100.0, 500.0, 0.0, step=5.0) / 100.0
        if p1_pct != 0: promotions[p1_age] = p1_pct
        if p2_pct != 0: promotions[p2_age] = p2_pct

    with st.sidebar.expander("2. Assets & Housing", expanded=True):
        start_balance_input = st.number_input("Invested Assets ($)", 0, 10000000, 100000, step=5000)
        
        include_home = st.checkbox("Include Home Strategy", True)
        # Default Home vars
        home_price_today = 0
        home_equity_by_year_full = [] # Will fill later
        
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
                home_price_today = st.number_input("Target Price ($)", value=250000)
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
            current_rent = st.number_input("Current Rent", value=1100)
            est_prop_tax_monthly = st.number_input("Tax/Ins ($/mo)", value=300)

    with st.sidebar.expander("3. Future Goals", expanded=True):
        # FIX: Dynamic default for retirement age to prevent error if current_age >= 60
        ret_default = max(60, current_age + 1)
        retirement_age = st.number_input("Full Retirement Age", current_age+1, 90, ret_default, help="The age you plan to stop working if you DON'T retire early (Traditional path).")
        
        fi_annual_spend_today = st.number_input("Retirement Spend ($)", 0, 500000, 60000, step=5000)
        barista_income_today = st.number_input("Barista Income Goal ($)", 0, 200000, 30000, step=5000)

    with st.sidebar.expander("Assumptions & Adjustments", expanded=False):
        annual_rate_base = st.slider("Investment Return (%)", 0.0, 15.0, 9.0, 0.5) / 100.0
        infl_rate = st.number_input("Inflation (%)", 0.0, 10.0, 3.0, 0.1) / 100.0
        base_swr_30yr = st.number_input("Safe Withdrawal Rate (%)", 1.0, 10.0, 4.0, 0.1) / 100.0
        state_tax_rate = st.number_input("State Tax Rate (%)", 0.0, 15.0, 0.0, 0.5) / 100.0
        expense_growth_rate = st.number_input("Expense Growth > Inflation (%)", 0.0, 10.0, 0.0, 0.5) / 100.0
        savings_rate_override = st.slider("Force Savings Rate (%)", 0.0, 1.0, 0.0, 0.05)
        # Removed show_real from sidebar, moved to main dashboard area below
        
        st.markdown("---")
        st.markdown("**Early Withdrawal Taxes**")
        st.caption("Effective tax/penalty rate on withdrawals before age 60.")
        early_withdrawal_tax_rate = st.number_input("Early Tax Rate (%)", 0.0, 50.0, 10.0, 1.0) / 100.0

        st.markdown("---")
        st.markdown("**One-time Expenses**")
        use_kid = st.checkbox("Include Kids Expenses", True)
        if use_kid:
            k1, k2 = st.columns(2)
            kids_start_age = k1.number_input("Parent Age at First Kid", value=current_age+2)
            num_kids = k2.number_input("Number of Kids", value=2)
            kid_spacing = k1.number_input("Spacing (Years)", value=2)
            support_years = k2.number_input("Years of Support per Kid", value=22)
            annual_cost_per_kid_today = st.number_input("Cost/Kid/Yr ($)", value=6000)
        else:
            kids_start_age, num_kids, kid_spacing, support_years, annual_cost_per_kid_today = 0,0,0,0,0

        use_car = st.checkbox("Include Car Replacement", True)
        if use_car:
            c1, c2 = st.columns(2)
            car_cost_today = c1.number_input("Car Cost ($)", value=30000)
            first_car_age = c2.number_input("First Purchase Age", value=current_age+5)
            car_interval_years = c1.number_input("Replace Every (Yrs)", value=8)
        else:
            car_cost_today, first_car_age, car_interval_years = 0,0,0

    # --- DASHBOARD LAYOUT START ---
    st.markdown("---")
    sim_col, _ = st.columns([1, 2])
    
    # Define Controls that affect calculation/display (BEFORE calculation logic)
    with sim_col:
        c_check1, c_check2 = st.columns(2)
        with c_check1:
            show_real = st.checkbox("Show Real Dollars", True, help="Adjust all values for inflation")
        with c_check2:
            use_barista_mode = st.checkbox("Simulate Barista FIRE?", False, help="If checked, custom early retirement assumes Barista income.")

    # --- CALCULATION ENGINE ---
    # (Same logic as before, just processing the data)
    
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
    
    # NEW: Tracking specific expense buckets for the detailed chart
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
            years_from_now = y + 1
            price_nom = base_price * ((1 + home_app_rate) ** years_from_now) if y >= purchase_idx else 0.0
            home_price_by_year_full[y] = price_nom
            
            # Simple Equity Calc
            if loan <= 0 or np == 0:
                equity = price_nom if y >= purchase_idx else 0.0
            else:
                if y < purchase_idx: equity = 0.0
                else:
                    k = min((y - purchase_idx + 1) * 12, np)
                    outstanding = (loan * (1+mortgage_rate/12)**k - mp*((1+mortgage_rate/12)**k - 1)/(mortgage_rate/12)) if (mortgage_rate > 0 and k > 0) else max(loan - mp*k, 0.0)
                    if k >= np: outstanding = 0.0
                    equity = max(price_nom - outstanding, 0.0)
            home_equity_by_year_full[y] = equity
            
            # Maintenance
            if y >= purchase_idx:
                maint_cost = price_nom * maintenance_pct
                annual_expense_by_year_nominal_full[y] += maint_cost
                exp_housing_nominal[y] += maint_cost

    for y in range(years_full):
        annual_expense_by_year_nominal_full[y] += housing_adj_by_year_full[y]
        exp_housing_nominal[y] += housing_adj_by_year_full[y]

    # Full Simulation (Baseline)
    df_full = compound_schedule(
        start_balance_effective, years_full, monthly_contrib_by_year_full,
        annual_expense_by_year_nominal_full, annual_rate_by_year=annual_rates_by_year_full
    )
    df_full["Age"] = current_age + df_full["Year"] - 1
    df_full["Balance"] = df_full["Balance"] # Nominal
    
    # --- KPI CALCS ---
    coast_age, _, _, _ = compute_coast_fi_age(
        df_full, current_age, start_balance_effective, fi_annual_spend_today, 
        infl_rate, show_real, base_swr_30yr, retirement_age, annual_rates_by_year_full,
        early_withdrawal_tax_rate
    )
    fi_age_regular, fi_target_bal = compute_regular_fi_age(
        df_full, current_age, start_balance_effective, fi_annual_spend_today, 
        infl_rate, show_real, base_swr_30yr, retirement_age, annual_rates_by_year_full,
        early_withdrawal_tax_rate
    )
    barista_age, _ = compute_barista_fi_age(
        df_full, current_age, start_balance_effective, fi_annual_spend_today, barista_income_today, 
        infl_rate, show_real, base_swr_30yr, retirement_age, annual_rates_by_year_full,
        early_withdrawal_tax_rate
    )

    # --- EXTRA KPI: TRADITIONAL RETIREMENT OUTCOME ---
    # Find the row for 'retirement_age' to see what the pot looks like if you just keep working
    traditional_row = df_full[df_full["Age"] == retirement_age]
    traditional_balance_display = 0.0
    traditional_annual_income = 0.0
    
    if not traditional_row.empty:
        # Get nominal balance
        bal_nom = traditional_row.iloc[0]["Balance"]
        
        # Deflate if necessary
        if show_real and infl_rate > 0:
            years_passed = retirement_age - current_age
            infl_factor = (1 + infl_rate) ** years_passed
            traditional_balance_display = bal_nom / infl_factor
        else:
            traditional_balance_display = bal_nom
            
        # Calculate Safe annual income from that pot
        traditional_annual_income = traditional_balance_display * base_swr_30yr


    # --- TOP ROW: THE VERDICT (Populate Container) ---
    
    def render_card(col, title, value, desc, sub_value=None):
        sub_html = f"<div style='font-size:14px; font-weight:600; color:#2E7D32; margin-top:4px;'>{sub_value}</div>" if sub_value else ""
        
        # Use simple string concatenation to avoid IndentationError or Markdown code-block interpretation
        # This guarantees the HTML is treated as a flat string with no leading whitespace issues.
        html_content = (
            f'<div class="kpi-card">'
            f'<div class="kpi-title">{title}</div>'
            f'<div class="kpi-value">{value}</div>'
            f'{sub_html}'
            f'<div class="kpi-subtitle">{textwrap.shorten(desc, width=120, placeholder="...")}</div>'
            f'</div>'
        )
        
        with col:
            st.markdown(html_content, unsafe_allow_html=True)

    with kpi_container:
        # SECTION 1: EARLY RETIREMENT MILESTONES
        st.markdown('<div class="section-header">1. Early Retirement Milestones</div>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        
        val_reg = str(fi_age_regular) if fi_age_regular else "N/A"
        color_reg = "#0D47A1" if fi_age_regular else "#CC0000"
        render_card(col1, "Regular FIRE Age", f"<span style='color:{color_reg}'>{val_reg}</span>", f"Quit completely. Target: ${fi_target_bal:,.0f}.")

        val_bar = str(barista_age) if barista_age else "N/A"
        color_bar = "#0D47A1" if barista_age else "#CC0000"
        render_card(col2, "Barista FIRE Age", f"<span style='color:{color_bar}'>{val_bar}</span>", f"Switch to ${barista_income_today/1000:.0f}k job.")
        
        val_cst = str(coast_age) if coast_age else "N/A"
        color_cst = "#0D47A1" if coast_age else "#CC0000"
        render_card(col3, "Coast FIRE Age", f"<span style='color:{color_cst}'>{val_cst}</span>", f"Stop saving. Work to cover expenses only.")

        # SECTION 2: TRADITIONAL PATH
        st.markdown(f'<div class="section-header">2. Traditional Path (Working until Age {retirement_age})</div>', unsafe_allow_html=True)
        t_col1, t_col2 = st.columns(2)
        
        # Card 1: The Pot
        render_card(
            t_col1, 
            f"Total Nest Egg at Age {retirement_age}", 
            f"${traditional_balance_display:,.0f}", 
            "Projected portfolio balance if you continue working and contributing until full retirement age."
        )
        
        # Card 2: The Income
        render_card(
            t_col2, 
            f"Potential Annual Income", 
            f"${traditional_annual_income:,.0f} / yr", 
            f"Based on a {base_swr_30yr*100:.1f}% Safe Withdrawal Rate from your accumulated Nest Egg.",
            sub_value=f"(${traditional_annual_income/12:,.0f} / month)"
        )


    # --- MAIN VISUALIZATION CONTROLS ---
    
    # 1. Controller (Resume filling sim_col)
    with sim_col:
        # Custom Early Retirement Slider
        default_exit = fi_age_regular if fi_age_regular else 55
        custom_exit_age = st.slider("Select Custom Early Retirement Age", min_value=current_age+1, max_value=retirement_age, value=default_exit)
        
        # --- FIXED: Stable Selectbox Logic ---
        # We track the KEY (e.g. "Coast") rather than the descriptive string (e.g. "Coast FIRE (Age 45)")
        # This prevents the selection from resetting when the calculated age changes due to expense updates.
        
        scenario_keys = ["Work"]
        display_map = {"Work": "Work until Full Retirement"}
        
        if coast_age:
            scenario_keys.append("Coast")
            display_map["Coast"] = f"Coast FIRE (Age {coast_age})"
            
        if barista_age:
            scenario_keys.append("Barista")
            display_map["Barista"] = f"Barista FIRE (Age {barista_age})"
            
        scenario_keys.append("Custom")
        display_map["Custom"] = f"Custom Early Retirement (Age {custom_exit_age})"
        
        selected_key = st.selectbox(
            "Visualize Scenario:", 
            options=scenario_keys, 
            format_func=lambda x: display_map[x]
        )

    # 2. Logic for Scenario
    stop_age = retirement_age # Default
    is_coast, is_barista, is_early = False, False, False
    
    # Logic updated to match keys
    if selected_key == "Coast":
        stop_age = coast_age
        is_coast = True
    elif selected_key == "Barista":
        stop_age = barista_age
        is_barista = True
    elif selected_key == "Custom":
        stop_age = custom_exit_age
        if use_barista_mode:
            is_barista = True
        else:
            is_early = True
            
    # Update Label for Charts
    scenario_label = display_map[selected_key]

    # 3. Build Chart Data
    monthly_contrib_chart = []
    
    # We will rebuild the expense chart based on specific scenario logic
    # Start with the fixed expenses (Kids, Cars, Housing) calculated earlier
    annual_expense_chart = list(annual_expense_by_year_nominal_full) # Initializes with Kids/Cars/Housing
    
    # Data collectors for Detailed Table (Tab 4)
    detailed_income_active = []
    detailed_expense_total = []
    
    # Breakdown columns
    det_living_withdrawal = []
    det_tax_penalty = []
    det_kids = []
    det_cars = []
    det_housing = []
    det_total_portfolio_draw = []

    def to_nom(val, y_idx):
        return val * ((1+infl_rate)**(y_idx+1)) if (show_real and infl_rate > 0) else val

    # RE-CALC CHART EXPENSES TO INCLUDE EARLY TAX
    for y in range(years_full):
        age = current_age + y
        
        # 1. Contributions
        val = monthly_contrib_by_year_full[y] if age < stop_age else 0.0
        monthly_contrib_chart.append(val)
        
        # Initialize Detailed metrics for this year
        active_income_this_year = 0.0
        base_need = 0.0
        
        # 2. Retirement Phase Expenses
        if age >= stop_age:
            # Base spend need in this future year
            if is_coast:
                 # Coast: You earn enough to cover expenses
                 active_income_this_year = fi_annual_spend_today # Assumed you earn exactly what you spend
                 if age < retirement_age: 
                     base_need = 0.0 # Portfolio covers 0
                 else: 
                     base_need = fi_annual_spend_today * ((1+infl_rate)**(y+1))
                     active_income_this_year = 0.0 # Retired fully
            elif is_barista:
                 # Barista: You earn some, portfolio covers gap
                 if age < retirement_age:
                     active_income_this_year = barista_income_today
                     base_need = max(0, fi_annual_spend_today - barista_income_today) * ((1+infl_rate)**(y+1))
                 else:
                     base_need = fi_annual_spend_today * ((1+infl_rate)**(y+1))
                     active_income_this_year = 0.0
            elif is_early:
                 base_need = fi_annual_spend_today * ((1+infl_rate)**(y+1))
            else:
                 # Standard retirement
                 if age < retirement_age: base_need = 0.0
                 else: base_need = fi_annual_spend_today * ((1+infl_rate)**(y+1))

            # Net draw needed (Base Need)
            net_draw = base_need
            
            # Early Withdrawal Tax Gross-up (If needed)
            gross_withdrawal = net_draw
            tax_penalty_amount = 0.0
            
            if net_draw > 0:
                if age < 60 and early_withdrawal_tax_rate > 0:
                    gross_withdrawal = net_draw / (1.0 - early_withdrawal_tax_rate)
                    tax_penalty_amount = gross_withdrawal - net_draw
            
            # Apply to chart array (Additive to existing one-time expenses like cars/homes)
            # annual_expense_chart[y] already contains Kids + Cars + Housing from initialization
            annual_expense_chart[y] += gross_withdrawal
            
            # Total expense for table is what you actually spent + taxes, roughly approximated by draw + active income
            detailed_expense_total.append(gross_withdrawal + to_nom(active_income_this_year, y))
            detailed_income_active.append(to_nom(active_income_this_year, y))
            
            # Store breakdown
            det_living_withdrawal.append(net_draw)
            det_tax_penalty.append(tax_penalty_amount)
            # Total draw = Housing + Kids + Cars + Living + Tax
            # Housing/Kids/Cars are in the pre-filled annual_expense_chart but we have them in separate lists too
            # Wait, annual_expense_chart[y] WAS initialized with exp_kids + exp_cars + exp_housing.
            # We just added gross_withdrawal (which is Living + Tax).
            # So annual_expense_chart[y] IS the total portfolio draw.
            det_total_portfolio_draw.append(annual_expense_chart[y])

        else:
            # Working Phase
            # In working phase, expense is handled implicitly by savings rate in 'df_income' 
            # But 'annual_expense_chart' tracks EXTRA expenses (kids/homes).
            # We'll just log 0 for portfolio draw in accumulation phase
            det_total_portfolio_draw.append(annual_expense_chart[y]) # Just the extra expenses
            detailed_income_active.append(0.0) 
            detailed_expense_total.append(annual_expense_chart[y])
            det_living_withdrawal.append(0.0)
            det_tax_penalty.append(0.0)

        # Append specific expenses
        det_kids.append(exp_kids_nominal[y])
        det_cars.append(exp_cars_nominal[y])
        det_housing.append(exp_housing_nominal[y])

    # 4. Generate Chart DF
    df_chart = compound_schedule(
        start_balance_effective, years_full, monthly_contrib_chart,
        annual_expense_chart, annual_rate_by_year=annual_rates_by_year_full
    )
    df_chart["Age"] = current_age + df_chart["Year"]
    df_chart["HomeEquity"] = home_equity_by_year_full
    df_chart["NetWorth"] = df_chart["Balance"] + df_chart["HomeEquity"]
    
    # Append detailed columns for Tab 4 (Nominal at this stage)
    df_chart["ScenarioActiveIncome"] = detailed_income_active
    df_chart["TotalPortfolioDraw"] = det_total_portfolio_draw
    df_chart["LivingWithdrawal"] = det_living_withdrawal
    df_chart["TaxPenalty"] = det_tax_penalty
    df_chart["KidCost"] = det_kids
    df_chart["CarCost"] = det_cars
    df_chart["HomeCost"] = det_housing

    # Real Adjustment
    if show_real and infl_rate > 0:
        df_chart["DF"] = (1+infl_rate)**df_chart["Year"]
        # Standard Cols
        for c in ["Balance", "HomeEquity", "NetWorth", "AnnualExpense"]:
            df_chart[c] /= df_chart["DF"]
        # Breakdown Cols
        for c in ["ScenarioActiveIncome", "TotalPortfolioDraw", "LivingWithdrawal", "TaxPenalty", "KidCost", "CarCost", "HomeCost", "InvestGrowthYear"]:
            df_chart[c] /= df_chart["DF"]

    # 5. Plot
    plot_end = retirement_age
    # If using custom stop logic (like is_early), we cap at retirement_age to avoid overshoot unless early is actually later (unlikely)
    
    df_p = df_chart[df_chart["Age"] <= plot_end].reset_index(drop=True)
    
    fig = go.Figure()
    # Main Balance (Stacked Bar)
    fig.add_trace(go.Bar(
        x=df_p["Age"], y=df_p["Balance"], 
        name="Invested Assets",
        marker_color='rgba(58, 110, 165, 0.8)', # Strong Blue
        hovertemplate="$%{y:,.0f}"
    ))
    # Home Equity (Stacked Bar)
    fig.add_trace(go.Bar(
        x=df_p["Age"], y=df_p["HomeEquity"], 
        name="Home Equity",
        marker_color='rgba(167, 173, 178, 0.5)', # Grey
        hovertemplate="$%{y:,.0f}"
    ))
    
    # Add Millionaire Milestone Dot
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
    
    # Final Number Annotation
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
    
    # Target Line
    target_val = fi_target_bal
    if show_real and infl_rate > 0: target_val = fi_annual_spend_today / base_swr_30yr
    
    # Visual Polish
    fig.update_layout(
        title="Net Worth Projection",
        xaxis_title="Age", yaxis_title="Value ($)",
        barmode='stack',
        hovermode="x unified",
        legend=dict(orientation="h", y=1.02, x=0.01),
        margin=dict(l=20, r=20, t=40, b=20),
        height=400,
        yaxis=dict(tickformat=",.0f")
    )
    
    st.plotly_chart(fig, use_container_width=True)

    # --- TABS FOR DETAILS ---
    tab1, tab2, tab3, tab4 = st.tabs(["Risk Analysis", "Cash Flow Details", "Audit Table", "Detailed Schedule"])
    
    with tab1:
        st.caption("How market volatility (+/- 1% annual return) impacts your outcome.")
        # Pre-calc scenarios
        rates_bear = [r - 0.01 for r in annual_rates_by_year_full]
        rates_bull = [r + 0.01 for r in annual_rates_by_year_full]
        
        df_bear = compound_schedule(start_balance_effective, years_full, monthly_contrib_chart, annual_expense_chart, annual_rate_by_year=rates_bear)
        df_bull = compound_schedule(start_balance_effective, years_full, monthly_contrib_chart, annual_expense_chart, annual_rate_by_year=rates_bull)
        
        # Add home equity & adjust real
        for df_ in [df_bear, df_bull]:
            df_["Age"] = current_age + df_["Year"]
            df_["NW"] = df_["Balance"] + home_equity_by_year_full
            if show_real and infl_rate > 0:
                df_["NW"] /= ((1+infl_rate)**df_["Year"])
        
        # Plot Cone
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
            st.markdown("**Income vs Expenses (Real)**")
            fig_i = go.Figure()
            # ADDED GROSS INCOME TRACE
            fig_i.add_trace(go.Scatter(x=df_income["Age"], y=df_income["IncomeRealBeforeTax"], name="Gross Income", line=dict(color="#90A4AE", dash="dot"), hovertemplate="$%{y:,.0f}"))
            fig_i.add_trace(go.Scatter(x=df_income["Age"], y=df_income["IncomeRealAfterTax"], name="Net Income", line=dict(color="#66BB6A"), hovertemplate="$%{y:,.0f}"))
            fig_i.add_trace(go.Scatter(x=df_income["Age"], y=df_income["ExpensesReal"], name="Expenses", line=dict(color="#EF5350"), hovertemplate="$%{y:,.0f}"))
            fig_i.update_layout(height=250, margin=dict(t=20, b=20, l=20, r=20), yaxis=dict(tickformat=",.0f"))
            st.plotly_chart(fig_i, use_container_width=True)
        with c2:
            st.markdown("**Investment Returns Glide Path**")
            fig_r = go.Figure()
            pcts = [r*100 for r in annual_rates_by_year_full]
            fig_r.add_trace(go.Scatter(x=df_p["Age"], y=pcts[:len(df_p)], mode='lines', name="Return %", hovertemplate="%{y:.1f}%"))
            fig_r.update_layout(height=250, margin=dict(t=20, b=20, l=20, r=20), yaxis_title="% Return", yaxis=dict(tickformat=".1f"))
            st.plotly_chart(fig_r, use_container_width=True)

        st.markdown("**Savings Rate Over Time**")
        fig_s = go.Figure()
        fig_s.add_trace(go.Scatter(
            x=df_income["Age"], 
            y=df_income["SavingsRate"] * 100, # Convert to % for display if stored as decimal
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
        st.write("Detailed yearly breakdown.")
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
        st.markdown("**Scenario Detail: " + scenario_label + "**")
        st.caption("Breakdown of withdrawals. 'LivingWithdrawal' matches your Retirement Spend input. 'TotalPortfolioDraw' includes taxes and one-time costs.")
        
        # Prepare table data
        format_dict_d = {
            "Balance": "${:,.0f}",
            "NetWorth": "${:,.0f}",
            "LivingWithdrawal": "${:,.0f}",
            "TaxPenalty": "${:,.0f}",
            "KidCost": "${:,.0f}",
            "CarCost": "${:,.0f}",
            "HomeCost": "${:,.0f}",
            "TotalPortfolioDraw": "${:,.0f}",
            "ScenarioActiveIncome": "${:,.0f}",
            "InvestGrowthYear": "${:,.0f}",
            "AnnualRate": "{:.2%}",
            "Age": "{:.0f}"
        }
        
        # Filter to relevant columns
        cols = [
            "Age", 
            "AnnualRate",
            "InvestGrowthYear",
            "LivingWithdrawal", 
            "TaxPenalty", 
            "KidCost", 
            "CarCost", 
            "HomeCost",
            "TotalPortfolioDraw",
            "ScenarioActiveIncome",
            "Balance"
        ]
        
        st.dataframe(
            df_p[cols].style.format(format_dict_d),
            use_container_width=True,
            hide_index=True
        )

if __name__ == "__main__":
    main()
