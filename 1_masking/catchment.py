import geopandas as gpd

from config import OUTLINE_BUFFER_CRS, OUTLINE_BUFFER_KM, SDL_FILE, UNITS


def load_units(units=UNITS):
    """The SDL units' outlines (MDBA surface water SDL resource units), indexed by unit ID, in EPSG:4326."""
    gdf = gpd.read_file(SDL_FILE).set_index("SWSDLID").rename_axis("sdl_unit").loc[list(units)]
    return gdf.rename(columns={"SWSDLName": "sdl_name"})[["sdl_name", "geometry"]].to_crs("EPSG:4326")


def load_catchment():
    """The modelled system's SDL units dissolved into one geometry in EPSG:4326."""
    return load_units().dissolve().reset_index(drop=True)[["geometry"]]


def buffer_outline(geom, km=OUTLINE_BUFFER_KM):
    """``geom`` (EPSG:4326, e.g. the union of unit outlines) grown by ``km`` on all sides, buffered in a metric CRS and
    returned in EPSG:4326. Only the exterior of a union grows; the borders between units inside it are not part of it."""
    metric = gpd.GeoSeries([geom], crs="EPSG:4326").to_crs(OUTLINE_BUFFER_CRS)
    return metric.buffer(km * 1000).to_crs("EPSG:4326").iloc[0]


def load_buffered_catchment(units=UNITS):
    """The modelled system's SDL units dissolved, with the exterior border moved out by OUTLINE_BUFFER_KM (EPSG:4326)."""
    return buffer_outline(load_units(units).geometry.union_all())
