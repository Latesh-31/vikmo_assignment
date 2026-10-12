import csv
import math
from collections import defaultdict
from pathlib import Path


def train_and_generate_forecast():
    base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / "data"
    ml_dir = base_dir / "ml"

    lead_times_path = data_dir / "lead_times.csv"
    sales_history_path = data_dir / "sales_history.csv"
    promo_calendar_path = data_dir / "promo_calendar.csv"
    forecast_output_path = ml_dir / "forecast.csv"

    # 1. Load forecast SKUs
    forecast_skus = []
    with open(lead_times_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            forecast_skus.append(row["sku"].strip())

    # 2. Load planned promo calendar for the 4 forecast weeks
    planned_promos = defaultdict(dict)
    with open(promo_calendar_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = row["sku"].strip()
            w = row["week_start"].strip()
            planned_promos[sku][w] = int(row["promo_flag"].strip())

    # 3. Load sales history
    sales_by_sku = defaultdict(list)
    with open(sales_history_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = row["sku"].strip()
            w = row["week_start"].strip()
            units = float(row["units_sold"].strip())
            promo = int(row["promo_flag"].strip())
            sales_by_sku[sku].append({"week_start": w, "units": units, "promo": promo})

    # Sort each SKU's history chronologically
    for sku in sales_by_sku:
        sales_by_sku[sku].sort(key=lambda x: x["week_start"])

    forecast_weeks = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]
    output_rows = []

    for sku in forecast_skus:
        history = sales_by_sku.get(sku, [])
        if not history:
            # Fallback if no history
            for w in forecast_weeks:
                output_rows.append({"sku": sku, "week_start": w, "forecast_units": 10.0})
            continue

        # Compute baseline from recent history (e.g. weighted average of last 12 weeks)
        recent_12 = history[-12:]
        units_12 = [h["units"] for h in recent_12]
        
        # Trend / baseline
        non_promo_recent = [h["units"] for h in recent_12 if h["promo"] == 0]
        baseline = sum(non_promo_recent) / len(non_promo_recent) if non_promo_recent else (sum(units_12) / len(units_12))

        # Promo lift factor
        all_promo_units = [h["units"] for h in history if h["promo"] == 1]
        all_non_promo_units = [h["units"] for h in history if h["promo"] == 0]
        avg_promo = sum(all_promo_units) / len(all_promo_units) if all_promo_units else 0.0
        avg_non_promo = sum(all_non_promo_units) / len(all_non_promo_units) if all_non_promo_units else baseline

        promo_multiplier = (avg_promo / avg_non_promo) if (avg_non_promo > 0 and avg_promo > 0) else 1.35
        # Cap multiplier reasonably
        promo_multiplier = max(1.1, min(promo_multiplier, 3.0))

        # Seasonal pre-festive lift factor for late Sept / Oct (approx +10% to +20%)
        seasonal_factors = {
            "2026-09-28": 1.05,
            "2026-10-05": 1.10,
            "2026-10-12": 1.15,
            "2026-10-19": 1.20,
        }

        for w in forecast_weeks:
            is_promo = planned_promos.get(sku, {}).get(w, 0)
            pred = baseline * seasonal_factors.get(w, 1.0)
            if is_promo == 1:
                pred *= promo_multiplier

            pred = max(0.0, round(pred, 1))
            output_rows.append({"sku": sku, "week_start": w, "forecast_units": pred})

    # Write ml/forecast.csv
    with open(forecast_output_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sku", "week_start", "forecast_units"])
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Generated {len(output_rows)} forecast rows in {forecast_output_path}")


if __name__ == "__main__":
    train_and_generate_forecast()
