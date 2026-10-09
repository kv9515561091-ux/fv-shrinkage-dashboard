// ===========================================================================
// pq_Agg_CategoryShrinkage.pq
// Aggregation feeding PivotTable 1 (shrinkage Pareto by category and reason)
// and the shrinkage-by-category chart.
//
// The reason columns stay separate rather than being unpivoted, because the
// dashboard pivots on them as a matrix: category down the rows, reason codes
// across the columns. Unpivoting first would flatten the matrix and lose the
// comparison.
// ===========================================================================

let
    Source = Excel.CurrentWorkbook(){[Name="PQ_Batches"]}[Content],

    // Drop the carry-in lots' receipts so the denominator is what this week
    // actually bought, not what was already on the rack when it started.
    ReceivedThisWeek = Table.SelectRows(Source, each [carry_in] = false),

    Grouped = Table.Group(ReceivedThisWeek, {"category", "perishable_class"}, {
        {"qty_received_kg",       each List.Sum([qty_received_kg]), type number},
        {"qty_granted_kg",        each List.Sum([qty_granted_kg]), type number},
        {"qty_sold_kg",           each List.Sum([qty_sold_kg]), type number},
        {"received_value_inr",    each List.Sum([received_value_inr]), type number},
        {"shrink_exp_kg",         each List.Sum([shrink_exp_kg]), type number},
        {"shrink_hdl_kg",         each List.Sum([shrink_hdl_kg]), type number},
        {"shrink_ovr_kg",         each List.Sum([shrink_ovr_kg]), type number},
        {"shrink_qlt_kg",         each List.Sum([shrink_qlt_kg]), type number},
        {"shrink_tmp_kg",         each List.Sum([shrink_tmp_kg]), type number},
        {"shrink_pil_kg",         each List.Sum([shrink_pil_kg]), type number},
        {"batches",               each Table.RowCount(_), Int64.Type}
    }),

    WithTotalShrink = Table.AddColumn(Grouped, "qty_shrunk_kg",
        each [shrink_exp_kg] + [shrink_hdl_kg] + [shrink_ovr_kg]
           + [shrink_qlt_kg] + [shrink_tmp_kg] + [shrink_pil_kg], type number),

    WithShrinkPct = Table.AddColumn(WithTotalShrink, "shrink_pct",
        each if [qty_received_kg] = 0 then 0
             else 100 * [qty_shrunk_kg] / [qty_received_kg], type number),

    // Value-weighted shrink: the rupee cost of the loss, not just its weight.
    WithShrinkValue = Table.AddColumn(WithShrinkPct, "shrink_value_inr",
        each [received_value_inr] * [qty_shrunk_kg] / [qty_received_kg], type number),

    WithSellThrough = Table.AddColumn(WithShrinkValue, "sell_through_pct",
        each if [qty_granted_kg] = 0 then 0
             else 100 * [qty_sold_kg] / [qty_granted_kg], type number),

    Sorted = Table.Sort(WithSellThrough, {{"shrink_value_inr", Order.Descending}}),

    Renamed = Table.RenameColumns(Sorted, {{"perishable_class", "perishability"}}),

    Typed = Table.TransformColumnTypes(Renamed, {
        {"shrink_pct", type number}, {"sell_through_pct", type number}
    })
in
    Typed
