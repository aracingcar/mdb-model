"""Fetch the freely downloadable BOM HRS station metadata into data/input/routing.

Run from the repository root with ``python 3_routing/download_public_data.py``.
The HRS page also offers observed daily flow series as per-station downloads;
those are not bulk-published as a simple CSV endpoint. WaterNSW API access
requires a subscription key, so this script deliberately does not automate it.
"""

from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "input" / "routing"
HRS_FILES = {
    "hrs_station_details.csv": "https://www.bom.gov.au/water/hrs/content/hrs_station_details.csv",
    "hrs_station_facts.csv": "https://www.bom.gov.au/water/hrs/content/hrs_station_facts.csv",
}


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    for filename, url in HRS_FILES.items():
        request = Request(url, headers={"User-Agent": "mdb-model public hydrology data downloader"})
        with urlopen(request, timeout=60) as response:
            content = response.read()
        if not content:
            raise RuntimeError(f"Empty response from {url}")
        output = DEST / filename
        output.write_bytes(content)
        print(f"Saved {output.relative_to(ROOT)} ({len(content):,} bytes)")


if __name__ == "__main__":
    main()
