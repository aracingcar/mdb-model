import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "3_routing"))

from gr4j import gr4j
from routing import runoff_depth_to_m3s


def run_rainfall_runoff(subcatchment_forcing, subcatchments):
    """GR4J per subcatchment: returns runoff as discharge (m3/s), one column per unit, upstream to downstream."""
    runoff = {}
    for _, unit in subcatchments.sort_values("route_order").iterrows():
        name = unit["subcatchment"]
        depth = gr4j(subcatchment_forcing[f"{name}_P"].to_numpy(), subcatchment_forcing[f"{name}_PET"].to_numpy())
        runoff[name] = runoff_depth_to_m3s(pd.Series(depth, index=subcatchment_forcing.index), unit["area_km2"])
    return pd.DataFrame(runoff)
