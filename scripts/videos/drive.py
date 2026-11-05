"""The walkthrough, in the real QGIS application, run by run_app.py with a throwaway profile.

Loads the Appleby DTM and the inflow point (prep_data.py), opens the setup tool and the
point's attributes, opens the panel from its toolbar button, fills in the Model tab,
builds and runs the model for real (grabbing the Run tab as it goes), then shows the
results and steps the Temporal Controller through the flood. capture.py does the
grabbing and the pacing.
"""
import os
import shutil
import sys

HERE = os.environ["FILM_SCRIPTS"]  # QGIS runs --code scripts without a __file__
sys.path.insert(0, HERE)
print("drive.py started", flush=True)

import qgis.utils  # noqa: E402
from qgis.core import QgsProject  # noqa: E402
from qgis.PyQt.QtCore import QPoint, Qt  # noqa: E402
from qgis.PyQt.QtWidgets import QAbstractButton, QTableView  # noqa: E402
from qgis.utils import iface  # noqa: E402

import style  # noqa: E402
from capture import (OUT, H, W, build_and_run, canvas, dock, grab_frames, group_row, layer_row,  # noqa: E402
                     main, map_rect, note, open_temporal, plugin_button, popup, rect, rects, run,
                     scroll_to, settle, snap, toolbox, tree_item)

DECK = "/Users/Shared/LISFLOOD-FP demo/appleby"   # on screen, so no home folder
CELL, SIM_TIME, SAVEINT, OUTFLOW = 5.0, 10800, 300, 40  # 5 m grid, three hours, every five minutes


def script():
    iface.messageBar().clearWidgets()
    shutil.rmtree(DECK, ignore_errors=True)
    main.resize(W, H)
    dock("Browser").hide()
    layers = style.load_project()
    dem, point = layers[style.DEM_NAME], layers["Inflow point"]
    root = QgsProject.instance().layerTreeRoot()
    for node in root.findLayers():
        node.setExpanded(False)
    layers_dock = dock("Layers")
    main.resizeDocks([layers_dock], [300], Qt.Orientation.Horizontal)
    extent = dem.extent()
    canvas.setExtent(extent.buffered(20))
    canvas.refresh()
    yield 2.0
    iface.messageBar().clearWidgets()
    rect("canvas", canvas)
    rect("layers", layers_dock)
    for key, layer in (("row_inflow", point), ("row_dem", dem), ("row_hillshade", layers["Hillshade"])):
        layer_row(key, layer)
    inflow = next(point.getFeatures()).geometry().asPoint()
    transform = canvas.mapSettings().mapToPixel()
    origin = canvas.mapTo(main, QPoint(0, 0))
    p = transform.transform(inflow.x(), inflow.y())
    rects["inflow_point"] = [origin.x() + p.x() - 10, origin.y() + p.y() - 10, 20, 20]
    map_rect("dem_full", extent)
    map_rect("town", style.TOWN)
    snap("00_project")

    # The inflow point's attributes: what kind of boundary it is, and how much.
    table = iface.showAttributeTable(point)
    settle()
    table.setMinimumWidth(560)  # it sits in a container that ignores resize()
    for view in table.findChildren(QTableView):
        view.resizeColumnsToContents()
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
    plugin_button(plugin)
    snap("04_before_panel")
    plugin.action.trigger()
    yield 1.0
    box.hide()
    panel = plugin.dock
    main.resizeDocks([panel], [520], Qt.Orientation.Horizontal)
    canvas.setExtent(extent.buffered(20))
    canvas.refresh()
    yield 1.0
    note("messages", [m.text() for m in iface.messageBar().items()])
    rect("panel", panel)
    rect("binary", panel.binary_label)
    rect("tabs", panel.tabs)
    rect("canvas_panel", canvas)
    snap("05_panel")
    iface.messageBar().clearWidgets()

    # The Model tab, top to bottom.
    scroll_to(panel, panel.dem_combo)
    rect("dem", panel.dem_combo)
    snap("06_dem_open", overlays=[popup(panel.dem_combo)])
    panel.dem_combo.hidePopup()
    panel.dem_combo.setLayer(dem)
    rect("extent", panel.extent_box)
    snap("07_dem")
    panel.cellsize.setValue(CELL)
    rect("cellsize", panel.cellsize)
    snap("07_cellsize")

    rect("manning", panel.manning_value)
    rect("manning_grid", panel.manning_combo)
    snap("08_manning")

    scroll_to(panel, panel.auto_outflow, 140)
    rect("bc_points", panel.bc_points)
    snap("09_points_open", overlays=[popup(panel.bc_points)])
    panel.bc_points.hidePopup()
    panel.bc_points.setLayer(point)
    snap("10_points")
    rect("ts_table", panel.ts_table)
    rect("edges", panel.edges)
    panel.auto_outflow.setChecked(True)
    panel.auto_outflow_width.setValue(OUTFLOW)
    rect("auto_outflow", panel.auto_outflow)
    rect("auto_outflow_width", panel.auto_outflow_width)
    snap("12_outflow")

    scroll_to(panel, panel.rain, 20)
    rect("river_layer", panel.river_layer)
    rect("rain", panel.rain)
    rect("channel_box", panel.river_layer.parentWidget())
    snap("13_optional")

    scroll_to(panel, panel.run_button, 20)
    panel.sim_time.setValue(SIM_TIME)
    rect("sim_time", panel.sim_time)
    snap("14_sim_time")
    panel.saveint.setValue(SAVEINT)
    rect("saveint", panel.saveint)
    snap("15_saveint")
    rect("solver", panel.solver)
    rect("outputs", panel.outputs)
    rect("threads", panel.threads)
    panel.deck_widget.setFilePath(DECK)
    rect("deck", panel.deck_widget)
    rect("build_button", panel.build_button)
    rect("run_button", panel.run_button)
    snap("16_deck")

    # Build and run, for real.
    yield from build_and_run(panel, every=0.25, panel_only=True)
    yield 1.5
    note("log tail", panel.log.toPlainText()[-600:])

    # The results: tidy the Layers panel the way you would. All six grids load switched
    # on, the time grids unstyled and drawn black over everything, so this comes first.
    group = root.findGroup("LISFLOOD-FP: res")
    loaded = {node.layer().name(): node.layer() for node in group.findLayers()}
    note("loaded", list(loaded))
    node = root.findLayer(point.id())  # keep the inflow above the water
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
    group_row("row_group", group)
    map_rect("town_panel", style.TOWN)
    snap("20_done", status=panel.status.text())
    snap("21_max")

    # Through time: the panel closed for room, the Temporal Controller open.
    panel.hide()
    for node in group.findLayers():
        node.setItemVisibilityChecked(node.layer().name().startswith("Water depth"))
    yield from open_temporal(SAVEINT // 60)
    canvas.setExtent(extent.buffered(20))
    canvas.temporalController().setCurrentFrameNumber(0)
    yield 1.0
    rect("temporal", dock("Temporal Controller"))
    rect("canvas_wide", canvas)
    map_rect("dem_wide", extent)
    map_rect("village", style.TOWN)
    layer_row("row_wd_time", [n.layer() for n in group.findLayers() if n.layer().name().startswith("Water depth")][0])
    yield from grab_frames(40)

    # Every step is a Processing tool too.
    dock("Temporal Controller").hide()
    box, view = toolbox("LISFLOOD")
    rect("toolbox_end", box)
    for key, text in (("alg_build", "Build model deck"), ("alg_run", "Run a model deck"),
                      ("alg_simulate", "Build and run"), ("alg_load", "Load results"),
                      ("alg_binary", "executable")):
        rects[key] = tree_item(view, text)
    for node in group.findLayers():
        node.setItemVisibilityChecked(node.layer().name().startswith("Maximum depth"))
    canvas.setExtent(extent.buffered(20))
    canvas.refresh()
    yield 1.0
    snap("30_toolbox")

    # The model's own maximum depth, for the opening slide.
    shutil.copy(os.path.join(DECK, "results", "res.max"), os.path.join(OUT, "res.max"))


run(script())
