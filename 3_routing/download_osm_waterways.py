"""Fetch and clip OpenStreetMap waterways for the Murrumbidgee valley.

Run from the project root with ``python 3_routing/download_osm_waterways.py``.
The output is a clipped GeoJSON extract; the raw Overpass response is kept in
memory. An optional ``--source`` path processes an existing Overpass JSON file.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import geopandas as gpd
from shapely.geometry import LineString, mapping


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "input" / "routing" / "osm_murrumbidgee_waterways.geojson"
METADATA = ROOT / "data" / "input" / "routing" / "osm_murrumbidgee_waterways_metadata.json"
OVERPASS = "https://overpass-api.de/api/interpreter"


def get_overpass_data(catchment):
    west, south, east, north = catchment.total_bounds
    query = (
        '[out:json][timeout:180];'
        f'(way["waterway"~"^(river|stream|canal|drain|ditch)$"]'
        f'({south},{west},{north},{east}););out geom;'
    )
    req = Request(
        OVERPASS,
        data=urlencode({"data": query}).encode(),
        headers={
            "User-Agent": "mdb-model/1.0 (Murrumbidgee rainfall-runoff research)",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urlopen(req, timeout=240) as response:
        return json.loads(response.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="existing Overpass JSON response (skip download)")
    args = parser.parse_args()

    import sys

    sys.path.insert(0, str(ROOT / "1_masking"))
    from catchment import load_catchment

    catchment = load_catchment().to_crs("EPSG:4326")
    boundary = catchment.geometry.union_all()
    data = json.loads(args.source.read_text()) if args.source else get_overpass_data(catchment)

    features = []
    for element in data.get("elements", []):
        coords = element.get("geometry", [])
        if element.get("type") != "way" or len(coords) < 2:
            continue
        line = LineString([(coord["lon"], coord["lat"]) for coord in coords])
        if not line.is_valid or not line.intersects(boundary):
            continue
        clipped = line.intersection(boundary)
        if clipped.is_empty:
            continue
        tags = element.get("tags", {})
        features.append({
            "type": "Feature",
            "id": f"way/{element['id']}",
            "properties": {
                "osm_id": int(element["id"]),
                "name": tags.get("name", ""),
                "waterway": tags.get("waterway", ""),
                "tags": tags,
            },
            "geometry": mapping(clipped),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    collection = {"type": "FeatureCollection", "name": "Murrumbidgee OSM waterways", "features": features}
    OUT.write_text(json.dumps(collection, separators=(",", ":")))
    metadata = {
        "source": "OpenStreetMap contributors via Overpass API",
        "endpoint": OVERPASS,
        "query": 'way[waterway~"^(river|stream|canal|drain|ditch)$"] within catchment bounding box, clipped to CEWO Murrumbidgee valley polygon',
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "elements_in_response": len(data.get("elements", [])),
        "features_after_clip": len(features),
        "output": str(OUT.relative_to(ROOT)),
        "attribution": "© OpenStreetMap contributors",
        "license": "Open Database License (ODbL) 1.0",
        "license_url": "https://www.openstreetmap.org/copyright",
    }
    METADATA.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Saved {len(features):,} clipped waterway features to {OUT}")
    print(f"Saved source metadata to {METADATA}")


if __name__ == "__main__":
    main()
