"""
ESRI ASCII grid geometry, as LISFLOOD-FP actually reads it.

LISFLOOD-FP's `LoadDomainGeometry` (input.cpp:1470-1500) reads the six header lines
**positionally** -- it scans a token and a value per line and throws the token away.
So the labels are never checked, only the order matters, and `xllcenter`/`yllcenter`
are read as if they said `xllcorner`/`yllcorner`.

It then hard-codes `dy = dx`. A raster with non-square cells is not rejected; it is
silently mis-georeferenced by the x/y ratio.

Worse, the eleven *ancillary* grid loaders (Manning's n, start depth, the SGC grids,
rainfall mask...) skip five header lines with `fscanf("%s %s")` and read only the
NODATA value, never comparing geometry against the DEM. A mismatched grid is read as
raw numbers straight onto the DEM's grid. That is silent, total corruption, so this
module treats exact geometry agreement as a hard requirement.
"""

from collections import namedtuple

NODATA = -9999.0

GridSpec = namedtuple("GridSpec", "ncols nrows xll yll cellsize nodata")


class GridError(Exception):
    pass


class NonSquareCellsError(GridError):
    pass


def read_header(path):
    """Read a 6-line ESRI ASCII header the way LISFLOOD-FP does: by position."""
    vals, labels = [], []
    with open(path, "r") as fh:
        for i in range(6):
            line = fh.readline()
            if not line:
                raise GridError(
                    "%s has only %d header lines; LISFLOOD-FP requires 6 "
                    "(ncols, nrows, xllcorner, yllcorner, cellsize, NODATA_value). "
                    "A 5-line header makes the model consume two data values as "
                    "header and shift the whole grid." % (path, i)
                )
            parts = line.split()
            if len(parts) < 2:
                raise GridError("%s: header line %d is malformed: %r" % (path, i + 1, line))
            labels.append(parts[0].lower())
            vals.append(parts[1])
    if labels[2].startswith("xllcenter") or labels[3].startswith("yllcenter"):
        raise GridError(
            "%s uses xllcenter/yllcenter. LISFLOOD-FP reads the 3rd and 4th header "
            "values as *corner* coordinates regardless of the label, so the grid "
            "would be offset by half a cell. Re-export with xllcorner/yllcorner." % path
        )
    try:
        return GridSpec(
            ncols=int(float(vals[0])), nrows=int(float(vals[1])),
            xll=float(vals[2]), yll=float(vals[3]),
            cellsize=float(vals[4]), nodata=float(vals[5]),
        )
    except ValueError as exc:
        raise GridError("%s: could not parse header values: %s" % (path, exc))


def spec_from_geotransform(gt, ncols, nrows, nodata=NODATA, tol=1e-6):
    """Build a GridSpec from a GDAL geotransform, rejecting rotation and non-square cells."""
    if abs(gt[2]) > tol or abs(gt[4]) > tol:
        raise GridError("Raster is rotated; LISFLOOD-FP needs an axis-aligned grid.")
    dx, dy = abs(gt[1]), abs(gt[5])
    if abs(dx - dy) > tol * max(dx, dy):
        raise NonSquareCellsError(
            "Non-square cells (%.6g x %.6g map units). LISFLOOD-FP hard-codes dy = dx "
            "and reads only the `cellsize` line, so it would run to completion and "
            "return results wrong by the x/y ratio, with no warning. "
            "Resample to square cells first." % (dx, dy)
        )
    return GridSpec(ncols, nrows, gt[0], gt[3] - nrows * dy, dx, nodata)


def geotransform(spec):
    """GDAL geotransform for a GridSpec (origin is the *top* left)."""
    return (spec.xll, spec.cellsize, 0.0,
            spec.yll + spec.nrows * spec.cellsize, 0.0, -spec.cellsize)


def same_grid(a, b, tol=1e-6):
    """Do two grids agree closely enough that LISFLOOD-FP's assumption holds?"""
    if a.ncols != b.ncols or a.nrows != b.nrows:
        return False
    scale = max(a.cellsize, tol)
    return (abs(a.xll - b.xll) <= tol * scale
            and abs(a.yll - b.yll) <= tol * scale
            and abs(a.cellsize - b.cellsize) <= tol * scale)


def describe(spec):
    return "%d x %d @ %g m, origin (%g, %g)" % (
        spec.ncols, spec.nrows, spec.cellsize, spec.xll, spec.yll)


def qx_spec(spec):
    """Geometry of a .Qx flux grid: x-faces, one extra column, origin shifted half a cell.

    The model already applies this offset when writing (output.cpp), so the file is
    correctly georeferenced as delivered -- do not shift it again on load.
    """
    return spec._replace(ncols=spec.ncols + 1, xll=spec.xll - spec.cellsize / 2.0)


def qy_spec(spec):
    """Geometry of a .Qy flux grid: y-faces, one extra row, origin shifted half a cell."""
    return spec._replace(nrows=spec.nrows + 1, yll=spec.yll - spec.cellsize / 2.0)


def write_prj(path, wkt):
    """Write a .prj sidecar. LISFLOOD-FP never writes one, so outputs are CRS-less.

    GDAL finds these by replacing the extension, so one `res-0001.prj` serves
    `res-0001.wd`, `.elev`, `.Qx`, `.Qy` ... simultaneously.
    """
    with open(path, "w") as fh:
        fh.write(wkt)
    return path
