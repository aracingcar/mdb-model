import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import xarray as xr

from catchment import load_catchment
from config import (BBOX_MARGIN, DOWNLOAD_WORKERS, NARCLIM_DIR, RLON_CORRECTION_FILE, RUN, RUN_TAG,
                    THREDDS_DODS, VARIABLES, YEAR_END, YEARS)


def url(var, year):
    return f"{THREDDS_DODS}/{RUN}/{var}/latest/{var}_{RUN_TAG.replace('_day', '')}_day_{year}0101-{year}{YEAR_END}.nc"


def index_box(ds, bounds):
    """Smallest rlat/rlon index window whose cells fall inside the lon/lat bounds (plus margin)."""
    minx, miny, maxx, maxy = bounds
    m = BBOX_MARGIN
    inside = ((ds.lon >= minx - m) & (ds.lon <= maxx + m) & (ds.lat >= miny - m) & (ds.lat <= maxy + m)).values
    rows, cols = np.where(inside)
    return slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1)


def _fetch(job):
    """Save one variable-year subset (a worker process; the netCDF library is not thread-safe)."""
    var, year, out, window, rlon = job
    for attempt in range(4):
        try:
            ds = xr.open_dataset(url(var, year)).assign_coords(rlon=("rlon", rlon))
            part = out.with_suffix(".part")
            # lossless zlib: ~40% less disk (P halves), for a fraction of a second per file
            ds[[var]].isel(rlat=window[0], rlon=window[1]).load().to_netcdf(part, encoding={var: {"zlib": True, "complevel": 1, "shuffle": True}})
            part.replace(out)  # a finished file only ever appears whole
            return out.name
        except OSError:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"could not download {out.name} after 4 attempts")


def download():
    """Save each variable-year subset in the configured model/scenario/regional directory, in parallel."""
    NARCLIM_DIR.mkdir(parents=True, exist_ok=True)
    rlon = np.loadtxt(RLON_CORRECTION_FILE)
    todo = [(var, year, NARCLIM_DIR / f"{var}_{year}.nc") for var in VARIABLES for year in YEARS]
    todo = [job for job in todo if not job[2].exists()]
    if not todo:
        return
    first = xr.open_dataset(url(todo[0][0], todo[0][1])).assign_coords(rlon=("rlon", rlon))
    window = index_box(first, load_catchment().to_crs("EPSG:4326").total_bounds)
    first.close()
    with ProcessPoolExecutor(DOWNLOAD_WORKERS) as pool:
        for i, name in enumerate(pool.map(_fetch, [(*job, window, rlon) for job in todo]), 1):
            print(f"saved {name} ({i}/{len(todo)})", flush=True)
