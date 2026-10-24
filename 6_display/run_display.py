import base64
import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from scipy.ndimage import binary_dilation

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1_masking"))

from config import INPUT, OUTPUT, GLOBAL_MODEL, SCENARIO, REGIONAL_CONFIG
from run_rainfall_runoff import RAINFALL_RUNOFF_MODEL, model_options
from terrain import Dem
from car.build import publish_assets

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
DISPLAY_FILE = OUTPUT / "murrumbidgee_river_pulse.html"
WATERWAYS_FILE = INPUT / "routing" / "osm_murrumbidgee_waterways.geojson"
MAINSTEM = "Murrumbidgee River"
CONTEXT_RIVERS = 120  # longest other named rivers drawn as thin context lines


def _rings(geom, dem=None, ndigits=4):
    """Exterior rings as [lon, lat] points, with the ground elevation (m) as a third value if a DEM is given."""
    out = []
    for p in getattr(geom, "geoms", [geom]):
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
    ways = gpd.read_file(WATERWAYS_FILE)
    ways = ways[(ways.waterway == "river") & (ways.name != "") & (~ways.name.isin(set(rivers["name"])))]
    top = ways.assign(len=ways.length).sort_values("len", ascending=False).head(CONTEXT_RIVERS)
    context = [_rings(g.buffer(0.0025, cap_style=2).simplify(0.001), dem) for g in top.geometry if not g.is_empty]
    return reaches, [r for rings in context for r in rings]


GRID_STEP = 0.01  # degrees (~1 km) for the terrain cells


def _terrain(units, dem):
    """Ground cells inside the valley: position, elevation, owning subcatchment and hillshade, plus per-unit stats."""
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


def run_display(forcing, subcatchments, subcatchment_forcing, evap_grid, flow, reach_flow, rivers, river_flow, fish, waterbirds, river_red_gum):
    """Write one self-contained interactive 'river pulse' page for the modelled Murrumbidgee."""
    units = subcatchments.sort_values("route_order").reset_index(drop=True)
    ids = list(units["subcatchment"])
    dem = Dem(units.total_bounds)
    reaches, context = _rivers(rivers, river_flow.mean(), dem)
    mids = {r.subcatchment: (r.geometry.centroid if r.geometry.contains(r.geometry.centroid) else r.geometry.representative_point()) for r in units.itertuples()}
    terrain, stats = _terrain(units, dem)
    days = subcatchment_forcing.index.strftime("%Y-%m-%d").tolist()
    data = {
        "climate": {"globalModel": GLOBAL_MODEL, "scenario": SCENARIO,
                    "regionalConfig": REGIONAL_CONFIG,
                    "period": f"{days[0][:4]}–{days[-1][:4]}",
                    "source": "NARCliM2.0", "resolution": "4 km", "frequency": "Daily"},
        "runoff": {"selected": RAINFALL_RUNOFF_MODEL, "options": [{"id": i, "label": l} for i, l in model_options()]},
        "days": days,
        "units": [{"id": r.subcatchment, "name": r.region_name, "area": round(r.area_km2), "mid": [round(mids[r.subcatchment].x, 4), round(mids[r.subcatchment].y, 4), int(dem.at(mids[r.subcatchment].x, mids[r.subcatchment].y))],
                   "rings": _rings(r.geometry.simplify(0.004), dem), "elev": stats[i]} for i, r in enumerate(units.itertuples())],
        "terrain": terrain,
        "outline": _rings(units.geometry.union_all().simplify(0.003), dem),
        "evap": {"bbox": [round(v, 4) for v in evap_grid["bbox"]], "nx": evap_grid["nx"], "ny": evap_grid["ny"], "dates": evap_grid["dates"],
                 "scale": evap_grid["scale"], "cells": int(evap_grid["values"].shape[1]),
                 "values": base64.b64encode(evap_grid["values"].tobytes()).decode(),
                 "idx": base64.b64encode(np.where(evap_grid["idx"] < 0, 65535, evap_grid["idx"]).astype("<u2").tobytes()).decode(),
                 "weights": base64.b64encode(np.round(evap_grid["weights"] * 255).astype("uint8").tobytes()).decode()},
        "reaches": reaches,
        "context": context,
        "P": {n: subcatchment_forcing[f"{n}_P"].round(1).tolist() for n in ids},
        "PET": {n: subcatchment_forcing[f"{n}_PET"].round(1).tolist() for n in ids},
        "reachFlow": {n: reach_flow[n].round(0).astype(int).tolist() for n in ids},
        "riverFlow": {n: base64.b64encode(np.clip(river_flow[n].round(0).to_numpy(), 0, 65535).astype("<u2").tobytes()).decode() for n in river_flow.columns},
        "flow": flow.round(0).astype(int).tolist(),
        "fish": fish.reset_index().round(3).to_dict("list"),
        "birds": waterbirds.reset_index().assign(trigger_date=lambda d: d.trigger_date.astype(str)).to_dict("list"),
        "gum": river_red_gum.reset_index().round(3).to_dict("list"),
    }
    DISPLAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    html = TEMPLATE.read_text().replace("__DATA__", json.dumps(data, separators=(",", ":"))).replace("__ROADS__", (HERE / "roads.json").read_text())
    car_path = Path(os.path.relpath(HERE / "car", DISPLAY_FILE.parent)).as_posix() + "/"
    DISPLAY_FILE.write_text(html.replace("../../6_display/car/", car_path))
    publish_assets()
    public_html = html.replace("../../6_display/car/", "car/")
    (HERE.parent / "docs" / "index.html").write_text(public_html)
    print(f"Wrote river pulse page ({DISPLAY_FILE.stat().st_size / 1e6:.1f} MB): {DISPLAY_FILE}")
