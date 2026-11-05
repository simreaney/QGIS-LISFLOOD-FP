"""What every capture script shares: grab the real QGIS window, note where things are, pace the script.

Imported by the capture scripts (drive.py, drive_rain.py), which run inside the real QGIS
application under run_app.py. A script is a generator handed to `run`: each `yield` is a
pause in seconds with QGIS's event loop running meanwhile, so the model's task, the canvas
and the dialogs keep going. Each state is grabbed at QT_SCALE_FACTOR (4x: enough to zoom 2x
in 4K), with any separate window (a dialog, a list) painted where it opens, and every
control a film points at has its rectangle, in window pixels, noted in capture.json.
"""
import json
import os
import time
import traceback

from qgis.core import QgsInterval, QgsProject, QgsUnitTypes
from qgis.PyQt.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QImage, QPainter
from qgis.PyQt.QtWidgets import (QAbstractButton, QApplication, QDockWidget, QLineEdit, QToolBar,
                                 QTreeView)
from qgis.utils import iface

OUT = os.environ["FILM_OUT"]
W, H = 1920, 1080
SCALE = float(os.environ.get("QT_SCALE_FACTOR", "2"))  # capture pixels per window pixel
main = iface.mainWindow()
canvas = iface.mapCanvas()
rects, states, runs, log = {}, [], {}, []


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


def map_rect(key, box):
    """Where a map rectangle (a QgsRectangle) is on screen now, in window pixels."""
    transform = canvas.mapSettings().mapToPixel()
    origin = canvas.mapTo(main, QPoint(0, 0))
    a = transform.transform(box.xMinimum(), box.yMaximum())
    b = transform.transform(box.xMaximum(), box.yMinimum())
    rects[key] = [origin.x() + a.x(), origin.y() + a.y(), b.x() - a.x(), b.y() - a.y()]
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


def group_row(key, group):
    """A group's row in the Layers panel."""
    view = iface.layerTreeView()
    view.doItemsLayout()
    r = view.visualRect(view.node2index(group))
    corner = view.viewport().mapTo(main, r.topLeft())
    rects[key] = [corner.x(), corner.y(), view.viewport().width() - r.x(), r.height()]
    return rects[key]


def popup(combo):
    """Open a combo's list; return it as an overlay where it drops down."""
    combo.showPopup()
    settle()
    container = combo.view().window()
    x, y, w, h = rect_in_main(combo)
    container.resize(max(container.width(), w), container.height())
    return container, (x, y + h)


def scroll_to(panel, widget, margin=60):
    """Scroll the plugin panel's Model tab until *widget* shows."""
    area = panel.tabs.widget(0)
    area.ensureWidgetVisible(widget, 0, margin)
    settle()


def scroll_to_top(panel, widget, offset=220):
    """Scroll the plugin panel's Model tab so *widget* sits *offset* pixels below its top."""
    area = panel.tabs.widget(0)
    y = widget.mapTo(area.widget(), QPoint(0, 0)).y()
    area.verticalScrollBar().setValue(max(0, y - offset))
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


def plugin_button(plugin):
    """Note where the plugin's toolbar button is."""
    for bar in main.findChildren(QToolBar):
        button = bar.widgetForAction(plugin.action)
        if button is not None and button.isVisible():
            rect("plugin_button", button)


def build_and_run(panel, every=0.3, limit=300, panel_only=False):
    """Press Build and run, and grab the Run tab every *every* seconds until the run ends.

    With *panel_only*, only the first grab is of the whole window; after it, just the
    panel, which is all that changes, is grabbed, and pasted onto the first once the run
    is over. A whole-window grab over a detailed map can take seconds to save, which
    would leave a short run with only a few frames.
    """
    started = time.time()
    QTimer.singleShot(0, panel.run_button.click)
    frames, pieces = [], []
    yield 0.3
    while panel.task is not None or not frames:
        name = f"run_{len(frames):03d}"
        if len(frames) == 0:
            rect("progress", panel.progress)
            rect("status", panel.status)
            rect("live", panel.live["area"].parentWidget())
            rect("log", panel.log)
            rect("cancel", panel.cancel_button)
            rect("load_button", panel.load_button)
            snap(name, progress=panel.progress.value(), status=panel.status.text())
        elif panel_only:
            settle()
            piece = panel.grab().toImage()
            piece.setDevicePixelRatio(1)
            pieces.append((name, piece, rect_in_main(panel)))
            states.append({"name": name, "progress": panel.progress.value(), "status": panel.status.text()})
        else:
            snap(name, progress=panel.progress.value(), status=panel.status.text())
        frames.append((panel.progress.value(), time.time() - started, name))
        if time.time() - started > limit:
            note("run timed out")
            break
        yield every
    runs["model"] = {"elapsed": time.time() - started, "frames": frames}
    note("run", runs["model"]["elapsed"], panel.status.text())
    base = QImage(os.path.join(OUT, f"{frames[0][2]}.png"))
    for name, piece, (x, y, _, _) in pieces:
        image = base.copy()
        painter = QPainter(image)
        painter.drawImage(QPointF(x * SCALE, y * SCALE), piece)
        painter.end()
        image.save(os.path.join(OUT, f"{name}.png"))


def open_temporal(minutes, height=118):
    """The Temporal Controller docked along the bottom, animated, one saved grid per frame."""
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
        controller.setFrameDuration(QgsInterval(minutes, QgsUnitTypes.TemporalUnit.TemporalMinutes))
    except AttributeError:
        from qgis.core import Qgis
        controller.setFrameDuration(QgsInterval(minutes, Qgis.TemporalUnit.Minutes))
    main.resizeDocks([temporal], [height], Qt.Orientation.Vertical)
    settle()


def grab_frames(limit=40, prefix="t_"):
    """Step the Temporal Controller through its frames, grabbing each."""
    temporal = dock("Temporal Controller")
    controller = canvas.temporalController()
    note("temporal", controller.totalFrameCount(), controller.temporalExtents().begin().toString(),
         controller.temporalExtents().end().toString())
    timeline = []
    for frame in range(min(controller.totalFrameCount(), limit)):
        controller.setCurrentFrameNumber(frame)
        canvas.refresh()
        yield 0.15
        settle()
        # The dock lays out its controls again some time after it is resized: keep the last.
        rect("play", temporal.findChild(QAbstractButton, "mForwardButton"))
        name = f"{prefix}{frame:02d}"
        begin = controller.dateTimeRangeForFrameNumber(frame).begin()
        snap(name, frame=frame, time=begin.toString("HH:mm"),
             minutes=controller.temporalExtents().begin().secsTo(begin) / 60)
        timeline.append(name)
    runs["timeline"] = timeline


def run(generator, timeout=900):
    """Drive a capture script; save capture.json at the end, or on an error, and quit."""
    QTimer.singleShot(int(timeout * 1000), lambda: os._exit(3))  # never hang

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
