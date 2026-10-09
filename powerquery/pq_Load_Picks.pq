// ===========================================================================
// pq_Load_Picks.pq
// Power Query M -- loads the event-level FEFO pick log and derives the
// compliance measures the dashboard pivots on.
//
// The pick log is the evidence base for every FEFO claim in the workbook. It
// records, per pick: which batch was chosen, where that batch sat in the
// expiry ordering, and how many days of shelf life were skipped. Compliance
// is then a comparison against the expiry ordering, not an opinion.
// ===========================================================================

let
    Source = Excel.CurrentWorkbook(){[Name="FEFO_Pick_Log"]}[Content],

    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),

    Typed = Table.TransformColumnTypes(PromotedHeaders, {
        {"event_id",                     type text},
        {"event_ts",                     type datetime},
        {"hour_of_week",                 Int64.Type},
        {"shift",                        type text},
        {"picker_id",                    type text},
        {"sku_code",                     type text},
        {"sku_name",                     type text},
        {"category",                     type text},
        {"perishable_class",             type text},
        {"storage_zone",                 type text},
        {"batch_id",                     type text},
        {"qty_picked_kg",                type number},
        {"batches_available_in_scope",   Int64.Type},
        {"expiry_rank_if_fefo",          Int64.Type},
        {"picked_expiry_date",           type date},
        {"earliest_expiry_date",         type date},
        {"expiry_gap_days",              type number},
        {"picked_batch_age_days",        Int64.Type},
        {"pick_rule_applied",            type text},
        {"fefo_compliant",               type text}
    }),

    // TRUE/FALSE arrive as text from the CSV; slicers and pivot filters need
    // real logicals or they silently match nothing.
    AsLogical = Table.TransformColumns(Typed, {{"fefo_compliant",
        each Text.Upper(Text.Trim(_)) = "TRUE", type logical}}),

    // Severity: how many batches deep the picker went against expiry order.
    AddedDepth = Table.AddColumn(AsLogical, "rotation_depth",
        each if [fefo_compliant] then 0 else [expiry_rank_if_fefo] - 1, Int64.Type),

    AddedSeverity = Table.AddColumn(AddedDepth, "severity",
        each if [fefo_compliant] then "Compliant"
             else if [expiry_gap_days] <= 1 then "Minor (<=1d skipped)"
             else if [expiry_gap_days] <= 3 then "Moderate (1-3d skipped)"
             else "Critical (>3d skipped)", type text),

    // The wrong-but-realistic rules a picker falls back on. Naming the
    // behaviour is what makes the finding trainable: "grabbed the top of
    // the rack" is a fixable habit, "human error" is not.
    AddedRuleClass = Table.AddColumn(AddedSeverity, "failure_mode",
        each if [pick_rule_applied] = "fefo" then "None"
             else if [pick_rule_applied] = "lifo_top_of_crate" then "Top-of-rack grab (LIFO)"
             else if [pick_rule_applied] = "largest_batch" then "Largest-crate bias"
             else if [pick_rule_applied] = "fifo_queue" then "FIFO queue discipline"
             else "Nearest rack face", type text),

    AddedEventDate = Table.AddColumn(AddedRuleClass, "event_date",
        each Date.From([event_ts]), type date),

    AddedEventHour = Table.AddColumn(AddedEventDate, "event_hour",
        each Date.Hour([event_ts]), Int64.Type),

    Sorted = Table.Sort(AddedEventHour, {{"event_ts", Order.Ascending}})
in
    Sorted
