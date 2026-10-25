import geopandas as gpd
import shapely

from config import HYBAS_FILE, MURRAY_CORRIDOR, OUTLINE_BUFFER_CRS, OUTLINE_BUFFER_KM, SDL_FILE, UNITS


def _move_murray_corridor(gdf):
    """``gdf`` (EPSG:4326, indexed by unit) with the MURRAY_CORRIDOR basins' area moved into the corridor's unit."""
    c = MURRAY_CORRIDOR
    basins = gpd.read_file(HYBAS_FILE, bbox=(c["west_lon"] - 0.1, -35.5, 143.8, -33.5)).set_index("HYBAS_ID").loc[list(c["basins"])]
    corridor = shapely.intersection(basins.geometry.union_all(), shapely.box(c["west_lon"], -90, 180, 90))
    moved = shapely.union_all([shapely.make_valid(gdf.at[u, "geometry"]) for u in c["from"]]).intersection(corridor)
    area_only = lambda g: shapely.union_all([p for p in shapely.get_parts(g) if p.geom_type == "Polygon"])  # drop the slivers' stray lines
    gdf = gdf.copy()
    gdf.at[c["unit"], "geometry"] = area_only(shapely.make_valid(gdf.at[c["unit"], "geometry"]).union(moved))
    for u in c["from"]:
        gdf.at[u, "geometry"] = area_only(shapely.make_valid(gdf.at[u, "geometry"]).difference(corridor))
    return gdf


def load_units(units=UNITS):
    """The SDL units' outlines (MDBA surface water SDL resource units, with the Murray corridor moved into the NSW Murray),
    indexed by unit ID, in EPSG:4326."""
    gdf = gpd.read_file(SDL_FILE).set_index("SWSDLID").rename_axis("sdl_unit").to_crs("EPSG:4326")
    gdf = _move_murray_corridor(gdf).loc[list(units)]
    return gdf.rename(columns={"SWSDLName": "sdl_name"})[["sdl_name", "geometry"]]


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
