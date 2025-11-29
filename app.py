import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# -----------------------------
# Core compound interest logic
# -----------------------------
def compound_schedule(
    start_balance,
    annual_rate,
    years,
    monthly_contrib_by_year,
    annual_expense_by_year,
):
    """
    Simulate investment account with monthly compounding and annual expenses.

    monthly_contrib_by_year: list length = years, monthly contribution for each year
    annual_expense_by_year:  list length = years, nominal $ expense taken at year-end

    We track:
      - CumContributions (cumulative contributions)
      - ContribYear      (contributions during that year)
      - InvestGrowth     (cumulative market return BEFORE expenses)
      - InvestGrowthYear (market return during that year)
      - ExpenseDrag      (cumulative negative impact of expenses)
      - NetGrowth        = InvestGrowth + ExpenseDrag
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
        # State at beginning of year
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

        # Pure investment growth for this year (before expenses)
        market_growth_year = balance_before_expense - (balance_start_year + contrib_year)
        cum_invest_growth += market_growth_year

        # Expense drag for this year
        expense_drag_year = -annual_expense
        cum_expense_drag += expense_drag_year

        # Apply expenses to balance
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


# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(page_title="Compound Interest Calculator", layout="wide")
st.title("Compound Interest Calculator")

# -----------------------------
# LEFT SIDEBAR: Core Inputs
# -----------------------------
st.sidebar.header("Core Inputs")

current_age = st.sidebar.number_input(
    "Current Age",
    value=26,
    min_value=0,
    max_value=100,
    step=1,
)

retirement_age = st.sidebar.number_input(
    "Retirement Age",
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
    "Starting Amount ($)", value=100000, step=1000, min_value=0
)

annual_rate = st.sidebar.slider(
    "Annual Rate of Return (%)",
    min_value=0.0,
    max_value=20.0,
    value=9.0,
    step=0.5,          # half-percent increments
) / 100.0

contrib_frequency = st.sidebar.radio(
    "Contribution Frequency", ("Monthly", "Annual"), index=0
)

contrib_amount = st.sidebar.number_input(
    f"{contrib_frequency} Contribution Amount ($)",
    value=2500.0,
    step=100.0,
    min_value=0.0,
)

# Convert to monthly contribution based on frequency
if contrib_frequency == "Monthly":
    monthly_contrib_base = contrib_amount
else:
    monthly_contrib_base = contrib_amount / 12.0

# Automatic annual contribution growth (real; on top of inflation)
contrib_growth_rate = st.sidebar.number_input(
    "Contribution growth rate (%/yr)",
    value=0.0,
    step=0.5,
    min_value=0.0,
    max_value=20.0,
) / 100.0

infl_rate = st.sidebar.number_input(
    "Assumed annual inflation rate (%)",
    value=3.0,
    step=0.1,
    min_value=0.0,
    max_value=20.0,
) / 100.0

show_real = st.sidebar.checkbox("Show values in today's dollars (inflation-adjusted)")

# -----------------------------
# MAIN LAYOUT: center + RIGHT CARD PANEL
# -----------------------------
main_left, main_right = st.columns([4, 1.7])

# RIGHT CARD PANEL: Additional customization inputs (including home)
with main_right:
    st.markdown(
        """
        <div style="
            background-color:#111827;
            padding:16px;
            border-radius:12px;
            border:1px solid #374151;
        ">
        """,
        unsafe_allow_html=True,
    )

    st.header("Additional Customization")

    extra_per_month = st.number_input(
        "Extra saved per month (scenario)",
        value=100.0,
        step=50.0,
        min_value=0.0,
        key="extra_per_month",
    )

    st.markdown("<hr>", unsafe_allow_html=True)
    st.subheader("Future Expenses (today's $)")

    # Kid-related expenses
    use_kid_expenses = st.checkbox("Add kid-related annual expenses", key="kid_exp")

    if use_kid_expenses:
        default_kid_start = current_age + 2
        default_kid_end = min(retirement_age, default_kid_start + 18)

        kids_start_age = st.number_input(
            "Kid expense start age",
            value=default_kid_start,
            min_value=current_age + 1,
            max_value=retirement_age,
            step=1,
            key="kids_start_age",
        )
        kids_end_age = st.number_input(
            "Kid expense end age",
            value=default_kid_end,
            min_value=kids_start_age,
            max_value=retirement_age,
            step=1,
            key="kids_end_age",
        )
        num_kids = st.number_input(
            "Number of kids",
            value=2,
            min_value=1,
            max_value=10,
            step=1,
            key="num_kids",
        )
        annual_cost_per_kid_today = st.number_input(
            "Annual cost per kid (today's $)",
            value=10000.0,
            step=1000.0,
            min_value=0.0,
            key="kid_cost",
        )
    else:
        kids_start_age = kids_end_age = num_kids = annual_cost_per_kid_today = None

    # Car replacement expenses
    use_car_expenses = st.checkbox("Add car replacement expenses", key="car_exp")

    if use_car_expenses:
        car_cost_today = st.number_input(
            "Cost per car (today's $)",
            value=30000.0,
            step=1000.0,
            min_value=0.0,
            key="car_cost",
        )
        first_car_age = st.number_input(
            "First replacement age",
            value=current_age + 5,
            min_value=current_age + 1,
            max_value=retirement_age,
            step=1,
            key="first_car_age",
        )
        car_interval_years = st.number_input(
            "Replacement interval (years)",
            value=8,
            min_value=1,
            max_value=50,
            step=1,
            key="car_interval",
        )
    else:
        car_cost_today = first_car_age = car_interval_years = None

    st.markdown("<hr>", unsafe_allow_html=True)
    st.subheader("Home")

    include_home = st.checkbox("Include home in plan", key="home_toggle")

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

    if include_home:
        home_app_rate = st.number_input(
            "Home appreciation rate (%/yr)",
            value=3.0,
            step=0.1,
            min_value=-10.0,
            max_value=20.0,
            key="home_app_rate",
        ) / 100.0

        maintenance_pct = st.number_input(
            "Annual maintenance (% of home value)",
            value=1.0,
            step=0.1,
            min_value=0.0,
            max_value=10.0,
            key="maint_pct",
        ) / 100.0

        home_status = st.radio(
            "Home status",
            ["I already own a home", "I plan to buy"],
            index=0,
            key="home_status",
        )

        if home_status == "I already own a home":
            current_home_value_today = st.number_input(
                "Current home value (today's $)",
                value=400000.0,
                step=10000.0,
                min_value=0.0,
                key="home_value_now",
            )

            equity_amount_now = st.number_input(
                "Current home equity you own ($)",
                value=120000.0,
                step=10000.0,
                min_value=0.0,
                key="equity_amount_now",
            )

            years_remaining_loan = st.number_input(
                "Years remaining on mortgage",
                value=25,
                min_value=0,
                max_value=40,
                step=1,
                key="years_remaining_loan",
            )

            mortgage_rate = st.number_input(
                "Mortgage interest rate (%/yr)",
                value=6.5,
                step=0.1,
                min_value=0.0,
                max_value=20.0,
                key="mort_rate_own",
            ) / 100.0

        else:  # plan to buy with mortgage
            home_price_today = st.number_input(
                "Target home price (today's $)",
                value=400000.0,
                step=10000.0,
                min_value=0.0,
                key="target_home_price",
            )
            planned_purchase_age = st.number_input(
                "Planned purchase age",
                value=current_age,
                min_value=current_age,
                max_value=retirement_age,
                step=1,
                key="purchase_age",
            )
            down_payment_pct = st.number_input(
                "Down payment (%)",
                value=20.0,
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                key="dp_pct",
            ) / 100.0

            mortgage_rate = st.number_input(
                "Mortgage interest rate (%/yr)",
                value=6.5,
                step=0.1,
                min_value=0.0,
                max_value=20.0,
                key="mort_rate_buy",
            ) / 100.0

            mortgage_term_years = st.radio(
                "Loan term (years)",
                [15, 30],
                index=1,
                key="mort_term",
            )

    st.markdown("<hr>", unsafe_allow_html=True)
    st.subheader("What if you saved more?")
    metric_placeholder = st.empty()  # filled after calculations

    st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------
# Build per-year contribution and expense schedules
# -----------------------------

# Automatic annual growth on contributions in nominal terms:
# - monthly_contrib_base is "today's dollars" at Year 1
# - each year we inflate by inflation and real growth
monthly_contrib_by_year = [
    monthly_contrib_base * (1 + contrib_growth_rate) ** y * (1 + infl_rate) ** y
    for y in range(years)
]

annual_expense_by_year_nominal = [0.0 for _ in range(years)]

# Home arrays
home_price_by_year = [0.0 for _ in range(years)]   # market price
home_equity_by_year = [0.0 for _ in range(years)]  # equity that counts to net worth

# Start with raw starting balance; may be reduced by immediate down payment
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
    # Determine base "today" price and purchase index
    if home_status == "I already own a home":
        base_price_today = current_home_value_today
        purchase_idx = 0

        # Outstanding mortgage principal now (if any)
        outstanding_now = max(base_price_today - equity_amount_now, 0.0)

        # Treat as new loan from now with given years remaining
        loan_amount = outstanding_now
        years_until_purchase = 0  # already purchased

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

        purchase_price_nominal = base_price_today  # at t=0

    else:
        base_price_today = home_price_today
        # year index whose end-age equals planned_purchase_age
        purchase_idx = max(0, planned_purchase_age - current_age - 1)
        years_until_purchase = purchase_idx + 1

        # Price at purchase year (nominal)
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

    # Year-by-year home price and equity
    for year_idx in range(years):
        years_from_now = year_idx + 1
        price_nominal = base_price_today * ((1 + home_app_rate) ** years_from_now)

        # price exists after purchase
        if year_idx >= purchase_idx:
            home_price_by_year[year_idx] = price_nominal
        else:
            home_price_by_year[year_idx] = 0.0

        if loan_amount <= 0 or n_payments == 0:
            # no mortgage: full equity after purchase
            if year_idx >= purchase_idx:
                home_equity_by_year[year_idx] = price_nominal
            else:
                home_equity_by_year[year_idx] = 0.0
        else:
            # mortgage exists
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

        # maintenance after purchase (based on full price)
        if year_idx >= purchase_idx:
            maint_nominal = price_nominal * maintenance_pct
            annual_expense_by_year_nominal[year_idx] += maint_nominal

    # Down payment hit for "plan to buy" only
    if home_status == "I plan to buy":
        if purchase_idx < years:
            down_payment_nominal = purchase_price_nominal * down_payment_pct

            if planned_purchase_age == current_age:
                start_balance_effective = max(
                    0.0, start_balance_effective - down_payment_nominal
                )
            else:
                annual_expense_by_year_nominal[purchase_idx] += down_payment_nominal

# -----------------------------
# Base scenario
# -----------------------------
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

# Net contributions (contributions minus expenses)
df["NetContributions"] = df["CumContributions"] + df["ExpenseDrag"]

# -----------------------------
# Real-dollar adjustment
# -----------------------------
if show_real and infl_rate > 0:
    df["DiscountFactor"] = (1 + infl_rate) ** df["Year"]

    # Discount nominal pieces, including contributions and expenses
    cols_to_discount = [
        "Balance",
        "CumContributions",
        "ContribYear",
        "InvestGrowth",
        "InvestGrowthYear",
        "AnnualExpense",
        "HomePrice",
        "HomeEquity",
        "ExpenseDrag",
        "NetWorth",
    ]
    for col in cols_to_discount:
        df[col] = df[col] / df["DiscountFactor"]

    # Recompute net contributions after discounting contributions and expense drag
    df["NetContributions"] = df["CumContributions"] + df["ExpenseDrag"]
else:
    df["DiscountFactor"] = 1.0

# Home price growth per year (in displayed units)
df["HomePriceGrowthYear"] = df["HomePrice"].diff().fillna(df["HomePrice"])

ending_net_worth = df["NetWorth"].iloc[-1]
ending_invest_balance = df["Balance"].iloc[-1]

label_suffix = " (today's dollars)" if show_real and infl_rate > 0 else " (nominal)"

# -----------------------------
# MAIN CONTENT (center)
# -----------------------------
with main_left:
    st.subheader(f"Ending Net Worth: ${ending_net_worth:,.0f}{label_suffix}")
    st.caption(
        f"(Investments: ${ending_invest_balance:,.0f}, Home equity included if configured.)"
    )

    # Key assumptions
    assumptions = []

    if contrib_growth_rate > 0:
        assumptions.append(
            f"- Contributions: start at `${monthly_contrib_base:,.0f}`/month (in today's $), "
            f"growing **{contrib_growth_rate*100:.1f}%/yr** plus inflation from age {current_age} to {retirement_age}, "
            f"at **{annual_rate*100:.1f}%** return."
        )
    else:
        assumptions.append(
            f"- Contributions: `${monthly_contrib_base:,.0f}`/month (today's $), inflated each year by {infl_rate*100:.1f}% "
            f"from age {current_age} to {retirement_age} at **{annual_rate*100:.1f}%** return."
        )

    if use_kid_expenses:
        assumptions.append(
            f"- Kid expenses: ages **{kids_start_age}–{kids_end_age}**, "
            f"`{num_kids}` kid(s) at `${annual_cost_per_kid_today:,.0f}`/kid/year (today's $)."
        )
    if use_car_expenses:
        assumptions.append(
            f"- Cars: `${car_cost_today:,.0f}` (today's $) starting at age **{first_car_age}** every **{car_interval_years}** years."
        )
    if include_home:
        if home_status == "I already own a home":
            assumptions.append(
                f"- Home: currently worth `${current_home_value_today:,.0f}`, "
                f"current equity ≈ `${equity_amount_now:,.0f}`, "
                f"{years_remaining_loan} years left at **{mortgage_rate*100:.2f}%**."
            )
        else:
            assumptions.append(
                f"- Home: purchase at age **{planned_purchase_age}**, today's price `${home_price_today:,.0f}`, "
                f"down `{down_payment_pct*100:.1f}%`, {mortgage_rate*100:.2f}% mortgage over {mortgage_term_years} years, "
                f"{home_app_rate*100:.1f}%/yr appreciation, {maintenance_pct*100:.1f}% maintenance."
            )
    if show_real and infl_rate > 0:
        assumptions.append(
            f"- All values shown in today's dollars using **{infl_rate*100:.1f}%** inflation."
        )

    if assumptions:
        st.markdown("**Key assumptions**")
        st.markdown("\n".join(assumptions))

    # Chart: Net contributions + investment growth + home equity
    color_net_contrib = "#5BA68E"
    color_invest_growth = "#D9A441"
    color_home = "#4C6E91"

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

    last_age = df["Age"].iloc[-1]
    last_bar_height = (
        df["NetContributions"].iloc[-1]
        + df["InvestGrowth"].iloc[-1]
        + df["HomeEquity"].iloc[-1]
    )  # equals NetWorth at end

    fig.update_layout(
        barmode="stack",
        title=dict(
            text="Net Contributions + Investment Growth + Home Equity Over Time",
            x=0.5,
            xanchor="center",
            font=dict(size=22, color="black"),
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=40, r=40, t=60, b=60),
        xaxis=dict(
            title=dict(text="Age", font=dict(color="black", size=14)),
            tickfont=dict(color="black", size=12),
            showgrid=False,
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
        ),
        yaxis=dict(
            title=dict(text="Amount ($)", font=dict(color="black", size=14)),
            tickfont=dict(color="black", size=12),
            showgrid=True,
            gridcolor="#e5e5e5",
            tickprefix="$",
            tickformat=",.0f",
            separatethousands=True,
            exponentformat="none",
            showexponent="none",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            font=dict(color="black", size=12),
        ),
    )

    fig.add_annotation(
        x=last_age,
        y=last_bar_height,
        text=f"<b>${ending_net_worth:,.0f}</b>",
        showarrow=True,
        arrowhead=2,
        ax=0,
        ay=-40,
        font=dict(color="black", size=12),
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor="black",
        borderwidth=1,
    )

    st.plotly_chart(fig, use_container_width=True)

    # Table with requested names/order
    st.markdown("### Age-by-age breakdown")

    display_df = df.copy()
    display_df["InvestmentValue"] = display_df["Balance"]
    display_df["Home Equity"] = display_df["HomeEquity"]
    display_df["Contributions"] = display_df["ContribYear"]
    display_df["AdditionalAnnualExpense"] = display_df["AnnualExpense"]
    display_df["Investment Growth"] = display_df["InvestGrowthYear"]
    display_df["Home Price Growth"] = display_df["HomePriceGrowthYear"]
    display_df["Net Worth"] = display_df["NetWorth"]

    display_cols = [
        "Year",
        "Age",
        "InvestmentValue",
        "Home Equity",
        "Contributions",
        "AdditionalAnnualExpense",
        "Investment Growth",
        "Home Price Growth",
        "Net Worth",
    ]

    st.dataframe(
        display_df[display_cols].style.format(
            {
                "InvestmentValue": "${:,.0f}",
                "Home Equity": "${:,.0f}",
                "Contributions": "${:,.0f}",
                "AdditionalAnnualExpense": "${:,.0f}",
                "Investment Growth": "${:,.0f}",
                "Home Price Growth": "${:,.0f}",
                "Net Worth": "${:,.0f}",
            }
        ),
        hide_index=True,
    )

# -----------------------------
# Fill metric inside right card
# -----------------------------
if extra_per_month > 0:
    monthly_contrib_by_year_more = [
        c + extra_per_month for c in monthly_contrib_by_year
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
        df_more["DiscountFactor"] = (1 + infl_rate) ** df_more["Year"]
        for col in ["Balance", "HomeEquity", "NetWorth"]:
            df_more[col] = df_more[col] / df_more["DiscountFactor"]

    ending_more = df_more["NetWorth"].iloc[-1]
    extra_growth = ending_more - ending_net_worth

    metric_placeholder.metric(
        f"+${extra_per_month:,.0f}/month",
        f"${ending_more:,.0f}",
        delta=f"+${extra_growth:,.0f}",
    )
