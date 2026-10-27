"""GR4J variant with a different parameter set, to demonstrate a second selectable rainfall-runoff method."""
from gr4j import gr4j

# Slightly smaller production store, small groundwater loss and a longer unit hydrograph than the default.
PARAMS = (300.0, -0.5, 80.0, 2.2)
LABEL = "GR4J (alt. parameters)"
ALGORITHM = "gr4j"


def simulate(precip, pet, zone=None):
    """Rainfall-runoff model interface: runoff depth (mm/day) with this model's parameters (one set for every zone)."""
    return gr4j(precip, pet, PARAMS)
