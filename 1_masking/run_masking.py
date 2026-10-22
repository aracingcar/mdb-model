from average import areal_average
from catchment import load_catchment
from config import HYBAS_FILE, N_SUBCATCHMENTS
from load import load_narclim
from subcatchments import subcatchment_averages
from terrain_regions import terrain_regions


def read_data():
    """Return (narclim, catchment): P and PET grids in mm/day, and the Murrumbidgee polygon."""
    return load_narclim(), load_catchment()


def run_masking(narclim, catchment):
    """Return (forcing, subcatchments, subcatchment_forcing): daily area-weighted P and PET."""
    subcatchments = terrain_regions(catchment, HYBAS_FILE, n=N_SUBCATCHMENTS)
    forcing = areal_average(narclim, catchment)
    subcatchment_forcing = subcatchment_averages(narclim, subcatchments)
    return forcing, subcatchments, subcatchment_forcing
