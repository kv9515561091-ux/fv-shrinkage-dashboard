// ===========================================================================
// pq_Agg_FEFO_Compliance.pq
// Aggregation feeding PivotTable 2 (FEFO compliance by category and storage
// zone) and the shift-compliance chart.
//
// This is the query that answers the dashboard's central question: where is
// rotation actually failing, and how much shelf life is being skipped when
// it does?
// ===========================================================================

let
    Source = Excel.CurrentWorkbook(){[Name="PQ_Picks"]}[Content],

    Grouped = Table.Group(Source, {"category", "storage_zone", "shift"}, {
        {"picks",           each Table.RowCount(_), Int64.Type},
        {"violations",      each List.Count(List.RemoveNulls(
                                List.Select([fefo_compliant], each _ = false))), Int64.Type},
        {"qty_picked_kg",   each List.Sum([qty_picked_kg]), type number},
        {"expiry_gap_sum",  each List.Sum([expiry_gap_days]), type number},
        {"skipped_days",    each List.Sum(List.Select([expiry_gap_days], each _ > 0)), Int64.Type}
    }),

    WithCompliance = Table.AddColumn(Grouped, "fefo_compliance_pct",
        each if [picks] = 0 then 0 else 100 * (1 - [violations] / [picks]), type number),

    WithViolationRate = Table.AddColumn(WithCompliance, "fefo_violation_pct",
        each if [picks] = 0 then 0 else 100 * [violations] / [picks], type number),

    // Mean shelf life skipped per violating pick. This is the severity
    // measure -- a 4-day skip on a 6-day SKU destroys the lot, a 4-day skip
    // on a 30-day SKU does not.
    WithAvgGap = Table.AddColumn(WithViolationRate, "avg_expiry_gap_days",
        each if [violations] = 0 then 0 else [expiry_gap_sum] / [violations], type number),

    // Count the wrong-but-realistic rules actually used on violating picks,
    // so the dashboard can name the behaviour to retrain rather than just
    // reporting a compliance percentage.
    RuleCounts = Table.Group(
        Table.SelectRows(Source, each [fefo_compliant] = false),
        {"category", "storage_zone", "shift", "pick_rule_applied"},
        {{"rule_picks", each Table.RowCount(_), Int64.Type}}),

    RuleTop = Table.Group(RuleCounts, {"category", "storage_zone", "shift"}, {
        {"dominant_failure_rule", each
            let r = Table.Sort(
                    Table.SelectColumns(_, {"pick_rule_applied", "rule_picks"}),
                    {{"rule_picks", Order.Descending}}),
                top = Table.FirstN(r, 3)[pick_rule_applied]
            in Text.Combine(List.Transform(top, each _ & ""), " / "), type text}
    }),

    Joined = Table.NestedJoin(WithAvgGap, {"category", "storage_zone", "shift"},
                              RuleTop, {"category", "storage_zone", "shift"},
                              "rule_detail", JoinKind.LeftOuter),

    WithRule = Table.AddColumn(Joined, "dominant_failure_rule",
        each if [violations] = 0 then "n/a" else [rule_detail][dominant_failure_rule]{0},
        type text),

    Dropped = Table.RemoveColumns(WithRule, {"rule_detail"}),

    Sorted = Table.Sort(WithRule, {{"fefo_compliance_pct", Order.Ascending}}),

    Kept = Table.SelectColumns(Sorted, {
        "category", "storage_zone", "shift", "picks", "violations",
        "fefo_compliance_pct", "fefo_violation_pct", "avg_expiry_gap_days", "qty_picked_kg"
    }),

    Typed = Table.TransformColumnTypes(Kept, {
        {"fefo_compliance_pct", type number},
        {"avg_expiry_gap_days", type number}
    })
in
    Typed
