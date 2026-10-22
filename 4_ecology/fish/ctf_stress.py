"""Fish cease-to-flow stress (Murray cod, golden perch): refuge / survival model.

Cease-to-flow (CTF) is flow <= CTF_THRESHOLD ML/d (EWR 'CF1' in the Murrumbidgee LTWP, MDBA py-ewr
parameter sheet: threshold 0-1 ML/d, target frequency 0%). During CTF the river breaks into pools; fish
survive in refuge pools with a constant daily mortality hazard, so survival over a spell is exp(-h * days).
HAZARD_PER_DAY is an assumed value, not a published one.
"""
import numpy as np
import pandas as pd

from flow import spells, water_year

CTF_THRESHOLD = 1.0
HAZARD_PER_DAY = 0.02


def ctf_stress(flow):
    """Per water year: CTF days, spell count, longest spell, and fraction of the population surviving."""
    ctf = flow <= CTF_THRESHOLD
    rows = {}
    for wy, mask in ctf.groupby(water_year(ctf.index)):
        lengths = [n for _, n in spells(mask)]
        days = int(mask.sum())
        rows[wy] = {
            "ctf_days": days,
            "ctf_spells": len(lengths),
            "longest_ctf_days": max(lengths, default=0),
            "survival": float(np.exp(-HAZARD_PER_DAY * days)),
            "CF1_met": days == 0,
        }
    return pd.DataFrame.from_dict(rows, orient="index").rename_axis("water_year")
