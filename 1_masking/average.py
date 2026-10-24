import geopandas as gpd
import numpy as np
import pandas as pd
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


def unit_averages(ds, units):
    """Daily area-weighted means for every unit, with columns ``<unit>_P``, ``<unit>_PET`` (one matrix product per variable)."""
    names = list(units["subcatchment"])
    weights = np.stack([cell_weights(ds, gpd.GeoDataFrame([u], geometry="geometry", crs=units.crs)).values.ravel()
                        for _, u in units.iterrows()])
    weights = (weights / weights.sum(axis=1, keepdims=True)).astype("float32")
    cols = {}
    for var in ds.data_vars:
        x = ds[var].transpose("time", "rlat", "rlon").values.astype("float32", copy=False).reshape(ds.sizes["time"], -1)
        avg = x @ weights.T
        for i, name in enumerate(names):
            cols[f"{name}_{var}"] = avg[:, i]
    return pd.DataFrame(cols, index=ds["time"].values).rename_axis("time")
