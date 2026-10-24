"""Flow for every mapped river and creek, from the routed basin network and the unit runoff.

Each basin's main channel carries the routed flow leaving that basin. Other rivers inside a basin share that
basin's own runoff by length, and rivers on the lowland plains share the lowland unit's delivered flow by length.
The shares are indicative (an even split by length), not routed.
"""
import geopandas as gpd
import pandas as pd
import shapely

from catchment import load_buffered_catchment
from config import MAINSTEM, OUTLINE_BUFFER_CRS, SYSTEM, WATERWAYS_FILE

MIN_KM = 3  # skip river groups shorter than this inside a basin
KM_PER_DEG = 111
SEGMENT_DEG = 0.01  # river pieces outside the basins are cut to about this length before each goes to its nearest basin


def _outside(ways, basins):
    """River pieces inside the buffered outline (OUTLINE_BUFFER_KM beyond the SDL units) but outside every basin, which
    is the strip along the exterior border that the basins, cut to the units, do not cover. Each piece goes to the
    nearest basin: {basin: GeoSeries of pieces indexed like ``ways``}."""
    zone = load_buffered_catchment().difference(basins.geometry.union_all())
    pieces = ways.geometry.intersection(zone)
    pieces = pieces[~pieces.is_empty]
    if pieces.empty:
        return {}
    segments = gpd.GeoDataFrame({"way": pieces.index}, geometry=shapely.segmentize(pieces.values, SEGMENT_DEG), crs=ways.crs).explode(index_parts=False).reset_index(drop=True)
    segments = segments[segments.length > 0]
    mid = gpd.GeoDataFrame({"way": segments["way"].values}, geometry=segments.geometry.interpolate(0.5, normalized=True).values, crs=ways.crs)
    nearest = gpd.sjoin_nearest(mid.to_crs(OUTLINE_BUFFER_CRS), basins[["subcatchment", "geometry"]].to_crs(OUTLINE_BUFFER_CRS))
    nearest = nearest[~nearest.index.duplicated()]
    segments["basin"] = nearest["subcatchment"].reindex(segments.index).values
    return {b: g.groupby("way").geometry.apply(lambda x: x.union_all()) for b, g in segments.groupby("basin")}


def _pieces(ways, geom, extra=None):
    """The river pieces inside ``geom`` plus, if given, the pieces ``extra`` hands this basin from beyond the unit border."""
    pieces = ways.geometry.intersection(geom)
    if extra is not None and len(extra):
        add = extra.reindex(pieces.index)
        add = [g if g is not None else shapely.LineString() for g in add.values]
        pieces = gpd.GeoSeries(shapely.union(pieces.values, add), index=pieces.index, crs=ways.crs)
    return pieces


def _channel(candidates, geom, prefer=None, extra=None):
    """River pieces inside geom that share the name with the most length (the main stem wins if present)."""
    pieces = _pieces(candidates, geom, extra)
    length = pieces[pieces.length > 0].length
    if length.empty:
        return None, "", set()
    by_name = length.groupby(candidates.loc[length.index, "name"]).sum()
    name = prefer if prefer in by_name.index and by_name[prefer] * KM_PER_DEG > 5 else by_name.idxmax()
    chosen = [i for i in length.index if candidates.at[i, "name"] == name]
    return pieces.loc[chosen].union_all(), name, set(chosen)


def _groups(ways, geom, skip, extra=None):
    """River pieces inside geom (excluding the main stem and ``skip``), grouped by name: (name, line, km). Pieces from
    beyond the unit border (``extra``) keep the main stem too: a river along the exterior border has no channel of its
    own in a basin that the units cut away, so it is not already drawn as one."""
    pieces = _pieces(ways, geom).where(ways["name"] != MAINSTEM, shapely.LineString())
    if extra is not None and len(extra):
        add = extra.reindex(pieces.index)
        pieces = gpd.GeoSeries(shapely.union(pieces.values, [g if g is not None else shapely.LineString() for g in add.values]), index=pieces.index, crs=ways.crs)
    keep = pieces[(pieces.length > 0) & (~ways.index.isin(skip))]
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

    beyond, beyond_streams = _outside(ways, basins), _outside(streams, basins)  # rivers along the exterior border, past the units

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
        line, name, chosen = _channel(ways, basin.geometry, prefer=MAINSTEM, extra=beyond.get(b))
        if line is None:  # headwater basin with no mapped river: fall back to its longest stream
            line, name, _ = _channel(streams, basin.geometry, extra=beyond_streams.get(b))
        if line is not None:
            add(b, name, line, "channel", 1.0, basin_flow[b])
        side = _groups(ways, basin.geometry, chosen, beyond.get(b))
        total = sum(km for n, _, km in side if n != MAINSTEM)
        for gname, gline, km in side:
            share = 0.0 if gname == MAINSTEM else km / total  # the main stem past the border is not routed here: kept, with no flow
            add(b, gname, gline, "tributary", share, lateral[b] * share)

    for basin in basins[lowland].itertuples():
        plains = _groups(ways, basin.geometry, set(), beyond.get(basin.subcatchment))
        total = sum(km for n, _, km in plains if n != MAINSTEM)
        for gname, gline, km in plains:
            share = 0.0 if gname == MAINSTEM else km / total
            add(basin.subcatchment, gname, gline, "lowland", share, lateral[basin.subcatchment] * share)

    return gpd.GeoDataFrame(rows, crs=basins.crs), pd.DataFrame(series)
