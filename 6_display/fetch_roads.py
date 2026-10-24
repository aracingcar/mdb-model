"""Download OpenStreetMap major roads for the display (bbox of the evaporation grid) and write a compact roads.json.

Each road is [class, [lon, lat, lon, lat, ...]] with class 0 = motorway/trunk, 1 = primary, 2 = secondary, 3 = tertiary.
Usage: python3 fetch_roads.py   (OSM data (c) OpenStreetMap contributors, ODbL)
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

BBOX = (-36.6, 143.15, -32.15, 150.05)  # south, west, north, east: the Murrumbidgee, ACT and Lachlan SDL units
CLASS = {"motorway": 0, "trunk": 0, "primary": 1, "secondary": 2, "tertiary": 3}
TOL = {0: 0.0002, 1: 0.0003, 2: 0.0004, 3: 0.0005}  # Douglas-Peucker tolerance in degrees
OUT = Path(__file__).with_name("roads.json")


def simplify(pts, tol):
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = (dx * dx + dy * dy) ** .5 or 1e-12
    k, dmax = 0, 0.0
    for i in range(1, len(pts) - 1):
        d = abs(dy * (pts[i][0] - x1) - dx * (pts[i][1] - y1)) / norm
        if d > dmax:
            k, dmax = i, d
    if dmax <= tol:
        return [pts[0], pts[-1]]
    return simplify(pts[:k + 1], tol)[:-1] + simplify(pts[k:], tol)


def main():
    query = '[out:json][timeout:240];way["highway"~"^(%s)$"](%s);out geom tags;' % ("|".join(CLASS), ",".join(map(str, BBOX)))
    req = urllib.request.Request("https://overpass-api.de/api/interpreter", urllib.parse.urlencode({"data": query}).encode(),
                                 {"User-Agent": "mdb-model-roads/1.0", "Accept": "*/*"})
    ways = json.load(urllib.request.urlopen(req, timeout=300))["elements"]
    roads = []
    for w in ways:
        cls = CLASS[w["tags"]["highway"]]
        pts = simplify([(p["lon"], p["lat"]) for p in w["geometry"]], TOL[cls])
        if len(pts) > 1:
            roads.append([cls, [round(v, 4) for p in pts for v in p]])
    OUT.write_text(json.dumps(roads, separators=(",", ":")))
    print(f"{len(roads)} roads, {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
