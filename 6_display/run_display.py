import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1_masking"))

from config import INPUT
from terrain import Dem, hillshade

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
DISPLAY_FILE = HERE.parent / "data" / "output" / "murrumbidgee_river_pulse.html"
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


def _rivers(subcatchments, reach_mean, dem):
    """Per-reach main-stem ribbons (width grows with mean flow) and thin context lines for other rivers."""
    ways = gpd.read_file(WATERWAYS_FILE)
    ways = ways[ways.waterway == "river"]
    stem = ways[ways.name == MAINSTEM]
    others = ways[(ways.name != MAINSTEM) & (ways.name != "")]
    top = others.assign(len=others.length).sort_values("len", ascending=False).head(CONTEXT_RIVERS)

    peak = max(reach_mean.values())
    reaches, mids = [], {}
    for unit in subcatchments.itertuples():
        line = stem.geometry.intersection(unit.geometry).union_all()
        centre = unit.geometry.centroid
        mids[unit.subcatchment] = centre if unit.geometry.contains(centre) else unit.geometry.representative_point()
        if line.is_empty:
            continue
        width = 0.004 + 0.010 * np.sqrt(reach_mean[unit.subcatchment] / peak)
        ribbon = line.buffer(width, cap_style=2, join_style=2).simplify(0.001)
        reaches.append({"unit": unit.subcatchment, "rings": _rings(ribbon, dem)})
    context = [_rings(g.buffer(0.0025, cap_style=2).simplify(0.001), dem) for g in top.geometry if not g.is_empty]
    return reaches, [r for rings in context for r in rings], mids


GRID_STEP = 0.01  # degrees (~1 km) for the terrain cells


def _terrain(units, dem):
    """Ground cells inside the valley: position, elevation, owning subcatchment and hillshade, plus per-unit stats."""
    minx, miny, maxx, maxy = units.total_bounds
    lons = np.arange(minx, maxx + GRID_STEP, GRID_STEP)
    lats = np.arange(maxy, miny - GRID_STEP, -GRID_STEP)  # north to south
    gx, gy = np.meshgrid(lons, lats)
    elev = dem.at(gx, gy)
    shade = hillshade(elev, GRID_STEP, (miny + maxy) / 2)
    owner = np.full(gx.shape, -1)
    for i, geom in enumerate(units.geometry):
        owner[shapely.contains_xy(geom, gx, gy)] = i
    rows, cols = np.nonzero(owner >= 0)
    stats = []
    for i in range(len(units)):
        e = elev[owner == i]
        stats.append({"mean": int(e.mean()), "min": int(e.min()), "max": int(e.max())} if e.size else {"mean": 0, "min": 0, "max": 0})
    return {"x0": round(float(lons[0]), 4), "y0": round(float(lats[0]), 4), "step": GRID_STEP,
            "col": cols.tolist(), "row": rows.tolist(), "elev": np.round(elev[rows, cols]).astype(int).tolist(),
            "unit": owner[rows, cols].tolist(), "shade": np.round(shade[rows, cols] * 100).astype(int).tolist()}, stats


def run_display(forcing, subcatchments, subcatchment_forcing, flow, reach_flow, fish, waterbirds, river_red_gum):
    """Write one self-contained interactive 'river pulse' page for the modelled Murrumbidgee."""
    units = subcatchments.sort_values("route_order").reset_index(drop=True)
    ids = list(units["subcatchment"])
    dem = Dem(units.total_bounds)
    reaches, context, mids = _rivers(units, reach_flow.mean().to_dict(), dem)
    terrain, stats = _terrain(units, dem)
    days = subcatchment_forcing.index.strftime("%Y-%m-%d").tolist()
    data = {
        "days": days,
        "units": [{"id": r.subcatchment, "name": r.region_name, "area": round(r.area_km2), "mid": [round(mids[r.subcatchment].x, 4), round(mids[r.subcatchment].y, 4), int(dem.at(mids[r.subcatchment].x, mids[r.subcatchment].y))],
                   "rings": _rings(r.geometry.simplify(0.004), dem), "elev": stats[i]} for i, r in enumerate(units.itertuples())],
        "terrain": terrain,
        "reaches": reaches,
        "context": context,
        "P": {n: subcatchment_forcing[f"{n}_P"].round(1).tolist() for n in ids},
        "PET": {n: subcatchment_forcing[f"{n}_PET"].round(1).tolist() for n in ids},
        "reachFlow": {n: reach_flow[n].round(0).astype(int).tolist() for n in ids},
        "flow": flow.round(0).astype(int).tolist(),
        "fish": fish.reset_index().round(3).to_dict("list"),
        "birds": waterbirds.reset_index().assign(trigger_date=lambda d: d.trigger_date.astype(str)).to_dict("list"),
        "gum": river_red_gum.reset_index().round(3).to_dict("list"),
    }
    DISPLAY_FILE.parent.mkdir(parents=True, exist_ok=True)
    DISPLAY_FILE.write_text(TEMPLATE.read_text().replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    print(f"Wrote river pulse page ({DISPLAY_FILE.stat().st_size / 1e6:.1f} MB): {DISPLAY_FILE}")
