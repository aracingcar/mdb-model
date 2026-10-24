from importlib import import_module

# Each method is a module in this folder exposing LABEL and route(runoff, basins, subcatchments), returning
# (flow, reach_flow, basin_flow, rivers, river_flow) as documented on run_routing.
# To offer another method, add its module name to AVAILABLE_MODELS; the display dropdown follows.
AVAILABLE_MODELS = ["muskingum", "muskingum_2"]
ROUTING_MODEL = "muskingum"


def model_options():
    """(module name, label) for every selectable method."""
    return [(name, import_module(name).LABEL) for name in AVAILABLE_MODELS]


def run_routing(runoff, basins, subcatchments, model=ROUTING_MODEL):
    """Route basin runoff (m3/s) down the watershed network; return (flow, reach_flow, basin_flow, rivers, river_flow).

    flow is the daily series at the valley outlet (ML/d), reach_flow the flow at each subcatchment reach's outlet
    basin, basin_flow the routed flow leaving every basin, and rivers / river_flow the segments of every mapped
    river and creek with their daily flow (see river_flows.py).
    """
    if model not in AVAILABLE_MODELS:
        raise ValueError(f"Unknown routing model {model!r}; available: {AVAILABLE_MODELS}")
    return import_module(model).route(runoff, basins, subcatchments)
