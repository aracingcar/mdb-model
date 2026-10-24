"""Muskingum routing variant with a different parameter set, to demonstrate a second selectable routing method."""
import muskingum

LABEL = "Muskingum (alt. parameters)"
# Slower wave speed (~0.75 m/s), more attenuation (x), slightly more lowland delivery and a lower outlet flow target.
PARAMS = {**muskingum.PARAMS, "x": 0.25, "velocity_km_day": 64.8, "delivery": {"LOWLAND": 0.08}, "target_outlet_m3s": 24.0}


def route(runoff, basins, subcatchments):
    return muskingum.route(runoff, basins, subcatchments, PARAMS)
