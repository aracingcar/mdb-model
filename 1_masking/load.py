import pandas as pd
import xarray as xr
import rioxarray  # noqa: F401  (registers the .rio accessor)

from config import NARCLIM_DIR, ROTATED_POLE_CRS, SECONDS_PER_DAY, VARIABLES


def load_year(year):
    """One year of the saved NARCliM subsets, read into memory; P and PET in mm/day on the rotated-pole grid.

    The 2015-2100 run is reduced a year at a time: the whole 4 km series is several GB per variable, too much for a laptop."""
    arrays = []
    for var, name in VARIABLES.items():
        with xr.open_dataset(NARCLIM_DIR / f"{var}_{year}.nc") as f:
            arrays.append((f[var].load() * SECONDS_PER_DAY).rename(name))
    ds = xr.merge(arrays, compat="override")
    if ds.time.dtype == object:  # a 365-day calendar (NorESM2-MM): use real dates, with each missing 29 February repeating 28 February
        ds = ds.convert_calendar("standard")
        ds = ds.reindex(time=pd.date_range(ds.time.values[0], ds.time.values[-1], freq="D"), method="ffill")
    ds["time"] = ds.time.dt.floor("D")  # daily means are stamped at 12:00
    ds = ds.assign_coords(rlon=ds.rlon % 360 - 180)  # into ROTATED_POLE_CRS's half-turned frame, where rlon never wraps
    ds = ds.rio.set_spatial_dims(x_dim="rlon", y_dim="rlat").rio.write_crs(ROTATED_POLE_CRS)
    return ds
