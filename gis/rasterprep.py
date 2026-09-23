"""
QGIS raster layers -> LISFLOOD-FP ESRI ASCII grids, on one shared grid.

The DEM defines the domain. Every other grid is warped onto *exactly* that grid rather
than trusted, because the model's ancillary loaders skip the header and read values
straight onto the DEM's geometry -- a mismatched grid is silently absorbed, not
reported.

AAIGrid is a CreateCopy-only driver, so each write is a warp into an in-memory dataset
followed by a translate. FORCE_CELLSIZE is deliberately *not* used: it would paper over
non-square cells by emitting a single `cellsize`, which is exactly the lie that makes
the model produce wrong answers silently. Non-square input is rejected instead.
"""

import os

from osgeo import gdal, osr

from ..core import gridio
from ..qt_compat import crs_to_esri_wkt

# Enabling GDAL exceptions calls AllRegister(), which raises outright if the
# environment points GDAL_DRIVER_PATH at plugins built against a different GDAL --
# a stray conda install is the usual cause. That must not take the plugin down at
# import time, so failures here are tolerated and errors are detected from null
# return values instead.
try:
    gdal.UseExceptions()
except Exception as exc:                             # noqa: BLE001 - see above
    from qgis.core import Qgis, QgsMessageLog
    QgsMessageLog.logMessage(
        "Could not enable GDAL exceptions (%s); check GDAL_DRIVER_PATH. Raster "
        "errors will be detected from return values instead." % exc,
        "LISFLOOD-FP", Qgis.Warning)

RESAMPLING = {
    "nearest": gdal.GRA_NearestNeighbour,
    "bilinear": gdal.GRA_Bilinear,
    "cubic": gdal.GRA_Cubic,
    "average": gdal.GRA_Average,
    "min": gdal.GRA_Min,
    "max": gdal.GRA_Max,
}


class RasterPrepError(Exception):
    pass


def _srs_input(crs):
    """A string GDAL can use for -t_srs / dstSRS.

    Prefer the authority code (e.g. "EPSG:27700"): GDAL resolves that against its
    own EPSG database, sidestepping any quirks in PyQGIS's WKT export. Fall back to
    WKT for CRSes without an authority (a custom/user CRS), and fail clearly rather
    than handing GDAL an empty string, which it rejects with a bare "Invalid SRS for
    -t_srs" that carries no clue which CRS caused it.
    """
    authid = crs.authid()
    if authid:
        return authid
    wkt = crs.toWkt()
    if not wkt:
        raise RasterPrepError(
            "Could not get a usable SRS definition from the CRS %r. It has no "
            "authority code (e.g. EPSG:27700) and its WKT export is empty, so GDAL "
            "has nothing to warp onto. Pick a CRS from the EPSG database instead of "
            "a custom/user-defined one, or fix the DEM's CRS in Layer Properties."
            % (crs.description() or "<unnamed>"))
    return wkt


def spec_from_layer(layer, cellsize=None, extent=None):
    """Derive the model GridSpec from a QGIS raster layer.

    `extent` (a QgsRectangle) is snapped outward to whole cells of the layer's own
    origin so results stay pixel-aligned with the source DEM.
    """
    ds = gdal.Open(layer.source())
    if ds is None:
        raise RasterPrepError(
            "Could not read %r with GDAL. LISFLOOD-FP needs a single-band raster "
            "on disk." % layer.name())
    gt = ds.GetGeoTransform()
    spec = gridio.spec_from_geotransform(gt, ds.RasterXSize, ds.RasterYSize)

    if cellsize:
        cellsize = float(cellsize)
    else:
        cellsize = spec.cellsize

    if extent is not None and not extent.isEmpty():
        ox, oy = spec.xll, spec.yll
        import math
        xmin = ox + math.floor((extent.xMinimum() - ox) / cellsize) * cellsize
        ymin = oy + math.floor((extent.yMinimum() - oy) / cellsize) * cellsize
        ncols = int(math.ceil((extent.xMaximum() - xmin) / cellsize))
        nrows = int(math.ceil((extent.yMaximum() - ymin) / cellsize))
        spec = gridio.GridSpec(max(1, ncols), max(1, nrows), xmin, ymin,
                               cellsize, gridio.NODATA)
    elif cellsize != spec.cellsize:
        ncols = max(1, int(round(spec.ncols * spec.cellsize / cellsize)))
        nrows = max(1, int(round(spec.nrows * spec.cellsize / cellsize)))
        spec = spec._replace(ncols=ncols, nrows=nrows, cellsize=cellsize)

    return spec._replace(nodata=gridio.NODATA)


def write_grid(layer, spec, crs, out_path, resample="bilinear",
               fill_nodata=None, decimal_precision=3, band=1):
    """Warp `layer` onto `spec` and write it as an ESRI ASCII grid.

    `fill_nodata`, when given, replaces nodata cells with a constant -- needed for
    Manning's n, where the model would otherwise use -9999 as a roughness coefficient.
    Returns the output path.
    """
    src = gdal.Open(layer.source() if hasattr(layer, "source") else str(layer))
    if src is None:
        raise RasterPrepError("Could not open raster %r." % layer)

    alg = RESAMPLING.get(str(resample).lower(), gdal.GRA_Bilinear)
    bounds = (spec.xll, spec.yll,
              spec.xll + spec.ncols * spec.cellsize,
              spec.yll + spec.nrows * spec.cellsize)

    if band != 1 or src.RasterCount > 1:
        # srcBands= only exists in GDAL 3.7+, and QGIS 3.42 ships 3.3.2
        src = gdal.Translate("", src, format="MEM", bandList=[band])

    warp_opts = dict(format="MEM", outputBounds=bounds,
                     xRes=spec.cellsize, yRes=spec.cellsize,
                     resampleAlg=alg, dstNodata=gridio.NODATA,
                     errorThreshold=0)
    if crs is not None:
        warp_opts["dstSRS"] = _srs_input(crs)
    try:
        mem = gdal.Warp("", src, **warp_opts)
    except RuntimeError as exc:
        raise RasterPrepError(
            "Warping %r onto the model grid failed: %s" % (out_path, exc))
    if mem is None:
        raise RasterPrepError("Warping %r onto the model grid failed." % out_path)

    if mem.RasterXSize != spec.ncols or mem.RasterYSize != spec.nrows:
        raise RasterPrepError(
            "Warped raster is %dx%d but the model grid is %dx%d."
            % (mem.RasterXSize, mem.RasterYSize, spec.ncols, spec.nrows))

    if fill_nodata is not None:
        arr = mem.GetRasterBand(1).ReadAsArray()
        nd = mem.GetRasterBand(1).GetNoDataValue()
        if arr is not None:
            import numpy as np
            mask = np.isnan(arr) if nd is None else (arr == nd)
            if mask.any():
                arr = arr.copy()
                arr[mask] = float(fill_nodata)
                mem.GetRasterBand(1).WriteArray(arr)

    gdal.Translate(out_path, mem, format="AAIGrid",
                   creationOptions=["DECIMAL_PRECISION=%d" % int(decimal_precision)],
                   noData=gridio.NODATA)
    mem = None
    src = None

    if crs is not None:
        gridio.write_prj(os.path.splitext(out_path)[0] + ".prj", crs_to_esri_wkt(crs))
    return out_path


def read_grid_values(path):
    """Read a written ESRI ASCII grid's data back, as (array, nodata).

    Reads the file LISFLOOD-FP will actually consume, rather than re-deriving values
    from the source layer, so this sees exactly what the model sees: the same
    resampling, extent and grid alignment `write_grid` already applied.
    """
    ds = gdal.Open(path)
    if ds is None:
        raise RasterPrepError("Could not reopen %r to read its values." % path)
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray()
    nodata = band.GetNoDataValue()
    ds = None
    return arr, nodata


def write_constant(spec, value, crs, out_path, decimal_precision=3):
    """Write a uniform grid on `spec` (used for a constant Manning's n or rain mask)."""
    drv = gdal.GetDriverByName("MEM")
    mem = drv.Create("", spec.ncols, spec.nrows, 1, gdal.GDT_Float32)
    mem.SetGeoTransform(gridio.geotransform(spec))
    if crs is not None:
        srs = osr.SpatialReference()
        srs.SetFromUserInput(_srs_input(crs))
        mem.SetProjection(srs.ExportToWkt())
    band = mem.GetRasterBand(1)
    band.SetNoDataValue(gridio.NODATA)
    band.Fill(float(value))
    gdal.Translate(out_path, mem, format="AAIGrid",
                   creationOptions=["DECIMAL_PRECISION=%d" % int(decimal_precision)])
    mem = None
    if crs is not None:
        gridio.write_prj(os.path.splitext(out_path)[0] + ".prj", crs_to_esri_wkt(crs))
    return out_path


def check_alignment(paths, reference_spec):
    """Confirm every written grid really does share the DEM's geometry."""
    problems = []
    for path in paths:
        try:
            spec = gridio.read_header(path)
        except gridio.GridError as exc:
            problems.append(str(exc))
            continue
        if not gridio.same_grid(spec, reference_spec):
            problems.append(
                "%s is %s but the DEM grid is %s. LISFLOOD-FP ignores this file's "
                "header and reads its values straight onto the DEM grid, so the "
                "mismatch would be absorbed silently."
                % (os.path.basename(path), gridio.describe(spec),
                   gridio.describe(reference_spec)))
    return problems
