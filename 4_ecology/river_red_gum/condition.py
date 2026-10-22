"""River red gum condition: floods neither too infrequent nor too frequent.

A flood year is one with >= FLOOD_DAYS days at or above FLOOD_FLOW. Defaults are the overbank EWR
'OB-S2' for the Murrumbidgee in the MDBA py-ewr parameter sheet (gauge 410040: >= 15,000 ML/d for
>= 11 days, Aug-Feb, max inter-event 4 years). Too long without a flood stresses trees; too many
consecutive flood years (waterlogging) also does. The condition step sizes and the 3-year waterlogging
limit are assumptions.
"""
import pandas as pd

from flow import water_year

FLOOD_FLOW = 15000
FLOOD_DAYS = 11
FLOOD_MONTHS = (8, 9, 10, 11, 12, 1, 2)
MAX_DRY_YEARS = 4
MAX_WET_YEARS = 3
GAIN, LOSS = 0.25, 0.15


def red_gum_condition(flow, start_condition=0.7):
    """Per water year: flooded?, years since last flood, and condition index (0 poor - 1 good)."""
    in_season = flow.index.month.isin(FLOOD_MONTHS)
    high = (flow >= FLOOD_FLOW) & in_season
    flood_days = high.groupby(water_year(flow.index)).sum()

    condition, dry, wet = start_condition, 0, 0
    rows = {}
    for wy, days in flood_days.items():
        flooded = days >= FLOOD_DAYS
        dry, wet = (0, wet + 1) if flooded else (dry + 1, 0)
        if flooded and wet <= MAX_WET_YEARS:
            condition += GAIN
        elif wet > MAX_WET_YEARS or dry > MAX_DRY_YEARS:
            condition -= LOSS
        condition = min(1.0, max(0.0, condition))
        rows[wy] = {"flood_days": int(days), "flooded": bool(flooded), "years_since_flood": dry, "condition": condition}
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("water_year")
