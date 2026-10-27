"""Download the Bureau of Meteorology storage gauges (dams, reservoirs, weirs, lagoons) that fall in the modelled area and write a compact storages.json.

Each storage is [name, lon, lat]. Only gauges that report Storage Volume are kept (that drops ponds and pool-level gauges); gauges within MERGE_KM of each other
belong to the same storage and are shown once, under the first of them in name priority (a gauge named "dam" first).
Usage: python downloads/fetch_storages.py   (BoM Water Data Online SOS 2.0, no key needed)
"""
import json
import math
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "6_display"  # storages.json is written beside the display build
SERVICE = "https://www.bom.gov.au/waterdata/services"
PROPERTY = "http://bom.gov.au/waterdata/services/parameters/Storage%20Volume"
GML = {"gml": "http://www.opengis.net/gml/3.2"}
MERGE_KM = 5.0
# gauges that are not a storage of their own: inflow channels, a second gauge on one dam, a Melbourne supply gauge, urban ponds
DROP = {"INFLOW @ EASTERNSPIL", "Dartmouth", "TYABB MR WR144", "Gungahlin Pond", "Swampy-Khancbn Pond", "Lake Victoria at Outlet Regulator",
        "MENINDEE@COPI HOLLOW", "L PAMARAROO   COPI H", "OUTEASTERN@LAKE BREW", "OUTWESTERN@LAKEBREWS"}
RENAME = {"L WETHERELL TANDURE": "Lake Wetherell", "Geehi at Geehi Res": "Geehi Reservoir", "Tooma at Tooma Res": "Tooma Reservoir"}
OUT = HERE / "storages.json"


def fetch():
    url = f"{SERVICE}?service=SOS&version=2.0&request=GetFeatureOfInterest&observedProperty={PROPERTY}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/124.0"})
            return ET.fromstring(urllib.request.urlopen(req, timeout=120).read())
        except OSError:
            time.sleep(2 * (attempt + 1))
    raise SystemExit("BoM did not answer")


def inside(lon, lat, ring):  # ray casting
    hit = False
    for (x1, y1, *_), (x2, y2, *_) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def tidy(name):  # "Corin Res. at Dam" -> "Corin Res.", "TANTANGARA DAM RL" -> "Tantangara Dam"
    if name in RENAME:
        return RENAME[name]
    name = re.sub(r"\s+(at Dam|RL|- RO)$", "", name.strip(), flags=re.I)
    return name.title() if name.isupper() else name


def km(a, b):
    return math.hypot((a[1] - b[1]) * 111.32 * math.cos(math.radians(a[2])), (a[2] - b[2]) * 110.57)


def main():
    ring = json.loads((HERE.parent / "docs/data/full/geometry.json").read_text())["outlineBuffer"][0]
    found = []
    for member in fetch():
        pos = member.find(".//gml:pos", GML)
        if pos is None or not pos.text:
            continue
        lat, lon = map(float, pos.text.split())
        name = member.find(".//gml:name", GML).text.strip()
        if name not in DROP and inside(lon, lat, ring):
            found.append((name, lon, lat))
    found.sort(key=lambda s: ("dam" not in s[0].lower(), s[0]))  # a gauge named for the dam wall represents its storage
    storages = []
    for s in found:
        if all(km(s, t) > MERGE_KM for t in storages):
            storages.append(s)
    out = sorted([tidy(n), round(lon, 4), round(lat, 4)] for n, lon, lat in storages)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"{len(found)} gauges in the modelled area, {len(out)} storages: {OUT}")


if __name__ == "__main__":
    main()
