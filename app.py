import textwrap

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# =========================================================
# Core compound interest logic
# =========================================================
def compound_schedule(
    start_balance,
    annual_rate,
    years,
    monthly_contrib_by_year,
    annual_expense_by_year,
):
    """
    Simulate investment account with monthly compounding and annual expenses.

    monthly_contrib_by_year: list length = years, monthly contribution for each year (nominal)
    annual_expense_by_year:  list length = years, nominal $ expense taken at year-end
    """
    r = annual_rate
    m = 12

    balance = start_balance
    cum_contrib = 0.0
    cum_invest_growth = 0.0
    cum_expense_drag = 0.0  # negative values
    cum_expense_abs = 0.0   # positive cumulative expenses

    rows = []

    for year_idx in range(years):
        balance_start_year = balance
        contrib_year = 0.0

        # Monthly contributions + growth
        for _ in range(m):
            monthly_contrib = monthly_contrib_by_year[year_idx]
            balance += monthly_contrib
            cum_contrib += monthly_contrib
            contrib_year += monthly_contrib

            growth_month = balance * (r / m)
            balance += growth_month

        balance_before_expense = balance
        annual_expense = annual_expense_by_year[year_idx]

        # Pure investment growth this year (before expenses)
        market_growth_year = balance_before_expense - (balance_start_year + contrib_year)
        cum_invest_growth += market_growth_year

        # Expense drag this year
        expense_drag_year = -annual_expense
        cum_expense_drag += expense_drag_year

        # Apply expenses
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
    """
    Adjust SWR downward for longer horizons, upward (slightly) for shorter.
    Heuristic: base_swr * sqrt(30 / horizon), capped between ~2.5% and 5%.
    """
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
    """
    FI age with horizon-aware SWR.

    Scans each age, computes horizon-specific SWR and required portfolio,
    and returns the earliest age where Balance >= required.

    Returns (fi_age, fi_portfolio, fi_required, eff_swr, horizon_years)
    or (None, None, None, None, None) if FI not reached.
    """
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
    annual_rate,
    base_30yr_swr,
    barista_start_age,
    barista_end_age,
    full_fi_age,
):
    """
    Model A: bridge-to-FI at full_fi_age using a fixed SWR (Option A).

    Logic:
      - Contributions stop at barista start age.
      - From barista_start_age to barista_end_age, portfolio funds (S - B) each year.
      - From barista_end_age to full_fi_age, portfolio funds full S each year.
      - All calculations are in real (today's) dollars.
      - At full_fi_age, portfolio must be >= S / base_30yr_swr.
      - Additionally, portfolio must not go negative at any point during the bridge.

    Returns:
      (barista_age, balance_at_barista_start_real, balance_at_full_fi_real,
       fi_target_real, years_bridge)
      or (None, None, None, None, None) if not achievable.
    """
    S = fi_annual_spend_today
    B = barista_income_today

    if S <= 0 or base_30yr_swr <= 0:
        return None, None, None, None, None

    # Work in real dollars
    if infl_rate > 0:
        real_return = (1 + annual_rate) / (1 + infl_rate) - 1
    else:
        real_return = annual_rate

    # Build a mapping from Age -> real portfolio balance.
    balance_real_by_age = {}
    for row in df.itertuples():
        age = row.Age
        year = row.Year
        bal = row.Balance

        if show_real and infl_rate > 0:
            bal_real = bal  # already in today's $
        else:
            if infl_rate > 0:
                bal_real = bal / ((1 + infl_rate) ** year)
            else:
                bal_real = bal

        balance_real_by_age[age] = bal_real

    # Real FI target at full_fi_age using fixed SWR (Option A).
    fi_target_real = S / base_30yr_swr

    # Effective earliest barista age to consider
    start_age_candidate = max(barista_start_age, current_age + 1)
    if start_age_candidate >= full_fi_age:
        return None, None, None, None, None

    # Clamp barista_end_age not to exceed full_fi_age - 1
    effective_barista_end_age = min(barista_end_age, full_fi_age - 1)

    best_barista_age = None
    bal_start_best = None
    bal_full_fi_best = None

    for age0 in range(start_age_candidate, full_fi_age + 1):
        if age0 not in balance_real_by_age:
            continue

        bal = balance_real_by_age[age0]
        bal_start_age = bal
        ok = True

        # Simulate year-by-year in real terms from age0 to full_fi_age
        for age in range(age0, full_fi_age):
            if age <= effective_barista_end_age:
                draw = max(S - B, 0.0)
            else:
                draw = S

            bal -= draw
            if bal < 0:
                ok = False
                break

            bal *= (1 + real_return)

        if not ok:
            continue

        # Check FI target at full_fi_age
        if bal >= fi_target_real:
            best_barista_age = age0
            bal_start_best = bal_start_age
            bal_full_fi_best = bal
            break

    if best_barista_age is None:
        return None, None, None, None, None

    years_bridge = full_fi_age - best_barista_age
    return best_barista_age, bal_start_best, bal_full_fi_best, fi_target_real, years_bridge


# =========================================================
# Page setup and main app
# =========================================================
def main():
    st.set_page_config(
        page_title="Personal FI Planner",
        layout="wide",
    )

    st.title("Personal FI Planner")

    # =========================================================
    # SIDEBAR: Core inputs
    # =========================================================
    st.sidebar.header("Core inputs")

    current_age = st.sidebar.number_input(
        "Current age (years)",
        value=26,
        min_value=0,
        max_value=100,
        step=1,
    )

    retirement_age_input = st.sidebar.number_input(
        "Retirement age (years)",
        value=60,
        min_value=1,
        max_value=100,
        step=1,
    )

    # FI simulation will always run to age 90
    max_sim_age = 90

    # Effective retirement age cannot exceed simulation end
    retirement_age = min(retirement_age_input, max_sim_age)

    years_plot = retirement_age - current_age
    if years_plot <= 0:
        st.error("Retirement age must be greater than current age and below the FI horizon (90).")
        return

    start_balance_input = st.sidebar.number_input(
        "Starting amount ($)",
        value=100000,
        step=1000,
        min_value=0,
    )

    annual_rate = st.sidebar.slider(
        "Annual rate of return (%/yr)",
        min_value=0.0,
        max_value=20.0,
        value=10.0,
        step=0.5,
    ) / 100.0

    contrib_frequency = st.sidebar.radio(
        "Contribution frequency",
        ("Monthly", "Annual"),
        index=0,
    )

    contrib_amount = st.sidebar.number_input(
        f"{contrib_frequency} contribution amount ($)",
        value=1000,
        step=100,
        min_value=0,
    )

    # Convert to monthly contribution based on frequency
    if contrib_frequency == "Monthly":
        monthly_contrib_base_today = contrib_amount
    else:
        monthly_contrib_base_today = contrib_amount / 12.0

    # Real (above inflation) contribution growth rate
    contrib_growth_rate = st.sidebar.number_input(
        "Contribution growth (%/yr above inflation)",
        value=0.0,
        step=0.5,
        min_value=0.0,
        max_value=20.0,
    ) / 100.0

    infl_rate = st.sidebar.number_input(
        "Assumed annual inflation (%/yr)",
        value=3.0,
        step=0.1,
        min_value=0.0,
        max_value=20.0,
    ) / 100.0

    show_real = st.sidebar.checkbox(
        "Show values in today's dollars (inflation-adjusted)",
        value=True,
    )

    # =========================================================
    # SIDEBAR: Additional customization
    # =========================================================
    st.sidebar.markdown("---")
    st.sidebar.subheader("Additional customization")

    # -----------------------------
    # Home (first section)
    # -----------------------------
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
    purchase_idx = 10**9  # default index far in future
    loan_amount = 0.0
    n_payments = 0
    r_m = 0.0

    if include_home:
        home_app_rate = st.sidebar.number_input(
            "Home appreciation (%/yr)",
            value=3.0,
            step=0.1,
            min_value=-10.0,
            max_value=20.0,
            key="home_app_rate",
        ) / 100.0

        maintenance_pct = st.sidebar.number_input(
            "Annual maintenance (% of home value)",
            value=1.0,
            step=0.1,
            min_value=0.0,
            max_value=10.0,
            key="maint_pct",
        ) / 100.0

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

            mortgage_rate = st.sidebar.number_input(
                "Mortgage interest rate (%/yr)",
                value=6.5,
                step=0.1,
                min_value=0.0,
                max_value=20.0,
                key="mort_rate_own",
            ) / 100.0

        else:  # plan to buy with mortgage
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
            down_payment_pct = st.sidebar.number_input(
                "Down payment (% of price)",
                value=20.0,
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                key="dp_pct",
            ) / 100.0

            mortgage_rate = st.sidebar.number_input(
                "Mortgage interest rate (%/yr)",
                value=6.5,
                step=0.1,
                min_value=0.0,
                max_value=20.0,
                key="mort_rate_buy",
            ) / 100.0

            mortgage_term_years = st.sidebar.radio(
                "Loan term (years)",
                [15, 30],
                index=1,
                key="mort_term",
            )

    # -----------------------------
    # Future expenses (kids + cars)
    # -----------------------------
    st.sidebar.markdown("---")
    st.sidebar.subheader("Future expenses (today's $)")

    # Kid-related expenses
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

    # Car replacement expenses
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

    # =========================================================
    # Build per-year contribution and expense schedules (full horizon to 90)
    # =========================================================
    years_full = max_sim_age - current_age  # full FI simulation horizon

    monthly_contrib_by_year_full = []
    for y in range(years_full):
        age = current_age + y
        if age < retirement_age:
            val = (
                monthly_contrib_base_today
                * (1 + contrib_growth_rate) ** y
                * (1 + infl_rate) ** y
            )
        else:
            val = 0.0
        monthly_contrib_by_year_full.append(val)

    annual_expense_by_year_nominal_full = [0.0 for _ in range(years_full)]

    # Home arrays for full horizon
    home_price_by_year_full = [0.0 for _ in range(years_full)]   # market price
    home_equity_by_year_full = [0.0 for _ in range(years_full)]  # equity
    housing_adj_by_year_full = [0.0 for _ in range(years_full)]  # mortgage vs rent delta

    # Start balance (may be hit by an immediate down payment)
    start_balance_effective = start_balance_input

    # Kid expenses
    for year_idx in range(years_full):
        age_end_of_year = current_age + year_idx + 1
        if use_kid_expenses:
            if kids_start_age <= age_end_of_year <= kids_end_age:
                expense_real = num_kids * annual_cost_per_kid_today
                expense_nominal = expense_real * ((1 + infl_rate) ** (year_idx + 1))
                annual_expense_by_year_nominal_full[year_idx] += expense_nominal

    # Car expenses
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

    # Home: equity, maintenance, and possible down payment
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

    # Housing cost delta: (mortgage + property tax) vs current rent
    if (
        include_home
        and home_status == "I plan to buy"
        and mortgage_payment > 0
    ):
        total_monthly_owner_cost = mortgage_payment + est_prop_tax_monthly
        extra_housing_monthly = total_monthly_owner_cost - current_rent
        for year_idx in range(years_full):
            if year_idx >= purchase_idx:
                housing_adj_by_year_full[year_idx] = extra_housing_monthly * 12

    # Add housing delta into annual expenses
    for y in range(years_full):
        annual_expense_by_year_nominal_full[y] += housing_adj_by_year_full[y]

    # =========================================================
    # Base scenario (full horizon to 90, nominal)
    # =========================================================
    df_full = compound_schedule(
        start_balance=start_balance_effective,
        annual_rate=annual_rate,
        years=years_full,
        monthly_contrib_by_year=monthly_contrib_by_year_full,
        annual_expense_by_year=annual_expense_by_year_nominal_full,
    )

    df_full["Age"] = current_age + df_full["Year"]
    df_full["HomePrice"] = home_price_by_year_full
    df_full["HomeEquity"] = home_equity_by_year_full
    df_full["NetWorth"] = df_full["Balance"] + df_full["HomeEquity"]
    df_full["HousingDelta"] = housing_adj_by_year_full

    # Net contributions (nominal)
    df_full["NetContributions"] = df_full["CumContributions"] + df_full["ExpenseDrag"]

    # =========================================================
    # Real-dollar adjustment (full horizon)
    # =========================================================
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

        df_full["ContribYear"] = df_full["ContribYear"] / df_full["DF_mid"]
        df_full["AnnualExpense"] = df_full["AnnualExpense"] / df_full["DF_end"]
        df_full["HousingDelta"] = df_full["HousingDelta"] / df_full["DF_end"]

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

    # =========================================================
    # MAIN LAYOUT: left = chart etc., right = FI KPI card
    # =========================================================
    main_left, fi_col = st.columns([4, 2])

    # -----------------------------
    # RIGHT COLUMN: Financial independence age (+ Barista FIRE)
    # -----------------------------
    with fi_col:
        st.markdown("### Financial independence age")

        fi_annual_spend_today = st.number_input(
            "Target annual spending in FI ($/yr, today's)",
            value=60000,
            step=5000,
            min_value=0,
            key="fi_spend",
        )

        base_swr_30yr = st.number_input(
            "Base safe withdrawal rate (% for ~30 yrs)",
            value=4.0,
            min_value=1.0,
            max_value=10.0,
            step=0.5,
            key="swr_base",
        ) / 100.0

        st.caption(
            "FI age is computed using your portfolio path from now to age 90. "
            "The retirement-age slider only controls when contributions stop "
            "and how far the chart extends."
        )

        # Barista FIRE controls
        use_barista = st.checkbox(
            "Show Barista FIRE scenario (part-time income in FI)",
            value=False,
            key="barista_toggle",
        )

        barista_income_today = 0.0
        barista_start_age = None
        barista_end_age = 65

        if use_barista:
            barista_income_today = st.number_input(
                "Expected part-time income in FI ($/yr, today's)",
                value=20000,
                step=5000,
                min_value=0,
                key="barista_income",
            )
            barista_end_age = st.number_input(
                "End age for part-time work",
                value=65,
                min_value=current_age + 1,
                max_value=retirement_age,
                step=1,
                key="barista_end_age",
            )
            barista_start_age = st.number_input(
                "Earliest age you switch to part-time",
                value=max(current_age + 5, current_age + 1),
                min_value=current_age + 1,
                max_value=barista_end_age,
                step=1,
                key="barista_start_age",
            )

        # -------- FI age (horizon-aware SWR, single pass over df_full) --------
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

        # ---------------- Barista FI (Model A bridge-to-FI, using retirement_age as full FI age) --------------------
        (
            barista_age,
            barista_start_balance_real,
            barista_fi_balance_real,
            barista_fi_target_real,
            barista_bridge_years,
        ) = (None, None, None, None, None)

        if (
            use_barista
            and barista_income_today > 0
            and barista_start_age is not None
            and fi_annual_spend_today > 0
            and base_swr_30yr > 0
        ):
            (
                barista_age,
                barista_start_balance_real,
                barista_fi_balance_real,
                barista_fi_target_real,
                barista_bridge_years,
            ) = compute_barista_fi_age_bridge(
                df_full,
                current_age=current_age,
                fi_annual_spend_today=fi_annual_spend_today,
                barista_income_today=barista_income_today,
                infl_rate=infl_rate,
                show_real=show_real,
                annual_rate=annual_rate,
                base_30yr_swr=base_swr_30yr,
                barista_start_age=barista_start_age,
                barista_end_age=barista_end_age,
                full_fi_age=retirement_age,
            )

        # ---------------- Render FI card -------------------
        if fi_age is not None:
            if effective_swr is None:
                effective_swr = base_swr_30yr
                horizon_years = (
                    max(max_sim_age - fi_age, 1) if horizon_years is None else horizon_years
                )

            if use_barista and barista_age is not None:
                barista_line = (
                    "Barista FI (bridge model): you can switch to part-time as early as "
                    f"age {barista_age} with ${barista_income_today:,.0f}/yr until age {barista_end_age}, "
                    f"and still reach a {base_swr_30yr*100:.1f}% FI target of "
                    f"${barista_fi_target_real:,.0f} by age {retirement_age} "
                    f"(projected portfolio at that age: ${barista_fi_balance_real:,.0f})."
                )
            elif use_barista:
                barista_line = (
                    f"Barista FI bridge model with ${barista_income_today:,.0f}/yr until age {barista_end_age}: "
                    "not reached under these assumptions (cannot bridge to the FI target by retirement age)."
                )
            else:
                barista_line = ""

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
                  {f'<div style="font-size:14px; color:#666666; margin-top:10px;">{barista_line}</div>' if barista_line else ''}
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

    # -----------------------------
    # Build Barista income schedule (per year) for table/plots
    # -----------------------------
    barista_income_series = []
    for row in df_full.itertuples():
        age = row.Age
        year = row.Year
        if (
            use_barista
            and barista_income_today > 0
            and barista_start_age is not None
            and barista_start_age <= age <= barista_end_age
        ):
            if show_real and infl_rate > 0:
                income = barista_income_today  # already in today's $
            else:
                income = barista_income_today * ((1 + infl_rate) ** year)
        else:
            income = 0.0
        barista_income_series.append(income)

    df_full["BaristaIncome"] = barista_income_series

    # Slice for visuals: only up to chosen retirement age
    df_plot = df_full[df_full["Age"] <= retirement_age].reset_index(drop=True)

    ending_net_worth = df_plot["NetWorth"].iloc[-1]
    ending_invest_balance = df_plot["Balance"].iloc[-1]

    # -----------------------------
    # LEFT COLUMN: main content (uses df_plot up to retirement age)
    # -----------------------------
    with main_left:
        st.subheader(f"Net worth at retirement age: ${ending_net_worth:,.0f}{label_suffix}")
        st.caption(
            f"(Investments: ${ending_invest_balance:,.0f}; home equity included in net worth.)"
        )

        # Key assumptions / notes
        assumptions = []

        if contrib_growth_rate > 0:
            assumptions.append(
                f"- Contributions: start at `${monthly_contrib_base_today:,.0f}`/month (today's $), "
                f"grow **{contrib_growth_rate*100:.1f}%/yr** above inflation, "
                f"from age {current_age} to {retirement_age} at **{annual_rate*100:.1f}%** return."
            )
        else:
            assumptions.append(
                f"- Contributions: `${monthly_contrib_base_today:,.0f}`/month (today's $), "
                f"inflation-adjusted only, from age {current_age} to {retirement_age} at **{annual_rate*100:.1f}%** return."
            )

        if use_kid_expenses:
            assumptions.append(
                f"- Kid expenses: ages **{kids_start_age}–{kids_end_age}**, "
                f"{num_kids} kid(s) at `${annual_cost_per_kid_today:,.0f}`/kid/year (today's $)."
            )
        if use_car_expenses:
            assumptions.append(
                f"- Cars: `${car_cost_today:,.0f}` (today's $) starting at age **{first_car_age}** every **{car_interval_years}** years."
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
            "- Financial independence age is calculated from the full path to age 90; "
            "home equity is excluded from FI calculations."
        )

        if use_barista and barista_start_age is not None:
            assumptions.append(
                f"- Barista FIRE (bridge model): assumes contributions stop and part-time income of "
                f"`{barista_income_today:,.0f}`/year from age {barista_start_age} to {barista_end_age}. "
                f"The calculator finds the earliest age you can switch to part-time and still be on track "
                f"to hit a {base_swr_30yr*100:.1f}% FI target by age {retirement_age}."
            )

        if assumptions:
            st.markdown("**Key assumptions & notes**")
            st.markdown("\n".join(assumptions))

        # Chart: Net contributions + investment growth + home equity (up to retirement age)
        color_net_contrib = "#C8A77A"
        color_invest_growth = "#3A6EA5"
        color_home = "#A7ADB2"

        highlight_color = "#CCAA00"  # gold

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

        st.plotly_chart(fig, use_container_width=True)

        # Scenario: What if you saved more (or less)?
        st.markdown("### What if you saved more (or less)?")

        extra_per_month = st.number_input(
            "Extra saved per month ($)",
            value=100,
            step=50,
            min_value=-10000,
            max_value=100000,
            key="extra_per_month_center",
        )

        if extra_per_month != 0:
            # only need to simulate to retirement age for this comparison
            years_extra = years_plot
            monthly_contrib_by_year_extra = []
            for y in range(years_extra):
                age = current_age + y
                base_c = (
                    monthly_contrib_base_today
                    * (1 + contrib_growth_rate) ** y
                    * (1 + infl_rate) ** y
                )
                if age < retirement_age:
                    c = base_c + extra_per_month * (1 + infl_rate) ** y
                else:
                    c = 0.0
                monthly_contrib_by_year_extra.append(c)

            annual_expenses_extra = annual_expense_by_year_nominal_full[:years_extra]

            df_more = compound_schedule(
                start_balance=start_balance_effective,
                annual_rate=annual_rate,
                years=years_extra,
                monthly_contrib_by_year=monthly_contrib_by_year_extra,
                annual_expense_by_year=annual_expenses_extra,
            )
            df_more["HomeEquity"] = home_equity_by_year_full[:years_extra]
            df_more["NetWorth"] = df_more["Balance"] + df_more["HomeEquity"]

            if show_real and infl_rate > 0:
                df_more["DF_end"] = (1 + infl_rate) ** df_more["Year"]
                for col in ["Balance", "HomeEquity", "NetWorth"]:
                    df_more[col] = df_more[col] / df_more["DF_end"]

            ending_more = df_more["NetWorth"].iloc[-1]
            extra_growth = ending_more - ending_net_worth

            label = f"Net worth at {retirement_age} with {extra_per_month:+,.0f}/month"
            st.metric(
                label=label,
                value=f"${ending_more:,.0f}",
                delta=f"${extra_growth:,.0f}",
            )
        else:
            st.caption("Set a non-zero amount to see the impact on ending net worth.")

        # Age-by-age table (up to retirement age)
        st.markdown("### Age-by-age breakdown")

        display_df = df_plot.copy()
        display_df["InvestmentValue"] = display_df["Balance"]
        display_df["Home Value"] = display_df["HomePrice"]
        display_df["Home Equity"] = display_df["HomeEquity"]
        display_df["Contributions"] = display_df["ContribYear"]
        display_df["AdditionalAnnualExpense"] = display_df["AnnualExpense"]
        display_df["Barista Income"] = display_df["BaristaIncome"]
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
            "Barista Income",
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
                    "Barista Income": "${:,.0f}",
                    "Investment Growth": "${:,.0f}",
                    "Net Worth": "${:,.0f}",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
