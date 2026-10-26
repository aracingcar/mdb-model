"""Run the modelled flow at every EWR gauge through the EWR tool (py_ewr), for each climate case.

    python 5_outputs/gauge_ewr.py evaluate [case ...]   slow (~10 min a case): py_ewr summary and yearly results into data/output/gauge_ewr/
    python 5_outputs/gauge_ewr.py export [case ...]     compact per-case results for the page into data/gauge_ewr/<case>.json

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
from results_db import load_geometry, load_results

GAUGES_FILE = ROOT / "data" / "input" / "routing" / "ewr_gauges.csv"
OUT_DIR = ROOT / "data" / "output" / "gauge_ewr"
EXPORT_DIR = ROOT / "data" / "gauge_ewr"
MAX_OFF_RIVER_KM = 1.5  # as in 3_routing/calibrate_routing.py
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


def evaluate(case):
    from py_ewr.scenario_handling import ScenarioHandler

    flows = case_flows(case, match_gauges())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{case['id']}.csv"
        flows.to_csv(path, date_format="%Y-%m-%d")
        handler = ScenarioHandler(str(path), "Standard time-series")
        handler.get_ewr_results().to_csv(OUT_DIR / f"{case['id']}_ewr_summary.csv", index=False)
        handler.get_yearly_ewr_results().to_csv(OUT_DIR / f"{case['id']}_ewr_yearly.csv", index=False)


def export(case):
    from py_ewr import data_inputs

    matched = match_gauges().set_index("gauge")
    summary = pd.read_csv(OUT_DIR / f"{case['id']}_ewr_summary.csv", dtype={"Gauge": str})
    yearly = pd.read_csv(OUT_DIR / f"{case['id']}_ewr_yearly.csv", dtype={"Gauge": str})
    sheet = data_inputs.get_EWR_table()
    sheet["Gauge"] = sheet["Gauge"].astype(str)
    sheet = sheet.drop_duplicates(["Gauge", "PlanningUnitName", "Code"]).set_index(["Gauge", "PlanningUnitName", "Code"])
    years = sorted(yearly["Year"].unique())
    by_ewr = {key: g.set_index("Year") for key, g in yearly.groupby(["Gauge", "PlanningUnit", "Code"])}
    full = lambda g: g.reindex(years)["totalPossibleDays"].ge(365)  # a record's part-year at either end is not judged

    def number(v):
        v = pd.to_numeric(v, errors="coerce")  # the sheet leaves unused thresholds blank
        return None if pd.isna(v) else float(v) if v % 1 else int(v)

    gauges = []
    for gauge, rows in summary.groupby("Gauge"):
        if gauge not in matched.index:
            continue
        ewrs = []
        for r in rows.itertuples():
            y = by_ewr[(gauge, r.PlanningUnit, r.Code)]
            ok = full(y)
            p = sheet.loc[(gauge, r.PlanningUnit, r.Code)]
            ach = y.reindex(years)["eventYears"].fillna(0).astype(int)
            ewrs.append({
                "code": r.Code, "pu": r.PlanningUnit,
                "thr": number(p["FlowThresholdMin"]), "thrMax": number(p["FlowThresholdMax"]), "dur": number(p["Duration"]),
                "sm": number(p["StartMonth"]), "em": number(p["EndMonth"]), "target": number(p["TargetFrequency"]), "mrip": number(p["MaxInter-event"]),
                "fr": round(min(1.0, r.Frequency / r.TargetFrequency), 3) if r.TargetFrequency else None,
                "ach": "".join(("1" if a else "0") if o else "-" for a, o in zip(ach, ok)),
                "max": y.reindex(years)["maxEventDays"].fillna(0).astype(int).tolist(),
            })
        m = matched.loc[gauge]
        gauges.append({"id": gauge, "name": m["name"], "lon": round(m["lon"], 4), "lat": round(m["lat"], 4), "river": m["river_id"], "km": m["km"],
                       "ewrs": sorted(ewrs, key=lambda e: (e["code"], e["pu"]))})
    EXPORT_DIR.mkdir(exist_ok=True)
    out = {"case": case["id"], "years": [int(y) for y in years], "gauges": sorted(gauges, key=lambda g: g["id"])}
    (EXPORT_DIR / f"{case['id']}.json").write_text(json.dumps(out, separators=(",", ":"), allow_nan=False))
    print(f"{case['id']}: {len(gauges)} gauges, {sum(len(g['ewrs']) for g in gauges)} EWRs -> data/gauge_ewr/{case['id']}.json")


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    step, *wanted = sys.argv[1:] or ["export"]
    for c in CLIMATE_CASES:
        if not wanted or c["id"] in wanted:
            {"evaluate": evaluate, "export": export}[step](c)
