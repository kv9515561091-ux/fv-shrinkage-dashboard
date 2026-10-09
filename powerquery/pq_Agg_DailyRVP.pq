// ===========================================================================
// pq_Agg_DailyRVP.pq
// Aggregation feeding PivotTable 3 (daily RVP and shrinkage trend) and the
// daily RVP line chart.
//
// RVP (inventory value at risk) is the value sitting in stock whose remaining
// shelf life has fallen inside the at-risk window, weighted by how close it
// is to expiry. Weighting matters: a batch one day from expiry is not the
// same exposure as one at the far edge of the window, and an unweighted
// count treats them as identical.
// ===========================================================================

let
    Source = Excel.CurrentWorkbook(){[Name="PQ_Batches"]}[Content],

    // Drop carry-in lots so the denominator is what this week actually
    // bought, not what was on the rack when the week started.
    ReceivedThisWeek = Table.SelectRows(Source, each [carry_in] = false),

    // Residual stock: received less sold less already-written-off.
    AddedResidual = Table.AddColumn(ReceivedThisWeek, "residual_kg",
        each [qty_received_kg] - [qty_sold_kg] - [qty_shrunk_kg], type number),

    AddedResidualValue = Table.AddColumn(AddedResidual, "residual_value_inr",
        each [residual_kg] * [acquisition_price_inr_kg], type number),

    // Fraction of the batch's total life that falls inside the 2-day window.
    AddedWindowFrac = Table.AddColumn(AddedResidualValue, "at_risk_fraction",
        each if [effective_shelf_life_days] <= 0 then 0
             else Number.Min(1, 2 / [effective_shelf_life_days]), type number),

    // Proximity weight: 1.0 for a batch already at expiry, 0.5 at the outer
    // edge of the window. Linear is a deliberate simplification -- it keeps
    // the measure auditable rather than hiding an assumption in a curve.
    AddedProximity = Table.AddColumn(AddedWindowFrac, "proximity_weight",
        each 1 - (0.5 * (1 - [at_risk_fraction])), type number),

    AddedRVP = Table.AddColumn(AddedProximity, "rvp_inr",
        each [residual_value_inr] * [at_risk_fraction] * [proximity_weight], type number),

    Grouped = Table.Group(AddedRVP, {"arrival_date", "day_of_week"}, {
        {"qty_received_kg",   each List.Sum([qty_received_kg]), type number},
        {"qty_sold_kg",       each List.Sum([qty_sold_kg]), type number},
        {"qty_shrunk_kg",     each List.Sum([qty_shrunk_kg]), type number},
        {"residual_kg",       each List.Sum([residual_kg]), type number},
        {"residual_value_inr",each List.Sum([residual_value_inr]), type number},
        {"rvp_inr",           each List.Sum([rvp_inr]), type number},
        {"batches",           each Table.RowCount(_), Int64.Type},
        {"cold_chain_breaches", each List.Count(
                                List.Select([cold_chain_breach], each _ = true)), Int64.Type}
    }),

    AddedShrinkPct = Table.AddColumn(Grouped, "shrink_pct",
        each if [qty_received_kg] = 0 then 0
             else 100 * [qty_shrunk_kg] / [qty_received_kg], type number),

    // Share of closing value that is at risk. This is the headline RVP ratio
    // the executive summary quotes.
    AddedRVPPct = Table.AddColumn(AddedShrinkPct, "rvp_pct_of_closing",
        each if [residual_value_inr] = 0 then 0
             else 100 * [rvp_inr] / [residual_value_inr], type number),

    AddedSellThrough = Table.AddColumn(AddedRVPPct, "sell_through_pct",
        each if [qty_received_kg] = 0 then 0
             else 100 * [qty_sold_kg] / [qty_received_kg], type number),

    Sorted = Table.Sort(AddedSellThrough, {{"arrival_date", Order.Ascending}}),

    Typed = Table.TransformColumnTypes(Sorted, {
        {"rvp_inr", type number}, {"shrink_pct", type number},
        {"rvp_pct_of_closing", type number}
    })
in
    Typed
