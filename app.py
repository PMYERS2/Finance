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

    Tracks:
      - CumContributions: cumulative contributions
      - ContribYear: contributions during that year
      - InvestGrowth: cumulative market return BEFORE expenses
      - InvestGrowthYear: market return during that year
      - ExpenseDrag: cumulative negative impact of expenses
      - NetGrowth: InvestGrowth + ExpenseDrag
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


def compute_fi_age(df, fi_annual_spend_today, infl_rate, show_real, swr):
    """
    Compute FI age for a given SWR using investment portfolio ONLY (Balance).
    Home equity is intentionally ignored here.

    Returns (fi_age, fi_portfolio, fi_required) or (None, None, None).
    """
    if swr <= 0 or fi_annual_spend_today <= 0:
        return None, None, None

    fi_multiple = 1.0 / swr

    if show_real and infl_rate > 0:
        required_by_year = [
            fi_annual_spend_today * fi_multiple for _ in df["Year"]
        ]
    else:
        required_by_year = [
            fi_annual_spend_today * ((1 + infl_rate) ** year) * fi_multiple
            for year in df["Year"]
        ]

    fi_age = None
    fi_portfolio = None
    fi_required = None

    for age, year, pv, req in zip(
        df["Age"], df["Year"], df["Balance"], required_by_year
    ):
        if pv >= req:
            fi_age = int(age)
            fi_portfolio = pv
            fi_required = req
            break

    return fi_age, fi_portfolio, fi_required


# =========================================================
# Page setup
# =========================================================
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

retirement_age = st.sidebar.number_input(
    "Retirement age (years)",
    value=60,
    min_value=1,
    max_value=100,
    step=1,
)

years = retirement_age - current_age
if years <= 0:
    st.error("Retirement age must be greater than current age.")
    st.stop()

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
    value=10.0,   # base 10%
    step=0.5,
) / 100.0

contrib_frequency = st.sidebar.radio(
    "Contribution frequency",
    ("Monthly", "Annual"),
    index=0,
)

contrib_amount = st.sidebar.number_input(
    f"{contrib_frequency} contribution amount ($)",
    value=1000,   # base $1,000
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
            max_value=retirement_age,
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
# Build per-year contribution and expense schedules (nominal)
# =========================================================
monthly_contrib_by_year = [
    monthly_contrib_base_today * (1 + contrib_growth_rate) ** y * (1 + infl_rate) ** y
    for y in range(years)
]

annual_expense_by_year_nominal = [0.0 for _ in range(years)]

# Home arrays
home_price_by_year = [0.0 for _ in range(years)]   # market price
home_equity_by_year = [0.0 for _ in range(years)]  # equity that counts to net worth

# Start balance (may be hit by an immediate down payment)
start_balance_effective = start_balance_input

# Kid expenses
for year_idx in range(years):
    age_end_of_year = current_age + year_idx + 1
    if use_kid_expenses:
        if kids_start_age <= age_end_of_year <= kids_end_age:
            expense_real = num_kids * annual_cost_per_kid_today
            expense_nominal = expense_real * ((1 + infl_rate) ** (year_idx + 1))
            annual_expense_by_year_nominal[year_idx] += expense_nominal

# Car expenses
for year_idx in range(years):
    age_end_of_year = current_age + year_idx + 1
    if use_car_expenses and car_interval_years and car_interval_years > 0:
        if age_end_of_year >= first_car_age:
            if (age_end_of_year - first_car_age) % car_interval_years == 0:
                expense_real = car_cost_today
                expense_nominal = expense_real * ((1 + infl_rate) ** (year_idx + 1))
                annual_expense_by_year_nominal[year_idx] += expense_nominal

# Home: equity, maintenance, and possible down payment
if include_home:
    if home_status == "I already own a home":
        base_price_today = current_home_value_today
        purchase_idx = 0

        outstanding_now = max(base_price_today - equity_amount_now, 0.0)
        loan_amount = outstanding_now
        years_until_purchase = 0

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

    for year_idx in range(years):
        years_from_now = year_idx + 1
        price_nominal = base_price_today * ((1 + home_app_rate) ** years_from_now)

        if year_idx >= purchase_idx:
            home_price_by_year[year_idx] = price_nominal
        else:
            home_price_by_year[year_idx] = 0.0

        if loan_amount <= 0 or n_payments == 0:
            if year_idx >= purchase_idx:
                home_equity_by_year[year_idx] = price_nominal
            else:
                home_equity_by_year[year_idx] = 0.0
        else:
            if year_idx < purchase_idx:
                home_equity_by_year[year_idx] = 0.0
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
                home_equity_by_year[year_idx] = equity

        if year_idx >= purchase_idx:
            maint_nominal = price_nominal * maintenance_pct
            annual_expense_by_year_nominal[year_idx] += maint_nominal

    if home_status == "I plan to buy":
        if purchase_idx < years:
            down_payment_nominal = purchase_price_nominal * down_payment_pct

            if planned_purchase_age == current_age:
                start_balance_effective = max(
                    0.0, start_balance_effective - down_payment_nominal
                )
            else:
                annual_expense_by_year_nominal[purchase_idx] += down_payment_nominal

# Housing cost delta: (mortgage + property tax) vs current rent
housing_adj_by_year = [0.0 for _ in range(years)]

if (
    include_home
    and home_status == "I plan to buy"
    and mortgage_payment > 0
):
    total_monthly_owner_cost = mortgage_payment + est_prop_tax_monthly
    extra_housing_monthly = total_monthly_owner_cost - current_rent  # + or -
    for year_idx in range(years):
        if year_idx >= purchase_idx:
            housing_adj_by_year[year_idx] = extra_housing_monthly * 12  # annual delta

# Add housing delta into annual expenses
for y in range(years):
    annual_expense_by_year_nominal[y] += housing_adj_by_year[y]

# =========================================================
# Base scenario (nominal)
# =========================================================
df = compound_schedule(
    start_balance=start_balance_effective,
    annual_rate=annual_rate,
    years=years,
    monthly_contrib_by_year=monthly_contrib_by_year,
    annual_expense_by_year=annual_expense_by_year_nominal,
)

df["Age"] = current_age + df["Year"]
df["HomePrice"] = home_price_by_year
df["HomeEquity"] = home_equity_by_year
df["NetWorth"] = df["Balance"] + df["HomeEquity"]
df["HousingDelta"] = housing_adj_by_year

# Net contributions (nominal)
df["NetContributions"] = df["CumContributions"] + df["ExpenseDrag"]

# =========================================================
# Real-dollar adjustment
# =========================================================
if show_real and infl_rate > 0:
    df["DF_end"] = (1 + infl_rate) ** df["Year"]
    df["DF_mid"] = (1 + infl_rate) ** (df["Year"] - 1)

    for col in [
        "Balance",
        "InvestGrowth",
        "InvestGrowthYear",
        "HomePrice",
        "HomeEquity",
        "NetWorth",
    ]:
        df[col] = df[col] / df["DF_end"]

    df["ContribYear"] = df["ContribYear"] / df["DF_mid"]
    df["AnnualExpense"] = df["AnnualExpense"] / df["DF_end"]
    df["HousingDelta"] = df["HousingDelta"] / df["DF_end"]

    cum_contrib_real = 0.0
    cum_expense_drag_real = 0.0
    cum_expense_abs_real = 0.0
    net_contrib_cum_real = 0.0

    for idx in range(len(df)):
        c = df.loc[idx, "ContribYear"]
        e = df.loc[idx, "AnnualExpense"]

        cum_contrib_real += c
        cum_expense_drag_real += -e
        cum_expense_abs_real += e
        net_contrib_cum_real = cum_contrib_real + cum_expense_drag_real

        df.loc[idx, "CumContributions"] = cum_contrib_real
        df.loc[idx, "ExpenseDrag"] = cum_expense_drag_real
        df.loc[idx, "CumulativeExpense"] = cum_expense_abs_real
        df.loc[idx, "NetContributions"] = net_contrib_cum_real

else:
    df["DF_end"] = 1.0
    df["DF_mid"] = 1.0

ending_net_worth = df["NetWorth"].iloc[-1]
ending_invest_balance = df["Balance"].iloc[-1]

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
        "This is the '4% rule' style input. The planner auto-adjusts the actual "
        "withdrawal rate based on how many years remain until age 90."
    )

    # Barista FIRE controls
    use_barista = st.checkbox(
        "Show Barista FIRE scenario (part-time income in FI)",
        value=False,
        key="barista_toggle",
    )

    barista_income_today = 0.0
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
            max_value=90,
            step=1,
            key="barista_end_age",
        )

    fi_age = None
    fi_portfolio = None
    fi_required = None
    effective_swr = None
    horizon_years = None

    barista_age = None
    barista_portfolio = None
    barista_required = None
    barista_effective_swr = None
    barista_horizon_years = None

    if fi_annual_spend_today > 0 and base_swr_30yr > 0:
        # ---- Full FI (no earned income) ----
        # Start with the user's base SWR, independent of retirement_age
        swr0 = base_swr_30yr

        fi_age0, fi_pv0, fi_req0 = compute_fi_age(
            df, fi_annual_spend_today, infl_rate, show_real, swr0
        )

        if fi_age0 is not None:
            horizon0 = max(90 - fi_age0, 1)
            swr1 = adjusted_swr_for_horizon(horizon0, base_30yr_swr=base_swr_30yr)

            if abs(swr1 - swr0) > 1e-4:
                fi_age1, fi_pv1, fi_req1 = compute_fi_age(
                    df, fi_annual_spend_today, infl_rate, show_real, swr1
                )
                if fi_age1 is not None:
                    fi_age, fi_portfolio, fi_required = fi_age1, fi_pv1, fi_req1
                    horizon_years = max(90 - fi_age1, 1)
                    effective_swr = swr1
                else:
                    fi_age, fi_portfolio, fi_required = fi_age0, fi_pv0, fi_req0
                    horizon_years = horizon0
                    effective_swr = swr0
            else:
                fi_age, fi_portfolio, fi_required = fi_age0, fi_pv0, fi_req0
                horizon_years = horizon0
                effective_swr = swr0

        # ---- Barista FI (part-time income only until barista_end_age) ----
        if use_barista and barista_income_today > 0:
            S = fi_annual_spend_today
            B = barista_income_today

            for row in df.itertuples():
                age = row.Age
                year = row.Year
                balance = row.Balance

                if age >= 90:
                    continue

                T = max(90 - age, 1)  # total horizon from this age to 90
                T_barista = max(0, min(T, barista_end_age - age))

                # Effective average required spending from portfolio over the full horizon
                S_eff_today = S - (B * T_barista / T)

                if S_eff_today <= 0:
                    # Barista income alone covers spending; treat this as immediate barista FI
                    barista_age = int(age)
                    barista_portfolio = balance
                    barista_required = 0.0
                    barista_horizon_years = T
                    barista_effective_swr = adjusted_swr_for_horizon(
                        T, base_30yr_swr=base_swr_30yr
                    )
                    break

                swr_i = adjusted_swr_for_horizon(T, base_30yr_swr=base_swr_30yr)
                multiple_i = 1.0 / swr_i

                if show_real and infl_rate > 0:
                    required_portfolio_i = S_eff_today * multiple_i
                else:
                    required_portfolio_i = (
                        S_eff_today * ((1 + infl_rate) ** year) * multiple_i
                    )

                if balance >= required_portfolio_i:
                    barista_age = int(age)
                    barista_portfolio = balance
                    barista_required = required_portfolio_i
                    barista_horizon_years = T
                    barista_effective_swr = swr_i
                    break

    if fi_age is not None:
        # Optional Barista line
        if use_barista and barista_age is not None:
            barista_line = (
                f"Barista FI age with ${barista_income_today:,.0f}/yr earned until age {barista_end_age}: "
                f"{barista_age}"
            )
        elif use_barista:
            barista_line = (
                f"Barista FI age with ${barista_income_today:,.0f}/yr earned until age {barista_end_age}: not reached"
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
                Horizon: ~{horizon_years:.0f} years (to age 90)<br>
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
            "With the current assumptions and horizon-aware withdrawal rate, "
            "FI is not reached before your retirement age."
        )

# -----------------------------
# LEFT COLUMN: main content
# -----------------------------
with main_left:
    st.subheader(f"Ending net worth: ${ending_net_worth:,.0f}{label_suffix}")
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
        "- Financial independence age is calculated using your investment portfolio only "
        "(home equity is excluded from FI calculations)."
    )

    if use_barista:
        assumptions.append(
            f"- Barista FIRE: assumes part-time income of `${barista_income_today:,.0f}`/year "
            f"until age {barista_end_age}; portfolio withdrawals are reduced during those years."
        )

    if assumptions:
        st.markdown("**Key assumptions & notes**")
        st.markdown("\n".join(assumptions))

    # Chart: Net contributions + investment growth + home equity
    color_net_contrib = "#C8A77A"
    color_invest_growth = "#3A6EA5"
    color_home = "#A7ADB2"

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df["Age"],
            y=df["NetContributions"],
            name="Net contributions (after expenses)",
            marker_color=color_net_contrib,
            hovertemplate="Age %{x}<br>Net contributions: $%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=df["Age"],
            y=df["InvestGrowth"],
            name="Investment growth (cumulative)",
            marker_color=color_invest_growth,
            hovertemplate="Age %{x}<br>Investment growth: $%{y:,.0f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=df["Age"],
            y=df["HomeEquity"],
            name="Home equity",
            marker_color=color_home,
            hovertemplate="Age %{x}<br>Home equity: $%{y:,.0f}<extra></extra>",
        )
    )

    ages = df["Age"].tolist()
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
            pad=dict(b=10),  # padding below title
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=40, r=40, t=60, b=60),
        xaxis=dict(
            title=dict(text="Age (years)", font=dict(size=14)),
            tickfont=dict(size=12),
            showgrid=False,
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
        ),
        yaxis=dict(
            title=dict(text="Amount ($)", font=dict(size=14)),
            tickfont=dict(size=12),
            showgrid=True,
            gridcolor="#E0E0E0",
            tickprefix="$",
            tickformat=",.0f",
            separatethousands=True,
            exponentformat="none",
            showexponent="none",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=0.96,  # move legend slightly down from title
            xanchor="center",
            x=0.5,
            font=dict(size=12),
        ),
    )

    # minimal annotation on last bar, slightly above the stack
    stacked_heights = (
        df["NetContributions"] + df["InvestGrowth"] + df["HomeEquity"]
    )
    last_age = df["Age"].iloc[-1]
    last_bar_height = stacked_heights.iloc[-1]
    max_bar_height = stacked_heights.max()
    label_y = last_bar_height + max_bar_height * 0.03  # 3% above bar

    fig.add_annotation(
    x=last_age,
    y=label_y,
    text=f"${ending_net_worth:,.0f}",
    showarrow=False,
    font=dict(size=14, color="black",weight="bold"),
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
        monthly_contrib_by_year_more = [
            c + extra_per_month * (1 + infl_rate) ** y
            for y, c in enumerate(monthly_contrib_by_year)
        ]

        df_more = compound_schedule(
            start_balance=start_balance_effective,
            annual_rate=annual_rate,
            years=years,
            monthly_contrib_by_year=monthly_contrib_by_year_more,
            annual_expense_by_year=annual_expense_by_year_nominal,
        )
        df_more["HomeEquity"] = home_equity_by_year
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

    # Age-by-age table
    st.markdown("### Age-by-age breakdown")

    display_df = df.copy()
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



