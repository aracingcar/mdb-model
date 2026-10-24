"""Validate the Victorian local-runoff pilot against stored default-run results."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
for folder in ('1_masking', '2_rainfall_runoff', '3_routing', '4_ecology', '5_outputs'):
    sys.path.insert(0, str(ROOT / folder))

from catchment import load_units
from config import HYBAS_FILE, RUN_KEY, SYSTEM, SYSTEM_ID, UNITS
from results_db import load_climate, load_geometry, load_results
from run_rainfall_runoff import run_rainfall_runoff
from muskingum import M3S_TO_ML_DAY, PARAMS, delivery, route
from terrain_regions import AREA_CRS, terrain_regions

assert SYSTEM_ID in ('vic_murray', 'goulburn_broken')
units = load_units()
subs, basins = terrain_regions(units, HYBAS_FILE, SYSTEM['n_subcatchments'], SYSTEM.get('min_network_km2'))
names = set(basins.subcatchment)
assert basins.subcatchment.is_unique and subs.subcatchment.is_unique
assert all(not n or n in names for n in basins.next_id)
assert all(basins.geometry.is_valid) and all(basins.area_km2 > 0)
assert all(n in names for n in subs.unit_outlet)
expected = pd.date_range('2015-01-01', '2100-12-31', name='time')
forcing, report = [], {}
for u in UNITS:
    climate = load_climate(u, RUN_KEY, subs[subs.sdl_unit == u], basins[basins.sdl_unit == u])
    assert climate is not None, u
    for frame in climate[:3]:
        assert frame.index.equals(expected), (u, 'dates')
        assert np.isfinite(frame.to_numpy()).all(), (u, 'nonfinite forcing')
        assert (frame.to_numpy() >= 0).all(), (u, 'negative forcing')
    forcing.append(climate[2])
    grid = climate[3]
    assert grid['values'].size and (grid['idx'] >= 0).any()
    assert np.isfinite(grid['weights']).all()
    stored = load_results(u, RUN_KEY, ('gr4j', 'muskingum'))
    assert stored is not None
    for frame in stored[:3]:
        assert np.isfinite(frame.to_numpy()).all() and (frame.to_numpy() >= 0).all()
    assert stored[3:] == (None, None, None)
    rivers = load_geometry(u, 'rivers')
    assert len(rivers) and set(rivers.sdl_unit) == {u}
    assert not set(rivers.name) & set(SYSTEM.get('other_rivers', ()))
    ub = basins[basins.sdl_unit == u]
    lowland = float(ub.loc[ub.subcatchment.str.startswith('LOWLAND'), 'area_km2'].sum())
    area = float(units.loc[[u]].to_crs(AREA_CRS).area.sum() / 1e6)
    report[u] = {'area_km2': area, 'basins': len(ub), 'reaches': int((subs.sdl_unit == u).sum()),
                 'lowland_percent': lowland / area * 100, 'allocated_area_km2': float(ub.area_km2.sum()),
                 'allocation_difference_percent': (ub.area_km2.sum() - area) / area * 100,
                 'rivers': len(rivers), 'mean_outlet_ML_d': float(stored[0].mean()),
                 'unit_outlet': subs.loc[subs.sdl_unit == u, 'unit_outlet'].iloc[0]}
runoff = run_rainfall_runoff(pd.concat(forcing, axis=1), basins)
unit_flow, _, flow, _, _ = route(runoff, basins, subs)
for u, series in unit_flow.items():
    np.testing.assert_array_equal(series.to_numpy(), load_results(u, RUN_KEY, ('gr4j', 'muskingum'))[0].to_numpy())
sinks = basins.loc[basins.next_id == '', 'subcatchment'].tolist()
lateral = sum(float(runoff[n].sum()) * delivery(PARAMS, n) for n in runoff) * M3S_TO_ML_DAY
outflow = float(flow[sinks].sum().sum())
error = abs(outflow - lateral) / lateral
assert error < 0.001, error
owner = basins.set_index('subcatchment').sdl_unit.to_dict()
crossings = [{'from': r.subcatchment, 'to': r.next_id, 'from_unit': r.sdl_unit, 'to_unit': owner[r.next_id]}
             for r in basins.itertuples() if r.next_id and owner[r.next_id] != r.sdl_unit]
print(json.dumps({'system': SYSTEM_ID, 'days': len(expected), 'units': report, 'outlets': sinks,
                  'crossings': crossings, 'mass_balance_relative_error': error}, indent=2))
