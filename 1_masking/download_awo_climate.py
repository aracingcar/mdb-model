"""Download BoM AWO daily precipitation and reference PET for model regions.

The BoM Australian Water Outlook image service is sampled at its 0.05 degree
grid-cell centres. Values are combined into area-weighted daily means for the
model basins of a river system (SYSTEM, default murrumbidgee; the basins stored in results.db, so run main.py
first), named and ordered like the model's basin forcing. This is observed climate for calibrating against gauged
flow, which the NARCliM projections cannot be. The archive service supplies 2012-2025; the current service supplies
2026 onward.

Run from the repository root with ``SYSTEM=<system> python 1_masking/download_awo_climate.py``.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import gzip
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import sys

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from config import SYSTEM_ID, UNITS


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "5_outputs"))

from results_db import load_geometry

OUT_DIR = ROOT / "data/input/climate"
OUT_CSV = OUT_DIR / f"{SYSTEM_ID}_basin_P_PET_2012_2026.csv"
OUT_META = OUT_DIR / f"{SYSTEM_ID}_basin_P_PET_2012_2026_metadata.json"

SERVICE_ROOT = "https://image-stg.wsapi-stg.cloud.bom.gov.au/arcgis/rest/services/awra_historical"
ARCHIVE = SERVICE_ROOT + "/physical_day_crf_multivariable_archive_2005_2019_data/ImageServer/getSamples"
LATEST = SERVICE_ROOT + "/physical_day_crf_multivariable_latest_data/ImageServer/getSamples"

START = dt.date(2012, 1, 1)
ARCHIVE_END = dt.date(2025, 12, 31)
LATEST_END = dt.date(2026, 10, 19)  # Last date available in the observed-flow store.
VARIABLES = {"rain_day": "P", "fao_pet": "PET"}
GRID_SIZE = 0.05
SAMPLES_PER_REGION = 10
BATCH_SIZE = SAMPLES_PER_REGION
WORKERS = 2


def epoch_ms(day: dt.date) -> int:
    return int(dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc).timestamp() * 1000)


def make_grid_points(regions: gpd.GeoDataFrame):
    """Return spatially distributed grid centres with represented-area weights."""
    point_rows: list[dict] = []
    for _, region in regions.iterrows():
        geom = region.geometry
        minx, miny, maxx, maxy = geom.bounds
        ilo = max(0, math.floor((minx - 112.0) / GRID_SIZE) - 1)
        ihi = min(840, math.ceil((maxx - 112.0) / GRID_SIZE) + 1)
        jlo = max(0, math.floor((miny + 44.0) / GRID_SIZE) - 1)
        jhi = min(680, math.ceil((maxy + 44.0) / GRID_SIZE) + 1)
        cells = []
        for i in range(ilo, ihi + 1):
            lon = round(112.0 + GRID_SIZE * i, 3)
            for j in range(jlo, jhi + 1):
                lat = round(-44.0 + GRID_SIZE * j, 3)
                if geom.covers(Point(lon, lat)):
                    cells.append((lon, lat, math.cos(math.radians(lat))))
        if not cells:  # a basin smaller than a cell: the cell holding a point inside it
            inside = geom.representative_point()
            lon, lat = (round(112.0 + GRID_SIZE * round((inside.x - 112.0) / GRID_SIZE), 3),
                        round(-44.0 + GRID_SIZE * round((inside.y + 44.0) / GRID_SIZE), 3))
            cells.append((lon, lat, math.cos(math.radians(lat))))

        # Farthest-point selection spreads representative cells over the region.
        # Each selected cell represents the area-weighted cluster of all cells
        # nearest to it, giving a compact approximation of the zonal mean.
        cell_array = np.asarray(cells, dtype=np.float64)
        lat_ref = float(np.average(cell_array[:, 1], weights=cell_array[:, 2]))
        xy = np.column_stack((cell_array[:, 0] * math.cos(math.radians(lat_ref)), cell_array[:, 1]))
        centroid = np.average(xy, axis=0, weights=cell_array[:, 2])
        selected = [int(np.argmin(((xy - centroid) ** 2).sum(axis=1)))]
        while len(selected) < min(SAMPLES_PER_REGION, len(cells)):
            distances = np.sqrt(((xy[:, None, :] - xy[selected][None, :, :]) ** 2).sum(axis=2)).min(axis=1)
            distances[selected] = -1
            selected.append(int(np.argmax(distances)))
        assignments = np.sqrt(((xy[:, None, :] - xy[selected][None, :, :]) ** 2).sum(axis=2)).argmin(axis=1)
        for sample_i, cell_i in enumerate(selected):
            mask = assignments == sample_i
            total_weight = float(cell_array[mask, 2].sum())
            lon, lat = float(cell_array[cell_i, 0]), float(cell_array[cell_i, 1])
            point_rows.append({
                "lon": lon,
                "lat": lat,
                "region": region["subcatchment"],
                "weight": total_weight,
                "represented_cells": int(mask.sum()),
            })
    if not point_rows:
        raise RuntimeError("No BoM grid cells intersect the configured model regions")
    return point_rows


def request_batch(service: str, variable: str, points: list[dict], start: dt.date, end: dt.date):
    geometry = {"points": [[p["lon"], p["lat"]] for p in points], "spatialReference": {"wkid": 4326}}
    mosaic_rule = {
        "multidimensionalDefinition": [{
            "variableName": variable,
            "dimensionName": "StdTime",
            "values": [[epoch_ms(start), epoch_ms(end)]],
            "isSlice": False,
        }]
    }
    params = {
        "geometry": json.dumps(geometry, separators=(",", ":")),
        "geometryType": "esriGeometryMultipoint",
        "returnGeometry": "false",
        "returnFirstValueOnly": "false",
        "mosaicRule": json.dumps(mosaic_rule, separators=(",", ":")),
        "f": "json",
    }
    request = urllib.request.Request(
        service + "?" + urllib.parse.urlencode(params),
        headers={"Accept-Encoding": "gzip", "User-Agent": "mdb-model climate data preparation"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            result = json.loads(body)
            if result.get("error"):
                raise RuntimeError(f"BoM API error: {result['error']}")
            return result.get("samples", [])
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Unreachable")


def accumulate(samples, points, variable, start, end, regions, sums, weights):
    # Accumulators are indexed from the overall output start, even when samples
    # come from the 2026 service window.
    date0 = START.toordinal()
    region_index = {name: i for i, name in enumerate(regions)}
    for sample in samples:
        loc = int(sample["locationId"])
        attrs = sample["attributes"]
        value = float(attrs.get(variable, sample.get("value", "nan")))
        timestamp = int(attrs["StdTime"])
        day = dt.datetime.fromtimestamp(timestamp / 1000, tz=dt.timezone.utc).date()
        if not start <= day <= end or not math.isfinite(value) or value < 0:
            continue
        point = points[loc]
        dindex = day.toordinal() - date0
        rindex = region_index[point["region"]]
        weight = point["weight"]
        sums[dindex, rindex] += value * weight
        weights[dindex, rindex] += weight


def download_variable(variable, label, points, dates, regions):
    sums = np.zeros((len(dates), len(regions)), dtype=np.float64)
    weights = np.zeros_like(sums)
    all_batches = [points[i : i + BATCH_SIZE] for i in range(0, len(points), BATCH_SIZE)]
    jobs = []
    for batch in all_batches:
        jobs.append((ARCHIVE, batch, START, ARCHIVE_END))
        jobs.append((LATEST, batch, dt.date(2026, 1, 1), LATEST_END))
    print(f"{label}: querying {len(jobs)} batches from BoM AWO", flush=True)
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        future_map = {
            pool.submit(request_batch, service, variable, batch, start, end): (batch, start, end)
            for service, batch, start, end in jobs
        }
        for future in concurrent.futures.as_completed(future_map):
            batch, start, end = future_map[future]
            samples = future.result()
            accumulate(samples, batch, variable, start, end, regions, sums, weights)
            done += 1
            if done % 10 == 0 or done == len(jobs):
                print(f"{label}: {done}/{len(jobs)} batches", flush=True)
    means = np.divide(sums, weights, out=np.full_like(sums, np.nan), where=weights > 0)
    return means, weights


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    regions_gdf = gpd.GeoDataFrame(pd.concat([load_geometry(u, "basins") for u in UNITS]), crs="EPSG:4326")
    if regions_gdf.empty:
        raise RuntimeError(f"No basins stored for {SYSTEM_ID}: run main.py first")
    regions = regions_gdf["subcatchment"].tolist()
    points = make_grid_points(regions_gdf)
    dates = pd.date_range(START, LATEST_END, freq="D")

    values = {}
    coverage = {}
    for variable, label in VARIABLES.items():
        means, valid_weights = download_variable(variable, label, points, dates, regions)
        for j, region in enumerate(regions):
            values[f"{region}_{label}"] = means[:, j]
            coverage[f"{region}_{label}_valid_days"] = int((valid_weights[:, j] > 0).sum())

    result = pd.DataFrame(values, index=dates)
    result.index.name = "date"
    result.to_csv(OUT_CSV, float_format="%.4f")
    metadata = {
        "source": "Bureau of Meteorology Australian Water Outlook (AWO), AWRA-L historical daily gridded service",
        "service_archive": ARCHIVE.split("/ImageServer")[0],
        "service_latest": LATEST.split("/ImageServer")[0],
        "variables": {
            "P": {"source_variable": "rain_day", "units": "mm/day", "description": "AWO gridded precipitation"},
            "PET": {"source_variable": "fao_pet", "units": "mm/day", "description": "FAO56 short-crop reference potential evapotranspiration"},
        },
        "start_date": START.isoformat(),
        "end_date": LATEST_END.isoformat(),
        "grid_resolution_degrees": GRID_SIZE,
        "area_weighting": "Within each model region, 10 spatially distributed 0.05-degree cell centres represent clusters of all in-region grid cells; each representative is weighted by the cluster's summed cos(latitude) cell-area factors.",
        "system": SYSTEM_ID,
        "region_source": f"model basins of SDL units {', '.join(UNITS)} (results.db geometry table)",
        "regions": regions,
        "sampled_grid_cell_count": len(points),
        "full_grid_cell_count_represented": int(sum(p["represented_cells"] for p in points)),
        "valid_day_counts_by_region_variable": coverage,
        "limitations": [
            "AWO precipitation and PET are gridded model products, not raw gauge observations.",
            "Ten representative cells per region approximate the full grid-cell area-weighted mean; this is not a pixel-exact polygon zonal statistic.",
            "Basins are the HydroBASINS-derived model basins at download time; rerun this script if the system's basins change.",
        ],
        "downloaded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "attribution": "© Commonwealth of Australia (Bureau of Meteorology) 2022; Australian Water Outlook / AWRA-L.",
    }
    OUT_META.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Saved {OUT_CSV} ({len(result)} daily rows, {len(regions)} regions)", flush=True)
    print(f"Saved metadata {OUT_META}", flush=True)
    print("Missing values by variable:", result.isna().sum().to_dict(), flush=True)


if __name__ == "__main__":
    main()
