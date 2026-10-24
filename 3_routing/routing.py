"""Simple daily routing methods for rainfall-runoff model output.

The functions accept discharge as a one-dimensional time series. They do not
infer river topology or parameters; supply reach-specific values from data or
calibration. Daily inflows are assumed to be mean discharge for each day.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


MIN_K_DAYS = 0.7  # below this a daily Muskingum reach is unstable (and adds lag); shorter reaches are a fractional-day lag instead


def store_and_release(inflow, max_release):
    """Pass ``inflow`` (m3/s) through a storage that releases at most ``max_release`` (m3/s) a day.

    The storage starts empty, releases the most it can up to the cap (all of the day's inflow plus what it holds, if that
    is less), and keeps the rest. It has no capacity limit and never spills, so inflow above the cap only builds the stored
    volume. Returns (release, stored), both in m3/s (stored is m3/s-days: x 86.4 for ML).
    """
    release, stored = np.empty_like(inflow), np.empty_like(inflow)
    held = 0.0
    for t, q in enumerate(inflow):
        available = held + q
        release[t] = min(max_release, available)
        held = available - release[t]
        stored[t] = held
    return release, stored


def route_network(lateral_inflows, downstream, reaches, splits=None, record_budget=True):
    """Route lateral inflows down a river network of reaches that can join, split and pass through storages.

    ``lateral_inflows`` maps node IDs to daily discharge Series (m3/s) on a shared index. ``downstream`` maps each
    node to the node it drains into ('' for the outlet). ``reaches`` maps each node to ``{"k_days", "x"}``, an
    optional ``rain_m3s``, ``evap_m3s`` and ``seepage_m3s`` daily exchanges,
    a ``loss`` miscellaneous fraction removed after those exchanges, before storage and splits and an optional ``max_release`` (m3/s): the node then
    holds a storage at its outlet (see ``store_and_release``). A reach with K under MIN_K_DAYS is a fractional-day lag
    (Muskingum cannot run it at a daily step); the rest are Muskingum. ``splits`` maps a node to ``{to: fraction}``: that
    share of its routed outflow goes to node ``to`` (or leaves the network if ``to`` is ''), and the rest goes
    downstream. A node's inflow is its own lateral flow plus its share of the routed outflow of every node feeding
    it. Returns a DataFrame of each node's routed outflow (before any split); its ``attrs["storages"]`` maps each
    storage node to a DataFrame of its release and stored volume (m3/s, m3/s-days).
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

    pending = {n: len(f) for n, f in feeds.items()}  # upstream before downstream (Kahn's algorithm)
    sends = {n: [] for n in lateral_inflows}
    for n, f in feeds.items():
        for up, _ in f:
            sends[up].append(n)
    order, ready = [], [n for n, c in pending.items() if c == 0]
    while ready:
        n = ready.pop()
        order.append(n)
        for to in sends[n]:
            pending[to] -= 1
            if not pending[to]:
                ready.append(to)
    if len(order) < len(lateral_inflows):
        raise ValueError(f"flow splits make a loop through {next(n for n, c in pending.items() if c)}")

    out, storages, budgets = {}, {}, {}
    for node in order:
        inflow = np.asarray(lateral_inflows[node], dtype=float).copy()
        for up, share in feeds[node]:
            inflow += out[up] * share
        _validate_flow(inflow)
        k, x, dt = reaches[node]["k_days"], reaches[node]["x"], 1.0
        if k >= MIN_K_DAYS:
            if not 2 * k * x <= dt <= 2 * k * (1 - x):
                raise ValueError("Muskingum stability requires 2*K*X <= dt <= 2*K*(1-X)")
            d = 2 * k * (1 - x) + dt
            b, a = [(dt - 2 * k * x) / d, (dt + 2 * k * x) / d], [1.0, -(2 * k * (1 - x) - dt) / d]
            routed = lfilter(b, a, inflow, zi=lfilter_zi(b, a) * inflow[0])[0]
        else:
            routed = (1 - k) * inflow + k * np.concatenate(([inflow[0]], inflow[:-1]))
        # Daily channel exchanges are applied to routed water before reservoir operation.
        # Fixed potential footprint: rainfall can rewet a dry channel. Losses cannot draw
        # on implicit Muskingum storage or on reservoir storage; this is an outlet approximation.
        cfg = reaches[node]
        def demand(name):
            value = cfg.get(name, 0.0)
            if isinstance(value, pd.Series) and not value.index.equals(index):
                raise ValueError(f'{name} dates must match inflows')
            values = np.broadcast_to(np.asarray(value, dtype=float), routed.shape)
            _validate_flow(values)
            return values
        rain, evap_demand, seep_demand = demand('rain_m3s'), demand('evap_m3s'), demand('seepage_m3s')
        before = routed.copy()
        available = routed + rain
        total = evap_demand + seep_demand
        scale = np.divide(available, total, out=np.ones_like(available), where=total > 0)
        scale = np.minimum(scale, 1.0)
        evap, seep = evap_demand * scale, seep_demand * scale
        routed = np.maximum(available - total, 0.0)
        loss = cfg.get('loss', 0.0)
        if not np.isfinite(loss) or not 0 <= loss <= 1:
            raise ValueError('loss must be a fraction between 0 and 1')
        misc = routed * loss
        routed -= misc
        if record_budget:
            budget = pd.DataFrame({'routed_m3s': before, 'rain_m3s': rain,
                'evap_m3s': evap, 'seepage_m3s': seep, 'misc_m3s': misc,
                'after_fluxes_m3s': routed}, index=index)
            budgets[node] = budget.sum() if record_budget == 'totals' else budget
        if reaches[node].get("max_release") is not None:
            routed, stored = store_and_release(routed, reaches[node]["max_release"])
            storages[node] = pd.DataFrame({"release_m3s": routed, "stored_m3s_days": stored}, index=index)
        out[node] = routed
    result = pd.DataFrame(out, index=index)
    result.attrs["storages"] = storages
    result.attrs["channel_budget"] = budgets
    return result


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
