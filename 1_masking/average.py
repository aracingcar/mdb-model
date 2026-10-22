import numpy as np
import xarray as xr
from exactextract import exact_extract


def cell_weights(ds, gdf):
    """Fraction of each grid cell covered by the catchment, as a DataArray on the grid."""
    template = ds[list(ds.data_vars)[0]].isel(time=0).load()
    template = template.rio.set_spatial_dims(x_dim="rlon", y_dim="rlat").rio.write_crs(ds.rio.crs)
    res = exact_extract(template, gdf.to_crs(ds.rio.crs), ["cell_id", "coverage"], output="pandas")
    ids = np.asarray(res["cell_id"].iloc[0], dtype=int)
    cov = np.asarray(res["coverage"].iloc[0], dtype=float)

    flat = np.zeros(template.size)
    flat[ids] = cov
    return xr.DataArray(flat.reshape(template.shape), coords=template.coords, dims=template.dims)


def areal_average(ds, gdf):
    """Daily area-weighted mean of every variable over the catchment."""
    weights = cell_weights(ds, gdf)
    out = ds.weighted(weights).mean(dim=["rlat", "rlon"])
    return out.to_dataframe()[list(ds.data_vars)]
