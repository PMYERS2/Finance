# ... existing imports ...
# ... existing functions ...

    # --- MAIN VISUALIZATION CONTROLS & LAYOUT ---
    
    # Use st.markdown to create a small vertical spacer instead of "---" if needed
    st.markdown("<div style='margin-bottom: 5px;'></div>", unsafe_allow_html=True)
    
    # Place KPIs in a container at the top so they appear above controls visually,
    # but we can populate them after we get control values.
    kpi_container = st.container()

    viz_col, control_col = st.columns([3, 1])
    
    # 5. Simulation Scenario (MOVED TO DASHBOARD)
    with control_col:
        st.markdown("**Visualize Scenario**")
        
        use_barista_mode = st.checkbox("Simulate Barista FIRE?", False, help="If checked, custom early retirement assumes Barista income.")
        
        # Custom Early Retirement Slider
        default_exit = fi_age_regular if fi_age_regular else 55
        custom_exit_age = st.slider("Custom Early Ret. Age", min_value=current_age+1, max_value=retirement_age, value=default_exit)
        
        # Scenario Selector
        scenario_keys = ["Work"]
        display_map = {"Work": "Work until Full Retirement"}
        
        if barista_age:
            scenario_keys.append("Barista")
            display_map["Barista"] = f"Barista FIRE (Age {barista_age})"
            
        scenario_keys.append("Custom")
        display_map["Custom"] = f"Custom (Age {custom_exit_age})"
        
        # We need a default index that is valid
        default_ix = 0
        
        selected_key = st.selectbox(
            "Select Scenario:", 
            options=scenario_keys, 
            format_func=lambda x: display_map[x],
            index=default_ix
        )

    # --- DETERMINE SCENARIO LOGIC (Moved up for Chart & KPI) ---
    stop_age = retirement_age # Default
    is_coast, is_barista, is_early = False, False, False
    scenario_label = display_map[selected_key]
    
    if selected_key == "Barista":
        stop_age = barista_age
        is_barista = True
    elif selected_key == "Custom":
        stop_age = custom_exit_age
        if use_barista_mode:
            is_barista = True
        else:
            is_early = True

    # --- BUILD CHART DATA (Now available for KPIs) ---
    monthly_contrib_chart = []
    annual_expense_chart = list(annual_expense_by_year_nominal_full) 
    
    detailed_income_active = []
    detailed_expense_total = []
    
    det_living_withdrawal = []
    det_tax_penalty = []
    det_kids = []
    det_cars = []
    det_housing = []
    det_total_portfolio_draw = []

    def to_nom(val, y_idx):
        return val * ((1+infl_rate)**(y_idx)) if (show_real and infl_rate > 0) else val

    # RE-CALC CHART EXPENSES TO INCLUDE EARLY TAX
    for y in range(years_full):
        age = current_age + y
        
        # 1. Contributions
        val = monthly_contrib_by_year_full[y] if age < stop_age else 0.0
        monthly_contrib_chart.append(val)
        
        active_income_this_year = 0.0
        base_need = 0.0
        
        # 2. Retirement Phase Expenses
        if age >= stop_age:
            if is_barista:
                 if age < barista_until_age:
                     # BARISTA PHASE
                     active_income_this_year = barista_income_today
                     base_need = max(0, fi_annual_spend_today - barista_income_today) * ((1+infl_rate)**(y+1))
                 else:
                     # FULL RETIREMENT PHASE (After Barista)
                     base_need = fi_annual_spend_today * ((1+infl_rate)**(y+1))
                     active_income_this_year = 0.0
            elif is_early:
                 base_need = fi_annual_spend_today * ((1+infl_rate)**(y+1))
            else:
                 # Standard retirement
                 if age < retirement_age: base_need = 0.0
                 else: base_need = fi_annual_spend_today * ((1+infl_rate)**(y+1))

            net_draw = base_need
            
            gross_withdrawal = net_draw
            tax_penalty_amount = 0.0
            
            if net_draw > 0:
                if age < 60 and early_withdrawal_tax_rate > 0:
                    gross_withdrawal = net_draw / (1.0 - early_withdrawal_tax_rate)
                    tax_penalty_amount = gross_withdrawal - net_draw
            
            annual_expense_chart[y] += gross_withdrawal
            
            detailed_expense_total.append(gross_withdrawal + to_nom(active_income_this_year, y))
            detailed_income_active.append(to_nom(active_income_this_year, y))
            
            det_living_withdrawal.append(net_draw)
            det_tax_penalty.append(tax_penalty_amount)
            det_total_portfolio_draw.append(annual_expense_chart[y])

        else:
            det_total_portfolio_draw.append(annual_expense_chart[y]) 
            
            if y < len(df_income):
                val_from_table = df_income.loc[y, "IncomeRealAfterTax"]
                if show_real and infl_rate > 0:
                        val_nominal = val_from_table * ((1 + infl_rate) ** y)
                else:
                        val_nominal = val_from_table
                
                detailed_income_active.append(val_nominal)
            else:
                detailed_income_active.append(0.0)
                
            detailed_expense_total.append(annual_expense_chart[y])
            det_living_withdrawal.append(0.0)
            det_tax_penalty.append(0.0)

        det_kids.append(exp_kids_nominal[y])
        det_cars.append(exp_cars_nominal[y])
        det_housing.append(exp_housing_nominal[y])

    # 4. Generate Chart DF
    df_chart = compound_schedule(
        start_balance_effective, years_full, monthly_contrib_chart,
        annual_expense_chart, annual_rate_by_year=annual_rates_by_year_full,
        use_yearly_compounding=use_yearly
    )
    df_chart["Age"] = current_age + df_chart["Year"] - 1
    df_chart["Balance"] = df_chart["StartBalance"]
    
    df_chart["HomeEquity"] = home_equity_by_year_full
    df_chart["NetWorth"] = df_chart["Balance"] + df_chart["HomeEquity"]
    
    df_chart["ScenarioActiveIncome"] = detailed_income_active
    df_chart["TotalPortfolioDraw"] = det_total_portfolio_draw
    df_chart["LivingWithdrawal"] = det_living_withdrawal
    df_chart["TaxPenalty"] = det_tax_penalty
    df_chart["KidCost"] = det_kids
    df_chart["CarCost"] = det_cars
    df_chart["HomeCost"] = det_housing

    # Real Adjustment
    if show_real and infl_rate > 0:
        # For Start of Year adjustments, we deflate by (1+inf)^year_idx
        df_chart["DF"] = (1+infl_rate)**(df_chart["Year"] - 1)
        for c in ["Balance", "HomeEquity", "NetWorth", "AnnualExpense", "StartBalance", "EndBalance"]:
            df_chart[c] /= df_chart["DF"]
        for c in ["ScenarioActiveIncome", "TotalPortfolioDraw", "LivingWithdrawal", "TaxPenalty", "KidCost", "CarCost", "HomeCost", "InvestGrowthYear", "ContribYear"]:
            df_chart[c] /= df_chart["DF"]

    # --- DYNAMIC FUTURE INCOME KPI ---
    
    # 1. Determine "Full Retirement Start Age" for the selected scenario
    full_ret_start_age = retirement_age # Default Work
    if is_barista:
        full_ret_start_age = barista_until_age
    elif is_early:
        full_ret_start_age = stop_age
    
    # 2. Get Balance at that age from df_chart
    # We look for the row where Age == full_ret_start_age
    row_at_ret = df_chart[df_chart["Age"] == full_ret_start_age]
    
    future_income_val = 0.0
    future_swr_used = 0.0
    
    if not row_at_ret.empty:
        final_balance = row_at_ret.iloc[0]["Balance"] # Already Real/Nominal adjusted by loop above
        future_swr_used = get_dynamic_swr(full_ret_start_age, base_swr_30yr)
        future_income_val = final_balance * future_swr_used
        
    # --- TOP ROW: THE VERDICT (Redesigned for Single Screen) ---
    
    def render_card(col, title, value, desc, sub_value=None):
        sub_html = f"<div style='font-size:12px; font-weight:600; color:#2E7D32; margin-top:2px;'>{sub_value}</div>" if sub_value else ""
        
        html_content = (
            f'<div class="kpi-card">'
            f'<div class="kpi-title">{title}</div>'
            f'<div class="kpi-value">{value}</div>'
            f'{sub_html}'
            f'<div class="kpi-subtitle">{textwrap.shorten(desc, width=60, placeholder="...")}</div>'
            f'</div>'
        )
        
        with col:
            st.markdown(html_content, unsafe_allow_html=True)

    with kpi_container:
        # Layout: 3 Equal Columns
        c1, c2, c3 = st.columns(3)
        
        # 1. Regular FIRE
        val_reg = str(fi_age_regular) if fi_age_regular else "N/A"
        color_reg = "#0D47A1" if fi_age_regular else "#CC0000"
        if fi_age_regular:
            swr_r = get_dynamic_swr(fi_age_regular, base_swr_30yr)
            desc_reg = f"Based on {swr_r*100:.2f}% SWR."
        else:
            desc_reg = "Target not reached."
        render_card(c1, "Regular FIRE Age", f"<span style='color:{color_reg}'>{val_reg}</span>", desc_reg)

        # 2. Barista FIRE
        val_bar = str(barista_age) if barista_age else "N/A"
        color_bar = "#0D47A1" if barista_age else "#CC0000"
        if barista_age:
            swr_b = get_dynamic_swr(barista_until_age, base_swr_30yr)
            desc_bar = f"Gap SWR: {swr_b*100:.2f}%. Work until {barista_until_age}."
        else:
            desc_bar = "N/A"
        render_card(c2, "Barista FIRE Age", f"<span style='color:{color_bar}'>{val_bar}</span>", desc_bar)
        
        # 3. Future Income (Dynamic)
        scen_name = "Work"
        if is_barista: scen_name = "Barista"
        elif is_early: scen_name = "Custom"
        
        render_card(
            c3, 
            f"Future Income ({scen_name})", 
            f"${future_income_val:,.0f}", 
            f"Safe draw at age {full_ret_start_age}.",
            sub_value=f"(${future_income_val/12:,.0f}/mo)"
        )

    # 5. Plot (In Left Column)
    with viz_col:
        # We plot a bit past the "Full Retirement Start" to show the safe phase
        # User requested: "until retirement age always"
        # We ensure it shows at least up to retirement_age, or the scenario end if later.
        plot_end = max(retirement_age, full_ret_start_age)
        if plot_end > max_sim_age: plot_end = max_sim_age
        
        df_p = df_chart[df_chart["Age"] <= plot_end].reset_index(drop=True)
        
        fig = go.Figure()
        # Main Balance
        fig.add_trace(go.Bar(
            x=df_p["Age"], y=df_p["Balance"], 
            name="Invested Assets (Start of Year)",
            marker_color='rgba(58, 110, 165, 0.8)', # Strong Blue
            hovertemplate="$%{y:,.0f}"
        ))
        # Home Equity
        fig.add_trace(go.Bar(
            x=df_p["Age"], y=df_p["HomeEquity"], 
            name="Home Equity (Start of Year)",
            marker_color='rgba(167, 173, 178, 0.5)', # Grey
            hovertemplate="$%{y:,.0f}"
        ))
        
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
        
        target_val = fi_target_bal
        if show_real and infl_rate > 0: target_val = fi_annual_spend_today / base_swr_30yr
        
        fig.update_layout(
            # UPDATED TITLE SIZE AND BOLDNESS
            title=dict(text="<b>Net Worth Projection (Start of Year)</b>", font=dict(size=20)),
            xaxis_title="Age (Start of Year)", yaxis_title="Value ($)",
            barmode='stack',
            hovermode="x unified",
            legend=dict(orientation="h", y=1.02, x=0.01),
            margin=dict(l=20, r=20, t=40, b=20),
            height=380, # Slightly smaller height to ensure fit
            yaxis=dict(tickformat=",.0f")
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
    with control_col:
        st.info(f"Viewing: **{scenario_label}**")
        if is_barista:
            st.caption(f"Barista Phase: Age {stop_age} to {barista_until_age}")
            st.caption(f"Full Retire: Age {barista_until_age}+")
        elif is_early:
            st.caption(f"Early Retire: Age {stop_age}+")
        else:
            st.caption(f"Work until: Age {retirement_age}")

    # --- TABS FOR DETAILS ---
    tab1, tab2, tab3, tab4 = st.tabs(["Risk Analysis", "Cash Flow Details", "Net Worth Table", "Audit Table"])
    
    with tab1:
        st.caption("How market volatility (+/- 1% annual return) impacts your outcome.")
        rates_bear = [r - 0.01 for r in annual_rates_by_year_full]
        rates_bull = [r + 0.01 for r in annual_rates_by_year_full]
        
        df_bear = compound_schedule(start_balance_effective, years_full, monthly_contrib_chart, annual_expense_chart, annual_rate_by_year=rates_bear, use_yearly_compounding=use_yearly)
        df_bull = compound_schedule(start_balance_effective, years_full, monthly_contrib_chart, annual_expense_chart, annual_rate_by_year=rates_bull, use_yearly_compounding=use_yearly)
        
        for df_ in [df_bear, df_bull]:
            df_["Age"] = current_age + df_["Year"] - 1
            df_["NW"] = df_["StartBalance"] + home_equity_by_year_full
            if show_real and infl_rate > 0:
                df_["NW"] /= ((1+infl_rate)**(df_["Year"]-1))
        
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
            y=df_income["SavingsRate"] * 100, 
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
        st.markdown("### Net Worth Summary (Start of Year)")
        st.caption("Simplified overview of your projected wealth at the start of each age.")
        
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
        st.markdown(f"**Audit Table: {scenario_label}**")
        st.caption("Detailed view of Start Balance to End Balance flow.")

        st.markdown("""
        #### 🧮 Flow Logic
        
        $$
        \\text{EndBalance} = \\text{StartBalance} + \\text{Growth} + \\text{AnnualSavings} - \\text{Withdrawals}
        $$
        
        Note: The **StartBalance** of the next row (Age + 1) equals the **EndBalance** of the current row.
        """)
        
        format_dict_d = {
            "StartBalance": "${:,.0f}",
            "EndBalance": "${:,.0f}",
            "LivingWithdrawal": "${:,.0f}",
            "TaxPenalty": "${:,.0f}",
            "KidCost": "${:,.0f}",
            "CarCost": "${:,.0f}",
            "HomeCost": "${:,.0f}",
            "TotalPortfolioDraw": "${:,.0f}",
            "ScenarioActiveIncome": "${:,.0f}",
            "InvestGrowthYear": "${:,.0f}",
            "ContribYear": "${:,.0f}",
            "AnnualRate": "{:.2%}",
            "Age": "{:.0f}"
        }
        
        cols = [
            "Age", 
            "StartBalance",
            "AnnualRate",
            "InvestGrowthYear",
            "ContribYear", 
            "TotalPortfolioDraw",
            "EndBalance",
            # "LivingWithdrawal", 
            # "TaxPenalty", 
            # "KidCost", 
            # "CarCost", 
            # "HomeCost",
            # "ScenarioActiveIncome"
        ]
        
        st.dataframe(
            df_p[cols].style.format(format_dict_d),
            use_container_width=True,
            hide_index=True
        )

if __name__ == "__main__":
    main()
