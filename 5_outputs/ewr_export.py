"""The page's gauge results from py_ewr's output: per gauge, each EWR's yearly achievement, events, gaps, MRIP exceedance, flow regimes and
ecological themes, and the daily flow.

Used by gauge_ewr.py (the climate cases and observed flow, built into the page) and run in the browser, under Pyodide, on flow the
user uploads, so it imports nothing but pandas and numpy, and py_ewr when building.
"""
import base64
import io

import numpy as np
import pandas as pd

from flow_regime_mappings import regimes_for


def encode_flow(values):
    """Daily flow as little-endian uint16, base64: steps of 0.1 ML/d below 1,000 ML/d, then steps of 3 ML/d (to about 167,000); 65535 is a missing day."""
    codes = np.where(values < 1000, np.round(values * 10), 10000 + np.minimum(np.round((values - 1000) / 3), 55534))
    codes = np.where(np.isnan(values), 65535, codes)
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


THEMES = ["Flows & Connectivity", "Native Fish", "Waterbirds", "Native Vegetation", "Ecosystem Functions", "Other Species", "Unclassified"]  # the dashboard's order


def mrip_exceedance(flow, t0, mrip_years, spans):
    """The share of the record beyond the maximum inter-event period (the dashboard's ETP): days past the MRIP in the gaps between
    successful events, over the days of record outside gaps that hold a missing day (those have an unknown length and count nowhere).
    `spans` are (first day, last day) of each gap; None when the EWR has no maximum or nothing is left to count."""
    mrip = int(round(float(mrip_years) * 365)) if mrip_years and mrip_years > 0 else 0
    if not mrip:
        return None
    missing = np.concatenate([[0], np.cumsum(np.isnan(flow))])  # missing days before each day, to test a gap in one step
    counted, excess = len(flow), 0
    for a, b in spans:
        i, j = (a - t0).days, (b - t0).days
        days = j - i + 1
        if missing[j + 1] - missing[i]:
            counted -= days
        else:
            excess += max(0, days - mrip)
    return round(min(1.0, excess / counted), 4) if counted > 0 else None


def build(case_id, flows, matched, summary, yearly, events, successful, gaps):
    """The page's results for one flow series: (results, daily flow), both JSON-ready. `flows` is daily ML/d with a `<gauge>_flow` column
    per gauge from its first day; `matched` has a row per gauge (index gauge: name, lon, lat, river_id, km); the rest are py_ewr's results."""
    from py_ewr import data_inputs

    tidy = lambda df, dates=(): pd.read_csv(io.StringIO(df.to_csv(index=False)), dtype={"Gauge": str}, parse_dates=list(dates))  # as py_ewr's CSVs read back
    summary, yearly = tidy(summary), tidy(yearly)
    events, successful, gaps = tidy(events, ["startDate", "endDate"]), tidy(successful, ["startDate"]), tidy(gaps, ["startDate", "endDate"])
    sheet = data_inputs.get_EWR_table()
    sheet["Gauge"] = sheet["Gauge"].astype(str)
    sheet = sheet.drop_duplicates(["Gauge", "PlanningUnitName", "Code"]).set_index(["Gauge", "PlanningUnitName", "Code"])
    key = ["Gauge", "PlanningUnit", "Code"]
    events_by, gaps_by = dict(list(events.groupby(key))), dict(list(gaps.groupby(key)))
    started = {k: set(g["startDate"]) for k, g in successful.groupby(key)}
    t0 = flows.index[0].normalize()  # day 0 of the event and gap offsets, and of the daily flow
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

    objectives = data_inputs.get_obj_mapping()[["Gauge", "PlanningUnitName", "Code", "EcoObj", "Target"]].drop_duplicates()
    objectives["Gauge"], objectives["Target"] = objectives["Gauge"].astype(str), objectives["Target"].fillna("Unclassified")
    themes = THEMES + sorted(set(objectives["Target"]) - set(THEMES))
    themes_of = {k: [themes.index(t) for t in g["Target"]] for k, g in objectives.groupby(["Gauge", "PlanningUnitName", "Code"])}  # one entry per objective the EWR serves
    regs = []  # the flow regimes any EWR is in
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
        series = flows[f"{gauge}_flow"].to_numpy(dtype=float)
        for r in rows.itertuples():
            y = by_ewr[(gauge, r.PlanningUnit, r.Code)]
            ok = full(y)
            p = sheet.loc[(gauge, r.PlanningUnit, r.Code)]
            ach = y.reindex(years)["eventYears"].fillna(0).astype(int)
            multi = isinstance(p["Multigauge"], str) and bool(p["Multigauge"].strip())
            low = handlers.get(f"{r.Code}-{'multigauge' if multi else 'single'}-{p['FlowLevelVolume']}") in ("lowflow_handle", "lowflow_handle_multi")
            dur, per_year = number(p["Duration"]), number(p["EventsPerYear"])
            k = (gauge, r.PlanningUnit, r.Code)
            spans = [(flows.index[0], flows.index[-1])] if k not in started else [(a, b) for a, b in zip(gaps_by[k]["startDate"], gaps_by[k]["endDate"])] if k in gaps_by else []
            regimes = [x for x in regimes_for(r.Code, p["State"]) if x != "excluded"]
            regs.extend(x for x in regimes if x not in regs)
            ewrs.append({
                "code": r.Code, "pu": r.PlanningUnit, "low": low,
                "dr": ratios(y, (gauge, r.PlanningUnit, r.Code), p, dur, low, per_year),
                "thr": number(p["FlowThresholdMin"]), "thrMax": number(p["FlowThresholdMax"]), "dur": number(p["Duration"]),
                "minSpell": number(p["MinSpell"]), "sm": number(p["StartMonth"]), "em": number(p["EndMonth"]), "target": number(p["TargetFrequency"]), "mrip": number(p["MaxInter-event"]),
                "fr": round(min(1.0, r.Frequency / r.TargetFrequency), 3) if r.TargetFrequency else None,
                "frr": round(r.Frequency / r.TargetFrequency, 3) if r.TargetFrequency else None,  # uncapped, as the joint chart plots it
                "etp": mrip_exceedance(series, t0, number(p["MaxInter-event"]), spans), "reg": [regs.index(x) for x in regimes], "th": themes_of.get((gauge, r.PlanningUnit, r.Code), []),
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
    flow_out = {"t0": t0.strftime("%Y-%m-%d"), "n": len(flows), "flow": {c[:-5]: encode_flow(flows[c].to_numpy(dtype=float)) for c in flows.columns if c[:-5] in matched.index}}
    out = {"case": case_id, "t0": t0.strftime("%Y-%m-%d"), "n": len(flows), "years": [int(y) for y in years], "themes": themes, "regs": regs, "gauges": sorted(gauges, key=lambda g: g["id"])}
    return out, flow_out
