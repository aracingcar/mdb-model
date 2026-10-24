"""SQLite store for reduced climate series (and, later, model results): one row per run, looked up by key.

Large arrays are saved as compressed .npz blobs. The raw NARCliM files are only needed to fill a row and can be
deleted once it exists.
"""
import io
import json
import sqlite3
import sys
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1_masking"))

from config import DB_FILE

CLIMATE_BLOBS = ("forcing", "subcatchment_forcing", "basin_forcing", "evap_grid")
RESULT_BLOBS = ("flow", "reach_flow", "river_flow", "fish", "birds", "gum")


def _connect():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    db.execute(f"""CREATE TABLE IF NOT EXISTS climate (
        global_model TEXT, scenario TEXT, regional_config TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP,
        {", ".join(f"{b} BLOB" for b in CLIMATE_BLOBS)},
        PRIMARY KEY (global_model, scenario, regional_config))""")
    db.execute("""CREATE TABLE IF NOT EXISTS geometry (name TEXT PRIMARY KEY, geojson BLOB)""")
    db.execute(f"""CREATE TABLE IF NOT EXISTS results (
        global_model TEXT, scenario TEXT, regional_config TEXT, rainfall_runoff TEXT, routing TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP, {", ".join(f"{b} BLOB" for b in RESULT_BLOBS)},
        PRIMARY KEY (global_model, scenario, regional_config, rainfall_runoff, routing))""")
    return db


def _pack(arrays, meta=None):
    buf = io.BytesIO()
    np.savez_compressed(buf, _meta=np.array(json.dumps(meta or {})), **arrays)
    return buf.getvalue()


def _unpack(blob):
    z = np.load(io.BytesIO(blob), allow_pickle=False)
    return {k: z[k] for k in z.files if k != "_meta"}, json.loads(str(z["_meta"]))


def _pack_frame(df):
    return _pack({"index": df.index.values, **{f"c{i}": df[c].to_numpy() for i, c in enumerate(df.columns)}},
                 {"columns": list(df.columns), "index_name": df.index.name})


def _unpack_frame(blob):
    arrays, meta = _unpack(blob)
    cols = {c: arrays[f"c{i}"] for i, c in enumerate(meta["columns"])}
    return pd.DataFrame(cols, index=pd.Index(arrays["index"], name=meta["index_name"]))


def _pack_grid(grid):
    arrays = {k: v for k, v in grid.items() if isinstance(v, np.ndarray)}
    return _pack(arrays, {k: v for k, v in grid.items() if k not in arrays})


def _unpack_grid(blob):
    arrays, meta = _unpack(blob)
    return {**meta, **arrays}


def save_climate(run, forcing, subcatchment_forcing, basin_forcing, evap_grid):
    """Store one climate run's reduced series; ``run`` is (global_model, scenario, regional_config)."""
    blobs = (_pack_frame(forcing), _pack_frame(subcatchment_forcing), _pack_frame(basin_forcing), _pack_grid(evap_grid))
    with _connect() as db:
        db.execute(f"INSERT OR REPLACE INTO climate (global_model, scenario, regional_config, {', '.join(CLIMATE_BLOBS)}) VALUES (?,?,?,?,?,?,?)",
                   (*run, *blobs))


def load_climate(run, subcatchments, basins):
    """(forcing, subcatchment_forcing, basin_forcing, evap_grid) for a run, or None if absent or built for other units."""
    with _connect() as db:
        row = db.execute(f"SELECT {', '.join(CLIMATE_BLOBS)} FROM climate WHERE global_model=? AND scenario=? AND regional_config=?", run).fetchone()
    if row is None:
        return None
    forcing, sub, basin, grid = _unpack_frame(row[0]), _unpack_frame(row[1]), _unpack_frame(row[2]), _unpack_grid(row[3])
    expected = {"sub": {f"{n}_{v}" for n in subcatchments["subcatchment"] for v in ("P", "PET")},
                "basin": {f"{n}_{v}" for n in basins["subcatchment"] for v in ("P", "PET")}}
    if set(sub.columns) != expected["sub"] or set(basin.columns) != expected["basin"]:
        return None
    return forcing, sub, basin, grid


def save_geometry(**layers):
    """Store GeoDataFrames (subcatchments, basins, rivers) as compressed GeoJSON, replacing any earlier copy."""
    with _connect() as db:
        for name, gdf in layers.items():
            db.execute("INSERT OR REPLACE INTO geometry (name, geojson) VALUES (?, ?)", (name, zlib.compress(gdf.to_crs("EPSG:4326").to_json().encode())))


def load_geometry(name):
    import geopandas as gpd
    with _connect() as db:
        row = db.execute("SELECT geojson FROM geometry WHERE name=?", (name,)).fetchone()
    return None if row is None else gpd.read_file(io.StringIO(zlib.decompress(row[0]).decode()))


def save_results(run, methods, flow, reach_flow, river_flow, fish, birds, gum):
    """Store one run's model results; ``methods`` is (rainfall_runoff, routing). None results are skipped."""
    if flow is None:
        return
    blobs = (_pack_frame(flow.rename("flow_ML_d").to_frame()), _pack_frame(reach_flow), _pack_frame(river_flow.astype("float32")),
             _pack_frame(fish), _pack_frame(birds), _pack_frame(gum))
    with _connect() as db:
        db.execute(f"INSERT OR REPLACE INTO results (global_model, scenario, regional_config, rainfall_runoff, routing, {', '.join(RESULT_BLOBS)}) "
                   f"VALUES (?,?,?,?,?,?,?,?,?,?,?)", (*run, *methods, *blobs))


def load_results(run, methods):
    """(flow, reach_flow, river_flow, fish, birds, gum) for a run and method pair, or None."""
    with _connect() as db:
        row = db.execute(f"SELECT {', '.join(RESULT_BLOBS)} FROM results WHERE global_model=? AND scenario=? AND regional_config=? "
                         "AND rainfall_runoff=? AND routing=?", (*run, *methods)).fetchone()
    if row is None:
        return None
    flow, *rest = [_unpack_frame(b) for b in row]
    return (flow["flow_ML_d"], *rest)
