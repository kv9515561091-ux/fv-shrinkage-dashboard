"""SKU reference master for the simulated processing centre.

Prices are anchored to publicly reported All-India figures (Department of
Consumer Affairs / Agmarknet) for early October 2026, converted from the
reported retail Rs/kg and mandi-quintal basis.

    potato   retail Rs 22.81/kg   mandi Rs 1,200/qtl  -> Rs 12.00/kg
    tomato   retail Rs 42.74/kg   mandi Rs 3,095/qtl  -> Rs 30.95/kg
    onion    retail Rs 53.53/kg   mandi Rs 4,500/qtl  -> Rs 45.00/kg

Leafy greens and herbs have no published national benchmark, so their
acquisition cost is expressed as a realistic fraction of the retail price
paid by a premium organised-retail basket.
"""

from __future__ import annotations

# sku_code, sku_name, category, perishable_class, storage_zone,
# nominal_shelf_life_days, min_shelf_life_days,
# mandi_cost_inr_kg, retail_benchmark_inr_kg, base_daily_arrival_kg,
# grade_a_share, handling_loss_pct
SKU_MASTER: list[dict] = [
    # ------------------------------------------------------------------
    # Leafy greens -- the hard case. 1-2 day shelf life, near-zero
    # tolerance for temperature excursion, highest shrink exposure.
    # ------------------------------------------------------------------
    dict(sku_code="LG001", sku_name="Coriander (Dhania) Bunch", category="Leafy Greens",
         perishable_class="Highly Perishable", storage_zone="Chilled 0-4C",
         nominal_shelf_life_days=2, min_shelf_life_days=1,
         mandi_cost_inr_kg=20.00, retail_benchmark_inr_kg=44.31,
         base_daily_arrival_kg=120, grade_a_share=0.55, handling_loss_pct=0.110),
    dict(sku_code="LG002", sku_name="Spinach (Palak) Loose", category="Leafy Greens",
         perishable_class="Highly Perishable", storage_zone="Chilled 0-4C",
         nominal_shelf_life_days=2, min_shelf_life_days=1,
         mandi_cost_inr_kg=18.00, retail_benchmark_inr_kg=36.00,
         base_daily_arrival_kg=95, grade_a_share=0.50, handling_loss_pct=0.120),
    dict(sku_code="LG003", sku_name="Methi Leaves", category="Leafy Greens",
         perishable_class="Highly Perishable", storage_zone="Chilled 0-4C",
         nominal_shelf_life_days=2, min_shelf_life_days=1,
         mandi_cost_inr_kg=16.00, retail_benchmark_inr_kg=32.00,
         base_daily_arrival_kg=70, grade_a_share=0.45, handling_loss_pct=0.135),
    dict(sku_code="LG004", sku_name="Lettuce (Batting) Whole", category="Leafy Greens",
         perishable_class="Highly Perishable", storage_zone="Chilled 0-4C",
         nominal_shelf_life_days=3, min_shelf_life_days=2,
         mandi_cost_inr_kg=32.00, retail_benchmark_inr_kg=68.00,
         base_daily_arrival_kg=45, grade_a_share=0.60, handling_loss_pct=0.090),
    dict(sku_code="LG005", sku_name="Coriander Root (Stalk attached)", category="Leafy Greens",
         perishable_class="Highly Perishable", storage_zone="Chilled 0-4C",
         nominal_shelf_life_days=3, min_shelf_life_days=2,
         mandi_cost_inr_kg=17.00, retail_benchmark_inr_kg=38.00,
         base_daily_arrival_kg=60, grade_a_share=0.52, handling_loss_pct=0.105),

    # ------------------------------------------------------------------
    # Bulb & stem -- onions/ginger/garlic. Long shelf life, high
    # value density, absorbs the low-perishability end of the mix.
    # ------------------------------------------------------------------
    dict(sku_code="BS001", sku_name="Onion (Nashik Red)", category="Bulb & Stem",
         perishable_class="Hardy", storage_zone="Ambient Ventilated",
         nominal_shelf_life_days=30, min_shelf_life_days=21,
         mandi_cost_inr_kg=45.00, retail_benchmark_inr_kg=53.53,
         base_daily_arrival_kg=900, grade_a_share=0.70, handling_loss_pct=0.022),
    dict(sku_code="BS002", sku_name="Potato (Agra)", category="Bulb & Stem",
         perishable_class="Hardy", storage_zone="Ambient Ventilated",
         nominal_shelf_life_days=35, min_shelf_life_days=25,
         mandi_cost_inr_kg=12.00, retail_benchmark_inr_kg=22.81,
         base_daily_arrival_kg=1100, grade_a_share=0.72, handling_loss_pct=0.018),
    dict(sku_code="BS003", sku_name="Ginger (Kerala)", category="Bulb & Stem",
         perishable_class="Hardy", storage_zone="Ambient Ventilated",
         nominal_shelf_life_days=21, min_shelf_life_days=14,
         mandi_cost_inr_kg=24.00, retail_benchmark_inr_kg=34.88,
         base_daily_arrival_kg=140, grade_a_share=0.66, handling_loss_pct=0.038),
    dict(sku_code="BS004", sku_name="Garlic (Girikonda)", category="Bulb & Stem",
         perishable_class="Hardy", storage_zone="Ambient Ventilated",
         nominal_shelf_life_days=45, min_shelf_life_days=30,
         mandi_cost_inr_kg=26.00, retail_benchmark_inr_kg=45.43,
         base_daily_arrival_kg=150, grade_a_share=0.68, handling_loss_pct=0.030),

    # ------------------------------------------------------------------
    # Root vegetables -- carrot, radish, beet. Moderate perishable.
    # ------------------------------------------------------------------
    dict(sku_code="RV001", sku_name="Carrot Ooty (Loose)", category="Root Vegetables",
         perishable_class="Perishable", storage_zone="Chilled 2-6C",
         nominal_shelf_life_days=18, min_shelf_life_days=12,
         mandi_cost_inr_kg=26.00, retail_benchmark_inr_kg=58.00,
         base_daily_arrival_kg=180, grade_a_share=0.62, handling_loss_pct=0.052),
    dict(sku_code="RV002", sku_name="Radish (Mullangi)", category="Root Vegetables",
         perishable_class="Perishable", storage_zone="Chilled 2-6C",
         nominal_shelf_life_days=14, min_shelf_life_days=9,
         mandi_cost_inr_kg=14.00, retail_benchmark_inr_kg=32.00,
         base_daily_arrival_kg=130, grade_a_share=0.55, handling_loss_pct=0.060),
    dict(sku_code="RV003", sku_name="Beetroot (Chukandar)", category="Root Vegetables",
         perishable_class="Perishable", storage_zone="Chilled 2-6C",
         nominal_shelf_life_days=16, min_shelf_life_days=10,
         mandi_cost_inr_kg=22.00, retail_benchmark_inr_kg=48.00,
         base_daily_arrival_kg=85, grade_a_share=0.58, handling_loss_pct=0.055),
    dict(sku_code="RV004", sku_name="Sweet Potato (Shakarkandi)", category="Root Vegetables",
         perishable_class="Hardy", storage_zone="Ambient Ventilated",
         nominal_shelf_life_days=28, min_shelf_life_days=20,
         mandi_cost_inr_kg=25.00, retail_benchmark_inr_kg=52.00,
         base_daily_arrival_kg=110, grade_a_share=0.60, handling_loss_pct=0.035),

    # ------------------------------------------------------------------
    # Brinjal & cucurbit -- the mid-perishability band, where
    # condensation and bruising drive the loss pattern.
    # ------------------------------------------------------------------
    dict(sku_code="BC001", sku_name="Brinjal Purple Long", category="Brinjal & Cucurbit",
         perishable_class="Perishable", storage_zone="Ambient Ventilated",
         nominal_shelf_life_days=8, min_shelf_life_days=5,
         mandi_cost_inr_kg=24.00, retail_benchmark_inr_kg=43.26,
         base_daily_arrival_kg=200, grade_a_share=0.58, handling_loss_pct=0.072),
    dict(sku_code="BC002", sku_name="Tomato Hybrid (Trapezium)", category="Brinjal & Cucurbit",
         perishable_class="Perishable", storage_zone="Chilled 8-10C",
         nominal_shelf_life_days=9, min_shelf_life_days=6,
         mandi_cost_inr_kg=30.95, retail_benchmark_inr_kg=42.74,
         base_daily_arrival_kg=420, grade_a_share=0.64, handling_loss_pct=0.065),
    dict(sku_code="BC003", sku_name="Bottle Gourd (Lauki)", category="Brinjal & Cucurbit",
         perishable_class="Perishable", storage_zone="Chilled 2-6C",
         nominal_shelf_life_days=7, min_shelf_life_days=4,
         mandi_cost_inr_kg=19.00, retail_benchmark_inr_kg=38.00,
         base_daily_arrival_kg=160, grade_a_share=0.56, handling_loss_pct=0.078),
    dict(sku_code="BC004", sku_name="Bitter Gourd (Karela)", category="Brinjal & Cucurbit",
         perishable_class="Perishable", storage_zone="Ambient Ventilated",
         nominal_shelf_life_days=7, min_shelf_life_days=4,
         mandi_cost_inr_kg=28.00, retail_benchmark_inr_kg=52.00,
         base_daily_arrival_kg=95, grade_a_share=0.50, handling_loss_pct=0.082),
    dict(sku_code="BC005", sku_name="Capsicum Green (Shimla Mirch)", category="Brinjal & Cucurbit",
         perishable_class="Perishable", storage_zone="Chilled 8-10C",
         nominal_shelf_life_days=10, min_shelf_life_days=7,
         mandi_cost_inr_kg=38.00, retail_benchmark_inr_kg=76.00,
         base_daily_arrival_kg=140, grade_a_share=0.66, handling_loss_pct=0.058),

    # ------------------------------------------------------------------
    # Fruit -- bananas ripen after harvest, so the loss mechanism
    # is maturation pressure rather than simple decay.
    # ------------------------------------------------------------------
    dict(sku_code="FR001", sku_name="Banana Robusta (Bunch)", category="Fruit",
         perishable_class="Perishable", storage_zone="Ambient Ventilated",
         nominal_shelf_life_days=6, min_shelf_life_days=4,
         mandi_cost_inr_kg=22.00, retail_benchmark_inr_kg=49.30,
         base_daily_arrival_kg=320, grade_a_share=0.61, handling_loss_pct=0.070),
    dict(sku_code="FR002", sku_name="Apple Shimla (Fuji)", category="Fruit",
         perishable_class="Hardy", storage_zone="Chilled 0-4C",
         nominal_shelf_life_days=40, min_shelf_life_days=28,
         mandi_cost_inr_kg=118.00, retail_benchmark_inr_kg=185.00,
         base_daily_arrival_kg=120, grade_a_share=0.74, handling_loss_pct=0.028),
    dict(sku_code="FR003", sku_name="Pomegranate Bhagwa", category="Fruit",
         perishable_class="Hardy", storage_zone="Chilled 2-6C",
         nominal_shelf_life_days=25, min_shelf_life_days=18,
         mandi_cost_inr_kg=95.00, retail_benchmark_inr_kg=160.00,
         base_daily_arrival_kg=90, grade_a_share=0.69, handling_loss_pct=0.034),
    dict(sku_code="FR004", sku_name="Pineapple (Queen)", category="Fruit",
         perishable_class="Perishable", storage_zone="Ambient Ventilated",
         nominal_shelf_life_days=12, min_shelf_life_days=8,
         mandi_cost_inr_kg=42.00, retail_benchmark_inr_kg=85.00,
         base_daily_arrival_kg=75, grade_a_share=0.63, handling_loss_pct=0.055),
]

# Reason codes used in the shrinkage ledger. The mix is deliberately
# weighted the way a real dump log looks: expiry dominates, with pilferage
# and over-buying showing up as material but secondary lines.
SHRINK_REASON_CODES: dict[str, str] = {
    "SR-EXP": "Shelf-life expiry (best-before crossed)",
    "SR-HDL": "Handling damage / bruising",
    "SR-OVR": "Over-purchase, no demand cover",
    "SR-QLT": "Quality rejection at grading gate",
    "SR-TMP": "Cold-chain temperature breach",
    "SR-PIL": "Pilferage / shrink theft",
}

SHIFT_WINDOWS = ["Shift A (05:00-13:00)", "Shift B (13:00-21:00)", "Shift C (21:00-05:00)"]
