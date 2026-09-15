"""
QGIS vector layers -> LISFLOOD-FP channel network.

Each line feature becomes one channel segment, in feature order, and its vertices become
cross-sections. Geometry (width, Manning's n, bed elevation) is attached to the first
and last vertex only; the model interpolates linearly between cross-sections that carry
geometry, so giving it the two ends produces a uniformly graded bed, which is what a
bed_up/bed_dn pair means anyway.

Junctions are detected rather than hand-declared. Authoring them by hand is the fiddliest
part of a .river file: the tributary's downstream end must carry `QOUT <target>` while
the receiving segment carries `TRIB <source>` at *identical* coordinates, and a
mismatch silently drops the inflow. Here, a segment whose downstream end lands on
another segment's line is snapped to the nearest vertex of that segment and both halves
of the junction are written together.
"""

from qgis.core import QgsCoordinateTransform, QgsGeometry, QgsPointXY

from ..core import river as R


class VectorPrepError(Exception):
    pass


def _attr(feature, field, default=None):
    if not field:
        return default
    try:
        value = feature[field]
    except KeyError:
        return default
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.upper() == "NULL":
        return default
    return text


def _num(feature, field, default=None):
    text = _attr(feature, field)
    if text is None:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def read_segments(source, crs, context, fields, tolerance=None):
    """Read line features into raw segments: (vertices, geometry, boundary conditions).

    `fields` maps the roles to attribute names:
    width, manning, bed_up, bed_dn, bc_up, bc_up_value, bc_dn, bc_dn_value.
    """
    transform = None
    if source.sourceCrs() != crs:
        transform = QgsCoordinateTransform(source.sourceCrs(), crs, context.project())

    segments = []
    for feature in source.getFeatures():
        geom = QgsGeometry(feature.geometry())
        if geom.isEmpty():
            continue
        if transform is not None:
            geom.transform(transform)
        if geom.isMultipart():
            lines = geom.asMultiPolyline()
            vertices = [pt for line in lines for pt in line]
        else:
            vertices = geom.asPolyline()
        if len(vertices) < 2:
            raise VectorPrepError(
                "A channel feature has fewer than two vertices; a segment needs at "
                "least an upstream and a downstream cross-section.")
        segments.append({
            "vertices": [(p.x(), p.y()) for p in vertices],
            "width": _num(feature, fields.get("width")),
            "manning": _num(feature, fields.get("manning")),
            "bed_up": _num(feature, fields.get("bed_up")),
            "bed_dn": _num(feature, fields.get("bed_dn")),
            "bc_up": _attr(feature, fields.get("bc_up")),
            "bc_up_value": _attr(feature, fields.get("bc_up_value")),
            "bc_dn": _attr(feature, fields.get("bc_dn")),
            "bc_dn_value": _attr(feature, fields.get("bc_dn_value")),
        })
    if not segments:
        raise VectorPrepError("The channel layer has no usable line features.")
    return segments


def detect_junctions(segments, tolerance):
    """Find segments whose downstream end meets another segment.

    Returns {source index: (target index, snapped x, snapped y)} and mutates nothing.
    The downstream point is snapped onto the target's nearest vertex so both sides of
    the junction end up at byte-identical coordinates, which is what the model requires.
    """
    junctions = {}
    for i, seg in enumerate(segments):
        if seg.get("bc_dn"):
            continue                    # an explicit downstream BC wins
        x, y = seg["vertices"][-1]
        best = None
        for j, other in enumerate(segments):
            if i == j:
                continue
            for (ox, oy) in other["vertices"]:
                d = ((ox - x) ** 2 + (oy - y) ** 2) ** 0.5
                if d <= tolerance and (best is None or d < best[0]):
                    best = (d, j, ox, oy)
        if best is not None:
            junctions[i] = (best[1], best[2], best[3])
    return junctions


def build_river(source, crs, context, fields, spec, series_names=None,
                tolerance=None, feedback=None):
    """Turn a line layer into validated river segments ready for write_river()."""
    tolerance = tolerance if tolerance else spec.cellsize
    raw = read_segments(source, crs, context, fields)
    junctions = detect_junctions(raw, tolerance)

    # a receiving segment needs a TRIB point at the junction coordinates
    incoming = {}
    for source_index, (target, jx, jy) in junctions.items():
        incoming.setdefault(target, []).append((source_index, jx, jy))

    segments = []
    for index, seg in enumerate(raw):
        vertices = list(seg["vertices"])
        if index in junctions:
            _target, jx, jy = junctions[index]
            vertices[-1] = (jx, jy)          # snap so both ends agree exactly

        points = []
        last = len(vertices) - 1
        for order, (x, y) in enumerate(vertices):
            width = manning = bed = None
            bctype = bcvalue = None
            if order == 0:
                width, manning, bed = seg["width"], seg["manning"], seg["bed_up"]
                if seg["bc_up"]:
                    bctype, bcvalue = seg["bc_up"], seg["bc_up_value"]
            elif order == last:
                width, manning, bed = seg["width"], seg["manning"], seg["bed_dn"]
                if index in junctions:
                    bctype, bcvalue = "QOUT", junctions[index][0]
                elif seg["bc_dn"]:
                    bctype, bcvalue = seg["bc_dn"], seg["bc_dn_value"]

            # a tributary arriving at this vertex must be declared here too
            for src, jx, jy in incoming.get(index, []):
                if abs(jx - x) < 1e-6 and abs(jy - y) < 1e-6:
                    if bctype in (None, ""):
                        bctype, bcvalue = "TRIB", src
                    elif feedback is not None:
                        feedback.pushWarning(
                            "Channel segment %d already has a %s boundary where segment "
                            "%d joins; the junction there was not written."
                            % (index, bctype, src))

            if width is not None and (manning is None or bed is None):
                width = manning = bed = None      # the model needs all three or none
            points.append(R.point(x, y, width, manning, bed, bctype, bcvalue))
        segments.append(points)

    # a mid-line vertex may also be a junction target
    for target, arrivals in incoming.items():
        for src, jx, jy in arrivals:
            if not any(p.bctype == "TRIB" and int(p.bcvalue) == src
                       for p in segments[target]):
                segments[target] = _insert_trib(segments[target], src, jx, jy)

    problems = R.validate(segments, spec=spec, series_names=series_names)
    fatal = [p for p in problems if not p.startswith("WARN ")]
    if feedback is not None:
        for p in problems:
            if p.startswith("WARN "):
                feedback.pushWarning(p[5:])
    if fatal:
        raise VectorPrepError("; ".join(fatal))
    if feedback is not None and junctions:
        feedback.pushInfo(
            "Channel network: %d segment(s), %d junction(s) detected within %g m."
            % (len(segments), len(junctions), tolerance))
    return segments


def _insert_trib(points, source_index, x, y):
    """Place a TRIB marker at (x, y), inserting a cross-section if needed."""
    out = list(points)
    for order, p in enumerate(out):
        if abs(p.x - x) < 1e-6 and abs(p.y - y) < 1e-6:
            if not p.bctype:
                out[order] = p._replace(bctype="TRIB", bcvalue=source_index)
            return out
    # not an existing vertex: insert at the closest position along the line
    best, best_d = 1, None
    for order in range(1, len(out)):
        px, py = out[order].x, out[order].y
        d = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
        if best_d is None or d < best_d:
            best, best_d = order, d
    out.insert(best, R.point(x, y, bctype="TRIB", bcvalue=source_index))
    return out
