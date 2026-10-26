"""Copy quality-filtered daily gauge flow for each river system's model basins from the mdb-river-pulse store.

The user's ``mdb-river-pulse/data/river.db`` holds BoM Water Data Online daily mean discharge (DMQaQc series), filtered
for good quality. A gauge belongs to a system if it lies in, or within OUTLINE_BUFFER_KM of, one of the system's model
basins (as stored in results.db, so run main.py first); it is tagged with the nearest basin. Writes, per system, to
data/input/routing/: <system>_observed_flow_daily.csv (wide, m3/s, blank days kept) and its _metadata.json.

Run from the repository root with ``python 3_routing/load_observed_flow.py [path/to/river.db]``.
"""
import json
import sqlite3
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "1_masking"), str(ROOT / "5_outputs")]

from config import DISPLAY_SYSTEMS, OUTLINE_BUFFER_CRS, OUTLINE_BUFFER_KM, SYSTEMS
from results_db import load_geometry

RIVER_DB = ROOT.parent / "mdb-river-pulse" / "data" / "river.db"
DEST = ROOT / "data" / "input" / "routing"


def load_gauges(db_path):
    """(stations GeoDataFrame, wide daily flow in m3/s) for every flow gauge in the river-pulse store."""
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        stations = pd.read_sql("SELECT id AS station, name, lat, lon FROM stations WHERE id IN "
                               "(SELECT DISTINCT station FROM daily_obs WHERE param='flow')", db)
        obs = pd.read_sql("SELECT station, ts, value, unit FROM daily_obs WHERE param='flow'", db)
    if set(obs["unit"]) != {"cumec"}:
        raise RuntimeError(f"Expected flow in cumec, found {sorted(set(obs['unit']))}")
    obs["date"] = pd.to_datetime(obs["ts"], unit="s").dt.normalize()
    flow = obs.pivot_table(index="date", columns="station", values="value", aggfunc="mean")
    stations = stations.dropna(subset=["lat", "lon"])
    return gpd.GeoDataFrame(stations, geometry=gpd.points_from_xy(stations.lon, stations.lat), crs="EPSG:4326"), flow


def system_gauges(system, stations):
    """The stations near the system's model basins, with the nearest basin and its SDL unit."""
    basins = pd.concat([load_geometry(u, "basins") for u in SYSTEMS[system]["units"]])
    if basins.empty:
        raise RuntimeError(f"No basins stored for {system}: run main.py first")
    basins = gpd.GeoDataFrame(basins[["subcatchment", "sdl_unit", "geometry"]], crs="EPSG:4326").to_crs(OUTLINE_BUFFER_CRS)
    near = gpd.sjoin_nearest(stations.to_crs(OUTLINE_BUFFER_CRS), basins, max_distance=OUTLINE_BUFFER_KM * 1000, distance_col="distance_m")
    near = near.sort_values("distance_m").drop_duplicates("station")  # a gauge on a basin border joins every touching basin
    return near.rename(columns={"subcatchment": "basin"}).sort_values("station")


def main():
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else RIVER_DB
    stations, flow = load_gauges(db_path)
    print(f"{len(stations)} located flow gauges, {flow.index.min():%Y-%m-%d} to {flow.index.max():%Y-%m-%d}")
    for system in DISPLAY_SYSTEMS:
        gauges = system_gauges(system, stations)
        series = flow[gauges["station"]].dropna(how="all")
        out = DEST / f"{system}_observed_flow_daily.csv"
        series.rename_axis("date").to_csv(out, date_format="%Y-%m-%d")
        metadata = {
            "source": "User-provided quality-filtered Bureau of Meteorology daily mean observations from mdb-river-pulse/data/river.db.",
            "source_project_readme": str(db_path.parent.parent / "README.md"),
            "record_table": "daily_obs",
            "parameter": "flow",
            "units": "m3/s (cumec)",
            "selection": f"gauges in, or within {OUTLINE_BUFFER_KM} km of, the system's model basins (results.db); basin is the nearest one",
            "period": {"start": f"{series.index.min():%Y-%m-%d}", "end": f"{series.index.max():%Y-%m-%d}", "daily_rows": len(series)},
            "stations": {
                g.station: {"name": g.name, "lat": g.lat, "lon": g.lon, "sdl_unit": g.sdl_unit, "basin": g.basin,
                            "units": "m3/s", "valid_daily_values": int(series[g.station].notna().sum()),
                            "first_date": f"{series[g.station].first_valid_index():%Y-%m-%d}",
                            "last_date": f"{series[g.station].last_valid_index():%Y-%m-%d}"}
                for g in gauges.itertuples()
            },
            "notes": [
                "Blank cells preserve days with no recorded value; they are not interpolated.",
                "The user confirmed these source records have been filtered for good quality.",
                "Gauges on regulated rivers reflect dam releases, diversions and weirs as well as runoff.",
                "A gauge within the buffer of two systems is listed in both.",
            ],
        }
        out.with_name(out.stem + "_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"{system}: {len(gauges)} gauges -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
