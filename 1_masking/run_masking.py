import pandas as pd

from average import areal_average, unit_averages
from catchment import load_units
from evap_grid import evap_anomaly_grids
from config import HYBAS_FILE, KEEP_RAW, N_SUBCATCHMENTS, NARCLIM_DIR, RUN_KEY, SYSTEM, SYSTEM_ID, UNITS, VARIABLES, YEARS
from download import download
from load import load_narclim
from results_db import load_climate, save_climate
from terrain_regions import terrain_regions


def _reduce_climate(units, subcatchments, basins):
    """Download the run's NARCliM subsets for the system, average them onto each SDL unit's outline, reaches, basins
    and display grid, store each unit's result in the database, then delete the raw files (set KEEP_RAW=1 to keep them)."""
    if not all((NARCLIM_DIR / f"{var}_{year}.nc").exists() for var in VARIABLES for year in YEARS):
        download()
    narclim = load_narclim()
    grids = evap_anomaly_grids(narclim, {u: units.loc[[u]] for u in UNITS})
    for u in UNITS:
        reduced = (areal_average(narclim, units.loc[[u]]), unit_averages(narclim, subcatchments[subcatchments["sdl_unit"] == u]),
                   unit_averages(narclim, basins[basins["sdl_unit"] == u]))
        empty = [c for frame in reduced for c in frame.columns if frame[c].isna().all()]
        if empty:  # a unit with no 4 km cells under it: the grid and outlines disagree, so store nothing
            raise RuntimeError(f"1_masking: no NARCliM cells under {', '.join(sorted({c.rsplit('_', 1)[0] for c in empty}))}")
        save_climate(u, RUN_KEY, *reduced, grids[u])
    narclim.close()
    if not KEEP_RAW:
        files = list(NARCLIM_DIR.glob("*.nc"))
        for f in files:
            f.unlink()
        print(f"1_masking: stored reduced climate for {', '.join(UNITS)} in the database, deleted {len(files)} raw NARCliM files")


def run_masking():
    """Return (units, subcatchments, basins, basin_forcing) for the system: daily area-weighted P and PET per basin.

    units are the system's SDL unit outlines. basins are the individual terrain watersheds (plus a lowland unit per
    SDL unit for the plains) that the rainfall-runoff and routing steps work on; subcatchments group them into
    reaches (and lowlands) for display. Each unit's reduced climate is stored in the database under its SDL unit.
    """
    units = load_units()
    subcatchments, basins = terrain_regions(units, HYBAS_FILE, n=N_SUBCATCHMENTS, min_network_km2=SYSTEM.get("min_network_km2"), joins=SYSTEM.get("joins"))
    of = lambda frame, u: frame[frame["sdl_unit"] == u]
    if any(load_climate(u, RUN_KEY, of(subcatchments, u), of(basins, u)) is None for u in UNITS):
        print(f"1_masking: no stored climate for {SYSTEM_ID} {'/'.join(RUN_KEY)}, reducing NARCliM")
        _reduce_climate(units, subcatchments, basins)
    basin_forcing = pd.concat([load_climate(u, RUN_KEY, of(subcatchments, u), of(basins, u))[2] for u in UNITS], axis=1)
    return units, subcatchments, basins, basin_forcing
