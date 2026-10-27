"""Calibrate GR4J against unregulated headwater gauges (BoM Hydrologic Reference Stations) on observed climate.

Each HRS gauge (downloads/download_hrs_flow.py) is fitted on its own: GR4J runs on the BoM AWO daily rainfall and PET of
the model basins above it (downloads/download_awo_climate.py), and differential evolution finds the x1-x4 that maximise
the Kling-Gupta efficiency (KGE) of daily runoff depth over CAL. The fitted set is then scored, unchanged, over VAL, years
it never saw. Runoff is compared as depth (mm/day = ML/day / km2 over the HRS catchment area), so the gauge's catchment
need not match the model basins' area. The forcing is the model basins': every basin above the gauge's own basin, plus
the gauge's basin weighted by the catchment area they leave over; a gauge whose catchment is smaller than the basins
above it (a tributary inside its basin) takes its own basin's climate alone.

Per system, the gauge set with the best median validation KGE across all the system's gauges is chosen as its regional
set. Days with HRS quality code E (unreliable) or G (gap filled) are left out. Writes data/calibration/gr4j_headwater.csv
(one row per gauge) and gr4j_systems.json. The fitted parameters are not used by the model until set in gr4j.py.

``--zones`` (after a calibration) picks the plains set from the saved fits: of the gauges whose catchment's observed aridity
index is under aridity.PLAINS_BELOW_AI, the fitted set with the best median validation KGE over them, from every system. It
scores the choice leave-one-out (each gauge with the set picked over the others) against each system's set and adds it to
gr4j_systems.json as "zones".

Run from the repository root with ``python 2b_calibration/calibrate_gr4j.py [--zones]``.
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import differential_evolution

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "1_masking"), str(ROOT / "2a_rainfall_runoff"), str(ROOT / "5_outputs")]

from aridity import PLAINS_BELOW_AI
from config import DISPLAY_SYSTEMS, SYSTEMS
from gr4j import DEFAULT_PARAMS, gr4j
from results_db import load_geometry

CLIMATE = ROOT / "data" / "input" / "climate"
ROUTING = ROOT / "data" / "input" / "routing"
OUT = ROOT / "data" / "calibration"
WARMUP_END = "2012-12-31"  # the first year fills GR4J's stores and is not scored
CAL = ("2013-01-01", "2019-12-31")  # includes the 2016 floods and the 2017-2019 drought
VAL = ("2020-01-01", "2026-02-28")  # includes the 2021-2022 floods; HRS ends February 2026
MIN_DAYS = 3 * 365  # scored days a gauge needs in each period
BOUNDS = [(10, 2500), (-10, 5), (1, 1000), (0.5, 6)]  # x1 mm, x2 mm/d, x3 mm, x4 days
BAD_CODES = {"E", "G"}


def kge(sim, obs):
    """Kling-Gupta efficiency (Gupta et al. 2009): 1 is perfect, below -0.41 is worse than the mean flow."""
    r = np.corrcoef(sim, obs)[0, 1]
    return 1 - np.sqrt((r - 1) ** 2 + (sim.std() / obs.std() - 1) ** 2 + (sim.mean() / obs.mean() - 1) ** 2)


def nse(sim, obs):
    return 1 - ((sim - obs) ** 2).sum() / ((obs - obs.mean()) ** 2).sum()


def upstream(basins, own):
    """The basins draining into ``own`` (not ``own`` itself), following next_id."""
    above, todo = [], [own]
    while todo:
        b = todo.pop()
        inflow = basins.index[basins["next_id"] == b].tolist()
        above += inflow
        todo += inflow
    return above


def gauge_weights(basins, own, area_km2):
    """{basin: area weight} for the climate above a gauge of catchment ``area_km2`` in basin ``own``."""
    above = upstream(basins, own)
    left = area_km2 - basins.loc[above, "area_km2"].sum()
    if not above or left <= 0:
        return {own: basins.at[own, "area_km2"]}
    return {**basins.loc[above, "area_km2"].to_dict(), own: min(left, basins.at[own, "area_km2"])}


def simulate(params, forcing):
    """Area-weighted GR4J runoff depth (mm/day) over [(weight, P, PET)]."""
    total = sum(w for w, _, _ in forcing)
    return sum(w * gr4j(p, e, params) for w, p, e in forcing) / total


def fit(job):
    """Calibrate one gauge: the job's row with its fitted parameters and scores."""
    row, forcing, obs, cal, val = job
    loss = lambda x: -np.nan_to_num(kge(simulate(x, forcing)[cal], obs[cal]), nan=-10.0)  # nan: a flat simulation
    best = differential_evolution(loss, BOUNDS, seed=1, popsize=15, maxiter=150, tol=1e-6, polish=False)
    params = tuple(float(v) for v in best.x)
    # parameters within 1% of the search range of a bound: the best fit may lie outside it
    at_bound = [n for n, v, (lo, hi) in zip(("x1", "x2", "x3", "x4"), params, BOUNDS) if min(v - lo, hi - v) < 0.01 * (hi - lo)]
    scores = {"at_bound": " ".join(at_bound)}
    for name, p in (("", params), ("default_", DEFAULT_PARAMS)):
        sim = simulate(p, forcing)
        for period, mask in (("cal", cal), ("val", val)):
            scores[f"{name}kge_{period}"] = kge(sim[mask], obs[mask])
            scores[f"{name}nse_{period}"] = nse(sim[mask], obs[mask])
            scores[f"{name}bias_{period}"] = sim[mask].sum() / obs[mask].sum() - 1
    print(f"  {row['station']} {row['name']}: KGE cal {scores['kge_cal']:.2f}, val {scores['kge_val']:.2f} "
          f"(default {scores['default_kge_cal']:.2f}, {scores['default_kge_val']:.2f})", flush=True)
    return {**row, **dict(zip(("x1", "x2", "x3", "x4"), params)), **scores}


def system_jobs(system):
    """(calibration jobs, {station: (forcing, obs, val mask)}) for the system's HRS gauges with enough record."""
    meta_file = ROUTING / f"{system}_hrs_flow_daily_metadata.json"
    if not meta_file.exists():
        return [], {}
    stations = json.loads(meta_file.read_text())["stations"]
    flow = pd.read_csv(ROUTING / f"{system}_hrs_flow_daily.csv", dtype={"station": str}, parse_dates=["date"])
    climate = pd.read_csv(CLIMATE / f"{system}_basin_P_PET_2012_2026.csv", index_col="date", parse_dates=True)
    climate = climate.loc[:VAL[1]].interpolate(limit=5)  # an occasional missing AWO day
    basins = pd.concat([load_geometry(u, "basins") for u in SYSTEMS[system]["units"]]).set_index("subcatchment")
    dates = climate.index
    jobs, pool = [], {}
    for station, s in stations.items():
        weights = gauge_weights(basins, s["basin"], s["area_km2"])
        columns = [f"{b}_{v}" for b in weights for v in ("P", "PET")]
        if climate[columns].isna().any().any():
            print(f"  {station}: missing climate for its basins, skipped")
            continue
        days = flow[(flow["station"] == station) & ~flow["qcode"].isin(BAD_CODES)].set_index("date")["flow_ML"]
        obs = (days / s["area_km2"]).reindex(dates).to_numpy()
        ok = ~np.isnan(obs) & (dates > WARMUP_END)
        cal, val = ok & (dates >= CAL[0]) & (dates <= CAL[1]), ok & (dates >= VAL[0]) & (dates <= VAL[1])
        if cal.sum() < MIN_DAYS or val.sum() < MIN_DAYS:
            print(f"  {station}: {cal.sum()} calibration and {val.sum()} validation days, skipped")
            continue
        forcing = [(w, climate[f"{b}_P"].to_numpy(), climate[f"{b}_PET"].to_numpy()) for b, w in weights.items()]
        row = {"system": system, "station": station, "name": s["name"], "area_km2": s["area_km2"], "basin": s["basin"],
               "model_area_km2": round(sum(weights.values()), 1), "cal_days": int(cal.sum()), "val_days": int(val.sum())}
        jobs.append((row, forcing, obs, cal, val))
        pool[station] = (forcing, obs, val)
    return jobs, pool


def regional_set(fits, pool):
    """The fitted set whose median validation KGE across all the system's gauges is highest, with that median."""
    scored = []
    for f in fits:
        params = (f["x1"], f["x2"], f["x3"], f["x4"])
        median = float(np.median([kge(simulate(params, forcing)[val], obs[val]) for forcing, obs, val in pool.values()]))
        scored.append((median, f["station"], params))
    return max(scored)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, systems = [], {}
    for system in DISPLAY_SYSTEMS:
        jobs, pool = system_jobs(system)
        print(f"{system}: calibrating {len(jobs)} gauges")
        if not jobs:
            continue
        with ProcessPoolExecutor() as executor:
            fits = list(executor.map(fit, jobs))
        rows += fits
        median, donor, params = regional_set(fits, pool)
        default = float(np.median([kge(simulate(DEFAULT_PARAMS, forcing)[val], obs[val]) for forcing, obs, val in pool.values()]))
        systems[system] = {"params": [round(v, 4) for v in params], "donor_station": donor, "gauges": len(fits),
                           "median_kge_val": round(median, 3), "default_median_kge_val": round(default, 3)}
        print(f"{system}: regional set from {donor} {np.round(params, 2).tolist()}, median validation KGE {median:.2f} (default {default:.2f})")
    pd.DataFrame(rows).round(4).to_csv(OUT / "gr4j_headwater.csv", index=False)
    (OUT / "gr4j_systems.json").write_text(json.dumps({"calibration": CAL, "validation": VAL, "objective": "KGE, daily runoff depth",
                                                       "systems": systems}, indent=2) + "\n")
    print(f"Saved {OUT.relative_to(ROOT)}/gr4j_headwater.csv and gr4j_systems.json")


def zones():
    """Pick the plains set from the saved fits and record it, with its leave-one-out scores, in gr4j_systems.json."""
    fits = pd.read_csv(OUT / "gr4j_headwater.csv", dtype={"station": str}).drop_duplicates("station").set_index("station")
    pool, ai = {}, {}
    for system in DISPLAY_SYSTEMS:
        for station, (forcing, obs, val) in system_jobs(system)[1].items():
            if station in fits.index and station not in pool:
                pool[station] = (forcing, obs, val)
                ai[station] = sum(w * np.nansum(p) for w, p, _ in forcing) / sum(w * np.nansum(e) for w, _, e in forcing)
    gauges = list(pool)
    params = {d: tuple(fits.loc[d, ["x1", "x2", "x3", "x4"]]) for d in gauges}
    score = pd.DataFrame({d: {g: kge(simulate(params[d], pool[g][0])[pool[g][2]], pool[g][1][pool[g][2]]) for g in gauges} for d in gauges})  # rows scored, columns donor
    best = lambda peers, donors: max(donors, key=lambda d: score.loc[peers, d].median())
    plains = [g for g in gauges if ai[g] < PLAINS_BELOW_AI]
    own = lambda g: [h for h in gauges if fits.at[h, "system"] == fits.at[g, "system"] and h != g]
    before = {g: score.at[g, best(own(g), [d for d in gauges if d != g])] for g in plains}
    after = {g: score.at[g, best([h for h in plains if h != g], [d for d in gauges if d != g])] for g in plains}
    donor = best(plains, gauges)
    record = {"plains_below_aridity_index": PLAINS_BELOW_AI, "plains_gauges": len(plains), "plains_donor_station": donor,
              "plains_donor_aridity_index": round(ai[donor], 3), "plains_params": [round(v, 4) for v in params[donor]],
              "plains_median_kge_val": round(float(score.loc[plains, donor].median()), 3),
              "loo_median_kge_val_system_set": round(float(np.median(list(before.values()))), 3),
              "loo_median_kge_val_plains_set": round(float(np.median(list(after.values()))), 3),
              "loo_plains_gauges_improved": int(sum(after[g] > before[g] for g in plains)),
              "driest_gauge_aridity_index": round(min(ai.values()), 3)}
    summary = json.loads((OUT / "gr4j_systems.json").read_text())
    (OUT / "gr4j_systems.json").write_text(json.dumps({**summary, "zones": record}, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    zones() if "--zones" in sys.argv[1:] else main()
