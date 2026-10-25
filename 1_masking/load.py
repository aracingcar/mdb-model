import numpy as np
import xarray as xr
import rioxarray  # noqa: F401  (registers the .rio accessor)

from config import NARCLIM_DIR, ROTATED_POLE_CRS, SECONDS_PER_DAY, VARIABLES


def load_narclim():
    """Open the saved NARCliM subsets; return P and PET in mm/day on the rotated-pole grid."""
    arrays = []
    for var, name in VARIABLES.items():
        files = sorted(NARCLIM_DIR.glob(f"{var}_*.nc"))
        da = xr.open_mfdataset(files, combine="by_coords")[var] * SECONDS_PER_DAY
        arrays.append(da.rename(name))
    ds = xr.merge(arrays)
    if ds.time.dtype == object:  # a 365-day calendar (NorESM2-MM): use real dates, and fill each missing 29 February from its neighbours
        ds = ds.convert_calendar("standard", missing=np.nan).chunk({"time": -1}).interpolate_na("time")
    ds["time"] = ds.time.dt.floor("D")  # daily means are stamped at 12:00
    ds = ds.assign_coords(rlon=ds.rlon % 360 - 180)  # into ROTATED_POLE_CRS's half-turned frame, where rlon never wraps
    ds = ds.rio.set_spatial_dims(x_dim="rlon", y_dim="rlat").rio.write_crs(ROTATED_POLE_CRS)
    return ds
