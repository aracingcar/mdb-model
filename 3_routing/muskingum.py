"""Muskingum network routing with explicit channel fluxes and residual miscellaneous loss."""
import numpy as np
import pandas as pd
import warnings

from channel_fluxes import channel_inputs

from config import LINKS, RUN_KEY, SYSTEM, SYSTEM_ID
from nodes import basin_outlets, build_nodes, connected
from results_db import load_link_flow
from river_flows import river_flows
from routing import route_network

LABEL = "Muskingum"
ALGORITHM = "muskingum"  # the browser engine (docs/engine.js) implements this algorithm and takes PARAMS from here
M3S_TO_ML_DAY = 86.4

# x: Muskingum weighting. velocity_km_day: wave speed (~1 m/s), sets each reach's K from its length ~ 1.5 x sqrt(area).
# delivery: share of a unit's runoff that reaches the river ("LOWLAND" applies to every lowland unit); the semi-arid
# western plains deliver little. target_scale: share of the river system's target outlet flow the loss is calibrated to.
# Provisional, uncalibrated channel assumptions: fixed 10 m surface width, open-water
# evaporation = 1 x available PET, seepage 0.02 ML/day/km. No measured geometry or
# groundwater heads are implied. Misc loss uses Q * (1-exp(-coefficient*length)).
# The default coefficient is 0.001/km (~9.5% over 100 km). At selected basin outlet
# nodes only, it is replaced by a coefficient fitted to the system's mean-flow target.
# All other physical reaches retain the default coefficient; synthetic LOWLAND has
# no channel footprint/fluxes. See README for limitations and future calibration.
PARAMS = {"x": 0.2, "velocity_km_day": 86.4, "delivery": {"LOWLAND": 0.05}, "target_scale": 1.0,
          "channel_width_m": 10.0, "pet_factor": 1.0, "seepage_ML_day_km": 0.02,
          "misc_loss_per_km": 0.001}
CALIBRATION = SYSTEM["routing"]
SPLITS = SYSTEM["splits"]


def delivery(p, n):
    return p["delivery"].get("LOWLAND" if n.startswith("LOWLAND") else n, 1.0)


def _network(runoff, nodes, p):
    """Node inputs: each node takes its area share of its basin's delivered runoff (m3/s) at the point it joins the river.
    K = channel length / wave speed (the length from HydroBASINS' distance-to-sink, else 1.5 x sqrt(area)), at most 2.4 days."""
    downstream = dict(zip(nodes["id"], nodes["next"]))
    lossy = dict(zip(nodes["id"], nodes["loss_rank"].between(1, p["loss_regions"] or 0)))
    length = nodes["length_km"].fillna(1.5 * np.sqrt(nodes["area_km2"]))
    k = {n: float(min(l / p["velocity_km_day"], 2.4)) for n, l in zip(nodes["id"], length)}
    lateral = {n.id: runoff[n.basin] * delivery(p, n.basin) * n.share for n in nodes.itertuples()}
    return downstream, lossy, k, lateral


def link_flow(link, index):
    """The stored outflow (ML/d) of the other river system's basin that ``link`` takes water from, on the dates ``index``."""
    flow = load_link_flow(link["from"], RUN_KEY, link["basin"])
    if flow is None:
        raise RuntimeError(f"{SYSTEM_ID}: no stored flow from {link['from']} {link['basin']} for {'/'.join(RUN_KEY)}; run {link['from']} first")
    flow = flow.reindex(index)
    if flow.isna().any():
        raise RuntimeError(f"{SYSTEM_ID}: the stored flow from {link['from']} {link['basin']} does not cover the run's dates")
    return flow


def _inflows(nodes, index):
    """{node: daily inflow (m3/s)} from the other river systems feeding this one (config.LINKS), each entering the outlet
    node of its ``into`` basin. A link with spill_above_ML_d only passes the flow above that."""
    outlet = basin_outlets(nodes)
    inflow = {}
    for link in LINKS:
        if link["to"] != SYSTEM_ID:
            continue
        flow = np.maximum(link_flow(link, index).to_numpy() - link.get("spill_above_ML_d", 0.0), 0.0) / M3S_TO_ML_DAY
        node = outlet[link["into"]]
        inflow[node] = inflow.get(node, 0.0) + pd.Series(flow, index=index)
    return inflow


def _storage_caps(nodes):
    """{node: max release (m3/s)} for the nodes holding a storage."""
    caps = {s: v["max_release_ML_d"] / M3S_TO_ML_DAY for s, v in SYSTEM.get("storages", {}).items()}
    return {n.id: caps[n.storage] for n in nodes.itertuples() if n.storage}


def _splits(nodes):
    """The system's basin splits as node splits: from a basin's outlet node to the target basin's outlet node ('' leaves the river)."""
    outlet = basin_outlets(nodes)
    return {outlet[b]: {outlet[to] if to else "": f for to, f in targets.items()} for b, targets in SPLITS.items()}


def _route(runoff, nodes, loss, p, channel, record_budget=False):
    downstream, lossy, k, _ = _network(runoff, nodes, p)
    lateral, fluxes = channel
    caps = _storage_caps(nodes)
    reaches = {n: {"k_days": k[n], "x": p["x"],
                   "loss": -np.expm1(-(loss if lossy[n] else p["misc_loss_per_km"]) * fluxes[n]['length_km']),
                   "max_release": caps.get(n), **fluxes[n]} for n in lateral}
    return route_network(lateral, downstream, reaches, _splits(nodes), record_budget=record_budget)


def _calibrate_loss(runoff, nodes, basins, outlet, p, channel):
    """Fit residual miscellaneous loss per km, after explicit channel exchanges."""
    if p["target_outlet_m3s"] is None:
        return p['misc_loss_per_km']
    if not basins["from_outlet"].between(1, p["loss_regions"] or 0).any():
        raise ValueError(f"{SYSTEM_ID}: loss_regions selects no basin")
    target = p["target_outlet_m3s"] * p["target_scale"]
    mean = lambda loss: _route(runoff, nodes, loss, p, channel)[outlet].mean()
    lo, hi = 0.0, 1.0
    if mean(lo) <= target:
        warnings.warn(f'{SYSTEM_ID}: outlet target is at/above flow with zero fitted misc loss; using zero. Losses cannot add water.')
        return lo
    if mean(hi) > target:
        warnings.warn(f'{SYSTEM_ID}: outlet target unreachable within misc loss bounds [0, 1]/km; using upper bound.')
        return hi
    for _ in range(25):
        mid = (lo + hi) / 2
        if mean(mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def route(runoff, basins, subcatchments, p=PARAMS, *, basin_forcing=None):
    """Route basin runoff (m3/s) down the node network; return (unit_flow, reach_flow, basin_flow, rivers, river_flow).

    unit_flow is {SDL unit: daily flow at the unit's outlet basin (ML/d)}, reach_flow the flow at each reach's outlet
    basin (a lowland's is its unit's outlet), basin_flow the routed flow leaving every basin (its outlet node), and rivers /
    river_flow the segments of every mapped river and creek with their daily flow (see river_flows.py). basin_flow.attrs
    ["storages"] holds each storage's daily inflow-routed release and stored volume (ML/d, ML).
    """
    p = {**p, **CALIBRATION}
    nodes = connected(build_nodes(basins, SYSTEM_ID), basins)
    outlet_node = basin_outlets(nodes)
    outlet = outlet_node[basins.loc[basins["next_id"] == "", "subcatchment"].iloc[0]]
    local, fluxes = channel_inputs(runoff, nodes, basins, basin_forcing, p, delivery)
    inflow = _inflows(nodes, runoff.index)
    channel = ({n: q + inflow[n] if n in inflow else q for n, q in local.items()}, fluxes)  # local runoff plus what other systems send
    loss = _calibrate_loss(runoff, nodes, basins, outlet, p, channel)
    print(f"3_routing: {SYSTEM_ID}, {len(basins)} basins as {len(nodes)} nodes routed, " + (f"calibrated misc loss /km over the last {p['loss_regions']} reaches = {loss:.6f}"
                                                                                           if p["target_outlet_m3s"] is not None else "no outlet calibration"))
    routed = _route(runoff, nodes, loss, p, channel, record_budget="totals")
    none = pd.Series(0.0, index=routed.index)  # a basin whose every node ends off the river system
    basin_flow = pd.DataFrame({b: routed[outlet_node[b]] if b in outlet_node else none for b in basins["subcatchment"]}) * M3S_TO_ML_DAY
    basin_flow.attrs['channel_budget_ML'] = pd.DataFrame(routed.attrs['channel_budget']).T.rename(
        columns=lambda c: c.replace('_m3s', '_ML')) * M3S_TO_ML_DAY
    basin_flow.attrs['misc_loss_per_km'] = loss
    totals = basin_flow.attrs['channel_budget_ML'][['rain_ML', 'evap_ML', 'seepage_ML', 'misc_ML']].sum()
    print('3_routing: channel totals ML: ' + ', '.join(f'{k}={v:,.0f}' for k, v in totals.items()))
    names = dict(zip(nodes["id"], nodes["storage"]))
    basin_flow.attrs["storages"] = {names[n]: (df * M3S_TO_ML_DAY).rename(columns={"release_m3s": "release_ML_d", "stored_m3s_days": "stored_ML"})
                                    for n, df in routed.attrs["storages"].items()}
    for name, df in basin_flow.attrs["storages"].items():
        cap = SYSTEM["storages"][name]["max_release_ML_d"]
        print(f"3_routing:   storage {name}: releases up to {cap:,.0f} ML/d, holds {df['stored_ML'].iloc[-1]:,.0f} ML at the end, at the cap {(df['release_ML_d'] >= cap - 1e-6).mean():.0%} of days")
    reach_flow = pd.DataFrame({r.subcatchment: basin_flow[r.outlet_basin] for r in subcatchments.itertuples()})
    unit_flow = {r.sdl_unit: basin_flow[r.unit_outlet].rename("flow_ML_d") for r in subcatchments.itertuples()}
    lateral = pd.DataFrame({b: sum(local[n.id] for n in nodes.itertuples() if n.basin == b)
                            for b in runoff.columns}) * M3S_TO_ML_DAY
    rivers, river_flow = river_flows(basins, lateral, basin_flow)
    return unit_flow, reach_flow, basin_flow, rivers, river_flow
