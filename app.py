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
):
    """
    Simulate investment account with monthly compounding and annual expenses.

    - monthly_contrib_by_year: list length = years, monthly contribution for each year
    - annual_expense_by_year:  list length = years, annual expense taken at year-end
    - annual_rate: single annual nominal rate (if annual_rate_by_year is None)
    - annual_rate_by_year: list length = years with annual nominal rate for each year
    """
    if annual_rate_by_year is not None and len(annual_rate_by_year) != years:
        raise ValueError("annual_rate_by_year length must equal 'years'")

    balance = start_balance
    cum_contrib = 0.0
    cum_invest_growth = 0.0
    cum_expense_drag = 0.0
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

        for _ in range(m):
            monthly_contrib = monthly_contrib_by_year[year_idx]
            balance += monthly_contrib
            cum_contrib += monthly_contrib
            contrib_year += monthly_contrib

            growth_month = balance * (r / m)
            balance += growth_month

        balance_before_expense = balance
        annual_expense = annual_expense_by_year[year_idx]

        market_growth_year = balance_before_expense - (balance_start_year + contrib_year)
        cum_invest_growth += market_growth_year

        expense_drag_year = -annual_expense
        cum_expense_drag += expense_drag_year

        balance = balance_before_expense - annual_expense
        cum_expense_abs += annual_expense

        net_growth_cum = cum_invest_growth + cum_expense_drag

        rows.append(
            {
                "Year": year_idx + 1,
                "Balance": balance,
                "CumContributions": cum_contrib,
                "ContribYear": contrib_year,
                "InvestGrowth": cum_invest_growth,
                "InvestGrowthYear": market_growth_year,
                "ExpenseDrag": cum_expense_drag,
                "NetGrowth": net_growth_cum,
                "AnnualExpense": annual_expense,
                "CumulativeExpense": cum_expense_abs,
            }
        )

    return pd.DataFrame(rows)


# =========================================================
# FI helper functions
# =========================================================
def adjusted_swr_for_horizon(horizon_years, base_30yr_swr=0.04):
    horizon_years = max(horizon_years, 1)
    raw = base_30yr_swr * (30.0 / horizon_years) ** 0.5
    return max(0.025, min(0.05, raw))


def compute_fi_age_horizon(
    df,
    fi_annual_spend_today,
    infl_rate,
    show_real,
    base_30yr_swr,
    horizon_end_age=90,
):
    if fi_annual_spend_today <= 0 or base_30yr_swr <= 0:
        return None, None, None, None, None

    fi_age = None
    fi_portfolio = None
    fi_required = None
    eff_swr = None
    horizon_years = None

    for row in df.itertuples():
        age = row.Age
        year = row.Year
        balance = row.Balance

        if age >= horizon_end_age:
            continue

        T = max(horizon_end_age - age, 1)
        swr = adjusted_swr_for_horizon(T, base_30yr_swr=base_30yr_swr)
        multiple = 1.0 / swr

        if show_real and infl_rate > 0:
            required = fi_annual_spend_today * multiple
        else:
            required = fi_annual_spend_today * ((1 + infl_rate) ** year) * multiple

        if balance >= required:
            fi_age = int(age)
            fi_portfolio = balance
            fi_required = required
            eff_swr = swr
            horizon_years = T
            break

    return fi_age, fi_portfolio, fi_required, eff_swr, horizon_years


def compute_barista_fi_age_bridge(
    df,
    current_age,
    fi_annual_spend_today,
    barista_income_today,
    infl_rate,
    show_real,
    annual_rates_by_year_full,
    base_30yr_swr,
    barista_end_age,
    full_fi_age,
    tax_rate_bridge=0.0,
    extra_health_today=0.0,
):
    """
    Bridge-to-FI model at full_fi_age using a fixed SWR (base_30yr_swr).
    """
    S = fi_annual_spend_today
    B = barista_income_today

    if S <= 0 or base_30yr_swr <= 0:
        return None, None, None, None, None, None

    t = max(0.0, min(tax_rate_bridge, 0.7))

    balance_real_by_age = {}
    for row in df.itertuples():
        age = row.Age
        year = row.Year
        bal = row.Balance

        if show_real and infl_rate > 0:
            bal_real = bal
        else:
            if infl_rate > 0:
                bal_real = bal / ((1 + infl_rate) ** year)
            else:
                bal_real = bal

        balance_real_by_age[age] = bal_real

    fi_target_real = S / base_30yr_swr

    start_age_candidate = current_age + 1
    if start_age_candidate >= full_fi_age:
        return None, None, None, None, None, None

    effective_barista_end_age = min(barista_end_age, full_fi_age - 1)
    if effective_barista_end_age < start_age_candidate:
        return None, None, None, None, None, None

    best_barista_age = None
    bal_start_best = None
    bal_full_fi_best = None
    pv_bridge_need_best = None

    for age0 in range(start_age_candidate, full_fi_age + 1):
        if age0 not in balance_real_by_age:
            continue

        bal = balance_real_by_age[age0]
        bal_start_age = bal
        ok = True

        pv_bridge_need = 0.0
        disc_factor = 1.0

        for age in range(age0, full_fi_age):
            idx = age - current_age
            if idx < 0 or idx >= len(annual_rates_by_year_full):
                ok = False
                break

            r_nominal = annual_rates_by_year_full[idx]
            if infl_rate > 0:
                real_return = (1 + r_nominal) / (1 + infl_rate) - 1
            else:
                real_return = r_nominal

            if age <= effective_barista_end_age:
                spend_from_portfolio = max(S - B, 0.0)
            else:
                spend_from_portfolio = S

            total_real_spend = spend_from_portfolio + max(extra_health_today, 0.0)
            pv_bridge_need += total_real_spend / disc_factor

            if t > 0:
                gross_withdrawal = total_real_spend / (1 - t)
            else:
                gross_withdrawal = total_real_spend

            bal -= gross_withdrawal
            if bal < 0:
                ok = False
                break

            bal *= (1 + real_return)
            disc_factor *= (1 + real_return)

        if not ok:
            continue

        if bal >= fi_target_real:
            best_barista_age = age0
            bal_start_best = bal_start_age
            bal_full_fi_best = bal
            pv_bridge_need_best = pv_bridge_need
            break

    if best_barista_age is None:
        return None, None, None, None, None, None

    years_bridge = full_fi_age - best_barista_age
    return (
        best_barista_age,
        bal_start_best,
        bal_full_fi_best,
        fi_target_real,
        years_bridge,
        pv_bridge_need_best,
    )


# =========================================================
# Tax model (federal + FICA + optional state)
# =========================================================
def federal_tax_single_approx(income):
    """Approximate US federal income tax for a single filer, no deductions."""
    if income <= 0:
        return 0.0

    # Rough 2024-ish brackets
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
        if income <= lower:
            break
        span = min(income, upper) - lower
        if span > 0:
            tax += span * rate
        if income <= upper:
            break

    if income > brackets[-1][1]:
        tax += (income - brackets[-1][1]) * top_rate

    return max(tax, 0.0)


def total_tax_on_earned(income, state_tax_rate):
    """
    Total tax on earned income:
      - Federal income tax (approx)
      - Social Security (6.2% up to wage base)
      - Medicare (1.45% on all wages)
      - Flat state income tax (user input)
    """
    if income <= 0:
        return 0.0

    federal = federal_tax_single_approx(income)

    ss_wage_base = 168600.0
    ss_rate = 0.062
    medicare_rate = 0.0145

    ss_tax = ss_rate * min(income, ss_wage_base)
    medicare_tax = medicare_rate * income
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
):
    """
    Build a per-year income / expense / investable schedule.
    Returns values in real (today's) dollars if show_real=True, otherwise nominal.
    """
    years = retirement_age - current_age
    rows = []

    for y in range(years):
        age = current_age + y

        income_nominal = start_income * ((1 + income_growth_rate) ** y)

        if show_real and infl_rate > 0:
            df_y = (1 + infl_rate) ** y
            income_real = income_nominal / df_y
        else:
            income_real = income_nominal

        tax_real = total_tax_on_earned(income_real, state_tax_rate)
        after_tax_income_real = max(income_real - tax_real, 0.0)

        expense_real_base = expense_today * ((1 + expense_growth_rate) ** y)

        if savings_rate_override > 0:
            investable_real = after_tax_income_real * savings_rate_override
            implied_expense_real = after_tax_income_real - investable_real
        else:
            implied_expense_real = expense_real_base
            investable_real = max(after_tax_income_real - implied_expense_real, 0.0)

        if after_tax_income_real > 0:
            savings_rate_actual = investable_real / after_tax_income_real
        else:
            savings_rate_actual = 0.0

        rows.append(
            {
                "YearIndex": y,
                "Age": age,
                "IncomeRealBeforeTax": income_real,
                "TaxReal": tax_real,
                "IncomeRealAfterTax": after_tax_income_real,
                "ExpensesReal": implied_expense_real,
                "InvestableRealAnnual": investable_real,
                "InvestableRealMonthly": investable_real / 12.0,
                "SavingsRate": savings_rate_actual,
            }
        )

    return pd.DataFrame(rows)


# =========================================================
# Glide path
# =========================================================
def glide_path_return(age, base_return):
    if age <= 35:
        return base_return + 0.01
    elif age <= 45:
        return base_return + 0.005
    elif age <= 55:
        return base_return
    elif age <= 65:
        return base_return - 0.01
    else:
        return base_return - 0.015


# =========================================================
# Main app
# =========================================================
def main():
    st.set_page_config(page_title="Personal FI Planner", layout="wide")
    st.title("Personal FI Planner")

    st.sidebar.header("Core inputs")

    current_age = st.sidebar.number_input(
        "Current age (years)", value=26, min_value=0, max_value=100, step=1
    )

    retirement_age_input = st.sidebar.number_input(
        "Traditional FI age (years – when you stop all work)",
        value=60,
        min_value=1,
        max_value=100,
        step=1,
    )

    max_sim_age = 90
    retirement_age = min(retirement_age_input, max_sim_age)

    years_plot = retirement_age - current_age
    if years_plot <= 0:
        st.error(
            "Traditional FI age must be greater than current age and below the FI horizon (90)."
        )
        return

    start_balance_input = st.sidebar.number_input(
        "Starting total investment balance ($)",
        value=100000,
        step=1000,
        min_value=0,
    )

    annual_rate_base = (
        st.sidebar.slider(
            "Annual return (adjusts closer to retirement) (%/yr, nominal)",
            min_value=0.0,
            max_value=20.0,
            value=8.0,
            step=0.5,
        )
        / 100.0
    )

    infl_rate = (
        st.sidebar.number_input(
            "Assumed annual inflation (%/yr)",
            value=3.0,
            step=0.1,
            min_value=0.0,
            max_value=20.0,
        )
        / 100.0
    )

    show_real = st.sidebar.checkbox(
        "Show values in today's dollars (inflation-adjusted)", value=True
    )

    # Income & expenses
    st.sidebar.markdown("---")
    st.sidebar.subheader("Income & expenses")

    start_income = st.sidebar.number_input(
        "Current pre-tax income ($/yr)",
        value=90000,
        step=5000,
        min_value=0,
        key="start_income",
    )

    income_growth_rate = (
        st.sidebar.number_input(
            "Income growth (%/yr)",
            value=3.0,
            step=0.5,
            min_value=0.0,
            max_value=20.0,
            key="income_growth",
        )
        / 100.0
    )

    state_tax_rate = (
        st.sidebar.number_input(
            "State income tax rate (% of income)",
            value=0.0,
            step=0.5,
            min_value=0.0,
            max_value=20.0,
            key="state_tax_rate",
        )
        / 100.0
    )

    expense_today = st.sidebar.number_input(
        "Current total expenses (per year, today's dollars)",
        value=36000,
        step=1000,
        min_value=0,
        key="expense_today",
    )

    expense_growth_rate = (
        st.sidebar.number_input(
            "Expense growth (%/yr above inflation)",
            value=0.0,
            step=0.5,
            min_value=0.0,
            max_value=20.0,
            key="expense_growth",
        )
        / 100.0
    )

    savings_rate_override = (
        st.sidebar.slider(
            "Optional savings rate (% of after-tax income, overrides explicit expenses if > 0)",
            min_value=0.0,
            max_value=80.0,
            value=0.0,
            step=1.0,
            key="savings_rate_override",
        )
        / 100.0
    )

    # Additional customization (home, kids, cars)
    st.sidebar.markdown("---")
    st.sidebar.subheader("Additional customization")
    st.sidebar.subheader("Home")

    include_home = st.sidebar.checkbox("Include home in plan", key="home_toggle")

    current_rent = st.sidebar.number_input(
        "Current rent ($/month – only needed if buying or upgrading home)",
        value=1100,
        step=50,
        min_value=0,
    )

    est_prop_tax_monthly = st.sidebar.number_input(
        "Estimated property tax + insurance ($/month at purchase)",
        value=300,
        step=50,
        min_value=0,
    )

    home_status = None
    home_app_rate = 0.0
    maintenance_pct = 0.0
    home_price_today = 0.0
    current_home_value_today = 0.0
    planned_purchase_age = current_age
    down_payment_pct = 0.0
    mortgage_rate = 0.0
    mortgage_term_years = 30
    years_remaining_loan = 0
    equity_amount_now = 0.0
    mortgage_payment = 0.0
    purchase_idx = 10**9
    loan_amount = 0.0
    n_payments = 0
    r_m = 0.0

    if include_home:
        home_app_rate = (
            st.sidebar.number_input(
                "Home appreciation (%/yr)",
                value=3.0,
                step=0.1,
                min_value=-10.0,
                max_value=20.0,
                key="home_app_rate",
            )
            / 100.0
        )

        maintenance_pct = (
            st.sidebar.number_input(
                "Annual maintenance (% of home value)",
                value=1.0,
                step=0.1,
                min_value=0.0,
                max_value=10.0,
                key="maint_pct",
            )
            / 100.0
        )

        home_status = st.sidebar.radio(
            "Home status",
            ["I already own a home", "I plan to buy"],
            index=0,
            key="home_status",
        )

        if home_status == "I already own a home":
            current_home_value_today = st.sidebar.number_input(
                "Current home value ($, today's)",
                value=400000,
                step=10000,
                min_value=0,
                key="home_value_now",
            )

            equity_amount_now = st.sidebar.number_input(
                "Current home equity you own ($)",
                value=120000,
                step=10000,
                min_value=0,
                key="equity_amount_now",
            )

            years_remaining_loan = st.sidebar.number_input(
                "Years remaining on mortgage",
                value=25,
                min_value=0,
                max_value=40,
                step=1,
                key="years_remaining_loan",
            )

            mortgage_rate = (
                st.sidebar.number_input(
                    "Mortgage interest rate (%/yr)",
                    value=6.5,
                    step=0.1,
                    min_value=0.0,
                    max_value=20.0,
                    key="mort_rate_own",
                )
                / 100.0
            )

        else:
            home_price_today = st.sidebar.number_input(
                "Target home price ($, today's)",
                value=400000,
                step=10000,
                min_value=0,
                key="target_home_price",
            )
            planned_purchase_age = st.sidebar.number_input(
                "Planned purchase age (years)",
                value=current_age,
                min_value=current_age,
                max_value=max_sim_age,
                step=1,
                key="purchase_age",
            )
            down_payment_pct = (
                st.sidebar.number_input(
                    "Down payment (% of price)",
                    value=20.0,
                    min_value=0.0,
                    max_value=100.0,
                    step=1.0,
                    key="dp_pct",
                )
                / 100.0
            )

            mortgage_rate = (
                st.sidebar.number_input(
                    "Mortgage interest rate (%/yr)",
                    value=6.5,
                    step=0.1,
                    min_value=0.0,
                    max_value=20.0,
                    key="mort_rate_buy",
                )
                / 100.0
            )

            mortgage_term_years = st.sidebar.radio(
                "Loan term (years)",
                [15, 30],
                index=1,
                key="mort_term",
            )

    st.sidebar.markdown("---")
    st.sidebar.subheader("Future expenses (today's $)")

    use_kid_expenses = st.sidebar.checkbox("Add kid-related annual expenses", key="kid_exp")

    if use_kid_expenses:
        default_kid_start = current_age + 2
        default_kid_end = min(retirement_age, default_kid_start + 18)

        kids_start_age = st.sidebar.number_input(
            "Kid expense start age (years)",
            value=default_kid_start,
            min_value=current_age + 1,
            max_value=retirement_age,
            step=1,
            key="kids_start_age",
        )
        kids_end_age = st.sidebar.number_input(
            "Kid expense end age (years)",
            value=default_kid_end,
            min_value=kids_start_age,
            max_value=retirement_age,
            step=1,
            key="kids_end_age",
        )
        num_kids = st.sidebar.number_input(
            "Number of kids",
            value=2,
            min_value=1,
            max_value=10,
            step=1,
            key="num_kids",
        )
        annual_cost_per_kid_today = st.sidebar.number_input(
            "Annual cost per kid ($/yr, today's)",
            value=10000,
            step=1000,
            min_value=0,
            key="kid_cost",
        )
    else:
        kids_start_age = kids_end_age = num_kids = annual_cost_per_kid_today = None

    use_car_expenses = st.sidebar.checkbox("Add car replacement expenses", key="car_exp")

    if use_car_expenses:
        car_cost_today = st.sidebar.number_input(
            "Cost per car ($, today's)",
            value=30000,
            step=1000,
            min_value=0,
            key="car_cost",
        )
        first_car_age = st.sidebar.number_input(
            "First replacement age (years)",
            value=current_age + 5,
            min_value=current_age + 1,
            max_value=retirement_age,
            step=1,
            key="first_car_age",
        )
        car_interval_years = st.sidebar.number_input(
            "Replacement interval (years)",
            value=8,
            min_value=1,
            max_value=50,
            step=1,
            key="car_interval",
        )
    else:
        car_cost_today = first_car_age = car_interval_years = None

    # FI / Barista FIRE settings moved to sidebar
    st.sidebar.markdown("---")
    st.sidebar.subheader("FI / Barista FIRE settings")

    fi_annual_spend_today = st.sidebar.number_input(
        "Target annual spending in FI ($/yr, today's)",
        value=60000,
        step=5000,
        min_value=0,
        key="fi_spend",
    )

    base_swr_30yr = (
        st.sidebar.number_input(
            "Base safe withdrawal rate (% for ~30 yrs)",
            value=4.0,
            min_value=1.0,
            max_value=10.0,
            step=0.5,
            key="swr_base",
        )
        / 100.0
    )

    st.sidebar.caption(
        "FI age is computed using your portfolio path from now to age 90. "
        "The traditional FI age slider only controls when contributions stop "
        "and how far the main chart extends."
    )

    use_barista = st.sidebar.checkbox(
        "Enable Barista FIRE bridge scenario",
        value=False,
        key="barista_toggle",
    )

    barista_income_today = 0.0
    barista_end_age = retirement_age
    barista_tax_rate_bridge = 0.0
    extra_health_today = 0.0

    if use_barista:
        barista_income_today = st.sidebar.number_input(
            "Expected part-time income during bridge ($/yr, today's)",
            value=50000,
            step=5000,
            min_value=0,
            key="barista_income",
        )

        extra_health_today = st.sidebar.number_input(
            "Extra health insurance cost during bridge ($/yr, today's)",
            value=8000,
            step=1000,
            min_value=0,
            key="barista_health",
        )

        barista_tax_rate_bridge = (
            st.sidebar.number_input(
                "Effective tax rate on portfolio withdrawals during bridge (%)",
                value=20.0,
                min_value=0.0,
                max_value=70.0,
                step=1.0,
                key="barista_tax_rate",
            )
            / 100.0
        )

        min_end_age = current_age + 1
        max_end_age = retirement_age
        default_end_age = min(max(65, min_end_age), max_end_age)

        barista_end_age = st.sidebar.number_input(
            "Latest age you might still work part-time",
            value=default_end_age,
            min_value=min_end_age,
            max_value=max_end_age,
            step=1,
            key="barista_end_age",
        )

    # Income schedule (after all taxes)
    df_income = build_income_schedule(
        current_age=current_age,
        retirement_age=retirement_age,
        start_income=start_income,
        income_growth_rate=income_growth_rate,
        expense_today=expense_today,
        expense_growth_rate=expense_growth_rate,
        infl_rate=infl_rate,
        savings_rate_override=savings_rate_override,
        show_real=show_real,
        state_tax_rate=state_tax_rate,
    )

    # Full-horizon schedules
    years_full = max_sim_age - current_age

    annual_rates_by_year_full = []
    for y in range(years_full):
        age = current_age + y
        annual_rates_by_year_full.append(glide_path_return(age, annual_rate_base))

    # ---- FIXED LOGIC: contributions always nominal in simulation ----
    monthly_contrib_by_year_full = []
    for y in range(years_full):
        age = current_age + y
        if age < retirement_age and y < len(df_income):
            contrib_month_real = df_income.loc[y, "InvestableRealMonthly"]
            if show_real and infl_rate > 0:
                # df_income is real → convert to nominal for simulation
                val = contrib_month_real * ((1 + infl_rate) ** y)
            else:
                # df_income already nominal
                val = contrib_month_real
        else:
            val = 0.0
        monthly_contrib_by_year_full.append(val)

    annual_expense_by_year_nominal_full = [0.0 for _ in range(years_full)]
    home_price_by_year_full = [0.0 for _ in range(years_full)]
    home_equity_by_year_full = [0.0 for _ in range(years_full)]
    housing_adj_by_year_full = [0.0 for _ in range(years_full)]

    start_balance_effective = start_balance_input

    # Kids
    for year_idx in range(years_full):
        age_end_of_year = current_age + year_idx + 1
        if use_kid_expenses:
            if kids_start_age <= age_end_of_year <= kids_end_age:
                expense_real = num_kids * annual_cost_per_kid_today
                expense_nominal = expense_real * ((1 + infl_rate) ** (year_idx + 1))
                annual_expense_by_year_nominal_full[year_idx] += expense_nominal

    # Cars
    for year_idx in range(years_full):
        age_end_of_year = current_age + year_idx + 1
        if (
            use_car_expenses
            and car_interval_years
            and car_interval_years > 0
            and first_car_age is not None
        ):
            if age_end_of_year >= first_car_age:
                if (age_end_of_year - first_car_age) % car_interval_years == 0:
                    expense_real = car_cost_today
                    expense_nominal = expense_real * ((1 + infl_rate) ** (year_idx + 1))
                    annual_expense_by_year_nominal_full[year_idx] += expense_nominal

    # Home
    if include_home:
        if home_status == "I already own a home":
            base_price_today = current_home_value_today
            purchase_idx = 0

            outstanding_now = max(base_price_today - equity_amount_now, 0.0)
            loan_amount = outstanding_now

            if years_remaining_loan > 0 and loan_amount > 0:
                r_m = mortgage_rate / 12.0
                n_payments = years_remaining_loan * 12
                if r_m > 0:
                    mortgage_payment = loan_amount * r_m / (1 - (1 + r_m) ** (-n_payments))
                else:
                    mortgage_payment = loan_amount / n_payments
            else:
                r_m = 0.0
                n_payments = 0
                mortgage_payment = 0.0

            purchase_price_nominal = base_price_today

        else:
            base_price_today = home_price_today
            purchase_idx = max(0, planned_purchase_age - current_age - 1)
            years_until_purchase = purchase_idx + 1

            purchase_price_nominal = base_price_today * (
                (1 + home_app_rate) ** years_until_purchase
            )
            loan_amount = purchase_price_nominal * (1.0 - down_payment_pct)

            r_m = mortgage_rate / 12.0
            n_payments = mortgage_term_years * 12
            if n_payments > 0 and loan_amount > 0:
                if r_m > 0:
                    mortgage_payment = loan_amount * r_m / (1 - (1 + r_m) ** (-n_payments))
                else:
                    mortgage_payment = loan_amount / n_payments
            else:
                mortgage_payment = 0.0
                r_m = 0.0
                n_payments = 0

        for year_idx in range(years_full):
            years_from_now = year_idx + 1
            price_nominal = base_price_today * ((1 + home_app_rate) ** years_from_now)

            if year_idx >= purchase_idx:
                home_price_by_year_full[year_idx] = price_nominal
            else:
                home_price_by_year_full[year_idx] = 0.0

            if loan_amount <= 0 or n_payments == 0:
                if year_idx >= purchase_idx:
                    home_equity_by_year_full[year_idx] = price_nominal
                else:
                    home_equity_by_year_full[year_idx] = 0.0
            else:
                if year_idx < purchase_idx:
                    home_equity_by_year_full[year_idx] = 0.0
                else:
                    years_since_purchase = year_idx - purchase_idx + 1
                    k = min(years_since_purchase * 12, n_payments)

                    if k == 0:
                        outstanding = loan_amount
                    else:
                        if r_m > 0:
                            outstanding = (
                                loan_amount * (1 + r_m) ** k
                                - mortgage_payment * ((1 + r_m) ** k - 1) / r_m
                            )
                        else:
                            outstanding = max(loan_amount - mortgage_payment * k, 0.0)

                    if k >= n_payments:
                        outstanding = 0.0

                    equity = max(price_nominal - outstanding, 0.0)
                    home_equity_by_year_full[year_idx] = equity

            if year_idx >= purchase_idx:
                maint_nominal = price_nominal * maintenance_pct
                annual_expense_by_year_nominal_full[year_idx] += maint_nominal

        if home_status == "I plan to buy":
            if purchase_idx < years_full:
                down_payment_nominal = purchase_price_nominal * down_payment_pct

                if planned_purchase_age == current_age:
                    start_balance_effective = max(
                        0.0, start_balance_effective - down_payment_nominal
                    )
                else:
                    annual_expense_by_year_nominal_full[purchase_idx] += down_payment_nominal

    if include_home and home_status == "I plan to buy" and mortgage_payment > 0:
        total_monthly_owner_cost = mortgage_payment + est_prop_tax_monthly
        extra_housing_monthly = total_monthly_owner_cost - current_rent
        for year_idx in range(years_full):
            if year_idx >= purchase_idx:
                housing_adj_by_year_full[year_idx] = extra_housing_monthly * 12

    for y in range(years_full):
        annual_expense_by_year_nominal_full[y] += housing_adj_by_year_full[y]

    df_full = compound_schedule(
        start_balance=start_balance_effective,
        years=years_full,
        monthly_contrib_by_year=monthly_contrib_by_year_full,
        annual_expense_by_year=annual_expense_by_year_nominal_full,
        annual_rate_by_year=annual_rates_by_year_full,
    )

    df_full["Age"] = current_age + df_full["Year"]
    df_full["HomePrice"] = home_price_by_year_full
    df_full["HomeEquity"] = home_equity_by_year_full
    df_full["NetWorth"] = df_full["Balance"] + df_full["HomeEquity"]
    df_full["HousingDelta"] = housing_adj_by_year_full
    df_full["NetContributions"] = df_full["CumContributions"] + df_full["ExpenseDrag"]

    if show_real and infl_rate > 0:
        df_full["DF_end"] = (1 + infl_rate) ** df_full["Year"]
        df_full["DF_mid"] = (1 + infl_rate) ** (df_full["Year"] - 1)

        for col in [
            "Balance",
            "InvestGrowth",
            "InvestGrowthYear",
            "HomePrice",
            "HomeEquity",
            "NetWorth",
        ]:
            df_full[col] = df_full[col] / df_full["DF_end"]

        cum_contrib_real = 0.0
        cum_expense_drag_real = 0.0
        cum_expense_abs_real = 0.0
        net_contrib_cum_real = 0.0

        for idx in range(len(df_full)):
            c = df_full.loc[idx, "ContribYear"]
            e = df_full.loc[idx, "AnnualExpense"]

            cum_contrib_real += c
            cum_expense_drag_real += -e
            cum_expense_abs_real += e
            net_contrib_cum_real = cum_contrib_real + cum_expense_drag_real

            df_full.loc[idx, "CumContributions"] = cum_contrib_real
            df_full.loc[idx, "ExpenseDrag"] = cum_expense_drag_real
            df_full.loc[idx, "CumulativeExpense"] = cum_expense_abs_real
            df_full.loc[idx, "NetContributions"] = net_contrib_cum_real
    else:
        df_full["DF_end"] = 1.0
        df_full["DF_mid"] = 1.0

    label_suffix = " (today's dollars)" if show_real and infl_rate > 0 else " (nominal)"

    main_left, fi_col = st.columns([4, 2])

    # Right column: FI + Barista bridge KPI cards only
    with fi_col:
        st.markdown("### FI and Barista FIRE summary")

        # --- Compute FI and Barista FI metrics ---
        fi_age, fi_portfolio, fi_required, effective_swr, horizon_years = (
            compute_fi_age_horizon(
                df_full,
                fi_annual_spend_today,
                infl_rate,
                show_real,
                base_swr_30yr,
                horizon_end_age=max_sim_age,
            )
        )

        (
            barista_age,
            barista_start_balance_real,
            barista_fi_balance_real,
            barista_fi_target_real,
            barista_bridge_years,
            barista_pv_bridge_need_real,
        ) = (None, None, None, None, None, None)
        taxable_ratio_rec = None

        if (
            use_barista
            and barista_income_today > 0
            and fi_annual_spend_today > 0
            and base_swr_30yr > 0
        ):
            (
                barista_age,
                barista_start_balance_real,
                barista_fi_balance_real,
                barista_fi_target_real,
                barista_bridge_years,
                barista_pv_bridge_need_real,
            ) = compute_barista_fi_age_bridge(
                df_full,
                current_age=current_age,
                fi_annual_spend_today=fi_annual_spend_today,
                barista_income_today=barista_income_today,
                infl_rate=infl_rate,
                show_real=show_real,
                annual_rates_by_year_full=annual_rates_by_year_full,
                base_30yr_swr=base_swr_30yr,
                barista_end_age=barista_end_age,
                full_fi_age=retirement_age,
                tax_rate_bridge=barista_tax_rate_bridge,
                extra_health_today=extra_health_today,
            )

            if (
                barista_age is not None
                and barista_start_balance_real is not None
                and barista_start_balance_real > 0
                and barista_pv_bridge_need_real is not None
            ):
                taxable_ratio_rec = min(
                    1.0, barista_pv_bridge_need_real / barista_start_balance_real
                )

        # --- FI KPI card ---
        if fi_age is not None:
            if effective_swr is None:
                effective_swr = base_swr_30yr
                horizon_years = (
                    max(max_sim_age - fi_age, 1)
                    if horizon_years is None
                    else horizon_years
                )

            fi_card_html = textwrap.dedent(
                f"""
                <div style="background-color:#E5E5E5; padding:30px 20px; border-radius:12px;
                            text-align:center; margin-bottom:20px; border:1px solid #CFCFCF;">
                  <div style="font-size:20px; color:#333333; margin-bottom:4px;">
                    Financial independence age
                  </div>
                  <div style="font-size:72px; font-weight:700; color:#000000; line-height:1.05;">
                    {fi_age}
                  </div>
                  <div style="font-size:16px; color:#444444; margin-top:14px;">
                    FI target: ${fi_required:,.0f} &bull;
                    Portfolio at FI: ${fi_portfolio:,.0f}
                  </div>
                  <div style="font-size:14px; color:#555555; margin-top:6px;">
                    Effective SWR: {effective_swr*100:.2f}% &bull;
                    Horizon: ~{horizon_years:.0f} years (to age {max_sim_age})<br>
                    Base 30-year SWR input: {base_swr_30yr*100:.2f}%
                  </div>
                </div>
                """
            )
            st.markdown(fi_card_html, unsafe_allow_html=True)
        else:
            fi_card_html = textwrap.dedent(
                """
                <div style="background-color:#E5E5E5; padding:24px 20px; border-radius:12px;
                            text-align:center; margin-bottom:16px; border:1px solid #CFCFCF;">
                  <div style="font-size:18px; color:#333333; margin-bottom:6px;">
                    Financial independence age
                  </div>
                  <div style="font-size:32px; font-weight:600; color:#CC0000;">
                    Not reached
                  </div>
                </div>
                """
            )
            st.markdown(fi_card_html, unsafe_allow_html=True)
            st.caption(
                "Under the horizon-aware withdrawal rate, FI is not reached by age 90 "
                "with the current assumptions."
            )

        # --- Separate Barista FIRE KPI card ---
        if use_barista:
            if barista_age is not None:
                summary_line = (
                    f"Part-time from age {barista_age} to {barista_end_age} "
                    f"(~{barista_bridge_years:.0f} years) before full FI at age {retirement_age}."
                )

                target_line = (
                    f"FI target: ${barista_fi_target_real:,.0f} &bull; "
                    f"Projected portfolio at FI: ${barista_fi_balance_real:,.0f}"
                )

                taxable_line = ""
                if taxable_ratio_rec is not None and barista_pv_bridge_need_real is not None:
                    taxable_line = (
                        f"Bridge withdrawals present value: ${barista_pv_bridge_need_real:,.0f} "
                        f"(~{taxable_ratio_rec*100:.0f}% of portfolio at Barista age)."
                    )

                barista_card_html = textwrap.dedent(
                    f"""
                    <div style="background-color:#F0EFEF; padding:26px 20px; border-radius:12px;
                                text-align:center; margin-bottom:20px; border:1px solid #CFCFCF;">
                      <div style="font-size:20px; color:#333333; margin-bottom:4px;">
                        Barista FIRE age
                      </div>
                      <div style="font-size:64px; font-weight:700; color:#000000; line-height:1.05;">
                        {barista_age}
                      </div>
                      <div style="font-size:15px; color:#444444; margin-top:12px;">
                        {summary_line}
                      </div>
                      <div style="font-size:14px; color:#555555; margin-top:6px;">
                        Part-time income: ${barista_income_today:,.0f}/yr &bull;
                        Extra health costs: ${extra_health_today:,.0f}/yr &bull;
                        Withdrawal tax: {barista_tax_rate_bridge*100:.0f}%
                      </div>
                      <div style="font-size:14px; color:#555555; margin-top:6px;">
                        {target_line}
                      </div>
                      {f'<div style="font-size:13px; color:#666666; margin-top:6px;">{taxable_line}</div>' if taxable_line else ''}
                    </div>
                    """
                )
                st.markdown(barista_card_html, unsafe_allow_html=True)
            else:
                barista_card_html = textwrap.dedent(
                    f"""
                    <div style="background-color:#F0EFEF; padding:24px 20px; border-radius:12px;
                                text-align:center; margin-bottom:20px; border:1px solid #CFCFCF;">
                      <div style="font-size:20px; color:#333333; margin-bottom:6px;">
                        Barista FIRE age
                      </div>
                      <div style="font-size:28px; font-weight:600; color:#CC0000;">
                        Not feasible
                      </div>
                      <div style="font-size:13px; color:#555555; margin-top:8px;">
                        With ${barista_income_today:,.0f}/yr part-time income, extra health costs of
                        ${extra_health_today:,.0f}/yr, and a {barista_tax_rate_bridge*100:.0f}% tax
                        rate on withdrawals, the model cannot reach the FI target by age {retirement_age}.
                      </div>
                    </div>
                    """
                )
                st.markdown(barista_card_html, unsafe_allow_html=True)

    # Barista income series (not shown in table)
    barista_income_series = []
    for row in df_full.itertuples():
        age = row.Age
        year = row.Year
        if (
            use_barista
            and "barista_age" in locals()
            and barista_age is not None
            and barista_income_today > 0
            and barista_age <= age <= barista_end_age
        ):
            if show_real and infl_rate > 0:
                income = barista_income_today
            else:
                income = barista_income_today * ((1 + infl_rate) ** year)
        else:
            income = 0.0
        barista_income_series.append(income)

    df_full["BaristaIncome"] = barista_income_series

    df_plot = df_full[df_full["Age"] <= retirement_age].reset_index(drop=True)

    ending_net_worth = df_plot["NetWorth"].iloc[-1]
    ending_invest_balance = df_plot["Balance"].iloc[-1]

    # Left column: charts + tables
    with main_left:
        st.subheader(f"Net worth at traditional FI age: ${ending_net_worth:,.0f}{label_suffix}")
        st.caption(
            f"(Investments: ${ending_invest_balance:,.0f}; home equity included in net worth.)"
        )

        # Net worth decomposition chart
        color_net_contrib = "#C8A77A"
        color_invest_growth = "#3A6EA5"
        color_home = "#A7ADB2"
        highlight_color = "#CCAA00"

        highlight_mask = df_plot["NetWorth"] >= 1_000_000
        if highlight_mask.any():
            first_million_index = highlight_mask.idxmax()
        else:
            first_million_index = None

        net_colors = []
        growth_colors = []
        home_colors = []
        for idx in df_plot.index:
            if first_million_index is not None and idx == first_million_index:
                net_colors.append(highlight_color)
                growth_colors.append(highlight_color)
                home_colors.append(highlight_color)
            else:
                net_colors.append(color_net_contrib)
                growth_colors.append(color_invest_growth)
                home_colors.append(color_home)

        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=df_plot["Age"],
                y=df_plot["NetContributions"],
                name="Net contributions (after expenses)",
                marker_color=net_colors,
                hovertemplate="Age %{x}<br>Net contributions: $%{y:,.0f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Bar(
                x=df_plot["Age"],
                y=df_plot["InvestGrowth"],
                name="Investment growth (cumulative)",
                marker_color=growth_colors,
                hovertemplate="Age %{x}<br>Investment growth: $%{y:,.0f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Bar(
                x=df_plot["Age"],
                y=df_plot["HomeEquity"],
                name="Home equity",
                marker_color=home_colors,
                hovertemplate="Age %{x}<br>Home equity: $%{y:,.0f}<extra></extra>",
            )
        )

        ages = df_plot["Age"].tolist()
        tickvals = []
        for i, age in enumerate(ages):
            if i == 0 or i == len(ages) - 1 or age % 5 == 0:
                tickvals.append(age)
        tickvals = sorted(set(tickvals))
        ticktext = [str(a) for a in tickvals]

        fig.update_layout(
            barmode="stack",
            title=dict(
                text="Decomposition of net worth over time",
                x=0.5,
                xanchor="center",
                font=dict(size=18),
                pad=dict(b=10),
            ),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=40, r=40, t=60, b=60),
            xaxis=dict(
                title=dict(text="Age (years)", font=dict(size=14)),
                tickfont=dict(size=12, color="#777777"),
                showgrid=False,
                showline=True,
                linecolor="#777777",
                tickmode="array",
                tickvals=tickvals,
                ticktext=ticktext,
            ),
            yaxis=dict(
                title=dict(text="Amount ($)", font=dict(size=14)),
                tickfont=dict(size=12, color="#777777"),
                showgrid=True,
                gridcolor="#E0E0E0",
                showline=True,
                linecolor="#777777",
                tickprefix="$",
                tickformat=",.0f",
                separatethousands=True,
                exponentformat="none",
                showexponent="none",
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=0.96,
                xanchor="center",
                x=0.5,
                font=dict(size=12),
            ),
        )

        stacked_heights = (
            df_plot["NetContributions"] + df_plot["InvestGrowth"] + df_plot["HomeEquity"]
        )
        last_age = df_plot["Age"].iloc[-1]
        last_bar_height = stacked_heights.iloc[-1]
        max_bar_height = stacked_heights.max()
        label_y = last_bar_height + max_bar_height * 0.03

        fig.add_annotation(
            x=last_age,
            y=label_y,
            text=f"<b>${ending_net_worth:,.0f}</b>",
            showarrow=False,
            font=dict(size=14, color="black", family="Arial"),
        )

        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        # Put the two line charts side by side and make them smaller
        col_ret, col_inc = st.columns(2)

        # Annual return by age chart (nominal + real), y-axis from 0
        with col_ret:
            st.markdown("### Annual return by age")

            nominal_pct = [r * 100 for r in annual_rates_by_year_full]
            if infl_rate > 0:
                real_pct = [
                    ((1 + r) / (1 + infl_rate) - 1) * 100 for r in annual_rates_by_year_full
                ]
            else:
                real_pct = nominal_pct.copy()

            age_returns_df = pd.DataFrame(
                {
                    "Age": df_full["Age"],
                    "Nominal": nominal_pct,
                    "Real": real_pct,
                }
            )

            y_max_ret = max(max(nominal_pct), max(real_pct))
            y_max_ret = y_max_ret * 1.1 if y_max_ret > 0 else 1.0

            fig_ret = go.Figure()
            fig_ret.add_trace(
                go.Scatter(
                    x=age_returns_df["Age"],
                    y=age_returns_df["Nominal"],
                    mode="lines",
                    name="Nominal return",
                )
            )
            fig_ret.add_trace(
                go.Scatter(
                    x=age_returns_df["Age"],
                    y=age_returns_df["Real"],
                    mode="lines",
                    name="Real return (net of inflation)",
                )
            )

            fig_ret.update_layout(
              
                xaxis_title="Age",
                yaxis_title="Return (%)",
                yaxis=dict(range=[0, y_max_ret]),
                margin=dict(l=30, r=20, t=40, b=40),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=11),
                ),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                height=300,
            )

            st.plotly_chart(fig_ret, use_container_width=True, config={"displayModeBar": False})

        # Income trajectory chart, y-axis from 0
        with col_inc:
            st.markdown("### Income trajectory")

            fig_inc = go.Figure()
            fig_inc.add_trace(
                go.Scatter(
                    x=df_income["Age"],
                    y=df_income["IncomeRealAfterTax"],
                    mode="lines",
                    name="Income (after tax)",
                )
            )
            fig_inc.add_trace(
                go.Scatter(
                    x=df_income["Age"],
                    y=df_income["ExpensesReal"],
                    mode="lines",
                    name="Expenses",
                )
            )
            fig_inc.add_trace(
                go.Scatter(
                    x=df_income["Age"],
                    y=df_income["InvestableRealAnnual"],
                    mode="lines",
                    name="Annual investable",
                )
            )

            y_max_inc = max(
                df_income["IncomeRealAfterTax"].max(),
                df_income["ExpensesReal"].max(),
                df_income["InvestableRealAnnual"].max(),
            )
            y_max_inc = y_max_inc * 1.1 if y_max_inc > 0 else 1.0

            fig_inc.update_layout(
                title=dict(
                    text="Income vs expenses",
                    x=0.5,
                    xanchor="center",
                    font=dict(size=16),
                ),
                xaxis_title="Age",
                yaxis_title="$/year",
                yaxis=dict(range=[0, y_max_inc], tickprefix="$"),
                margin=dict(l=30, r=20, t=40, b=40),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="center",
                    x=0.5,
                    font=dict(size=11),
                ),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                height=300,
            )

            st.plotly_chart(fig_inc, use_container_width=True, config={"displayModeBar": False})

        # Age-by-age table
        st.markdown("### Age-by-age breakdown")

        display_df = df_plot.copy()
        display_df["InvestmentValue"] = display_df["Balance"]
        display_df["Home Value"] = display_df["HomePrice"]
        display_df["Home Equity"] = display_df["HomeEquity"]
        display_df["Contributions"] = display_df["ContribYear"]
        display_df["AdditionalAnnualExpense"] = display_df["AnnualExpense"]
        display_df["Investment Growth"] = display_df["InvestGrowthYear"]
        display_df["Net Worth"] = display_df["NetWorth"]

        display_cols = [
            "Year",
            "Age",
            "InvestmentValue",
            "Home Value",
            "Home Equity",
            "Contributions",
            "AdditionalAnnualExpense",
            "Investment Growth",
            "Net Worth",
        ]

        st.dataframe(
            display_df[display_cols].style.format(
                {
                    "InvestmentValue": "${:,.0f}",
                    "Home Value": "${:,.0f}",
                    "Home Equity": "${:,.0f}",
                    "Contributions": "${:,.0f}",
                    "AdditionalAnnualExpense": "${:,.0f}",
                    "Investment Growth": "${:,.0f}",
                    "Net Worth": "${:,.0f}",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

        # -------- Key assumptions moved to bottom --------
        assumptions = []

        if len(df_income) > 0:
            first_row = df_income.iloc[0]
            assumptions.append(
                f"- Current income model (after income tax + FICA + state): income ≈ "
                f"${first_row['IncomeRealAfterTax']:,.0f}/yr, expenses ≈ "
                f"${first_row['ExpensesReal']:,.0f}/yr, investable ≈ "
                f"${first_row['InvestableRealAnnual']:,.0f}/yr "
                f"({first_row['SavingsRate']*100:.1f}% savings rate on after-tax income)."
            )
        assumptions.append(
            f"- Pre-tax income grows at {income_growth_rate*100:.1f}%/yr; "
            f"expenses grow at {expense_growth_rate*100:.1f}%/yr above inflation."
        )

        if use_kid_expenses:
            assumptions.append(
                f"- Kid expenses: ages **{kids_start_age}–{kids_end_age}**, "
                f"{num_kids} kid(s) at `${annual_cost_per_kid_today:,.0f}`/kid/year (today's $)."
            )
        if use_car_expenses:
            assumptions.append(
                f"- Cars: `${car_cost_today:,.0f}` (today's $) starting at age **{first_car_age}** "
                f"every **{car_interval_years}** years."
            )

        if include_home:
            if home_status == "I already own a home":
                assumptions.append(
                    f"- Home: currently worth `${current_home_value_today:,.0f}`, "
                    f"current equity `${equity_amount_now:,.0f}`, "
                    f"{years_remaining_loan} years remaining at **{mortgage_rate*100:.2f}%**."
                )
            else:
                assumptions.append(
                    f"- Home: purchase at age **{planned_purchase_age}**, today's price `${home_price_today:,.0f}`, "
                    f"down `{down_payment_pct*100:.1f}%`, {mortgage_rate*100:.2f}% mortgage over {mortgage_term_years} years, "
                    f"{home_app_rate*100:.1f}%/yr appreciation, {maintenance_pct*100:.1f}% maintenance."
                )
                assumptions.append(
                    f"- After purchase: housing cost uses mortgage payment + estimated property tax/insurance "
                    f"of `${est_prop_tax_monthly*12:,.0f}`/yr compared with current rent `${current_rent:,.0f}`/month. "
                    "The difference is modeled as additional annual housing expense."
                )

        if show_real and infl_rate > 0:
            assumptions.append(
                f"- All values shown in today's dollars using **{infl_rate*100:.1f}%** inflation."
            )

        assumptions.append(
            "- Age-based glide path for returns: higher expected nominal returns early in your career, "
            "gradually de-risking as you approach and pass traditional FI age."
        )
        assumptions.append(
            "- Financial independence age is calculated from the full path to age 90; "
            "home equity is excluded from FI calculations."
        )

        if use_barista and "barista_age" in locals() and barista_age is not None:
            assumptions.append(
                f"- Barista bridge: contributions stop at age {barista_age}. "
                f"Part-time income `${barista_income_today:,.0f}`/yr, extra health `${extra_health_today:,.0f}`/yr, "
                f"{barista_tax_rate_bridge*100:.0f}% withdrawal tax, and an approximate taxable-need "
                f"of ${barista_pv_bridge_need_real:,.0f} for the bridge period."
            )

        if assumptions:
            st.markdown("**Key assumptions & notes**")
            st.markdown("\n".join(assumptions))


if __name__ == "__main__":
    main()

