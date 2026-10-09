"""Analysis layer for the F&V shrinkage dashboard.

Establishes the causal claim behind the dashboard rather than asserting it.
The headline question is: *how much of this centre's shrinkage is actually
caused by FEFO rotation failure?*

Method
------
The generator is re-run as a counterfactual in which every pick is forced
FEFO-compliant, from the same seed and therefore the same arrivals and the
same demand curve. The difference between the observed run and the
counterfactual run is the shrinkage attributable to rotation failure, with
every other loss source (handling damage, grading rejection, pilferage,
cold-chain breach) held constant by construction.

Also produced:
  * a shrinkage Pareto by reason code
  * FEFO compliance cut by shift, zone and category
  * RVP (inventory value at risk) -- value sitting in stock whose remaining
    shelf life is inside the at-risk window, weighted by proximity to
    expiry
  * a before/after improvement projection for the README executive summary
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import generate_data as G

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "reports"

# An RVP window: stock with <=2 days of life left is materially at risk.
RVP_WINDOW_DAYS = 2


def load_observed() -> tuple[pd.DataFrame, pd.DataFrame]:
    b = pd.read_csv(RAW / "processing_center_batches.csv")
    p = pd.read_csv(RAW / "fefo_pick_events.csv")
    b["cold_chain_breach"] = b["cold_chain_breach"].astype(str).str.upper() == "TRUE"
    p["fefo_compliant"] = p["fefo_compliant"].astype(str).str.upper() == "TRUE"
    return b, p


def run_counterfactual(seed: int) -> pd.DataFrame:
    """Re-simulate with rotation failure removed, everything else identical."""
    G.FEFO_LOCK["enabled"] = True
    try:
        rng = random.Random(seed)
        rows, _, _ = G.simulate(rng)
        cf = pd.DataFrame(rows)
        cf["cold_chain_breach"] = cf["cold_chain_breach"].astype(str).str.upper() == "TRUE"
        return cf
    finally:
        G.FEFO_LOCK["enabled"] = False


def rvp_table(b: pd.DataFrame) -> pd.DataFrame:
    """Value at risk: granted value of stock inside the expiry window.

    Computed per batch as the fraction of the batch still on hand whose
    life is inside the window, weighted by how close it sits to expiry.
    The unsold closing balance is apportioned across the window.
    """
    out = []
    for _, r in b.iterrows():
        life = float(r["effective_shelf_life_days"])
        if life <= 0:
            continue
        closing = float(r["qty_received_kg"]) - float(r["qty_sold_kg"]) - float(r["qty_shrunk_kg"])
        if closing <= 0:
            continue
        # Fraction of the batch's life that falls inside the at-risk window.
        frac_window = min(1.0, RVP_WINDOW_DAYS / life)
        # Weight by proximity: a day from expiry carries far more risk than
        # a day at the edge of the window.
        weight = 1.0 - (0.5 * (1.0 - frac_window))
        value = closing * float(r["acquisition_price_inr_kg"]) * frac_window * weight
        out.append({
            "batch_id": r["batch_id"], "sku_code": r["sku_code"],
            "sku_name": r["sku_name"], "category": r["category"],
            "perishable_class": r["perishable_class"],
            "storage_zone": r["storage_zone"], "arrival_date": r["arrival_date"],
            "closing_kg": round(closing, 2),
            "unit_cost_inr_kg": r["acquisition_price_inr_kg"],
            "closing_value_inr": round(closing * float(r["acquisition_price_inr_kg"]), 2),
            "life_days": life, "at_risk_fraction": round(frac_window, 4),
            "proximity_weight": round(weight, 4),
            "rvp_inr": round(value, 2),
        })
    return pd.DataFrame(out)


def pareto_by_reason(b: pd.DataFrame) -> pd.DataFrame:
    cols = {"SR-EXP": "shrink_exp_kg", "SR-HDL": "shrink_hdl_kg", "SR-OVR": "shrink_ovr_kg",
            "SR-QLT": "shrink_qlt_kg", "SR-TMP": "shrink_tmp_kg", "SR-PIL": "shrink_pil_kg"}
    rows = []
    for code, col in cols.items():
        kg = float(b[col].sum())
        val = kg * float(
            (b[col] * b["acquisition_price_inr_kg"]).sum() / kg if kg > 0 else 0.0
        )
        rows.append({
            "reason_code": code, "reason_desc": G.SHRINK_REASON_CODES[code],
            "shrink_kg": round(kg, 2), "shrink_value_inr": round(val, 2),
        })
    df = pd.DataFrame(rows).sort_values("shrink_kg", ascending=False).reset_index(drop=True)
    total = df["shrink_kg"].sum()
    df["pct_of_shrink"] = (100 * df["shrink_kg"] / total).round(2)
    df["cumulative_pct"] = df["pct_of_shrink"].cumsum().round(2)
    return df


def compliance_cuts(p: pd.DataFrame) -> pd.DataFrame:
    cuts = []
    for dim in ["perishable_class", "category", "storage_zone", "shift", "day_of_week"]:
        g = p.groupby(dim).agg(
            picks=("fefo_compliant", "size"),
            violations=("fefo_compliant", lambda s: int((~s).sum())),
            mean_gap_days=("expiry_gap_days", "mean"),
        )
        g["compliance_pct"] = (100 * (1 - g["violations"] / g["picks"])).round(2)
        g["mean_gap_days"] = g["mean_gap_days"].round(2)
        g = g.reset_index().rename(columns={dim: "cut_value"})
        g.insert(0, "dimension", dim)
        cuts.append(g)
    return pd.concat(cuts, ignore_index=True)


def counterfactual_report(obs: pd.DataFrame, cf: pd.DataFrame) -> dict:
    # Reason-code breakdown for the counterfactual run, so the README can show
    # what the loss profile looks like once rotation is enforced -- not just
    # the total. Written out as a real table rather than inferred.
    cf_pareto = pareto_by_reason(cf)
    obs_kg = float(obs["qty_shrunk_kg"].sum())
    cf_kg = float(cf["qty_shrunk_kg"].sum())
    obs_val = float((obs["qty_shrunk_kg"] * obs["acquisition_price_inr_kg"]).sum())
    cf_val = float((cf["qty_shrunk_kg"] * cf["acquisition_price_inr_kg"]).sum())
    obs_recv = float(obs["qty_received_kg"].sum())

    obs_exp = float(obs["shrink_exp_kg"].sum())
    cf_exp = float(cf["shrink_exp_kg"].sum())

    per_sku = []
    o = obs.groupby("sku_code").agg(shr=("qty_shrunk_kg", "sum"), exp=("shrink_exp_kg", "sum"),
                                    recv=("qty_received_kg", "sum"))
    c = cf.groupby("sku_code").agg(shr_cf=("qty_shrunk_kg", "sum"),
                                   exp_cf=("shrink_exp_kg", "sum"))
    m = o.join(c).fillna(0.0)
    m["expiry_avoided_kg"] = m["exp"] - m["exp_cf"]
    m["shrink_avoided_kg"] = m["shr"] - m["shr_cf"]
    m = m.sort_values("expiry_avoided_kg", ascending=False)

    return {
        "observed_shrink_kg": round(obs_kg, 2),
        "observed_shrink_value_inr": round(obs_val, 2),
        "observed_shrink_pct_of_received": round(100 * obs_kg / obs_recv, 2),
        "counterfactual_shrink_kg": round(cf_kg, 2),
        "counterfactual_shrink_value_inr": round(cf_val, 2),
        "counterfactual_shrink_pct_of_received": round(100 * cf_kg / obs_recv, 2),
        "expiry_kg_observed": round(obs_exp, 2),
        "expiry_kg_counterfactual": round(cf_exp, 2),
        "expiry_avoided_kg": round(obs_exp - cf_exp, 2),
        "pct_of_expiry_caused_by_rotation_failure": (
            round(100 * (obs_exp - cf_exp) / obs_exp, 2) if obs_exp > 0 else None
        ),
        "shrink_avoided_kg": round(obs_kg - cf_kg, 2),
        "shrink_value_avoided_inr": round(obs_val - cf_val, 2),
        "top_skus_expiry_avoided": m.head(6).reset_index().round(2).to_dict("records"),
        "_counterfactual_pareto": cf_pareto,
    }


def workbook_inputs(obs: pd.DataFrame, picks: pd.DataFrame, rvp: pd.DataFrame
                    ) -> dict[str, pd.DataFrame]:
    """Materialise the four pivot source tables.

    These are the same four aggregations the .pq scripts define, expressed in
    pandas so the workbook ships populated. The M queries are embedded in the
    .xlsx for a user who wants to audit or re-run the logic in Power Query;
    these tables are what the PivotTables actually bind to, so the workbook
    opens with live numbers on any machine.
    """
    wk = obs[obs["carry_in"].astype(str).str.upper() != "TRUE"].copy()
    wk["received_value_inr"] = wk["qty_received_kg"] * wk["acquisition_price_inr_kg"]

    # --- 1. Category shrinkage matrix -----------------------------------
    reason_cols = ["shrink_exp_kg", "shrink_hdl_kg", "shrink_ovr_kg",
                   "shrink_qlt_kg", "shrink_tmp_kg", "shrink_pil_kg"]
    cat = wk.groupby(["category", "perishable_class"], as_index=False).agg(
        qty_received_kg=("qty_received_kg", "sum"),
        qty_granted_kg=("qty_granted_kg", "sum"),
        qty_sold_kg=("qty_sold_kg", "sum"),
        received_value_inr=("received_value_inr", "sum"),
        batches=("batch_id", "count"),
        **{c: (c, "sum") for c in reason_cols},
    )
    cat["qty_shrunk_kg"] = cat[reason_cols].sum(axis=1)
    cat["shrink_pct"] = (100 * cat["qty_shrunk_kg"] / cat["qty_received_kg"]).round(2)
    cat["shrink_value_inr"] = (cat["received_value_inr"]
                               * cat["qty_shrunk_kg"] / cat["qty_received_kg"]).round(2)
    cat["sell_through_pct"] = (100 * cat["qty_sold_kg"] / cat["qty_granted_kg"]).round(2)
    cat = cat.sort_values("shrink_value_inr", ascending=False).reset_index(drop=True)

    # --- 2. FEFO compliance by category / zone / shift --------------------
    comp = picks.groupby(["category", "storage_zone", "shift"], as_index=False).agg(
        picks_count=("fefo_compliant", "size"),
        violations=("fefo_compliant", lambda s: int((~s).sum())),
        qty_picked_kg=("qty_picked_kg", "sum"),
        expiry_gap_sum=("expiry_gap_days", "sum"),
    )
    comp["fefo_compliance_pct"] = (100 * (1 - comp["violations"]
                                         / comp["picks_count"])).round(2)
    comp["avg_expiry_gap_days"] = np.where(
        comp["violations"] > 0,
        (comp["expiry_gap_sum"] / comp["violations"].replace(0, 1)).round(2), 0.0)
    top_rule = (picks[~picks["fefo_compliant"]]
                .groupby(["category", "storage_zone", "shift", "pick_rule_applied"])
                .size().reset_index(name="n")
                .sort_values("n", ascending=False)
                .groupby(["category", "storage_zone", "shift"])["pick_rule_applied"]
                .apply(lambda s: " / ".join(list(dict.fromkeys(s))[:3]))
                .rename("dominant_failure_rule").reset_index())
    comp = comp.merge(top_rule, on=["category", "storage_zone", "shift"], how="left")
    comp = comp.sort_values("fefo_compliance_pct").reset_index(drop=True)

    # --- 3. Daily RVP trend ----------------------------------------------
    day = rvp.groupby(["arrival_date"], as_index=False).agg(
        rvp_inr=("rvp_inr", "sum"),
        closing_value_inr=("closing_value_inr", "sum"),
    )
    daily = wk.groupby("arrival_date", as_index=False).agg(
        day_of_week=("day_of_week", "first"),
        qty_received_kg=("qty_received_kg", "sum"),
        qty_sold_kg=("qty_sold_kg", "sum"),
        qty_shrunk_kg=("qty_shrunk_kg", "sum"),
        cold_chain_breaches=("cold_chain_breach",
                             lambda s: int(s.astype(str).str.upper().eq("TRUE").sum())),
        batches=("batch_id", "count"),
    )
    daily = daily.merge(day, on="arrival_date", how="left").fillna({"rvp_inr": 0.0,
                                                                   "closing_value_inr": 0.0})
    daily["shrink_pct"] = (100 * daily["qty_shrunk_kg"] / daily["qty_received_kg"]).round(2)
    daily["rvp_pct_of_closing"] = np.where(
        daily["closing_value_inr"] > 0,
        (100 * daily["rvp_inr"] / daily["closing_value_inr"]).round(2), 0.0)
    daily["sell_through_pct"] = (100 * daily["qty_sold_kg"]
                                 / daily["qty_received_kg"]).round(2)
    daily = daily.sort_values("arrival_date").reset_index(drop=True)

    # --- 4. SKU bottleneck ranking ---------------------------------------
    sku = wk.groupby(["sku_code", "sku_name", "category", "perishable_class",
                      "storage_zone"], as_index=False).agg(
        qty_received_kg=("qty_received_kg", "sum"),
        qty_sold_kg=("qty_sold_kg", "sum"),
        qty_shrunk_kg=("qty_shrunk_kg", "sum"),
        received_value_inr=("received_value_inr", "sum"),
        shrink_exp_kg=("shrink_exp_kg", "sum"),
        shrink_hdl_kg=("shrink_hdl_kg", "sum"),
        shrink_qlt_kg=("shrink_qlt_kg", "sum"),
        shrink_tmp_kg=("shrink_tmp_kg", "sum"),
        shrink_pil_kg=("shrink_pil_kg", "sum"),
        mean_shelf_life_days=("effective_shelf_life_days", "mean"),
        mean_age_at_receipt=("age_at_receipt_days", "mean"),
    )
    sku["avg_cost_inr_kg"] = (sku["received_value_inr"] / sku["qty_received_kg"]).round(2)
    sku["shrink_value_inr"] = (sku["qty_shrunk_kg"] * sku["avg_cost_inr_kg"]).round(2)
    sku["shrink_pct"] = (100 * sku["qty_shrunk_kg"] / sku["qty_received_kg"]).round(2)
    rot = picks.groupby("sku_code", as_index=False).agg(
        picks_n=("fefo_compliant", "size"),
        violations_n=("fefo_compliant", lambda s: int((~s).sum())),
        gap_sum=("expiry_gap_days", "sum"),
    )
    sku = sku.merge(rot, on="sku_code", how="left").fillna({"picks_n": 0, "violations_n": 0,
                                                           "gap_sum": 0.0})
    sku["fefo_compliance_pct"] = np.where(
        sku["picks_n"] > 0,
        (100 * (1 - sku["violations_n"] / sku["picks_n"])).round(2), 0.0)
    sku["avg_expiry_gap_days"] = np.where(
        sku["violations_n"] > 0,
        (sku["gap_sum"] / sku["violations_n"].replace(0, 1)).round(2), 0.0)
    sku = sku.sort_values("shrink_value_inr", ascending=False).reset_index(drop=True)
    sku.insert(0, "loss_rank", np.arange(1, len(sku) + 1))

    def driver(r: pd.Series) -> str:
        if r["qty_shrunk_kg"] == 0:
            return "No loss"
        if r["fefo_compliance_pct"] < 75 and r["shrink_exp_kg"] > 0.4 * r["qty_shrunk_kg"]:
            return "Rotation failure (FEFO)"
        if r["shrink_qlt_kg"] > 0.35 * r["qty_shrunk_kg"]:
            return "Upstream quality (grading reject)"
        if r["shrink_pil_kg"] > 0.25 * r["qty_shrunk_kg"]:
            return "Pilferage / shrink theft"
        if r["shrink_hdl_kg"] > 0.25 * r["qty_shrunk_kg"]:
            return "Handling damage"
        if r["shrink_tmp_kg"] > 0:
            return "Cold-chain breach"
        return "Mixed / over-purchase"

    sku["primary_driver"] = sku.apply(driver, axis=1)
    sku["mean_shelf_life_days"] = sku["mean_shelf_life_days"].round(2)
    sku["mean_age_at_receipt"] = sku["mean_age_at_receipt"].round(2)

    keep_sku = ["loss_rank", "sku_code", "sku_name", "category", "perishable_class",
                "storage_zone", "qty_received_kg", "qty_sold_kg", "qty_shrunk_kg",
                "shrink_pct", "shrink_value_inr", "avg_cost_inr_kg",
                "mean_shelf_life_days", "mean_age_at_receipt",
                "fefo_compliance_pct", "avg_expiry_gap_days", "primary_driver"]
    sku = sku[keep_sku]
    cat = cat[["category", "perishable_class", "qty_received_kg", "qty_sold_kg",
               "qty_shrunk_kg", "shrink_pct", "shrink_value_inr", "sell_through_pct",
               "received_value_inr", "batches", "shrink_exp_kg", "shrink_hdl_kg",
               "shrink_ovr_kg", "shrink_qlt_kg", "shrink_tmp_kg", "shrink_pil_kg"]]
    return {"PQ_Category_Agg": cat, "PQ_FEFO_Agg": comp,
            "PQ_DailyRVP": daily, "PQ_SKUBottleneck": sku}


def main() -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    PROC.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    print("[analyze] loading observed run")
    obs, picks = load_observed()

    print("[analyze] running FEFO-locked counterfactual (same seed)")
    cf = run_counterfactual(G.SEED)

    # ---- KPI summary ---------------------------------------------------
    total_recv = float(obs["qty_received_kg"].sum())
    total_granted = float(obs["qty_granted_kg"].sum())
    total_sold = float(obs["qty_sold_kg"].sum())
    total_shrink = float(obs["qty_shrunk_kg"].sum())
    total_value = float((obs["qty_received_kg"] * obs["acquisition_price_inr_kg"]).sum())
    shrink_value = float((obs["qty_shrunk_kg"] * obs["acquisition_price_inr_kg"]).sum())

    compliance = float(100 * picks["fefo_compliant"].mean())
    pi = float(np.average(obs.groupby("sku_code")["product_in_stock_pct_sku"].first(),
                          weights=obs.groupby("sku_code")["qty_received_kg"].sum()))

    kpis = {
        "week": "2026-10-05 to 2026-10-11",
        "centre": "Simulated Regional Processing Centre",
        "skus": int(obs["sku_code"].nunique()),
        "batches": int(len(obs)),
        "picks": int(len(picks)),
        "qty_received_kg": round(total_recv, 2),
        "qty_granted_kg": round(total_granted, 2),
        "qty_sold_kg": round(total_sold, 2),
        "qty_shrunk_kg": round(total_shrink, 2),
        "received_value_inr": round(total_value, 2),
        "shrink_value_inr": round(shrink_value, 2),
        "shrink_pct_of_received": round(100 * total_shrink / total_recv, 2),
        "sell_through_pct_of_granted": round(100 * total_sold / total_granted, 2),
        "fefo_compliance_pct": round(compliance, 2),
        "fefo_violation_pct": round(100 - compliance, 2),
        "mean_expiry_gap_days_on_violation": round(
            float(picks.loc[~picks["fefo_compliant"], "expiry_gap_days"].mean()), 2),
        "product_in_stock_pct": round(pi, 2),
        "cold_chain_breach_batches": int(obs["cold_chain_breach"].sum()),
        "rvp_window_days": RVP_WINDOW_DAYS,
    }

    # ---- Derived tables -----------------------------------------------
    rvp = rvp_table(obs)
    pareto = pareto_by_reason(obs)
    cuts = compliance_cuts(picks.assign(
        day_of_week=picks["event_ts"].str.slice(0, 10).pipe(pd.to_datetime).dt.day_name()
    ))
    cf_rep = counterfactual_report(obs, cf)
    cf_pareto = cf_rep.pop("_counterfactual_pareto")
    cf_pareto.to_csv(PROC / "counterfactual_pareto.csv", index=False)

    kpis["rvp_total_inr"] = round(float(rvp["rvp_inr"].sum()), 2)
    kpis["closing_value_inr"] = round(float(rvp["closing_value_inr"].sum()), 2)
    kpis["rvp_as_pct_of_closing_value"] = round(
        100 * float(rvp["rvp_inr"].sum()) / float(rvp["closing_value_inr"].sum()), 2
    )
    kpis.update({f"cf_{k}": v for k, v in cf_rep.items() if not isinstance(v, list)})

    obs.to_csv(PROC / "batches_enriched.csv", index=False)
    picks.to_csv(PROC / "picks_enriched.csv", index=False)
    rvp.to_csv(PROC / "rvp_by_batch.csv", index=False)
    pareto.to_csv(PROC / "shrinkage_pareto.csv", index=False)
    cuts.to_csv(PROC / "fefo_compliance_cuts.csv", index=False)
    pd.DataFrame([kpis]).to_csv(OUT / "kpi_summary.csv", index=False)

    # Pivot source tables for the workbook.
    tables = workbook_inputs(obs, picks, rvp)
    for name, df in tables.items():
        df.to_csv(PROC / f"{name}.csv", index=False)
    obs.to_csv(PROC / "PQ_Batches.csv", index=False)
    picks.to_csv(PROC / "PQ_Picks.csv", index=False)

    with (OUT / "analysis_findings.json").open("w", encoding="utf-8") as fh:
        json.dump({"kpis": kpis, "counterfactual": cf_rep,
                   "pareto": pareto.to_dict("records"),
                   "top_skus_expiry_avoided": cf_rep["top_skus_expiry_avoided"]},
                  fh, indent=2)

    # ---- Console report -------------------------------------------------
    print()
    print("=" * 74)
    print("F&V PROCESSING CENTRE -- WEEKLY SHRINKAGE & FEFO DIAGNOSTIC")
    print("=" * 74)
    print(f"Received            {total_recv:>12,.0f} kg   Rs {total_value:>12,.0f}")
    print(f"Granted             {total_granted:>12,.0f} kg")
    print(f"Sold                {total_sold:>12,.0f} kg")
    print(f"Shrunk              {total_shrink:>12,.0f} kg   Rs {shrink_value:>12,.0f}")
    print(f"Shrink % of received{100*total_shrink/total_recv:>11.2f} %")
    print(f"Sell-through %      {100*total_sold/total_granted:>11.2f} %")
    print(f"FEFO compliance     {compliance:>11.2f} %")
    print(f"PI % (value-weighted){pi:>11.2f} %")
    print(f"RVP ({RVP_WINDOW_DAYS}d window)  Rs {float(rvp['rvp_inr'].sum()):>12,.0f}"
          f"   ({kpis['rvp_as_pct_of_closing_value']}% of closing value)")
    print("-" * 74)
    print("COUNTERFACTUAL: identical arrivals and demand, rotation failure removed")
    print(f"  expiry observed        {cf_rep['expiry_kg_observed']:>10,.0f} kg")
    print(f"  expiry counterfactual  {cf_rep['expiry_kg_counterfactual']:>10,.0f} kg")
    print(f"  expiry avoided         {cf_rep['expiry_avoided_kg']:>10,.0f} kg"
          f"   ({cf_rep['pct_of_expiry_caused_by_rotation_failure']}% of all expiry)")
    print(f"  total shrink avoided   {cf_rep['shrink_avoided_kg']:>10,.0f} kg"
          f"   Rs {cf_rep['shrink_value_avoided_inr']:,.0f}")
    print(f"  shrink %% would move    {cf_rep['observed_shrink_pct_of_received']:>10.2f} %"
          f" -> {cf_rep['counterfactual_shrink_pct_of_received']:.2f} %")
    print("-" * 74)
    print("SHRINKAGE PARETO")
    for _, r in pareto.iterrows():
        print(f"  {r['reason_code']}  {r['pct_of_shrink']:>6.2f}%  "
              f"{r['shrink_kg']:>9,.1f} kg   {r['reason_desc']}")
    print("-" * 74)
    print("FEFO COMPLIANCE BY SHIFT")
    sh = cuts[cuts["dimension"] == "shift"]
    for _, r in sh.iterrows():
        print(f"  {r['cut_value']:<24} {r['compliance_pct']:>6.2f}%  "
              f"gap {r['mean_gap_days']:>5.2f}d  ({int(r['picks'])} picks)")
    print("=" * 74)
    print(f"[analyze] wrote {len(rvp)} RVP rows, {len(pareto)} pareto rows, "
          f"{len(cuts)} compliance cuts")


if __name__ == "__main__":
    main()
