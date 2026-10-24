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


def _terrain(units, dem):
    """Ground cells inside the modelled units: position, elevation, owning subcatchment and hillshade, plus per-unit stats."""
    minx, miny, maxx, maxy = units.total_bounds
    lons = np.arange(minx, maxx + GRID_STEP, GRID_STEP)
    lats = np.arange(maxy, miny - GRID_STEP, -GRID_STEP)  # north to south
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
    return {"x0": round(float(lons[0]), 4), "y0": round(float(lats[0]), 4), "step": GRID_STEP,
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


def run_display(run=DEFAULT_RUN, methods=(RAINFALL_RUNOFF_MODEL, ROUTING_MODEL)):
    """Write the interactive 'river pulse' page for every SDL unit of DISPLAY_SYSTEMS, from their stored geometry,
    climate and results for one run and method pair."""
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
    dem = Dem(regions.total_bounds)
    reaches, context = _rivers(rivers, river_flow.mean(), dem)
    mids = {r.subcatchment: (r.geometry.centroid if r.geometry.contains(r.geometry.centroid) else r.geometry.representative_point()) for r in regions.itertuples()}
    terrain, stats = _terrain(regions, dem)
    days = climate[next(iter(geo))][1].index.strftime("%Y-%m-%d").tolist()
    evap_index, evap_values = _evap({u: climate[u][3] for u in geo})
    tag, mtag = "_".join(run), "_".join(methods)
    names = {u: SDL_UNITS[u]["name"] for u in geo}
    files = {"geometry.json": {
        "units": [{"id": r.subcatchment, "sdl": r.sdl_unit, "name": r.region_name, "area": round(r.area_km2),
                   "mid": [round(mids[r.subcatchment].x, 4), round(mids[r.subcatchment].y, 4), int(dem.at(mids[r.subcatchment].x, mids[r.subcatchment].y))],
                   "rings": _rings(r.geometry.simplify(0.004), dem), "elev": stats[i]} for i, r in enumerate(regions.itertuples())],
        "terrain": terrain,
        "outline": _rings(regions.geometry.union_all().simplify(0.003), dem),
        "sdlBounds": [{"id": u, "name": names[u], "fullName": geo[u]["outline"]["sdl_name"].iloc[0], "system": s,
                       "mid": _label_point(geo[u]["outline"].geometry.iloc[0], dem),
                       "rings": _rings(geo[u]["outline"].geometry.iloc[0].simplify(0.003), dem)} for s, us in units.items() for u in us],
        "reaches": reaches,
        "context": context,
    }, f"climate_{tag}.json": {"days": days, "evap": evap_index}}
    engines = {}
    for s, us in units.items():
        sub = pd.concat([climate[u][1] for u in us], axis=1)
        sys_regions = regions[regions["sdl_unit"].isin(us)]
        files[f"climate_{s}_{tag}.json"] = {
            "P": {n: sub[f"{n}_P"].round(1).tolist() for n in sys_regions["subcatchment"]},
            "PET": {n: sub[f"{n}_PET"].round(1).tolist() for n in sys_regions["subcatchment"]},
            "evapParts": {u: evap_values[u] for u in us},
        }
        files[f"flow_{s}_{tag}_{mtag}.json"] = {
            "reachFlow": {n: v.round(0).astype(int).tolist() for u in us for n, v in results[u][1].items()},
            "riverFlow": {n: base64.b64encode(np.clip(v.round(0).to_numpy(), 0, 65535).astype("<u2").tobytes()).decode() for u in us for n, v in results[u][2].items()},
            "sdl": {u: {"flow": results[u][0].round(0).astype(int).tolist(), "fish": _table(results[u][3]), "birds": _birds(results[u][4]), "gum": _table(results[u][5])}
                    for u in us},
        }
        basins = pd.concat([geo[u]["basins"] for u in us], ignore_index=True)
        engines[s] = f"engine_{s}_{tag}.json"
        files[engines[s]] = _engine(s, basins, pd.concat([climate[u][2] for u in us], axis=1), sys_regions,
                                    rivers[rivers["sdl_unit"].isin(us)])
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for old in DATA_DIR.rglob("*.json"):  # keep only the build's own files; unchanged content is rewritten byte-for-byte
        if old.relative_to(DATA_DIR).as_posix() not in files:
            old.unlink()
    for d in [d for d in DATA_DIR.iterdir() if d.is_dir() and not any(d.iterdir())]:
        d.rmdir()
    for name, payload in files.items():
        (DATA_DIR / name).write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False))
    title = ", ".join(list(names.values())[:-1]) + " and " + list(names.values())[-1] if len(names) > 1 else next(iter(names.values()))
    meta = {
        "title": title,
        "focus": next(iter(geo)),  # the unit whose outlet flow and ecology the page shows first
        "climate": {"globalModel": run[0], "scenario": run[1], "regionalConfig": run[2],
                    "period": f"{days[0][:4]}–{days[-1][:4]}", "source": "NARCliM2.0", "resolution": "4 km", "frequency": "Daily"},
        "runoff": {"selected": methods[0], "specs": runoff_specs()},
        "routing": {"selected": methods[1], "specs": routing_specs()},
        "run": tag,
        "engines": {s: f"data/{f}" for s, f in engines.items()},  # fetched only when a non-default method is chosen
        "engineHash": hashlib.sha1(b"".join((DATA_DIR / f).read_bytes() for f in engines.values())).hexdigest()[:10],  # saved results are keyed by it
        "files": [f"data/{name}" for name in files if name not in engines.values()],
    }
    DISPLAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    html = TEMPLATE.read_text().replace("__TITLE__", title).replace("__META__", json.dumps(meta, separators=(",", ":"))).replace("__ROADS__", (HERE / "roads.json").read_text())
    DISPLAY_FILE.write_text(html.replace("../../6_display/car/", "car/"))
    publish_assets()
    sizes = {name: (DATA_DIR / name).stat().st_size / 1e6 for name in files}
    print(f"Wrote river pulse page ({DISPLAY_FILE.stat().st_size / 1e6:.2f} MB) for {title} and {len(files)} data files "
          f"({sum(sizes.values()):.1f} MB total, largest {max(sizes, key=sizes.get)} {max(sizes.values()):.1f} MB): {DISPLAY_FILE}")


if __name__ == "__main__":
    run_display()
