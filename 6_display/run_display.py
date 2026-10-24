"""Build the River Pulse page, docs/index.html, for every SDL unit of the displayed river systems, from results.db.

The page shows every unit's reaches and SDL boundary on one map. Its data files in docs/data/ are split so each stays
well under GitHub's file size limit: geometry, a shared evaporation pixel index, and per river system the climate
series (with each unit's evaporation values), the flow results and the browser engine's forcing.
"""
import base64
import hashlib
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.ndimage import binary_dilation

for folder in ("1_masking", "2_rainfall_runoff", "3_routing", "5_outputs"):  # also runs on its own: python 6_display/run_display.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / folder))

from catchment import buffer_outline
from config import DEFAULT_RUN, DISPLAY_SYSTEMS, SDL_UNITS, SYSTEMS, waterways_file
from evap_grid import PIXEL_DEG
from results_db import load_climate, load_geometry, load_results
from run_rainfall_runoff import RAINFALL_RUNOFF_MODEL, model_specs as runoff_specs
from run_routing import ROUTING_MODEL, model_specs as routing_specs
from terrain import Dem
from car.build import publish_assets

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
DISPLAY_FILE = HERE.parent / "docs" / "index.html"
DATA_DIR = HERE.parent / "docs" / "data"
CONTEXT_RIVERS = 120  # per river system: longest other named rivers drawn as thin context lines


def _rings(geom, dem=None, ndigits=4):
    """Exterior rings as [lon, lat] points, with the ground elevation (m) as a third value if a DEM is given."""
    out = []
    for p in shapely.get_parts(geom):
        if p.geom_type != "Polygon":  # a repaired geometry can be a collection of collections, or carry stray lines
            out += _rings(p, dem, ndigits) if hasattr(p, "geoms") else []
            continue
        if p.is_empty:
            continue
        pts = np.array(p.exterior.coords)[:, :2]
        z = np.round(dem.at(pts[:, 0], pts[:, 1])).astype(int) if dem is not None else None
        out.append([[round(x, ndigits), round(y, ndigits), *([int(z[i])] if z is not None else [])] for i, (x, y) in enumerate(pts)])
    return out


def _ribbon(line, mean_flow, peak, dem):
    width = 0.0018 + 0.0115 * np.sqrt(mean_flow / peak)
    ribbon = line.buffer(width, cap_style=2, join_style=2).simplify(0.001)
    return None if ribbon.is_empty else _rings(ribbon, dem)


def _rivers(rivers, mean_flow, dem):
    """Ribbons (width grows with mean flow) for every river segment, plus thin context lines for unrouted rivers."""
    peak = mean_flow.max()
    reaches = []
    for r in rivers.itertuples():
        rings = _ribbon(r.geometry, mean_flow[r.river_id], peak, dem)
        if rings:
            reaches.append({"unit": r.river_id, "name": r.name, "kind": r.kind, "rings": rings})
    ways = pd.concat([gpd.read_file(waterways_file(s)) for s in DISPLAY_SYSTEMS], ignore_index=True)
    ways = ways[(ways.waterway == "river") & (ways.name != "") & (~ways.name.isin(set(rivers["name"])))].drop_duplicates("osm_id")
    top = ways.assign(len=ways.length).sort_values("len", ascending=False).head(CONTEXT_RIVERS * len(DISPLAY_SYSTEMS))
    context = [_rings(g.buffer(0.0025, cap_style=2).simplify(0.001), dem) for g in top.geometry if not g.is_empty]
    return reaches, [r for rings in context for r in rings]


GRID_STEP = 0.01  # degrees (~1 km) for the terrain cells
DEMO_GRID_STEP = 0.02  # coarser terrain (~2 km) for the demo bundle the page opens on
DEMO_YEARS = (2027, 2036)  # the years the page opens on
LEAD_DAYS = 120  # the page's longest look-back (the 120-day evaporation bars; rain rolls over 60); the demo bundle starts this much early
ROLL_EVAP = 30  # the page's rolling evaporation window


def _terrain(units, dem, step=GRID_STEP):
    """Ground cells inside the modelled units: position, elevation, owning subcatchment and hillshade, plus per-unit stats."""
    minx, miny, maxx, maxy = units.total_bounds
    lons = np.arange(minx, maxx + step, step)
    lats = np.arange(maxy, miny - step, -step)  # north to south
    gx, gy = np.meshgrid(lons, lats)
    elev = dem.at(gx, gy)
    owner = np.full(gx.shape, -1)
    for i, geom in enumerate(units.geometry):
        owner[shapely.contains_xy(geom, gx, gy)] = i
    rows, cols = np.nonzero(binary_dilation(owner >= 0, iterations=3))  # a margin of ground beyond the valley, trimmed smoothly by the page
    stats = []
    for i in range(len(units)):
        e = elev[owner == i]
        stats.append({"mean": int(e.mean()), "min": int(e.min()), "max": int(e.max())} if e.size else {"mean": 0, "min": 0, "max": 0})
    return {"x0": round(float(lons[0]), 4), "y0": round(float(lats[0]), 4), "step": step,
            "col": cols.tolist(), "row": rows.tolist(), "elev": np.round(elev[rows, cols]).astype(int).tolist(),
            "unit": owner[rows, cols].tolist()}, stats


def _quantised(basin_forcing, names, var):
    """Basin series as base64 little-endian uint16 in hundredths of a mm/day, basin-major."""
    a = np.stack([basin_forcing[f"{n}_{var}"].to_numpy() for n in names])
    return base64.b64encode(np.clip(np.round(a * 100), 0, 65535).astype("<u2").tobytes()).decode()


def _quantised(basin_forcing, names, var):
    """Basin series as base64 little-endian uint16 in hundredths of a mm/day, basin-major."""
    a = np.stack([basin_forcing[f"{n}_{var}"].to_numpy() for n in names])
    return base64.b64encode(np.clip(np.round(a * 100), 0, 65535).astype("<u2").tobytes()).decode()


def _engine(system, basins, basin_forcing, regions, rivers):
    """Everything the browser needs to re-run one river system's rainfall-runoff, routing, river flows and ecology on another method pair."""
    names = list(basins["subcatchment"])
    splits = SYSTEMS[system]["splits"]
    return {
        "scale": 100,
        "basins": [{"id": b.subcatchment, "area": float(b.area_km2), "next": b.next_id, "lossRank": int(b.from_outlet),
                    **({"splits": splits[b.subcatchment]} if b.subcatchment in splits else {})}
                   for b in basins.itertuples()],
        "calibration": SYSTEMS[system]["routing"],
        "P": _quantised(basin_forcing, names, "P"),
        "PET": _quantised(basin_forcing, names, "PET"),
        "reachOutlet": {r.subcatchment: r.outlet_basin for r in regions.itertuples()},
        "rivers": [[r.river_id, r.basin, r.kind, r.share] for r in rivers.itertuples()],
        "units": {u: {"outlet": regions.loc[regions["sdl_unit"] == u, "unit_outlet"].iloc[0], "ecology": SDL_UNITS[u]["ecology"]}
                  for u in SYSTEMS[system]["units"]},
    }


def _evap(grids):
    """One pixel index over every unit's evaporation raster (they share a PIXEL_DEG lattice), each unit's 4 km cells
    numbered after the previous unit's; returns (index, {unit: base64 values}). Where rasters overlap the first unit wins."""
    first = next(iter(grids.values()))
    assert all(g["dates"] == first["dates"] and g["scale"] == first["scale"] for g in grids.values())
    minx, miny = min(g["bbox"][0] for g in grids.values()), min(g["bbox"][1] for g in grids.values())
    maxx, maxy = max(g["bbox"][2] for g in grids.values()), max(g["bbox"][3] for g in grids.values())
    nx, ny = round((maxx - minx) / PIXEL_DEG), round((maxy - miny) / PIXEL_DEG)
    idx, weights = np.full((ny, nx, 4), -1), np.zeros((ny, nx, 2), dtype="float32")
    parts, offset = [], 0
    for u, g in grids.items():
        r0, c0 = round((maxy - g["bbox"][3]) / PIXEL_DEG), round((g["bbox"][0] - minx) / PIXEL_DEG)
        gi, gw = g["idx"].reshape(g["ny"], g["nx"], 4), g["weights"].reshape(g["ny"], g["nx"], 2)
        sub_i, sub_w = idx[r0:r0 + g["ny"], c0:c0 + g["nx"]], weights[r0:r0 + g["ny"], c0:c0 + g["nx"]]
        take = (gi[..., 0] >= 0) & (sub_i[..., 0] < 0)
        sub_i[take], sub_w[take] = gi[take] + offset, gw[take]
        parts.append([u, int(g["values"].shape[1])])
        offset += g["values"].shape[1]
    assert offset < 65535, "too many 4 km cells for the page's uint16 index"
    index = {"bbox": [round(v, 4) for v in (minx, miny, maxx, maxy)], "nx": nx, "ny": ny, "dates": first["dates"], "scale": first["scale"],
             "cells": offset, "parts": parts,
             "idx": base64.b64encode(np.where(idx < 0, 65535, idx).astype("<u2").tobytes()).decode(),
             "weights": base64.b64encode(np.round(weights * 255).astype("uint8").tobytes()).decode()}
    return index, {u: base64.b64encode(g["values"].tobytes()).decode() for u, g in grids.items()}


def _label_point(geom, dem):
    p = geom.representative_point()
    return [round(p.x, 4), round(p.y, 4), int(dem.at(p.x, p.y))]


def _table(df):
    return None if df is None else df.reset_index().round(3).to_dict("list")


def _birds(df):
    if df is None:
        return None
    return {**df.reset_index().drop(columns="trigger_date").to_dict("list"), "trigger_date": [None if v != v else str(v) for v in df["trigger_date"]]}


def _evap_normals(sub, names, keys):
    """Per unit, the rolling 30-day PET (mm / 30 days) averaged for each day of the year over the whole run, computed
    as the page does (from the same 0.1 mm series), so a page holding only a few years still measures its anomalies
    against the full-run normal. Returned in the order of ``sorted(set(keys))``."""
    out = {}
    for n in names:
        a = sub[f"{n}_PET"].round(1).to_numpy(float)
        c = np.cumsum(a)
        s = c - np.concatenate([np.zeros(ROLL_EVAP), c[:-ROLL_EVAP]])
        r = s * ROLL_EVAP / np.minimum(np.arange(1, len(a) + 1), ROLL_EVAP)
        out[n] = pd.Series(r).groupby(keys).mean().round(2).tolist()
    return out


def _payloads(units, geo, climate, results, regions, rivers, river_flow, dem, terrain_step, window, demo, fringe):
    """The page's data files for one time window (a slice of the run's days): geometry, the shared evaporation index,
    and per river system its climate series and flow results.

    ``demo`` makes the small bundle the page opens on: it adds the full-run evaporation normals and draws only each
    basin's main channel, and per river system a detail file (1 km terrain cells, its other rivers and their flows)
    that the page fetches when it zooms in on that system."""
    first = next(iter(geo))
    all_days = climate[first][1].index
    days = all_days[window]
    reaches, context = _rivers(rivers, river_flow.mean(), dem)
    shown = {r["unit"] for r in reaches if r["kind"] == "channel" or not demo}
    mids = {r.subcatchment: (r.geometry.centroid if r.geometry.contains(r.geometry.centroid) else r.geometry.representative_point()) for r in regions.itertuples()}
    terrain, stats = _terrain(regions, dem, terrain_step)
    lo, hi = days[0].strftime("%Y-%m-%d"), days[-1].strftime("%Y-%m-%d")
    grids = {}
    for u in geo:  # keep only the stored evaporation fields inside the window
        g = climate[u][3]
        steps = [i for i, d in enumerate(g["dates"]) if lo <= d <= hi]
        grids[u] = {**g, "dates": [g["dates"][i] for i in steps], "values": np.ascontiguousarray(g["values"][steps])}
    evap_index, evap_values = _evap(grids)
    years = range(int(days[0].year + (days[0].month >= 7)), int(days[-1].year + (days[-1].month >= 7)) + 1)  # water years touched
    wy = lambda df: None if df is None else df[df.index.isin(years)]
    names = {u: SDL_UNITS[u]["name"] for u in geo}
    common = {"days": days.strftime("%Y-%m-%d").tolist(), "evap": evap_index}
    if demo:
        common["normalKeys"] = sorted(set(all_days.strftime("%m-%d")))
    files = {"geometry.json": {
        "units": [{"id": r.subcatchment, "sdl": r.sdl_unit, "name": r.region_name, "area": round(r.area_km2),
                   "mid": [round(mids[r.subcatchment].x, 4), round(mids[r.subcatchment].y, 4), int(dem.at(mids[r.subcatchment].x, mids[r.subcatchment].y))],
                   "rings": _rings(r.geometry.simplify(0.004), dem), "elev": stats[i]} for i, r in enumerate(regions.itertuples())],
        "terrain": terrain,
        "outline": _rings(regions.geometry.union_all().simplify(0.003), dem),
        "outlineBuffer": _rings(fringe.simplify(0.003), dem),  # the SDL outlines grown by OUTLINE_BUFFER_KM: rivers are kept within it
        "sdlBounds": [{"id": u, "name": names[u], "fullName": geo[u]["outline"]["sdl_name"].iloc[0], "system": s,
                       "mid": _label_point(geo[u]["outline"].geometry.iloc[0], dem),
                       "rings": _rings(geo[u]["outline"].geometry.iloc[0].simplify(0.003), dem)} for s, us in units.items() for u in us],
        "reaches": [r for r in reaches if r["unit"] in shown],
        "context": context,
    }, "climate.json": common}
    for s, us in units.items():
        full_sub = pd.concat([climate[u][1] for u in us], axis=1)
        sub = full_sub.iloc[window]
        ids = list(regions.loc[regions["sdl_unit"].isin(us), "subcatchment"])
        files[f"climate_{s}.json"] = {
            "P": {n: sub[f"{n}_P"].round(1).tolist() for n in ids},
            "PET": {n: sub[f"{n}_PET"].round(1).tolist() for n in ids},
            "evapParts": {u: evap_values[u] for u in us},
            **({"petNormal": _evap_normals(full_sub, ids, all_days.strftime("%m-%d"))} if demo else {}),
        }
        files[f"flow_{s}.json"] = {
            "reachFlow": {n: v.iloc[window].round(0).astype(int).tolist() for u in us for n, v in results[u][1].items()},
            "riverFlow": {n: base64.b64encode(np.clip(v.iloc[window].round(0).to_numpy(), 0, 65535).astype("<u2").tobytes()).decode()
                          for u in us for n, v in results[u][2].items() if n in shown},
            "sdl": {u: {"flow": results[u][0].iloc[window].round(0).astype(int).tolist(), "fish": _table(wy(results[u][3])),
                        "birds": _birds(wy(results[u][4])), "gum": _table(wy(results[u][5]))} for u in us},
        }
    if demo:
        fine, _ = _terrain(regions, dem, GRID_STEP)  # on the same origin as the demo terrain, every second node shared
        system_of = [SDL_UNITS[u]["system"] for u in regions["sdl_unit"]]
        for s in units:
            keep = [i for i, o in enumerate(fine["unit"]) if o >= 0 and system_of[o] == s]
            rest = [r for r in reaches if r["unit"] not in shown and SDL_UNITS[r["unit"].split("-R")[0]]["system"] == s]
            files[f"detail_{s}.json"] = {
                "terrain": {k: [fine[k][i] for i in keep] for k in ("col", "row", "elev", "unit")},
                "reaches": rest,
                "riverFlow": {r["unit"]: base64.b64encode(np.clip(river_flow[r["unit"]].iloc[window].round(0).to_numpy(), 0, 65535).astype("<u2").tobytes()).decode()
                              for r in rest},
            }
    return files


def run_display(run=DEFAULT_RUN, methods=(RAINFALL_RUNOFF_MODEL, ROUTING_MODEL)):
    """Write the interactive 'river pulse' page for every SDL unit of DISPLAY_SYSTEMS, from their stored geometry,
    climate and results for one run and method pair.

    The page opens on a small demo bundle (docs/data/demo/): DEMO_YEARS only, 2 km terrain and full-run evaporation
    normals. Choosing other years or methods reloads it on the full series (docs/data/full/, 1 km terrain), and the
    browser engine's forcing (docs/data/engine_*.json) is fetched only to recalculate other methods.
    """
    units = {s: SYSTEMS[s]["units"] for s in DISPLAY_SYSTEMS}
    geo = {u: {n: load_geometry(u, n) for n in ("outline", "subcatchments", "basins", "rivers")} for us in units.values() for u in us}
    climate = {u: load_climate(u, run) for u in geo}
    results = {u: load_results(u, run, methods) for u in geo}
    missing = [u for u in geo if climate[u] is None or results[u] is None or geo[u]["subcatchments"] is None]
    if missing:
        raise RuntimeError(f"no stored {'/'.join(run)} results for {', '.join(missing)}: run python main.py first")

    regions = pd.concat([geo[u]["subcatchments"] for u in geo], ignore_index=True)
    regions = gpd.GeoDataFrame(regions, crs=geo[next(iter(geo))]["subcatchments"].crs)
    regions["geometry"] = regions.geometry.make_valid()  # the stored GeoJSON can carry tiny self-touches that break the union
    rivers = gpd.GeoDataFrame(pd.concat([geo[u]["rivers"] for u in geo], ignore_index=True), crs=regions.crs)
    river_flow = pd.concat([results[u][2] for u in geo], axis=1)
    fringe = buffer_outline(shapely.union_all([geo[u]["outline"].geometry.union_all() for u in geo]))  # SDL outlines + OUTLINE_BUFFER_KM
    bx = np.array(fringe.bounds).reshape(2, 2)
    dem = Dem(np.concatenate([np.minimum(regions.total_bounds[:2], bx[0]), np.maximum(regions.total_bounds[2:], bx[1])]))
    all_days = climate[next(iter(geo))][1].index
    shown = np.flatnonzero((all_days.year >= DEMO_YEARS[0]) & (all_days.year <= DEMO_YEARS[1]))
    demo = slice(max(0, shown[0] - LEAD_DAYS), shown[-1] + 1)  # a lead-in so the rolling windows are full on the first shown day
    files = {f"demo/{k}": v for k, v in _payloads(units, geo, climate, results, regions, rivers, river_flow, dem, DEMO_GRID_STEP, demo, True, fringe).items()}
    files.update({f"full/{k}": v for k, v in _payloads(units, geo, climate, results, regions, rivers, river_flow, dem, GRID_STEP, slice(None), False, fringe).items()})
    engines = {}
    for s, us in units.items():
        basins = pd.concat([geo[u]["basins"] for u in us], ignore_index=True)
        engines[s] = f"engine_{s}_{'_'.join(run)}.json"
        files[engines[s]] = _engine(s, basins, pd.concat([climate[u][2] for u in us], axis=1), regions[regions["sdl_unit"].isin(us)],
                                    rivers[rivers["sdl_unit"].isin(us)])
    files["roads.json"] = json.loads((HERE / "roads.json").read_text())  # fetched only when the Roads switch is turned on
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for old in DATA_DIR.rglob("*.json"):  # keep only the build's own files; unchanged content is rewritten byte-for-byte
        if old.relative_to(DATA_DIR).as_posix() not in files:
            old.unlink()
    for d in [d for d in DATA_DIR.iterdir() if d.is_dir() and not any(d.iterdir())]:
        d.rmdir()
    for name, payload in files.items():
        (DATA_DIR / name).parent.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / name).write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False))
    names = [SDL_UNITS[u]["name"] for u in geo]
    title = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
    meta = {
        "title": title,
        "focus": next(iter(geo)),  # the unit whose outlet flow and ecology the page shows first
        "climate": {"globalModel": run[0], "scenario": run[1], "regionalConfig": run[2],
                    "period": f"{all_days[0].year}–{all_days[-1].year}", "source": "NARCliM2.0", "resolution": "4 km", "frequency": "Daily"},
        "runoff": {"selected": methods[0], "specs": runoff_specs()},
        "routing": {"selected": methods[1], "specs": routing_specs()},
        "run": "_".join(run),
        "years": [int(all_days[0].year), int(all_days[-1].year)],
        "demoYears": list(DEMO_YEARS),
        # full-run peak flow, so the demo bundle colours its rivers on the same scale as the full series
        "maxQ": round(float(max(max(results[u][0].max(), results[u][1].max().max()) for u in geo))),
        "engines": {s: f"data/{f}" for s, f in engines.items()},  # fetched only when a non-default method is chosen
        "engineHash": hashlib.sha1(b"".join((DATA_DIR / f).read_bytes() for f in engines.values())).hexdigest()[:10],  # saved results are keyed by it
        "demoFiles": [f"data/{n}" for n in files if n.startswith("demo/") and not n.startswith("demo/detail_")],
        "details": {s: f"data/demo/detail_{s}.json" for s in units},  # fetched when the demo page zooms in on a system
        "detailStep": GRID_STEP,
        "files": [f"data/{n}" for n in files if n.startswith("full/")],
    }
    DISPLAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    html = TEMPLATE.read_text().replace("__TITLE__", title).replace("__META__", json.dumps(meta, separators=(",", ":")))
    DISPLAY_FILE.write_text(html.replace("../../6_display/car/", "car/"))
    publish_assets()
    size = lambda prefix: sum((DATA_DIR / n).stat().st_size for n in files if n.startswith(prefix)) / 1e6
    print(f"Wrote river pulse page ({DISPLAY_FILE.stat().st_size / 1e6:.2f} MB) for {title}: demo data {size('demo/'):.1f} MB, "
          f"full data {size('full/'):.1f} MB, engines {size('engine_'):.1f} MB, roads {size('roads'):.1f} MB: {DISPLAY_FILE}")


if __name__ == "__main__":
    run_display()
