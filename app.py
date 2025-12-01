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

        # Monthly contributions and growth
        for _ in range(m):
            monthly_contrib = monthly_contrib_by_year[year_idx]
            balance += monthly_contrib
            cum_contrib += monthly_contrib
            contrib_year += monthly_contrib

            growth_month = balance * (r / m)
            balance += growth_month

        balance_before_expense = balance
        annual_expense = annual_expense_by_year[year_idx]

        # Market growth in that year (before expense)
        market_growth_year = balance_before_expense - (balance_start_year + contrib_year)
        cum_invest_growth += market_growth_year

        # Apply annual expense at year-end
        balance -= annual_expense
        expense_drag_year = -annual_expense
        cum_expense_drag += expense_drag_year
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
# FI / Barista helpers (bridge-style logic)
# =========================================================
def compute_fi_age_horizon(
    df_full,
    current_age,
    fi_annual_spend_today,
    infl_rate,
    show_real,
    base_30yr_swr,
    retirement_age,
    annual_rates_by_year_full,
    extra_health_today=0.0,
    tax_rate_bridge=0.0,
):
    """
    FI age = earliest age at which you can:
      - Quit full-time work;
      - Set contributions to 0 from that age onward;
      - Have the portfolio cover:
          * Target FI spending (today's $) each year, plus
          * Extra health costs (today's $), grossed up for withdrawal tax; and
      - Still arrive at FI target at the traditional FI age:

          FI_target_real = fi_annual_spend_today / base_30yr_swr

    All math in this function is in real (today's) dollars.
    """
    S = fi_annual_spend_today
    if (
        S <= 0
        or base_30yr_swr <= 0
        or df_full is None
        or df_full.empty
        or current_age is None
        or retirement_age is None
        or retirement_age <= current_age
    ):
        return None, None, None, None, None

    # Convert df_full balances to "today" dollars (real)
    balance_real_by_age = {}
    for row in df_full.itertuples():
        age = row.Age
        year = row.Year
        bal = row.Balance

        if show_real and infl_rate > 0:
            bal_real = bal  # already adjusted
        else:
            if infl_rate > 0:
                bal_real = bal / ((1 + infl_rate) ** year)
            else:
                bal_real = bal

        balance_real_by_age[age] = bal_real

    # FI target at traditional FI age in today's dollars
    fi_target_real = S / base_30yr_swr

    t = max(0.0, min(tax_rate_bridge, 0.7))

    best_fi_age = None
    best_portfolio_at_ret = None

    # Candidate FI ages
    start_age_candidate = current_age + 1
    for age0 in range(start_age_candidate, retirement_age + 1):
        if age0 not in balance_real_by_age:
            continue

        bal = balance_real_by_age[age0]
        ok = True

        # Walk year by year from FI age to retirement age
        for age in range(age0, retirement_age):
            idx = age - current_age
            if idx < 0 or idx >= len(annual_rates_by_year_full):
                ok = False
                break

            r_nominal = annual_rates_by_year_full[idx]
            if infl_rate > 0:
                real_return = (1 + r_nominal) / (1 + infl_rate) - 1
            else:
                real_return = r_nominal

            spend_from_portfolio = S
            total_real_spend = spend_from_portfolio + max(extra_health_today, 0.0)

            if t > 0:
                gross_withdrawal = total_real_spend / (1 - t)
            else:
                gross_withdrawal = total_real_spend

            bal -= gross_withdrawal
            if bal < 0:
                ok = False
                break

            bal *= (1 + real_return)

        if not ok:
            continue

        if bal >= fi_target_real:
            best_fi_age = age0
            best_portfolio_at_ret = bal
            break

    if best_fi_age is None:
        return None, None, fi_target_real, base_30yr_swr, None

    horizon_years = retirement_age - best_fi_age
    effective_swr = base_30yr_swr

    return best_fi_age, best_portfolio_at_ret, fi_target_real, effective_swr, horizon_years


def compute_barista_fi_age_bridge(
    df_full,
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
    Barista FI = earliest age at which you can:
      - Stop full-time work and start part-time;
      - From Barista age → barista_end_age:
           portfolio covers (FI spend − barista income) + extra health (in real dollars);
      - From barista_end_age → full_fi_age:
           portfolio covers full FI spend + extra health;
      - All withdrawals grossed up for withdrawal tax rate;
      - Still arrive at FI target at full_fi_age:

           FI_target_real = fi_annual_spend_today / base_30yr_swr

    Returns:
      (barista_age, bal_start_at_barista, bal_at_full_fi, fi_target_real,
       bridge_years, pv_bridge_need_real)
    """
    S = fi_annual_spend_today
    B = barista_income_today

    if S <= 0 or base_30yr_swr <= 0:
        return None, None, None, None, None, None

    t = max(0.0, min(tax_rate_bridge, 0.7))

    balance_real_by_age = {}
    for row in df_full.itertuples():
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

    best_barista_age = None
    bal_start_best = None
    bal_full_fi_best = None
    pv_bridge_need_best = None

    for age0 in range(current_age + 1, full_fi_age + 1):
        if age0 not in balance_real_by_age:
            continue

        bal_start_age = balance_real_by_age[age0]
        bal = bal_start_age
        pv_bridge_need = 0.0
        disc_factor = 1.0
        ok = True

        effective_barista_end_age = min(barista_end_age, full_fi_age - 1)

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

    bridge_years = full_fi_age - best_barista_age

    return (
        best_barista_age,
        bal_start_best,
        bal_full_fi_best,
        fi_target_real,
        bridge_years,
        pv_bridge_need_best,
    )


# =========================================================
# Tax helper functions
# =========================================================
def federal_tax_single_approx(income):
    """
    Rough US federal income tax approximation for single filer.
    """
    if income <= 0:
        return 0.0

    brackets = [
        (0, 11000, 0.10),
        (11000, 44725, 0.12),
        (44725, 95375, 0.22),
        (95375, 182100, 0.24),
        (182100, 231250, 0.32),
        (231250, 578125, 0.35),
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

    ss_wage_base = 160_200
    ss_tax = 0.062 * min(income, ss_wage_base)
    medicare_tax = 0.0145 * income
    state_tax = max(state_tax_rate, 0.0) * income

    return federal + ss_tax + medicare_tax + state_tax


# =========================================================
# UI + main logic
# =========================================================
def main():
    st.set_page_config(
        page_title="Financial Independence / Barista FIRE Simulator",
        layout="wide",
    )

    st.title("Financial Independence & Barista FIRE Planner")

    # =====================================================
    # Sidebar inputs
    # =====================================================
    with st.sidebar:
        st.markdown("### Core Setup")

        current_age = st.slider("Current age", 20, 60, 30)
        retirement_age = st.slider("Traditional FI age (target)", 40, 80, 60)

        start_balance_effective = st.number_input(
            "Starting investment balance ($)",
            min_value=0.0,
            value=50_000.0,
            step=10_000.0,
            format="%.0f",
        )

        st.markdown("---")
        st.markdown("### Income & Savings")

        starting_income = st.number_input(
            "Current pre-tax income ($/year)",
            min_value=0.0,
            value=75_000.0,
            step=5_000.0,
            format="%.0f",
        )

        annual_raise_pct = st.slider(
            "Expected annual raise (%)",
            0.0,
            10.0,
            3.0,
            step=0.5,
        )

        future_big_raise_age = st.slider(
            "Age for large promotion / raise (0 = none)",
            0,
            70,
            0,
        )
        future_big_raise_pct = st.slider(
            "Promotion raise at that age (%)",
            0.0,
            100.0,
            0.0,
            step=1.0,
        )

        savings_rate_override = st.slider(
            "Target savings rate on after-tax income (0 = infer from expenses)",
            0.0,
            0.9,
            0.0,
            step=0.05,
        )

        st.markdown("---")
        st.markdown("### Spending & Inflation")

        expense_real_base = st.number_input(
            "Baseline annual spending (today's $)",
            min_value=0.0,
            value=40_000.0,
            step=1_000.0,
            format="%.0f",
        )

        infl_rate = st.slider(
            "Inflation assumption (%)",
            0.0,
            10.0,
            2.5,
            step=0.25,
        ) / 100.0

        show_real = st.checkbox("Show values in today's dollars", value=True)

        st.markdown("---")
        st.markdown("### Investment Returns (Glide Path)")

        annual_rate_base = st.slider(
            "Annual Return (Adjusts closer to retirement) – nominal %",
            0.0,
            15.0,
            7.0,
            step=0.25,
        ) / 100.0

        def glide_path_return(age, base_r):
            """
            Simple glide path:
              - Higher return when young
              - Lower near retirement
            """
            if age <= 35:
                return base_r + 0.01
            elif age >= 60:
                return base_r - 0.02
            else:
                frac = (age - 35) / (60 - 35)
                return (base_r + 0.01) + frac * (-0.03)

        st.markdown("---")
        st.markdown("### FI / Barista Settings")

        fi_annual_spend_today = st.number_input(
            "Target annual spending in FI (today's $)",
            min_value=0.0,
            value=60_000.0,
            step=1_000.0,
            format="%.0f",
        )

        base_swr_30yr = st.slider(
            "Base SWR for FI target (30-yr horizon, %)",
            2.0,
            6.0,
            4.0,
            step=0.1,
        ) / 100.0

        extra_health_today = st.number_input(
            "Extra annual health costs in FI (today's $)",
            min_value=0.0,
            value=6_000.0,
            step=500.0,
            format="%.0f",
        )

        use_barista = st.checkbox("Model Barista / part-time bridge?", value=True)

        if use_barista:
            barista_income_today = st.number_input(
                "Part-time work income (today's $/year)",
                min_value=0.0,
                value=25_000.0,
                step=1_000.0,
                format="%.0f",
            )

            barista_start_default = min(retirement_age - 5, max(current_age + 1, 35))
            barista_end_default = max(barista_start_default + 5, retirement_age - 5)

            barista_age_start_slider = st.slider(
                "Candidate start age for part-time work (display only)",
                current_age + 1,
                retirement_age - 1,
                barista_start_default,
            )
            barista_end_age = st.slider(
                "Age until you keep working part-time",
                barista_age_start_slider,
                retirement_age - 1,
                barista_end_default,
            )

            barista_tax_rate_bridge = st.slider(
                "Effective tax rate on withdrawals during Barista / FI (%)",
                0.0,
                40.0,
                10.0,
                step=1.0,
            ) / 100.0
        else:
            barista_income_today = 0.0
            barista_end_age = retirement_age - 1
            barista_tax_rate_bridge = 0.0

        st.markdown("---")
        st.markdown("### Tax Settings")

        state_tax_rate = st.slider(
            "State income tax rate (%)",
            0.0,
            15.0,
            0.0,
            step=0.5,
        ) / 100.0

        st.markdown("---")
        st.markdown("### Housing / Home Equity (Optional)")

        include_home = st.checkbox("Include home / housing in net worth?", value=True)

        if include_home:
            current_home_value = st.number_input(
                "Current home value ($)",
                min_value=0.0,
                value=400_000.0,
                step=25_000.0,
                format="%.0f",
            )
            current_home_equity = st.number_input(
                "Current home equity ($)",
                min_value=0.0,
                value=80_000.0,
                step=10_000.0,
                format="%.0f",
            )

            home_appreciation_rate = st.slider(
                "Home price appreciation rate (%)",
                0.0,
                10.0,
                3.0,
                step=0.25,
            ) / 100.0

            monthly_housing_cost_today = st.number_input(
                "Current monthly housing cost (today's $)",
                min_value=0.0,
                value=2_000.0,
                step=100.0,
                format="%.0f",
            )

            housing_cost_change_age = st.slider(
                "Age at which housing cost changes",
                current_age,
                retirement_age,
                retirement_age,
            )

            new_monthly_housing_cost_today = st.number_input(
                "New monthly housing cost at that age (today's $)",
                min_value=0.0,
                value=1_200.0,
                step=100.0,
                format="%.0f",
            )

            extra_home_maintenance_today = st.number_input(
                "Extra annual home maintenance (today's $)",
                min_value=0.0,
                value=3_000.0,
                step=500.0,
                format="%.0f",
            )

            home_purchase_future_age = st.slider(
                "Age at which you might buy a new home (0 = none)",
                0,
                80,
                0,
            )
            future_home_price_today = st.number_input(
                "Future home price (today's $)",
                min_value=0.0,
                value=500_000.0,
                step=25_000.0,
                format="%.0f",
            )
            future_down_payment_pct = st.slider(
                "Down payment (%) for future home",
                0.0,
                50.0,
                20.0,
                step=1.0,
            ) / 100.0
        else:
            current_home_value = 0.0
            current_home_equity = 0.0
            home_appreciation_rate = 0.0
            monthly_housing_cost_today = 0.0
            housing_cost_change_age = retirement_age
            new_monthly_housing_cost_today = 0.0
            extra_home_maintenance_today = 0.0
            home_purchase_future_age = 0
            future_home_price_today = 0.0
            future_down_payment_pct = 0.0

        st.markdown("---")
        st.markdown("### Projection Horizon")

        years_full_default = max(1, retirement_age - current_age + 30)
        years_full = st.slider(
            "Projection horizon (years from now)",
            10,
            60,
            years_full_default,
        )

    label_suffix = " (today's dollars)" if show_real and infl_rate > 0 else " (nominal)"

    # =====================================================
    # Income trajectory, taxes, investable cash (REAL)
    # =====================================================
    years_list = list(range(years_full))
    ages = [current_age + y for y in years_list]

    incomes_nominal = []
    for y in years_list:
        age = current_age + y
        # annual raise compounding
        income_nominal = starting_income * ((1 + annual_raise_pct / 100.0) ** y)
        # single promotion factor applied once for all ages >= promo age
        if future_big_raise_age > 0 and age >= future_big_raise_age:
            income_nominal *= (1 + future_big_raise_pct / 100.0)
        incomes_nominal.append(income_nominal)

    rows = []
    for y, age in zip(years_list, ages):
        income_nominal = incomes_nominal[y]

        # convert gross income to real for intuition (not strictly needed)
        if infl_rate > 0:
            income_real_today = income_nominal / ((1 + infl_rate) ** y)
        else:
            income_real_today = income_nominal

        # tax in nominal terms
        tax_nominal = total_tax_on_earned(income_nominal, state_tax_rate)
        after_tax_nominal = income_nominal - tax_nominal

        if infl_rate > 0:
            after_tax_income_real = after_tax_nominal / ((1 + infl_rate) ** y)
        else:
            after_tax_income_real = after_tax_nominal

        # baseline expense rule (real)
        expense_real = expense_real_base
        if age >= retirement_age:
            expense_real *= 0.9

        if savings_rate_override > 0:
            # user forces savings rate; expenses are whatever is left
            investable_real = after_tax_income_real * savings_rate_override
            implied_expense_real = after_tax_income_real - investable_real
        else:
            # user forces expenses; savings are whatever is left
            implied_expense_real = expense_real
            investable_real = max(after_tax_income_real - implied_expense_real, 0.0)

        if after_tax_income_real > 0:
            savings_rate_actual = investable_real / after_tax_income_real
        else:
            savings_rate_actual = 0.0

        rows.append(
            {
                "YearIndex": y,
                "Age": age,
                "IncomeNominal": income_nominal,
                "IncomeReal": income_real_today,
                "AfterTaxIncomeReal": after_tax_income_real,
                "ExpenseReal": implied_expense_real,
                "InvestableReal": investable_real,
                "SavingsRateActual": savings_rate_actual,
            }
        )

    df_income = pd.DataFrame(rows)

    # =====================================================
    # Annual returns (glide path) – nominal
    # =====================================================
    annual_rates_by_year_full = []
    for y in range(years_full):
        age = current_age + y
        annual_rates_by_year_full.append(glide_path_return(age, annual_rate_base))

    # =====================================================
    # Contributions (nominal) from REAL investable cash
    # =====================================================
    monthly_contrib_by_year_full = []
    for y in range(years_full):
        age = current_age + y
        if age < retirement_age and y < len(df_income):
            investable_real_annual = df_income.loc[y, "InvestableReal"]
            if show_real and infl_rate > 0:
                annual_contrib_nominal = investable_real_annual * ((1 + infl_rate) ** y)
            else:
                annual_contrib_nominal = investable_real_annual
            monthly_contrib_by_year_full.append(annual_contrib_nominal / 12.0)
        else:
            monthly_contrib_by_year_full.append(0.0)

    # =====================================================
    # Baseline non-FI expenses (nominal): housing, maintenance, etc.
    # =====================================================
    annual_expense_by_year_nominal_full = [0.0 for _ in range(years_full)]
    housing_adj_by_year_full = [0.0 for _ in range(years_full)]
    home_price_by_year_full = [0.0 for _ in range(years_full)]
    home_equity_by_year_full = [0.0 for _ in range(years_full)]

    if include_home:
        home_price = current_home_value
        home_equity = current_home_equity

        for y in range(years_full):
            age = current_age + y

            if y == 0:
                home_price_by_year_full[y] = home_price
                home_equity_by_year_full[y] = home_equity
            else:
                home_price *= 1 + home_appreciation_rate
                home_equity *= 1 + home_appreciation_rate
                home_price_by_year_full[y] = home_price
                home_equity_by_year_full[y] = home_equity

            housing_cost_real = monthly_housing_cost_today * 12.0
            if age >= housing_cost_change_age:
                housing_cost_real = new_monthly_housing_cost_today * 12.0

            if infl_rate > 0:
                housing_cost_nominal = housing_cost_real * ((1 + infl_rate) ** y)
            else:
                housing_cost_nominal = housing_cost_real

            housing_adj_by_year_full[y] = housing_cost_nominal

            maint_real = extra_home_maintenance_today
            if infl_rate > 0:
                maint_nominal = maint_real * ((1 + infl_rate) ** y)
            else:
                maint_nominal = maint_real

            annual_expense_by_year_nominal_full[y] += maint_nominal

        if home_purchase_future_age > 0:
            for y in range(years_full):
                age = current_age + y
                if age == home_purchase_future_age:
                    if infl_rate > 0:
                        future_home_price_nominal = future_home_price_today * (
                            (1 + infl_rate) ** y
                        )
                    else:
                        future_home_price_nominal = future_home_price_today

                    down_payment_nominal = future_home_price_nominal * future_down_payment_pct
                    annual_expense_by_year_nominal_full[y] += down_payment_nominal

    for y in range(years_full):
        annual_expense_by_year_nominal_full[y] += housing_adj_by_year_full[y]

    # =====================================================
    # Full-time baseline path (no FI / Barista withdrawals)
    # =====================================================
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
            "CumContributions",
            "ExpenseDrag",
            "CumulativeExpense",
            "NetGrowth",
            "AnnualExpense",
        ]:
            df_full[col] = df_full[col] / df_full["DF_end"]
    else:
        df_full["DF_end"] = 1.0
        df_full["DF_mid"] = 1.0

    main_left, fi_col = st.columns([4, 2])

    # =====================================================
    # FI and Barista KPIs
    # =====================================================
    with fi_col:
        st.markdown("### FI and Part-Time Work summary")

        fi_age, fi_portfolio, fi_required, effective_swr, horizon_years = compute_fi_age_horizon(
            df_full=df_full,
            current_age=current_age,
            fi_annual_spend_today=fi_annual_spend_today,
            infl_rate=infl_rate,
            show_real=show_real,
            base_30yr_swr=base_swr_30yr,
            retirement_age=retirement_age,
            annual_rates_by_year_full=annual_rates_by_year_full,
            extra_health_today=extra_health_today,
            tax_rate_bridge=barista_tax_rate_bridge,
        )

        barista_age = None
        barista_start_balance_real = None
        barista_portfolio_at_fi_real = None
        barista_bridge_years = None
        barista_pv_bridge_need_real = None
        taxable_ratio_rec = None

        if use_barista:
            (
                barista_age,
                barista_start_balance_real,
                barista_portfolio_at_fi_real,
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

        # FI KPI card
        if fi_age is not None:
            fi_card_html = textwrap.dedent(
                f"""
                <div style="background-color:#E5E5E5; padding:30px 20px; border-radius:12px;
                            text-align:center; margin-bottom:20px; border:1px solid #CFCFCF;">
                  <div style="font-size:18px; color:#333333; margin-bottom:4px;">
                    FI independence age
                  </div>
                  <div style="font-size:72px; font-weight:700; color:#000000; line-height:1.05;">
                    {fi_age}
                  </div>
                  <div style="font-size:16px; color:#444444; margin-top:14px;">
                    FI target at age {retirement_age}: ${fi_required:,.0f} &bull;
                    Portfolio at traditional FI age (FI path): ${fi_portfolio:,.0f}
                  </div>
                  <div style="font-size:14px; color:#555555; margin-top:6px;">
                    SWR at traditional FI age: {effective_swr*100:.2f}% &bull;
                    Horizon: ~{horizon_years:.0f} years (FI age {fi_age} → {retirement_age})<br>
                    Base SWR input: {base_swr_30yr*100:.2f}%
                  </div>
                </div>
                """
            )
            st.markdown(fi_card_html, unsafe_allow_html=True)
        else:
            fi_card_html = textwrap.dedent(
                """
                <div style="background-color:#F5F5F5; padding:24px 18px; border-radius:12px;
                            text-align:center; margin-bottom:20px; border:1px solid #E0E0E0;">
                  <div style="font-size:16px; color:#555555;">
                    FI independence age not reachable under current assumptions.
                  </div>
                </div>
                """
            )
            st.markdown(fi_card_html, unsafe_allow_html=True)

        # Barista KPI card
        if use_barista and barista_age is not None:
            if taxable_ratio_rec is not None:
                summary_line = (
                    f"Bridge duration: ~{barista_bridge_years:.0f} years "
                    f"(age {barista_age} → {retirement_age}). "
                    f"PV of withdrawals during bridge: "
                    f"${barista_pv_bridge_need_real:,.0f} in today's dollars "
                    f"(~{taxable_ratio_rec*100:.0f}% of portfolio at part-time age)."
                )
            else:
                summary_line = (
                    f"Bridge duration: ~{barista_bridge_years:.0f} years "
                    f"(age {barista_age} → {retirement_age})."
                )

            barista_card_html = textwrap.dedent(
                f"""
                <div style="background-color:#F0EFEF; padding:26px 20px; border-radius:12px;
                            text-align:center; margin-bottom:20px; border:1px solid #CFCFCF;">
                  <div style="font-size:20px; color:#333333; margin-bottom:4px;">
                    Part Time Work FI Independence Age
                  </div>
                  <div style="font-size:64px; font-weight:700; color:#000000; line-height:1.05;">
                    {barista_age}
                  </div>
                  <div style="font-size:15px; color:#444444; margin-top:12px;">
                    {summary_line}
                  </div>
                </div>
                """
            )
            st.markdown(barista_card_html, unsafe_allow_html=True)
        elif use_barista:
            barista_card_html = textwrap.dedent(
                """
                <div style="background-color:#F7F7F7; padding:24px 18px; border-radius:12px;
                            text-align:center; margin-bottom:20px; border:1px solid #E0E0E0;">
                  <div style="font-size:15px; color:#555555;">
                    Part-time FI bridge not reachable under current assumptions.
                  </div>
                </div>
                """
            )
            st.markdown(barista_card_html, unsafe_allow_html=True)

    # =====================================================
    # Chart path: choose stop-work age and overlay FI/Barista withdrawals
    # =====================================================
    with main_left:
        st.markdown("### Net worth chart assumptions")

        stop_options = []
        stop_ages = []

        # Traditional
        stop_options.append("Traditional FI age slider")
        stop_ages.append(retirement_age)

        # FI age
        if fi_age is not None:
            stop_options.append("FI independence age")
            stop_ages.append(fi_age)

        # Barista
        if use_barista and barista_age is not None:
            stop_options.append("Part Time Work FI Independence Age")
            stop_ages.append(barista_age)

        stop_choice = st.selectbox(
            "Net worth chart assumes you stop full-time work at:",
            options=stop_options,
            index=0,
        )

    stop_work_age_for_chart = stop_ages[stop_options.index(stop_choice)]

    # Contributions for chart path: 0 after chosen stop age
    monthly_contrib_by_year_chart = []
    for y in range(years_full):
        age = current_age + y
        if age < stop_work_age_for_chart:
            monthly_contrib_by_year_chart.append(monthly_contrib_by_year_full[y])
        else:
            monthly_contrib_by_year_chart.append(0.0)

    # Expenses for chart path: base non-FI expenses + FI/Barista withdrawals as needed
    annual_expense_by_year_chart = annual_expense_by_year_nominal_full.copy()

    def withdraw_nominal_from_real(real_amount, year_index):
        if real_amount <= 0:
            return 0.0
        if infl_rate > 0:
            return real_amount * ((1 + infl_rate) ** year_index)
        else:
            return real_amount

    # FI overlay
    if stop_choice == "FI independence age" and fi_age is not None:
        for y in range(years_full):
            age = current_age + y
            if age >= fi_age and age <= retirement_age:
                base_real = fi_annual_spend_today + max(extra_health_today, 0.0)
                if barista_tax_rate_bridge > 0:
                    gross_real = base_real / (1 - barista_tax_rate_bridge)
                else:
                    gross_real = base_real
                annual_expense_by_year_chart[y] += withdraw_nominal_from_real(
                    gross_real, y
                )

    # Barista overlay
    elif (
        stop_choice == "Part Time Work FI Independence Age"
        and use_barista
        and barista_age is not None
    ):
        for y in range(years_full):
            age = current_age + y
            if age < barista_age or age > retirement_age:
                continue

            if age <= barista_end_age:
                spend_real = max(fi_annual_spend_today - barista_income_today, 0.0)
            else:
                spend_real = fi_annual_spend_today

            spend_real += max(extra_health_today, 0.0)

            if barista_tax_rate_bridge > 0:
                gross_real = spend_real / (1 - barista_tax_rate_bridge)
            else:
                gross_real = spend_real

            annual_expense_by_year_chart[y] += withdraw_nominal_from_real(
                gross_real, y
            )

    # =====================================================
    # Chart path simulation
    # =====================================================
    df_full_chart = compound_schedule(
        start_balance=start_balance_effective,
        years=years_full,
        monthly_contrib_by_year=monthly_contrib_by_year_chart,
        annual_expense_by_year=annual_expense_by_year_chart,
        annual_rate_by_year=annual_rates_by_year_full,
    )

    df_full_chart["Age"] = current_age + df_full_chart["Year"]
    df_full_chart["HomePrice"] = home_price_by_year_full
    df_full_chart["HomeEquity"] = home_equity_by_year_full
    df_full_chart["NetWorth"] = df_full_chart["Balance"] + df_full_chart["HomeEquity"]
    df_full_chart["HousingDelta"] = housing_adj_by_year_full

    if show_real and infl_rate > 0:
        df_full_chart["DF_end"] = (1 + infl_rate) ** df_full_chart["Year"]
        df_full_chart["DF_mid"] = (1 + infl_rate) ** (df_full_chart["Year"] - 1)
        for col in [
            "Balance",
            "InvestGrowth",
            "InvestGrowthYear",
            "HomePrice",
            "HomeEquity",
            "NetWorth",
            "CumContributions",
            "ExpenseDrag",
            "CumulativeExpense",
            "NetGrowth",
            "AnnualExpense",
        ]:
            df_full_chart[col] = df_full_chart[col] / df_full_chart["DF_end"]
    else:
        df_full_chart["DF_end"] = 1.0
        df_full_chart["DF_mid"] = 1.0

    # Net contributions in same unit (real or nominal)
    df_full_chart["NetContributions"] = (
        df_full_chart["CumContributions"] + df_full_chart["ExpenseDrag"]
    )

    # Clip chart to retirement age
    df_plot = df_full_chart[df_full_chart["Age"] <= retirement_age].reset_index(drop=True)

    # =====================================================
    # Net worth chart
    # =====================================================
    with main_left:
        st.markdown("### Net worth over time" + label_suffix)

        color_net_contrib = "#C8A77A"  # brown-ish
        color_invest_growth = "#3A6EA5"  # blue
        color_home = "#A7ADB2"  # grey

        fig = go.Figure()

        fig.add_trace(
            go.Bar(
                x=df_plot["Age"],
                y=df_plot["NetContributions"],
                name="Net contributions (incl. expense drag)",
                marker=dict(color=color_net_contrib),
                hovertemplate="Age %{x}<br>Net Contributions: $%{y:,.0f}<extra></extra>",
            )
        )

        fig.add_trace(
            go.Bar(
                x=df_plot["Age"],
                y=df_plot["InvestGrowth"],
                name="Investment growth (cumulative)",
                marker=dict(color=color_invest_growth),
                hovertemplate="Age %{x}<br>Investment Growth: $%{y:,.0f}<extra></extra>",
            )
        )

        if include_home:
            fig.add_trace(
                go.Bar(
                    x=df_plot["Age"],
                    y=df_plot["HomeEquity"],
                    name="Home equity",
                    marker=dict(color=color_home),
                    hovertemplate="Age %{x}<br>Home Equity: $%{y:,.0f}<extra></extra>",
                )
            )

        # First $1M net worth marker
        highlight_mask = df_plot["NetWorth"] >= 1_000_000
        if highlight_mask.any():
            first_million_index = highlight_mask.idxmax()
            age_million = df_plot.loc[first_million_index, "Age"]
            networth_million = df_plot.loc[first_million_index, "NetWorth"]
            fig.add_trace(
                go.Scatter(
                    x=[age_million],
                    y=[networth_million],
                    mode="markers+text",
                    marker=dict(size=12, symbol="circle"),
                    text=["$1M+"],
                    textposition="top center",
                    name="First $1M",
                    hovertemplate="First $1M at age %{x}<extra></extra>",
                )
            )

        fig.update_layout(
            barmode="relative",
            xaxis_title="Age",
            yaxis_title="Net worth" + label_suffix,
            showlegend=True,
            hovermode="x unified",
            margin=dict(l=40, r=30, t=40, b=40),
        )
        fig.update_yaxes(rangemode="tozero")

        st.plotly_chart(fig, use_container_width=True)

    # =====================================================
    # Income trajectory + returns line charts
    # =====================================================
    with main_left:
        st.markdown("### Income and expected return by age")

        df_income_plot = df_income.copy()
        df_income_plot["Age"] = df_income_plot["Age"]

        df_returns_plot = pd.DataFrame(
            {
                "Age": ages,
                "AnnualReturn": [r * 100 for r in annual_rates_by_year_full],
            }
        )

        fig_income = go.Figure()
        fig_income.add_trace(
            go.Scatter(
                x=df_income_plot["Age"],
                y=df_income_plot["IncomeNominal"],
                mode="lines",
                name="Pre-tax income (nominal)",
                hovertemplate="Age %{x}<br>Income: $%{y:,.0f}<extra></extra>",
            )
        )

        fig_income.update_layout(
            xaxis_title="Age",
            yaxis_title="Income ($/year, nominal)",
            hovermode="x unified",
            showlegend=True,
            margin=dict(l=40, r=30, t=40, b=40),
        )
        fig_income.update_yaxes(rangemode="tozero")

        st.plotly_chart(fig_income, use_container_width=True)

        fig_returns = go.Figure()
        fig_returns.add_trace(
            go.Scatter(
                x=df_returns_plot["Age"],
                y=df_returns_plot["AnnualReturn"],
                mode="lines",
                name="Annual return (nominal, glide path)",
                hovertemplate="Age %{x}<br>Return: %{y:.2f}%<extra></extra>",
            )
        )

        fig_returns.update_layout(
            xaxis_title="Age",
            yaxis_title="Expected annual return (%)",
            hovermode="x unified",
            showlegend=True,
            margin=dict(l=40, r=30, t=40, b=40),
        )
        fig_returns.update_yaxes(rangemode="tozero")

        st.plotly_chart(fig_returns, use_container_width=True)

    # =====================================================
    # Detailed projection table (chart path)
    # =====================================================
    with main_left:
        st.markdown("### Detailed projection table (chart path)")

        df_table = df_plot[
            [
                "Age",
                "Balance",
                "HomeEquity",
                "NetWorth",
                "CumContributions",
                "InvestGrowth",
                "ExpenseDrag",
                "CumulativeExpense",
                "AnnualExpense",
            ]
        ].copy()

        df_table.columns = [
            "Age",
            "Portfolio",
            "Home equity",
            "Net worth",
            "Cumulative contributions",
            "Investment growth (cum)",
            "Expense drag (cum)",
            "Cumulative expenses",
            "Annual expenses (incl. FI / Barista withdrawals)",
        ]

        st.dataframe(df_table.style.format("{:,.0f}", subset=df_table.columns[1:]))

    # =====================================================
    # Key assumptions text
    # =====================================================
    with main_left:
        st.markdown("### Key assumptions")

        assumptions = []

        assumptions.append(
            f"- FI target is always FI spending / base SWR at the traditional FI age "
            f"({retirement_age}), in today's dollars."
        )

        if fi_age is not None:
            assumptions.append(
                f"- FI independence age {fi_age}: you stop full-time work at this age, "
                f"set new contributions to $0, and withdraw FI spending + extra health "
                f"(grossed up for the specified withdrawal tax rate) each year until "
                f"traditional FI age {retirement_age}."
            )

        if use_barista and barista_age is not None:
            assumptions.append(
                f"- Part-time bridge: Barista FI math models withdrawals needed to cover "
                f"the gap between spending and part-time income from age {barista_age} "
                f"to {retirement_age}, including extra health costs and the specified "
                f"withdrawal tax rate."
            )

        if assumptions:
            st.markdown("**Key assumptions & notes**")
            st.markdown("\n".join(assumptions))


if __name__ == "__main__":
    main()
