"""SQLite store for reduced climate series, geometry and model results, keyed by SDL unit and run.

Large arrays are saved as compressed .npz blobs. The raw NARCliM files are only needed to fill a row and can be
deleted once it exists.
"""
import io
import json
import shutil
import sqlite3
import sys
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1_masking"))

from config import DB_FILE

CLIMATE_BLOBS = ("forcing", "subcatchment_forcing", "basin_forcing", "evap_grid")
LEGACY_TABLES = ("climate", "geometry", "results")  # the tables that predate the SDL unit key
RESULT_BLOBS = ("flow", "reach_flow", "river_flow", "fish", "birds", "gum")  # an ecology table is NULL when the unit has no thresholds for it
TABLES = {
    "climate": f"""sdl_unit TEXT NOT NULL, global_model TEXT, scenario TEXT, regional_config TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP,
        {", ".join(f"{b} BLOB" for b in CLIMATE_BLOBS)},
        PRIMARY KEY (sdl_unit, global_model, scenario, regional_config)""",
    "geometry": "sdl_unit TEXT NOT NULL, name TEXT, geojson BLOB, PRIMARY KEY (sdl_unit, name)",
    "results": f"""sdl_unit TEXT NOT NULL, global_model TEXT, scenario TEXT, regional_config TEXT, rainfall_runoff TEXT, routing TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP, {", ".join(f"{b} BLOB" for b in RESULT_BLOBS)},
        PRIMARY KEY (sdl_unit, global_model, scenario, regional_config, rainfall_runoff, routing)""",
    # routed outflow (ML/d) of the basins where one river system's water enters another (config.LINKS), from the default methods
    "link_flows": "system TEXT NOT NULL, global_model TEXT, scenario TEXT, regional_config TEXT, basin TEXT NOT NULL, flow BLOB, PRIMARY KEY (system, global_model, scenario, regional_config, basin)",
}
UNKEYED_UNIT = "CEWO-MBG"  # databases from before the SDL unit key held only the Murrumbidgee, on its CEWO valley outline


def _add_unit_key(db):
    """Move rows from tables without an sdl_unit column under UNKEYED_UNIT, after backing the file up beside it."""
    old = [t for t in LEGACY_TABLES if (cols := [r[1] for r in db.execute(f"PRAGMA table_info({t})")]) and "sdl_unit" not in cols]
    if not old:
        return
    backup = DB_FILE.with_name(f"{DB_FILE.stem}_before_sdl_unit{DB_FILE.suffix}")
    if not backup.exists():
        shutil.copy2(DB_FILE, backup)
    db.execute("BEGIN")
    for t in old:
        cols = ", ".join(r[1] for r in db.execute(f"PRAGMA table_info({t})"))
        db.execute(f"ALTER TABLE {t} RENAME TO {t}_unkeyed")
        db.execute(f"CREATE TABLE {t} ({TABLES[t]})")
        db.execute(f"INSERT INTO {t} (sdl_unit, {cols}) SELECT ?, {cols} FROM {t}_unkeyed", (UNKEYED_UNIT,))
        db.execute(f"DROP TABLE {t}_unkeyed")
    db.commit()
    print(f"5_outputs: keyed {', '.join(old)} in {DB_FILE.name} by SDL unit (existing rows are {UNKEYED_UNIT}; backup {backup.name})")


def _connect():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    _add_unit_key(db)
    for name, columns in TABLES.items():
        db.execute(f"CREATE TABLE IF NOT EXISTS {name} ({columns})")
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


def stored_runs(units):
    """(global_model, scenario, regional_config) of every climate run stored for all of these SDL units."""
    with _connect() as db:
        runs = [set(db.execute("SELECT global_model, scenario, regional_config FROM climate WHERE sdl_unit=?", (u,))) for u in units]
    return set.intersection(*runs)


def save_climate(unit, run, forcing, subcatchment_forcing, basin_forcing, evap_grid):
    """Store one climate run's reduced series for an SDL unit; ``run`` is (global_model, scenario, regional_config)."""
    blobs = (_pack_frame(forcing), _pack_frame(subcatchment_forcing), _pack_frame(basin_forcing), _pack_grid(evap_grid))
    with _connect() as db:
        db.execute(f"INSERT OR REPLACE INTO climate (sdl_unit, global_model, scenario, regional_config, {', '.join(CLIMATE_BLOBS)}) VALUES (?,?,?,?,?,?,?,?)",
                   (unit, *run, *blobs))


def load_climate(unit, run, subcatchments=None, basins=None):
    """(forcing, subcatchment_forcing, basin_forcing, evap_grid) for an SDL unit and run, or None if absent or, when
    the unit's reaches and basins are given, built for others."""
    with _connect() as db:
        row = db.execute(f"SELECT {', '.join(CLIMATE_BLOBS)} FROM climate WHERE sdl_unit=? AND global_model=? AND scenario=? AND regional_config=?",
                         (unit, *run)).fetchone()
    if row is None:
        return None
    forcing, sub, basin, grid = _unpack_frame(row[0]), _unpack_frame(row[1]), _unpack_frame(row[2]), _unpack_grid(row[3])
    if subcatchments is not None:
        expected = {"sub": {f"{n}_{v}" for n in subcatchments["subcatchment"] for v in ("P", "PET")},
                    "basin": {f"{n}_{v}" for n in basins["subcatchment"] for v in ("P", "PET")}}
        if set(sub.columns) != expected["sub"] or set(basin.columns) != expected["basin"]:
            return None
    return forcing, sub, basin, grid


def save_geometry(unit, **layers):
    """Store GeoDataFrames (outline, subcatchments, basins, rivers) as compressed GeoJSON, replacing the SDL unit's earlier copy."""
    with _connect() as db:
        for name, gdf in layers.items():
            db.execute("INSERT OR REPLACE INTO geometry (sdl_unit, name, geojson) VALUES (?, ?, ?)",
                       (unit, name, zlib.compress(gdf.to_crs("EPSG:4326").to_json().encode())))


def load_geometry(unit, name):
    import geopandas as gpd
    with _connect() as db:
        row = db.execute("SELECT geojson FROM geometry WHERE sdl_unit=? AND name=?", (unit, name)).fetchone()
    return None if row is None else gpd.read_file(io.StringIO(zlib.decompress(row[0]).decode()))


def save_results(unit, run, methods, flow, reach_flow, river_flow, fish, birds, gum):
    """Store one run's model results for an SDL unit; ``methods`` is (rainfall_runoff, routing). No flow: nothing is stored."""
    if flow is None:
        return
    blobs = (_pack_frame(flow.rename("flow_ML_d").to_frame()), _pack_frame(reach_flow), _pack_frame(river_flow.astype("float32")),
             *(None if t is None else _pack_frame(t) for t in (fish, birds, gum)))
    with _connect() as db:
        db.execute(f"INSERT OR REPLACE INTO results (sdl_unit, global_model, scenario, regional_config, rainfall_runoff, routing, {', '.join(RESULT_BLOBS)}) "
                   f"VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (unit, *run, *methods, *blobs))


def load_results(unit, run, methods):
    """(flow, reach_flow, river_flow, fish, birds, gum) for a run and method pair, or None."""
    with _connect() as db:
        row = db.execute(f"SELECT {', '.join(RESULT_BLOBS)} FROM results WHERE sdl_unit=? AND global_model=? AND scenario=? AND regional_config=? "
                         "AND rainfall_runoff=? AND routing=?", (unit, *run, *methods)).fetchone()
    if row is None:
        return None
    flow, *rest = [None if b is None else _unpack_frame(b) for b in row]
    return (flow["flow_ML_d"], *rest)


def save_link_flows(system, run, flows):
    """Store the routed outflow (ML/d, a Series per basin ID) of the basins in ``flows`` that other river systems take water from."""
    with _connect() as db:
        for basin, flow in flows.items():
            db.execute("INSERT OR REPLACE INTO link_flows (system, global_model, scenario, regional_config, basin, flow) VALUES (?,?,?,?,?,?)",
                       (system, *run, basin, _pack_frame(flow.rename("flow_ML_d").to_frame())))


def load_link_flow(system, run, basin):
    """The stored outflow (ML/d Series, daily) of a river system's basin for a run, or None."""
    with _connect() as db:
        row = db.execute("SELECT flow FROM link_flows WHERE system=? AND global_model=? AND scenario=? AND regional_config=? AND basin=?",
                         (system, *run, basin)).fetchone()
    return None if row is None else _unpack_frame(row[0])["flow_ML_d"]
