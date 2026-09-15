"""Build a complete LISFLOOD-FP deck from QGIS layers."""

import os

from qgis.core import (QgsCoordinateTransform, QgsProcessingException,
                       QgsProcessingParameterBoolean, QgsProcessingParameterCrs,
                       QgsProcessingParameterEnum, QgsProcessingParameterExtent,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterField,
                       QgsProcessingParameterFolderDestination,
                       QgsProcessingParameterMatrix, QgsProcessingParameterNumber,
                       QgsProcessingParameterRasterLayer, QgsProcessingParameterString,
                       QgsProcessing)

from ..core import bc as BC
from ..core import gridio
from ..core.river import write_river
from ..core.par import ParFile
from ..gis import rasterprep
from ..gis.vectorprep import VectorPrepError, build_river
from ..qt_compat import advanced_flag, distance_unit_meters
from .base import LisfloodAlgorithm

SOLVERS = [
    ("acceleration", "Acceleration (local inertial) - recommended"),
    ("", "Adaptive storage cell (model default)"),
    ("adaptoff", "Storage cell, fixed timestep (adaptoff)"),
    ("diffusive", "Diffusive channel solver"),
    ("Roe", "Roe shallow water"),
    ("fv1", "FV1 shallow water"),
]
OUTPUTS = [
    ("depth", "Water depth (.wd)"),
    ("elev", "Water surface elevation (.elev)"),
    ("velocity", "Velocity (.Vx/.Vy)"),
    ("discharge", "Discharge (.Qx/.Qy)"),
    ("hazard", "Hazard grids"),
]
UNITS = ["seconds", "minutes", "hours", "days"]


class BuildModelAlgorithm(LisfloodAlgorithm):
    GROUP = "Model setup"
    GROUP_ID = "setup"

    DEM = "DEM"; EXTENT = "EXTENT"; CELLSIZE = "CELLSIZE"; RESAMPLING = "RESAMPLING"
    CRS = "CRS"
    MANNING = "MANNING"; MANNING_VALUE = "MANNING_VALUE"; START_DEPTH = "START_DEPTH"
    BOUNDARY_POINTS = "BOUNDARY_POINTS"
    BC_TYPE_FIELD = "BC_TYPE_FIELD"; BC_VALUE_FIELD = "BC_VALUE_FIELD"
    BC_SERIES_FIELD = "BC_SERIES_FIELD"
    EDGE_BOUNDARIES = "EDGE_BOUNDARIES"
    AUTO_OUTFLOW = "AUTO_OUTFLOW"; AUTO_OUTFLOW_WIDTH = "AUTO_OUTFLOW_WIDTH"
    TIMESERIES = "TIMESERIES"; TS_NAME_FIELD = "TS_NAME_FIELD"
    TS_TIME_FIELD = "TS_TIME_FIELD"; TS_VALUE_FIELD = "TS_VALUE_FIELD"; TS_UNITS = "TS_UNITS"
    RAIN = "RAIN"; RAIN_UNITS = "RAIN_UNITS"
    RIVER = "RIVER"
    RIVER_WIDTH = "RIVER_WIDTH"; RIVER_MANNING = "RIVER_MANNING"
    RIVER_BED_UP = "RIVER_BED_UP"; RIVER_BED_DN = "RIVER_BED_DN"
    RIVER_BC_UP = "RIVER_BC_UP"; RIVER_BC_UP_VALUE = "RIVER_BC_UP_VALUE"
    RIVER_BC_DN = "RIVER_BC_DN"; RIVER_BC_DN_VALUE = "RIVER_BC_DN_VALUE"
    RIVER_SNAP = "RIVER_SNAP"
    STAGE_POINTS = "STAGE_POINTS"
    SIM_TIME = "SIM_TIME"; INITIAL_TSTEP = "INITIAL_TSTEP"
    SAVEINT = "SAVEINT"; MASSINT = "MASSINT"
    SOLVER = "SOLVER"; OUTPUTS_P = "OUTPUTS"
    CHECKPOINT = "CHECKPOINT"; EXTRA_PAR = "EXTRA_PAR"; RESROOT = "RESROOT"
    OUTPUT = "OUTPUT"

    def name(self):
        return "buildmodel"

    def displayName(self):
        return self.tr("Build model deck")

    def shortHelpString(self):
        return self.tr(
            "Writes a complete, runnable LISFLOOD-FP deck from QGIS layers: the ASCII "
            "grids, the boundary and time series files, and the .par control file.\n\n"
            "Inflows are entered in m3/s. LISFLOOD-FP actually wants discharge per "
            "metre of cell width, so the conversion is applied for you -- getting this "
            "wrong scales every inflow by the cell size with no warning.\n\n"
            "Every grid is warped onto the DEM's exact grid, because the model reads "
            "ancillary grids straight onto the DEM geometry without checking their "
            "headers. A mismatch would be absorbed silently rather than reported.\n\n"
            "'Auto outflow' adds a FREE boundary at the lowest cell on the model's "
            "*edge* -- not the lowest cell in the whole DEM, since LISFLOOD-FP only "
            "applies boundary conditions along the domain perimeter. Use it alongside, "
            "not instead of, any inflow boundaries you define yourself.\n\n"
            "No executable is needed to build a deck.")

    # -- parameters ------------------------------------------------------
    def initAlgorithm(self, config=None):
        add = self.addParameter

        add(QgsProcessingParameterRasterLayer(self.DEM, self.tr("DEM")))
        add(QgsProcessingParameterExtent(self.EXTENT, self.tr("Model extent"), optional=True))
        add(QgsProcessingParameterNumber(
            self.CELLSIZE, self.tr("Cell size (0 = same as DEM)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0))

        add(QgsProcessingParameterRasterLayer(
            self.MANNING, self.tr("Manning's n grid"), optional=True))
        add(QgsProcessingParameterNumber(
            self.MANNING_VALUE, self.tr("Manning's n (uniform, or fill for nodata)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.06, minValue=0.0))
        add(QgsProcessingParameterRasterLayer(
            self.START_DEPTH, self.tr("Initial water depth grid"), optional=True))

        add(QgsProcessingParameterFeatureSource(
            self.BOUNDARY_POINTS, self.tr("Boundary points"),
            types=[QgsProcessing.TypeVectorPoint], optional=True))
        add(QgsProcessingParameterField(
            self.BC_TYPE_FIELD, self.tr("Boundary type field (FREE/HFIX/QFIX/HVAR/QVAR)"),
            parentLayerParameterName=self.BOUNDARY_POINTS, optional=True,
            defaultValue="bctype"))
        add(QgsProcessingParameterField(
            self.BC_VALUE_FIELD, self.tr("Value field (m for HFIX, m3/s for QFIX)"),
            parentLayerParameterName=self.BOUNDARY_POINTS, optional=True,
            defaultValue="value"))
        add(QgsProcessingParameterField(
            self.BC_SERIES_FIELD, self.tr("Series name field (for HVAR/QVAR)"),
            parentLayerParameterName=self.BOUNDARY_POINTS, optional=True,
            defaultValue="series"))

        add(QgsProcessingParameterMatrix(
            self.EDGE_BOUNDARIES, self.tr("Edge boundaries"),
            headers=["Edge (N/S/E/W)", "From", "To", "Type", "Value or series"],
            defaultValue=[], optional=True))
        add(QgsProcessingParameterBoolean(
            self.AUTO_OUTFLOW, self.tr(
                "Auto outflow: add a FREE boundary at the DEM's lowest edge cell"),
            defaultValue=False))

        add(QgsProcessingParameterFeatureSource(
            self.TIMESERIES, self.tr("Time series table (for HVAR/QVAR)"),
            optional=True))
        add(QgsProcessingParameterField(
            self.TS_NAME_FIELD, self.tr("Series name field"),
            parentLayerParameterName=self.TIMESERIES, optional=True, defaultValue="name"))
        add(QgsProcessingParameterField(
            self.TS_TIME_FIELD, self.tr("Time field"),
            parentLayerParameterName=self.TIMESERIES, optional=True, defaultValue="time"))
        add(QgsProcessingParameterField(
            self.TS_VALUE_FIELD, self.tr("Value field (m3/s or m)"),
            parentLayerParameterName=self.TIMESERIES, optional=True, defaultValue="value"))
        add(QgsProcessingParameterEnum(
            self.TS_UNITS, self.tr("Time units"), options=UNITS, defaultValue=0))

        add(QgsProcessingParameterMatrix(
            self.RAIN, self.tr("Rainfall (time, mm/hr)"),
            headers=["Time", "Rain (mm/hr)"], defaultValue=[], optional=True))
        add(QgsProcessingParameterEnum(
            self.RAIN_UNITS, self.tr("Rainfall time units"), options=UNITS, defaultValue=0))

        add(QgsProcessingParameterFeatureSource(
            self.RIVER, self.tr("Channel network (lines)"),
            types=[QgsProcessing.TypeVectorLine], optional=True))
        add(QgsProcessingParameterField(
            self.RIVER_WIDTH, self.tr("Channel width field (m)"),
            parentLayerParameterName=self.RIVER, optional=True, defaultValue="width"))
        add(QgsProcessingParameterField(
            self.RIVER_MANNING, self.tr("Channel Manning's n field"),
            parentLayerParameterName=self.RIVER, optional=True, defaultValue="manning"))
        add(QgsProcessingParameterField(
            self.RIVER_BED_UP, self.tr("Bed elevation field, upstream end (m)"),
            parentLayerParameterName=self.RIVER, optional=True, defaultValue="bed_up"))
        add(QgsProcessingParameterField(
            self.RIVER_BED_DN, self.tr("Bed elevation field, downstream end (m)"),
            parentLayerParameterName=self.RIVER, optional=True, defaultValue="bed_dn"))

        add(QgsProcessingParameterFeatureSource(
            self.STAGE_POINTS, self.tr("Stage output points"),
            types=[QgsProcessing.TypeVectorPoint], optional=True))

        add(QgsProcessingParameterNumber(
            self.SIM_TIME, self.tr("Simulation time (s)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=3600.0, minValue=0.0))
        add(QgsProcessingParameterNumber(
            self.SAVEINT, self.tr("Save interval (s, 0 = sim_time/20)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0))
        add(QgsProcessingParameterEnum(
            self.SOLVER, self.tr("Solver"),
            options=[label for _, label in SOLVERS], defaultValue=0))
        add(QgsProcessingParameterEnum(
            self.OUTPUTS_P, self.tr("Outputs"),
            options=[label for _, label in OUTPUTS], allowMultiple=True,
            defaultValue=[0, 2]))
        add(QgsProcessingParameterFolderDestination(
            self.OUTPUT, self.tr("Deck folder")))

        for param in (
            QgsProcessingParameterNumber(
                self.INITIAL_TSTEP, self.tr("Initial timestep (s)"),
                type=QgsProcessingParameterNumber.Double, defaultValue=1.0, minValue=0.0),
            QgsProcessingParameterNumber(
                self.MASSINT, self.tr("Mass balance interval (s, 0 = automatic)"),
                type=QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0),
            QgsProcessingParameterNumber(
                self.CHECKPOINT, self.tr("Checkpoint every N hours (0 = off)"),
                type=QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0),
            QgsProcessingParameterEnum(
                self.RESAMPLING, self.tr("Resampling"),
                options=["nearest", "bilinear", "cubic", "average"], defaultValue=1),
            QgsProcessingParameterCrs(self.CRS, self.tr("Model CRS (blank = DEM's)"),
                                      defaultValue="", optional=True),
            QgsProcessingParameterString(self.RESROOT, self.tr("Results prefix"),
                                         defaultValue="res"),
            QgsProcessingParameterField(
                self.RIVER_BC_UP, self.tr("Channel upstream boundary type field"),
                parentLayerParameterName=self.RIVER, optional=True, defaultValue="bc_up"),
            QgsProcessingParameterField(
                self.RIVER_BC_UP_VALUE, self.tr("Channel upstream boundary value field"),
                parentLayerParameterName=self.RIVER, optional=True,
                defaultValue="bc_up_value"),
            QgsProcessingParameterField(
                self.RIVER_BC_DN, self.tr("Channel downstream boundary type field"),
                parentLayerParameterName=self.RIVER, optional=True, defaultValue="bc_dn"),
            QgsProcessingParameterField(
                self.RIVER_BC_DN_VALUE, self.tr("Channel downstream boundary value field"),
                parentLayerParameterName=self.RIVER, optional=True,
                defaultValue="bc_dn_value"),
            QgsProcessingParameterNumber(
                self.RIVER_SNAP, self.tr("Junction snap distance (m, 0 = one cell)"),
                type=QgsProcessingParameterNumber.Double, defaultValue=0.0, minValue=0.0),
            QgsProcessingParameterNumber(
                self.AUTO_OUTFLOW_WIDTH, self.tr("Auto outflow width (cells)"),
                type=QgsProcessingParameterNumber.Integer, defaultValue=1, minValue=1),
            QgsProcessingParameterString(
                self.EXTRA_PAR, self.tr("Additional .par keywords, one per line"),
                defaultValue="", optional=True, multiLine=True),
        ):
            param.setFlags(param.flags() | advanced_flag())
            add(param)

    # -- execution -------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        deck = self.parameterAsString(parameters, self.OUTPUT, context)
        if not os.path.isdir(deck):
            os.makedirs(deck)
        results_dir = os.path.join(deck, "results")
        if not os.path.isdir(results_dir):
            os.makedirs(results_dir)      # avoids the model's unquoted system("mkdir")

        dem_layer = self.parameterAsRasterLayer(parameters, self.DEM, context)
        if dem_layer is None:
            raise QgsProcessingException(self.tr("A DEM is required."))

        crs = self.parameterAsCrs(parameters, self.CRS, context)
        if crs is None or not crs.isValid():
            crs = dem_layer.crs()
        self._check_crs(crs, feedback)

        cellsize = self.parameterAsDouble(parameters, self.CELLSIZE, context) or None
        extent = self.parameterAsExtent(parameters, self.EXTENT, context, crs)
        spec = rasterprep.spec_from_layer(dem_layer, cellsize, extent)
        feedback.pushInfo("Model grid: %s" % gridio.describe(spec))
        self._check_size(spec, feedback)

        resample = ["nearest", "bilinear", "cubic", "average"][
            self.parameterAsEnum(parameters, self.RESAMPLING, context)]

        par = ParFile()
        par.header_comments = [
            "LISFLOOD-FP deck generated by the QGIS plugin",
            "Grid: %s" % gridio.describe(spec),
            "CRS:  %s" % (crs.authid() or crs.description() or "unknown"),
            "Discharges below are per metre of cell width, converted from m3/s.",
        ]

        written = []
        dem_path = os.path.join(deck, "dem.asc")
        rasterprep.write_grid(dem_layer, spec, crs, dem_path, resample=resample)
        written.append(dem_path)
        par.set("DEMfile", "dem.asc")

        manning = self.parameterAsRasterLayer(parameters, self.MANNING, context)
        n_value = self.parameterAsDouble(parameters, self.MANNING_VALUE, context)
        par.set("fpfric", "%g" % n_value)
        if manning is not None:
            path = os.path.join(deck, "manning.asc")
            rasterprep.write_grid(manning, spec, crs, path, resample=resample,
                                  fill_nodata=n_value)
            written.append(path)
            par.set("manningfile", "manning.asc")

        start = self.parameterAsRasterLayer(parameters, self.START_DEPTH, context)
        if start is not None:
            path = os.path.join(deck, "start.asc")
            rasterprep.write_grid(start, spec, crs, path, resample=resample, fill_nodata=0.0)
            written.append(path)
            par.set("startfile", "start.asc")

        problems = rasterprep.check_alignment(written, spec)
        for problem in problems:
            feedback.reportError(problem)
        if problems:
            raise QgsProcessingException(self.tr("Grids are not aligned with the DEM."))

        series = self._read_series(parameters, context, feedback, spec)
        points = self._read_points(parameters, context, crs, spec, feedback)
        edges = self._read_edges(parameters, context, spec, feedback)
        if self.parameterAsBoolean(parameters, self.AUTO_OUTFLOW, context):
            width = self.parameterAsInt(parameters, self.AUTO_OUTFLOW_WIDTH, context) or 1
            outflow = self._auto_outflow(dem_path, spec, width, feedback)
            if outflow is not None:
                edges = [outflow] + list(edges)
        river_segments = self._read_river(parameters, context, crs, spec, series, feedback)
        series = self._convert_series(series, points, edges, spec, feedback,
                                      river_segments)

        if points or edges:
            BC.write_bci(os.path.join(deck, "bc.bci"), points, edges)
            par.set("bcifile", "bc.bci")
            for message in BC.cross_validate(points, edges, series):
                if message.startswith("WARN "):
                    feedback.pushWarning(message[5:])
                else:
                    raise QgsProcessingException(message)
        if river_segments:
            write_river(os.path.join(deck, "channel.river"), river_segments)
            par.set("riverfile", "channel.river")
        if series:
            BC.write_bdy(os.path.join(deck, "bc.bdy"), series)
            par.set("bdyfile", "bc.bdy")

        rain = self._read_rain(parameters, context)
        if rain is not None:
            BC.write_timeseries(os.path.join(deck, "rain.txt"), rain)
            par.set("rainfall", "rain.txt")

        stage = self.parameterAsSource(parameters, self.STAGE_POINTS, context)
        if stage is not None:
            pts = self._points_xy(stage, crs, context)
            if pts:
                BC.write_stage(os.path.join(deck, "out.stage"), pts)
                par.set("stagefile", "out.stage")

        self._run_control(par, parameters, context)
        self._solver_and_outputs(par, parameters, context)

        par.set("resroot", self.parameterAsString(parameters, self.RESROOT, context) or "res")
        par.set("dirroot", "results")
        par.merge_text(self.parameterAsString(parameters, self.EXTRA_PAR, context))

        issues = par.validate(deck_dir=deck)
        blocking = [i for i in issues if i.blocking]
        for issue in issues:
            text = "%s: %s" % (issue.key, issue.message)
            feedback.reportError(text) if issue.blocking else feedback.pushInfo(text)
        if blocking:
            raise QgsProcessingException(self.tr(
                "The generated deck has %d problem(s); see the log." % len(blocking)))

        par_path = par.write(os.path.join(deck, "model.par"))
        feedback.pushInfo("Deck written to %s" % deck)
        return {"PAR_FILE": par_path, "DECK_FOLDER": deck,
                "RESULTS_FOLDER": results_dir}

    # -- pieces ----------------------------------------------------------
    def _check_crs(self, crs, feedback):
        if not crs.isValid():
            raise QgsProcessingException(self.tr(
                "The DEM has no CRS. LISFLOOD-FP is CRS-blind, so the plugin cannot "
                "georeference the results or confirm the cell size is in metres."))
        if crs.isGeographic():
            raise QgsProcessingException(self.tr(
                "The DEM is in a geographic CRS (%s), so its cell size is in degrees. "
                "LISFLOOD-FP would treat that as metres and every depth, discharge and "
                "roughness would be meaningless. Reproject to a projected CRS in metres."
                % crs.authid()))
        try:
            if crs.mapUnits() != distance_unit_meters():
                feedback.pushWarning(
                    "The CRS's map units are not metres. LISFLOOD-FP assumes SI "
                    "throughout, including gravity and Manning's equation.")
        except (AttributeError, TypeError):
            pass

    def _check_size(self, spec, feedback):
        cells = spec.ncols * spec.nrows
        if cells > 50e6:
            raise QgsProcessingException(self.tr(
                "The model grid is %d cells, which needs roughly %.1f GB of memory. "
                "Coarsen the cell size or clip the extent."
                % (cells, cells * 420 / 1e9)))
        if cells > 5e6:
            feedback.pushWarning(
                "The model grid is %d cells (about %.1f GB of memory, and large ASCII "
                "output). Consider a coarser cell size."
                % (cells, cells * 420 / 1e9))

    def _read_series(self, parameters, context, feedback, spec):
        source = self.parameterAsSource(parameters, self.TIMESERIES, context)
        if source is None:
            return []
        name_f = self.parameterAsString(parameters, self.TS_NAME_FIELD, context) or "name"
        time_f = self.parameterAsString(parameters, self.TS_TIME_FIELD, context) or "time"
        value_f = self.parameterAsString(parameters, self.TS_VALUE_FIELD, context) or "value"
        units = UNITS[self.parameterAsEnum(parameters, self.TS_UNITS, context)]

        gathered = {}
        for feature in source.getFeatures():
            try:
                name = str(feature[name_f])
                t = float(feature[time_f])
                v = float(feature[value_f])
            except (KeyError, TypeError, ValueError):
                continue
            gathered.setdefault(name, []).append((t, v))

        out = []
        for name, rows in gathered.items():
            rows.sort()
            times = [t for t, _ in rows]
            values = [v for _, v in rows]
            out.append(BC.Series(name, units, times, values))
        if out:
            feedback.pushInfo("Read %d time series: %s"
                              % (len(out), ", ".join(s.name for s in out)))
        return out

    def _read_river(self, parameters, context, crs, spec, series, feedback):
        source = self.parameterAsSource(parameters, self.RIVER, context)
        if source is None:
            return None
        fields = {
            "width": self.parameterAsString(parameters, self.RIVER_WIDTH, context),
            "manning": self.parameterAsString(parameters, self.RIVER_MANNING, context),
            "bed_up": self.parameterAsString(parameters, self.RIVER_BED_UP, context),
            "bed_dn": self.parameterAsString(parameters, self.RIVER_BED_DN, context),
            "bc_up": self.parameterAsString(parameters, self.RIVER_BC_UP, context),
            "bc_up_value": self.parameterAsString(
                parameters, self.RIVER_BC_UP_VALUE, context),
            "bc_dn": self.parameterAsString(parameters, self.RIVER_BC_DN, context),
            "bc_dn_value": self.parameterAsString(
                parameters, self.RIVER_BC_DN_VALUE, context),
        }
        snap = self.parameterAsDouble(parameters, self.RIVER_SNAP, context) or None
        try:
            return build_river(source, crs, context, fields, spec,
                               series_names=set(s.name for s in series),
                               tolerance=snap, feedback=feedback)
        except VectorPrepError as exc:
            raise QgsProcessingException(str(exc))

    @staticmethod
    def _river_series_names(river_segments):
        """Series referenced by the channel network, which are already in m3/s."""
        names = set()
        for points in river_segments or ():
            for p in points:
                if p.bctype in ("QVAR", "HVAR", "RATE") and p.bcvalue:
                    names.add(str(p.bcvalue))
        return names

    def _convert_series(self, series, points, edges, spec, feedback,
                        river_segments=None):
        """Convert QVAR series from m3/s to the model's per-metre convention.

        A series carries its values in the .bdy, so the conversion cannot be done when
        the boundary is written -- it depends on which boundary refers to the series and
        how many cells that boundary spans. HVAR series are water elevations and must
        not be touched.
        """
        channel_names = self._river_series_names(river_segments)
        usage = {}
        for bcs, n_cells in ((points, 1), (edges, None)):
            for item in bcs:
                if item.type.upper() not in BC.VARYING or not item.series:
                    continue
                cells = n_cells
                if cells is None:
                    cells = BC.edge_cell_count(item.edge, item.start, item.finish, spec)
                usage.setdefault(item.series, []).append((item.type.upper(), cells))

        out = []
        for s in series:
            uses = usage.get(s.name, [])
            kinds = set(k for k, _ in uses)
            if s.name in channel_names:
                # channel discharge really is m3/s, unlike .bci -- see core/river.py
                if uses:
                    raise QgsProcessingException(self.tr(
                        "Series %r is used by both the channel network and a .bci "
                        "boundary. Those take different units -- m3/s in the channel, "
                        "per metre of cell width at a .bci boundary -- so give each "
                        "one its own series." % s.name))
                out.append(s)
                continue
            if not uses:
                out.append(s)
                continue
            if kinds == {"HVAR"}:
                out.append(s)                      # water elevations, no conversion
                continue
            if len(kinds) > 1:
                raise QgsProcessingException(self.tr(
                    "Series %r is used as both a discharge and a water level boundary. "
                    "Those need different units, so give each one its own series."
                    % s.name))
            widths = set(c for _, c in uses)
            if len(widths) > 1:
                raise QgsProcessingException(self.tr(
                    "Series %r is shared by boundaries spanning different numbers of "
                    "cells (%s). LISFLOOD-FP applies discharge per metre of cell width, "
                    "so one series cannot serve both. Duplicate it under a second name."
                    % (s.name, ", ".join(str(w) for w in sorted(widths)))))
            cells = widths.pop()
            if cells < 1:
                raise QgsProcessingException(self.tr(
                    "Series %r is used by a boundary that covers no cells." % s.name))
            values = [BC.to_model_discharge(v, spec.cellsize, cells) for v in s.values]
            feedback.pushInfo(
                "Series %r: discharge converted from m3/s to m2/s over %d cell(s) "
                "(peak %.6g -> %.6g)."
                % (s.name, cells, max(s.values) if s.values else 0.0,
                   max(values) if values else 0.0))
            out.append(BC.Series(s.name, s.units, s.times, values))
        return out

    def _read_points(self, parameters, context, crs, spec, feedback):
        source = self.parameterAsSource(parameters, self.BOUNDARY_POINTS, context)
        if source is None:
            return []
        type_f = self.parameterAsString(parameters, self.BC_TYPE_FIELD, context) or "bctype"
        value_f = self.parameterAsString(parameters, self.BC_VALUE_FIELD, context) or "value"
        series_f = self.parameterAsString(parameters, self.BC_SERIES_FIELD, context) or "series"

        transform = None
        if source.sourceCrs() != crs:
            transform = QgsCoordinateTransform(source.sourceCrs(), crs, context.project())

        xmax = spec.xll + spec.ncols * spec.cellsize
        ymax = spec.yll + spec.nrows * spec.cellsize
        out = []
        for feature in source.getFeatures():
            geom = feature.geometry()
            if geom.isEmpty():
                continue
            if transform is not None:
                geom.transform(transform)
            pt = geom.asPoint()
            if not (spec.xll <= pt.x() <= xmax and spec.yll <= pt.y() <= ymax):
                raise QgsProcessingException(self.tr(
                    "Boundary point at (%g, %g) lies outside the model domain. "
                    "LISFLOOD-FP indexes point sources with no bounds check and writes "
                    "straight into the depth array, so this would crash the run."
                    % (pt.x(), pt.y())))
            bctype = str(feature[type_f]).strip().upper() if type_f in source.fields().names() else "FREE"
            value = self._field(feature, value_f)
            name = self._field(feature, series_f, as_str=True)
            if bctype == "QFIX" and value is not None:
                value = BC.to_model_discharge(float(value), spec.cellsize)
                feedback.pushInfo(
                    "Point QFIX converted to %.6g m2/s (per metre of cell width)." % value)
            out.append(BC.PointBC(pt.x(), pt.y(), bctype, value, name))
        return out

    def _read_edges(self, parameters, context, spec, feedback):
        rows = self.parameterAsMatrix(parameters, self.EDGE_BOUNDARIES, context) or []
        out = []
        for i in range(0, len(rows) - 4, 5):
            edge, start, finish, bctype, tail = rows[i:i + 5]
            if not str(edge).strip():
                continue
            bctype = str(bctype).strip().upper()
            start, finish = float(start), float(finish)
            n_cells = BC.edge_cell_count(str(edge), start, finish, spec)
            if n_cells == 0:
                raise QgsProcessingException(self.tr(
                    "Edge boundary %s %g to %g covers no cells on a %g m grid. "
                    "LISFLOOD-FP would silently drop it."
                    % (edge, start, finish, spec.cellsize)))
            value, name = None, None
            if bctype in BC.VARYING:
                name = str(tail).strip()
            elif str(tail).strip():
                value = float(tail)
                if bctype == "QFIX":
                    value = BC.to_model_discharge(value, spec.cellsize, n_cells)
                    feedback.pushInfo(
                        "Edge QFIX over %d cells converted to %.6g m2/s." % (n_cells, value))
            out.append(BC.EdgeBC(str(edge), start, finish, bctype, value, name))
        return out

    def _auto_outflow(self, dem_path, spec, width, feedback):
        """A FREE EdgeBC at the model grid's lowest perimeter cell.

        Deliberately restricted to the perimeter: LISFLOOD-FP only ever applies
        boundary conditions along the N/S/E/W edges, so the lowest point in the
        DEM overall would be meaningless here unless it also happens to sit on
        the boundary -- an interior low point is just a sink the model ponds into.
        """
        elev, nodata = rasterprep.read_grid_values(dem_path)
        found = BC.lowest_edge_cell(spec, elev, nodata)
        if found is None:
            feedback.pushWarning(
                "Auto outflow: every edge cell of the model grid is NODATA; "
                "no outflow boundary was added.")
            return None
        edge, row, col = found
        feedback.pushInfo(
            "Auto outflow: FREE boundary added on the %s edge at elevation %.3g m "
            "(the lowest point on the model boundary)." % (edge, elev[row][col]))
        outflow = BC.outflow_edge_bc(spec, edge, row, col, elev, nodata, width=width)
        actual = BC.edge_cell_count(edge, outflow.start, outflow.finish, spec)
        if actual < width:
            feedback.pushWarning(
                "Auto outflow: asked for %d cells wide, but only %d cells of real "
                "DEM data were available next to the lowest edge cell before hitting "
                "NODATA (which LISFLOOD-FP treats as a wall); the opening was narrowed "
                "to fit." % (width, actual))
        return outflow

    def _read_rain(self, parameters, context):
        rows = self.parameterAsMatrix(parameters, self.RAIN, context) or []
        units = UNITS[self.parameterAsEnum(parameters, self.RAIN_UNITS, context)]
        times, values = [], []
        for i in range(0, len(rows) - 1, 2):
            try:
                times.append(float(rows[i]))
                values.append(float(rows[i + 1]))
            except (TypeError, ValueError):
                continue
        if not times:
            return None
        return BC.Series("rain", units, times, values)

    def _run_control(self, par, parameters, context):
        sim = self.parameterAsDouble(parameters, self.SIM_TIME, context)
        save = self.parameterAsDouble(parameters, self.SAVEINT, context) or sim / 20.0
        mass = (self.parameterAsDouble(parameters, self.MASSINT, context)
                or min(sim / 500.0, 300.0) or 1.0)
        par.set("sim_time", "%g" % sim)
        par.set("initial_tstep",
                "%g" % self.parameterAsDouble(parameters, self.INITIAL_TSTEP, context))
        par.set("saveint", "%g" % save)
        par.set("massint", "%g" % mass)
        par.set("comp_out")
        checkpoint = self.parameterAsDouble(parameters, self.CHECKPOINT, context)
        if checkpoint > 0:
            par.set("checkpoint", "%g" % checkpoint)

    def _solver_and_outputs(self, par, parameters, context):
        keyword = SOLVERS[self.parameterAsEnum(parameters, self.SOLVER, context)][0]
        if keyword:
            par.set(keyword)
        chosen = set(OUTPUTS[i][0]
                     for i in self.parameterAsEnums(parameters, self.OUTPUTS_P, context))
        if "depth" not in chosen:
            par.set("depthoff")
        if "elev" not in chosen:
            par.set("elevoff")
        if "velocity" in chosen:
            par.set("voutput")
        if "discharge" in chosen:
            par.set("qoutput")
        if "hazard" in chosen:
            par.set("hazard")

    @staticmethod
    def _field(feature, name, as_str=False):
        try:
            value = feature[name]
        except KeyError:
            return None
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.upper() == "NULL":
            return None
        return text if as_str else float(text)

    @staticmethod
    def _points_xy(source, crs, context):
        transform = None
        if source.sourceCrs() != crs:
            transform = QgsCoordinateTransform(source.sourceCrs(), crs, context.project())
        out = []
        for feature in source.getFeatures():
            geom = feature.geometry()
            if geom.isEmpty():
                continue
            if transform is not None:
                geom.transform(transform)
            pt = geom.asPoint()
            out.append((pt.x(), pt.y()))
        return out
