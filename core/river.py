"""
The 1D channel network (.river).

File shape, verified against testing/T007_CTBranchFine/CTBranchFine.river:

    Tribs <nSegments>          (optional; absent means a single segment)
    <npoints>                  segment 0
    <x> <y> [<w> <n> <z>] [<BCTYPE> <arg>]
    ...
    <npoints>                  segment 1
    ...

Each cross-section line is parsed by reading x and y, then buffering to end of line and
running two speculative scans (input.cpp:446-455): three floats give width, Manning's n
and bed elevation; a trailing token pair gives the boundary condition. All four
combinations are therefore legal -- bare `x y`, `x y w n z`, `x y BCTYPE arg`, and
`x y w n z BCTYPE arg` -- and a point with no geometry has it interpolated from its
neighbours.

Two things differ from the .bci boundaries and catch people out:

  * **Channel discharge really is m3/s here.** The per-metre conversion that .bci needs
    does not apply, so values are written through unchanged.
  * **Junctions must be declared from both ends.** The tributary's last point carries
    `QOUT <target segment>` and the receiving segment carries `TRIB <source segment>` at
    *identical* coordinates. Segment numbers are 0-based (`ChannelSegments[trib[i]]` is
    a direct index at input.cpp:788).

The reader consumes each line with `do { buff[j] = fgetc(fp); } while (buff[j++] !=
'\\n');`, so **every line must end with a newline**, the final one included, or it runs
off the end of the file. The line buffer is 800 bytes and series names are capped at 80.
"""

from collections import namedtuple

#: width/n/bed may be None (interpolated); bctype/bcvalue may be None (no BC).
RiverPoint = namedtuple("RiverPoint", "x y width n bed bctype bcvalue")
RiverPoint.__new__.__defaults__ = (None, None, None, None, None)

#: BCs that name a series in the .bdy
NAMED = ("QVAR", "HVAR", "RATE")
#: BCs that reference another segment, 0-based
SEGMENT_REF = ("QOUT", "TRIB")
#: BCs that take a number
NUMERIC = ("QFIX", "HFIX", "FREE")
BC_TYPES = NAMED + SEGMENT_REF + NUMERIC

MAX_LINE = 800
MAX_NAME = 79


class RiverError(Exception):
    pass


def point(x, y, width=None, n=None, bed=None, bctype=None, bcvalue=None):
    """Build a RiverPoint, normalising the boundary type."""
    if bctype:
        bctype = str(bctype).strip().upper()
        if bctype not in BC_TYPES:
            raise RiverError(
                "Unknown channel boundary type %r; expected one of %s."
                % (bctype, ", ".join(BC_TYPES)))
    has_geom = [v is not None for v in (width, n, bed)]
    if any(has_geom) and not all(has_geom):
        raise RiverError(
            "A cross-section needs width, Manning's n and bed elevation together, or "
            "none of them. LISFLOOD-FP only stores the three when all three parse "
            "(input.cpp:446), so a partial set is silently discarded.")
    return RiverPoint(float(x), float(y),
                      None if width is None else float(width),
                      None if n is None else float(n),
                      None if bed is None else float(bed),
                      bctype or None, bcvalue)


def _format_bc(bctype, bcvalue):
    if bctype in SEGMENT_REF:
        return "%s\t%d" % (bctype, int(bcvalue))
    if bctype in NAMED:
        name = str(bcvalue).strip()
        if not name or " " in name:
            raise RiverError(
                "%s needs a single whitespace-free series name, got %r." % (bctype, bcvalue))
        if len(name) > MAX_NAME:
            raise RiverError("Series name %r exceeds the model's %d-character limit."
                             % (name, MAX_NAME))
        return "%s\t%s" % (bctype, name)
    if bcvalue is None:
        if bctype == "FREE":
            return "FREE\t-1"       # -1 means "use the slope of the last segment"
        raise RiverError("%s needs a value." % bctype)
    return "%s\t%g" % (bctype, float(bcvalue))


def format_point(p):
    """Render one cross-section line."""
    parts = ["%.6f" % p.x, "%.6f" % p.y]
    if p.width is not None:
        parts += ["%g" % p.width, "%g" % p.n, "%g" % p.bed]
    if p.bctype:
        parts.append(_format_bc(p.bctype, p.bcvalue))
    line = "\t".join(parts)
    if len(line) >= MAX_LINE:
        raise RiverError("Cross-section line is %d characters; the model's buffer is %d."
                         % (len(line), MAX_LINE))
    return line


def write_river(path, segments, force_tribs=None):
    """Write a .river file.

    `segments` is a sequence of point sequences. The `Tribs` header is written whenever
    there is more than one segment; a single segment omits it, matching the model's own
    rewind-and-assume-one behaviour.
    """
    segments = [list(s) for s in segments]
    if not segments:
        raise RiverError("A river file needs at least one segment.")
    problems = [p for p in validate(segments) if not p.startswith("WARN ")]
    if problems:
        raise RiverError("; ".join(problems))

    lines = []
    multi = force_tribs if force_tribs is not None else len(segments) > 1
    if multi:
        lines.append("Tribs %d" % len(segments))
    for points in segments:
        lines.append("%d" % len(points))
        lines.extend(format_point(p) for p in points)
    # the reader scans to '\n', so the final line must carry one
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def validate(segments, spec=None, series_names=None):
    """Return a list of problems. Entries prefixed 'WARN ' are advisory."""
    problems = []
    segments = [list(s) for s in segments]
    n_seg = len(segments)

    for index, points in enumerate(segments):
        if len(points) < 2:
            problems.append("Channel segment %d has %d point(s); at least 2 are needed."
                            % (index, len(points)))
            continue
        if not any(p.width is not None for p in points):
            problems.append(
                "Channel segment %d has no cross-section geometry at all. At least one "
                "point needs width, Manning's n and bed elevation, or the channel has "
                "no conveyance." % index)
        seen = {}
        for order, p in enumerate(points):
            key = (round(p.x, 6), round(p.y, 6))
            if key in seen:
                problems.append(
                    "Channel segment %d repeats the point (%g, %g) at positions %d and "
                    "%d; chainage would be zero between them."
                    % (index, p.x, p.y, seen[key], order))
            seen[key] = order

            if p.bctype in SEGMENT_REF:
                try:
                    target = int(p.bcvalue)
                except (TypeError, ValueError):
                    problems.append("Channel segment %d: %s needs a segment number."
                                    % (index, p.bctype))
                    continue
                if not 0 <= target < n_seg:
                    problems.append(
                        "Channel segment %d refers to segment %d via %s, but there are "
                        "only %d segments (numbered 0 to %d)."
                        % (index, target, p.bctype, n_seg, n_seg - 1))
                elif target == index:
                    problems.append("Channel segment %d refers to itself via %s."
                                    % (index, p.bctype))
            if p.bctype in NAMED and series_names is not None:
                if p.bcvalue not in series_names:
                    problems.append(
                        "Channel segment %d refers to series %r via %s, which is not in "
                        "the .bdy file. Names are matched case-sensitively."
                        % (index, p.bcvalue, p.bctype))
            if spec is not None:
                xmax = spec.xll + spec.ncols * spec.cellsize
                ymax = spec.yll + spec.nrows * spec.cellsize
                if not (spec.xll <= p.x <= xmax and spec.yll <= p.y <= ymax):
                    problems.append(
                        "Channel segment %d has a point at (%g, %g) outside the model "
                        "domain (%g to %g, %g to %g)."
                        % (index, p.x, p.y, spec.xll, xmax, spec.yll, ymax))

    problems.extend(_check_junctions(segments))
    return problems


def _check_junctions(segments):
    """A QOUT must be answered by a TRIB at the same coordinates, and vice versa."""
    problems = []
    outs, tribs = [], []
    for index, points in enumerate(segments):
        for order, p in enumerate(points):
            if p.bctype == "QOUT":
                outs.append((index, order, p))
                if order != len(points) - 1:
                    problems.append(
                        "WARN Channel segment %d declares QOUT at point %d rather than "
                        "its last point; the junction is normally the downstream end."
                        % (index, order))
            elif p.bctype == "TRIB":
                tribs.append((index, order, p))

    def at(seg_index, x, y):
        for p in segments[seg_index]:
            if abs(p.x - x) < 1e-6 and abs(p.y - y) < 1e-6:
                return p
        return None

    for index, _order, p in outs:
        try:
            target = int(p.bcvalue)
        except (TypeError, ValueError):
            continue
        if not 0 <= target < len(segments):
            continue
        partner = at(target, p.x, p.y)
        if partner is None:
            problems.append(
                "Channel segment %d discharges into segment %d at (%g, %g), but segment "
                "%d has no point at those coordinates. The junction cell must coincide "
                "exactly." % (index, target, p.x, p.y, target))
        elif partner.bctype != "TRIB":
            problems.append(
                "Channel segment %d discharges into segment %d at (%g, %g), but the "
                "matching point there is not marked TRIB %d, so the inflow would be "
                "dropped." % (index, target, p.x, p.y, index))
        elif int(partner.bcvalue) != index:
            problems.append(
                "Channel segment %d discharges into segment %d, but the receiving point "
                "is marked TRIB %s rather than TRIB %d."
                % (index, target, partner.bcvalue, index))

    for index, _order, p in tribs:
        try:
            source = int(p.bcvalue)
        except (TypeError, ValueError):
            continue
        if not 0 <= source < len(segments):
            continue
        partner = at(source, p.x, p.y)
        if partner is None or partner.bctype != "QOUT":
            problems.append(
                "Channel segment %d expects inflow from segment %d at (%g, %g), but "
                "segment %d does not discharge there. Add QOUT %d to its last point."
                % (index, source, p.x, p.y, source, index))
    return problems


def write_multiriver(path, river_paths):
    """Write a `multiriverfile`: a count, then one .river path per line."""
    lines = ["%d" % len(river_paths)] + [str(p) for p in river_paths]
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path
