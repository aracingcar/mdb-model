import sys
from importlib import import_module
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "3_routing"))

from aridity import basin_zones
from config import SYSTEM_ID
from routing import runoff_depth_to_m3s

# Each method is a module in this folder exposing LABEL and simulate(precip, pet, zone) -> runoff depth (mm/day), zone being
# the basin's climate zone ('highland' or 'plains', 1_masking/aridity.py).
# To offer another method, add its module name to AVAILABLE_MODELS; the display dropdown follows.
AVAILABLE_MODELS = ["gr4j", "gr4j_2"]
RAINFALL_RUNOFF_MODEL = "gr4j"


def model_specs():
    """{module name: {label, algorithm, params}} for every selectable method, so the browser can re-run them. params is
    one list, or {system: list} for a method calibrated per river system, or {system: {zone: list}} per system and zone."""
    as_list = lambda p: {z: list(v) for z, v in p.items()} if isinstance(p, dict) else list(p)
    out = {}
    for name in AVAILABLE_MODELS:
        m = import_module(name)
        params = {s: as_list(p) for s, p in m.PARAMS.items()} if isinstance(m.PARAMS, dict) else list(m.PARAMS)
        out[name] = {"label": m.LABEL, "algorithm": m.ALGORITHM, "params": params}
    return out


def run_rainfall_runoff(basin_forcing, basins, model=RAINFALL_RUNOFF_MODEL):
    """Selected rainfall-runoff method on every basin: returns runoff as discharge (m3/s), one column per basin id (and LOWLAND)."""
    if model not in AVAILABLE_MODELS:
        raise ValueError(f"Unknown rainfall-runoff model {model!r}; available: {AVAILABLE_MODELS}")
    simulate = import_module(model).simulate
    zones = basin_zones(SYSTEM_ID, basins)
    runoff = {}
    for _, unit in basins.iterrows():
        name = unit["subcatchment"]
        depth = simulate(basin_forcing[f"{name}_P"].to_numpy(), basin_forcing[f"{name}_PET"].to_numpy(), zones[name])
        runoff[name] = runoff_depth_to_m3s(pd.Series(depth, index=basin_forcing.index), unit["area_km2"])
    return pd.DataFrame(runoff)
