import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "1_masking"))

from config import RUN_KEY
from results_db import save_geometry, save_results


def write_data(unit, outline, subcatchments, basins, flow, reach_flow, rivers, river_flow, fish, waterbirds, river_red_gum, methods):
    """Store an SDL unit's geometry and this run's results in the database (results.db). ``methods`` is (rainfall_runoff, routing)."""
    save_geometry(unit, outline=outline, subcatchments=subcatchments, basins=basins, **({"rivers": rivers} if rivers is not None else {}))
    save_results(unit, RUN_KEY, methods, flow, reach_flow, river_flow, fish, waterbirds, river_red_gum)
    if flow is not None:
        print(f"5_outputs: stored {len(flow)} days of results for {unit} {'/'.join(RUN_KEY)} with {methods[0]} + {methods[1]} in results.db")
