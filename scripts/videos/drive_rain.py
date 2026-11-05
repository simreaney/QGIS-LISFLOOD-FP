"""The direct-rainfall film, in the real QGIS application, run by run_app.py.

Loads the River Axe DEM (rain_prep.py trims it at the outlet), opens the panel, sets up
a model with no inflow at all, just rain on every cell and a free outflow, types in a
storm, runs it for real and steps the Temporal Controller through the flood as it
gathers into the river network. capture.py does the grabbing and the pacing.
"""
import json
import os
import shutil
import sys

HERE = os.environ["FILM_SCRIPTS"]  # QGIS runs --code scripts without a __file__
sys.path.insert(0, HERE)
print("drive_rain.py started", flush=True)

import qgis.utils  # noqa: E402
from qgis.core import QgsProject, QgsRectangle  # noqa: E402
from qgis.PyQt.QtCore import Qt  # noqa: E402
from qgis.PyQt.QtWidgets import QPushButton, QTableWidgetItem  # noqa: E402
from qgis.utils import iface  # noqa: E402

import style  # noqa: E402
from capture import (OUT, W, H, build_and_run, canvas, dock, grab_frames, group_row, layer_row,  # noqa: E402
                     main, map_rect, note, open_temporal, plugin_button, popup, rect, rects, runs,
                     run, scroll_to, scroll_to_top, settle, snap)

DECK = "/Users/Shared/LISFLOOD-FP demo/axe-rain"   # on screen, so no home folder
STORM = [(0, 0), (5400, 33), (10800, 0)]          # s, mm/hr: 50 mm in three hours
SIM_TIME, SAVEINT, OUTFLOW = 28800, 900, 60       # eight hours, a grid every 15 minutes
with open(os.path.join(style.AXE, "outlet.json")) as handle:
    OUTLET = json.load(handle)


def around(x, y, width, height):
    return QgsRectangle(x - width / 2, y - height / 2, x + width / 2, y + height / 2)


def script():
    iface.messageBar().clearWidgets()
    shutil.rmtree(DECK, ignore_errors=True)
    main.resize(W, H)
    dock("Browser").hide()
    layers = style.load_axe()
    dem = layers["River Axe DEM (20 m)"]
    root = QgsProject.instance().layerTreeRoot()
    for node in root.findLayers():
        node.setExpanded(False)
    layers_dock = dock("Layers")
    main.resizeDocks([layers_dock], [300], Qt.Orientation.Horizontal)
    extent = dem.extent()
    # Room below the outlet, which is on the DEM's bottom edge, for the film's captions.
    home = QgsRectangle(extent.xMinimum() - 400, extent.yMinimum() - 2600,
                        extent.xMaximum() + 400, extent.yMaximum() + 400)
    canvas.setExtent(home)
    canvas.refresh()
    yield 2.5
    iface.messageBar().clearWidgets()
    rect("canvas", canvas)
    rect("layers", layers_dock)
    layer_row("row_dem", dem)
    layer_row("row_hillshade", layers["Hillshade"])
    x, y = OUTLET["outlet"]
    map_rect("catchment", extent)
    map_rect("outlet", around(x, y, 1600, 1600))
    snap("00_project")

    # The outlet, close up: the trimmed southern edge crosses the floodplain.
    canvas.setExtent(around(x + 300, y + 1500, 7000, 4200))
    canvas.refresh()
    yield 1.5
    map_rect("outlet_close", around(x, y, 700, 400))
    run_start, run_end = OUTLET["outlet_run"]
    map_rect("edge_close", QgsRectangle(run_start, y - 50, run_end, y + 30))  # the DEM ends at y - 10
    snap("01_outlet")
    canvas.setExtent(home)
    canvas.refresh()
    yield 1.0

    # The panel, from its toolbar button.
    plugin = qgis.utils.plugins["lisflood_fp"]
    plugin_button(plugin)
    snap("04_before_panel")
    plugin.action.trigger()
    yield 1.0
    panel = plugin.dock
    main.resizeDocks([panel], [520], Qt.Orientation.Horizontal)
    canvas.setExtent(home)
    canvas.refresh()
    yield 1.5
    note("messages", [m.text() for m in iface.messageBar().items()])
    iface.messageBar().clearWidgets()
    rect("panel", panel)
    rect("binary", panel.binary_label)
    rect("canvas_panel", canvas)
    map_rect("catchment_panel", extent)
    snap("05_panel")

    # The Model tab: the DEM, the outflow, the rain, the run.
    scroll_to(panel, panel.dem_combo)
    rect("dem", panel.dem_combo)
    snap("06_dem_open", overlays=[popup(panel.dem_combo)])
    panel.dem_combo.hidePopup()
    panel.dem_combo.setLayer(dem)
    rect("cellsize", panel.cellsize)
    rect("manning", panel.manning_value)
    snap("07_dem")

    scroll_to(panel, panel.auto_outflow, 140)
    rect("bc_points", panel.bc_points)
    rect("boundaries", panel.bc_points.parentWidget())
    panel.auto_outflow.setChecked(True)
    panel.auto_outflow_width.setValue(OUTFLOW)
    rect("auto_outflow", panel.auto_outflow)
    rect("auto_outflow_width", panel.auto_outflow_width)
    snap("08_outflow")

    box = panel.rain.parentWidget()
    scroll_to_top(panel, box)  # high enough for the 9:16 frame to keep it above the caption
    rect("rain_box", box)
    rect("rain", panel.rain)
    add = [b for b in box.findChildren(QPushButton) if b.text().replace("&", "") == "Add row"][0]
    rect("rain_add", add)
    snap("09_rain")
    scroll = panel.tabs.widget(0).verticalScrollBar()
    held = scroll.value()  # adding a row scrolls the panel; a person's would stay put
    for i, (t, value) in enumerate(STORM):
        panel.rain.insertRow(i)
        settle()
        scroll.setValue(held)
        settle()
        snap(f"10_rain_{i}_row")
        panel.rain.setItem(i, 0, QTableWidgetItem(str(t)))
        panel.rain.setItem(i, 1, QTableWidgetItem(str(value)))
        panel.rain.setCurrentCell(i, 1)
        settle()
        scroll.setValue(held)
        settle()
        r = panel.rain.visualItemRect(panel.rain.item(i, 0)).united(panel.rain.visualItemRect(panel.rain.item(i, 1)))
        viewport = panel.rain.viewport().mapTo(main, panel.rain.viewport().rect().topLeft())
        rects[f"rain_row_{i}"] = [viewport.x() + r.x(), viewport.y() + r.y(), r.width(), r.height()]
        snap(f"10_rain_{i}")
    rect("rain", panel.rain)

    scroll_to(panel, panel.run_button, 20)
    panel.sim_time.setValue(SIM_TIME)
    rect("sim_time", panel.sim_time)
    snap("11_sim_time")
    panel.saveint.setValue(SAVEINT)
    rect("saveint", panel.saveint)
    rect("solver", panel.solver)
    snap("12_saveint")
    panel.deck_widget.setFilePath(DECK)
    rect("deck", panel.deck_widget)
    rect("run_button", panel.run_button)
    snap("13_deck")

    # Build and run, for real: a few minutes, so a grab every few seconds.
    yield from build_and_run(panel, every=4.0, limit=1200)
    yield 1.5
    text = panel.log.toPlainText()
    note("log tail", text[-900:])
    # The panel's log leaves out the deck builder's notes, so read the opening from the deck.
    with open(os.path.join(DECK, "bc.bci")) as handle:
        edge = [line.split() for line in handle if line.split()[:1] == ["S"]][0]
    runs["outflow"] = OUTFLOW
    runs["outflow_cells"] = round((float(edge[2]) - float(edge[1])) / OUTLET["cell"])
    # All six grids load switched on, the time grids unstyled and drawn black over
    # everything, so untick all but the depth through time, as you would.
    group = root.findGroup("LISFLOOD-FP: res")
    loaded = {node.layer().name(): node.layer() for node in group.findLayers()}
    note("loaded", list(loaded))
    for node in group.findLayers():
        node.setItemVisibilityChecked(node.layer().name().startswith("Water depth"))
        node.setExpanded(False)  # the depth legends read 0 to 255: the ramp's range is never set
    group.setExpanded(True)
    canvas.refresh()
    yield 1.5
    group_row("row_group", group)
    for key, prefix in (("row_max", "Maximum depth"), ("row_wd", "Water depth")):
        match = [layer for name, layer in loaded.items() if name.startswith(prefix)]
        if match:
            layer_row(key, match[0])
    snap("20_done", status=panel.status.text())

    # Through time: the panel closed for room, the Temporal Controller open.
    panel.hide()
    yield from open_temporal(SAVEINT // 60)
    canvas.setExtent(extent.buffered(300))
    canvas.temporalController().setCurrentFrameNumber(0)
    yield 1.5
    rect("temporal", dock("Temporal Controller"))
    rect("canvas_wide", canvas)
    map_rect("catchment_wide", extent)
    map_rect("outlet_wide", around(x, y, 1600, 1600))
    yield from grab_frames(60)

    # The deepest water anywhere in the run, down the valley from Axminster to the outlet.
    dock("Temporal Controller").hide()
    for node in group.findLayers():
        node.setItemVisibilityChecked(node.layer().name().startswith("Maximum depth"))
    yield 0.5
    canvas.setExtent(around(x + 2600, y + 4200, 9000, 9000 * 0.55))
    canvas.refresh()
    yield 2.0
    rect("canvas_max", canvas)
    layer_row("row_max", [n.layer() for n in group.findLayers() if n.layer().name().startswith("Maximum depth")][0])
    snap("30_max")

    # The model's own grids, for the opening slide.
    results = os.path.join(DECK, "results")
    for name in ("res.max", "res.mass"):
        shutil.copy(os.path.join(results, name), os.path.join(OUT, name))
    runs["storm"] = STORM
    runs["sim_time"] = SIM_TIME
    runs["saveint"] = SAVEINT
    runs["outlet"] = OUTLET


run(script(), timeout=1800)
