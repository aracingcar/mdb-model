from importlib import import_module

# Each method is a module in this folder exposing LABEL and route(runoff, basins, subcatchments, *, basin_forcing), returning
# (unit_flow, reach_flow, basin_flow, rivers, river_flow) as documented on run_routing.
# To offer another method, add its module name to AVAILABLE_MODELS; the display dropdown follows.
AVAILABLE_MODELS = ["muskingum", "muskingum_2"]
ROUTING_MODEL = "muskingum"


def model_specs():
    """{module name: {label, algorithm, params}} for every selectable method, so the browser can re-run them."""
    out = {}
    for name in AVAILABLE_MODELS:
        m = import_module(name)
        out[name] = {"label": m.LABEL, "algorithm": m.ALGORITHM, "params": m.PARAMS}
    return out


def run_routing(runoff, basins, subcatchments, model=ROUTING_MODEL, *, basin_forcing=None):
    """Route basin runoff (m3/s) down the watershed network; return (unit_flow, reach_flow, basin_flow, rivers, river_flow).

    unit_flow is {SDL unit: daily flow at the unit's outlet (ML/d)}, reach_flow the flow at each reach's outlet
    basin, basin_flow the routed flow leaving every basin, and rivers / river_flow the segments of every mapped
    river and creek with their daily flow (see river_flows.py).
    """
    if model not in AVAILABLE_MODELS:
        raise ValueError(f"Unknown routing model {model!r}; available: {AVAILABLE_MODELS}")
    return import_module(model).route(runoff, basins, subcatchments, basin_forcing=basin_forcing)
