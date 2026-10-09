// ===========================================================================
// pq_Load_Batches_FileVariant.pq
// The same transformation as pq_Load_Batches.pq, but sourced from the CSV on
// disk. Use this when the workbook is refreshed outside its own folder, or as
// the reference implementation when porting the logic to Power BI.
//
// Requires the CSV folder to be set to:
//   <repo>\fv-shrinkage-dashboard\data\raw
// ===========================================================================

let
    Source = Csv.Document(
        File.Contents("data\raw\processing_center_batches.csv"),
        [Delimiter=",", Columns=48, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),

    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),

    // The CSV is written with a UTF-8 BOM so Excel opens it without mangling
    // the rupee-adjacent text. Strip it if the header row still carries it.
    CleanHeaders = Table.RenameColumns(PromotedHeaders,
        List.Transform(List.Names(PromotedHeaders), each {_, Text.Trim(Text.Replace(_, "#(tab)", ""))})),

    // Excel cannot infer a date column that arrives as "2026-10-05" without
    // a locale hint; ISO-8601 parses deterministically across regions.
    ParsedDates = Table.TransformColumns(CleanHeaders, {
        {"arrival_date",   each Date.FromText(_, "yyyy-MM-dd"), type date},
        {"best_before_date", each Date.FromText(_, "yyyy-MM-dd"), type date},
        {"arrival_ts",     each DateTime.FromText(_, "yyyy-MM-ddTHH:mm:ss"), type datetime}
    }),

    Typed = Table.TransformColumnTypes(ParsedDates, {
        {"sku_code", type text}, {"category", type text},
        {"perishable_class", type text}, {"storage_zone", type text},
        {"qty_received_kg", type number}, {"qty_granted_kg", type number},
        {"qty_sold_kg", type number}, {"qty_shrunk_kg", type number},
        {"acquisition_price_inr_kg", type number},
        {"effective_shelf_life_days", type number},
        {"fefo_violation_rate_sku_pct", type number},
        {"product_in_stock_pct_sku", type number},
        {"shrink_exp_kg", type number}, {"shrink_hdl_kg", type number},
        {"shrink_qlt_kg", type number}, {"shrink_tmp_kg", type number},
        {"shrink_pil_kg", type number}, {"shrink_ovr_kg", type number}
    }),

    AddedValue = Table.AddColumn(Typed, "received_value_inr",
        each [qty_received_kg] * [acquisition_price_inr_kg], type number),

    AddedShrinkPct = Table.AddColumn(AddedValue, "shrink_pct_recalc",
        each if [qty_received_kg] = 0 then 0
             else 100 * [qty_shrunk_kg] / [qty_received_kg], type number),

    Sorted = Table.Sort(AddedShrinkPct, {{"arrival_date", Order.Ascending}})
in
    Sorted
