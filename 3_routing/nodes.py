"""Routing nodes: the finer terrain watersheds (HydroBASINS level 10) inside the modelled basins (level 8).

Rainfall-runoff still runs once per basin; its runoff is shared out to the basin's nodes by area, and each node's share
enters the river where that node's watershed drains into the next one down. Storages sit on the node containing them.
"""
import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from config import HYBAS_FILE, HYBAS_NODE_FILE, SYSTEMS, waterways_file
from network_view import river_view
from terrain_regions import AREA_CRS

MAX_GAP_KM = 40  # a straight link (no mapped river between two nodes) longer than this is not drawn or routed: the stream ends
MIN_SHARE = 1e-4  # a level-10 watershed with less than this share of its basin inside the system is dropped


def _outlet_points(geoms, next_geoms):
    """Where each watershed drains into the next one down: the middle of their shared boundary, else its own interior point."""
    out = []
    for g, h in zip(geoms, next_geoms):
        pt = None
        if h is not None:
            shared = shapely.intersection(shapely.boundary(g), shapely.boundary(h))
            if not shared.is_empty:
                pt = shapely.line_interpolate_point(shapely.line_merge(shared), 0.5, normalized=True) if shared.geom_type in ("LineString", "MultiLineString") else shared.centroid
        out.append(pt if pt is not None and not pt.is_empty else g.representative_point())
    return out


def build_nodes(basins, system):
    """Routing nodes for a system's ``basins`` (the frame ``terrain_regions`` returns, EPSG:4326 or any CRS).

    Returns a DataFrame indexed like the node order (upstream-agnostic) with columns id, basin (the level-8 basin or
    lowland whose runoff it takes), share (of that basin's runoff), area_km2, length_km (NaN: fall back to the area rule),
    next ('' at a system outlet), lon, lat (where it enters the river), loss_rank (the basin's from_outlet, at the basin's
    outlet node only), outlet (True at a basin's outlet node, whose flow is the basin's flow) and storage ('' or the name of
    the one of ``storages`` ({name: {lon, lat, ...}}) that sits in it). ``attrs["watersheds"]`` holds each node's polygon (EPSG:4326).
    """
    storages = SYSTEMS[system].get("storages", {})
    land = basins[~basins["subcatchment"].str.startswith("LOWLAND")]
    parent_geom = land.set_index("hybas_id").to_crs(AREA_CRS).geometry
    pfaf = gpd.read_file(HYBAS_FILE, ignore_geometry=True, columns=["HYBAS_ID", "PFAF_ID"]).set_index("HYBAS_ID")["PFAF_ID"]
    parent_of_pfaf = {pfaf[h]: h for h in land["hybas_id"]}
    bounds = tuple(land.to_crs("EPSG:4326").total_bounds)
    fine = gpd.read_file(HYBAS_NODE_FILE, bbox=bounds)
    fine = fine[(fine["PFAF_ID"] // 100).isin(parent_of_pfaf)].set_index("HYBAS_ID")
    fine["parent"] = [parent_of_pfaf[p // 100] for p in fine["PFAF_ID"]]
    fine = fine.to_crs(AREA_CRS)
    inside = shapely.intersection(fine.geometry.values, parent_geom.loc[fine["parent"]].values)
    fine["w"] = shapely.area(inside)
    total = fine.groupby("parent")["w"].transform("sum")
    fine["share"] = fine["w"] / total
    fine = fine[fine["share"] >= MIN_SHARE].copy()
    fine["share"] /= fine.groupby("parent")["share"].transform("sum")

    kept = set(fine.index)
    basin_of = dict(zip(land["hybas_id"], land["subcatchment"]))
    next_basin = dict(zip(land["hybas_id"], land["next_id"]))
    to_hybas = {sc: h for h, sc in basin_of.items()}

    def kept_next(i):
        d = fine.at[i, "NEXT_DOWN"]
        return d if d in kept else None

    # each basin's outlet node: a node draining beyond the basin (or whose drain was dropped), preferring the biggest
    outlet = {}
    for h, group in fine.groupby("parent"):
        exits = [i for i in group.index if kept_next(i) is None or fine.at[kept_next(i), "parent"] != h]
        outlet[h] = max(exits or group.index, key=lambda i: fine.at[i, "UP_AREA"])
    ids = {i: f"N{i}" for i in fine.index}
    outlet_id = {basin_of[h]: ids[o] for h, o in outlet.items()}

    nxt = {}
    for i in fine.index:
        h, d = fine.at[i, "parent"], kept_next(i)
        if d is not None and not (outlet[h] == i and fine.at[d, "parent"] == h):
            nxt[i] = ids[d]
        elif outlet[h] != i:
            nxt[i] = ids[outlet[h]]  # drain dropped (outside the system): join the basin's outlet node
        else:
            nxt[i] = outlet_id.get(next_basin[h], "")  # basin's downstream link, else a system outlet

    down_geom = [fine.geometry.get(kept_next(i)) if kept_next(i) is not None else None for i in fine.index]
    pts = gpd.GeoSeries(_outlet_points(fine.geometry.values, down_geom), index=fine.index, crs=AREA_CRS).to_crs("EPSG:4326")
    dist = fine["DIST_SINK"]
    length = pd.Series({i: dist[i] - dist[kept_next(i)] if kept_next(i) is not None else np.nan for i in fine.index})
    loss_rank = dict(zip(land["subcatchment"], land["from_outlet"]))
    rows = [{"id": ids[i], "basin": basin_of[fine.at[i, "parent"]], "share": float(fine.at[i, "share"]),
             "area_km2": float(fine.at[i, "w"] / 1e6), "length_km": float(length[i]) if length[i] > 0 else np.nan, "next": nxt[i],
             "lon": round(pts[i].x, 4), "lat": round(pts[i].y, 4), "outlet": outlet[fine.at[i, "parent"]] == i,
             "loss_rank": int(loss_rank[basin_of[fine.at[i, "parent"]]]) if outlet[fine.at[i, "parent"]] == i else 0, "storage": ""}
            for i in fine.index]

    for low in basins[basins["subcatchment"].str.startswith("LOWLAND")].itertuples():  # the plains drain into their unit's outlet basin
        p = low.geometry.representative_point()
        rows.append({"id": low.subcatchment, "basin": low.subcatchment, "share": 1.0, "area_km2": float(low.area_km2), "length_km": np.nan,
                     "next": outlet_id.get(low.next_id, ""), "lon": round(p.x, 4), "lat": round(p.y, 4), "outlet": True, "loss_rank": 0, "storage": ""})
    nodes = pd.DataFrame(rows)
    fine_deg = fine.to_crs("EPSG:4326")
    _place_storages(nodes, fine_deg, ids, storages)
    plains = basins[basins["subcatchment"].str.startswith("LOWLAND")].to_crs("EPSG:4326")
    watersheds = pd.concat([pd.Series(fine_deg.geometry.values, index=[ids[i] for i in fine_deg.index]), pd.Series(plains.geometry.values, index=plains["subcatchment"].values)])
    return _along_river(nodes, watersheds, system)


def _along_river(nodes, watersheds, system):
    """Move the nodes onto the river: keep the river nodes and fold the rest into the one they drain to along it.

    A kept node sits on the river inside its own watershed, and its reach to the next kept node is the river's path
    between them (``length_km``). A folded node (``river`` False) keeps its runoff share but joins its kept node directly,
    with no channel of its own (length 0), so everything between two river points is one segment. ``path`` holds the
    [lon, lat] points of a kept node's reach, ``straight`` marks one with no mapped channel to follow.
    """
    spec = SYSTEMS[system]
    splits, outlet = spec.get("splits", {}), dict(zip(nodes.loc[nodes["outlet"], "basin"], nodes.loc[nodes["outlet"], "id"]))
    ends = set(nodes.loc[nodes["outlet"] & ~nodes["basin"].str.startswith("LOWLAND"), "id"]) | {n for b, to in splits.items() for n in [outlet[b], *(outlet[t] for t in to if t)]}
    ways = gpd.read_file(waterways_file(system))
    ways = ways[(ways.waterway == "river") & ~ways["name"].isin(spec.get("other_rivers", ()))]
    reach = shapely.union_all(watersheds.values).buffer(0.05)
    lines = [g for g in shapely.intersection(ways.geometry.values, reach) if not g.is_empty]
    view = river_view(nodes, watersheds, lines, spec.get("storages"), ends)
    nodes = nodes.copy()
    nodes["river"] = nodes["id"].isin(view["spot"])
    nodes["next"] = nodes["id"].map(view["next"])
    lon, lat = zip(*[view["spot"].get(i, (a, b)) for i, a, b in zip(nodes["id"], nodes["lon"], nodes["lat"])])
    nodes["lon"], nodes["lat"] = lon, lat
    nodes["length_km"] = [view["km"].get(i, 0.0 if r else np.nan) for i, r in zip(nodes["id"], nodes["river"])]
    nodes.loc[~nodes["river"], "length_km"] = 0.0
    nodes["path"] = nodes["id"].map(view["path"])
    nodes["straight"] = nodes["id"].isin(view["straight"])
    cut = nodes["straight"] & (nodes["length_km"] > MAX_GAP_KM)  # a river with no mapped channel to the next one, far off: its water ends here
    nodes.loc[cut, "next"], nodes.loc[cut, "length_km"], nodes.loc[cut, "straight"] = "", np.nan, False
    nodes.loc[cut, "path"] = None
    nodes["split_path"] = None
    for basin, name in spec.get("split_rivers", {}).items():
        i = nodes.index[nodes["id"] == outlet[basin]][0]
        pieces = [list(g.coords) for g in shapely.get_parts(shapely.line_merge(shapely.union_all(ways.geometry[ways["name"] == name].values)))]
        coords, here = [], (nodes.at[i, "lon"], nodes.at[i, "lat"])
        while pieces:  # chain the mapped pieces from the one nearest the offtake, each next one by its nearest end
            gap = lambda c: np.hypot(c[0] - (coords[-1] if coords else here)[0], c[1] - (coords[-1] if coords else here)[1])
            k, flip = min(((k, f) for k in range(len(pieces)) for f in (0, 1)), key=lambda t: gap(pieces[t[0]][-1 if t[1] else 0]))
            if gap(pieces[k][-1 if flip else 0]) > 0.1:
                break
            piece = pieces.pop(k)
            coords += piece[::-1] if flip else piece
        line = shapely.LineString(coords)
        nodes.at[i, "split_path"] = [[round(x, 4), round(y, 4)] for x, y in shapely.simplify(line, 0.001).coords]
    return nodes


def _place_storages(nodes, fine, ids, storages):
    """Mark the node each of the system's storages sits in (the watershed containing it, else the nearest within 15 km)."""
    for name, s in storages.items():
        pt = shapely.Point(s["lon"], s["lat"])
        hit = fine[fine.geometry.contains(pt)]
        if hit.empty:
            near = fine.geometry.distance(pt) * 111
            if near.min() > 15:
                raise ValueError(f"storage {name} at {s['lon']}, {s['lat']} is not inside the system's watersheds")
            hit = fine.loc[[near.idxmin()]]
        node = ids[hit.index[0]]
        row = nodes.index[nodes["id"] == node]
        if nodes.at[row[0], "storage"]:
            raise ValueError(f"storages {nodes.at[row[0], 'storage']} and {name} fall in the same node")
        nodes.at[row[0], "storage"] = name
