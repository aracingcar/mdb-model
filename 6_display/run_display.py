import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import mapping

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1_masking"))

from config import INPUT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
DISPLAY_FILE = HERE.parent / "data" / "output" / "murrumbidgee_river_pulse.html"
WATERWAYS_FILE = INPUT / "routing" / "osm_murrumbidgee_waterways.geojson"
MAINSTEM = "Murrumbidgee River"
CONTEXT_RIVERS = 120  # longest other named rivers drawn as thin context lines


def _rings(geom, ndigits=4):
    polys = getattr(geom, "geoms", [geom])
    return [[[round(x, ndigits), round(y, ndigits)] for x, y in p.exterior.coords] for p in polys if not p.is_empty]


def _rivers(subcatchments, reach_mean):
    """Per-reach main-stem ribbons (width grows with mean flow) and thin context lines for other rivers."""
    ways = gpd.read_file(WATERWAYS_FILE)
    ways = ways[ways.waterway == "river"]
    stem = ways[ways.name == MAINSTEM]
    others = ways[(ways.name != MAINSTEM) & (ways.name != "")]
    top = others.assign(len=others.length).sort_values("len", ascending=False).head(CONTEXT_RIVERS)

    peak = max(reach_mean.values())
    reaches = []
    for unit in subcatchments.itertuples():
        line = stem.geometry.intersection(unit.geometry).union_all()
        if line.is_empty:
            continue
        width = 0.004 + 0.010 * np.sqrt(reach_mean[unit.subcatchment] / peak)
        ribbon = line.buffer(width, cap_style=2, join_style=2).simplify(0.001)
        reaches.append({"unit": unit.subcatchment, "rings": _rings(ribbon)})
    context = [_rings(g.buffer(0.0025, cap_style=2).simplify(0.001)) for g in top.geometry if not g.is_empty]
    return reaches, [r for rings in context for r in rings]


def run_display(forcing, subcatchments, subcatchment_forcing, flow, reach_flow, fish, waterbirds, river_red_gum):
    """Write one self-contained interactive 'river pulse' page for the modelled Murrumbidgee."""
    units = subcatchments.sort_values("route_order").reset_index(drop=True)
    ids = list(units["subcatchment"])
    reaches, context = _rivers(units, reach_flow.mean().to_dict())
    days = subcatchment_forcing.index.strftime("%Y-%m-%d").tolist()
    data = {
        "days": days,
        "units": [{"id": r.subcatchment, "name": r.region_name, "area": round(r.area_km2),
                   "rings": _rings(r.geometry.simplify(0.004))} for r in units.itertuples()],
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
