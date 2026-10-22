"""Daily GR4J rainfall-runoff model.

Inputs are catchment-average precipitation and potential evapotranspiration in
mm/day. The implementation follows the standard four-parameter GR4J structure
with a production store, unit hydrographs, and routing store.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def gr4j(
    forcing: pd.DataFrame,
    x1: float,
    x2: float,
    x3: float,
    x4: float,
    *,
    precip_column: str = "P",
    pet_column: str = "PET",
    production_store: float | None = None,
    routing_store: float | None = None,
    return_states: bool = False,
):
    """Simulate daily discharge with GR4J.

    Parameters
    ----------
    forcing:
        DataFrame with daily precipitation and PET columns in mm/day. The
        default column names, ``P`` and ``PET``, match ``areal_average``.
        Missing and non-finite values are rejected.
    x1:
        Production store capacity (mm), positive.
    x2:
        Groundwater exchange coefficient (mm/day), may be positive or negative.
    x3:
        Routing store capacity (mm), positive.
    x4:
        Unit hydrograph time base (days), at least 0.5.
    production_store, routing_store:
        Initial store contents in mm. Defaults to 60% of x1 and 70% of x3,
        respectively, as common GR4J initial conditions.
    return_states:
        If true, return a DataFrame with Q and the production/routing stores.

    Example
    -------
    ``q = gr4j(forcing, x1=350, x2=0, x3=90, x4=1.7)``

    Returns
    -------
    pandas.Series or pandas.DataFrame
        Simulated daily discharge in mm/day (equivalent to catchment runoff
        depth per day). Convert to m3/s separately using catchment area if
        needed.
    """
    _validate_parameters(x1, x2, x3, x4)
    if not isinstance(forcing, pd.DataFrame):
        raise TypeError("forcing must be a pandas DataFrame with P and PET columns")
    missing = [column for column in (precip_column, pet_column) if column not in forcing]
    if missing:
        raise ValueError(f"forcing is missing required column(s): {', '.join(missing)}")
    p, _ = _as_1d_array(forcing[precip_column], precip_column)
    e, _ = _as_1d_array(forcing[pet_column], pet_column)
    if np.any(p < 0) or np.any(e < 0):
        raise ValueError("precip and pet must be non-negative")

    s = 0.6 * x1 if production_store is None else float(production_store)
    r = 0.7 * x3 if routing_store is None else float(routing_store)
    if not 0 <= s <= x1:
        raise ValueError("production_store must be between 0 and x1")
    if r < 0:
        raise ValueError("routing_store must be non-negative")

    uh1, uh2 = _unit_hydrographs(float(x4))
    uh1_queue = np.zeros(len(uh1), dtype=float)
    uh2_queue = np.zeros(len(uh2), dtype=float)
    q_out = np.empty(p.size, dtype=float)
    s_out = np.empty(p.size, dtype=float)
    r_out = np.empty(p.size, dtype=float)

    for t, (rain, evap) in enumerate(zip(p, e)):
        if rain >= evap:
            net_rain = rain - evap
            ratio = net_rain / x1
            tanh_ratio = np.tanh(ratio)
            ps = x1 * (1 - (s / x1) ** 2) * tanh_ratio / (1 + (s / x1) * tanh_ratio)
            s += ps
            effective_rain = net_rain - ps
        else:
            net_evap = evap - rain
            ratio = net_evap / x1
            tanh_ratio = np.tanh(ratio)
            es = s * (2 - s / x1) * tanh_ratio / (1 + (1 - s / x1) * tanh_ratio)
            s -= es
            effective_rain = 0.0

        percolation = s * (1 - (1 + (4 * s / (9 * x1)) ** 4) ** -0.25)
        s -= percolation
        effective_rain += percolation

        uh1_queue += effective_rain * uh1
        uh2_queue += effective_rain * uh2
        q9 = uh1_queue[0]
        q1 = uh2_queue[0]
        uh1_queue[:-1] = uh1_queue[1:]
        uh1_queue[-1] = 0.0
        uh2_queue[:-1] = uh2_queue[1:]
        uh2_queue[-1] = 0.0

        exchange = x2 * (r / x3) ** 3.5
        r += q9 * 0.9 + exchange
        r = max(0.0, r)
        qr = r * (1 - (1 + (r / x3) ** 4) ** -0.25)
        r -= qr
        qd = max(0.0, q1 * 0.1 + exchange)
        q_out[t] = qr + qd
        s_out[t] = s
        r_out[t] = r

    q = pd.Series(q_out, index=forcing.index, name="Q")
    if not return_states:
        return q
    return pd.DataFrame(
        {"Q": q_out, "production_store": s_out, "routing_store": r_out},
        index=forcing.index,
    )


def gr4j_subcatchments(forcing, subcatchments, parameter_sets):
    """Run GR4J independently for multiple units and aggregate discharge.

    ``forcing`` contains ``<unit>_P`` and ``<unit>_PET`` columns. ``subcatchments``
    maps unit IDs to area in km2, while ``parameter_sets`` maps each ID to its
    ``x1``..``x4`` values. Returns per-unit discharge plus total discharge in
    m3/s; unit runoff depths are area-scaled before aggregation.
    """
    if not isinstance(forcing, pd.DataFrame):
        raise TypeError("forcing must be a pandas DataFrame")
    ids = list(subcatchments)
    if set(ids) != set(parameter_sets):
        raise ValueError("subcatchments and parameter_sets must have the same ids")

    output = pd.DataFrame(index=forcing.index)
    for unit_id in ids:
        area_km2 = float(subcatchments[unit_id])
        if not np.isfinite(area_km2) or area_km2 <= 0:
            raise ValueError(f"area for {unit_id} must be positive and finite")
        unit_forcing = forcing.rename(columns={
            f"{unit_id}_P": "P",
            f"{unit_id}_PET": "PET",
        })
        q_depth = gr4j(unit_forcing, **parameter_sets[unit_id])
        output[f"{unit_id}_Q_m3s"] = q_depth * area_km2 / 86.4
    output["Q_total_m3s"] = output.sum(axis=1)
    return output


def _validate_parameters(x1, x2, x3, x4):
    params = np.asarray([x1, x2, x3, x4], dtype=float)
    if not np.all(np.isfinite(params)):
        raise ValueError("GR4J parameters must be finite")
    if x1 <= 0 or x3 <= 0 or x4 < 0.5:
        raise ValueError("x1 and x3 must be positive and x4 must be at least 0.5 days")


def _as_1d_array(values, name):
    index = values.index if isinstance(values, pd.Series) else None
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError(f"{name} must be a one-dimensional sequence")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must not contain missing or non-finite values")
    return array, index


def _unit_hydrographs(x4):
    """Cumulative S-curves sampled into the two GR4J unit hydrographs."""
    n1 = int(np.ceil(x4))
    n2 = int(np.ceil(2 * x4))
    s1 = np.asarray([_s_curve1(i / x4, x4) for i in range(n1 + 1)])
    s2 = np.asarray([_s_curve2(i / x4, x4) for i in range(n2 + 1)])
    return np.diff(s1), np.diff(s2)


def _s_curve1(t, x4):
    if t <= 0:
        return 0.0
    if t < 1:
        return t ** 2.5
    return 1.0


def _s_curve2(t, x4):
    if t <= 0:
        return 0.0
    if t < 1:
        return 0.5 * t ** 2.5
    if t < 2:
        return 1 - 0.5 * (2 - t) ** 2.5
    return 1.0
