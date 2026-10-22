"""Spawning trigger for colonial waterbird breeding.

Trigger: a wetland-inundating high flow in the breeding window. Thresholds follow the large-fresh
wetland EWRs for the Lowbidgee in the MDBA py-ewr parameter sheet (gauge 410021, 'W-LF4_S':
>= 15,500 ML/d for >= 9 days, 90% target frequency). The breeding window and the sustain rule
(birds need ~90 days of continued wetland water to fledge, with flow staying above half the trigger)
are assumptions based on typical colonial waterbird breeding cycles, not taken from the sheet.
"""
import pandas as pd

from flow import spells, water_year

TRIGGER_FLOW = 15500
TRIGGER_DAYS = 9
WINDOW_MONTHS = (8, 9, 10, 11, 12)
SUSTAIN_FLOW = TRIGGER_FLOW / 2
SUSTAIN_DAYS = 90


def breeding_trigger(flow):
    """Per water year: whether breeding was triggered, the trigger date, and whether it was sustained."""
    high = flow >= TRIGGER_FLOW
    rows = {}
    for wy, wy_flow in flow.groupby(water_year(flow.index)):
        trigger = None
        for start, n in spells(high.loc[wy_flow.index]):
            if n >= TRIGGER_DAYS and start.month in WINDOW_MONTHS:
                trigger = start
                break
        sustained = False
        if trigger is not None:
            after = flow.loc[trigger: trigger + pd.Timedelta(days=SUSTAIN_DAYS - 1)]
            sustained = len(after) == SUSTAIN_DAYS and bool((after >= SUSTAIN_FLOW).all())
        rows[wy] = {"triggered": trigger is not None, "trigger_date": trigger, "sustained": sustained}
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("water_year")
