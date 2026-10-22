import geopandas as gpd

from config import CATCHMENT_FILE, VALLEY_NAME


def load_catchment():
    """Read the MDB valleys, keep the Murrumbidgee, and return it as one geometry in EPSG:4326."""
    gdf = gpd.read_file(CATCHMENT_FILE)
    gdf = gdf[gdf["ValleyName"].str.strip() == VALLEY_NAME].to_crs("EPSG:4326")
    return gdf.dissolve().reset_index(drop=True)[["geometry"]]
