"""The guided LISFLOOD-FP panel.

Wraps exactly the same core calls the Processing algorithms use -- it builds the deck
by running `lisfloodfp:buildmodel`, so the two paths cannot drift apart. What it adds
is a single screen for setting a scenario up, and a live view of a running model:
wetted area and Qin/Qout answer "is anything actually happening?" long before the
depth grids do.
"""

import os

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsMapLayerProxyModel,
                       QgsProject, Qgis)
from qgis.gui import (QgsExtentGroupBox, QgsFieldComboBox, QgsFileWidget,
                      QgsMapLayerComboBox)
from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox,
                                 QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
                                 QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
                                 QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
                                 QVBoxLayout, QWidget)

from ..algs.alg_build_model import OUTPUTS, SOLVERS
from ..core.runner import RunnerError, probe
from ..gis import settings
from ..gis.loader import load_results
from ..qt_compat import enum_value, monospace_font
from .task import RunTask


class LisfloodDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super(LisfloodDock, self).__init__(self.tr("LISFLOOD-FP"), parent)
        self.iface = iface
        self.setObjectName("LisfloodFpDock")
        self.task = None
        self._deck = None
        self._build_ui()
        self._refresh_binary()

    # -- construction ----------------------------------------------------
    def _build_ui(self):
        tabs = QTabWidget()
        tabs.addTab(self._scroll(self._setup_tab()), self.tr("Model"))
        tabs.addTab(self._run_tab(), self.tr("Run"))
        self.tabs = tabs

        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(6, 6, 6, 6)
        self.binary_label = QLabel()
        self.binary_label.setWordWrap(True)
        layout.addWidget(self.binary_label)
        layout.addWidget(tabs)
        self.setWidget(outer)

    @staticmethod
    def _scroll(widget):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(widget)
        return area

    def _setup_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)

        # domain
        box = QGroupBox(self.tr("Domain"))
        form = QFormLayout(box)
        self.dem_combo = QgsMapLayerComboBox()
        self.dem_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        form.addRow(self.tr("DEM"), self.dem_combo)
        self.extent_box = QgsExtentGroupBox()
        self.extent_box.setTitle(self.tr("Extent (optional)"))
        self.extent_box.setCheckable(True)
        self.extent_box.setChecked(False)
        form.addRow(self.extent_box)
        self.cellsize = self._spin(0.0, 0.0, 1e6, 2, self.tr("0 = same as DEM"))
        form.addRow(self.tr("Cell size (m)"), self.cellsize)
        outer.addWidget(box)

        # roughness and initial state
        box = QGroupBox(self.tr("Roughness and initial condition"))
        form = QFormLayout(box)
        self.manning_combo = QgsMapLayerComboBox()
        self.manning_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.manning_combo.setAllowEmptyLayer(True)
        self.manning_combo.setCurrentIndex(0)
        form.addRow(self.tr("Manning's n grid"), self.manning_combo)
        self.manning_value = self._spin(0.06, 0.0, 1.0, 3)
        form.addRow(self.tr("Manning's n"), self.manning_value)
        self.start_combo = QgsMapLayerComboBox()
        self.start_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.start_combo.setAllowEmptyLayer(True)
        self.start_combo.setCurrentIndex(0)
        form.addRow(self.tr("Initial depth"), self.start_combo)
        outer.addWidget(box)

        # boundaries
        box = QGroupBox(self.tr("Boundaries"))
        vbox = QVBoxLayout(box)
        form = QFormLayout()
        self.bc_points = QgsMapLayerComboBox()
        self.bc_points.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.bc_points.setAllowEmptyLayer(True)
        self.bc_points.setCurrentIndex(0)
        form.addRow(self.tr("Point boundaries"), self.bc_points)
        self.ts_table = QgsMapLayerComboBox()
        self.ts_table.setFilters(QgsMapLayerProxyModel.VectorLayer |
                                 QgsMapLayerProxyModel.NoGeometry)
        self.ts_table.setAllowEmptyLayer(True)
        self.ts_table.setCurrentIndex(0)
        form.addRow(self.tr("Time series table"), self.ts_table)
        vbox.addLayout(form)
        vbox.addWidget(QLabel(self.tr(
            "Discharges are entered in m³/s and converted automatically.")))
        vbox.addWidget(QLabel(self.tr("Edge boundaries:")))
        self.edges = QTableWidget(0, 5)
        self.edges.setHorizontalHeaderLabels(
            [self.tr("Edge"), self.tr("From"), self.tr("To"),
             self.tr("Type"), self.tr("Value / series")])
        self.edges.setMaximumHeight(140)
        vbox.addWidget(self.edges)
        row = QHBoxLayout()
        add = QPushButton(self.tr("Add edge"))
        add.clicked.connect(lambda: self.edges.insertRow(self.edges.rowCount()))
        remove = QPushButton(self.tr("Remove"))
        remove.clicked.connect(self._remove_edge)
        row.addWidget(add); row.addWidget(remove); row.addStretch()
        vbox.addLayout(row)

        self.auto_outflow = QCheckBox(self.tr(
            "Auto outflow: add a FREE boundary at the DEM's lowest edge cell"))
        vbox.addWidget(self.auto_outflow)
        outflow_row = QHBoxLayout()
        outflow_row.addWidget(QLabel(self.tr("Width (cells)")))
        self.auto_outflow_width = QSpinBox()
        self.auto_outflow_width.setRange(1, 1000)
        self.auto_outflow_width.setValue(1)
        self.auto_outflow_width.setEnabled(False)
        self.auto_outflow.toggled.connect(self.auto_outflow_width.setEnabled)
        outflow_row.addWidget(self.auto_outflow_width)
        outflow_row.addStretch()
        vbox.addLayout(outflow_row)
        outer.addWidget(box)

        # channel network
        box = QGroupBox(self.tr("Channel network (optional)"))
        form = QFormLayout(box)
        self.river_layer = QgsMapLayerComboBox()
        self.river_layer.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.river_layer.setAllowEmptyLayer(True)
        self.river_layer.setCurrentIndex(0)
        form.addRow(self.tr("Channel lines"), self.river_layer)
        self.river_fields = {}
        for key, label, default in (
                ("RIVER_WIDTH", self.tr("Width field"), "width"),
                ("RIVER_MANNING", self.tr("Manning's n field"), "manning"),
                ("RIVER_BED_UP", self.tr("Bed elevation, upstream"), "bed_up"),
                ("RIVER_BED_DN", self.tr("Bed elevation, downstream"), "bed_dn"),
                ("RIVER_BC_UP", self.tr("Upstream boundary type"), "bc_up"),
                ("RIVER_BC_UP_VALUE", self.tr("Upstream boundary value"), "bc_up_value"),
                ("RIVER_BC_DN", self.tr("Downstream boundary type"), "bc_dn"),
                ("RIVER_BC_DN_VALUE", self.tr("Downstream boundary value"), "bc_dn_value")):
            combo = QgsFieldComboBox()
            combo.setAllowEmptyFieldName(True)
            self.river_fields[key] = (combo, default)
            form.addRow(label, combo)
        self.river_layer.layerChanged.connect(self._river_layer_changed)
        note = QLabel(self.tr(
            "Each line is one channel segment. Junctions are found automatically: a "
            "segment ending on another is snapped to it and both sides written. "
            "Channel discharge is m³/s and is not rescaled."))
        note.setWordWrap(True)
        form.addRow(note)
        outer.addWidget(box)

        # rainfall
        box = QGroupBox(self.tr("Rainfall"))
        vbox = QVBoxLayout(box)
        self.rain = QTableWidget(0, 2)
        self.rain.setHorizontalHeaderLabels([self.tr("Time (s)"), self.tr("mm/hr")])
        self.rain.setMaximumHeight(120)
        vbox.addWidget(self.rain)
        row = QHBoxLayout()
        add = QPushButton(self.tr("Add row"))
        add.clicked.connect(lambda: self.rain.insertRow(self.rain.rowCount()))
        remove = QPushButton(self.tr("Remove"))
        remove.clicked.connect(lambda: self.rain.removeRow(self.rain.currentRow())
                               if self.rain.currentRow() >= 0 else None)
        row.addWidget(add); row.addWidget(remove); row.addStretch()
        vbox.addLayout(row)
        outer.addWidget(box)

        # run control
        box = QGroupBox(self.tr("Run control"))
        form = QFormLayout(box)
        self.sim_time = self._spin(3600.0, 0.0, 1e9, 1)
        form.addRow(self.tr("Simulation time (s)"), self.sim_time)
        self.saveint = self._spin(0.0, 0.0, 1e9, 1, self.tr("0 = sim_time / 20"))
        form.addRow(self.tr("Save interval (s)"), self.saveint)
        self.solver = QComboBox()
        for _, label in SOLVERS:
            self.solver.addItem(label)
        form.addRow(self.tr("Solver"), self.solver)
        self.outputs = QComboBox()
        self.outputs.addItems([self.tr("Depth only"),
                               self.tr("Depth + elevation"),
                               self.tr("Depth + velocity + discharge")])
        form.addRow(self.tr("Outputs"), self.outputs)
        self.threads = QSpinBox()
        self.threads.setRange(0, 256)
        self.threads.setSpecialValueText(self.tr("automatic"))
        form.addRow(self.tr("Threads"), self.threads)
        self.deck_widget = QgsFileWidget()
        self.deck_widget.setStorageMode(QgsFileWidget.GetDirectory)
        form.addRow(self.tr("Deck folder"), self.deck_widget)
        outer.addWidget(box)

        row = QHBoxLayout()
        self.build_button = QPushButton(self.tr("Build deck"))
        self.build_button.clicked.connect(lambda: self._go(run=False))
        self.run_button = QPushButton(self.tr("Build and run"))
        self.run_button.setDefault(True)
        self.run_button.clicked.connect(lambda: self._go(run=True))
        row.addWidget(self.build_button); row.addWidget(self.run_button)
        outer.addLayout(row)
        outer.addStretch()
        return page

    def _run_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        self.progress = QProgressBar()
        outer.addWidget(self.progress)
        self.status = QLabel(self.tr("Idle."))
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        box = QGroupBox(self.tr("Live mass balance"))
        form = QFormLayout(box)
        self.live = {}
        for key, label in (("area", self.tr("Wetted area (m²)")),
                           ("volume", self.tr("Volume (m³)")),
                           ("q", self.tr("Qin / Qout (m³/s)")),
                           ("tstep", self.tr("Min timestep (s)"))):
            widget = QLabel("-")
            self.live[key] = widget
            form.addRow(label, widget)
        outer.addWidget(box)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setFont(monospace_font(10))
        outer.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.cancel_button = QPushButton(self.tr("Cancel"))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        self.load_button = QPushButton(self.tr("Load results"))
        self.load_button.setEnabled(False)
        self.load_button.clicked.connect(self._load)
        row.addWidget(self.cancel_button); row.addWidget(self.load_button); row.addStretch()
        outer.addLayout(row)
        return page

    @staticmethod
    def _spin(value, lo, hi, decimals, tip=None):
        widget = QDoubleSpinBox()
        widget.setRange(lo, hi)
        widget.setDecimals(decimals)
        widget.setValue(value)
        if tip:
            widget.setToolTip(tip)
            widget.setSpecialValueText(tip)
        return widget

    def _river_layer_changed(self, layer):
        """Point the field pickers at the chosen layer and preselect the usual names."""
        for key, (combo, default) in self.river_fields.items():
            combo.setLayer(layer)
            if layer is None:
                continue
            names = [f.name() for f in layer.fields()]
            match = next((n for n in names if n.lower() == default), None)
            combo.setField(match if match else "")

    def _remove_edge(self):
        if self.edges.currentRow() >= 0:
            self.edges.removeRow(self.edges.currentRow())

    # -- state -----------------------------------------------------------
    def _refresh_binary(self):
        path = settings.binary_path()
        if not path:
            self.binary_label.setText(self.tr(
                "<b>No executable configured.</b> Building a deck works without one; "
                "running needs it. Use Processing ▸ LISFLOOD-FP ▸ Setup."))
            return
        try:
            caps = probe(path)
            self.binary_label.setText(self.tr("Using %s") % caps.describe())
        except RunnerError as exc:
            self.binary_label.setText(self.tr("<b>Executable problem:</b> %s") % exc)

    # -- actions ---------------------------------------------------------
    def _collect(self):
        dem = self.dem_combo.currentLayer()
        if dem is None:
            raise ValueError(self.tr("Choose a DEM."))
        deck = self.deck_widget.filePath()
        if not deck:
            raise ValueError(self.tr("Choose a deck folder."))

        edges = []
        for r in range(self.edges.rowCount()):
            cells = [self.edges.item(r, c) for c in range(5)]
            if not cells[0] or not cells[0].text().strip():
                continue
            edges.extend([(c.text().strip() if c else "") for c in cells])

        rain = []
        for r in range(self.rain.rowCount()):
            t = self.rain.item(r, 0)
            v = self.rain.item(r, 1)
            if t and v and t.text().strip() and v.text().strip():
                rain.extend([t.text().strip(), v.text().strip()])

        outputs = {0: [0], 1: [0, 1], 2: [0, 2, 3]}[self.outputs.currentIndex()]

        river = self.river_layer.currentLayer()
        river_params = {}
        if river is not None:
            river_params["RIVER"] = river
            for key, (combo, _default) in self.river_fields.items():
                if combo.currentField():
                    river_params[key] = combo.currentField()

        params = {
            "DEM": dem,
            "CELLSIZE": self.cellsize.value(),
            "MANNING_VALUE": self.manning_value.value(),
            "SIM_TIME": self.sim_time.value(),
            "SAVEINT": self.saveint.value(),
            "SOLVER": self.solver.currentIndex(),
            "OUTPUTS": outputs,
            "EDGE_BOUNDARIES": edges,
            "AUTO_OUTFLOW": self.auto_outflow.isChecked(),
            "AUTO_OUTFLOW_WIDTH": self.auto_outflow_width.value(),
            "RAIN": rain,
            "OUTPUT": deck,
        }
        params.update(river_params)
        if self.extent_box.isChecked():
            params["EXTENT"] = self.extent_box.outputExtent()
        for key, combo in (("MANNING", self.manning_combo),
                           ("START_DEPTH", self.start_combo),
                           ("BOUNDARY_POINTS", self.bc_points),
                           ("TIMESERIES", self.ts_table)):
            layer = combo.currentLayer()
            if layer is not None:
                params[key] = layer
        return params

    def _go(self, run):
        import processing
        try:
            params = self._collect()
        except ValueError as exc:
            self.iface.messageBar().pushMessage("LISFLOOD-FP", str(exc),
                                                level=Qgis.Warning, duration=6)
            return
        self.log.clear()
        self.tabs.setCurrentIndex(1)
        self._append(self.tr("Building deck..."), 0)
        try:
            built = processing.run("lisfloodfp:buildmodel", params)
        except Exception as exc:
            self._append(str(exc), 2)
            self.status.setText(self.tr("Deck could not be built."))
            return
        self._deck = built
        self._append(self.tr("Deck written to %s") % built["DECK_FOLDER"], 0)
        self.load_button.setEnabled(True)
        if run:
            self._start(built)

    def _start(self, built):
        path = settings.binary_path()
        if not path:
            self._append(self.tr(
                "No executable configured, so the deck was built but not run."), 1)
            return
        from ..core.par import ParFile
        par = ParFile.parse(built["PAR_FILE"])
        task = RunTask(path, built["PAR_FILE"],
                       float(par.get("sim_time") or 3600.0),
                       par.get("resroot") or "res",
                       built["RESULTS_FOLDER"],
                       self.threads.value() or settings.threads())
        queued = enum_value(Qt, "ConnectionType.QueuedConnection", "QueuedConnection")
        task.logged.connect(self._append, queued)
        task.stats.connect(self._live, queued)
        task.taskCompleted.connect(self._finished)
        task.taskTerminated.connect(self._finished)
        self.task = task
        self.progress.setValue(0)
        self.cancel_button.setEnabled(True)
        self.run_button.setEnabled(False)
        self.status.setText(self.tr("Running..."))
        QgsApplication.taskManager().addTask(task)

    def _cancel(self):
        if self.task is not None:
            self.task.cancel()
            self.status.setText(self.tr("Cancelling..."))

    def _finished(self):
        self.cancel_button.setEnabled(False)
        self.run_button.setEnabled(True)
        result = getattr(self.task, "result", None)
        if result is None:
            self.status.setText(self.tr("Run did not finish."))
        else:
            outcome = result.outcome
            self.status.setText(outcome.message)
            for warning in outcome.warnings:
                self._append(warning, 1)
            if outcome.ok:
                self.progress.setValue(100)
                self._load()
        self.task = None

    def _load(self):
        if not self._deck:
            return
        from ..core.par import ParFile
        par = ParFile.parse(self._deck["PAR_FILE"])
        dem = self.dem_combo.currentLayer()
        crs = dem.crs() if dem is not None else QgsCoordinateReferenceSystem()
        layers = load_results(
            self._deck["RESULTS_FOLDER"], par.get("resroot") or "res", crs,
            saveint=float(par.get("saveint") or 1.0),
            project=QgsProject.instance(),
            group_name="LISFLOOD-FP: %s" % (par.get("resroot") or "res"))
        self._append(self.tr("Loaded %d layer(s).") % len(layers), 0)

    # -- display ---------------------------------------------------------
    def _append(self, text, level):
        prefix = {0: "", 1: "WARNING: ", 2: "ERROR: "}.get(level, "")
        self.log.appendPlainText(prefix + text)

    def _live(self, fraction, tracker):
        self.progress.setValue(int(100 * fraction))
        def fmt(value, spec="%.1f"):
            return "-" if value is None else spec % value
        self.live["area"].setText(fmt(tracker.wetted_area, "%.0f"))
        self.live["volume"].setText(fmt(tracker.volume, "%.0f"))
        self.live["q"].setText("%s / %s" % (fmt(tracker.qin, "%.3f"),
                                            fmt(tracker.qout, "%.3f")))
        self.live["tstep"].setText(fmt(tracker.min_tstep, "%.4f"))
        if tracker.last_time is not None:
            self.status.setText(self.tr("Running: model time %.0f s (%.0f%%)")
                                % (tracker.last_time, 100 * fraction))

    def tr(self, text):
        return QCoreApplication.translate("LisfloodDock", text)
