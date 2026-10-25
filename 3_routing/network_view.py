"""Where the routing nodes sit on the river, and which of them the river network keeps.

The terrain tree has a node for every terrain watershed, linked through HydroBASINS, which is far finer than the river.
This puts each node where the river runs through its own watershed and keeps only the points that matter along the
river (a confluence of branches draining enough area, a storage, a basin or system outlet, a flow split). The rest fold
into the node below them on the river, joining it with no channel of their own, and the kept nodes are joined by the
river's own path, whose length sets each reach.
"""
import heapq
import sys
from collections import defaultdict

import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.ops import substring

MAX_OFF_RIVER_KM = 5  # a watershed whose nearest mapped river is further than this has no river to sit on
BRIDGE_DEG = 0.05  # separate river pieces are joined across gaps up to this (~5 km), nearest first: basin borders, gaps in the mapping
T_JOIN_DEG = 0.01  # a river ending within this (~1 km) of another joins it there
KM_PER_DEG = 111
MIN_TRIBUTARY_KM2 = 500  # a branch draining less than this above its mouth is folded into the river it joins
DETOUR = 2.5  # a river path more than this times longer than the straight line is not the same river: draw the straight line


def _river_point(line, pt):
    """The point of ``line`` nearest ``pt``."""
    return shapely.ops.nearest_points(line, pt)[0]


def _pieces(lines, points):
    """``lines`` (LineStrings) cut at ``points`` (each on or very near one of them) and where another line's end meets them
    (a tributary that stops short of its river): returns (the pieces as coordinate lists, [(end, cut)] gaps to bridge)."""
    tree = shapely.STRtree(lines)
    cuts, bridges = defaultdict(list), []
    for p in points:
        i = int(tree.nearest(p))
        cuts[i].append(lines[i].project(p))
    for i, line in enumerate(lines):
        for end in (shapely.Point(line.coords[0]), shapely.Point(line.coords[-1])):
            near = [j for j in tree.query(end.buffer(T_JOIN_DEG)) if j != i]
            if near:
                j = min(near, key=lambda j: lines[j].distance(end))
                at = lines[j].project(end)
                q = lines[j].interpolate(at)
                if 0 < end.distance(q) <= T_JOIN_DEG:
                    cuts[j].append(at)
                    bridges.append((end.coords[0], q.coords[0]))
    out = []
    for i, line in enumerate(lines):
        at = sorted({0.0, line.length, *cuts.get(i, [])})
        for a, b in zip(at, at[1:]):
            if b > a:
                out.append(list(substring(line, a, b).coords))
    return out, bridges


def _graph(pieces, bridges):
    """Adjacency of the river pieces: {node: [(neighbour, length, coords oriented from the node)]}, nodes keyed by rounded position."""
    key = lambda c: (round(c[0], 5), round(c[1], 5))
    adj, ends = defaultdict(list), set()

    def link(a, b, length, coords):
        adj[a].append((b, length, coords))
        adj[b].append((a, length, coords[::-1]))

    for coords in pieces:
        a, b = key(coords[0]), key(coords[-1])
        if a != b:
            link(a, b, sum(np.hypot(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in zip(coords, coords[1:])), coords)
            ends |= {a, b}
    for e, q in bridges:
        a, b = key(e), key(q)
        if a != b and a in adj and b in adj:
            link(a, b, float(np.hypot(a[0] - b[0], a[1] - b[1])), [a, b])
    ends = list(ends)
    parent = {n: n for n in ends}

    def root(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for a in ends:
        for b, _, _ in adj[a]:
            parent[root(a)] = root(b)
    pairs = sorted((float(np.hypot(ends[i][0] - ends[j][0], ends[i][1] - ends[j][1])), i, j) for i, j in cKDTree(ends).query_pairs(BRIDGE_DEG))
    for d, i, j in pairs:  # reconnect pieces cut apart (at the basin borders, or a gap in the mapping), nearest first
        a, b = ends[i], ends[j]
        if root(a) != root(b):
            link(a, b, d, [a, b])
            parent[root(a)] = root(b)
    return adj, key


def _path(adj, src, dst):
    """Shortest river path between two graph nodes as (coordinates, length), or None."""
    best, back, queue = {src: 0.0}, {}, [(0.0, src)]
    while queue:
        d, n = heapq.heappop(queue)
        if n == dst:
            break
        if d > best.get(n, np.inf):
            continue
        for m, w, coords in adj[n]:
            if d + w < best.get(m, np.inf):
                best[m], back[m] = d + w, (n, coords)
                heapq.heappush(queue, (d + w, m))
    if dst not in best:
        return None
    parts, n = [], dst
    while n != src:
        n, coords = back[n]
        parts.append(coords)
    coords = [c for part in parts[::-1] for c in part]
    return coords, best[dst]


def river_view(nodes, watersheds, river_lines, storages=None, fixed=()):
    """Place ``nodes`` (the frame ``build_nodes`` builds before this step) on the river and keep the river nodes.

    ``watersheds`` is each node's polygon (EPSG:4326, indexed by node id), ``river_lines`` the mapped rivers (EPSG:4326
    geometries), ``storages`` {name: {lon, lat, ...}} and ``fixed`` node ids that always stay. Returns ``spot`` {kept node:
    (lon, lat) on the river}, ``next`` {every node: the kept node it drains into, '' at an outlet}, and for each kept node
    that drains on: ``path`` ([lon, lat] points along the river to its next node), ``km`` (that path's length) and ``straight``
    (the nodes with no mapped channel to the next one, so a straight line).
    """
    storages = storages or {}
    lines = [g for geom in river_lines for g in shapely.get_parts(shapely.line_merge(geom)) if g.length > 0]
    union = shapely.union_all(lines)
    row = nodes.set_index("id")
    drain = {i: shapely.Point(r.lon, r.lat) for i, r in row.iterrows()}

    # where each node sits on the river: in its own watershed if the river runs through it, else the nearest river close by
    spot = {}
    for i in row.index:
        poly = watersheds.get(i)
        if row.at[i, "storage"]:
            s = storages[row.at[i, "storage"]]
            pt = shapely.Point(s["lon"], s["lat"])
        else:
            inside = shapely.intersection(union, poly) if poly is not None and not poly.is_empty else None
            if inside is not None and not inside.is_empty:
                pt = shapely.ops.nearest_points(inside, drain[i])[0]
            else:
                pt = None
        if pt is None:
            near = _river_point(union, drain[i])
            pt = near if drain[i].distance(near) * KM_PER_DEG <= MAX_OFF_RIVER_KM else None
        elif row.at[i, "storage"]:
            near = _river_point(union, pt)
            pt = near if pt.distance(near) * KM_PER_DEG <= MAX_OFF_RIVER_KM else pt
        spot[i] = pt

    down = {i: row.at[i, "next"] or None for i in row.index}

    def first(i, keep):  # the nearest node at or below i that is in ``keep``
        while i is not None and i not in keep:
            i = down[i]
        return i

    # the nodes that stand on the river, then of those only where something happens: a confluence, a storage, an outlet
    upstream = defaultdict(list)
    for i, d in down.items():
        if d:
            upstream[d].append(i)
    drained = {}

    def area(i):  # everything draining through the node, itself included
        if i not in drained:
            drained[i] = float(row.at[i, "area_km2"]) + sum(area(c) for c in upstream[i])
        return drained[i]

    sys.setrecursionlimit(max(sys.getrecursionlimit(), 4 * len(row) + 1000))
    on_river = {i for i in row.index if row.at[i, "storage"] or down[i] is None or i in fixed or (spot[i] is not None and area(i) >= MIN_TRIBUTARY_KM2 and not i.startswith("LOWLAND"))}  # the plains have no channel to sit on
    for i in on_river:
        if spot[i] is None:
            spot[i] = drain[i]
    kept = set(on_river)
    while True:
        feeders = defaultdict(set)
        for i in kept:
            d = first(down[i], kept) if down[i] else None
            if d is not None:
                feeders[d].add(i)
        drop = {i for i in kept if not row.at[i, "storage"] and down[i] is not None and i not in fixed and len(feeders[i]) == 1}
        if not drop:
            break
        kept -= drop
    feeders = defaultdict(set)
    for i in kept:
        d = first(down[i], kept) if down[i] else None
        if d is not None:
            feeders[d].add(i)

    pts = [spot[i] for i in kept]
    adj, key = _graph(*_pieces(lines, pts))
    out = {"spot": {}, "next": {}, "path": {}, "km": {}, "straight": set()}
    for i in row.index:
        d = first(down[i], kept) if down[i] else None
        out["next"][i] = d or ""
        if i not in kept:
            continue
        out["spot"][i] = (round(spot[i].x, 4), round(spot[i].y, 4))
        if d is None:
            continue
        a, b = spot[i], spot[d]
        route = _path(adj, key((a.x, a.y)), key((b.x, b.y)))
        straight = float(np.hypot(a.x - b.x, a.y - b.y))
        along = route is not None and route[1] <= DETOUR * max(straight, 1e-6)
        path = [(a.x, a.y), *(route[0] if along else []), (b.x, b.y)]
        out["path"][i] = [[round(x, 4), round(y, 4)] for x, y in shapely.simplify(shapely.LineString(path), 0.001).coords]
        out["km"][i] = _km(path)
        if not along:
            out["straight"].add(i)
    return out


def _km(path):
    """Length of a [lon, lat] path in km."""
    xy = np.asarray(path, dtype=float)
    dx = np.diff(xy[:, 0]) * np.cos(np.radians(xy[:-1, 1])) * KM_PER_DEG
    return float(np.hypot(dx, np.diff(xy[:, 1]) * KM_PER_DEG).sum())
