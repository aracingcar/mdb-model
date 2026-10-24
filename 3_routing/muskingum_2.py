"""Muskingum routing variant with a different parameter set, to demonstrate a second selectable routing method."""
import muskingum

LABEL = "Muskingum (alt. parameters)"
ALGORITHM = "muskingum"
# Slower wave speed (~0.75 m/s), more attenuation (lower x; K is clipped to 0.7-2.4 d so x must stay within 0.15-0.2 for daily stability), slightly more lowland delivery and a lower outlet flow target.
PARAMS = {**muskingum.PARAMS, "x": 0.15, "velocity_km_day": 64.8, "delivery": {"LOWLAND": 0.08}, "target_outlet_m3s": 24.0}


def route(runoff, basins, subcatchments):
    return muskingum.route(runoff, basins, subcatchments, PARAMS)
