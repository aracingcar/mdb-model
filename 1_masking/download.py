import numpy as np
import xarray as xr

from catchment import load_catchment
from config import (BBOX_MARGIN, NARCLIM_DIR, RLON_CORRECTION_FILE, RUN, RUN_TAG,
                    THREDDS_DODS, VARIABLES, YEARS)


def url(var, year):
    return f"{THREDDS_DODS}/{RUN}/{var}/latest/{var}_{RUN_TAG.replace('_day', '')}_day_{year}0101-{year}1231.nc"


def index_box(ds, bounds):
    """Smallest rlat/rlon index window whose cells fall inside the lon/lat bounds (plus margin)."""
    minx, miny, maxx, maxy = bounds
    m = BBOX_MARGIN
    inside = ((ds.lon >= minx - m) & (ds.lon <= maxx + m) & (ds.lat >= miny - m) & (ds.lat <= maxy + m)).values
    rows, cols = np.where(inside)
    return slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1)


def download():
    """Save each variable-year subset in the configured model/scenario/regional directory."""
    NARCLIM_DIR.mkdir(parents=True, exist_ok=True)
    rlon = np.loadtxt(RLON_CORRECTION_FILE)
    bounds = load_catchment().to_crs("EPSG:4326").total_bounds
    window = None
    for var in VARIABLES:
        for year in YEARS:
            out = NARCLIM_DIR / f"{var}_{year}.nc"
            if out.exists():
                continue
            ds = xr.open_dataset(url(var, year))
            ds = ds.assign_coords(rlon=("rlon", rlon))
            window = window or index_box(ds, bounds)
            sub = ds[[var]].isel(rlat=window[0], rlon=window[1])
            sub.load().to_netcdf(out)
            print("saved", out.name)
