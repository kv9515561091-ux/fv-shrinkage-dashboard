// ===========================================================================
// pq_Agg_SKUBottleneck.pq
// Aggregation feeding PivotTable 4 -- the Top-N ₹-loss bottleneck table.
//
// This is the "pinpoint where wastage occurs" query. It ranks SKUs by rupee
// value lost, not by percentage lost, because a 40% shrink on coriander is a
// fraction of the rupee value of a 4% shrink on onions. A percentage-ranked
// list would send the category manager after the wrong SKUs.
//
// It also carries each SKU's rotation metrics alongside the loss, so a
// bottleneck can be attributed to a cause rather than just reported.
// ===========================================================================

let
    Source = Excel.CurrentWorkbook(){[Name="PQ_Batches"]}[Content],
    Picks = Excel.CurrentWorkbook(){[Name="PQ_Picks"]}[Content],

    ReceivedThisWeek = Table.SelectRows(Source, each [carry_in] = false),

    // ---- Loss side: aggregate to one row per SKU -------------------------
    LossBySKU = Table.Group(ReceivedThisWeek, {"sku_code", "sku_name", "category",
                                               "perishable_class", "storage_zone"}, {
        {"qty_received_kg",  each List.Sum([qty_received_kg]), type number},
        {"qty_sold_kg",      each List.Sum([qty_sold_kg]), type number},
        {"qty_shrunk_kg",    each List.Sum([qty_shrunk_kg]), type number},
        {"received_value_inr", each List.Sum([received_value_inr]), type number},
        {"shrink_exp_kg",    each List.Sum([shrink_exp_kg]), type number},
        {"shrink_hdl_kg",    each List.Sum([shrink_hdl_kg]), type number},
        {"shrink_qlt_kg",    each List.Sum([shrink_qlt_kg]), type number},
        {"shrink_tmp_kg",    each List.Sum([shrink_tmp_kg]), type number},
        {"shrink_pil_kg",    each List.Sum([shrink_pil_kg]), type number},
        {"mean_shelf_life_days", each List.Average([effective_shelf_life_days]), type number},
        {"mean_age_at_receipt",   each List.Average([age_at_receipt_days]), type number},
        {"breach_batches",   each List.Count(
                                List.Select([cold_chain_breach], each _ = true)), Int64.Type}
    }),

    // Weighted average acquisition cost -- a simple mean would misprice SKUs
    // whose lots vary in grade and mandi.
    WithAvgCost = Table.AddColumn(LossBySKU, "avg_cost_inr_kg",
        each if [qty_received_kg] = 0 then 0
             else [received_value_inr] / [qty_received_kg], type number),

    WithShrinkValue = Table.AddColumn(WithAvgCost, "shrink_value_inr",
        each [qty_shrunk_kg] * [avg_cost_inr_kg], type number),

    WithShrinkPct = Table.AddColumn(WithShrinkValue, "shrink_pct",
        each if [qty_received_kg] = 0 then 0
             else 100 * [qty_shrunk_kg] / [qty_received_kg], type number),

    // ---- Rotation side: same grain, from the pick log --------------------
    RotationBySKU = Table.Group(Picks, {"sku_code"}, {
        {"picks",       each Table.RowCount(_), Int64.Type},
        {"violations",  each List.Count(List.RemoveNulls(
                          List.Select([fefo_compliant], each _ = false))), Int64.Type},
        {"gap_sum",     each List.Sum([expiry_gap_days]), type number},
        {"gap_max",     each List.Max([expiry_gap_days]), type number}
    }),

    // ---- Join the two sides ----------------------------------------------
    Joined = Table.NestedJoin(WithShrinkPct, {"sku_code"}, RotationBySKU,
                              {"sku_code"}, "rotation", JoinKind.LeftOuter),

    Flattened = Table.ExpandTableColumn(Joined, "rotation",
        {"picks", "violations", "gap_sum", "gap_max"}, {"picks", "violations",
                                                        "gap_sum", "gap_max"}),

    WithCompliance = Table.AddColumn(Flattened, "fefo_compliance_pct",
        each if [picks] = null or [picks] = 0 then 0
             else 100 * (1 - [violations] / [picks]), type number),

    WithAvgGap = Table.AddColumn(WithCompliance, "avg_expiry_gap_days",
        each if [violations] = null or [violations] = 0 then 0
             else [gap_sum] / [violations], type number),

    // Expiry-weighted loss: the rupee value of the expiry component alone.
    WithExpiryValue = Table.AddColumn(WithAvgGap, "expiry_value_inr",
        each [shrink_exp_kg] * [avg_cost_inr_kg], type number),

    // Attribution heuristic. States the primary driver of the loss so the
    // bottleneck table is actionable rather than a ranking of symptoms.
    WithDriver = Table.AddColumn(WithExpiryValue, "primary_driver",
        each if [qty_shrunk_kg] = 0 then "No loss"
             else if [fefo_compliance_pct] < 75 and [shrink_exp_kg] > 0.4 * [qty_shrunk_kg]
                  then "Rotation failure (FEFO)"
             else if [shrink_qlt_kg] > 0.35 * [qty_shrunk_kg]
                  then "Upstream quality (grading reject)"
             else if [shrink_pil_kg] > 0.25 * [qty_shrunk_kg]
                  then "Pilferage / shrink theft"
             else if [shrink_hdl_kg] > 0.25 * [qty_shrunk_kg]
                  then "Handling damage"
             else if [breach_batches] > 0 and [shrink_tmp_kg] > 0
                  then "Cold-chain breach"
             else "Mixed / over-purchase", type text),

    Sorted = Table.Sort(WithDriver, {{"shrink_value_inr", Order.Descending}}),

    Ranked = Table.AddIndexColumn(Sorted, "loss_rank", 1, 1, Int64.Type),

    Kept = Table.SelectColumns(Ranked, {
        "loss_rank", "sku_code", "sku_name", "category", "perishable_class",
        "storage_zone", "qty_received_kg", "qty_sold_kg", "qty_shrunk_kg",
        "shrink_pct", "shrink_value_inr", "avg_cost_inr_kg",
        "mean_shelf_life_days", "mean_age_at_receipt", "breach_batches",
        "fefo_compliance_pct", "avg_expiry_gap_days", "primary_driver"
    }),

    Typed = Table.TransformColumnTypes(Kept, {
        {"loss_rank", Int64.Type}, {"shrink_value_inr", type number},
        {"shrink_pct", type number}, {"fefo_compliance_pct", type number}
    })
in
    Typed
