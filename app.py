import textwrap
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =========================================================
# Core Calculation Logic
# =========================================================

def simulate_period_exact(
    start_balance_nominal, start_age, end_age, current_age, 
    annual_rates_full, annual_expense_real, monthly_contrib_real, 
    infl_rate, tax_rate=0.0, early_withdrawal_tax_rate=0.0, 
    use_yearly_compounding=False
):
    """
    Simulates portfolio flow between two ages. 
    Crucial for finding the 'Part-Time Work' transition age.
    """
    balance = start_balance_nominal
    for age in range(start_age, end_age):
        year_idx = age - current_age
        if year_idx < 0 or year_idx >= len(annual_rates_full):
            break
            
        r_nominal = annual_rates_full[year_idx]
        infl_factor = (1 + infl_rate) ** (year_idx + 1)
        
        # 1. Inflation-adjusted withdrawals
        net_draw_nominal = annual_expense_real * infl_factor
        
        # 2. Tax "Gross-up" (Withdraw more to cover the tax/penalty)
        final_withdrawal_nominal = 0.0
        if net_draw_nominal > 0:
            # If under 60, apply early withdrawal penalty/tax
            tax_to_apply = early_withdrawal_tax_rate if age < 60 else tax_rate
            final_withdrawal_nominal = net_draw_nominal / (1.0 - tax_to_apply)

        # 3. Compounding
        if use_yearly_compounding:
            balance = (balance * (1 + r_nominal)) - final_withdrawal_nominal
        else:
            monthly_rate = r_nominal / 12.0
            for _ in range(12):
                balance += balance * monthly_rate
            balance -= final_withdrawal_nominal
        
        if balance < 0:
            return 0.0
            
    return balance

def compute_part_time_fi_age(
    df_full, current_age, start_balance_input, fi_annual_spend_today, 
    pt_income_today, pt_spend_today, infl_rate, base_swr, 
    full_retirement_age, annual_rates_by_year_full, early_tax, use_yearly
):
    """
    Finds the earliest age you can switch to Part-Time work.
    Logic: At 'full_retirement_age', the balance must hit the FI Target.
    """
    gap = max(0, pt_spend_today - pt_income_today)
    
    # Target needed at the end of the part-time phase
    final_swr = get_dynamic_swr(full_retirement_age, base_swr)
    target_real = fi_annual_spend_today / final_swr
    target_nominal_finish = target_real * ((1 + infl_rate) ** (full_retirement_age - current_age))
    
    balance_map = {row.Age: row.StartBalance for row in df_full.itertuples()}
    
    # Search for the earliest successful transition age
    for age in range(current_age, full_retirement_age + 1):
        if age not in balance_map: continue
        
        final_bal = simulate_period_exact(
            start_balance_nominal=balance_map[age],
            start_age=age,
            end_age=full_retirement_age,
            current_age=current_age,
            annual_rates_full=annual_rates_by_year_full,
            annual_expense_real=gap,
            monthly_contrib_real=0.0,
            infl_rate=infl_rate,
            early_withdrawal_tax_rate=early_tax,
            use_yearly_compounding=use_yearly
        )
        
        if final_bal >= target_nominal_finish:
            return age
    return None

# =========================================================
# UI & Dashboard (Updated Labels)
# =========================================================

# ... (Helper functions like get_dynamic_swr remain the same) ...

def main():
    # ... (Sidebar Setup) ...
    
    with st.sidebar.expander("2. Future Goals", expanded=True):
        retirement_age = st.number_input("Full Retirement Age", value=60)
        fi_annual_spend_today = st.number_input("Full Retirement Spend ($)", value=60000)
        
        st.markdown("---")
        st.markdown("**Part-Time Phase Settings**")
        pt_income_today = st.number_input("Part-Time Annual Income ($)", value=30000)
        pt_spend_today = st.number_input("Spending During Part-Time ($)", value=50000)
        pt_until_age = st.number_input("Work Part-Time Until Age", value=60)

    # ... (Calculations) ...
    
    # Updated KPI Cards
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Regular FIRE Age", fi_age_regular if fi_age_regular else "N/A")
    with c2:
        st.metric("Part-Time FIRE Age", pt_age if pt_age else "N/A")
    with c3:
        st.metric("Expected Retirement Income", f"${future_income:,.0f}/yr")

    # Scenario Selection
    scenario = st.selectbox("Visualize Scenario", ["Standard Career", "Part-Time Transition", "Custom Early Exit"])
