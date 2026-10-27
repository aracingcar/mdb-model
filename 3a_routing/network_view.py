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
BRIDGE_DEG = 0.2  # separate river pieces are joined across gaps up to this (~5 km), nearest first: basin borders, gaps in the mapping
T_JOIN_DEG = 0.01  # a river ending within this (~1 km) of another joins it there
KM_PER_DEG = 111
MIN_TRIBUTARY_KM2 = 500  # a branch draining less than this above its mouth is folded into the river it joins
JUNCTION_SLACK_DEG = 0.02  # a confluence node moves up to where its branches meet only if that is within ~2 km of its own watershed
DETOUR = 6  # a river path more than this times longer than the straight line is not the same river: draw the straight line
MAIN_SNAP_DEG = 0.02  # a watershed the main river runs through within ~2 km of its drain sits on the main river, not a nearer side channel
MAIN_THROUGH_DEG = 0.05  # runs through: ~5 km of it inside the watershed (a tributary's watershed only touches it at the mouth)


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
    """Shortest river path between two graph nodes as (coordinates, length, graph nodes passed from src to dst), or None."""
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
    parts, passed, n = [], [dst], dst
    while n != src:
        n, coords = back[n]
        parts.append(coords)
        passed.append(n)
    coords = [c for part in parts[::-1] for c in part]
    return coords, best[dst], passed[::-1]


def _junction(routes):
    """Where river paths (lists of graph nodes) first all meet, or None if there are fewer than two."""
    if len(routes) < 2:
        return None
    rest = [set(r) for r in routes[1:]]
    return next(n for n in routes[0] if all(n in r for r in rest))


def river_view(nodes, watersheds, river_lines, storages=None, fixed=(), pinned=(), main_lines=()):
    """Place ``nodes`` (the frame ``build_nodes`` builds before this step) on the river and keep the river nodes.

    ``watersheds`` is each node's polygon (EPSG:4326, indexed by node id), ``river_lines`` the mapped rivers (EPSG:4326
    geometries), ``main_lines`` those of them that are the system's main river, ``storages`` {name: {lon, lat, ...}},
    ``fixed`` node ids that always stay and ``pinned`` those of them
    that keep their own spot rather than move up to a confluence (flow splits). Returns ``spot`` {kept node:
    (lon, lat) on the river}, ``next`` {every node: the kept node it drains into, '' at an outlet}, and for each kept node
    that drains on: ``path`` ([lon, lat] points along the river to its next node), ``km`` (that path's length), ``straight``
    (the nodes with no mapped channel to the next one, so a straight line) and ``side`` (the basin outlets placed inside their
    catchment, whose straight reach is a stand-in for an unmapped creek).
    """
    storages = storages or {}
    lines = [g for geom in river_lines for g in shapely.get_parts(shapely.line_merge(geom)) if g.length > 0]
    union = shapely.union_all(lines)
    main = shapely.union_all(list(main_lines)) if len(main_lines) else None
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
            on_main = shapely.intersection(main, poly) if main is not None and inside is not None else None
            # an anabranch or creek beside the main river can pass nearer the drain; on it the node misses the main river's reaches
            if on_main is not None and on_main.length >= MAIN_THROUGH_DEG and on_main.distance(drain[i]) <= MAIN_SNAP_DEG:
                inside = on_main
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
    adj, key = _graph(*_pieces(lines, [spot[i] for i in on_river]))
    at_key = lambda i: key((spot[i].x, spot[i].y))
    lateral = set()  # watersheds along another branch's river with no channel of their own: they fold into the node below
    while True:
        kept = on_river - lateral
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
        # a confluence node sits where its branches meet, not lower down its watershed, or their reaches would run on together;
        # a branch that starts on another branch's path down to it is no branch, just runoff entering along that river
        moved, alongside, side = {}, set(), set()
        for d, feeds in feeders.items():
            if len(feeds) < 2 or row.at[d, "storage"] or d in pinned or watersheds.get(d) is None:
                continue
            routes = {f: r[2] for f in feeds if (r := _path(adj, at_key(f), at_key(d))) is not None}
            on_branch = {f for f in routes if not feeders.get(f) and not row.at[f, "storage"] and any(at_key(f) in r for g, r in routes.items() if g != f)}
            alongside |= on_branch - set(fixed)
            side |= on_branch & set(fixed)
            at = _junction(list(routes.values()))
            if at is not None and watersheds[d].buffer(JUNCTION_SLACK_DEG).contains(shapely.Point(at)):
                moved[d] = shapely.Point(at)
        if not alongside:
            break
        lateral |= alongside
    spot.update(moved)
    # a basin outlet that must stay but has no mapped channel of its own (its creek is not in the river layer) would sit on
    # the junction it drains to: it goes inside its catchment instead, joined to the junction by a straight unmapped reach
    def catchment(i):
        return [i] + [j for c in upstream[i] for j in catchment(c)]
    for f in side:
        spot[f] = shapely.union_all([watersheds[j] for j in catchment(f) if watersheds.get(j) is not None]).representative_point()
    out = {"spot": {}, "next": {}, "path": {}, "km": {}, "straight": set(), "side": side}
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
