"""Build the F&V shrinkage dashboard workbook.

Two-stage build, because the two halves have opposite performance profiles:

  Stage 1 (openpyxl)  writes every data sheet as a real Excel Table
                      (ListObject). openpyxl creates genuine table objects, so
                      the sheets are not just formatted ranges -- Excel shows
                      them in the Name Manager and PivotTables bind to them
                      properly. Writing ~80k cells through the COM interface
                      one at a time takes minutes; this takes seconds.

  Stage 2 (COM)       opens the file and adds the things only Excel itself can
                      create: four live PivotTables with caches, dashboard
                      charts, conditional formatting, and the embedded
                      Power Query M.

On Power Query
--------------
The M is embedded with `Workbook.Queries.Add`, which is reliable through COM.
*Loading* query results into a worksheet needs a WorkbookConnection the COM
automation interface will not build without a UI, and attempting it blocks
indefinitely. So the queries ship embedded (auditable, and one click from the
Data ribbon to load) while the PivotTables bind to the pandas-materialised
`PQ_*` sheets, which carry identical logic -- so the workbook opens populated
on any machine. See docs/PowerQuery-Setup.md.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

import win32com.client as win32

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
PQDIR = ROOT / "powerquery"
OUT = ROOT / "fv_shrinkage_dashboard.xlsx"

# Excel enum values spelled out so the script does not depend on gencache.
XL_ROW_FIELD, XL_COLUMN_FIELD, XL_DATA_FIELD = 1, 2, 4
XL_SUM, XL_AVERAGE = -4157, -4106
XL_DATABASE, XL_PIVOTTABLE_VERSION = 1, 8
XL_BAR_CLUSTERED, XL_COLUMN_CLUSTERED = 57, 51

HDR_FILL = PatternFill("solid", fgColor="1F3864")
HDR_FONT = Font(bold=True, color="FFFFFF", size=10)
CARD_LBL_FONT = Font(bold=True, size=9, color="595959")
CARD_VAL_FONT = Font(bold=True, size=18)
SECTION_FONT = Font(bold=True, size=11, color="1F3864")

SHEET_ORDER = ["Dashboard", "PT1_Category_Shrinkage", "PT2_FEFO_Compliance",
               "PT3_Daily_RVP_Trend", "PT4_Bottleneck_SKUs", "README",
               "Data_Dictionary", "Raw_Batches", "FEFO_Pick_Log",
               "PQ_Batches", "PQ_Picks", "PQ_Category_Agg", "PQ_FEFO_Agg",
               "PQ_DailyRVP", "PQ_SKUBottleneck", "Shrinkage_Pareto"]

PIVOT_SPECS = [
    # (dest sheet, anchor, pivot name, source table, row fields, col fields,
    #  (field, function, label), number format)
    ("PT1_Category_Shrinkage", "A3", "PT_Category_Shrinkage", "PQ_Category_Agg",
     ["category"], [],
     [("shrink_value_inr", XL_SUM, "Loss Rs"), ("shrink_pct", XL_AVERAGE, "Shrink %")],
     "#,##0"),
    ("PT2_FEFO_Compliance", "A3", "PT_FEFO_Compliance", "PQ_FEFO_Agg",
     ["category", "storage_zone"], [],
     [("fefo_compliance_pct", XL_AVERAGE, "FEFO compliance %"),
      ("avg_expiry_gap_days", XL_AVERAGE, "Days skipped"),
      ("picks_count", XL_SUM, "Picks")],
     "#,##0.0"),
    ("PT3_Daily_RVP_Trend", "A3", "PT_Daily_RVP", "PQ_DailyRVP",
     ["arrival_date", "day_of_week"], [],
     [("qty_received_kg", XL_SUM, "Received kg"),
      ("qty_sold_kg", XL_SUM, "Sold kg"),
      ("rvp_inr", XL_SUM, "RVP Rs"),
      ("shrink_pct", XL_AVERAGE, "Shrink %")],
     "#,##0"),
    ("PT4_Bottleneck_SKUs", "A3", "PT_Bottleneck", "PQ_SKUBottleneck",
     ["category"], [],
     [("shrink_value_inr", XL_SUM, "Loss Rs"),
      ("shrink_pct", XL_AVERAGE, "Shrink %"),
      ("fefo_compliance_pct", XL_AVERAGE, "FEFO compliance %")],
     "#,##0"),
]

DICTIONARY = [
    ("batch_id", "Unique lot identifier, B-<sku>-<arrival day>-<sequence>.", "batch"),
    ("carry_in", "TRUE if the lot was on the rack before the measured week began. Excluded from the week's loss denominators.", "batch"),
    ("qty_received_kg", "Gross weight off the vehicle at intake.", "batch"),
    ("qty_granted_kg", "Weight that passed the grading gate and entered marketable stock.", "batch"),
    ("grading_reject_kg", "Weight rejected at intake. Never becomes stock, so it is a sourcing loss rather than a storage loss.", "batch"),
    ("acquisition_price_inr_kg", "Weighted acquisition cost of the granted weight.", "batch"),
    ("effective_shelf_life_days", "Remaining life at receipt. Shorter than nominal when the lot arrived warm.", "batch"),
    ("best_before_date", "Printed date the lot must leave the chain by. Drives the FEFO ordering.", "batch"),
    ("cold_chain_breach", "TRUE if intake temperature fell outside the storage zone's tolerance band.", "batch"),
    ("age_at_receipt_days", "Farm-to-DC transit lag. Long age on a short-life SKU is a sourcing failure, not a storage one.", "batch"),
    ("qty_sold_kg", "Weight despatched to stores against demand.", "batch"),
    ("qty_shrunk_kg", "Total written off, all reason codes.", "batch"),
    ("shrink_exp_kg", "Written off because best-before passed with stock still on hand.", "batch"),
    ("shrink_hdl_kg", "Bruising and handling damage accrued in-store.", "batch"),
    ("shrink_qlt_kg", "Rejected at the grading gate.", "batch"),
    ("shrink_tmp_kg", "Loss attributable to a cold-chain breach.", "batch"),
    ("shrink_pil_kg", "Pilferage / shrink theft.", "batch"),
    ("fefo_violation_rate_sku_pct", "Share of that SKU's picks that took a later-expiry batch than the earliest available.", "SKU (repeated on each batch row)"),
    ("product_in_stock_pct_sku", "1 - (lost sales / demand). Value-weighted to the weekly KPI.", "SKU (repeated on each batch row)"),
    ("event_id", "Unique fulfilment event identifier.", "pick event"),
    ("expiry_rank_if_fefo", "Position of the picked batch in the expiry ordering. 1 = earliest expiry.", "pick event"),
    ("expiry_gap_days", "Days of shelf life skipped by picking out of order. 0 on a compliant pick.", "pick event"),
    ("pick_rule_applied", "Rule the picker actually used: fefo, lifo_top_of_crate, largest_batch, fifo_queue, nearest_rack_face.", "pick event"),
    ("fefo_compliant", "TRUE if the picked batch was the earliest-expiry batch available at that moment.", "pick event"),
    ("picked_batch_age_days", "Days the lot had been held when picked. Deeper means more likely mis-picked.", "pick event"),
    ("rvp_inr", "Inventory value at risk: residual value inside the 2-day window, weighted by proximity to expiry.", "batch"),
    ("proximity_weight", "1.0 at expiry, 0.5 at the outer edge of the at-risk window. Linear by design.", "batch"),
    ("loss_rank", "SKUs ordered by rupee value lost, not percentage lost.", "SKU"),
    ("primary_driver", "Heuristic attribution of the loss to a cause, so the bottleneck table is actionable.", "SKU"),
]

README_LINES = [
    ("F&V SHRINKAGE & FEFO DIAGNOSTIC -- HOW TO USE THIS WORKBOOK", "title"),
    ("", ""),
    ("WHAT THIS IS", "h"),
    ("  A simulated processing-centre operations week (05-11 Oct 2026, 24 SKUs) analysed for where value", ""),
    ("  is lost and why. All data is synthetic and seeded; nothing here is a real trading record. The", ""),
    ("  generator and the analysis live in scripts/ on the repository and reproduce these numbers exactly.", ""),
    ("", ""),
    ("SHEETS", "h"),
    ("  Dashboard              KPI cards, shrinkage Pareto, FEFO compliance by shift, and read-me-first notes.", ""),
    ("  PT1_Category_Shrinkage Rupee loss by category x reason code.", ""),
    ("  PT2_FEFO_Compliance   Rotation adherence by category x storage zone, with mean shelf life skipped.", ""),
    ("  PT3_Daily_RVP_Trend   Daily receipts, sell-through and inventory value at risk.", ""),
    ("  PT4_Bottleneck_SKUs   Per-SKU loss ranked by rupee value, with the primary driver attributed.", ""),
    ("  Raw_Batches           The batch ledger (Power Query source).", ""),
    ("  FEFO_Pick_Log         Event-level pick log. This is the evidence base for every FEFO number.", ""),
    ("  PQ_*                  Materialised Power Query outputs, pre-computed so the workbook opens populated.", ""),
    ("  Data_Dictionary       Every column, its meaning, and its grain.", ""),
    ("", ""),
    ("POWER QUERY", "h"),
    ("  {n} queries are embedded in this file. Data > Queries & Connections > pick a query > Load To >", ""),
    ("  Worksheet to materialise it. The same M is in powerquery/*.pq on the repository, readable without", ""),
    ("  opening Excel. The PQ_* sheets were produced by identical logic in scripts/analyze.py, which is", ""),
    ("  why the workbook is populated on first open.", ""),
    ("", ""),
    ("REFRESHING", "h"),
    ("  Option A (Excel):   Data > Refresh All, after loading the embedded queries.", ""),
    ("  Option B (Python):  python scripts/generate_data.py", ""),
    ("                      python scripts/analyze.py", ""),
    ("                      python scripts/build_workbook.py", ""),
    ("  The generator is seeded (seed=20261009) so a re-run reproduces these numbers exactly.", ""),
    ("", ""),
    ("HOW TO READ THE FEFO NUMBERS", "h"),
    ("  fefo_compliant is a comparison, not a label. At every pick the simulator knows which batch had", ""),
    ("  the earliest best-before date; a violation is picking anything else. expiry_gap_days records how", ""),
    ("  much shelf life was skipped, which is what makes a violation on a 3-day SKU distinguishable from", ""),
    ("  one on a 35-day SKU.", ""),
    ("", ""),
    ("  The causal claim is established by counterfactual rather than correlation: the same week is", ""),
    ("  re-simulated with every pick forced compliant. The result is in reports/analysis_findings.json.", ""),
]


def write_table(ws, df: pd.DataFrame, name: str) -> None:
    """Write a DataFrame as a real Excel Table with a styled header."""
    cols = list(df.columns)
    ws.append(cols)
    for row in df.itertuples(index=False, name=None):
        ws.append([None if pd.isna(v) else v for v in row])
    for cell in ws[1]:
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
    if len(df):
        ref = f"A1:{get_column_letter(len(cols))}{len(df) + 1}"
        tbl = Table(displayName=name, ref=ref)
        tbl.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2", showRowStripes=True,
            showColumnStripes=False, showFirstColumn=False, showLastColumn=False)
        ws.add_table(tbl)
    ws.freeze_panes = "A2"
    # Sensible column widths without scanning every row.
    for i, col in enumerate(cols, start=1):
        width = min(max(11, len(str(col)) + 2), 34)
        if col in {"sku_name", "reason_desc", "primary_shrink_reason_desc",
                   "primary_driver", "meaning", "dominant_failure_rule",
                   "storage_zone", "category", "perishable_class", "shift",
                   "source_mandi", "pick_rule_applied", "fpo_id"}:
            width = 26
        ws.column_dimensions[get_column_letter(i)].width = width


def section(ws, row: int, text: str) -> int:
    ws.cell(row=row, column=1, value=text).font = SECTION_FONT
    return row + 1


def build_dashboard(ws, kpi: pd.Series, pareto: pd.DataFrame,
                    fefo: pd.DataFrame) -> dict[str, str]:
    """KPI cards, Pareto block and shift-compliance block. Returns chart anchors."""
    ws.column_dimensions["A"].width = 30
    for col in "BCDEFGHIJKLMNOP":
        ws.column_dimensions[col].width = 12

    ws["A1"] = "F&V PROCESSING CENTRE -- SHRINKAGE & FEFO DIAGNOSTIC"
    ws["A1"].font = Font(bold=True, size=16, color="1F3864")
    ws["A2"] = ("Simulated operations week 05-11 Oct 2026  |  24 SKUs  |  synthetic seeded data"
                "  |  method in README.md")
    ws["A2"].font = Font(italic=True, size=9, color="808080")

    cards = [
        ("RECEIVED (kg)", f"{kpi.qty_received_kg:,.0f}", "D9E1F2"),
        ("LOSS VALUE (Rs)", f"{kpi.shrink_value_inr:,.0f}", "F8CBAD"),
        ("SHRINK % OF RECEIVED", f"{kpi.shrink_pct_of_received:.2f}%", "FFE699"),
        ("SELL-THROUGH %", f"{kpi.sell_through_pct_of_granted:.2f}%", "C6E0B4"),
        ("FEFO COMPLIANCE", f"{kpi.fefo_compliance_pct:.2f}%", "F4B183"),
        ("PRODUCT IN-STOCK %", f"{kpi.product_in_stock_pct:.2f}%", "FFE699"),
        ("RVP 2-DAY WINDOW (Rs)", f"{kpi.rvp_total_inr:,.0f}", "FFE699"),
        ("EXPIRY FROM ROTATION FAILURE", f"{kpi.cf_pct_of_expiry_caused_by_rotation_failure:.1f}%", "F4B183"),
    ]
    row = 4
    for i, (label, value, fill) in enumerate(cards):
        r = row + (i // 4) * 3
        col = 1 + (i % 4) * 3
        lc = ws.cell(row=r, column=col, value=label)
        lc.font = CARD_LBL_FONT
        lc.fill = PatternFill("solid", fgColor=fill)
        lc.alignment = Alignment(horizontal="center")
        ws.merge_cells(start_row=r, start_column=col, end_row=r, end_column=col + 2)
        for c2 in range(col, col + 3):
            ws.cell(row=r, column=c2).fill = PatternFill("solid", fgColor=fill)
        vc = ws.cell(row=r + 1, column=col, value=value)
        vc.font = CARD_VAL_FONT
        vc.alignment = Alignment(horizontal="center")
        ws.merge_cells(start_row=r + 1, start_column=col, end_row=r + 1, end_column=col + 2)
        for c2 in range(col, col + 3):
            ws.cell(row=r + 1, column=c2).fill = PatternFill("solid", fgColor=fill)

    r = row + 3 * ((len(cards) + 3) // 4) + 1
    r = section(ws, r, "READ THIS FIRST")
    notes = [
        "1.  FEFO rotation failure is the headline loss driver, not an incidental one. The counterfactual",
        "     re-simulates this identical week with every pick forced FEFO-compliant and attributes the",
        f"     difference to rotation failure: {kpi.cf_pct_of_expiry_caused_by_rotation_failure:.1f}% of all shelf-life expiry, worth",
        f"     Rs {kpi.cf_shrink_value_avoided_inr:,.0f} of avoidable loss and moving shrink from {kpi.shrink_pct_of_received:.2f}% to {kpi.cf_counterfactual_shrink_pct_of_received:.2f}%.",
        "2.  The night shift is the worst segment. Low supervision, no pick-face audit, deepest rack fatigue.",
        "3.  Grade-C rejection at the intake gate is the second loss line and is an upstream sourcing",
        "     problem, not a processing-centre problem. Fixing it means grading at the FPO, not here.",
        "4.  Sheets prefixed PQ_ are the Power Query outputs. The M for each is embedded in this workbook",
        "     and in powerquery/*.pq on the repository.",
    ]
    for line in notes:
        ws.cell(row=r, column=1, value=line).font = Font(size=9)
        r += 1
    r += 1

    r = section(ws, r, "SHRINKAGE PARETO BY REASON CODE")
    pareto_hdr = r
    for j, h in enumerate(["code", "reason", "kg", "value Rs", "% of loss", "cum %"], start=1):
        cell = ws.cell(row=pareto_hdr, column=j, value=h)
        cell.font = Font(bold=True, size=9)
    r += 1
    pareto_top = r
    for row_vals in pareto.itertuples(index=False):
        ws.cell(row=r, column=1, value=str(row_vals.reason_code))
        ws.cell(row=r, column=2, value=str(row_vals.reason_desc))
        ws.cell(row=r, column=3, value=round(float(row_vals.shrink_kg), 1)).number_format = "#,##0"
        ws.cell(row=r, column=4, value=round(float(row_vals.shrink_value_inr), 0)).number_format = "#,##0"
        ws.cell(row=r, column=5, value=round(float(row_vals.pct_of_shrink), 1)).number_format = '0.0"%"'
        ws.cell(row=r, column=6, value=round(float(row_vals.cumulative_pct), 1)).number_format = '0.0"%"'
        r += 1

    r += 1
    r = section(ws, r, "FEFO COMPLIANCE BY SHIFT -- the fastest fixable win")
    sh = fefo.groupby("shift", as_index=False).agg(
        picks=("picks_count", "sum"), viol=("violations", "sum"),
        gap=("expiry_gap_sum", "sum"))
    sh["compliance"] = (100 * (1 - sh.viol / sh.picks)).round(2)
    sh["avg_gap"] = (sh.gap / sh.viol.replace(0, 1)).round(2)
    shift_hdr = r
    for j, h in enumerate(["shift", "FEFO compliance %", "picks", "avg days skipped"], start=1):
        ws.cell(row=shift_hdr, column=j, value=h).font = Font(bold=True, size=9)
    r += 1
    shift_top = r
    for row_vals in sh.itertuples(index=False):
        ws.cell(row=r, column=1, value=str(row_vals.shift))
        ws.cell(row=r, column=2, value=float(row_vals.compliance)).number_format = '0.00"%"'
        ws.cell(row=r, column=3, value=int(row_vals.picks))
        ws.cell(row=r, column=4, value=float(row_vals.avg_gap)).number_format = "0.00"
        r += 1

    return {
        "pareto": f"Dashboard!$A${pareto_hdr}:$D${pareto_top + len(pareto) - 1}",
        "shift": f"Dashboard!$A${shift_hdr}:$B${shift_top + len(sh) - 1}",
        "pareto_anchor": f"G{pareto_hdr - 1}",
        "shift_anchor": f"G{shift_top + len(sh) + 2}",
    }


def stage1_tables() -> dict:
    print("[build_workbook] stage 1: writing data sheets (openpyxl)")
    batches = pd.read_csv(PROC / "PQ_Batches.csv")
    picks = pd.read_csv(PROC / "PQ_Picks.csv")
    cat_agg = pd.read_csv(PROC / "PQ_Category_Agg.csv")
    fefo_agg = pd.read_csv(PROC / "PQ_FEFO_Agg.csv")
    daily = pd.read_csv(PROC / "PQ_DailyRVP.csv")
    bottleneck = pd.read_csv(PROC / "PQ_SKUBottleneck.csv")
    pareto = pd.read_csv(PROC / "shrinkage_pareto.csv")
    kpi = pd.read_csv(REPORTS / "kpi_summary.csv").iloc[0]

    wb = Workbook()
    ws = wb.active
    ws.title = "Dashboard"
    anchors = build_dashboard(ws, kpi, pareto, fefo_agg)

    for name in SHEET_ORDER:
        if name != "Dashboard":
            wb.create_sheet(name)

    data_tables = {
        "Raw_Batches": batches, "FEFO_Pick_Log": picks, "PQ_Batches": batches,
        "PQ_Picks": picks, "PQ_Category_Agg": cat_agg, "PQ_FEFO_Agg": fefo_agg,
        "PQ_DailyRVP": daily, "PQ_SKUBottleneck": bottleneck,
        "Shrinkage_Pareto": pareto,
    }
    for name, df in data_tables.items():
        write_table(wb[name], df, name)

    ws = wb["Data_Dictionary"]
    write_table(ws, pd.DataFrame(DICTIONARY, columns=["column", "meaning", "grain"]),
                "Data_Dictionary")
    ws.column_dimensions["B"].width = 90

    ws = wb["README"]
    embedded = len(list(PQDIR.glob("*.pq")))
    for i, (line, kind) in enumerate(README_LINES, start=1):
        text = line.replace("{n}", str(embedded))
        cell = ws.cell(row=i, column=1, value=text)
        if kind == "title":
            cell.font = Font(bold=True, size=13, color="1F3864")
        elif kind == "h":
            cell.font = Font(bold=True, size=11, color="1F3864")
        else:
            cell.font = Font(size=10)
    ws.column_dimensions["A"].width = 100

    # Heat map on the bottleneck sheet: worst SKUs read red.
    ws = wb["PT4_Bottleneck_SKUs"]
    ws.conditional_formatting.add(
        "A5:Z60",
        ColorScaleRule(start_type="min", start_color="63BE7B",
                       mid_type="percentile", mid_value=50, mid_color="FFEB84",
                       end_type="max", end_color="F8696B"))

    for name in SHEET_ORDER:
        wb[name].sheet_properties.tabColor = (
            "808080" if name.startswith(("Raw_", "FEFO_", "PQ_", "Shrinkage_"))
            else ("2F5597" if name.startswith("PT") else "1F3864"))

    if OUT.exists():
        OUT.unlink()
    wb.save(OUT)
    print(f"[build_workbook] stage 1 done -> {OUT.name} "
          f"({OUT.stat().st_size/1024:.0f} KB)")
    return anchors


def stage2_excel(anchors: dict) -> None:
    print("[build_workbook] stage 2: pivots, charts, embedded queries (COM)")
    xl = win32.Dispatch("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        wb = xl.Workbooks.Open(str(OUT))
        dash = wb.Worksheets("Dashboard")

        for dest, anchor, name, table, rows, cols, values, numfmt in PIVOT_SPECS:
            ws = wb.Worksheets(dest)
            cache = wb.PivotCaches().Create(XL_DATABASE, table, XL_PIVOTTABLE_VERSION)
            pt = cache.CreatePivotTable(ws.Range(anchor), name)
            for i, f in enumerate(rows, start=1):
                pf = pt.PivotFields(f)
                pf.Orientation = XL_ROW_FIELD
                pf.Position = i
            for f in cols:
                pt.PivotFields(f).Orientation = XL_COLUMN_FIELD
            for f, fn, label in values:
                pf = pt.PivotFields(f)
                pf.Orientation = XL_DATA_FIELD
                pf.Function = fn
                pf.NumberFormat = numfmt
                pf.Name = label
            pt.RowAxisLayout(1)
            pt.TableStyle2 = "PivotStyleMedium9"
            print(f"  pivot {name}: {pt.TableRange2.Address}")

        # Charts, anchored beside the dashboard blocks.
        ch = dash.Shapes.AddChart2(-1, XL_BAR_CLUSTERED,
                                   dash.Range(anchors["pareto_anchor"]).Left,
                                   dash.Range(anchors["pareto_anchor"]).Top,
                                   520, 240)
        ch.Chart.SetSourceData(dash.Range(anchors["pareto"]))
        ch.Chart.HasTitle = True
        ch.Chart.ChartTitle.Text = "Where the value is lost (Rs by reason code)"
        ch.Chart.HasLegend = True

        ch2 = dash.Shapes.AddChart2(-1, XL_COLUMN_CLUSTERED,
                                    dash.Range(anchors["shift_anchor"]).Left,
                                    dash.Range(anchors["shift_anchor"]).Top,
                                    520, 220)
        ch2.Chart.SetSourceData(dash.Range(anchors["shift"]))
        ch2.Chart.HasTitle = True
        ch2.Chart.ChartTitle.Text = "FEFO compliance by shift -- night shift is the gap"
        ch2.Chart.HasLegend = False

        embedded = 0
        for pq in sorted(PQDIR.glob("*.pq")):
            m = pq.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
            try:
                wb.Queries.Add(pq.stem, m)
                embedded += 1
            except Exception as exc:
                print(f"  ! could not embed {pq.name}: {exc}")
        print(f"  embedded {embedded} Power Query definitions")

        dash.Activate()
        wb.Save()
        time.sleep(1.0)
        # Workbook.PivotTables is not exposed on every Excel build, so count
        # per worksheet instead of trusting the collection accessor.
        n_pivots = sum(wb.Worksheets(i).PivotTables().Count
                       for i in range(1, wb.Worksheets.Count + 1))
        print(f"[build_workbook] saved -> {wb.Queries.Count} queries, "
              f"{n_pivots} pivot tables, "
              f"{OUT.stat().st_size/1024:.0f} KB")
        wb.Close(False)
    finally:
        try:
            xl.Quit()
        except Exception:
            pass
        time.sleep(0.6)


def main() -> None:
    if not (PROC / "PQ_SKUBottleneck.csv").exists():
        raise SystemExit("Run generate_data.py and analyze.py first.")
    anchors = stage1_tables()
    stage2_excel(anchors)


if __name__ == "__main__":
    main()
