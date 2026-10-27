"""Fetch and clip OpenStreetMap waterways for a river system's SDL units (SYSTEM, default murrumbidgee).

Run from the project root with ``python 3a_routing/download_osm_waterways.py``.
The output is a clipped GeoJSON extract; the raw Overpass response is kept in
memory. An optional ``--source`` path processes an existing Overpass JSON file.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import geopandas as gpd
from shapely.geometry import LineString, mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "1_masking"))

from catchment import load_buffered_catchment
from config import OUTLINE_BUFFER_KM, SYSTEM_ID, UNITS, WATERWAYS_FILE as OUT

METADATA = OUT.with_name(OUT.stem + "_metadata.json")
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
            "User-Agent": "mdb-model/1.0 (Murray-Darling Basin rainfall-runoff research)",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    for attempt in range(5):  # the public Overpass server answers 429/502/504 when busy
        try:
            with urlopen(req, timeout=240) as response:
                return json.loads(response.read())
        except HTTPError as e:
            if e.code not in (429, 502, 503, 504) or attempt == 4:
                raise
            print(f"Overpass busy ({e.code}), retrying in {30 * (attempt + 1)} s")
            time.sleep(30 * (attempt + 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="existing Overpass JSON response (skip download)")
    args = parser.parse_args()

    boundary = load_buffered_catchment()  # the SDL outlines grown by OUTLINE_BUFFER_KM, so border rivers are not cut
    catchment = gpd.GeoDataFrame(geometry=[boundary], crs="EPSG:4326")
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
    collection = {"type": "FeatureCollection", "name": f"{SYSTEM_ID} OSM waterways", "features": features}
    OUT.write_text(json.dumps(collection, separators=(",", ":")))
    metadata = {
        "source": "OpenStreetMap contributors via Overpass API",
        "endpoint": OVERPASS,
        "query": 'way[waterway~"^(river|stream|canal|drain|ditch)$"] within catchment bounding box, ' f"clipped to MDBA SDL resource units {', '.join(UNITS)} grown by {OUTLINE_BUFFER_KM} km",
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
