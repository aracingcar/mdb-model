"""Basin climate zones from observed aridity: the parameter zones of rainfall-runoff (2a_rainfall_runoff/gr4j.py) and routing
(3a_routing/muskingum.py).

A basin's aridity index is its mean BoM AWO daily rainfall over its mean AWO PET, 2012-2026 (1_masking/download_awo_climate.py),
so a basin keeps its zone under every climate run. Basins at or above PLAINS_BELOW_AI are highland (the tablelands and the
alps the headwater gauges are in), the rest plains. The threshold is where one parameter set fitted to the drier gauges
best improves on each system's single regional set (calibrate_gr4j.py --zones, data/calibration/gr4j_systems.json).
"""
import pandas as pd

from config import INPUT

PLAINS_BELOW_AI = 0.7
CLIMATE = INPUT / "climate"


def basin_zones(system, basins):
    """{basin: 'highland' or 'plains'} for ``basins`` (subcatchment, next_id). A basin with no observed climate (a few small
    basins the AWO grid misses) takes the zone of the first basin below it that has one, else plains."""
    climate = pd.read_csv(CLIMATE / f"{system}_basin_P_PET_2012_2026.csv", index_col="date")
    ai = {}
    for b in basins["subcatchment"]:
        p, e = climate.get(f"{b}_P"), climate.get(f"{b}_PET")
        if p is not None and e is not None and p.notna().any() and e.sum() > 0:
            ai[b] = p.sum() / e.sum()
    down = dict(zip(basins["subcatchment"], basins["next_id"]))
    zones = {}
    for b in basins["subcatchment"]:
        i, seen = b, set()
        while i and i not in ai and i not in seen:
            seen.add(i)
            i = down.get(i, "")
        zones[b] = "highland" if ai.get(i, 0.0) >= PLAINS_BELOW_AI else "plains"
    return zones
