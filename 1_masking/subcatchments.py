"""Create approximate runoff regions guided by the mapped river network."""

import geopandas as gpd
import math
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import linemerge, split, unary_union

from average import cell_weights


AREA_CRS = "EPSG:3577"  # Australian Albers equal-area projection


def network_based_regions(catchment, waterways_file):
    """Split the valley into longitudinal regions at major OSM tributary junctions.

    The selected junctions are cross-valley cut locations along the mapped
    Murrumbidgee main stem. This gives runoff regions that follow the river's
    sequence and major tributary inflows; they are still approximations, not
    terrain-derived drainage basins.
    """
    junction_groups = [
        ("Bredbo River", ("Bredbo River",)),
        ("Gudgenby River", ("Gudgenby River",)),
        ("Cotter River", ("Cotter River",)),
        ("Molonglo River", ("Molonglo River",)),
        ("Yass River", ("Yass River",)),
        ("Goodradigbee River", ("Goodradigbee River",)),
        ("Jugiong Creek", ("Jugiong Creek",)),
        ("Tumut–Muttama junctions", ("Tumut River", "Muttama Creek")),
        ("Hillas Creek", ("Hillas Creek",)),
        ("Tarcutta–Kyeamba junctions", ("Tarcutta Creek", "Kyeamba Creek")),
        ("Old Man Creek", ("Old Man Creek",)),
    ]

    valley = catchment.to_crs(AREA_CRS)
    basin = valley.geometry.union_all()
    waterways = gpd.read_file(waterways_file).to_crs(AREA_CRS)
    mainstem_features = waterways[
        (waterways["name"] == "Murrumbidgee River")
        & (waterways["waterway"] == "river")
    ]
    if mainstem_features.empty:
        raise ValueError("OSM waterways contain no Murrumbidgee River mainstem")
    merged = linemerge(unary_union(list(mainstem_features.geometry)))
    mainstem_parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
    mainstem = max(mainstem_parts, key=lambda line: line.length)
    if not isinstance(mainstem, LineString):
        raise ValueError("Could not construct a continuous Murrumbidgee mainstem line")
    if mainstem.coords[0][0] < mainstem.coords[-1][0]:
        mainstem = LineString(list(mainstem.coords)[::-1])

    junctions = []
    for label, tributaries in junction_groups:
        candidates = []
        for tributary in tributaries:
            rows = waterways[waterways["name"] == tributary]
            for line in rows.geometry:
                crossing = line.intersection(mainstem)
                if crossing.geom_type == "Point":
                    points = [crossing]
                elif hasattr(crossing, "geoms"):
                    points = [part for part in crossing.geoms if part.geom_type == "Point"]
                else:
                    points = []
                candidates.extend((mainstem.project(point), point) for point in points)
        if not candidates:
            raise ValueError(f"No OSM mainstem junction found for {label}")
        # For grouped tributaries, place the boundary after the last junction;
        # for a name with multiple mapped intersections, use its first reach.
        chooser = max if len(tributaries) > 1 else min
        chainage, point = chooser(candidates, key=lambda item: item[0])
        junctions.append((chainage, label, point))
    junctions.sort(key=lambda item: item[0])

    # A perpendicular transect at each major junction creates one contiguous
    # longitudinal model region per mainstem reach interval.
    pieces = [basin]
    for chainage, _, point in junctions:
        before = mainstem.interpolate(max(0, chainage - 1000))
        after = mainstem.interpolate(min(mainstem.length, chainage + 1000))
        dx, dy = after.x - before.x, after.y - before.y
        norm = (dx * dx + dy * dy) ** 0.5
        if norm == 0:
            raise ValueError("Could not estimate mainstem direction at tributary junction")
        normal_angle = math.atan2(dx, -dy)
        target_piece_index = min(range(len(pieces)), key=lambda i: pieces[i].distance(point))
        target_piece = pieces[target_piece_index]
        split_pieces = None
        # A straight perpendicular transect can cross a meandering boundary
        # more than twice. Search nearby angles and accept only a single
        # boundary-to-boundary cut that divides the containing region in two.
        for offset_degrees in (0, 5, -5, 10, -10, 15, -15, 20, -20, 30, -30, 45, -45, 60, -60, 90):
            angle = normal_angle + math.radians(offset_degrees)
            nx, ny = math.cos(angle), math.sin(angle)
            cutter = LineString([
                (point.x - nx * 300_000, point.y - ny * 300_000),
                (point.x + nx * 300_000, point.y + ny * 300_000),
            ])
            edge_crossings = target_piece.boundary.intersection(cutter)
            if edge_crossings.geom_type == "Point":
                crossing_points = [edge_crossings]
            elif hasattr(edge_crossings, "geoms"):
                crossing_points = [g for g in edge_crossings.geoms if g.geom_type == "Point"]
            else:
                crossing_points = []
            unique_points = []
            for crossing in crossing_points:
                if not any(crossing.distance(known) < 1 for known in unique_points):
                    unique_points.append(crossing)
            if len(unique_points) != 2:
                continue
            result = split(target_piece, cutter)
            candidates = [g for g in result.geoms if g.geom_type == "Polygon" and g.area > 0]
            if len(candidates) == 2:
                split_pieces = candidates
                break
        if split_pieces is None:
            raise ValueError(f"Could not make a clean cross-valley cut at {label}")
        pieces[target_piece_index:target_piece_index + 1] = split_pieces

    # Sort from headwaters to downstream by where each region meets the trunk.
    def trunk_position(piece):
        overlap = piece.intersection(mainstem)
        if overlap.is_empty:
            return mainstem.project(piece.representative_point())
        return mainstem.project(overlap.representative_point())

    pieces.sort(key=trunk_position)
    if len(pieces) != len(junctions) + 1:
        raise ValueError(
            f"Expected {len(junctions) + 1} regions from tributary cuts, got {len(pieces)}; "
            "check OSM connectivity or adjust junctions"
        )
    boundaries = [(None, "Headwaters"), *[(d, label) for d, label, _ in junctions], (mainstem.length, "Valley outlet")]
    rows = []
    for i, piece in enumerate(pieces):
        upstream_limit = boundaries[i][1]
        downstream_limit = boundaries[i + 1][1]
        rows.append({
            "subcatchment": f"SC{i + 1:02d}",
            "route_order": i + 1,
            "region_name": f"{upstream_limit} to {downstream_limit}",
            "upstream_boundary": upstream_limit,
            "downstream_boundary": downstream_limit,
            "area_km2": piece.area / 1_000_000,
            "geometry": piece,
        })
    return gpd.GeoDataFrame(rows, crs=AREA_CRS).to_crs(catchment.crs)


def subcatchment_averages(ds, subcatchments):
    """Return area-weighted daily averages with columns ``SC01_P``, ``SC01_PET``, etc."""
    frames = []
    for _, unit in subcatchments.iterrows():
        one = gpd.GeoDataFrame([unit], geometry="geometry", crs=subcatchments.crs)
        weights = cell_weights(ds, one)
        averaged = ds.weighted(weights).mean(dim=["rlat", "rlon"]).to_dataframe()
        averaged = averaged[list(ds.data_vars)].rename(
            columns={name: f"{unit['subcatchment']}_{name}" for name in ds.data_vars}
        )
        frames.append(averaged)
    return pd.concat(frames, axis=1)
