"""GR4J daily rainfall-runoff model (Perrin, Michel & Andreassian 2003, J. Hydrol. 279)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1_masking"))

from config import DISPLAY_SYSTEMS, SYSTEM_ID

# Median parameter set from Perrin et al. (2003): x1 production store (mm), x2 exchange (mm/d),
# x3 routing store (mm), x4 unit hydrograph time base (days).
DEFAULT_PARAMS = (350.0, 0.0, 90.0, 1.7)
# Per river system, the regional set fitted by calibrate_gr4j.py to unregulated headwater gauges on observed climate,
# 2013-2019 (data/calibration/gr4j_systems.json, with each set's validation KGE). x3 sits near its 1 mm lower bound and the
# Murray's x1 at its 2500 mm upper bound. The Lower Darling has no HRS gauge, so it keeps the median set.
CALIBRATED = {
    "murrumbidgee": (362.6467, -3.7956, 10.6427, 1.2552),  # from 410734 Queanbeyan River at Tinderry
    "lachlan": (291.7566, -2.2397, 1.2058, 1.4496),  # from 412029 Boorowa River at Prossers Crossing
    "murray": (2499.9984, -2.4784, 4.9333, 1.288),  # from 401210 Snowy Creek below Granite Flat
    "goulburn_broken": (1401.8726, -1.4118, 1.8823, 2.0),  # from 405228 Hughes Creek at Tarcombe Road
}
# The plains (basins with an observed aridity index under 0.7, 1_masking/aridity.py) of every system take one set instead:
# the gauge set with the best median validation KGE over the 16 HRS gauges under that aridity (calibrate_gr4j.py --zones).
# Scored leave-one-out, those gauges' median validation KGE rises from 0.13 with their system's set to 0.29 (13 of 16 better);
# the highland gauges keep their system's set. The plains basins are drier than every gauge (the Riverine Plain, Mallee and
# Lower Darling reach an aridity index of 0.13, the driest gauge 0.37), so the set is extrapolated there.
PLAINS = (355.7715, -5.0484, 7.2274, 1.4473)  # from 410705 Molonglo River at Burbong (aridity index 0.68)
LABEL = "GR4J"
ALGORITHM = "gr4j"  # the browser engine (docs/engine.js) implements this algorithm and takes PARAMS from here
# per system and zone: the engine picks its own
PARAMS = {s: {"highland": CALIBRATED.get(s, DEFAULT_PARAMS), "plains": PLAINS} for s in DISPLAY_SYSTEMS}


def _unit_hydrographs(x4):
    n1, n2 = int(np.ceil(x4)), int(np.ceil(2 * x4))

    def sh1(t):
        return 0.0 if t <= 0 else (t / x4) ** 2.5 if t < x4 else 1.0

    def sh2(t):
        if t <= 0:
            return 0.0
        if t < x4:
            return 0.5 * (t / x4) ** 2.5
        return 1 - 0.5 * (2 - t / x4) ** 2.5 if t < 2 * x4 else 1.0

    uh1 = np.array([sh1(i) - sh1(i - 1) for i in range(1, n1 + 1)])
    uh2 = np.array([sh2(i) - sh2(i - 1) for i in range(1, n2 + 1)])
    return uh1, uh2


def gr4j(precip, pet, params=DEFAULT_PARAMS):
    """Runoff depth (mm/day) from daily precipitation and PET (mm/day) arrays."""
    x1, x2, x3, x4 = params
    uh1, uh2 = _unit_hydrographs(x4)
    q9_buf, q1_buf = np.zeros(len(uh1)), np.zeros(len(uh2))
    s, r = 0.3 * x1, 0.5 * x3
    out = np.empty(len(precip))
    for t, (p, e) in enumerate(zip(precip, pet)):
        pn, en = max(p - e, 0.0), max(e - p, 0.0)
        ps = es = 0.0
        if pn > 0:
            th = np.tanh(pn / x1)
            ps = x1 * (1 - (s / x1) ** 2) * th / (1 + (s / x1) * th)
        if en > 0:
            th = np.tanh(en / x1)
            es = s * (2 - s / x1) * th / (1 + (1 - s / x1) * th)
        s += ps - es
        perc = s * (1 - (1 + (s / (4 / 9 * x1)) ** 4) ** -0.25)
        s -= perc
        pr = pn - ps + perc

        q9_buf[:-1], q9_buf[-1] = q9_buf[1:], 0.0
        q1_buf[:-1], q1_buf[-1] = q1_buf[1:], 0.0
        q9_buf += 0.9 * pr * uh1
        q1_buf += 0.1 * pr * uh2

        f = x2 * (r / x3) ** 3.5
        r = max(r + q9_buf[0] + f, 0.0)
        qr = r * (1 - (1 + (r / x3) ** 4) ** -0.25)
        r -= qr
        out[t] = qr + max(q1_buf[0] + f, 0.0)
    return out


def simulate(precip, pet, zone="highland"):
    """Rainfall-runoff model interface: runoff depth (mm/day) with this model's parameters for the basin's ``zone``."""
    return gr4j(precip, pet, PARAMS[SYSTEM_ID][zone])
