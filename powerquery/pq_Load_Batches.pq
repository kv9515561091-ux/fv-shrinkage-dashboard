// ===========================================================================
// pq_Load_Batches.pq
// Power Query M -- loads the batch ledger from the workbook's Raw_Batches
// sheet, applies explicit column types, and derives the FEFO / RVP /
// shrink-pct columns the dashboard pivots on.
//
// Source of truth note: this reads from Excel.CurrentWorkbook rather than
// the CSV on disk. That is deliberate -- the shipped workbook opens and
// refreshes on any machine without a file-path dependency, while
// pq_Load_Batches_FileVariant.pq holds the equivalent Csv.Document version
// for use outside this workbook.
// ===========================================================================

let
    Source = Excel.CurrentWorkbook(){[Name="Raw_Batches"]}[Content],

    // ---- Promote headers -------------------------------------------------
    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),

    // ---- Explicit types --------------------------------------------------
    // Every column is typed by name. Untyped text columns silently become
    // text in Excel and then sort and aggregate lexicographically, which is
    // how a shrink-% column ends up "9.5" ranking above "12".
    Typed = Table.TransformColumnTypes(PromotedHeaders, {
        {"batch_id",                 type text},
        {"sku_code",                 type text},
        {"sku_name",                 type text},
        {"category",                 type text},
        {"perishable_class",         type text},
        {"storage_zone",             type text},
        {"carry_in",                 type text},
        {"arrival_date",             type date},
        {"arrival_ts",               type datetime},
        {"day_of_week",              type text},
        {"shift",                    type text},
        {"source_mandi",             type text},
        {"source_district",          type text},
        {"fpo_id",                   type text},
        {"age_at_receipt_days",      type number},
        {"temp_at_receipt_c",        type number},
        {"cold_chain_breach",        type text},
        {"qty_received_kg",          type number},
        {"qty_grade_a_kg",           type number},
        {"qty_grade_b_kg",           type number},
        {"qty_grade_c_kg",           type number},
        {"grading_reject_kg",        type number},
        {"qty_granted_kg",           type number},
        {"acquisition_price_inr_kg", type number},
        {"granted_value_inr",        type number},
        {"nominal_shelf_life_days",  type number},
        {"effective_shelf_life_days",type number},
        {"best_before_date",         type date},
        {"days_on_hand_at_close",    type number},
        {"qty_sold_kg",              type number},
        {"qty_shrunk_kg",            type number},
        {"shrink_pct_of_received",   type number},
        {"shrink_value_inr",         type number},
        {"shrink_exp_kg",            type number},
        {"shrink_hdl_kg",            type number},
        {"shrink_ovr_kg",            type number},
        {"shrink_qlt_kg",            type number},
        {"shrink_tmp_kg",            type number},
        {"shrink_pil_kg",            type number},
        {"primary_shrink_reason",    type text},
        {"primary_shrink_reason_desc", type text},
        {"fefo_picks_sku_total",     type number},
        {"fefo_violations_sku_total",type number},
        {"fefo_violation_rate_sku_pct", type number},
        {"lost_sales_kg_sku_total",  type number},
        {"product_in_stock_pct_sku", type number}
    }),

    // ---- Normalise the boolean-as-text flags ----------------------------
    // The CSV writes TRUE/FALSE as text. Pivot slicers cannot filter on
    // text "TRUE" reliably, so convert to real logicals.
    BreachBool = Table.TransformColumns(Typed, {{"cold_chain_breach",
        each Text.Upper(Text.Trim(_)) = "TRUE", type logical}}),
    CarryInBool = Table.TransformColumns(BreachBool, {{"carry_in",
        each Text.Upper(Text.Trim(_)) = "TRUE", type logical}}),

    // ---- Derived measures ----------------------------------------------
    AddedMeasures = Table.AddColumn(CarryInBool, "received_value_inr",
        each [qty_received_kg] * [acquisition_price_inr_kg], type number),

    AddedShrinkPct = Table.AddColumn(AddedMeasures, "shrink_pct_recalc",
        each if [qty_received_kg] = 0 then 0
             else 100 * [qty_shrunk_kg] / [qty_received_kg], type number),

    AddedSellThrough = Table.AddColumn(AddedShrinkPct, "sell_through_pct",
        each if [qty_granted_kg] = 0 then 0
             else 100 * [qty_sold_kg] / [qty_granted_kg], type number),

    // A batch that arrived on a cold-chain breach has had part of its
    // shelf life consumed by heat before it ever reached the rack. Flagging
    // it here is what lets the dashboard separate "expired because it sat
    // too long" from "expired because it arrived warm".
    AddedArrivalRisk = Table.AddColumn(AddedSellThrough, "arrival_condition",
        each if [cold_chain_breach] then "Cold-chain breach at receipt"
             else if [age_at_receipt_days] >= 7 then "Aged at receipt (7d+)"
             else "Compliant", type text),

    // Over-purchase test: received materially more than the week's sell-through
    // of that SKU would absorb, without a perishable reason for it.
    AddedOverstock = Table.AddColumn(AddedArrivalRisk, "overstock_flag",
        each if [shrink_ovr_kg] > 0 then "True" else "False", type text),

    Sorted = Table.Sort(AddedOverstock, {{"arrival_date", Order.Ascending}, {"sku_code", Order.Ascending}})
in
    Sorted
