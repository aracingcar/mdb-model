"""Muskingum routing down the basin network, with a lowland loss calibrated to the recorded outlet flow."""
import numpy as np
import pandas as pd

from config import SYSTEM, SYSTEM_ID
from river_flows import river_flows
from routing import route_network

LABEL = "Muskingum"
ALGORITHM = "muskingum"  # the browser engine (docs/engine.js) implements this algorithm and takes PARAMS from here
M3S_TO_ML_DAY = 86.4

# x: Muskingum weighting. velocity_km_day: wave speed (~1 m/s), sets each reach's K from its length ~ 1.5 x sqrt(area).
# delivery: share of a unit's runoff that reaches the river ("LOWLAND" applies to every lowland unit); the semi-arid
# western plains deliver little. target_scale: share of the river system's target outlet flow the loss is calibrated to.
# The system itself sets loss_regions, target_outlet_m3s and the flow splits (config.SYSTEMS, shipped to the browser
# with the system's engine data): one fractional loss at the outlet of every basin in the last loss_regions main-stem
# reaches stands in for what GR4J on its own cannot see (regulation, irrigation, seepage).
PARAMS = {"x": 0.2, "velocity_km_day": 86.4, "delivery": {"LOWLAND": 0.05}, "target_scale": 1.0}
CALIBRATION = SYSTEM["routing"]
SPLITS = SYSTEM["splits"]


def delivery(p, n):
    return p["delivery"].get("LOWLAND" if n.startswith("LOWLAND") else n, 1.0)


def _network(runoff, basins, p):
    downstream = dict(zip(basins["subcatchment"], basins["next_id"]))
    lossy = dict(zip(basins["subcatchment"], basins["from_outlet"].between(1, p["loss_regions"] or 0)))
    # K = channel length / velocity, kept inside the 1-day Muskingum stability range. The length is the river's run through
    # the basin from HydroBASINS' distance-to-sink; where it has none (lowlands, a system outlet) 1.5 x sqrt(area) stands in.
    length = basins["length_km"].where(basins["length_km"] > 0, 1.5 * np.sqrt(basins["area_km2"]))
    k = {n: float(np.clip(l / p["velocity_km_day"], 0.7, 2.4)) for n, l in zip(basins["subcatchment"], length)}
    lateral = {n: runoff[n] * delivery(p, n) for n in runoff.columns}
    return downstream, lossy, k, lateral


def _route(runoff, basins, loss, p):
    downstream, lossy, k, lateral = _network(runoff, basins, p)
    reaches = {n: {"k_days": k[n], "x": p["x"], "loss": loss if lossy[n] else 0.0} for n in lateral}
    return route_network(lateral, downstream, reaches, SPLITS)


def _calibrate_loss(runoff, basins, outlet, p):
    """Bisect the per-reach loss fraction so mean outlet flow hits the target (more loss -> less flow); 0 if the system has no target."""
    if p["target_outlet_m3s"] is None:
        return 0.0
    if not basins["from_outlet"].between(1, p["loss_regions"] or 0).any():
        raise ValueError(f"{SYSTEM_ID}: loss_regions = {p['loss_regions']} selects no basin, so the outlet flow could not be calibrated")
    target = p["target_outlet_m3s"] * p["target_scale"]
    lo, hi = 0.0, 0.99
    for _ in range(25):
        mid = (lo + hi) / 2
        if _route(runoff, basins, mid, p)[outlet].mean() > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def route(runoff, basins, subcatchments, p=PARAMS):
    """Route basin runoff (m3/s) down the watershed network; return (unit_flow, reach_flow, basin_flow, rivers, river_flow).

    unit_flow is {SDL unit: daily flow at the unit's outlet basin (ML/d)}, reach_flow the flow at each reach's outlet
    basin (a lowland's is its unit's outlet), basin_flow the routed flow leaving every basin, and rivers / river_flow
    the segments of every mapped river and creek with their daily flow (see river_flows.py).
    """
    p = {**p, **CALIBRATION}
    outlet = basins.loc[basins["next_id"] == "", "subcatchment"].iloc[0]
    loss = _calibrate_loss(runoff, basins, outlet, p)
    print(f"3_routing: {SYSTEM_ID}, {len(basins)} basins routed, " + (f"calibrated per-reach loss over the last {p['loss_regions']} reaches = {loss:.2f}"
                                                                      if p["target_outlet_m3s"] is not None else "no outlet calibration"))
    basin_flow = _route(runoff, basins, loss, p) * M3S_TO_ML_DAY
    reach_flow = pd.DataFrame({r.subcatchment: basin_flow[r.outlet_basin] for r in subcatchments.itertuples()})
    unit_flow = {r.sdl_unit: basin_flow[r.unit_outlet].rename("flow_ML_d") for r in subcatchments.itertuples()}
    lateral = runoff * M3S_TO_ML_DAY * pd.Series({n: delivery(p, n) for n in runoff.columns})
    rivers, river_flow = river_flows(basins, lateral, basin_flow)
    return unit_flow, reach_flow, basin_flow, rivers, river_flow
