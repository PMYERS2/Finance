import textwrap
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =========================================================
# 1. CORE CALCULATION ENGINE
# =========================================================

def compound_schedule(start_balance, years, monthly_contrib_by_year, 
                      annual_expense_by_year, annual_rate_by_year=None, 
                      use_yearly_compounding=False):
    """Calculates year-by-year growth, contributions, and withdrawals."""
    balance = start_balance
    cum_contrib = 0.0
    rows = []

    for year_idx in range(years):
        r = annual_rate_by_year[year_idx] if annual_rate_by_year else 0.0
        balance_start_year = balance
        contrib_year = 0.0
        growth_year_sum = 0.0

        if use_yearly_compounding:
            growth_year_sum = balance * r
            balance += growth_year_sum
            annual_contrib = monthly_contrib_by_year[year_idx] * 12.0
            balance += annual_contrib
            contrib_year = annual_contrib
        else:
            m = 12
            for _ in range(m):
                m_contrib = monthly_contrib_by_year[year_idx]
                balance += m_contrib
                balance += balance * (r / m)
                contrib_year += m_contrib
                growth_year_sum += (balance * (r/m))

        annual_expense = annual_expense_by_year[year_idx]
        balance -= annual_expense
        
        rows.append({
            "Year": year_idx + 1,
            "StartBalance": balance_start_year,
            "EndBalance": max(balance, 0),
            "ContribYear": contrib_year,
            "InvestGrowthYear": growth_year_sum,
            "AnnualRate": r,
            "AnnualExpense": annual_expense
        })
    return pd.DataFrame(rows)

def simulate_period_exact(start_balance_nominal, start_age, end_age, current_age, 
                          annual_rates_full, annual_expense_real, infl_rate, 
                          early_withdrawal_tax_rate=0.0):
    """
    Simulates a specific window of time (e.g., the Part-Time years).
    Used by the solver to see if a specific transition age 'works'.
    """
    balance = start_balance_nominal
    for age in range(start_age, end_age):
        y_idx = age - current_age
        r_nominal = annual_rates_full[y_idx]
        infl_factor = (1 + infl_rate) ** (y_idx + 1)
        
        # Portfolio only covers the 'Gap' (Spend - PartTime Income)
        net_draw_nominal = annual_expense_real * infl_factor
        
        # Apply tax gross-up for early withdrawals (Pre-age 60)
        final_draw = net_draw_nominal / (1.0 - early_withdrawal_tax_rate) if age < 60 else net_draw_nominal
        
        # Monthly compounding simulation
        for _ in range(12):
            balance += balance * (r_nominal / 12)
        balance -= final_draw
        
        if balance < 0: return 0.0
    return balance

# =========================================================
# 2. PART-TIME SOLVER LOGIC
# =========================================================

def get_dynamic_swr(age, base_swr):
    """Adjusts SWR based on timeline; younger = more conservative."""
    if age >= 60: return base_swr
    if age >= 50: return max(0.01, base_swr - 0.0025)
    return max(0.01, base_swr - 0.0050)

def compute_part_time_fi_age(df_full, current_age, start_bal, full_spend, 
                             pt_income, pt_spend, infl_rate, base_swr, 
                             pt_until_age, rates_full, early_tax):
    """
    SOLVER: Iterates through every possible age to find the earliest 
    point you can switch to Part-Time work and still hit your final target.
    """
    gap_real = max(0, pt_spend - pt_income)
    final_swr = get_dynamic_swr(pt_until_age, base_swr)
    target_nom_finish = (full_spend / final_swr) * ((1 + infl_rate)**(pt_until_age - current_age))
    
    balance_map = {row.Age: row.StartBalance for row in df_full.itertuples()}
    
    for age in range(current_age, pt_until_age + 1):
        if age not in balance_map: continue
        
        # Test: If I quit my career at 'age', do I have enough at 'pt_until_age'?
        final_bal = simulate_period_exact(balance_map[age], age, pt_until_age, 
                                          current_age, rates_full, gap_real, 
                                          infl_rate, early_tax)
        if final_bal >= target_nom_finish:
            return age
    return None

# =========================================================
# 3. STREAMLIT UI & DASHBOARD
# =========================================================

def main():
    st.set_page_config(page_title="Part-Time Work Forecaster", layout="wide")
    st.markdown("## 🛠️ Part-Time Transition & FIRE Forecaster")
    
    # --- SIDEBAR INPUTS ---
    st.sidebar.header("1. Current Financials")
    current_age = st.sidebar.number_input("Current Age", 20, 80, 30)
    start_income = st.sidebar.number_input("Career Income (Pre-tax $)", value=100000)
    expense_today = st.sidebar.number_input("Current Living Expenses ($)", value=45000)
    start_assets = st.sidebar.number_input("Invested Assets ($)", value=150000)
    
    st.sidebar.header("2. Part-Time Goals")
    full_ret_age = st.sidebar.number_input("Full Retirement Age (Stop all work)", value=60)
    full_spend = st.sidebar.number_input("Full Retirement Spending ($/yr)", value=60000)
    
    st.sidebar.markdown("---")
    pt_income = st.sidebar.number_input("Part-Time Job Income ($/yr)", value=30000)
    pt_spend = st.sidebar.number_input("Part-Time Phase Spending ($/yr)", value=50000)
    
    st.sidebar.header("3. Assumptions")
    infl_rate = st.sidebar.slider("Inflation (%)", 0.0, 8.0, 3.0) / 100
    mkt_rate = st.sidebar.slider("Market Return (%)", 0.0, 12.0, 7.0) / 100
    early_tax = st.sidebar.slider("Early Withdrawal Tax/Penalty (%)", 0.0, 30.0, 15.0) / 100
    base_swr = 0.04

    # --- CALCULATIONS ---
    years_to_sim = 90 - current_age
    rates_full = [mkt_rate] * years_to_sim # Simplified constant rate for this demo
    
    # 1. Build Baseline (Career) Schedule
    # Mocking contributions: Income - Expenses - 25% estimated tax
    monthly_sav = (start_income * 0.75 - expense_today) / 12
    df_career = compound_schedule(start_assets, years_to_sim, [monthly_sav]*years_to_sim, 
                                  [0]*years_to_sim, annual_rate_by_year=rates_full)
    df_career["Age"] = current_age + df_career["Year"] - 1
    
    # 2. Solve for Part-Time Age
    pt_age = compute_part_time_fi_age(df_career, current_age, start_assets, full_spend, 
                                     pt_income, pt_spend, infl_rate, base_swr, 
                                     full_ret_age, rates_full, early_tax)

    # --- VISUALIZATION ---
    c1, c2 = st.columns([3, 1])
    
    with c1:
        # Simple Net Worth Chart
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df_career["Age"], y=df_career["EndBalance"], 
                                 name="Net Worth (Career Path)", line=dict(color='#2E7D32')))
        
        if pt_age:
            fig.add_vline(x=pt_age, line_dash="dash", line_color="orange", 
                          annotation_text=f"Part-Time Age: {pt_age}")
        
        fig.update_layout(title="Wealth Projection", xaxis_title="Age", yaxis_title="Balance ($)")
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.metric("Career Milestone", f"Age {pt_age if pt_age else 'N/A'}", "Part-Time Ready")
        st.write(f"This is the age where you can drop to a **${pt_income:,.0f}** job while spending **${pt_spend:,.0f}** and still retire fully at **{full_ret_age}**.")

    # --- AUDIT TABLE ---
    with st.expander("View Full Data Audit"):
        st.dataframe(df_career)

if __name__ == "__main__":
    main()
