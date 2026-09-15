"""
Boundary conditions (.bci) and time series (.bdy, rainfall, evaporation).

Two traps live here, both silent, both verified against the model source.

**1. `.bdy` rows are `value` then `time`, not `time` then `value`.**
`LoadTimeSeries` (input.cpp:1903) does
`sscanf(line, "%lf%lf", &series.value[i], &series.time[i])`.
Reversing the columns is the single most common authoring error and produces a
running model with a nonsense hydrograph. Times must also be *strictly* increasing
or the model calls `exit(-1)`.

**2. Discharge in a `.bci` is per metre of cell width (m2/s), not m3/s.**
The model multiplies the supplied value by the cell size
(iterateq.cpp:500-501, `H += PS_Val * dx * Tstep / dA`; sgm_fast.cpp:2037 sets
`Q_multiplier = dx` whenever `latlong` is off). So to inject X m3/s at a point you
must write `X / cellsize`, and across an edge spanning N cells, `X / (cellsize * N)`.
`to_model_discharge` does this conversion so callers can work in m3/s throughout.

Note the exception: discharges in a `.river` file really are m3/s. Do not convert those.
"""

from collections import namedtuple

#: A point source. x/y are real-world coordinates; the model takes the containing cell.
PointBC = namedtuple("PointBC", "x y type value series")
#: An edge segment. `edge` is N/S/E/W; start/finish are map coordinates along that edge.
EdgeBC = namedtuple("EdgeBC", "edge start finish type value series")
#: A named time series. `times` in `units`; `values` in the model's own units.
Series = namedtuple("Series", "name units times values")

BC_TYPES = ("FREE", "HFIX", "QFIX", "HVAR", "QVAR")
VARYING = ("HVAR", "QVAR")
UNITS = ("seconds", "minutes", "hours", "days")
_UNIT_SECONDS = {"seconds": 1.0, "minutes": 60.0, "hours": 3600.0, "days": 86400.0}


class BCError(Exception):
    pass


def to_model_discharge(q_cumecs, cellsize, n_cells=1):
    """Convert a discharge in m3/s to the per-metre value a .bci expects.

    `n_cells` is 1 for a point source, or the number of cells an edge segment spans.
    """
    if cellsize <= 0:
        raise BCError("cellsize must be positive")
    if n_cells < 1:
        raise BCError("n_cells must be at least 1")
    return q_cumecs / (cellsize * n_cells)


def from_model_discharge(q_model, cellsize, n_cells=1):
    """Inverse of `to_model_discharge`, for reading a deck back."""
    return q_model * cellsize * n_cells


def lowest_edge_cell(spec, elev, nodata):
    """The perimeter cell with the lowest elevation, as (edge, row, col).

    `elev[row][col]` must follow the ESRI ASCII convention gridio uses: row 0 is the
    grid's *northern* edge, matching the raster's own top-left origin.

    Only perimeter cells are considered. LISFLOOD-FP applies boundary conditions
    strictly along the N/S/E/W edges (`boundary.cpp`'s BC loop runs over exactly
    `2*xsz + 2*ysz` perimeter slots) -- a FREE condition anywhere else in the domain
    is not a boundary at all, just an unreachable interior sink. Worse, a point-source
    FREE condition (a `P ... FREE` row in the .bci) is silently dropped outright unless
    sub-grid-channel mode is on (`input.cpp` gates it on `Statesptr->SGC == ON`), so a
    "lowest point in the whole DEM" search that ignored this and landed on an interior
    cell would produce a deck that looks complete but drains nothing.

    Returns None if every perimeter cell is NODATA.
    """
    ncols, nrows = spec.ncols, spec.nrows
    candidates = [("N", 0, col) for col in range(ncols)]
    candidates += [("S", nrows - 1, col) for col in range(ncols)]
    candidates += [("W", row, 0) for row in range(nrows)]
    candidates += [("E", row, ncols - 1) for row in range(nrows)]

    best = None
    for edge, row, col in candidates:
        v = elev[row][col]
        if v is None or v == nodata or v != v:      # v != v catches NaN
            continue
        if best is None or v < best[0]:
            best = (v, edge, row, col)
    return None if best is None else best[1:]


def outflow_edge_bc(spec, edge, row, col, elev, nodata, width=1, slope=None):
    """A FREE EdgeBC spanning up to `width` perimeter cells, centred on (row, col).

    `edge`, `row` and `col` normally come straight from `lowest_edge_cell`. `slope`,
    if given, is the floodplain slope LISFLOOD-FP falls back to at the boundary
    (m/m); the default `None` lets the model use the local water-surface slope
    instead, which is the usual choice for an open outflow.

    The window only ever grows into cells that are real data. Growing blindly by
    index can walk straight off the edge of a clipped catchment's valid footprint
    into NODATA, and LISFLOOD-FP treats a NODATA DEM cell as a ~1e7 m wall (see
    `nodata_elevation` in pars.cpp/lisflood.cpp) -- silently turning part of a
    requested opening into a dam instead of an outflow. So the returned segment can
    be narrower than `width` if the valid run around (row, col) is that short; it is
    never wider, and it never includes a NODATA cell.
    """
    if width < 1:
        raise BCError("width must be at least 1")

    def is_valid(r, c):
        v = elev[r][c]
        return not (v is None or v == nodata or v != v)   # v != v catches NaN

    if edge in ("N", "S"):
        n = spec.ncols
        lo = hi = col
    elif edge in ("E", "W"):
        n = spec.nrows
        lo = hi = row
    else:
        raise BCError("edge must be one of N/S/E/W, got %r" % edge)

    r_or_c = row if edge in ("N", "S") else col       # the fixed index (row for N/S, col for E/W)
    while hi - lo + 1 < width:
        grew = False
        if lo > 0 and is_valid(*((r_or_c, lo - 1) if edge in ("N", "S") else (lo - 1, r_or_c))):
            lo -= 1
            grew = True
            if hi - lo + 1 >= width:
                break
        if hi < n - 1 and is_valid(*((r_or_c, hi + 1) if edge in ("N", "S") else (hi + 1, r_or_c))):
            hi += 1
            grew = True
        if not grew:
            break

    if edge in ("N", "S"):
        start = spec.xll + lo * spec.cellsize
        finish = spec.xll + (hi + 1) * spec.cellsize
    else:
        start = spec.yll + (n - 1 - hi) * spec.cellsize
        finish = spec.yll + (n - lo) * spec.cellsize
    return EdgeBC(edge, start, finish, "FREE", slope, None)


def edge_cell_count(edge, start, finish, spec):
    """How many cells an edge segment covers, mirroring the model's index arithmetic.

    input.cpp converts the map coordinates to cell indices and then decrements the
    upper bound, so a segment shorter than one cell collapses to nothing and the
    boundary is silently dropped.
    """
    lo, hi = (start, finish) if start <= finish else (finish, start)
    if edge.upper().startswith(("N", "S")):
        lo = max(lo, spec.xll); hi = min(hi, spec.xll + spec.ncols * spec.cellsize)
    else:
        lo = max(lo, spec.yll); hi = min(hi, spec.yll + spec.nrows * spec.cellsize)
    if hi <= lo:
        return 0
    i1 = int((lo - (spec.xll if edge.upper().startswith(("N", "S")) else spec.yll)) / spec.cellsize)
    i2 = int((hi - (spec.xll if edge.upper().startswith(("N", "S")) else spec.yll)) / spec.cellsize)
    return max(0, i2 - i1)


def _bc_tail(type_, value, series):
    t = type_.upper()
    if t not in BC_TYPES:
        raise BCError("Unknown boundary type %r; expected one of %s"
                      % (type_, ", ".join(BC_TYPES)))
    if t in VARYING:
        if not series:
            raise BCError("%s boundary needs the name of a .bdy series" % t)
        if len(series) > 79:
            raise BCError("Series name %r exceeds the model's 79-character limit" % series)
        return "\t%s" % series
    if t == "FREE":
        # optional slope; omitted means "use the local water-surface slope"
        return "" if value is None else "\t%g" % value
    if value is None:
        raise BCError("%s boundary needs a value" % t)
    return "\t%g" % value


def write_bci(path, points=(), edges=()):
    """Write a .bci. Edge rows first, then point sources.

    Ordering matters: input.cpp tests the first character for N/S/E/W before it tests
    for P/F, and its point-source branch is only well defined once at least one `P`
    row has been seen.
    """
    lines = []
    for e in edges:
        edge = e.edge.upper()[:1]
        if edge not in ("N", "S", "E", "W"):
            raise BCError("Edge must be one of N/S/E/W, got %r" % e.edge)
        lines.append("%s\t%.6f\t%.6f\t%s%s"
                     % (edge, e.start, e.finish, e.type.upper(),
                        _bc_tail(e.type, e.value, e.series)))
    for p in points:
        lines.append("P\t%.6f\t%.6f\t%s%s"
                     % (p.x, p.y, p.type.upper(), _bc_tail(p.type, p.value, p.series)))
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def validate_series(s, sim_time=None):
    """Return a list of problems with a Series. Empty means it is safe to write."""
    problems = []
    if not s.name or " " in s.name:
        problems.append("Series name %r must be a single whitespace-free token." % s.name)
    if len(s.name) > 79:
        problems.append("Series name %r exceeds the model's 79-character limit." % s.name)
    if s.units not in UNITS:
        problems.append(
            "Units %r are not recognised. LISFLOOD-FP accepts only seconds/minutes/"
            "hours/days and silently falls back to *seconds* otherwise, so a 48-hour "
            "hydrograph would run in 48 seconds." % (s.units,))
    if len(s.times) != len(s.values):
        problems.append("Series %r has %d times but %d values."
                        % (s.name, len(s.times), len(s.values)))
    if not s.times:
        problems.append("Series %r is empty." % s.name)
    for i in range(1, len(s.times)):
        if s.times[i] <= s.times[i - 1]:
            problems.append(
                "Series %r has a non-increasing time at row %d (%g after %g). "
                "LISFLOOD-FP exits with an error on this."
                % (s.name, i + 1, s.times[i], s.times[i - 1]))
            break
    if sim_time is not None and s.times:
        end = s.times[-1] * _UNIT_SECONDS.get(s.units, 1.0)
        if end < sim_time:
            problems.append(
                "WARN Series %r ends at %g s but sim_time is %g s. LISFLOOD-FP holds "
                "the final value constant for the remaining %g s."
                % (s.name, end, sim_time, sim_time - end))
    return problems


def _series_block(s):
    rows = ["%s" % s.name, "%d\t%s" % (len(s.times), s.units)]
    # value first, then time -- input.cpp:1903
    rows += ["%g\t%g" % (v, t) for t, v in zip(s.times, s.values)]
    return rows


def write_bdy(path, series, comment="Generated by LISFLOOD-FP for QGIS"):
    """Write a .bdy.

    The reader unconditionally discards line 1 of the whole file, then expects
    repeating `name` / `count units` / rows blocks. Only one leading comment line is
    permitted -- a stray comment between blocks is read as a series name.
    """
    for s in series:
        bad = [p for p in validate_series(s) if not p.startswith("WARN ")]
        if bad:
            raise BCError("; ".join(bad))
    lines = ["# %s" % comment]
    for s in series:
        lines += _series_block(s)
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def write_timeseries(path, s, comment="Generated by LISFLOOD-FP for QGIS"):
    """Write a rainfall (mm/hr) or evaporation (mm/day) series.

    Same reader as .bdy but with no name line: one skipped comment, then
    `count units`, then `value time` rows.
    """
    bad = [p for p in validate_series(s) if not p.startswith("WARN ")]
    if bad:
        raise BCError("; ".join(bad))
    lines = ["# %s" % comment, "%d\t%s" % (len(s.times), s.units)]
    lines += ["%g\t%g" % (v, t) for t, v in zip(s.times, s.values)]
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def write_stage(path, points):
    """Write a .stage: a count, then x/y map coordinates."""
    lines = ["%d" % len(points)] + ["%.6f\t%.6f" % (x, y) for x, y in points]
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def write_gauge(path, gauges):
    """Write a .gauge: a count, then x/y, direction (NSEW) and section length."""
    lines = ["%d" % len(gauges)]
    lines += ["%.6f\t%.6f\t%s\t%g" % (x, y, d.upper()[:1], w) for x, y, d, w in gauges]
    with open(path, "w", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def cross_validate(points, edges, series):
    """Check that every QVAR/HVAR name resolves, and flag unreferenced series.

    An unresolved name does not stop the model: it disables the boundary and carries
    on, giving a complete-looking run with no inflow at all.
    """
    problems = []
    names = set(s.name for s in series)
    used = set()
    for bc in list(points) + list(edges):
        if bc.type.upper() in VARYING:
            used.add(bc.series)
            if bc.series not in names:
                problems.append(
                    "Boundary %r refers to series %r, which is not in the .bdy file. "
                    "Names are matched case-sensitively. Depending on the boundary type "
                    "LISFLOOD-FP either disables the boundary silently -- giving a "
                    "complete-looking run with no inflow -- or segfaults part way "
                    "through. Verified: a mismatched point-source name crashes it."
                    % (bc.type.upper(), bc.series))
    for n in sorted(names - used):
        problems.append("WARN Series %r is not referenced by any boundary; it will be ignored." % n)
    return problems
