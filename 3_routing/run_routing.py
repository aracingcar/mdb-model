import numpy as np
import pandas as pd

from river_flows import river_flows
from routing import route_network

X = 0.2
M3S_TO_ML_DAY = 86.4
VELOCITY_KM_DAY = 86.4  # ~1 m/s

# Lowland corrections for what GR4J on its own cannot see (regulation, irrigation, seepage).
# Delivery: share of a unit's runoff that reaches the river. The semi-arid western plains deliver little.
DELIVERY = {"LOWLAND": 0.05}
# Loss: one fractional loss applied at the outlet of every basin reach in the regions from LOSS_FROM downstream,
# calibrated so mean outlet flow matches TARGET_OUTLET_M3S (recorded mean at Balranald, ~27 m3/s; Wikipedia, "Murrumbidgee River").
LOSS_FROM = 9
TARGET_OUTLET_M3S = 27.0


def _network(runoff, basins):
    downstream = dict(zip(basins["subcatchment"], basins["next_id"]))
    region = dict(zip(basins["subcatchment"], basins["region"].str[2:].astype(int)))
    # reach length ~ 1.5 x sqrt(area); K = length / velocity, kept inside the 1-day Muskingum stability range
    k = {n: float(np.clip(1.5 * np.sqrt(a) / VELOCITY_KM_DAY, 0.7, 2.4)) for n, a in zip(basins["subcatchment"], basins["area_km2"])}
    lateral = {n: runoff[n] * DELIVERY.get(n, 1.0) for n in runoff.columns}
    return downstream, region, k, lateral


def _route(runoff, basins, loss):
    downstream, region, k, lateral = _network(runoff, basins)
    reaches = {n: {"k_days": k[n], "x": X, "loss": loss if (n != "LOWLAND" and region[n] >= LOSS_FROM) else 0.0} for n in lateral}
    return route_network(lateral, downstream, reaches)


def _calibrate_loss(runoff, basins, outlet):
    """Bisect the per-reach loss fraction so mean outlet flow hits the target (more loss -> less flow)."""
    lo, hi = 0.0, 0.99
    for _ in range(25):
        mid = (lo + hi) / 2
        if _route(runoff, basins, mid)[outlet].mean() > TARGET_OUTLET_M3S:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def run_routing(runoff, basins, subcatchments):
    """Route basin runoff (m3/s) down the watershed network; return (flow, reach_flow, basin_flow, rivers, river_flow).

    flow is the daily series at the valley outlet (ML/d), reach_flow the flow at each subcatchment reach's outlet
    basin, basin_flow the routed flow leaving every basin, and rivers / river_flow the segments of every mapped
    river and creek with their daily flow (see river_flows.py).
    """
    outlet = basins.loc[basins["next_id"] == "", "subcatchment"].iloc[0]
    loss = _calibrate_loss(runoff, basins, outlet)
    print(f"3_routing: {len(basins)} basins routed, calibrated per-reach loss from region SC{LOSS_FROM:02d} = {loss:.2f}")
    basin_flow = _route(runoff, basins, loss) * M3S_TO_ML_DAY
    reach_flow = pd.DataFrame({r.subcatchment: basin_flow[r.outlet_basin if r.outlet_basin else outlet] for r in subcatchments.itertuples()})
    lateral = runoff * M3S_TO_ML_DAY * pd.Series({n: DELIVERY.get(n, 1.0) for n in runoff.columns})
    rivers, river_flow = river_flows(basins, lateral, basin_flow)
    return basin_flow[outlet].rename("flow_ML_d"), reach_flow, basin_flow, rivers, river_flow
