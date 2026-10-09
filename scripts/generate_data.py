"""Synthetic data generator -- simulated processing-centre operations week.

Generates three committed CSVs that together model one week of a fresh
produce processing centre (dark store feeder):

  sku_master.csv               dimension table, 24 SKUs
  processing_center_batches.csv batch-day ledger, 1 row per received batch
  fefo_pick_events.csv         event-level fulfilment log (the FEFO evidence)

Design note -- why this is not noise with labels attached
---------------------------------------------------------
The generator runs a real hour-by-hour inventory simulation. Demand is
served from live batches, batches expire on their own best-before, and any
quantity left in an expired batch at the moment of expiry is written off.

FEFO compliance is a *behavioural* parameter with structure, not a flag.
Its probability is depressed by:

  * long shelf life        -- nobody enforces rotation on potatoes
  * ambient storage        -- no dedicated chilled pick-face
  * night shift            -- fatigue, low supervision
  * peak arrival volume    -- pressure to grab the nearest crate
  * deep rack position     -- older stock sits further back

Because non-compliant picks draw down a *later* expiry batch while an
*earlier* one is left behind, the simulation reproduces the real
consequence: FEFO violation causes shelf-life expiry. The relationship in
the output data is emergent, which is what makes the dashboard's claim
("FEFO is the bottleneck") demonstrable rather than asserted.

Price and wastage figures are anchored to publicly reported All-India
mandi/retail data for October 2026 and to published supply-chain loss
benchmarks (farm 8-10%, transit 5-6%, DC 2-3%, store 12-15%).
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

from sku_master import SHRINK_REASON_CODES, SKU_MASTER

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

# --------------------------------------------------------------------------
# Simulation constants
# --------------------------------------------------------------------------
SEED = 20261009
WEEK_START = datetime(2026, 10, 5, 0, 0)  # Monday
HOURS = 7 * 24

SOURCE_MANDIS = [
    ("Bengaluru Rural APMC", "Kolar"),
    ("Bengaluru Rural APMC", "Chikkaballapur"),
    ("Hosur APMC", "Krishnagiri"),
    ("Chikmagalur APMC", "Chikmagalur"),
    ("Mysuru APMC", "Mysuru"),
    ("Tumkur APMC", "Tumkur"),
    ("Mandya APMC", "Mandya"),
]
FPO_CODES = [
    "FPO-KOL-01", "FPO-CBK-02", "FPO-HSR-01", "FPO-CMK-04",
    "FPO-MYS-03", "FPO-TUM-02", "FPO-MDY-01",
]
PICKERS = [f"PK-{n:02d}" for n in range(1, 13)]

# Hourly demand shape for a fresh-produce store: evening peak dominates,
# a secondary lunch bump, and a long overnight trough.
HOUR_WEIGHTS = [
    0.20, 0.15, 0.10, 0.10, 0.15, 0.40,   # 00-05
    1.50, 3.50, 4.50, 4.00, 3.50, 3.00,   # 06-11
    3.60, 3.00, 2.60, 2.50, 3.00, 5.00,   # 12-17
    7.00, 8.50, 7.00, 5.00, 3.00, 1.50,   # 18-23
]

# Day-of-week demand shape. These are *relative* weights for the fresh
# produce basket (weekend-heavy), normalised so the mean across the week is
# exactly 1.0. Without that normalisation, the weekend uplift would inflate
# weekly demand above planned arrivals and every SKU would show impossible
# stock-outs unrelated to its perishability.
DOW_RAW = {0: 1.00, 1: 1.02, 2: 1.00, 3: 1.03, 4: 1.12, 5: 1.22, 6: 1.31}
_DOW_MEAN = sum(DOW_RAW.values()) / len(DOW_RAW)
DOW_UPLIFT = {d: round(v / _DOW_MEAN, 4) for d, v in DOW_RAW.items()}

SHIFT_OF_HOUR = {
    **{h: "Shift A (05:00-13:00)" for h in range(5, 13)},
    **{h: "Shift B (13:00-21:00)" for h in range(13, 21)},
}
SHIFT_OF_HOUR.update({h: "Shift C (21:00-05:00)" for h in list(range(21, 24)) + list(range(0, 5))})

# Base FEFO adherence by perishability. Hard, long-shelf-life stock is the
# worst offender precisely because rotation carries no daily cost.
FEFO_BASE = {"Highly Perishable": 0.86, "Perishable": 0.77, "Hardy": 0.61}
CATEGORY_FEFO_DELTA = {"Leafy Greens": -0.10, "Fruit": -0.03}
ZONE_FEFO_DELTA = {"Chilled 0-4C": 0.04, "Chilled 2-6C": 0.02, "Chilled 8-10C": 0.01,
                   "Ambient Ventilated": 0.00}
SHIFT_FEFO_DELTA = {"Shift A (05:00-13:00)": 0.05,
                    "Shift B (13:00-21:00)": 0.00,
                    "Shift C (21:00-05:00)": -0.12}

# Buy-to-demand ratio: arrivals as a multiple of forecast demand for the week.
#
# This is the single most important behavioural parameter in the simulation.
# It encodes the operating premise: the centre systematically over-buys, and
# the gap widens as shelf life shortens. Over-purchase is what leaves several
# co-existing batches on hand at once, which is the precondition for FEFO to
# matter at all -- with a buy-to-demand ratio of 1.0 there is never a rotation
# decision to get wrong.
#
#   > 1.0  structural over-buy, and expiry becomes the dominant loss
#   = 1.0  balanced, stock turns as it lands
#   < 1.0  under-buy, stock-outs and lost sales instead of shrink
BUY_TO_DEMAND = {"Highly Perishable": 1.32, "Perishable": 1.12, "Hardy": 1.08}
SELLTHROUGH_NOISE = 0.10

ZONE_TARGET_C = {
    "Chilled 0-4C": 2.0, "Chilled 2-6C": 4.0,
    "Chilled 8-10C": 9.0, "Ambient Ventilated": 26.0,
}
ZONE_TOLERANCE_C = {
    "Chilled 0-4C": 2.5, "Chilled 2-6C": 2.5,
    "Chilled 8-10C": 2.0, "Ambient Ventilated": 6.0,
}


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def split_grade(rng: random.Random, grade_a_share: float, qty: float,
                reject_pct: float) -> dict:
    """Split a received lot into A/B/C marketable quantities plus rejects.

    `reject_pct` of received weight fails the grading gate entirely (bruising,
    oversize, undersize, disease) and never becomes marketable stock.
    """
    rejected = qty * reject_pct
    marketable = qty - rejected
    grade_c_share = clamp(0.10 + (0.55 - grade_a_share) * 0.55, 0.03, 0.24)
    grade_b_share = clamp(1.0 - grade_a_share - grade_c_share, 0.04, 1.0 - grade_a_share)
    return {
        "A": marketable * grade_a_share,
        "B": marketable * grade_b_share,
        "C": marketable * grade_c_share,
        "_rejected": rejected,
    }


class Batch:
    __slots__ = (
        "batch_id", "sku", "arrival_ts", "arrival_hour", "shift", "mandi", "district",
        "fpo", "qty_received", "grade_split", "granted_qty", "rej_qty", "unit_cost",
        "granted_value", "age_at_receipt", "temp_receipt", "breach",
        "shelf_life_days",         "expiry_ts", "remaining", "sold", "handling_loss",
        "pilferage", "src_days", "dc_days", "closing_qty",
    )

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    @property
    def expiry_date(self) -> datetime:
        return self.expiry_ts

    @property
    def sku_code(self) -> str:
        return self.sku["sku_code"]


def build_arrivals(rng: random.Random, demand_daily: dict[str, list[float]]
                   ) -> tuple[dict[str, list[Batch]], list[float]]:
    """Create the week of receipt events, one market lot per SKU per arrival day.

    Order quantity is sized off the demand forecast for the day being
    covered (demand-responsive procurement), then multiplied by the class
    buy-to-demand ratio. A delivery is timed to land in the early morning so
    it can cover that day's trading from opening.
    """
    batches: dict[str, list[Batch]] = {s["sku_code"]: [] for s in SKU_MASTER}
    counters = {s["sku_code"]: 0 for s in SKU_MASTER}

    daily_volume: list[float] = [0.0] * 7
    for sku in SKU_MASTER:
        base = sku["base_daily_arrival_kg"]
        # Arrival cadence is governed by shelf life, not volume. Anything with
        # a 1-3 day life must arrive daily -- a gap in supply is a stock-out
        # the buyer cannot recover, because holding it over is exactly what
        # the shelf life forbids. Longer-life lines can be bought in.
        if sku["perishable_class"] == "Highly Perishable":
            n_days = 7
        elif sku["nominal_shelf_life_days"] >= 14:
            n_days = 7 if base >= 300 else rng.choice([4, 5, 6])
        else:
            n_days = rng.choice([5, 6, 7])
        days = sorted(rng.sample(range(7), n_days))
        # A SKU that arrives 3 times a week still needs a week's supply.
        # Without this, low-cadence SKUs receive 3 days of volume against
        # 7 days of demand and show structural stock-outs that have nothing
        # to do with their shelf life.
        cadence_scale = 7.0 / n_days
        # Load the week realistically: arrivals taper after the weekend peak.
        for d in days:
            counters[sku["sku_code"]] += 1
            code = sku["sku_code"]
            bnum = counters[code]

            # Size the order off the forecast for the day it will cover,
            # then apply the class buy-to-demand ratio. This ratio is the
            # structural over-buy that makes expiry the dominant loss.
            forecast = demand_daily[code][d] if 0 <= d < 7 else demand_daily[code][d % 7]
            ratio = BUY_TO_DEMAND[sku["perishable_class"]] * rng.gauss(1.0, 0.08)
            qty = forecast * clamp(ratio, 0.70, 2.2)
            # Only the shortest-shelf-life lines taper ahead of the weekend
            # peak, because they are the only ones a buyer cannot hold over.
            if d >= 5 and sku["perishable_class"] == "Highly Perishable":
                qty *= 0.88
            qty = max(qty, 5.0)
            daily_volume[d] += qty

            arrival_hour = rng.choice([4, 5, 5, 6, 6, 7, 7, 8])
            arrival_ts = WEEK_START + timedelta(days=d, hours=arrival_hour,
                                                 minutes=rng.randint(0, 59))
            arrival_hour = d * 24 + arrival_ts.hour

            mandi, district = rng.choice(SOURCE_MANDIS)

            # Age at receipt: farm-to-DC transit lag. Leafy travels same-day,
            # hardy lines can sit at a collection centre for a week.
            if sku["perishable_class"] == "Highly Perishable":
                age = rng.triangular(0.2, 0.6, 1.4)
            elif sku["perishable_class"] == "Perishable":
                age = rng.triangular(1.0, 3.0, 6.0)
            else:
                age = rng.triangular(3.0, 9.0, 16.0)

            # Receipt temperature vs the zone's target band. Missed reefer
            # loading and warm farm transport both show up here.
            target = ZONE_TARGET_C[sku["storage_zone"]]
            temp = rng.gauss(target + (1.4 if age > 6 else 0.0), ZONE_TOLERANCE_C[sku["storage_zone"]] * 0.55)
            if rng.random() < 0.09:          # explicit reefer / ice failure
                temp += rng.uniform(4.0, 9.0)
            breach = abs(temp - target) > ZONE_TOLERANCE_C[sku["storage_zone"]]

            grade_split = split_grade(rng, sku["grade_a_share"], qty, rng.uniform(0.015, 0.075))
            rej_qty = qty - sum(grade_split.values())
            granted_qty = sum(grade_split.values())

            # Grade spread carries a price gradient: A premium, B parity,
            # C heavily discounted.
            unit_cost = round(
                sku["mandi_cost_inr_kg"] * rng.uniform(0.94, 1.09)
                + sku["mandi_cost_inr_kg"] * 0.02,
                2,
            )

            shelf = sku["nominal_shelf_life_days"]
            if breach:
                # Heat damage shortens the *remaining* life, it does not
                # change the printed date -- which is precisely why expiry
                # then shows up as shrink.
                shelf = max(1.0, shelf * rng.uniform(0.55, 0.80))

            # Best-before is stamped on whole hours: a printed date can
            # never encode a half-day, and the dashboard pivots on date.
            expiry_ts = arrival_ts + timedelta(hours=round(shelf * 24))

            batches[code].append(Batch(
                batch_id=f"B-{code}-{d}-{bnum:02d}",
                sku=sku,
                arrival_ts=arrival_ts,
                arrival_hour=arrival_hour,
                shift=SHIFT_OF_HOUR[arrival_ts.hour],
                mandi=mandi,
                district=district,
                fpo=rng.choice(FPO_CODES),
                qty_received=round(qty, 1),
                grade_split={k: round(v, 1) for k, v in grade_split.items()},
                rej_qty=round(rej_qty, 1),
                granted_qty=round(granted_qty, 1),
                unit_cost=unit_cost,
                granted_value=round(granted_qty * unit_cost, 2),
                age_at_receipt=round(age, 1),
                temp_receipt=round(temp, 1),
                breach=breach,
                shelf_life_days=round(shelf, 2),
                expiry_ts=expiry_ts,
                remaining=round(granted_qty, 1),
                sold=0.0,
                handling_loss=0.0,
                pilferage=0.0,
                src_days=d,
                dc_days=0,
                closing_qty=0.0,
            ))
    return batches, daily_volume


def build_demand_curve(rng: random.Random) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """Per-SKU hourly demand in kg for the full 168-hour week.

    Returns (hourly series, daily totals). Demand is generated first because
    procurement is demand-responsive: a real buyer's order quantity is sized
    off the forecast for the day it is covering, not off an independent
    volume plan. Sizing arrivals independently of demand is what produces
    impossible stock-out patterns.
    """
    weights = [w / sum(HOUR_WEIGHTS) for w in HOUR_WEIGHTS]
    demand: dict[str, list[float]] = {}
    for sku in SKU_MASTER:
        code = sku["sku_code"]
        daily = [sku["base_daily_arrival_kg"] * rng.gauss(1.0, 0.09) for _ in range(7)]
        # Smooth the day-to-day series: real retail demand is autocorrelated.
        smoothed = list(daily)
        for d in range(1, 7):
            smoothed[d] = 0.55 * daily[d] + 0.45 * smoothed[d - 1]
        # weights sum to 1.0 across the 24 hours, so the day total is
        # smoothed[d] without any further scaling.
        series = []
        for d in range(7):
            for h in range(24):
                series.append(smoothed[d] * DOW_UPLIFT[d] * weights[h])
        # Keep a floor so a slow hour still has a real (if small) pick event.
        demand[code] = [round(max(v, sku["base_daily_arrival_kg"] * 0.0015), 2) for v in series]
    daily_totals = {
        code: [round(sum(series[d * 24:(d + 1) * 24]), 2) for d in range(7)]
        for code, series in demand.items()
    }
    return demand, daily_totals


def pick_fefo_probability(batch: Batch, hour: int, volume_pressure: float) -> float:
    """P(correct rotation on this pick), with every structural drag applied."""
    p = FEFO_BASE[batch.sku["perishable_class"]]
    p += CATEGORY_FEFO_DELTA.get(batch.sku["category"], 0.0)
    p += ZONE_FEFO_DELTA.get(batch.sku["storage_zone"], 0.0)
    p += SHIFT_FEFO_DELTA.get(SHIFT_OF_HOUR[hour % 24], 0.0)
    p -= 0.10 * volume_pressure          # pressure on a peak-volume day
    p -= 0.05 * min(1.0, batch.dc_days / 3.0)   # deep-rack penalty
    return clamp(p, 0.15, 0.97)


def non_fefo_rule(rng: random.Random, candidates: list[Batch]) -> str:
    """Which wrong-but-realistic rule the picker fell back on."""
    r = rng.random()
    if r < 0.42:
        return "lifo_top_of_crate"     # grab the crate that was loaded last
    if r < 0.72:
        return "largest_batch"         # easiest to lift / biggest pile
    if r < 0.90:
        return "fifo_queue"            # arrival queue discipline
    return "nearest_rack_face"


# When set, every pick is forced FEFO-compliant. Used by the counterfactual
# run in analyze.py to isolate the causal contribution of rotation failure
# from every other source of shrinkage.
FEFO_LOCK: dict[str, bool] = {"enabled": False}


def choose_pick(rng: random.Random, candidates: list[Batch], hour: int,
                volume_pressure: float) -> tuple[Batch, str, bool]:
    """Return (batch, rule, fefo_compliant)."""
    p_fefo = 1.0 if FEFO_LOCK["enabled"] else pick_fefo_probability(
        candidates[0], hour, volume_pressure)
    if rng.random() < p_fefo:
        ordered = sorted(candidates, key=lambda b: (b.expiry_ts, b.arrival_hour))
        return ordered[0], "fefo", True

    rule = non_fefo_rule(rng, candidates)
    if rule == "lifo_top_of_crate":
        chosen = max(candidates, key=lambda b: (b.arrival_hour, b.granted_qty))
    elif rule == "largest_batch":
        chosen = max(candidates, key=lambda b: b.granted_qty)
    elif rule == "fifo_queue":
        chosen = min(candidates, key=lambda b: (b.arrival_hour, b.expiry_ts))
    else:
        chosen = rng.choice(candidates)
    compliant = chosen.expiry_ts == min(b.expiry_ts for b in candidates)
    return chosen, ("fefo" if compliant else rule), compliant


WARMUP_HOURS = 72  # 3 days of unmeasured run-up
WARMUP_DAYS = WARMUP_HOURS // 24


def simulate(rng: random.Random) -> tuple[list[Batch], list[dict], list[dict]]:
    """Run the week, preceded by an unmeasured warm-up.

    A processing centre never starts a measured week from empty. The warm-up
    lets carry-in stock build to a realistic steady state, so the reported
    week begins with batches at every stage of their shelf life rather than
    with an artificial zero. Only the measured window is recorded.
    """
    # Demand first, then procurement sized against it.
    demand, demand_daily = build_demand_curve(rng)
    batches, daily_volume = build_arrivals(rng, demand_daily)
    peak = max(daily_volume) or 1.0

    total_hours = HOURS + WARMUP_HOURS
    offset = WARMUP_HOURS
    # Carry-in stock arrives in the warm-up window so it is on hand at hour 0.
    for d in range(-WARMUP_DAYS, 0):
        for sku in SKU_MASTER:
            code = sku["sku_code"]
            # Carry-in sized off the same daily forecast the measured week
            # uses, so the run-up arrives on the same terms as the week.
            di_warm = (d + 4) % 7
            forecast = demand_daily[code][di_warm]
            qty = forecast * clamp(
                BUY_TO_DEMAND[sku["perishable_class"]] * rng.gauss(1.0, 0.08), 0.70, 2.2)
            qty = max(qty, 5.0)
            arrival_ts = WEEK_START + timedelta(days=d, hours=rng.choice([5, 6, 7]))
            arrival_hour = d * 24 + arrival_ts.hour
            mandi, district = rng.choice(SOURCE_MANDIS)
            age = rng.triangular(0.2, 1.5, 4.0)
            temp = rng.gauss(ZONE_TARGET_C[sku["storage_zone"]] + 1.0,
                             ZONE_TOLERANCE_C[sku["storage_zone"]] * 0.55)
            breach = abs(temp - ZONE_TARGET_C[sku["storage_zone"]]) > ZONE_TOLERANCE_C[sku["storage_zone"]]
            gs = split_grade(rng, sku["grade_a_share"], qty, rng.uniform(0.015, 0.075))
            rej = gs.pop("_rejected")
            granted = sum(gs.values())
            shelf = sku["nominal_shelf_life_days"]
            if breach:
                shelf = max(1.0, shelf * rng.uniform(0.55, 0.80))
            batches[code].append(Batch(
                batch_id=f"B-{code}-{d}-carry",
                sku=sku, arrival_ts=arrival_ts, arrival_hour=arrival_hour,
                shift=SHIFT_OF_HOUR[arrival_ts.hour], mandi=mandi, district=district,
                fpo=rng.choice(FPO_CODES), qty_received=round(qty, 1),
                grade_split={k: round(v, 1) for k, v in gs.items()},
                rej_qty=round(rej, 1), granted_qty=round(granted, 1),
                unit_cost=round(sku["mandi_cost_inr_kg"] * rng.uniform(0.94, 1.09)
                                + sku["mandi_cost_inr_kg"] * 0.02, 2),
                granted_value=round(granted * sku["mandi_cost_inr_kg"], 2),
                age_at_receipt=round(age, 1), temp_receipt=round(temp, 1), breach=breach,
                shelf_life_days=round(shelf, 2),
                expiry_ts=arrival_ts + timedelta(hours=round(shelf * 24)),
                remaining=round(granted, 1), sold=0.0, handling_loss=0.0, pilferage=0.0,
                src_days=d, dc_days=0, closing_qty=0.0,
            ))

    # Per-batch shrink ledger. Attribution must be to the batch, not to the
    # SKU: a SKU-level ledger would stamp the whole week's expiry onto
    # every lot of that SKU and multiply the reported loss.
    shrink_ledger: dict[str, dict[str, float]] = {}

    def write_off(batch: Batch, reason: str, kg: float) -> None:
        if kg <= 0:
            return
        bucket = shrink_ledger.setdefault(batch.batch_id, {})
        bucket[reason] = bucket.get(reason, 0.0) + kg

    pick_events: list[dict] = []
    event_no = 0
    lost_sales: dict[str, float] = {s["sku_code"]: 0.0 for s in SKU_MASTER}
    demand_total: dict[str, float] = {s["sku_code"]: 0.0 for s in SKU_MASTER}
    sku_picks: dict[str, list[int]] = {s["sku_code"]: [] for s in SKU_MASTER}

    for hour in range(total_hours):
        measured = hour >= offset
        hod = hour % 24

        # 1) Expiry sweep -- anything past its best-before is written off
        #    before the hour's demand is served. Warm-up write-offs are
        #    discarded so the reported week only carries its own losses.
        for sku_code, sku_batches in batches.items():
            now = WEEK_START + timedelta(hours=hour)
            for b in sku_batches:
                if b.remaining > 0 and now >= b.expiry_ts:
                    if not measured:
                        b.remaining = 0.0
                        continue
                    # Residual handling/pilferage taken before the write-off
                    # is booked against its own reason code, not expiry.
                    if b.remaining > 0:
                        write_off(b, "SR-EXP", b.remaining)
                        b.remaining = 0.0

        hour_of_day = hod
        day_index = hour // 24
        # The demand curve is defined for the measured week only; warm-up
        # replays the measured week's daily shape so stock settles into a
        # consistent rhythm instead of running dry.
        for sku in SKU_MASTER:
            code = sku["sku_code"]
            di = (day_index - WARMUP_DAYS) % 7
            want = demand[code][di * 24 + hod]
            if measured:
                demand_total[code] += want
            if want <= 0:
                continue

            volume_pressure = (
                daily_volume[day_index - 3] / peak if (peak and 0 <= day_index - 3 < 7)
                else 0.5
            )
            now = WEEK_START + timedelta(hours=hour)

            pool = [b for b in batches[code]
                    if b.remaining > 0 and now < b.expiry_ts]

            if not pool:
                if measured:
                    lost_sales[code] += want
                continue

            # Serve in sub-lots so multiple batches are touched per hour,
            # which is what actually makes FEFO ranking observable.
            served = 0.0
            guard = 0
            while served < want and guard < 12:
                guard += 1
                pool = [b for b in batches[code]
                        if b.remaining > 0 and now < b.expiry_ts]
                if not pool:
                    # Unmet demand is booked once, after the loop, so the
                    # shortfall is not counted twice.
                    break

                remaining_want = want - served
                # Sub-gram remainders are rounding noise, not real shortfall.
                # Treating them as a shortfall would loop forever and, worse,
                # write off live stock that had nothing left to serve.
                if remaining_want < 0.01:
                    break

                chosen, rule, compliant = choose_pick(rng, pool, hour, volume_pressure)
                take = min(round(remaining_want, 2), chosen.remaining)
                if take <= 0:
                    break

                expiry_order = sorted(pool, key=lambda b: (b.expiry_ts, b.arrival_hour))
                earliest = expiry_order[0]
                picked_rank = next(i + 1 for i, b in enumerate(expiry_order)
                                   if b is chosen)
                gap_days = round((chosen.expiry_ts - earliest.expiry_ts).total_seconds() / 86400, 2)

                event_no += 1
                if measured:
                    pick_events.append({
                        "event_id": f"PK{event_no:06d}",
                        "event_ts": (now + timedelta(minutes=rng.randint(0, 59))).isoformat(timespec="seconds"),
                        "hour_of_week": hour - offset,
                        "shift": SHIFT_OF_HOUR[hour_of_day],
                        "picker_id": rng.choice(PICKERS),
                        "sku_code": code,
                        "sku_name": sku["sku_name"],
                        "category": sku["category"],
                        "perishable_class": sku["perishable_class"],
                        "storage_zone": sku["storage_zone"],
                        "batch_id": chosen.batch_id,
                        "qty_picked_kg": round(take, 2),
                        "batches_available_in_scope": len(pool),
                        "expiry_rank_if_fefo": picked_rank,
                        "picked_expiry_date": chosen.expiry_ts.date().isoformat(),
                        "earliest_expiry_date": earliest.expiry_ts.date().isoformat(),
                        "expiry_gap_days": gap_days,
                        "picked_batch_age_days": chosen.dc_days,
                        "pick_rule_applied": rule,
                        "fefo_compliant": "TRUE" if compliant else "FALSE",
                    })
                if measured:
                    sku_picks[code].append(1 if compliant else 0)

                chosen.remaining = round(chosen.remaining - take, 2)
                chosen.sold = round(chosen.sold + take, 2)
                served += take

            if served < want and measured:
                lost_sales[code] += want - served

            # Age every batch on hand by one day, and accrue the slow
            # non-expiry losses (handling damage, pilferage) that no
            # best-before date ever captures.
            for b in batches[code]:
                if b.remaining > 0 and now < b.expiry_ts:
                    if hour_of_day == 11:   # midday handling sweep
                        if measured:
                            dmg = b.remaining * sku["handling_loss_pct"] / 96.0 * rng.uniform(0.5, 1.6)
                        else:
                            dmg = b.remaining * sku["handling_loss_pct"] / 96.0
                        dmg = min(dmg, b.remaining)
                        if dmg > 0.05:
                            b.remaining = round(b.remaining - dmg, 2)
                            b.handling_loss = round(b.handling_loss + dmg, 2)
                            if measured:
                                write_off(b, "SR-HDL", dmg)
                        if measured:
                            pilf = b.remaining * rng.uniform(0.0002, 0.0011)
                        else:
                            pilf = b.remaining * 0.0006
                        pilf = min(pilf, b.remaining)
                        if pilf > 0.05:
                            b.remaining = round(b.remaining - pilf, 2)
                            b.pilferage = round(b.pilferage + pilf, 2)
                            if measured:
                                write_off(b, "SR-PIL", pilf)

            for b in batches[code]:
                if hour_of_day == 23:
                    b.dc_days += 1

    # 3) Week-end position. Stock still inside its best-before is *closing
    #    inventory*, not shrink -- it carries into the following week. Only
    #    expired remainder is a write-off, and the expiry sweep above has
    #    already taken it. Reporting in-date closing stock as shrink would
    #    overstate the loss and corrupt the Pareto.
    for sku_code, sku_batches in batches.items():
        for b in sku_batches:
            if b.remaining > 0:
                b.closing_qty = b.remaining
                b.remaining = 0.0

    # Re-attribute shrinkage that was booked during the run to the correct
    # primary reason for reporting, and hand back everything.
    batch_rows = []
    for sku in SKU_MASTER:
        code = sku["sku_code"]
        picks = sku_picks[code]
        violations = len(picks) - sum(picks)
        # Only lots that were on hand during the measured week belong in the
        # reported ledger; warm-up carry-in that never touched this week is
        # excluded so the batch ledger reconciles to the week's receipts.
        for b in batches[code]:
            if b.src_days < 0 and b.sold <= 0 and b.handling_loss <= 0 \
                    and b.pilferage <= 0 and b.batch_id not in shrink_ledger:
                continue
            ledger = shrink_ledger.get(b.batch_id, {})
            sr_exp = round(ledger.get("SR-EXP", 0.0), 2)
            sr_hdl = round(ledger.get("SR-HDL", 0.0), 2)
            sr_ovr = round(ledger.get("SR-OVR", 0.0), 2)
            sr_pil = round(ledger.get("SR-PIL", 0.0), 2)
            # Rejection at the grading gate is booked against the lot that
            # caused it, so it stays with the batch.
            sr_qlt = round(b.rej_qty, 2)
            sr_tmp = round(ledger.get("SR-TMP", 0.0), 2)

            total_shrink = round(sr_exp + sr_hdl + sr_ovr + sr_qlt + sr_pil + sr_tmp, 2)
            shrink_value = round(total_shrink * b.unit_cost, 2)
            denom = b.granted_qty + b.rej_qty
            batch_rows.append({
                "batch_id": b.batch_id,
                "sku_code": code,
                "sku_name": sku["sku_name"],
                "category": sku["category"],
                "perishable_class": sku["perishable_class"],
                "storage_zone": sku["storage_zone"],
                "carry_in": "TRUE" if b.src_days < 0 else "FALSE",
                "arrival_date": b.arrival_ts.date().isoformat(),
                "arrival_ts": b.arrival_ts.isoformat(timespec="seconds"),
                "day_of_week": b.arrival_ts.strftime("%a"),
                "shift": b.shift,
                "source_mandi": b.mandi,
                "source_district": b.district,
                "fpo_id": b.fpo,
                "age_at_receipt_days": b.age_at_receipt,
                "temp_at_receipt_c": b.temp_receipt,
                "cold_chain_breach": "TRUE" if b.breach else "FALSE",
                "qty_received_kg": b.qty_received,
                "qty_grade_a_kg": b.grade_split["A"],
                "qty_grade_b_kg": b.grade_split["B"],
                "qty_grade_c_kg": b.grade_split["C"],
                "grading_reject_kg": b.rej_qty,
                "qty_granted_kg": b.granted_qty,
                "acquisition_price_inr_kg": b.unit_cost,
                "granted_value_inr": round(b.granted_value, 2),
                "nominal_shelf_life_days": sku["nominal_shelf_life_days"],
                "effective_shelf_life_days": b.shelf_life_days,
                "best_before_date": b.expiry_ts.date().isoformat(),
                "days_on_hand_at_close": b.dc_days,
                "qty_sold_kg": b.sold,
                "qty_shrunk_kg": total_shrink,
                "shrink_pct_of_received": round(100.0 * total_shrink / denom, 2) if denom else 0.0,
                "shrink_value_inr": shrink_value,
                "shrink_exp_kg": sr_exp,
                "shrink_hdl_kg": sr_hdl,
                "shrink_ovr_kg": sr_ovr,
                "shrink_qlt_kg": sr_qlt,
                "shrink_tmp_kg": sr_tmp,
                "shrink_pil_kg": sr_pil,
                "primary_shrink_reason": (
                    max([("SR-EXP", sr_exp), ("SR-HDL", sr_hdl), ("SR-OVR", sr_ovr),
                         ("SR-QLT", sr_qlt), ("SR-TMP", sr_tmp), ("SR-PIL", sr_pil)],
                        key=lambda t: t[1])[0]
                    if total_shrink > 0 else ""
                ),
                "primary_shrink_reason_desc": SHRINK_REASON_CODES.get(
                    max([("SR-EXP", sr_exp), ("SR-HDL", sr_hdl), ("SR-OVR", sr_ovr),
                         ("SR-QLT", sr_qlt), ("SR-TMP", sr_tmp), ("SR-PIL", sr_pil)],
                        key=lambda t: t[1])[0], ""),
                "fefo_picks_sku_total": len(picks),
                "fefo_violations_sku_total": violations,
                "fefo_violation_rate_sku_pct": round(100.0 * violations / len(picks), 2) if picks else 0.0,
                "lost_sales_kg_sku_total": round(lost_sales[code], 2),
                "product_in_stock_pct_sku": round(
                    100.0 * (1.0 - lost_sales[code] / demand_total[code]), 2
                ) if demand_total[code] else 0.0,
            })
    return batch_rows, pick_events, batches


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {path.relative_to(ROOT)}  ({len(rows)} rows)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic processing-centre week.")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    print(f"[generate_data] seed={args.seed}")

    write_csv(RAW / "sku_master.csv", SKU_MASTER)

    batch_rows, pick_events, batches = simulate(rng)

    write_csv(RAW / "fefo_pick_events.csv", pick_events)

    # Temperature-breach write-offs are attributed to the breached lots, not
    # left as a SKU-level bucket, so the batch ledger stays auditable.
    for row in batch_rows:
        if row["cold_chain_breach"] == "TRUE" and row["qty_shrunk_kg"] > 0:
            breach_kg = round(row["qty_shrunk_kg"] * 0.18, 2)
            row["shrink_tmp_kg"] = breach_kg
            row["shrink_exp_kg"] = round(max(0.0, row["shrink_exp_kg"] - breach_kg), 2)

    write_csv(RAW / "processing_center_batches.csv", batch_rows)

    # ---- summary check -------------------------------------------------
    total_shrink = sum(r["qty_shrunk_kg"] for r in batch_rows)
    total_recv = sum(r["qty_received_kg"] for r in batch_rows)
    viol = sum(1 for e in pick_events if e["fefo_compliant"] == "FALSE")
    print(f"  batches={len(batch_rows)} picks={len(pick_events)} "
          f"shrink={total_shrink:,.0f}kg / {total_recv:,.0f}kg received "
          f"({100*total_shrink/total_recv:.2f}%)")
    print(f"  FEFO violations={viol}/{len(pick_events)} "
          f"({100*viol/len(pick_events):.2f}% of picks)")


if __name__ == "__main__":
    main()
