"""Muskingum routing down the basin network, with a lowland loss calibrated to the recorded outlet flow."""
import numpy as np
import pandas as pd

from river_flows import river_flows
from routing import route_network

LABEL = "Muskingum"
M3S_TO_ML_DAY = 86.4

# x: Muskingum weighting. velocity_km_day: wave speed (~1 m/s), sets each reach's K from its length ~ 1.5 x sqrt(area).
# delivery: share of a unit's runoff that reaches the river; the semi-arid western plains deliver little.
# loss_from: one fractional loss applied at the outlet of every basin reach in the regions from this one downstream,
# calibrated so mean outlet flow matches target_outlet_m3s (recorded mean at Balranald, ~27 m3/s; Wikipedia, "Murrumbidgee River").
# Lowland corrections stand in for what GR4J on its own cannot see (regulation, irrigation, seepage).
PARAMS = {"x": 0.2, "velocity_km_day": 86.4, "delivery": {"LOWLAND": 0.05}, "loss_from": 9, "target_outlet_m3s": 27.0}


def _network(runoff, basins, p):
    downstream = dict(zip(basins["subcatchment"], basins["next_id"]))
    region = dict(zip(basins["subcatchment"], basins["region"].str[2:].astype(int)))
    # reach length ~ 1.5 x sqrt(area); K = length / velocity, kept inside the 1-day Muskingum stability range
    k = {n: float(np.clip(1.5 * np.sqrt(a) / p["velocity_km_day"], 0.7, 2.4)) for n, a in zip(basins["subcatchment"], basins["area_km2"])}
    lateral = {n: runoff[n] * p["delivery"].get(n, 1.0) for n in runoff.columns}
    return downstream, region, k, lateral


def _route(runoff, basins, loss, p):
    downstream, region, k, lateral = _network(runoff, basins, p)
    reaches = {n: {"k_days": k[n], "x": p["x"], "loss": loss if (n != "LOWLAND" and region[n] >= p["loss_from"]) else 0.0} for n in lateral}
    return route_network(lateral, downstream, reaches)


def _calibrate_loss(runoff, basins, outlet, p):
    """Bisect the per-reach loss fraction so mean outlet flow hits the target (more loss -> less flow)."""
    lo, hi = 0.0, 0.99
    for _ in range(25):
        mid = (lo + hi) / 2
        if _route(runoff, basins, mid, p)[outlet].mean() > p["target_outlet_m3s"]:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def route(runoff, basins, subcatchments, p=PARAMS):
    """Route basin runoff (m3/s) down the watershed network; return (flow, reach_flow, basin_flow, rivers, river_flow).

    flow is the daily series at the valley outlet (ML/d), reach_flow the flow at each subcatchment reach's outlet
    basin, basin_flow the routed flow leaving every basin, and rivers / river_flow the segments of every mapped
    river and creek with their daily flow (see river_flows.py).
    """
    outlet = basins.loc[basins["next_id"] == "", "subcatchment"].iloc[0]
    loss = _calibrate_loss(runoff, basins, outlet, p)
    print(f"3_routing: {len(basins)} basins routed, calibrated per-reach loss from region SC{p['loss_from']:02d} = {loss:.2f}")
    basin_flow = _route(runoff, basins, loss, p) * M3S_TO_ML_DAY
    reach_flow = pd.DataFrame({r.subcatchment: basin_flow[r.outlet_basin if r.outlet_basin else outlet] for r in subcatchments.itertuples()})
    lateral = runoff * M3S_TO_ML_DAY * pd.Series({n: p["delivery"].get(n, 1.0) for n in runoff.columns})
    rivers, river_flow = river_flows(basins, lateral, basin_flow)
    return basin_flow[outlet].rename("flow_ML_d"), reach_flow, basin_flow, rivers, river_flow
