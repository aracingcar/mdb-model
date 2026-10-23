"""Simple daily routing methods for rainfall-runoff model output.

The functions accept discharge as a one-dimensional time series. They do not
infer river topology or parameters; supply reach-specific values from data or
calibration. Daily inflows are assumed to be mean discharge for each day.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def muskingum(inflow, k_days: float, x: float, dt_days: float = 1.0):
    """Route a daily flow series through one Muskingum reach.

    Parameters ``k_days`` and ``dt_days`` use days. ``x`` is dimensionless.
    Initial outflow defaults to the first inflow (steady initial condition).
    The usual stability conditions ``2*K*X <= dt <= 2*K*(1-X)`` are required.
    Returns the same type/index as a pandas Series input, otherwise ndarray.
    """
    _validate_flow(inflow)
    if not np.isfinite(k_days) or k_days <= 0:
        raise ValueError("k_days must be positive and finite")
    if not np.isfinite(x) or not 0 <= x <= 0.5:
        raise ValueError("x must be between 0 and 0.5")
    if not np.isfinite(dt_days) or dt_days <= 0:
        raise ValueError("dt_days must be positive and finite")
    if not 2 * k_days * x <= dt_days <= 2 * k_days * (1 - x):
        raise ValueError("Muskingum stability requires 2*K*X <= dt <= 2*K*(1-X)")

    qin = np.asarray(inflow, dtype=float)
    qout = np.empty_like(qin)
    if not qin.size:
        return _restore_type(inflow, qout)
    c0 = (dt_days - 2 * k_days * x) / (2 * k_days * (1 - x) + dt_days)
    c1 = (dt_days + 2 * k_days * x) / (2 * k_days * (1 - x) + dt_days)
    c2 = (2 * k_days * (1 - x) - dt_days) / (2 * k_days * (1 - x) + dt_days)
    qout[0] = qin[0]
    for i in range(1, qin.size):
        qout[i] = c0 * qin[i] + c1 * qin[i - 1] + c2 * qout[i - 1]
    return _restore_type(inflow, qout)


def route_reaches(inflow, reaches):
    """Route sequentially through reach dictionaries in upstream-to-downstream order.

    Each reach must contain ``k_days`` and ``x``. An optional ``name`` is
    retained in the returned DataFrame. For example::

        route_reaches(q, [{"name": "reach_1", "k_days": 2.0, "x": 0.2}])

    The output has the routed series after each reach. The first reach output
    is the returned series when ``reaches`` is empty.
    """
    _validate_flow(inflow)
    current = inflow.copy() if isinstance(inflow, pd.Series) else np.asarray(inflow, dtype=float).copy()
    outputs = {}
    for i, reach in enumerate(reaches, start=1):
        if "k_days" not in reach or "x" not in reach:
            raise ValueError("Each reach requires k_days and x")
        current = muskingum(current, reach["k_days"], reach["x"])
        outputs[reach.get("name", f"reach_{i}")] = np.asarray(current, dtype=float)
    if isinstance(inflow, pd.Series):
        return pd.DataFrame(outputs, index=inflow.index) if outputs else current.rename("Q")
    return pd.DataFrame(outputs) if outputs else current


def route_lateral_units(lateral_inflows, reaches):
    """Accumulate and route sequential lateral subcatchment inflows.

    ``lateral_inflows`` maps unit IDs to daily discharge Series (m3/s), ordered
    upstream to downstream. ``reaches`` has one matching dictionary per unit,
    with ``name``, ``k_days`` and ``x``. At each reach the local lateral flow is
    added to the upstream routed flow, then routed through that reach. An optional
    ``loss`` (fraction 0-1) removes that share of the routed flow at the reach
    outlet, standing in for evaporation, seepage and diversions.
    """
    if list(lateral_inflows) != [reach.get("name") for reach in reaches]:
        raise ValueError("lateral inflow keys must match reach names in upstream-to-downstream order")
    if not lateral_inflows:
        return pd.DataFrame()
    current = None
    outputs = {}
    for name, reach in zip(lateral_inflows, reaches):
        lateral = lateral_inflows[name]
        _validate_flow(lateral)
        if current is None:
            current = lateral.copy() if isinstance(lateral, pd.Series) else np.asarray(lateral, dtype=float).copy()
        else:
            if isinstance(lateral, pd.Series) and isinstance(current, pd.Series):
                if not lateral.index.equals(current.index):
                    raise ValueError("all lateral inflows must have matching indexes")
                current = current + lateral
            else:
                if len(lateral) != len(current):
                    raise ValueError("all lateral inflows must have matching lengths")
                current = np.asarray(current) + np.asarray(lateral)
        current = muskingum(current, reach["k_days"], reach["x"]) * (1 - reach.get("loss", 0.0))
        outputs[name] = np.asarray(current, dtype=float)
    index = next((v.index for v in lateral_inflows.values() if isinstance(v, pd.Series)), None)
    return pd.DataFrame(outputs, index=index)


def route_network(lateral_inflows, downstream, reaches):
    """Route lateral inflows down a branching river network of Muskingum reaches.

    ``lateral_inflows`` maps node IDs to daily discharge Series (m3/s) on a shared index. ``downstream`` maps each
    node to the node it drains into ('' for the outlet). ``reaches`` maps each node to ``{"k_days", "x"}`` and an
    optional ``loss`` fraction removed at that reach's outlet. A node's inflow is its own lateral flow plus the
    routed outflow of every node draining into it. Returns a DataFrame of each node's routed outflow.
    """
    from scipy.signal import lfilter, lfilter_zi

    index = next(iter(lateral_inflows.values())).index
    children = {n: [] for n in lateral_inflows}
    for node, down in downstream.items():
        if down:
            children[down].append(node)
    out = {}

    def outflow(node):
        if node in out:
            return out[node]
        inflow = np.asarray(lateral_inflows[node], dtype=float).copy()
        for child in children[node]:
            inflow += outflow(child)
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


def unit_hydrograph(inflow, ordinates):
    """Route with a discrete unit hydrograph whose ordinates sum to one."""
    _validate_flow(inflow)
    uh = np.asarray(ordinates, dtype=float)
    if uh.ndim != 1 or not uh.size or not np.all(np.isfinite(uh)) or np.any(uh < 0):
        raise ValueError("ordinates must be a non-empty, finite, non-negative 1D sequence")
    total = uh.sum()
    if not np.isclose(total, 1.0, atol=1e-8):
        raise ValueError("unit hydrograph ordinates must sum to 1")
    q = np.convolve(np.asarray(inflow, dtype=float), uh, mode="full")[:len(inflow)]
    return _restore_type(inflow, q)


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
