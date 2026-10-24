"""River red gum condition: floods neither too infrequent nor too frequent.

A flood year is one with >= flood_days days at or above flood_flow, set per SDL unit in config.SDL_UNITS. The
Murrumbidgee's are the overbank EWR 'OB-S2' in the MDBA py-ewr parameter sheet (gauge 410040: >= 15,000 ML/d for
>= 11 days, Aug-Feb, max inter-event 4 years). Too long without a flood stresses trees; too many
consecutive flood years (waterlogging) also does. The condition step sizes and the 3-year waterlogging
limit are assumptions.
"""
import pandas as pd

from flow import water_year

FLOOD_MONTHS = (8, 9, 10, 11, 12, 1, 2)
MAX_DRY_YEARS = 4
MAX_WET_YEARS = 3
GAIN, LOSS = 0.25, 0.15


def red_gum_condition(flow, flood_flow, flood_days, start_condition=0.7):
    """Per water year: flooded?, years since last flood, and condition index (0 poor - 1 good)."""
    in_season = flow.index.month.isin(FLOOD_MONTHS)
    high = (flow >= flood_flow) & in_season
    per_year = high.groupby(water_year(flow.index)).sum()

    condition, dry, wet = start_condition, 0, 0
    rows = {}
    for wy, days in per_year.items():
        flooded = days >= flood_days
        dry, wet = (0, wet + 1) if flooded else (dry + 1, 0)
        if flooded and wet <= MAX_WET_YEARS:
            condition += GAIN
        elif wet > MAX_WET_YEARS or dry > MAX_DRY_YEARS:
            condition -= LOSS
        condition = min(1.0, max(0.0, condition))
        rows[wy] = {"flood_days": int(days), "flooded": bool(flooded), "years_since_flood": dry, "condition": condition}
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("water_year")
