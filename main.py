import sys
from pathlib import Path

ROOT = Path(__file__).parent
for folder in ("1_masking", "2_rainfall_runoff", "3_routing", "4_ecology", "5_outputs", "6_display"):
    sys.path.insert(0, str(ROOT / folder))

from outputs_io import write_data
from run_display import run_display
from run_ecology import run_ecology
from run_masking import read_data, run_masking
from run_rainfall_runoff import run_rainfall_runoff
from run_routing import run_routing

if __name__ == "__main__":
    narclim, catchment = read_data()
    forcing, subcatchments, subcatchment_forcing, basins, basin_forcing = run_masking(narclim, catchment)
    runoff = run_rainfall_runoff(basin_forcing, basins)
    flow, reach_flow, basin_flow, rivers, river_flow = run_routing(runoff, basins, subcatchments)
    fish, waterbirds, river_red_gum = run_ecology(flow)
    write_data(forcing, subcatchments, subcatchment_forcing, basins, flow, reach_flow, rivers, river_flow, fish, waterbirds, river_red_gum)
    run_display(forcing, subcatchments, subcatchment_forcing, flow, reach_flow, rivers, river_flow, fish, waterbirds, river_red_gum)
