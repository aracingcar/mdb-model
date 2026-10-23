"""Elevation for the display from public AWS Terrain Tiles (Terrarium PNG, 8 bit RGB: elevation = R*256 + G + B/256 - 32768 m)."""
import io
import math
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

ZOOM = 9  # ~300 m pixels at this latitude
SMOOTH_PX = 3  # gaussian sigma in DEM pixels (~0.9 km)
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
CACHE = Path(__file__).resolve().parent.parent / "data" / "input" / "dem"


def _tile_xy(lon, lat):
    n = 2 ** ZOOM
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def _fetch(x, y):
    path = CACHE / f"{ZOOM}_{x}_{y}.png"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL.format(z=ZOOM, x=x, y=y), timeout=60) as r:
            path.write_bytes(r.read())
    rgb = np.asarray(Image.open(io.BytesIO(path.read_bytes())).convert("RGB"), dtype=float)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


class Dem:
    """Mosaic of terrain tiles covering lon/lat bounds, sampled by nearest pixel."""

    def __init__(self, bounds):
        minx, miny, maxx, maxy = bounds
        x0, y1 = map(int, _tile_xy(minx, miny))
        x1, y0 = map(int, _tile_xy(maxx, maxy))
        self.x0, self.y0 = x0, y0
        z = np.vstack([np.hstack([_fetch(x, y) for x in range(x0, x1 + 1)]) for y in range(y0, y1 + 1)])
        self.z = gaussian_filter(z, sigma=SMOOTH_PX)  # soften pixel noise so the surface reads as continuous

    def at(self, lon, lat):
        lon, lat = np.asarray(lon, float), np.asarray(lat, float)
        n = 2 ** ZOOM
        px = ((lon + 180) / 360 * n - self.x0) * 256
        py = ((1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * n - self.y0) * 256
        col = np.clip(px.astype(int), 0, self.z.shape[1] - 1)
        row = np.clip(py.astype(int), 0, self.z.shape[0] - 1)
        return self.z[row, col]


def hillshade(elev, step_deg, lat, azimuth=315.0, altitude=45.0):
    """Standard hillshade (0 dark - 1 bright) of an elevation grid whose rows run north to south."""
    dx = step_deg * 111320 * math.cos(math.radians(lat))
    dy = step_deg * 110574
    gy, gx = np.gradient(elev, dy, dx)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = math.radians(360 - azimuth + 90), math.radians(altitude)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(shade, 0, 1)
