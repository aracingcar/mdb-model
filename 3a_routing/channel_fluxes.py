"""Provisional channel footprint and daily flux demands; no groundwater gain model."""
import numpy as np


def channel_inputs(runoff, nodes, basins, forcing, p, delivery):
    if forcing is None or not forcing.index.equals(runoff.index):
        raise ValueError('Channel fluxes require P/PET forcing aligned with runoff dates')
    for key in ('channel_width_m', 'pet_factor', 'seepage_ML_day_km', 'misc_loss_per_km'):
        if not np.isfinite(p[key]) or p[key] < 0:
            raise ValueError(f'{key} must be finite and non-negative')
    areas = basins.set_index('subcatchment').area_km2
    lengths = nodes.length_km.fillna(1.5 * np.sqrt(nodes.area_km2))
    lateral, fluxes = {}, {}
    for n, length in zip(nodes.itertuples(), lengths):
        # LOWLAND is an aggregated land runoff source, not a mapped river reach.
        length = 0.0 if n.basin.startswith('LOWLAND') else float(length)
        area = float(areas[n.basin]) * n.share
        surface = min(length * p['channel_width_m'] / 1000, area)  # km2
        rain = forcing[f'{n.basin}_P'].to_numpy(float)
        pet = forcing[f'{n.basin}_PET'].to_numpy(float)
        if not np.isfinite([rain, pet]).all() or np.any(rain < 0) or np.any(pet < 0):
            raise ValueError('P/PET must be finite, non-negative mm/day')
        lateral[n.id] = runoff[n.basin] * delivery(p, n.basin) * n.share * (1 - surface / area)
        fluxes[n.id] = {'length_km': length, 'rain_m3s': rain * surface / 86.4,
                       'evap_m3s': pet * p['pet_factor'] * surface / 86.4,
                       'seepage_m3s': length * p['seepage_ML_day_km'] / 86.4}
    return lateral, fluxes
