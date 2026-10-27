"""Run the modelled flow at every EWR gauge through the EWR tool (py_ewr), for each climate case.

    python 5_outputs/gauge_ewr.py evaluate [case ...]   slow (~10 min a case): py_ewr summary, yearly, event and gap results into data/output/gauge_ewr/
    python 5_outputs/gauge_ewr.py export [case ...]     compact per-case results for the page into data/gauge_ewr/<case>.json

`observed` is a case too: the BoM gauge records of data/input/routing/ put through the same steps (no model, so only the gauges with a record).

An EWR gauge is a gauge of py_ewr's parameter sheet (positions in data/input/routing/ewr_gauges.csv) within MAX_OFF_RIVER_KM of a
modelled river. The model stores flow per river, not per point, so the gauge takes the flow of the river it sits on: the routed
outflow of that river's basin on a main channel, a length share of the basin's runoff on a tributary. Every case is run over its
whole stored series. py_ewr is only needed to evaluate; run_display.py copies the exported files into the page.
"""
import json
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import shapely

ROOT = Path(__file__).resolve().parent.parent
for folder in ("1_masking", "5_outputs"):
    sys.path.insert(0, str(ROOT / folder))

from config import CLIMATE_CASES, SYSTEMS
from ewr_export import build
from results_db import load_geometry, load_results

GAUGES_FILE = ROOT / "data" / "input" / "routing" / "ewr_gauges.csv"
OUT_DIR = ROOT / "data" / "output" / "gauge_ewr"
EXPORT_DIR = ROOT / "data" / "gauge_ewr"
MAX_OFF_RIVER_KM = 1.5  # as in 3a_routing/calibrate_routing.py
KM_PER_DEGREE = 111
EXCLUDED = {"425020", "425022"}  # lake EWRs that need a level series, which the model does not produce: py_ewr stops on them
METHODS = ("gr4j", "muskingum")
UNITS = [u for s in SYSTEMS.values() for u in s["units"]]


def _km(coords):
    return np.column_stack([coords[:, 0] * np.cos(np.radians(coords[:, 1])) * KM_PER_DEGREE, coords[:, 1] * KM_PER_DEGREE])


def match_gauges():
    """The EWR gauges on a modelled river: gauge, name, lon, lat, SDL unit, river_id and distance (km), nearest river first."""
    gauges = pd.read_csv(GAUGES_FILE, dtype={"gauge": str})
    gauges = gauges[~gauges["gauge"].isin(EXCLUDED)]
    points = shapely.points(_km(gauges[["lon", "lat"]].to_numpy()))
    best = {}
    for unit in UNITS:
        rivers = load_geometry(unit, "rivers")
        if rivers is None:
            continue
        lines = [shapely.transform(g, _km) for g in rivers.geometry]
        for i, point in enumerate(points):
            km, k = min((line.distance(point), j) for j, line in enumerate(lines))
            if km <= MAX_OFF_RIVER_KM and (i not in best or km < best[i][0]):
                best[i] = (km, unit, rivers["river_id"].iloc[k])
    rows = [{**gauges.iloc[i].to_dict(), "unit": unit, "river_id": river, "km": round(km, 2)} for i, (km, unit, river) in best.items()]
    return pd.DataFrame(rows).sort_values("km").reset_index(drop=True)


def case_flows(case, matched):
    """Daily flow (ML/d), one `<gauge>_flow` column per matched gauge, over the case's whole stored series."""
    cols = {}
    for unit, group in matched.groupby("unit"):
        river_flow = load_results(unit, tuple(case["run"]), METHODS)[2]
        for row in group.itertuples():
            cols[f"{row.gauge}_flow"] = river_flow[row.river_id].astype(float)
    flows = pd.DataFrame(cols)
    flows.index.name = "Date"
    return flows


def observed_flows():
    """Observed daily flow (ML/d, from the BoM gauge records in data/input/routing/, m3/s) at the EWR gauges that have one, over the whole water
    years of the record (days without a reading blank), and those gauges (index gauge: name, lon, lat, river_id and km on the modelled river or blank)."""
    gauges = pd.read_csv(GAUGES_FILE, dtype={"gauge": str}).set_index("gauge")
    parts = []
    for path in sorted(GAUGES_FILE.parent.glob("*_observed_flow_daily.csv")):
        part = pd.read_csv(path, index_col=0, parse_dates=True)
        part.columns = part.columns.astype(str)
        parts.append(part[[c for c in part.columns if c in gauges.index and c not in EXCLUDED]])
    flow = pd.concat(parts, axis=1)
    flow = flow.loc[:, ~flow.columns.duplicated()] * 86.4
    first, last = flow.index.min(), flow.index.max()
    before = first - pd.Timedelta(days=1)
    start = pd.Timestamp(before.year if before.month < 7 else before.year + 1, 7, 1)  # the first whole water year
    end = pd.Timestamp(last.year if last.month >= 7 else last.year - 1, 6, 30)  # the last complete water year
    flow = flow.reindex(pd.date_range(start, end)).rename(columns=lambda c: f"{c}_flow")
    flow.index.name = "Date"
    matched = match_gauges().set_index("gauge")[["river_id", "km"]]
    gauges = gauges.loc[[c[:-5] for c in flow.columns]].join(matched).fillna({"river_id": "", "km": 0})
    return flow, gauges


def evaluate(case, flows=None):
    from py_ewr.scenario_handling import ScenarioHandler

    flows = case_flows(case, match_gauges()) if flows is None else flows
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{case['id']}.csv"
        flows.to_csv(path, date_format="%Y-%m-%d")
        handler = ScenarioHandler(str(path), "Standard time-series")
        handler.get_ewr_results().to_csv(OUT_DIR / f"{case['id']}_ewr_summary.csv", index=False)
        handler.get_yearly_ewr_results().to_csv(OUT_DIR / f"{case['id']}_ewr_yearly.csv", index=False)
        for name, getter in (("events", handler.get_all_events), ("successful_events", handler.get_all_successful_events), ("inter_events", handler.get_all_successful_interEvents)):
            getter().to_csv(OUT_DIR / f"{case['id']}_ewr_{name}.csv", index=False)


def export(case, flows=None, matched=None):
    """Write the page's results for a climate case, or for any `flows` (daily ML/d, a `<gauge>_flow` column each) whose gauges are `matched`."""
    if flows is None:
        matched = match_gauges().set_index("gauge")
        flows = case_flows(case, matched.reset_index())
    read = lambda name: pd.read_csv(OUT_DIR / f"{case['id']}_ewr_{name}.csv", dtype={"Gauge": str})
    out, flow = build(case["id"], flows, matched, read("summary"), read("yearly"), read("events"), read("successful_events"), read("inter_events"))
    EXPORT_DIR.mkdir(exist_ok=True)
    (EXPORT_DIR / f"{case['id']}_flow.json").write_text(json.dumps(flow, separators=(",", ":")))
    (EXPORT_DIR / f"{case['id']}.json").write_text(json.dumps(out, separators=(",", ":"), allow_nan=False))
    print(f"{case['id']}: {len(out['gauges'])} gauges, {sum(len(g['ewrs']) for g in out['gauges'])} EWRs -> data/gauge_ewr/{case['id']}.json")


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    step, *wanted = sys.argv[1:] or ["export"]
    for c in CLIMATE_CASES:
        if not wanted or c["id"] in wanted:
            {"evaluate": evaluate, "export": export}[step](c)
    if not wanted or "observed" in wanted:
        flows, gauges = observed_flows()
        {"evaluate": lambda c: evaluate(c, flows), "export": lambda c: export(c, flows, gauges)}[step]({"id": "observed"})
