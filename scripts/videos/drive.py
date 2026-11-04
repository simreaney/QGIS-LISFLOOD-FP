"""The walkthrough, in the real QGIS application, run by run_app.py with a throwaway profile.

Loads the demo valley, opens the setup tool and the hydrograph, opens the panel from
its toolbar button, fills in the Model tab, builds and runs the model for real
(grabbing the Run tab as it goes), then shows the results and steps the Temporal
Controller through the flood. Each state is grabbed at 4x (enough to zoom 2x in 4K), with any separate window
(a dialog, a list) painted where it opens, and every control the film points at has
its rectangle noted in capture.json.

The script is a generator: each `yield` is a pause in seconds, with QGIS's event
loop running meanwhile, so the model's task, the canvas and the dialogs keep going.
"""
import json
import os
import shutil
import sys
import time
import traceback

HERE = os.environ["FILM_SCRIPTS"]  # QGIS runs --code scripts without a __file__
sys.path.insert(0, HERE)
print("drive.py started", flush=True)

import qgis.utils  # noqa: E402
from qgis.core import QgsApplication, QgsInterval, QgsProject, QgsUnitTypes  # noqa: E402
from qgis.PyQt.QtCore import QPoint, QPointF, QRectF, Qt, QTimer  # noqa: E402
from qgis.PyQt.QtGui import QColor, QPainter  # noqa: E402
from qgis.PyQt.QtWidgets import (QAbstractButton, QApplication, QDockWidget, QLineEdit,  # noqa: E402
                                 QToolBar, QTreeView)
from qgis.utils import iface  # noqa: E402

import style  # noqa: E402

OUT = os.environ["FILM_OUT"]
DECK = "/Users/Shared/LISFLOOD-FP demo/valley-flood"   # on screen, so no home folder
W, H = 1920, 1080
SCALE = float(os.environ.get("QT_SCALE_FACTOR", "2"))  # capture pixels per window pixel
main = iface.mainWindow()
canvas = iface.mapCanvas()
rects, states, runs, log = {}, [], {}, []
QTimer.singleShot(900000, lambda: os._exit(3))  # never hang


def note(*parts):
    log.append(" ".join(str(p) for p in parts))
    print(*parts, flush=True)


def save():
    with open(os.path.join(OUT, "capture.json"), "w") as handle:
        json.dump({"scale": SCALE, "rects": rects, "states": states, "runs": runs, "log": log}, handle, indent=1)


def settle(rounds=6):
    for _ in range(rounds):
        QApplication.processEvents()
    canvas.waitWhileRendering()
    QApplication.processEvents()


def rect_in_main(widget):
    corner = widget.mapTo(main, QPoint(0, 0))
    return [corner.x(), corner.y(), widget.width(), widget.height()]


def rect(key, widget):
    rects[key] = rect_in_main(widget)
    return rects[key]


def snap(name, overlays=(), **extra):
    """The main window at SCALE, with any (widget, (x, y)) overlays where they open."""
    settle()
    image = main.grab().toImage()
    image.setDevicePixelRatio(1)
    if overlays:
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for widget, (x, y) in overlays:
            shot = widget.grab().toImage()
            shot.setDevicePixelRatio(1)
            left, top, k = x * SCALE, y * SCALE, SCALE / 2
            for spread, alpha in ((36 * k, 16), (20 * k, 26), (8 * k, 40)):  # a soft drop shadow
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, alpha))
                painter.drawRoundedRect(QRectF(left - spread + 8 * k, top - spread + 24 * k,
                                               shot.width() + 2 * spread, shot.height() + 2 * spread),
                                        spread, spread)
            painter.drawImage(QPointF(left, top), shot)
        painter.end()
    image.save(os.path.join(OUT, f"{name}.png"))
    states.append({"name": name, **extra})


def dock(name):
    """A dock by object name or title: QGIS 4.3 renamed the Processing Toolbox's."""
    for widget in main.findChildren(QDockWidget):
        if name in (widget.objectName(), widget.windowTitle()):
            return widget
    return None


def layer_row(key, layer):
    """A layer's row in the Layers panel."""
    view = iface.layerTreeView()
    view.doItemsLayout()
    index = view.node2index(QgsProject.instance().layerTreeRoot().findLayer(layer.id()))
    r = view.visualRect(index)
    corner = view.viewport().mapTo(main, r.topLeft())
    rects[key] = [corner.x(), corner.y(), min(r.width(), view.viewport().width() - r.x()), r.height()]
    return rects[key]


def popup(combo):
    """Open a combo's list; return it as an overlay where it drops down."""
    combo.showPopup()
    settle()
    container = combo.view().window()
    x, y, w, h = rect_in_main(combo)
    container.resize(max(container.width(), w), container.height())
    return container, (x, y + h)


def scroll_to(widget, margin=60):
    area = PANEL.tabs.widget(0)
    area.ensureWidgetVisible(widget, 0, margin)
    settle()


def tree_item(view, text):
    """The rectangle of the first row in a tree view whose text contains *text*."""
    model = view.model()

    def walk(parent):
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            if text in str(model.data(index)):
                return index
            found = walk(index)
            if found is not None:
                return found
        return None

    index = walk(view.rootIndex())
    if index is None:
        return None
    view.scrollTo(index)
    r = view.visualRect(index)
    corner = view.viewport().mapTo(main, r.topLeft())
    return [corner.x(), corner.y(), min(r.width(), view.viewport().width() - r.x()), r.height()]


def toolbox(filter_text):
    box = dock("Processing Toolbox")
    box.show()
    main.resizeDocks([box], [430], Qt.Orientation.Horizontal)
    search = [e for e in box.findChildren(QLineEdit) if e.isVisible()][0]
    search.setText(filter_text)
    settle()
    view = [v for v in box.findChildren(QTreeView) if v.isVisible()][0]
    view.expandAll()
    settle()
    return box, view


def script():
    global PANEL
    iface.messageBar().clearWidgets()
    shutil.rmtree(DECK, ignore_errors=True)
    main.resize(W, H)
    dock("Browser").hide()
    layers = style.load_project()
    root = QgsProject.instance().layerTreeRoot()
    for node in root.findLayers():
        node.setExpanded(False)
    layers_dock = dock("Layers")
    main.resizeDocks([layers_dock], [300], Qt.Orientation.Horizontal)
    extent = layers["DEM (10 m)"].extent()
    canvas.setExtent(extent.buffered(80))
    canvas.refresh()
    yield 2.0
    iface.messageBar().clearWidgets()
    rect("canvas", canvas)
    rect("layers", layers_dock)
    for key, name in (("row_inflow", "Inflow point"), ("row_buildings", "Buildings"),
                      ("row_hydro", "Inflow hydrograph"), ("row_dem", "DEM (10 m)"),
                      ("row_hillshade", "Hillshade")):
        layer_row(key, layers[name])
    transform = canvas.mapSettings().mapToPixel()
    origin = canvas.mapTo(main, QPoint(0, 0))
    inflow = next(layers["Inflow point"].getFeatures()).geometry().asPoint()
    p = transform.transform(inflow.x(), inflow.y())
    rects["inflow_point"] = [origin.x() + p.x() - 10, origin.y() + p.y() - 10, 20, 20]
    snap("00_project")

    # The hydrograph's attribute table.
    table = iface.showAttributeTable(layers["Inflow hydrograph"])
    table.resize(470, 520)
    settle()
    position = (rects["canvas"][0] + 60, rects["canvas"][1] + 70)
    rects["table"] = [position[0], position[1], table.width(), table.height()]
    snap("01_table", overlays=[(table, position)])
    table.close()
    yield 0.5

    # Setup, once: the Processing tool that builds the executable.
    box, view = toolbox("LISFLOOD")
    rect("toolbox", box)
    rects["tool_build"] = tree_item(view, "executable")
    rects["tool_group"] = tree_item(view, "LISFLOOD-FP")
    snap("02_toolbox")
    import processing
    dialog = processing.createAlgorithmDialog("lisfloodfp:buildbinary", {})
    dialog.resize(760, 560)
    dialog.show()
    settle()
    position = ((W - dialog.width()) / 2 - 120, (H - dialog.height()) / 2 - 20)
    rects["build_dialog"] = [position[0], position[1], dialog.width(), dialog.height()]
    from qgis.gui import QgsFileWidget
    files = [f for f in dialog.findChildren(QgsFileWidget) if f.isVisible()]
    if files:
        corner = files[0].mapTo(dialog, QPoint(0, 0))
        rects["build_source"] = [position[0] + corner.x(), position[1] + corner.y(),
                                 files[0].width(), files[0].height()]
    run_buttons = [b for b in dialog.findChildren(QAbstractButton) if b.isVisible() and b.text().replace("&", "") == "Run"]
    if run_buttons:
        corner = run_buttons[0].mapTo(dialog, QPoint(0, 0))
        rects["build_run"] = [position[0] + corner.x(), position[1] + corner.y(),
                              run_buttons[0].width(), run_buttons[0].height()]
    snap("03_build_dialog", overlays=[(dialog, position)])
    dialog.close()
    box.hide()
    yield 0.5

    # The panel, from its toolbar button.
    plugin = qgis.utils.plugins["lisflood_fp"]
    for bar in main.findChildren(QToolBar):
        button = bar.widgetForAction(plugin.action)
        if button is not None and button.isVisible():
            rect("plugin_button", button)
    snap("04_before_panel")
    plugin.action.trigger()
    yield 1.0
    box.hide()
    PANEL = plugin.dock
    main.resizeDocks([PANEL], [520], Qt.Orientation.Horizontal)
    canvas.setExtent(extent.buffered(80))
    canvas.refresh()
    yield 1.0
    note("messages", [m.text() for m in iface.messageBar().items()])
    rect("panel", PANEL)
    rect("binary", PANEL.binary_label)
    rect("tabs", PANEL.tabs)
    rect("canvas_panel", canvas)
    snap("05_panel")
    iface.messageBar().clearWidgets()

    # The Model tab, top to bottom.
    scroll_to(PANEL.dem_combo)
    rect("dem", PANEL.dem_combo)
    snap("06_dem_open", overlays=[popup(PANEL.dem_combo)])
    PANEL.dem_combo.hidePopup()
    PANEL.dem_combo.setLayer(layers["DEM (10 m)"])
    rect("cellsize", PANEL.cellsize)
    rect("extent", PANEL.extent_box)
    snap("07_dem")

    rect("manning", PANEL.manning_value)
    rect("manning_grid", PANEL.manning_combo)
    PANEL.manning_value.setValue(0.04)
    snap("08_manning")

    scroll_to(PANEL.auto_outflow, 140)
    rect("bc_points", PANEL.bc_points)
    snap("09_points_open", overlays=[popup(PANEL.bc_points)])
    PANEL.bc_points.hidePopup()
    PANEL.bc_points.setLayer(layers["Inflow point"])
    snap("10_points")
    rect("ts_table", PANEL.ts_table)
    PANEL.ts_table.setLayer(layers["Inflow hydrograph"])
    snap("11_series")
    rect("edges", PANEL.edges)
    PANEL.auto_outflow.setChecked(True)
    PANEL.auto_outflow_width.setValue(80)
    rect("auto_outflow", PANEL.auto_outflow)
    rect("auto_outflow_width", PANEL.auto_outflow_width)
    snap("12_outflow")

    scroll_to(PANEL.rain, 20)
    rect("river_layer", PANEL.river_layer)
    rect("rain", PANEL.rain)
    rect("channel_box", PANEL.river_layer.parentWidget())
    snap("13_optional")

    scroll_to(PANEL.run_button, 20)
    PANEL.sim_time.setValue(21600)
    rect("sim_time", PANEL.sim_time)
    snap("14_sim_time")
    PANEL.saveint.setValue(600)
    rect("saveint", PANEL.saveint)
    snap("15_saveint")
    rect("solver", PANEL.solver)
    rect("outputs", PANEL.outputs)
    rect("threads", PANEL.threads)
    PANEL.deck_widget.setFilePath(DECK)
    rect("deck", PANEL.deck_widget)
    rect("build_button", PANEL.build_button)
    rect("run_button", PANEL.run_button)
    snap("16_deck")

    # Build and run, for real.
    started = time.time()
    QTimer.singleShot(0, PANEL.run_button.click)
    frames = []
    yield 0.3
    while PANEL.task is not None or not frames:
        name = f"run_{len(frames):03d}"
        if len(frames) == 0:
            rect("progress", PANEL.progress)
            rect("status", PANEL.status)
            rect("live", PANEL.live["area"].parentWidget())
            rect("log", PANEL.log)
            rect("cancel", PANEL.cancel_button)
            rect("load_button", PANEL.load_button)
        snap(name, progress=PANEL.progress.value(), status=PANEL.status.text())
        frames.append((PANEL.progress.value(), time.time() - started, name))
        if time.time() - started > 300:
            note("run timed out")
            break
        yield 0.3
    runs["model"] = {"elapsed": time.time() - started, "frames": frames}
    note("run", runs["model"]["elapsed"], PANEL.status.text())
    yield 1.5
    note("log tail", PANEL.log.toPlainText()[-600:])
    snap("20_done", status=PANEL.status.text())

    # The results: tidy the Layers panel the way you would.
    group = root.findGroup("LISFLOOD-FP: res")
    loaded = {node.layer().name(): node.layer() for node in group.findLayers()}
    note("loaded", list(loaded))
    for name in ("Buildings", "Inflow point"):  # keep them above the water
        node = root.findLayer(layers[name].id())
        root.insertChildNode(0, node.clone())
        root.removeChildNode(node)
    for node in group.findLayers():
        node.setItemVisibilityChecked(node.layer().name().startswith("Maximum depth"))
        node.setExpanded(False)  # the depth legends read 0 to 255: the ramp's range is never set
    group.setExpanded(True)
    canvas.refresh()
    yield 1.5
    rect("layers_after", iface.layerTreeView())
    for key, prefix in (("row_max", "Maximum depth"), ("row_wd", "Water depth"),
                        ("row_arrival", "Time of first inundation"), ("row_total", "Total time inundated"),
                        ("row_maxtm", "Time of maximum depth"), ("row_mxe", "Maximum water elevation")):
        match = [layer for name, layer in loaded.items() if name.startswith(prefix)]
        if match:
            layer_row(key, match[0])
    view = iface.layerTreeView()
    view.doItemsLayout()
    gi = view.node2index(group)
    r = view.visualRect(gi)
    corner = view.viewport().mapTo(main, r.topLeft())
    rects["row_group"] = [corner.x(), corner.y(), view.viewport().width() - r.x(), r.height()]
    snap("21_max")

    # Through time: the panel closed for room, the Temporal Controller open.
    PANEL.hide()
    for node in group.findLayers():
        node.setItemVisibilityChecked(node.layer().name().startswith("Water depth"))
    temporal = dock("Temporal Controller")
    temporal.show()
    main.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, temporal)
    yield 0.8
    controller = canvas.temporalController()
    names = sorted({w.objectName() for w in temporal.findChildren(QAbstractButton) if w.objectName()})
    note("temporal buttons", names)
    animated = temporal.findChild(QAbstractButton, "mNavigationAnimated")
    if animated is not None:
        animated.click()
    full = temporal.findChild(QAbstractButton, "mSetToProjectTimeButton")
    if full is not None:
        full.click()
    yield 0.5
    try:
        controller.setFrameDuration(QgsInterval(10, QgsUnitTypes.TemporalUnit.TemporalMinutes))
    except AttributeError:
        from qgis.core import Qgis
        controller.setFrameDuration(QgsInterval(10, Qgis.TemporalUnit.Minutes))
    main.resizeDocks([temporal], [118], Qt.Orientation.Vertical)
    settle()
    # The valley floor across the canvas's full width: the hilltops can go.
    from qgis.core import QgsRectangle
    canvas.setExtent(QgsRectangle(extent.xMinimum() - 40, extent.yMinimum() + 400,
                                  extent.xMaximum() + 40, extent.yMaximum() - 400))
    controller.setCurrentFrameNumber(0)
    yield 1.0
    note("temporal", controller.totalFrameCount(), controller.temporalExtents().begin().toString(),
         controller.temporalExtents().end().toString())
    rect("temporal", temporal)
    rect("canvas_wide", canvas)
    transform = canvas.mapSettings().mapToPixel()
    origin = canvas.mapTo(main, QPoint(0, 0))
    a = transform.transform(extent.xMinimum(), extent.yMaximum())
    b = transform.transform(extent.xMaximum(), extent.yMinimum())
    rects["dem_wide"] = [origin.x() + a.x(), origin.y() + a.y(), b.x() - a.x(), b.y() - a.y()]
    village = style.village_extent()
    a = transform.transform(village.xMinimum(), village.yMaximum())
    b = transform.transform(village.xMaximum(), village.yMinimum())
    rects["village"] = [origin.x() + a.x(), origin.y() + a.y(), b.x() - a.x(), b.y() - a.y()]
    layer_row("row_wd_time", [n.layer() for n in group.findLayers() if n.layer().name().startswith("Water depth")][0])
    timeline = []
    for frame in range(min(controller.totalFrameCount(), 40)):
        controller.setCurrentFrameNumber(frame)
        canvas.refresh()
        yield 0.15
        settle()
        # The dock lays out its controls again some time after it is resized: keep the last.
        rect("play", temporal.findChild(QAbstractButton, "mForwardButton"))
        name = f"t_{frame:02d}"
        snap(name, frame=frame, time=controller.dateTimeRangeForFrameNumber(frame).begin().toString("HH:mm"))
        timeline.append(name)
    runs["timeline"] = timeline

    # Every step is a Processing tool too.
    temporal.hide()
    box, view = toolbox("LISFLOOD")
    rect("toolbox_end", box)
    for key, text in (("alg_build", "Build model deck"), ("alg_run", "Run a model deck"),
                      ("alg_simulate", "Build and run"), ("alg_load", "Load results"),
                      ("alg_binary", "executable")):
        rects[key] = tree_item(view, text)
    for node in group.findLayers():
        node.setItemVisibilityChecked(node.layer().name().startswith("Maximum depth"))
    canvas.setExtent(extent.buffered(80))
    canvas.refresh()
    yield 1.0
    snap("30_toolbox")


def run(generator):
    def resume():
        try:
            delay = next(generator)
        except StopIteration:
            save()
            note("saved")
            os._exit(0)
        except Exception as exc:  # report and stop rather than hang
            note("error", exc, traceback.format_exc())
            save()
            os._exit(10)
        QTimer.singleShot(int(delay * 1000), resume)
    QTimer.singleShot(4000, resume)  # let QGIS finish starting


PANEL = None
run(script())
