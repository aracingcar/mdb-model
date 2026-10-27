"""Fetch observed daily mean discharge for gauges in each subcatchment reach from BoM Water Data Online.

Station IDs 410001-410999 and 411001-411100 (the NSW Murrumbidgee numbering) are probed for a location,
kept if inside the valley, and their daily mean discharge (m3/s) downloaded. Writes to data/input/observed_flow/:
stations.csv (gauge, reach, record span), observed_flow_daily.csv (long format) and reach_coverage.csv.
"""
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "1_masking"))

from catchment import load_catchment

DEST = ROOT / "data" / "input" / "observed_flow"
BASE = "https://www.bom.gov.au/waterdata/services"
PARAM = "http://bom.gov.au/waterdata/services/parameters/Water Course Discharge"
DAILY_MEAN = "http://bom.gov.au/waterdata/services/tstypes/Pat4_C_B_1_DailyMean"
STATION = "http://bom.gov.au/waterdata/services/stations/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
CANDIDATES = [*range(410001, 411000), *range(411001, 411101)]
FROM_YEAR, CHUNK_YEARS = 1950, 10


def sos(query, retries=3):
    url = BASE + "?" + urllib.parse.urlencode({"service": "SOS", "version": "2.0", **query}, quote_via=urllib.parse.quote)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                return r.read().decode()
        except Exception:
            if attempt == retries - 1:
                return None
            time.sleep(attempt + 1)


def locate(station):
    """(id, name, lat, lon) for a station ID, or None if BoM has no such station."""
    xml = sos({"request": "GetFeatureOfInterest", "featureOfInterest": STATION + str(station)})
    if not xml or "gml:pos" not in xml:
        return None
    name = re.search(r"<gml:name>([^<]*)</gml:name>", xml).group(1)
    pos = re.search(r"<gml:pos[^>]*>([^<]*)<", xml).group(1).split()
    if len(pos) != 2:
        return None
    return station, name, float(pos[0]), float(pos[1])


def daily_span(station):
    """(first, last) timestamps of the daily-mean discharge series, or None if the gauge has none."""
    xml = sos({"request": "GetDataAvailability", "featureOfInterest": STATION + str(station), "observedProperty": PARAM})
    if not xml:
        return None
    for block in re.findall(r"<gml:TimePeriod.*?</gml:TimePeriod>|<gda:dataAvailabilityMember.*?</gda:dataAvailabilityMember>", xml, re.S):
        if "Pat4_C_B_1_DailyMean" in block:
            begin = re.search(r"beginPosition>([^<]+)<", block)
            end = re.search(r"endPosition>([^<]+)<", block)
            if begin and end:
                return pd.Timestamp(begin.group(1)[:10]), pd.Timestamp(end.group(1)[:10])
    return None


def fetch_daily(station, first, last):
    """Daily mean discharge (m3/s) for a station over its record, fetched in multi-year chunks."""
    rows = []
    start = max(first, pd.Timestamp(f"{FROM_YEAR}-01-01"))
    while start <= last:
        end = min(start + pd.DateOffset(years=CHUNK_YEARS) - pd.Timedelta(days=1), last)
        xml = sos({"request": "GetObservation", "featureOfInterest": STATION + str(station), "observedProperty": PARAM,
                   "procedure": DAILY_MEAN, "temporalFilter": f"om:phenomenonTime,{start:%Y-%m-%d}/{end:%Y-%m-%d}"})
        if xml and "ExceptionReport" not in xml[:2000]:
            for t, v in re.findall(r"<wml2:time>([^<]+)</wml2:time><wml2:value[^>]*?>([^<]*)<", xml):
                try:
                    rows.append((t[:10], float(v)))
                except ValueError:
                    pass
        start = end + pd.Timedelta(days=1)
    return pd.DataFrame(rows, columns=["date", "flow_m3s"]).assign(station=station)


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(10) as pool:
        found = [s for s in pool.map(locate, CANDIDATES) if s]
    stations = gpd.GeoDataFrame(found, columns=["station", "name", "lat", "lon"]).pipe(
        lambda d: d.set_geometry(gpd.points_from_xy(d.lon, d.lat), crs="EPSG:4326"))
    reaches = gpd.read_file(ROOT / "data" / "output" / "murrumbidgee_subcatchments.gpkg")[["subcatchment", "geometry"]]
    inside = gpd.sjoin(stations, reaches, predicate="within").drop(columns=["index_right", "geometry"])
    print(f"{len(found)} stations found, {len(inside)} inside the valley")

    with ThreadPoolExecutor(10) as pool:
        spans = list(pool.map(daily_span, inside["station"]))
    inside["first"] = [s[0] if s else pd.NaT for s in spans]
    inside["last"] = [s[1] if s else pd.NaT for s in spans]
    gauged = inside.dropna(subset=["first"]).copy()
    print(f"{len(gauged)} have daily mean discharge")

    with ThreadPoolExecutor(6) as pool:
        series = list(pool.map(lambda r: fetch_daily(r.station, r.first, r.last), gauged.itertuples()))
    daily = pd.concat(series, ignore_index=True)
    counts = daily.groupby("station").size().rename("days")
    gauged = gauged.join(counts, on="station")
    gauged.sort_values(["subcatchment", "station"]).to_csv(DEST / "stations.csv", index=False)
    daily[["date", "station", "flow_m3s"]].to_csv(DEST / "observed_flow_daily.csv", index=False)

    coverage = (gauged.groupby("subcatchment").agg(gauges=("station", "count"), first=("first", "min"), last=("last", "max"))
                .reindex(reaches["subcatchment"]).fillna({"gauges": 0}).astype({"gauges": int}))
    coverage.to_csv(DEST / "reach_coverage.csv")
    print(coverage.to_string())
    print(f"Wrote {len(daily):,} daily values for {daily.station.nunique()} gauges to {DEST}")


if __name__ == "__main__":
    main()
