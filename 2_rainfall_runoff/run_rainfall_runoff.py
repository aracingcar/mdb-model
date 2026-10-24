import sys
from importlib import import_module
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "3_routing"))

from routing import runoff_depth_to_m3s

# Each method is a module in this folder exposing LABEL and simulate(precip, pet) -> runoff depth (mm/day).
# To offer another method, add its module name to AVAILABLE_MODELS; the display dropdown follows.
AVAILABLE_MODELS = ["gr4j", "gr4j_2"]
RAINFALL_RUNOFF_MODEL = "gr4j"


def model_specs():
    """{module name: {label, algorithm, params}} for every selectable method, so the browser can re-run them."""
    out = {}
    for name in AVAILABLE_MODELS:
        m = import_module(name)
        out[name] = {"label": m.LABEL, "algorithm": m.ALGORITHM, "params": list(m.PARAMS)}
    return out


def run_rainfall_runoff(basin_forcing, basins, model=RAINFALL_RUNOFF_MODEL):
    """Selected rainfall-runoff method on every basin: returns runoff as discharge (m3/s), one column per basin id (and LOWLAND)."""
    if model not in AVAILABLE_MODELS:
        raise ValueError(f"Unknown rainfall-runoff model {model!r}; available: {AVAILABLE_MODELS}")
    simulate = import_module(model).simulate
    runoff = {}
    for _, unit in basins.iterrows():
        name = unit["subcatchment"]
        depth = simulate(basin_forcing[f"{name}_P"].to_numpy(), basin_forcing[f"{name}_PET"].to_numpy())
        runoff[name] = runoff_depth_to_m3s(pd.Series(depth, index=basin_forcing.index), unit["area_km2"])
    return pd.DataFrame(runoff)
