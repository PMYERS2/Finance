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
        balance_start_year = balance
        
        contrib_year = 0.0
        growth_year_sum = 0.0

        if use_yearly_compounding:
            growth_year_sum = balance * r
            balance += growth_year_sum
            
            monthly_val = monthly_contrib_by_year[year_idx]
            annual_contrib = monthly_val * 12.0
            balance += annual_contrib
            
            contrib_year = annual_contrib
            cum_contrib += annual_contrib
        else:
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

        balance = balance_before_expense - annual_expense
        cum_expense_abs += annual_expense

        net_growth_cum = balance - (start_balance + cum_contrib)
        
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
    for age in range(start_age, end_age):
        year_idx = age - current_age
        if year_idx < 0 or year_idx >= len(annual_rates_full):
            break
        r_nominal = annual_rates_full[year_idx]
        years_from_now = year_idx + 1 
        infl_factor = (1 + infl_rate) ** years_from_now
        contrib_nominal = monthly_contrib_real * infl_factor
        base_expense_nominal = annual_expense_real * infl_factor
        if tax_rate > 0:
            base_expense_nominal = base_expense_nominal / (1.0 - tax_rate)
        net_draw_nominal = base_expense_nominal
        final_withdrawal_nominal = 0.0
        if net_draw_nominal > 0:
            if age < 60 and early_withdrawal_tax_rate > 0:
                final_withdrawal_nominal = net_draw_nominal / (1.0 - early_withdrawal_tax_rate)
            else:
                final_withdrawal_nominal = net_draw_nominal 
        if use_yearly_compounding:
            balance += balance * r_nominal
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

def get_dynamic_swr(age, base_swr):
    if age >= 60: return base_swr
    elif age >= 50: return max(0.01, base_swr - 0.0025)
    elif age >= 40: return max(0.01, base_swr - 0.0050)
    else: return max(0.01, base_swr - 0.0075)

def compute_regular_fi_age(df_full, current_age, start_balance_input, fi_annual_spend_today, infl_rate, base_swr):
    if fi_annual_spend_today <= 0 or base_swr <= 0 or df_full is None: return None, None
    for row in df_full.itertuples():
        age = row.Age
        current_swr = get_dynamic_swr(age, base_swr)
        target_real_at_age = fi_annual_spend_today / current_swr
        years_passed = age - current_age
        target_nominal = target_real_at_age * ((1 + infl_rate) ** years_passed)
        if row.StartBalance >= target_nominal:
            return age, target_real_at_age
    return None, fi_annual_spend_today / base_swr

def compute_part_time_fi_age(df_full, current_age, start_balance_input, fi_annual_spend_today, pt_income_today, pt_spend_today, infl_rate, base_swr, pt_until_age, annual_rates_by_year_full, early_withdrawal_tax_rate, use_yearly_compounding):
    gap = max(0, pt_spend_today - pt_income_today)
    if base_swr <= 0 or df_full is None: return None, None
    final_swr = get_dynamic_swr(pt_until_age, base_swr)
    target_real_at_finish = fi_annual_spend_today / final_swr
    balance_map = {row.Age: row.StartBalance for row in df_full.itertuples()}
    balance_map[current_age] = start_balance_input
    for age in range(current_age, pt_until_age + 1):
        if age not in balance_map: continue
        start_bal = balance_map[age]
        target_nominal_finish = target_real_at_finish * ((1 + infl_rate) ** (pt_until_age - current_age))
        final_bal = simulate_period_exact(start_bal, age, pt_until_age, current_age, annual_rates_by_year_full, gap, 0.0, infl_rate, 0.0, early_withdrawal_tax_rate, use_yearly_compounding)
        if final_bal >= target_nominal_finish:
            return age, target_real_at_finish
    return None, target_real_at_finish

def compute_coast_fi_age(df_full, current_age, start_balance_input, fi_annual_spend_today, infl_rate, base_swr, retirement_age, annual_rates_by_year_full):
    if fi_annual_spend_today <= 0 or base_swr <= 0 or df_full is None: return None, None, None, None
    target_real = fi_annual_spend_today / base_swr
    target_nominal_at_60 = target_real * ((1 + infl_rate) ** (60 - current_age))
    balance_map = {row.Age: row.StartBalance for row in df_full.itertuples()}
    balance_map[current_age] = start_balance_input
    for age in range(current_age, retirement_age + 1):
        if age not in balance_map: continue
        bal_sim = balance_map[age]
        for k in range(60 - age):
            y_idx = (age - current_age) + k
            if y_idx < len(annual_rates_by_year_full): bal_sim *= (1 + annual_rates_by_year_full[y_idx])
        if bal_sim >= target_nominal_at_60: return age, balance_map[age], target_real, base_swr
    return None, None, None, None

def total_tax_on_earned(income, state_tax_rate):
    if income <= 0: return 0.0
    federal = 0.0
    brackets = [(0.0, 11600.0, 0.10), (11600.0, 47150.0, 0.12), (47150.0, 100525.0, 0.22), (100525.0, 191950.0, 0.24), (191950.0, 243725.0, 0.32), (243725.0, 609350.0, 0.35)]
    for lower, upper, rate in brackets:
        if income <= lower: break
        span = min(income, upper) - lower
        if span > 0: federal += span * rate
    if income > 609350.0: federal += (income - 609350.0) * 0.37
    ss_tax = 0.062 * min(income, 168600.0)
    med_tax = 0.0145 * income
    state_tax = state_tax_rate * income
    return federal + ss_tax + med_tax + state_tax

def build_income_schedule(current_age, retirement_age, start_income, income_growth_rate, expense_today, expense_growth_rate, infl_rate, savings_rate_override=0.0, show_real=True, state_tax_rate=0.0, promotions=None):
    years = retirement_age - current_age
    rows, curr_nom_inc = [], start_income
    for y in range(years):
        age = current_age + y
        if y > 0: curr_nom_inc *= (1 + income_growth_rate)
        if promotions and age in promotions: curr_nom_inc *= (1 + promotions[age])
        df_y = (1 + infl_rate) ** y
        inc_real = curr_nom_inc / df_y
        tax_real = total_tax_on_earned(inc_real, state_tax_rate)
        post_tax_real = max(inc_real - tax_real, 0.0)
        exp_real = expense_today * ((1 + expense_growth_rate) ** y)
        invest_real = max(post_tax_real - exp_real, 0.0)
        if not show_real:
            inc_real *= df_y; tax_real *= df_y; post_tax_real *= df_y; exp_real *= df_y; invest_real *= df_y
        rows.append({"Age": age, "IncomeRealBeforeTax": inc_real, "TaxReal": tax_real, "IncomeRealAfterTax": post_tax_real, "ExpensesReal": exp_real, "InvestableRealMonthly": invest_real / 12.0, "SavingsRate": invest_real / post_tax_real if post_tax_real > 0 else 0.0})
    return pd.DataFrame(rows)

def glide_path_return(age, base_return):
    if age <= 35: return base_return + 0.01
    elif age <= 45: return base_return + 0.005
    elif age <= 55: return base_return
    elif age <= 65: return base_return - 0.01
    else: return base_return - 0.015

# =========================================================
# Main app
# =========================================================
def main():
    st.set_page_config(page_title="FIRE Planner", layout="wide")
    st.markdown("""<style>.kpi-card {background-color: #F8F9FA; border: 1px solid #E9ECEF; border-radius: 8px; padding: 8px 4px; text-align: center; margin-bottom: 5px; height: 100%; min-height: 90px; display: flex; flex-direction: column; justify-content: center;} .kpi-title {font-size: 11px; color: #6C757D; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px;} .kpi-value {font-size: 18px; font-weight: 700; color: #212529; margin: 0; line-height: 1.2;} .kpi-subtitle {font-size: 10px; color: #495057; margin-top: 4px; line-height: 1.3;}</style>""", unsafe_allow_html=True)

    c_head_1, c_head_2, c_head_3 = st.columns([3, 0.4, 1])
    with c_head_1: st.markdown("##### 🔮 FIRE & Retirement Forecaster")
    with c_head_2:
        with st.popover("❓"):
            st.markdown("""**How to use:** 1. Set sidebar inputs. 2. Define goals. 3. Select Scenario. *Note: Portfolio withdrawals only; no Social Security.*""")
    with c_head_3: show_real = st.checkbox("Show Real Dollars", True)

    kpi_container = st.container()
    current_age = st.sidebar.number_input("Current Age", 20, 100, 30)
    
    # Sidebar Sections - ALL EXPANDED
    with st.sidebar.expander("1. Income & Expenses", expanded=True):
        start_income = st.number_input("Pre-tax Income ($)", 0, 1000000, 100000, step=5000)
        expense_today = st.number_input("Current Expenses ($/yr)", 0, 500000, 40000, step=1000)
        state_tax_rate = st.number_input("State Tax Rate (%)", 0.0, 15.0, 0.0, 0.5) / 100.0
        income_growth_rate = st.number_input("Annual Income Growth (%)", 0.0, 20.0, 3.0) / 100.0
        promotions = {}
        c1, c2 = st.columns(2)
        p1_age = c1.number_input("Event 1 Age", current_age+1, 90, current_age+5)
        p1_pct = c2.number_input("Event 1 %", -100.0, 500.0, 0.0) / 100.0
        if p1_pct != 0: promotions[p1_age] = p1_pct

    with st.sidebar.expander("2. Future Goals", expanded=True):
        retirement_age = st.number_input("Full Retirement Age", current_age+1, 90, 60)
        fi_annual_spend_today = st.number_input("Retirement Spend ($)", 0, 500000, 60000, step=5000)

    with st.sidebar.expander("3. Part-Time Work Settings", expanded=True):
        pt_income_today = st.number_input("Part-Time Income Goal ($)", 0, 200000, 30000, step=5000)
        pt_spend_today = st.number_input("Part-Time Annual Spend ($)", 0, 500000, 50000, step=5000)
        pt_until_age = st.number_input("Work Part-Time Until Age", current_age+1, 100, 60)

    with st.sidebar.expander("4. Assets & Housing", expanded=True):
        start_balance_input = st.number_input("Invested Assets ($)", 0, 10000000, 100000, step=5000)
        include_home = st.checkbox("Include Home Strategy", False)
        home_equity_by_year_full = [0.0] * 71

    with st.sidebar.expander("5. Assumptions & Adjustments", expanded=True):
        use_yearly = st.radio("Compounding", ["Monthly", "Yearly"]) == "Yearly"
        style_map = {"Aggressive": 0.09, "Balanced": 0.07, "Conservative": 0.05}
        annual_rate_base = style_map[st.selectbox("Portfolio Style", list(style_map.keys()), index=1)]
        infl_rate = st.number_input("Inflation (%)", 0.0, 10.0, 3.0) / 100.0
        base_swr_30yr = st.number_input("SWR (%)", 1.0, 10.0, 4.0) / 100.0
        early_withdrawal_tax_rate = st.number_input("Early Tax Rate (%)", 0.0, 50.0, 15.0) / 100.0

    # Engine
    df_income = build_income_schedule(current_age, retirement_age, start_income, income_growth_rate, expense_today, 0.0, infl_rate, 0.0, show_real, state_tax_rate, promotions)
    years_full = 90 - current_age
    annual_rates = [glide_path_return(current_age + y, annual_rate_base) for y in range(years_full)]
    monthly_contribs = [(df_income.loc[y, "InvestableRealMonthly"] * ((1+infl_rate)**y if show_real else 1.0)) if y < len(df_income) else 0.0 for y in range(years_full)]
    
    df_full = compound_schedule(start_balance_input, years_full, monthly_contribs, [0.0]*years_full, annual_rate_by_year=annual_rates, use_yearly_compounding=use_yearly)
    df_full["Age"] = current_age + df_full["Year"] - 1

    fi_age_regular, _ = compute_regular_fi_age(df_full, current_age, start_balance_input, fi_annual_spend_today, infl_rate, base_swr_30yr)
    pt_age, _ = compute_part_time_fi_age(df_full, current_age, start_balance_input, fi_annual_spend_today, pt_income_today, pt_spend_today, infl_rate, base_swr_30yr, pt_until_age, annual_rates, early_withdrawal_tax_rate, use_yearly)

    # Dashboard
    viz_col, control_col = st.columns([3, 1])
    with control_col:
        st.markdown("**Visualize Scenario**")
        scenario_options = ["Work"]
        display_map = {"Work": "Full Retirement"}
        if pt_age: scenario_options.append("Part-Time"); display_map["Part-Time"] = f"Part-Time Work (Age {pt_age})"
        selected_key = st.selectbox("Select Scenario:", scenario_options, format_func=lambda x: display_map[x], key="scenario_selector")

    stop_age = retirement_age if selected_key == "Work" else pt_age
    is_pt = selected_key == "Part-Time"
    
    annual_expenses_chart = [0.0]*years_full
    detailed_income_active = []
    det_living_draw, det_tax_pen = [], []
    for y in range(years_full):
        age = current_age + y
        inf_f = (1+infl_rate)**(y+1)
        if age >= stop_age:
            if is_pt and age < pt_until_age:
                active_inc = pt_income_today * (inf_f if not show_real else 1.0)
                draw = max(0, pt_spend_today - pt_income_today) * inf_f
            else:
                active_inc = 0.0; draw = fi_annual_spend_today * inf_f
            
            pen = (draw / (1 - early_withdrawal_tax_rate)) - draw if age < 60 else 0.0
            annual_expenses_chart[y] = draw + pen
            detailed_income_active.append(active_inc); det_living_draw.append(draw); det_tax_pen.append(pen)
        else:
            detailed_income_active.append(df_income.loc[y, "IncomeRealAfterTax"] if y < len(df_income) else 0.0)
            det_living_draw.append(0.0); det_tax_pen.append(0.0)

    df_chart = compound_schedule(start_balance_input, years_full, [c if (current_age + i) < stop_age else 0.0 for i, c in enumerate(monthly_contribs)], annual_expenses_chart, annual_rate_by_year=annual_rates, use_yearly_compounding=use_yearly)
    df_chart["Age"] = current_age + df_chart["Year"] - 1
    if show_real:
        for c in ["StartBalance", "EndBalance", "InvestGrowthYear"]: df_chart[c] /= (1+infl_rate)**(df_chart["Year"]-1)
    
    with kpi_container:
        c1, c2, c3 = st.columns(3)
        row_at_exit = df_chart[df_chart["Age"] == (pt_until_age if is_pt else retirement_age)].iloc[0]
        f_inc = row_at_exit["StartBalance"] * get_dynamic_swr(row_at_exit["Age"], base_swr_30yr)
        
        def render_kpi(col, t, v, d, sv=None):
            with col: st.markdown(f'<div class="kpi-card"><div class="kpi-title">{t}</div><div class="kpi-value">{v}</div><div style="font-size:12px; color:#2E7D32;">{sv if sv else ""}</div><div class="kpi-subtitle">{d}</div></div>', unsafe_allow_html=True)
        
        render_kpi(c1, "Full FIRE Age", f"<span style='color:#0D47A1'>{fi_age_regular if fi_age_regular else 'N/A'}</span>", "Based on portfolio size.")
        render_kpi(c2, "Part-Time Age", f"<span style='color:#0D47A1'>{pt_age if pt_age else 'N/A'}</span>", f"Work until {pt_until_age}.")
        render_kpi(c3, f"Future Income ({selected_key})", f"${f_inc:,.0f}", f"Draw at age {row_at_exit['Age']}.", f"(${f_inc/12:,.0f}/mo)")

    with viz_col:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_chart["Age"], y=df_chart["StartBalance"], name="Invested Assets", marker_color='#3A6EA5'))
        fig.update_layout(title="<b>Net Worth Projection</b>", barmode='stack', height=380, yaxis=dict(tickformat=",.0f"))
        st.plotly_chart(fig, use_container_width=True)

    # Tabs
    t1, t2, t3 = st.tabs(["Cash Flow", "Net Worth Table", "Audit"])
    with t1:
        fig_i = go.Figure()
        fig_i.add_trace(go.Scatter(x=df_chart["Age"], y=detailed_income_active, name="Active Income", line=dict(color="#66BB6A", width=3)))
        fig_i.add_trace(go.Scatter(x=df_chart["Age"], y=det_living_draw, name="Portfolio Draw", line=dict(color="#EF5350", width=3)))
        st.plotly_chart(fig_i, use_container_width=True)
    with t2: st.dataframe(df_chart[["Age", "StartBalance"]].style.format("${:,.0f}"), use_container_width=True, hide_index=True)
    with t3: st.dataframe(df_chart.style.format({c: "${:,.0f}" for c in df_chart.columns if c != "Age"}), use_container_width=True, hide_index=True)

if __name__ == "__main__":
    main()
