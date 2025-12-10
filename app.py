# --- EXTRA KPI: TRADITIONAL RETIREMENT OUTCOME ---
    # Find the row for 'retirement_age' to see what the pot looks like.
    # ADJUSTMENT: To align with the graph (which deducts living expenses for the retirement year itself),
    # we must subtract the living expense from df_full's balance (which only subtracts extra expenses like kids/housing).
    
    traditional_row = df_full[df_full["Age"] == retirement_age]
    traditional_balance_display = 0.0
    traditional_annual_income = 0.0
    
    if not traditional_row.empty:
        # Get nominal balance from the accumulation-only simulation
        bal_nom = traditional_row.iloc[0]["Balance"]
        
        # Calculate the living expense withdrawal that the graph subtracts for this specific year
        years_passed = retirement_age - current_age
        infl_factor = (1 + infl_rate) ** years_passed
        # Note: Graph uses ((1+infl)**(y+1)) where y is index. 
        # y = retirement_age - current_age - 1 ?? No.
        # In graph loop: age = current_age + y. If age == retirement_age, then y = retirement_age - current_age.
        # Expense factor = (1+infl)**(y+1).
        
        y_idx = retirement_age - current_age
        # Note: df_full 'Year' is y_idx+1. 
        
        living_expense_nominal_that_year = fi_annual_spend_today * ((1 + infl_rate) ** (y_idx))
        # Wait, check graph logic:
        # if age >= stop_age: base_need = fi_annual_spend_today * ((1+infl_rate)**(y+1))
        # y starts at 0. age = current_age + y. 
        # So if age == retirement_age, then y = retirement_age - current_age.
        # So exponent is (retirement_age - current_age + 1).
        
        # Actually, let's use the standard inflation factor used for display to keep it simple,
        # but the graph uses (y+1).
        expense_inflation_exponent = (retirement_age - current_age) + 1
        living_expense_nominal_that_year = fi_annual_spend_today * ((1+infl_rate)**expense_inflation_exponent)
        
        # Adjust the balance to match graph
        bal_nom_aligned = bal_nom - living_expense_nominal_that_year
        
        # Deflate if necessary
        if show_real and infl_rate > 0:
            # Display factor matches the year
            display_deflator = (1 + infl_rate) ** (retirement_age - current_age)
            traditional_balance_display = bal_nom_aligned / display_deflator
        else:
            traditional_balance_display = bal_nom_aligned
            
        # Calculate Safe annual income from that pot
        traditional_annual_income = traditional_balance_display * base_swr_30yr
    # --- EXTRA KPI: TRADITIONAL RETIREMENT OUTCOME ---
    # Find the row for 'retirement_age' to see what the pot looks like.
    # We align this strictly with the "Age" shown on the Graph's X-axis.
    # In the graph: Age = Current_Age + Year. 
    # So for Age = Retirement_Age, we need Year = Retirement_Age - Current_Age.
    
    target_year_idx = retirement_age - current_age
    # df_full["Year"] is 1-based index corresponding to that duration.
    traditional_row = df_full[df_full["Year"] == target_year_idx]
    
    traditional_balance_display = 0.0
    traditional_annual_income = 0.0
    
    if not traditional_row.empty:
        # Get nominal balance
        bal_nom = traditional_row.iloc[0]["Balance"]
        
        # Deflate if necessary
        if show_real and infl_rate > 0:
            infl_factor = (1 + infl_rate) ** target_year_idx
            traditional_balance_display = bal_nom / infl_factor
        else:
            traditional_balance_display = bal_nom
            
        # Calculate Safe annual income from that pot
        traditional_annual_income = traditional_balance_display * base_swr_30yr
