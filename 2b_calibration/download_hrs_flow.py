"""Download BoM Hydrologic Reference Station (HRS) daily flow for the HRS gauges in each river system.

HRS gauges are unregulated catchments chosen by the Bureau for long-term streamflow study, each with a published catchment
area, so they are the gauges GR4J is calibrated against (2b_calibration/calibrate_gr4j.py). A gauge belongs to a system
if it lies in, or within OUTLINE_BUFFER_KM of, one of the system's model basins (results.db). Needs
data/input/routing/hrs_station_details.csv (python 2b_calibration/download_public_data.py). Writes, per system, to
data/input/routing/: <system>_hrs_flow_daily.csv (long: date, station, flow_ML, qcode) and its _metadata.json.

Run from the repository root with ``python 2b_calibration/download_hrs_flow.py``.
"""
import io
import json
import sys
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "3b_calibration"))

from load_observed_flow import DEST, ROOT, system_gauges
from config import DISPLAY_SYSTEMS

DETAILS = DEST / "hrs_station_details.csv"
URL = "https://www.bom.gov.au/water/hrs/content/data/{id}/{id}_daily_ts.csv"
START = "2012-01-01"  # the observed climate (1_masking/download_awo_climate.py) starts here


def fetch(station):
    request = urllib.request.Request(URL.format(id=station), headers={"User-Agent": "mdb-model public hydrology data downloader"})
    with urllib.request.urlopen(request, timeout=120) as response:
        frame = pd.read_csv(io.BytesIO(response.read()), comment="#")
    frame.columns = ["date", "flow_ML", "qcode"]
    frame = frame[frame["date"] >= START]
    return frame.assign(station=station)[["date", "station", "flow_ML", "qcode"]]


def main():
    details = pd.read_csv(DETAILS, comment="#", dtype={"AWRC Station Number": str})
    details = details.rename(columns={"AWRC Station Number": "station", "Station Name": "name", "Latitude": "lat",
                                      "Longitude": "lon", "Catchment Area (km2)": "area_km2"})
    stations = gpd.GeoDataFrame(details, geometry=gpd.points_from_xy(details.lon, details.lat), crs="EPSG:4326")
    for system in DISPLAY_SYSTEMS:
        gauges = system_gauges(system, stations)
        if gauges.empty:
            print(f"{system}: no HRS gauges")
            continue
        flow =pd.concat([fetch(s) for s in gauges["station"]], ignore_index=True)
        out = DEST / f"{system}_hrs_flow_daily.csv"
        flow.to_csv(out, index=False)
        metadata = {
            "source": "Bureau of Meteorology Hydrologic Reference Stations, daily streamflow (ML/day) with quality codes",
            "source_url": URL.format(id="<station>"),
            "station_details": str(DETAILS.relative_to(ROOT)),
            "dataset_version": "September 2026",
            "quality_codes": {"A": "best available", "B": "good", "C": "poor", "E": "unreliable", "G": "gap filled"},
            "start": START,
            "stations": {
                g.station: {"name": g.name, "lat": g.lat, "lon": g.lon, "area_km2": g.area_km2, "sdl_unit": g.sdl_unit,
                            "basin": g.basin, "days": int((flow["station"] == g.station).sum()),
                            "last_date": flow.loc[flow["station"] == g.station, "date"].max()}
                for g in gauges.itertuples()
            },
            "attribution": "© Commonwealth of Australia (Bureau of Meteorology); Hydrologic Reference Stations, CC BY 4.0.",
        }
        out.with_name(out.stem + "_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"{system}: {len(gauges)} HRS gauges -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
