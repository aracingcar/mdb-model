"""Run the modelled flow at every EWR gauge through the EWR tool (py_ewr), for each climate case.

    python 5_outputs/gauge_ewr.py evaluate [case ...]   slow (~10 min a case): py_ewr summary, yearly, event and gap results into data/output/gauge_ewr/
    python 5_outputs/gauge_ewr.py export [case ...]     compact per-case results for the page into data/gauge_ewr/<case>.json

An EWR gauge is a gauge of py_ewr's parameter sheet (positions in data/input/routing/ewr_gauges.csv) within MAX_OFF_RIVER_KM of a
modelled river. The model stores flow per river, not per point, so the gauge takes the flow of the river it sits on: the routed
outflow of that river's basin on a main channel, a length share of the basin's runoff on a tributary. Every case is run over its
whole stored series. py_ewr is only needed to evaluate; run_display.py copies the exported files into the page.
"""
import base64
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
from flow_regime_mappings import regimes_for
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


def encode_flow(values):
    """Daily flow as little-endian uint16, base64: steps of 0.1 ML/d below 1,000 ML/d, then steps of 3 ML/d (to about 167,000)."""
    codes = np.where(values < 1000, np.round(values * 10), 10000 + np.minimum(np.round((values - 1000) / 3), 55535))
    return base64.b64encode(codes.astype("<u2").tobytes()).decode()


def regime_years(values, index, years, hit_level):
    """Per water year (labelled by its first calendar year, as py_ewr does) of a regime at or above `hit_level`: the days, the longest run
    and the runs starting in the year, each -1 where the year is not complete. Lists in the order of `years`."""
    wy = np.where(index.month >= 7, index.year, index.year - 1)
    hit = values >= hit_level
    starts = hit & ~np.concatenate([[False], hit[:-1]])
    out = {"d": [], "l": [], "n": []}
    for y in years:
        in_year = wy == y
        days = int(in_year.sum())
        if days != (366 if pd.Timestamp(year=y + 1, month=2, day=1).is_leap_year else 365) or np.isnan(values[in_year]).any():
            for k in out:
                out[k].append(-1)
            continue
        h = hit[in_year]
        edges = np.diff(np.concatenate([[0], h.astype(int), [0]]))
        runs = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
        out["d"].append(int(h.sum()))
        out["l"].append(int(runs.max()) if len(runs) else 0)
        out["n"].append(int(starts[in_year].sum()))
    return out


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
        for name, getter in (("events", handler.get_all_events), ("successful_events", handler.get_all_successful_events), ("inter_events", handler.get_all_successful_interEvents)):
            getter().to_csv(OUT_DIR / f"{case['id']}_ewr_{name}.csv", index=False)


def export(case):
    from py_ewr import data_inputs

    matched = match_gauges().set_index("gauge")
    summary = pd.read_csv(OUT_DIR / f"{case['id']}_ewr_summary.csv", dtype={"Gauge": str})
    yearly = pd.read_csv(OUT_DIR / f"{case['id']}_ewr_yearly.csv", dtype={"Gauge": str})
    sheet = data_inputs.get_EWR_table()
    sheet["Gauge"] = sheet["Gauge"].astype(str)
    sheet = sheet.drop_duplicates(["Gauge", "PlanningUnitName", "Code"]).set_index(["Gauge", "PlanningUnitName", "Code"])
    read = lambda name, dates: pd.read_csv(OUT_DIR / f"{case['id']}_ewr_{name}.csv", dtype={"Gauge": str}, parse_dates=dates)
    events, successful, gaps = read("events", ["startDate", "endDate"]), read("successful_events", ["startDate"]), read("inter_events", ["startDate", "endDate"])
    key = ["Gauge", "PlanningUnit", "Code"]
    events_by, gaps_by = dict(list(events.groupby(key))), dict(list(gaps.groupby(key)))
    started = {k: set(g["startDate"]) for k, g in successful.groupby(key)}
    t0 = events["startDate"].min().normalize().replace(month=1, day=1)  # day 0 of the event and gap offsets
    years = sorted(yearly["Year"].unique())
    by_ewr = {key: g.set_index("Year") for key, g in yearly.groupby(["Gauge", "PlanningUnit", "Code"])}
    full = lambda g: g.reindex(years)["totalPossibleDays"].ge(365)  # a record's part-year at either end is not judged

    def number(v):
        v = pd.to_numeric(v, errors="coerce")  # the sheet leaves unused thresholds blank
        return None if pd.isna(v) else float(v) if v % 1 else int(v)

    def deltas(starts):  # start days as steps from the one before: small numbers, so the file stays small
        return np.diff(starts, prepend=0).tolist()

    def event_fields(k):
        ev = events_by[k].sort_values("startDate") if k in events_by else events.iloc[:0]
        starts = ((ev["startDate"] - t0).dt.days).to_numpy(dtype=int)
        ok = ev["startDate"].isin(started.get(k, ())).to_numpy()
        gp = gaps_by[k].sort_values("startDate") if k in gaps_by else gaps.iloc[:0]
        gs = ((gp["startDate"] - t0).dt.days).to_numpy(dtype=int)
        months = ev["startDate"][ok].dt.month.value_counts()
        return {"es": deltas(starts), "el": ((ev["endDate"] - ev["startDate"]).dt.days + 1).tolist(), "eo": "".join("1" if o else "0" for o in ok),
                "tm": [int(months.get(m, 0)) for m in range(1, 13)], "gs": deltas(gs), "gl": gp["interEventLength"].astype(int).tolist()}

    flows = case_flows(case, matched.reset_index())
    handlers = {k: h for h, keys in data_inputs.get_ewr_calc_config(None).items() for k in keys}
    lengths = {k: g.groupby("waterYear")["eventDuration"].apply(lambda v: sorted(v, reverse=True)).to_dict() for k, g in events_by.items()}

    def ratios(y, k, p, dur, low, per_year):  # the dashboard's duration ratio: the longest event (any-days EWRs: the days at or above) over the duration, capped at 2
        if not dur or dur <= 0:
            return [None] * len(years)
        out = []
        for w in years:
            if per_year and per_year > 1 and not low:
                lens = lengths.get(k, {}).get(w, [])
                days = lens[per_year - 1] if len(lens) >= per_year else 0
            else:
                days = y["totalEventDays" if low else "maxEventDays"].get(w, np.nan)
            out.append(None if pd.isna(days) else round(min(float(days) / dur, 2.0), 2))
        return out

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
            multi = isinstance(p["Multigauge"], str) and bool(p["Multigauge"].strip())
            low = handlers.get(f"{r.Code}-{'multigauge' if multi else 'single'}-{p['FlowLevelVolume']}") in ("lowflow_handle", "lowflow_handle_multi")
            dur, per_year = number(p["Duration"]), number(p["EventsPerYear"])
            ewrs.append({
                "code": r.Code, "pu": r.PlanningUnit, "low": low,
                "dr": ratios(y, (gauge, r.PlanningUnit, r.Code), p, dur, low, per_year),
                "thr": number(p["FlowThresholdMin"]), "thrMax": number(p["FlowThresholdMax"]), "dur": number(p["Duration"]),
                "minSpell": number(p["MinSpell"]), "sm": number(p["StartMonth"]), "em": number(p["EndMonth"]), "target": number(p["TargetFrequency"]), "mrip": number(p["MaxInter-event"]),
                "fr": round(min(1.0, r.Frequency / r.TargetFrequency), 3) if r.TargetFrequency else None,
                "ach": "".join(("1" if a else "0") if o else "-" for a, o in zip(ach, ok)),
                "max": y.reindex(years)["maxEventDays"].fillna(0).astype(int).tolist(),
                **event_fields((gauge, r.PlanningUnit, r.Code)),
            })
        m = matched.loc[gauge]
        flow_ewrs = [(e, sheet.loc[(gauge, e["pu"], e["code"])]) for e in ewrs]
        by_regime = {}
        for e, p in flow_ewrs:  # each regime's threshold is the lowest flow threshold among the gauge's flow EWRs in it (the dashboard's rule)
            if p["FlowLevelVolume"] == "F" and e["thr"] is not None:
                for regime in regimes_for(e["code"], p["State"]):
                    if regime != "excluded":
                        by_regime.setdefault(regime, []).append(e)
        regimes = []
        for regime, members in sorted(by_regime.items(), key=lambda kv: min(e["thr"] for e in kv[1])):
            thr = min(e["thr"] for e in members)
            regimes.append({"regime": regime, "thr": thr, "codes": sorted({e["code"] for e in members}), "atThr": sorted({e["code"] for e in members if e["thr"] == thr}),
                            **regime_years(flows[f"{gauge}_flow"].to_numpy(dtype=float), flows.index, years, thr)})
        gauges.append({"regimes": regimes, "id": gauge, "name": m["name"], "lon": round(m["lon"], 4), "lat": round(m["lat"], 4), "river": m["river_id"], "km": m["km"],
                       "ewrs": sorted(ewrs, key=lambda e: (e["code"], e["pu"]))})
    EXPORT_DIR.mkdir(exist_ok=True)
    (EXPORT_DIR / f"{case['id']}_flow.json").write_text(json.dumps({"t0": t0.strftime("%Y-%m-%d"), "n": len(flows), "flow": {c[:-5]: encode_flow(flows[c].to_numpy(dtype=float)) for c in flows.columns if c[:-5] in matched.index}}, separators=(",", ":")))
    out = {"case": case["id"], "t0": t0.strftime("%Y-%m-%d"), "years": [int(y) for y in years], "gauges": sorted(gauges, key=lambda g: g["id"])}
    (EXPORT_DIR / f"{case['id']}.json").write_text(json.dumps(out, separators=(",", ":"), allow_nan=False))
    print(f"{case['id']}: {len(gauges)} gauges, {sum(len(g['ewrs']) for g in gauges)} EWRs -> data/gauge_ewr/{case['id']}.json")


if __name__ == "__main__":
    warnings.filterwarnings("ignore")
    step, *wanted = sys.argv[1:] or ["export"]
    for c in CLIMATE_CASES:
        if not wanted or c["id"] in wanted:
            {"evaluate": evaluate, "export": export}[step](c)
