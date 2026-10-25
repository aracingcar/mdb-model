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


def evap_anomaly_grids(pet_years, grid, outlines):
    """Return {key: grid} for every outline in ``outlines`` ({key: GeoDataFrame}), each grid a dict with the raster
    geometry, the stored 4 km anomaly fields and the pixel -> cell mapping. Rasters of different outlines sit on one
    shared PIXEL_DEG lattice, so the display can merge them.

    ``pet_years`` yields the run's daily PET (time, rlat, rlon) a year at a time, in order, and ``grid`` is a dataset on
    the same grid. Only the running sum's last ROLL_DAYS days, the day-of-year sums and every STEP_DAYS-th 30-day total
    are kept, so the full 4 km series (~2 GB) is never in memory at once."""
    lagged = np.empty((0, grid.sizes["rlat"], grid.sizes["rlon"]), "float32")  # running sum, last ROLL_DAYS days
    sums, counts = {}, {}  # per day of year: sum of the 30-day totals, and how many
    samples, dates = [], []
    n = 0
    for pet in pet_years:
        x = pet.transpose("time", "rlat", "rlon").values.astype("float32", copy=False)
        # Running sum continued from the last day before this year, then difference with the sum ROLL_DAYS earlier.
        cum = np.cumsum(np.concatenate([lagged[-1:] if n else np.zeros((1, *x.shape[1:]), "float32"), x]), axis=0, dtype="float32")[1:]
        both = np.concatenate([lagged, cum])
        roll = both[ROLL_DAYS:] - both[:-ROLL_DAYS]
        if not n:  # the run's first ROLL_DAYS windows are partial: scaled up to mm / 30 days
            roll = np.concatenate([cum[:ROLL_DAYS] * (ROLL_DAYS / (np.arange(ROLL_DAYS) + 1)).astype("float32")[:, None, None], roll])
        lagged = both[-ROLL_DAYS:]
        keys = pet["time"].dt.strftime("%m-%d").values
        days = [str(d)[:10] for d in pet["time"].values]
        for i, k in enumerate(keys):
            sums[k] = sums[k] + roll[i] if k in sums else roll[i].copy()
            counts[k] = counts.get(k, 0) + 1
            if (n + i) % STEP_DAYS == 0:
                samples.append((roll[i].copy(), k))
                dates.append(days[i])
        n += len(keys)
        last = (roll[-1].copy(), keys[-1], days[-1])
    if (n - 1) % STEP_DAYS:  # always end on the last day
        samples.append(last[:2])
        dates.append(last[2])

    normal = {k: sums[k] / counts[k] for k in sums}
    anomaly = np.stack([r - normal[k] for r, k in samples])  # (steps, rlat, rlon)
    return {key: _raster(grid, anomaly, dates, outline) for key, outline in outlines.items()}


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
