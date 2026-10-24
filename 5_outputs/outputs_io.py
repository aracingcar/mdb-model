import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1_masking"))

from config import GLOBAL_MODEL, REGIONAL_CONFIG, SCENARIO
from results_db import save_geometry, save_results


def write_data(subcatchments, basins, flow, reach_flow, rivers, river_flow, fish, waterbirds, river_red_gum, methods):
    """Store geometry and this run's results in the database (results.db). ``methods`` is (rainfall_runoff, routing)."""
    save_geometry(subcatchments=subcatchments, basins=basins, **({"rivers": rivers} if rivers is not None else {}))
    save_results((GLOBAL_MODEL, SCENARIO, REGIONAL_CONFIG), methods, flow, reach_flow, river_flow, fish, waterbirds, river_red_gum)
    if flow is not None:
        print(f"5_outputs: stored {len(flow)} days of results for {GLOBAL_MODEL}/{SCENARIO}/{REGIONAL_CONFIG} with {methods[0]} + {methods[1]} in results.db")
