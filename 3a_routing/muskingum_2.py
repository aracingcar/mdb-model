"""Muskingum routing variant with a different parameter set, to demonstrate a second selectable routing method."""
import muskingum

LABEL = "Muskingum (alt. parameters)"
ALGORITHM = "muskingum"
# Slower wave speed (~0.75 m/s), more attenuation (lower x; each Muskingum (sub-)reach has K within 0.7-2.4 d, so x must stay within 0.15-0.2 for daily stability), slightly more lowland delivery and a lower outlet flow target (24/27 of the system's, e.g. 24 of the Murrumbidgee's 27 m3/s).
# The plains are slower in the same proportion as the default set's (0.65 of the highland speed).
PARAMS = {**muskingum.PARAMS, "x": 0.15, "velocity_km_day": 64.8, "plains_velocity_km_day": 42.12, "delivery": {"LOWLAND": 0.08}, "target_scale": 24 / 27}


def route(runoff, basins, subcatchments, *, basin_forcing=None):
    return muskingum.route(runoff, basins, subcatchments, PARAMS, basin_forcing=basin_forcing)
