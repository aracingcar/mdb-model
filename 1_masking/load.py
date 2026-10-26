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
    # A 365-day (NorESM2-MM) or 360-day (UKESM1-0-LL) calendar: use real dates, each missing day repeating the one before.
    # A 360-day year is spread evenly over the real year, so its 5 or 6 repeated days fall across the seasons.
    if ds.time.dtype == object:
        ds = ds.convert_calendar("standard", align_on="year" if ds.time.dt.calendar == "360_day" else None)
        ds = ds.reindex(time=pd.date_range(ds.time.values[0], ds.time.values[-1], freq="D"), method="ffill")
    ds["time"] = ds.time.dt.floor("D")  # daily means are stamped at 12:00
    ds = ds.assign_coords(rlon=ds.rlon % 360 - 180)  # into ROTATED_POLE_CRS's half-turned frame, where rlon never wraps
    ds = ds.rio.set_spatial_dims(x_dim="rlon", y_dim="rlat").rio.write_crs(ROTATED_POLE_CRS)
    return ds
