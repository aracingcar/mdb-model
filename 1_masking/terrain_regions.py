"""Terrain-derived subcatchments from HydroBASINS (HydroSHEDS, DEM-derived watersheds with downstream links)."""
import geopandas as gpd
import pandas as pd

AREA_CRS = "EPSG:3577"  # Australian Albers equal-area projection
MIN_OVERLAP = 0.5  # keep basins at least half inside the system
MIN_LOWLAND = 0.01  # a unit's leftover area smaller than this share of the unit is dropped instead of becoming a lowland unit


def terrain_regions(units, hybas_file, n=12, min_network_km2=None):
    """Aggregate the HydroBASINS watersheds of a river system into reaches, each inside one SDL unit, plus one lowland
    unit per SDL unit for the plains HydroBASINS has no drainage for. ``units`` are the system's SDL unit outlines,
    indexed by unit ID. Returns (regions, basins): the reaches and lowlands, and the individual watersheds with their
    downstream link (next_id), reach (region) and SDL unit.

    Each basin belongs to the unit holding most of its area. The main stem is followed upstream from the system outlet
    through the largest inflow at each junction; reach outlets are the main-stem basins where cumulative upstream area
    crosses k/n of the system total, plus every basin whose water flows on into another unit. Each reach is its outlet
    basin plus every basin draining to it, so tributaries stay with their reach and no reach crosses a unit border.
    from_outlet numbers the main-stem reaches from the system outlet (1 = the outlet reach); other basins get 0.
    Other drainage networks (draining out of the system elsewhere) join the lowland, unless min_network_km2 is set:
    then each one at least that big is kept as a reach of its own, ending where it leaves the system.
    """
    polys = units.to_crs(AREA_CRS).geometry
    system = polys.union_all()
    basins = gpd.read_file(hybas_file).to_crs(AREA_CRS)
    basins = basins[basins.intersects(system)].copy()
    full = basins.geometry.area
    basins["geometry"] = basins.geometry.intersection(system)
    basins["area"] = basins.geometry.area
    basins = basins[basins["area"] / full >= MIN_OVERLAP].set_index("HYBAS_ID")
    basins["sdl_unit"] = pd.DataFrame({u: basins.geometry.intersection(g).area for u, g in polys.items()}).idxmax(axis=1)

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
    stem_outlets = []
    for k in range(1, n + 1):
        node = next(i for i in stem if up_area(i) >= k / n * total * 0.9999)
        if node not in stem_outlets:
            stem_outlets.append(node)
    if stem[-1] not in stem_outlets:
        stem_outlets.append(stem[-1])
    crossings = [i for i, d in nxt.items() if basins.at[i, "sdl_unit"] != basins.at[d, "sdl_unit"]]
    networks = [s for s in sinks if s != outlet and min_network_km2 is not None and up_area(s) >= min_network_km2 * 1e6]
    outlets = sorted(set(stem_outlets) | set(crossings) | set(networks), key=up_area)  # roughly upstream to downstream

    def region_of(i):
        while i not in outlets:
            if i not in nxt:
                return None
            i = nxt[i]
        return i

    basins["region"] = [region_of(i) for i in basins.index]
    kept = basins.dropna(subset=["region"]).copy()
    kept["region"] = kept["region"].astype(type(outlet))
    unit_of = kept["sdl_unit"].to_dict()
    unit_outlet = {u: max((i for i in kept.index if unit_of[i] == u), key=up_area) for u in set(unit_of.values())}
    from_outlet = {o: len(stem_outlets) - stem_outlets.index(o) for o in stem_outlets}

    code, count = {}, {}
    for out in outlets:
        u = unit_of[out]
        count[u] = count.get(u, 0) + 1
        code[out] = f"{u}-SC{count[u]:02d}"
    rows = []
    for order, out in enumerate(outlets, start=1):
        geom = kept.loc[kept["region"] == out].geometry.union_all()
        ups = sorted(code[o] for o in outlets if o in nxt and region_of(nxt[o]) == out)
        down = region_of(nxt[out]) if out in nxt else None
        rows.append({
            "subcatchment": code[out], "sdl_unit": unit_of[out], "route_order": order,
            "region_name": f"Reach {code[out].split('-SC')[1].lstrip('0')} (outlet HYBAS {out})",
            "upstream_boundary": ", ".join(f"{o} outlet" for o in ups) or "Headwaters",
            "downstream_boundary": f"{code[down]} (flows on)" if down else ("System outlet" if out == outlet else "Leaves the system"),
            "area_km2": geom.area / 1e6, "outlet_basin": f"B{out}", "unit_outlet": f"B{unit_outlet[unit_of[out]]}", "geometry": geom,
        })
    covered = kept.geometry.union_all()
    lowlands = []
    for u, poly in polys.items():
        rest = poly.difference(covered)
        if u not in unit_outlet or rest.area < MIN_LOWLAND * poly.area:
            print(f"1_masking: {u} leftover {rest.area / 1e6:.0f} km2 outside the terrain reaches, dropped")
            continue
        sc = f"{u}-SC{count.get(u, 0) + 1:02d}"
        rows.append({
            "subcatchment": sc, "sdl_unit": u, "route_order": len(rows) + 1,
            "region_name": "Lowland plains (no terrain-defined drainage)",
            "upstream_boundary": "Plains", "downstream_boundary": f"{u} outlet",
            "area_km2": rest.area / 1e6, "outlet_basin": f"B{unit_outlet[u]}", "unit_outlet": f"B{unit_outlet[u]}", "geometry": rest,
        })
        lowlands.append({"subcatchment": f"LOWLAND-{u}", "hybas_id": 0, "next_id": f"B{unit_outlet[u]}", "region": sc, "sdl_unit": u,
                         "from_outlet": 0, "area_km2": rest.area / 1e6, "geometry": rest})
    regions = gpd.GeoDataFrame(rows, crs=AREA_CRS).to_crs(units.crs)

    if networks:  # routing calibrates at the first basin with no downstream link, so keep the system outlet first
        kept = kept.loc[[outlet] + [i for i in kept.index if i != outlet]]
    kept["subcatchment"] = [f"B{i}" for i in kept.index]
    kept["next_id"] = [f"B{nxt[i]}" if i in nxt else "" for i in kept.index]
    kept["from_outlet"] = kept["region"].map(lambda o: from_outlet.get(o, 0)).astype(int)
    kept["region"] = kept["region"].map(code)
    kept["area_km2"] = kept.geometry.area / 1e6
    kept.index.name = "hybas_id"
    columns = ["subcatchment", "hybas_id", "next_id", "region", "sdl_unit", "from_outlet", "area_km2", "geometry"]
    network = pd.concat([kept.reset_index()[columns], gpd.GeoDataFrame(lowlands, columns=columns, crs=AREA_CRS)], ignore_index=True)
    return regions, gpd.GeoDataFrame(network, crs=AREA_CRS).to_crs(units.crs)
