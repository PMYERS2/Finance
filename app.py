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

        # monthly contributions + growth
        for _ in range(m):
            monthly_contrib = monthly_contrib_by_year[year_idx]
            balance += monthly_contrib
            cum_contrib += monthly_contrib
            contrib_year += monthly_contrib

            growth_month = balance * (r / m)
            balance += growth_month

        balance_before_expense = balance
        annual_expense = annual_expense_by_year[year_idx]

        # track investment growth (before expenses)
        market_growth_year = balance_before_expense - (balance_start_year + contrib_year)
        cum_invest_growth += market_growth_year

        # track expense drag
        expense_drag_year = -annual_expense
        cum_expense_drag += expense_drag_year

        # take expenses at year end
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
    """
    Scan the full portfolio path and find the first age where
    portfolio >= FI spending target * horizon-aware multiple.
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
    annual_rates_by_year_full,
    base_30yr_swr,
    barista_end_age,
    full_fi_age,
    tax_rate_bridge=0.0,
    extra_health_today=0.0,
):
    """
    Compute earliest "Barista FI Age" such that:

    - You stop contributions at barista_age and work part-time.
    - Portfolio covers (Spending - BaristaIncome + ExtraHealth) until full_fi_age.
    - At full_fi_age, remaining portfolio >= FI target (real).

    Uses df (full path) only for portfolio level at each candidate start age.
    """
    S = fi_annual_spend_today
    B = barista_income_today

    if S <= 0 or base_30yr_swr <= 0:
        return None, None, None, None, None, None

    t = max(0.0, min(tax_rate_bridge, 0.7))

    # Map age -> real portfolio
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

    # Real FI target (anchor for Barista bridge)
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

        # simulate real withdrawals/no contributions until full_fi_age
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
            pv_bridge_need
