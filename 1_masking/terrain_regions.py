"""Terrain-derived subcatchments from HydroBASINS (HydroSHEDS, DEM-derived watersheds with downstream links)."""
import geopandas as gpd
import pandas as pd

AREA_CRS = "EPSG:3577"  # Australian Albers equal-area projection
MIN_OVERLAP = 0.5  # keep basins at least half inside the valley


def terrain_regions(catchment, hybas_file, n=12):
    """Aggregate HydroBASINS watersheds inside the valley into n regions along the main stem, plus a lowland unit
    for the western plains, which HydroBASINS has no drainage for. Returns (regions, basins): the regions, and
    the individual watersheds with their downstream link (next_id) and region.

    The main stem is followed upstream from the valley outlet through the largest in-valley inflow at each
    junction. Region outlets are the main-stem basins where cumulative upstream area crosses k/n of the
    valley total; each region is its outlet basin plus every basin draining to it. Regions are ordered
    upstream to downstream and are true watershed unions, so tributaries stay with their reach.
    """
    valley = catchment.to_crs(AREA_CRS).geometry.union_all()
    basins = gpd.read_file(hybas_file).to_crs(AREA_CRS)
    basins = basins[basins.intersects(valley)].copy()
    basins["geometry"] = basins.geometry.intersection(valley)
    basins["area"] = basins.geometry.area
    full = gpd.read_file(hybas_file).set_index("HYBAS_ID").to_crs(AREA_CRS).geometry.area
    basins = basins[basins["area"] / basins["HYBAS_ID"].map(full) >= MIN_OVERLAP].set_index("HYBAS_ID")

    nxt = {i: d for i, d in basins["NEXT_DOWN"].items() if d in basins.index}
    children = {i: [] for i in basins.index}
    for i, d in nxt.items():
        children[d].append(i)

    upstream = {}

    def up_area(i):
        if i not in upstream:
            upstream[i] = basins.at[i, "area"] + sum(up_area(c) for c in children[i])
        return upstream[i]

    sinks = [i for i in basins.index if i not in nxt]
    outlet = max(sinks, key=up_area)
    stem = [outlet]
    while children[stem[-1]]:
        stem.append(max(children[stem[-1]], key=up_area))
    stem.reverse()  # headwater -> outlet

    total = up_area(outlet)
    outlets = []
    for k in range(1, n + 1):
        node = next(i for i in stem if up_area(i) >= k / n * total * 0.9999)
        if node not in outlets:
            outlets.append(node)
    if stem[-1] not in outlets:
        outlets.append(stem[-1])

    def region_of(i):
        while i not in outlets:
            if i not in nxt:
                return None
            i = nxt[i]
        return i

    basins["region"] = [region_of(i) for i in basins.index]
    rows = []
    for order, out in enumerate(outlets, start=1):
        geom = basins.loc[basins["region"] == out].geometry.union_all()
        rows.append({
            "subcatchment": f"SC{order:02d}", "route_order": order,
            "region_name": f"Reach {order} (outlet HYBAS {out})",
            "upstream_boundary": "Headwaters" if order == 1 else f"SC{order - 1:02d} outlet",
            "downstream_boundary": f"SC{order:02d} outlet",
            "area_km2": geom.area / 1e6, "geometry": geom,
        })
    covered = gpd.GeoSeries([r["geometry"] for r in rows], crs=AREA_CRS).union_all()
    lowland = valley.difference(covered)
    rows.append({
        "subcatchment": f"SC{len(rows) + 1:02d}", "route_order": len(rows) + 1,
        "region_name": "Lowland plains (no terrain-defined drainage)",
        "upstream_boundary": f"SC{len(rows):02d} outlet", "downstream_boundary": "Valley outlet",
        "area_km2": lowland.area / 1e6, "geometry": lowland,
    })
    rows[len(outlets) - 1]["downstream_boundary"] = f"SC{len(outlets):02d} outlet"
    for i, row in enumerate(rows[:len(outlets)]):
        row["outlet_basin"] = f"B{outlets[i]}"
    rows[-1]["outlet_basin"] = ""
    regions = gpd.GeoDataFrame(rows, crs=AREA_CRS).to_crs(catchment.crs)

    code = {out: f"SC{k:02d}" for k, out in enumerate(outlets, start=1)}
    kept = basins.dropna(subset=["region"]).copy()
    kept["subcatchment"] = [f"B{i}" for i in kept.index]
    kept["next_id"] = [f"B{nxt[i]}" if i in nxt else "" for i in kept.index]
    kept["region"] = kept["region"].map(code)
    kept["area_km2"] = kept.geometry.area / 1e6
    kept.index.name = "hybas_id"
    network = gpd.GeoDataFrame(kept.reset_index()[["subcatchment", "hybas_id", "next_id", "region", "area_km2", "geometry"]],
                               crs=AREA_CRS).to_crs(catchment.crs)
    return regions, network
