"""Flow for every mapped river and creek, from the routed basin network and the unit runoff.

Each basin's main channel carries the routed flow leaving that basin. Other rivers inside a basin share that
basin's own runoff by length, and rivers on the lowland plains share the lowland unit's delivered flow by length.
The shares are indicative (an even split by length), not routed.
"""
import geopandas as gpd
import pandas as pd

from config import MAINSTEM, SYSTEM, WATERWAYS_FILE

MIN_KM = 3  # skip river groups shorter than this inside a basin
KM_PER_DEG = 111


def _channel(candidates, geom, prefer=None):
    """River pieces inside geom that share the name with the most length (the main stem wins if present)."""
    pieces = candidates.geometry.intersection(geom)
    length = pieces[pieces.length > 0].length
    if length.empty:
        return None, "", set()
    by_name = length.groupby(candidates.loc[length.index, "name"]).sum()
    name = prefer if prefer in by_name.index and by_name[prefer] * KM_PER_DEG > 5 else by_name.idxmax()
    chosen = [i for i in length.index if candidates.at[i, "name"] == name]
    return pieces.loc[chosen].union_all(), name, set(chosen)


def _groups(ways, geom, skip):
    """River pieces inside geom (excluding the main stem and ``skip``), grouped by name: (name, line, km)."""
    pieces = ways.geometry.intersection(geom)
    keep = pieces[(pieces.length > 0) & (~ways.index.isin(skip)) & (ways["name"] != MAINSTEM)]
    out = []
    for name, idx in ways.loc[keep.index].groupby("name").groups.items():
        line = pieces.loc[idx].union_all()
        if line.length * KM_PER_DEG >= MIN_KM:
            out.append((name, line, line.length * KM_PER_DEG))
    return out


def river_flows(basins, lateral, basin_flow):
    """Return (rivers, river_flow).

    rivers: one row per river segment with ``river_id`` (numbered per SDL unit), ``name``, ``basin``, ``sdl_unit``,
    ``kind`` (channel / tributary / lowland), ``share`` and a line geometry. river_flow: daily flow (ML/d) per ``river_id``.
    ``lateral`` is each basin's runoff reaching the river (ML/d) and ``basin_flow`` the routed flow leaving it.
    """
    allways = gpd.read_file(WATERWAYS_FILE)
    allways = allways[~allways["name"].isin(SYSTEM.get("other_rivers", ()))]  # rivers of other systems that cross this one
    ways = allways[allways.waterway == "river"].reset_index(drop=True)
    streams = allways[allways.waterway == "stream"].reset_index(drop=True)

    rows, series, count = [], {}, {}
    lowland = basins["subcatchment"].str.startswith("LOWLAND")

    def add(basin, name, line, kind, share, flow):
        unit = basins.loc[basins["subcatchment"] == basin, "sdl_unit"].iloc[0]
        count[unit] = count.get(unit, 0) + 1
        river_id = f"{unit}-R{count[unit]:03d}"
        rows.append({"river_id": river_id, "name": name or "Unnamed river", "basin": basin, "sdl_unit": unit, "kind": kind,
                     "share": share, "geometry": line})
        series[river_id] = flow

    for basin in basins[~lowland].itertuples():
        b = basin.subcatchment
        line, name, chosen = _channel(ways, basin.geometry, prefer=MAINSTEM)
        if line is None:  # headwater basin with no mapped river: fall back to its longest stream
            line, name, _ = _channel(streams, basin.geometry)
        if line is not None:
            add(b, name, line, "channel", 1.0, basin_flow[b])
        side = _groups(ways, basin.geometry, chosen)
        total = sum(km for _, _, km in side)
        for gname, gline, km in side:
            add(b, gname, gline, "tributary", km / total, lateral[b] * km / total)

    for basin in basins[lowland].itertuples():
        plains = _groups(ways, basin.geometry, set())
        total = sum(km for _, _, km in plains)
        for gname, gline, km in plains:
            add(basin.subcatchment, gname, gline, "lowland", km / total, lateral[basin.subcatchment] * km / total)

    return gpd.GeoDataFrame(rows, crs=basins.crs), pd.DataFrame(series)
