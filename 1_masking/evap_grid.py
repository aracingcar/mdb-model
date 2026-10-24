"""Gridded evaporation anomaly on the native 4 km NARCliM grid, resampled onto a lon/lat raster for display.

Anomaly = rolling 30-day potential evaporation (mm / 30 days) minus its mean for that day of the year across the
run. Values are kept on the 4 km cells (sampled every few days) together with, for every raster pixel, the four
surrounding 4 km cells and bilinear weights, so a viewer can interpolate a smooth field without the full grid.
"""
import numpy as np
import shapely
from pyproj import Transformer

from config import ROTATED_POLE_CRS

ROLL_DAYS = 30
STEP_DAYS = 15  # one stored field every STEP_DAYS days
PIXEL_DEG = 0.025  # raster pixel size (~2.5 km)
BUFFER_DEG = 0.12  # keep pixels this close to the valley
SCALE = 2  # stored as int8 in half-mm steps


def evap_anomaly_grids(ds, outlines):
    """Return {key: grid} for every outline in ``outlines`` ({key: GeoDataFrame}), each grid a dict with the raster
    geometry, the stored 4 km anomaly fields and the pixel -> cell mapping. Rasters of different outlines sit on one
    shared PIXEL_DEG lattice, so the display can merge them."""
    n = ds.sizes["time"]
    roll = ds["PET"].transpose("time", "rlat", "rlon").values.astype("float32", copy=False)
    # In place (the full series is ~2 GB): running sum, then difference with the sum ROLL_DAYS earlier, scaled to mm / 30 days.
    np.cumsum(roll, axis=0, dtype="float32", out=roll)
    for t in range(n - 1, ROLL_DAYS - 1, -1):
        roll[t] -= roll[t - ROLL_DAYS]
    early = min(ROLL_DAYS, n)  # partial windows are scaled up
    roll[:early] *= (ROLL_DAYS / (np.arange(early) + 1)).astype("float32")[:, None, None]
    keys = ds["time"].dt.strftime("%m-%d").values
    normal = {k: roll[keys == k].mean(axis=0) for k in np.unique(keys)}

    times = list(range(0, n, STEP_DAYS))
    if times[-1] != n - 1:
        times.append(n - 1)
    anomaly = np.stack([roll[t] - normal[keys[t]] for t in times])  # (steps, rlat, rlon)
    del roll
    dates = [str(ds["time"].values[t])[:10] for t in times]
    return {key: _raster(ds, anomaly, dates, outline) for key, outline in outlines.items()}


def _raster(ds, anomaly, dates, outline):
    valley = outline.to_crs("EPSG:4326").geometry.union_all()
    minx, miny, maxx, maxy = valley.bounds
    minx, miny = np.floor(minx / PIXEL_DEG) * PIXEL_DEG, np.floor(miny / PIXEL_DEG) * PIXEL_DEG
    nx, ny = int(np.ceil((maxx - minx) / PIXEL_DEG)), int(np.ceil((maxy - miny) / PIXEL_DEG))
    maxy = miny + ny * PIXEL_DEG
    lon = minx + (np.arange(nx) + 0.5) * PIXEL_DEG
    lat = maxy - (np.arange(ny) + 0.5) * PIXEL_DEG  # row 0 is north
    gx, gy = np.meshgrid(lon, lat)

    near = shapely.contains_xy(valley.buffer(BUFFER_DEG), gx, gy)
    rx, ry = Transformer.from_crs("EPSG:4326", ROTATED_POLE_CRS, always_xy=True).transform(gx, gy)
    rlon, rlat = ds["rlon"].values, ds["rlat"].values
    fj = np.interp(rx, rlon, np.arange(len(rlon)), left=np.nan, right=np.nan)
    fi = np.interp(ry, rlat, np.arange(len(rlat)), left=np.nan, right=np.nan)
    near &= np.isfinite(fi) & np.isfinite(fj) & (fi < len(rlat) - 1) & (fj < len(rlon) - 1)

    i0, j0 = np.floor(np.nan_to_num(fi)).astype(int), np.floor(np.nan_to_num(fj)).astype(int)
    corners = np.stack([i0 * len(rlon) + j0, i0 * len(rlon) + j0 + 1, (i0 + 1) * len(rlon) + j0, (i0 + 1) * len(rlon) + j0 + 1], axis=-1)
    used = np.unique(corners[near])
    remap = np.full(len(rlat) * len(rlon), -1)
    remap[used] = np.arange(len(used))
    idx = np.where(near[..., None], remap[corners], -1).reshape(-1, 4)
    weights = np.stack([np.nan_to_num(fj) - j0, np.nan_to_num(fi) - i0], axis=-1).reshape(-1, 2)

    fields = anomaly.reshape(len(dates), -1)[:, used]
    return {
        "bbox": [minx, miny, minx + nx * PIXEL_DEG, maxy], "nx": nx, "ny": ny,
        "dates": dates,
        "values": np.clip(np.round(fields * SCALE), -127, 127).astype("int8"), "scale": SCALE,
        "idx": idx.astype("int32"), "weights": weights.astype("float32"),
    }
