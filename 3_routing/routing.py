"""Simple daily routing methods for rainfall-runoff model output.

The functions accept discharge as a one-dimensional time series. They do not
infer river topology or parameters; supply reach-specific values from data or
calibration. Daily inflows are assumed to be mean discharge for each day.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def route_network(lateral_inflows, downstream, reaches, splits=None):
    """Route lateral inflows down a river network of Muskingum reaches that can join and split.

    ``lateral_inflows`` maps node IDs to daily discharge Series (m3/s) on a shared index. ``downstream`` maps each
    node to the node it drains into ('' for the outlet). ``reaches`` maps each node to ``{"k_days", "x"}`` and an
    optional ``loss`` fraction removed at that reach's outlet. ``splits`` maps a node to ``{to: fraction}``: that
    share of its routed outflow goes to node ``to`` (or leaves the network if ``to`` is ''), and the rest goes
    downstream. A node's inflow is its own lateral flow plus its share of the routed outflow of every node feeding
    it. Returns a DataFrame of each node's routed outflow (before any split).
    """
    from scipy.signal import lfilter, lfilter_zi

    splits = splits or {}
    for node, targets in splits.items():
        if node not in lateral_inflows or any(to and to not in lateral_inflows for to in targets):
            raise ValueError(f"split {node} -> {list(targets)} names a node that is not in the network")
        if any(f < 0 for f in targets.values()) or sum(targets.values()) > 1:
            raise ValueError(f"split fractions from {node} must be non-negative and sum to at most 1")
    index = next(iter(lateral_inflows.values())).index
    feeds = {n: [] for n in lateral_inflows}  # node -> [(upstream node, share of its outflow)]
    for node, down in downstream.items():
        if down:
            feeds[down].append((node, 1 - sum(splits.get(node, {}).values())))
    for node, targets in splits.items():
        for to, share in targets.items():
            if to:
                feeds[to].append((node, share))
    out, active = {}, set()

    def outflow(node):
        if node in out:
            return out[node]
        if node in active:
            raise ValueError(f"flow splits make a loop through {node}")
        active.add(node)
        inflow = np.asarray(lateral_inflows[node], dtype=float).copy()
        for up, share in feeds[node]:
            inflow += outflow(up) * share
        _validate_flow(inflow)
        k, x, dt = reaches[node]["k_days"], reaches[node]["x"], 1.0
        if not 2 * k * x <= dt <= 2 * k * (1 - x):
            raise ValueError("Muskingum stability requires 2*K*X <= dt <= 2*K*(1-X)")
        d = 2 * k * (1 - x) + dt
        b, a = [(dt - 2 * k * x) / d, (dt + 2 * k * x) / d], [1.0, -(2 * k * (1 - x) - dt) / d]
        routed = lfilter(b, a, inflow, zi=lfilter_zi(b, a) * inflow[0])[0]
        out[node] = routed * (1 - reaches[node].get("loss", 0.0))
        return out[node]

    import sys
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 4 * len(lateral_inflows) + 100))
    for node in lateral_inflows:
        outflow(node)
    return pd.DataFrame(out, index=index)


def runoff_depth_to_m3s(runoff_mm_day, area_km2: float):
    """Convert catchment runoff depth (mm/day) to mean discharge (m3/s)."""
    _validate_flow(runoff_mm_day)
    if not np.isfinite(area_km2) or area_km2 <= 0:
        raise ValueError("area_km2 must be positive and finite")
    q = np.asarray(runoff_mm_day, dtype=float) * area_km2 * 1000 / 86400
    return _restore_type(runoff_mm_day, q)


def _validate_flow(values):
    q = np.asarray(values, dtype=float)
    if q.ndim != 1 or not np.all(np.isfinite(q)):
        raise ValueError("flow must be a finite, one-dimensional series")
    if np.any(q < 0):
        raise ValueError("flow must be non-negative")


def _restore_type(original, array):
    if isinstance(original, pd.Series):
        return pd.Series(array, index=original.index, name=original.name)
    return array
