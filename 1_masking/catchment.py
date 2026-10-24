import geopandas as gpd

from config import SDL_FILE, UNITS


def load_units(units=UNITS):
    """The SDL units' outlines (MDBA surface water SDL resource units), indexed by unit ID, in EPSG:4326."""
    gdf = gpd.read_file(SDL_FILE).set_index("SWSDLID").rename_axis("sdl_unit").loc[list(units)]
    return gdf.rename(columns={"SWSDLName": "sdl_name"})[["sdl_name", "geometry"]].to_crs("EPSG:4326")


def load_catchment():
    """The modelled system's SDL units dissolved into one geometry in EPSG:4326."""
    return load_units().dissolve().reset_index(drop=True)[["geometry"]]
