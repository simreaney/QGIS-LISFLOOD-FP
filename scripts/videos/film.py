"""Compose a film from captured UI states: camera, cursor, captions, cards.

One timeline (states, cursor, clicks, highlights, captions) renders in two
formats: 16:9 in 4K for YouTube, and 9:16 for Instagram Reels. Each format has
its own camera track, given as (centre x, centre y, width) in stage coordinates:
the captured window's logical pixels, 1920 x 1080. Everything is laid out on a
1920 x 1080 (or 1080 x 1920) page and drawn at the format's `ratio`, so 4K is the
1080p layout at twice the pixels. The captures are at 4x, so the camera can zoom
to about 2x and stay sharp even in 4K.

Adapted from the SCIMAP for QGIS films (scimap-app/scripts/videos/film.py).
"""
import math
import subprocess
from dataclasses import dataclass

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import (QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter,
                             QPen, QPolygonF)

FPS = 30
STAGE_W, STAGE_H = 1920, 1080
SCALE = 4  # capture pixels per stage pixel; set from the capture

ACCENT = QColor("#d23c78")
INK = QColor("#121a19")
CARD = QColor("#15201e")
PAPER = QColor("#f2f5f4")
MUTED = QColor("#9fb0ac")
FONT = "Helvetica Neue"
WRAP = int(Qt.TextFlag.TextWordWrap)


@dataclass(frozen=True)
class Format:
    name: str
    width: int
    height: int
    caption_size: int
    caption_width: int
    caption_centre_x: float
    caption_bottom: float     # distance from the frame's bottom edge
    title_size: int
    title_origin: tuple       # top-left of the title card
    title_width: int
    badge_origin: tuple       # top-left of the run-time badge, or None for top right
    end_top: float
    end_title_size: int
    header: int = 0           # a title band across the top, above the capture
    note_title: int = 30      # the callouts that say what a control is
    note_body: int = 25
    note_width: int = 560
    ratio: int = 1            # output pixels per layout pixel

    @property
    def aspect(self):
        """The shape of the part of the frame the capture fills."""
        return self.width / (self.height - self.header)


LANDSCAPE = Format("landscape", 1920, 1080, 44, 1500, 960, 58, 76, (72, 750), 1500, (72, 56),
                   330, 104, ratio=2)
# Instagram Reels covers the top ~250 px, the bottom ~400 px and a column of
# buttons on the right, so text stays inside what is left.
# Its title band keeps the film's name on screen for viewers who arrive part way.
VERTICAL = Format("vertical", 1080, 1920, 50, 820, 510, 420, 70, (60, 250), 900, (60, 370),
                  620, 92, header=330, note_title=40, note_body=34, note_width=860)
FORMATS = {f.name: f for f in (LANDSCAPE, VERTICAL)}


@dataclass(frozen=True)
class Cover:
    """An opening slide that is also the thumbnail: a full-bleed picture and big type.
    In 9:16 the type sits in the middle band that both a Reel's 3:4 grid crop and its
    on-screen buttons leave clear."""
    eyebrow: str
    title: str
    subtitle: str
    detail: str
    images: dict              # format name -> a picture made at that format's output size
    title_sizes: dict = None  # format name -> the title's pixel size, for a longer title
    shade_top: float = 880    # 9:16: where the shade under the type starts, for a busy picture


def ease(u):
    u = min(max(u, 0.0), 1.0)
    return 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


def lerp(a, b, u):
    return tuple(x + (y - x) * u for x, y in zip(a, b))


def fade(t, t0, t1, edge=0.18):
    """1 inside [t0, t1], ramping over *edge* seconds at each end."""
    if t < t0 or t > t1:
        return 0.0
    return min(1.0, (t - t0) / edge, (t1 - t) / edge)


def mmss(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def centre(rect):
    x, y, w, h = rect
    return (x + w / 2, y + h / 2)


def union(*rects):
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return (x0, y0, x1 - x0, y1 - y0)


def view_of(rect, fmt, margin=24, max_zoom=2.0):
    """A camera (cx, cy, width) showing all of a stage rectangle in a format."""
    x, y, w, h = rect
    width = max(w + 2 * margin, (h + 2 * margin) * fmt.aspect, fmt.width / max_zoom)
    return (x + w / 2, y + h / 2, width)


class Track:
    """A value that holds still, then eases to each new target in turn."""

    def __init__(self, start, arc=0.0):
        self.start = tuple(start)
        self.moves = []
        self.arc = arc

    def to(self, t0, t1, target):
        self.moves.append((t0, t1, tuple(target)))
        self.moves.sort(key=lambda move: move[0])
        return self

    def at(self, t):
        value = self.start
        for t0, t1, target in self.moves:
            if t >= t1:
                value = target
                continue
            if t > t0:
                u = ease((t - t0) / (t1 - t0))
                point = lerp(value, target, u)
                if self.arc and len(point) == 2:
                    dx, dy = target[0] - value[0], target[1] - value[1]
                    bow = math.sin(math.pi * u) * self.arc
                    point = (point[0] - dy * bow, point[1] + dx * bow)
                return point
            break
        return value


def camera_rect(cam, fmt):
    """(cx, cy, width) -> an (x, y, w, h) rectangle of the format's shape, inside the stage."""
    cx, cy, w = cam
    w = min(w, STAGE_W, STAGE_H * fmt.aspect)
    h = w / fmt.aspect
    x = min(max(cx - w / 2, 0.0), STAGE_W - w)
    y = min(max(cy - h / 2, 0.0), STAGE_H - h)
    return x, y, w, h


class Film:
    def __init__(self, eyebrow, title, end_title, end_lines=(), duration=30.0):
        self.eyebrow = eyebrow
        self.title, self.end_title, self.end_lines = title, end_title, list(end_lines)
        self.duration = duration
        self.states = []        # (t, path, crossfade seconds)
        self.cameras = {name: Track((STAGE_W / 2, STAGE_H / 2, STAGE_W)) for name in FORMATS}
        self.cursor = None      # Track of (x, y) in stage pixels
        self.cursor_window = (0.0, 0.0)
        self.clicks = []
        self.highlights = []    # (t0, t1, rect)
        self.captions = []      # (t0, t1, text, {format name: anchor})
        self.badges = []        # (t0, t1, text)
        self.tickers = []       # (t0, t1, label, [(t, text), ...], slot)
        self.notes = []         # (t0, t1, title, text, target rect or None)
        self.covers = []        # (t0, t1, Cover)
        self.title_window = (0.15, 2.85)
        self.end_start = duration - 3.0
        self.capture = None     # the folder png() finds captured states in
        self._cache = {}
        self._stage = {}

    def png(self, name):
        import os
        return os.path.join(self.capture, f"{name}.png")

    # ── Script ─────────────────────────────────────────────────────────

    def state(self, t, path, crossfade=0.2, alt=None):
        """From *t*, show a capture. *alt* maps a format's name to an image made for that
        format (the dashboard at phone size, say), shown full-frame instead of through the camera."""
        self.states.append((t, path, crossfade, alt or {}))

    def camera(self, fmt, start=None, moves=()):
        """Set a format's camera: where it starts, then (t0, t1, (cx, cy, w)) moves."""
        track = self.cameras[fmt]
        if start is not None:
            track.start = tuple(start)
        for move in moves:
            track.to(*move)

    def move_cursor(self, t0, t1, point):
        self.cursor.to(t0, t1, point)

    def click(self, t):
        self.clicks.append(t)

    def highlight(self, t0, t1, rect, pad=5):
        x, y, w, h = rect
        self.highlights.append((t0, t1, (x - pad, y - pad, w + 2 * pad, h + 2 * pad)))

    def caption(self, t0, t1, text, anchors=None):
        self.captions.append((t0, t1, text, anchors or {}))

    def badge(self, t0, t1, text):
        self.badges.append((t0, t1, text))

    def ticker(self, t0, t1, label, steps, slot=0):
        """A readout that changes in place, e.g. the model time as a flood plays: *steps*
        is [(t, text)], each shown from its t. It fades in and out only at t0 and t1.
        A second readout (slot 1) sits beside the first."""
        self.tickers.append((t0, t1, label, sorted(steps), slot))

    def cover(self, t0, t1, cover):
        """A full-frame opening slide, made to work as the thumbnail too, over everything
        until it fades out at *t1*."""
        self.covers.append((t0, t1, cover))

    def note(self, t0, t1, title, text, target=None):
        """A callout beside *target* (a stage rectangle) naming it and saying what it is."""
        self.notes.append((t0, t1, title, text, target))

    def finish(self, t, card=4.5):
        """End the film at *t*, with the end card after it."""
        self.duration = t + card
        self.end_start = t

    # ── Drawing ────────────────────────────────────────────────────────

    def _image(self, path):
        if path not in self._cache:
            if len(self._cache) > 8:
                self._cache.pop(next(iter(self._cache)))
            self._cache[path] = QImage(path).convertToFormat(QImage.Format.Format_RGB32)
        return self._cache[path]

    def _states_at(self, t):
        ordered = sorted(self.states, key=lambda s: s[0])
        current, previous = None, None
        for entry in ordered:
            if entry[0] <= t:
                previous, current = current, entry
        if current is None:
            return ordered[0], None, 1.0
        crossfade = current[2]
        if previous is not None and crossfade > 0 and t - current[0] < crossfade:
            return current, previous, (t - current[0]) / crossfade
        return current, None, 1.0

    @staticmethod
    def _font(size, weight=QFont.Weight.Normal, spacing=0.0):
        font = QFont(FONT)
        font.setPixelSize(int(size))
        font.setWeight(weight)
        if spacing:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
        return font

    def _draw_stage(self, painter, t, fmt):
        x, y, w, h = camera_rect(self.cameras[fmt.name].at(t), fmt)
        source = QRectF(x * SCALE, y * SCALE, w * SCALE, h * SCALE)
        current, previous, alpha = self._states_at(t)
        # Most frames hold still: scale the capture once and reuse it until something moves.
        key = (round(x, 2), round(y, 2), round(w, 2), current[1], previous and previous[1], round(alpha, 3))
        cached = self._stage.get(fmt.name)
        if cached is None or cached[0] != key:
            stage = QImage(fmt.width * fmt.ratio, (fmt.height - fmt.header) * fmt.ratio, QImage.Format.Format_RGB32)
            stage.fill(PAPER)
            target = QRectF(0, 0, stage.width(), stage.height())
            p = QPainter(stage)
            p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)

            def draw(entry):
                alt = entry[3].get(fmt.name)
                if alt:
                    image = self._image(alt)
                    p.drawImage(target, image, QRectF(0, 0, image.width(),
                                                      image.width() * target.height() / target.width()))
                else:
                    p.drawImage(target, self._image(entry[1]), source)

            if previous is not None:
                draw(previous)
                p.setOpacity(alpha)
            draw(current)
            p.end()
            cached = self._stage[fmt.name] = (key, stage)
        painter.drawImage(QRectF(0, fmt.header, fmt.width, fmt.height - fmt.header), cached[1])
        self._full_frame = bool(current[3].get(fmt.name))
        return x, y, fmt.width / w, fmt.header

    @staticmethod
    def _to_screen(view, point):
        x, y, zoom, top = view
        return QPointF((point[0] - x) * zoom, (point[1] - y) * zoom + top)

    def _draw_highlights(self, painter, t, view):
        for t0, t1, rect in self.highlights:
            a = fade(t, t0, t1, 0.15)
            if a <= 0:
                continue
            top_left = self._to_screen(view, rect[:2])
            zoom = view[2]
            box = QRectF(top_left, top_left + QPointF(rect[2] * zoom, rect[3] * zoom))
            glow = QColor(ACCENT)
            glow.setAlphaF(0.22 * a)
            painter.setPen(QPen(glow, 10))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(box, 8, 8)
            line = QColor(ACCENT)
            line.setAlphaF(a)
            painter.setPen(QPen(line, 3.5))
            painter.drawRoundedRect(box, 8, 8)

    def _draw_cursor(self, painter, t, view):
        if self.cursor is None or not (self.cursor_window[0] <= t <= self.cursor_window[1]):
            return
        a = fade(t, *self.cursor_window, 0.25)
        tip = self._to_screen(view, self.cursor.at(t))
        for click in self.clicks:
            u = (t - click) / 0.5
            if 0 <= u <= 1:
                ring = QColor(ACCENT)
                ring.setAlphaF((1 - u) * a)
                painter.setPen(QPen(ring, 4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                radius = 10 + 30 * ease(u)
                painter.drawEllipse(tip, radius, radius)
        pressed = any(0 <= t - click <= 0.18 for click in self.clicks)
        size = 1.94 * (0.88 if pressed else 1.0)
        arrow = [(0, 0), (0, 17), (4.6, 12.9), (7.6, 19.6), (10.2, 18.5), (7.3, 11.9), (12.8, 11.9)]
        polygon = QPolygonF([QPointF(tip.x() + px * size, tip.y() + py * size) for px, py in arrow])
        painter.setOpacity(a * 0.35)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0))
        painter.drawPolygon(polygon.translated(2, 3))
        painter.setOpacity(a)
        painter.setPen(QPen(QColor(255, 255, 255), 2.4))
        painter.setBrush(QColor(20, 20, 20))
        painter.drawPolygon(polygon)
        painter.setOpacity(1.0)

    def _draw_caption(self, painter, t, fmt):
        for t0, t1, text, anchors in self.captions:
            a = fade(t, t0, t1, 0.15)
            if a <= 0:
                continue
            anchor = anchors.get(fmt.name, "center")
            width = fmt.caption_width if anchor == "center" else min(fmt.caption_width, 470)
            font = self._font(fmt.caption_size, QFont.Weight.DemiBold)
            flags = int(Qt.AlignmentFlag.AlignCenter) | WRAP
            bounds = QFontMetricsF(font).boundingRect(QRectF(0, 0, width, 600), flags, text)
            box = QRectF(0, 0, bounds.width() + 64, bounds.height() + 30)
            x = {"center": fmt.caption_centre_x, "right": fmt.width - 48 - box.width() / 2,
                 "left": 48 + box.width() / 2}[anchor]
            box.moveCenter(QPointF(x, fmt.height - fmt.caption_bottom - box.height() / 2))
            painter.setOpacity(a)
            painter.setPen(Qt.PenStyle.NoPen)
            back = QColor(INK)
            back.setAlphaF(0.88)
            painter.setBrush(back)
            painter.drawRoundedRect(box, 14, 14)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(box, flags, text)
            painter.setOpacity(1.0)

    def _draw_badges(self, painter, t, fmt):
        for t0, t1, text in self.badges:
            a = fade(t, t0, t1, 0.15)
            if a <= 0:
                continue
            font = self._font(54, QFont.Weight.Bold)
            label = self._font(19, QFont.Weight.DemiBold, 2.0)
            width = max(QFontMetricsF(font).horizontalAdvance(text),
                        QFontMetricsF(label).horizontalAdvance("REAL RUN TIME")) + 132
            if fmt.badge_origin is None:
                box = QRectF(fmt.width - 64 - width, 56, width, 124)
            else:
                box = QRectF(fmt.badge_origin[0], fmt.badge_origin[1], width, 124)
            painter.setOpacity(a)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ACCENT)
            painter.drawRoundedRect(box, 26, 26)
            painter.setBrush(QColor(255, 255, 255))
            cy = box.top() + 50
            for i in range(2):  # a fast-forward mark, drawn rather than an emoji
                ox = box.left() + 30 + i * 21
                painter.drawPolygon(QPolygonF([QPointF(ox, cy - 16), QPointF(ox, cy + 16),
                                               QPointF(ox + 23, cy)]))
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(font)
            painter.drawText(QRectF(box.left() + 96, box.top() + 14, width - 100, 72),
                             int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
            painter.setFont(label)
            painter.drawText(QRectF(box.left() + 30, box.top() + 84, width - 40, 26),
                             int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                             "REAL RUN TIME")
            painter.setOpacity(1.0)

    def _draw_tickers(self, painter, t, fmt):
        right = None  # where the last readout drawn ends, for one in the next slot
        for t0, t1, label, steps, slot in sorted(self.tickers, key=lambda ticker: ticker[4]):
            a = fade(t, t0, t1, 0.2)
            if a <= 0:
                continue
            text = steps[0][1]
            for at, value in steps:
                if at <= t:
                    text = value
            font = self._font(54, QFont.Weight.Bold)
            small = self._font(19, QFont.Weight.DemiBold, 2.0)
            width = max(QFontMetricsF(font).horizontalAdvance(text),
                        QFontMetricsF(small).horizontalAdvance(label)) + 64
            x, y = fmt.badge_origin if fmt.badge_origin is not None else (fmt.width - 64 - width, 56)
            if slot and right is not None:
                x = right + 20
            right = x + width
            box = QRectF(x, y, width, 124)
            painter.setOpacity(a)
            painter.setPen(Qt.PenStyle.NoPen)
            back = QColor(CARD)
            back.setAlphaF(0.9)
            painter.setBrush(back)
            painter.drawRoundedRect(box, 26, 26)
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(font)
            painter.drawText(QRectF(box.left() + 30, box.top() + 14, width - 40, 72),
                             int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), text)
            painter.setPen(MUTED)
            painter.setFont(small)
            painter.drawText(QRectF(box.left() + 30, box.top() + 84, width - 40, 26),
                             int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
            painter.setOpacity(1.0)

    def _draw_notes(self, painter, t, fmt, view):
        for t0, t1, title, text, target in self.notes:
            a = fade(t, t0, t1, 0.2)
            if a <= 0:
                continue
            title_font = self._font(fmt.note_title, QFont.Weight.Bold)
            body_font = self._font(fmt.note_body)
            inner = fmt.note_width - 64
            flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | WRAP
            title_h = QFontMetricsF(title_font).boundingRect(QRectF(0, 0, inner, 400), flags, title).height()
            body_h = QFontMetricsF(body_font).boundingRect(QRectF(0, 0, inner, 600), flags, text).height() if text else 0
            w = fmt.note_width
            h = title_h + (body_h + 10 if text else 0) + 44
            top_limit = fmt.header + 24 if fmt.header else 36
            bottom_limit = fmt.height - fmt.caption_bottom - 150 - h
            box = None
            pointed = False
            if target is not None and not self._full_frame:
                tl = self._to_screen(view, target[:2])
                zoom = view[2]
                tr = QRectF(tl.x(), tl.y(), target[2] * zoom, target[3] * zoom)
                # A control outside the frame gets no line pointing off-screen.
                pointed = tr.intersects(QRectF(0, fmt.header, fmt.width, fmt.height - fmt.header))
            if pointed:
                if fmt is LANDSCAPE:
                    room_left, room_right = tr.left() - 40, fmt.width - tr.right() - 40
                    x = tr.left() - 36 - w if room_left >= w or room_left > room_right else tr.right() + 36
                    x = min(max(x, 40), fmt.width - 40 - w)
                    y = min(max(tr.center().y() - h / 2, top_limit), bottom_limit)
                    box = QRectF(x, y, w, h)
                    if box.intersects(tr):  # no room beside it: go above or below instead
                        y = tr.bottom() + 28 if tr.center().y() < fmt.height / 2 else tr.top() - 28 - h
                        box = QRectF(min(max(tr.center().x() - w / 2, 40), fmt.width - 40 - w),
                                     min(max(y, top_limit), bottom_limit), w, h)
                else:
                    middle = (fmt.header + fmt.height - fmt.caption_bottom) / 2
                    y = tr.bottom() + 30 if tr.center().y() < middle else tr.top() - 30 - h
                    box = QRectF(60, min(max(y, top_limit), bottom_limit), w, h)
            if box is None:
                box = QRectF(60 if fmt is VERTICAL else 72, top_limit + (40 if fmt is LANDSCAPE else 0), w, h)
            painter.setOpacity(a)
            if pointed:
                # A line from the card to the control it describes.
                cx = min(max(tr.center().x(), box.left()), box.right())
                cy = min(max(tr.center().y(), box.top()), box.bottom())
                ex = min(max(cx, tr.left()), tr.right())
                ey = min(max(cy, tr.top()), tr.bottom())
                painter.setPen(QPen(ACCENT, 3))
                painter.drawLine(QPointF(cx, cy), QPointF(ex, ey))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(ACCENT)
                painter.drawEllipse(QPointF(ex, ey), 6, 6)
            painter.setPen(Qt.PenStyle.NoPen)
            for spread, alpha in ((14, 18), (6, 30)):
                painter.setBrush(QColor(0, 0, 0, alpha))
                painter.drawRoundedRect(box.adjusted(-spread / 2, -spread / 2 + 6, spread / 2, spread / 2 + 6), 16, 16)
            painter.setBrush(QColor(255, 255, 255))
            painter.drawRoundedRect(box, 14, 14)
            painter.setBrush(ACCENT)
            painter.drawRoundedRect(QRectF(box.left(), box.top(), 10, box.height()), 5, 5)
            painter.setFont(title_font)
            painter.setPen(INK)
            painter.drawText(QRectF(box.left() + 36, box.top() + 20, inner, title_h + 4), flags, title)
            if text:
                painter.setFont(body_font)
                painter.setPen(QColor("#3c4a47"))
                painter.drawText(QRectF(box.left() + 36, box.top() + 30 + title_h, inner, body_h + 4), flags, text)
            painter.setOpacity(1.0)

    def _eyebrow(self):
        return self.eyebrow

    def _draw_header(self, painter, fmt):
        if not fmt.header:
            return
        painter.fillRect(QRectF(0, 0, fmt.width, fmt.header), CARD)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ACCENT)
        painter.drawRoundedRect(QRectF(60, 168, 44, 6), 3, 3)
        painter.setFont(self._font(22, QFont.Weight.DemiBold, 3.0))
        painter.setPen(MUTED)
        painter.drawText(QRectF(120, 152, fmt.width - 180, 38), int(Qt.AlignmentFlag.AlignVCenter),
                         self._eyebrow())
        title = self._font(50, QFont.Weight.Bold)
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | WRAP
        painter.setFont(title)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QRectF(60, 200, fmt.width - 120, fmt.header - 210), flags, self.title)

    def _draw_title(self, painter, t, fmt):
        if fmt.header:
            return  # the band already carries it
        t0, t1 = self.title_window
        a = fade(t, t0, t1, 0.3)
        if a <= 0:
            return
        slide = (1 - ease(min(1.0, (t - t0) / 0.45))) * -60
        eyebrow = self._font(24, QFont.Weight.DemiBold, 3.0)
        title = self._font(fmt.title_size, QFont.Weight.Bold)
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | WRAP
        text_box = QFontMetricsF(title).boundingRect(QRectF(0, 0, fmt.title_width, 600), flags, self.title)
        width = max(text_box.width(), QFontMetricsF(eyebrow).horizontalAdvance(self._eyebrow()) + 60) + 104
        box = QRectF(fmt.title_origin[0] + slide, fmt.title_origin[1], width, text_box.height() + 124)
        painter.setOpacity(a)
        painter.setPen(Qt.PenStyle.NoPen)
        back = QColor(CARD)
        back.setAlphaF(0.93)
        painter.setBrush(back)
        painter.drawRoundedRect(box, 18, 18)
        painter.setBrush(ACCENT)
        painter.drawRoundedRect(QRectF(box.left() + 52, box.top() + 40, 44, 6), 3, 3)
        painter.setFont(eyebrow)
        painter.setPen(MUTED)
        painter.drawText(QRectF(box.left() + 112, box.top() + 26, width, 34),
                         int(Qt.AlignmentFlag.AlignVCenter), self._eyebrow())
        painter.setFont(title)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(QRectF(box.left() + 52, box.top() + 80, fmt.title_width, text_box.height() + 10),
                         flags, self.title)
        painter.setOpacity(1.0)

    def _draw_end(self, painter, t, fmt):
        if t < self.end_start:
            return
        a = min(1.0, (t - self.end_start) / 0.35)
        painter.setOpacity(a)
        painter.fillRect(QRectF(0, 0, fmt.width, fmt.height), CARD)
        rise = (1 - ease(min(1.0, (t - self.end_start) / 0.6))) * 30
        left, top = (150, fmt.end_top) if fmt is LANDSCAPE else (80, fmt.end_top)
        text_width = fmt.width - left - 80
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | WRAP
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ACCENT)
        painter.drawRoundedRect(QRectF(left, top + 17 + rise, 44, 6), 3, 3)
        painter.setPen(MUTED)
        painter.setFont(self._font(26, QFont.Weight.DemiBold, 3.0))
        painter.drawText(QRectF(left + 62, top + rise, text_width, 40), int(Qt.AlignmentFlag.AlignVCenter),
                         self._eyebrow())
        y = top + 70
        title = self._font(fmt.end_title_size, QFont.Weight.Bold)
        bounds = QFontMetricsF(title).boundingRect(QRectF(0, 0, text_width, 800), flags, self.end_title)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(title)
        painter.drawText(QRectF(left, y + rise, text_width, bounds.height() + 10), flags, self.end_title)
        y += bounds.height() + 50
        for i, (line, colour, size) in enumerate(self.end_lines):
            font = self._font(size, QFont.Weight.DemiBold if i == 0 else QFont.Weight.Normal)
            bounds = QFontMetricsF(font).boundingRect(QRectF(0, 0, text_width, 800), flags, line)
            painter.setPen(QColor(colour))
            painter.setFont(font)
            painter.drawText(QRectF(left, y + rise * (1 + 0.3 * i), text_width, bounds.height() + 10), flags, line)
            y += bounds.height() + 26
        painter.setOpacity(1.0)

    def _draw_cover(self, painter, t, fmt):
        for t0, t1, cover in self.covers:
            if not t0 <= t <= t1:
                continue
            painter.setOpacity(min(1.0, (t1 - t) / 0.45))  # holds, then fades into the film
            frame = QRectF(0, 0, fmt.width, fmt.height)
            painter.fillRect(frame, CARD)
            painter.drawImage(frame, self._image(cover.images[fmt.name]))
            # Shade the side the type goes on, so it reads over any picture. The type is
            # sized to be read in a thumbnail a few centimetres wide.
            if fmt is LANDSCAPE:
                shade = QLinearGradient(0, 0, 1180, 0)
                stops = ((0.0, 0.94), (0.5, 0.82), (1.0, 0.0))
                left, top, widths, sizes, gaps = 110, 250, (900, 700), (30, 176, 52, 30), (34, 24)
            else:
                shade = QLinearGradient(0, cover.shade_top, 0, cover.shade_top + 420)
                stops = ((0.0, 0.0), (1.0, 0.92))
                left, top, widths, sizes, gaps = 72, 1020, (936, 936), (28, 140, 44, 27), (22, 22)
            for at, alpha in stops:
                colour = QColor(CARD)
                colour.setAlphaF(alpha)
                shade.setColorAt(at, colour)
            painter.fillRect(frame, shade)
            flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | WRAP
            eyebrow = self._font(sizes[0], QFont.Weight.DemiBold, 4.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ACCENT)
            painter.drawRoundedRect(QRectF(left, top + sizes[0] / 2 - 3, 52, 7), 3, 3)
            painter.setFont(eyebrow)
            painter.setPen(MUTED)
            painter.drawText(QRectF(left + 72, top - 10, widths[0], sizes[0] + 20),
                             int(Qt.AlignmentFlag.AlignVCenter), cover.eyebrow)
            y = top + sizes[0] + 34
            title_size = (cover.title_sizes or {}).get(fmt.name, sizes[1])
            for text, size, weight, colour, width, gap in (
                    (cover.title, title_size, QFont.Weight.Black, QColor(255, 255, 255), widths[0], gaps[0]),
                    (cover.subtitle, sizes[2], QFont.Weight.DemiBold, QColor("#cfe6f7"), widths[1], gaps[1]),
                    (cover.detail, sizes[3], QFont.Weight.Normal, MUTED, widths[0], 0)):
                font = self._font(size, weight, -size * 0.02 if size > 100 else 0.0)
                bounds = QFontMetricsF(font).boundingRect(QRectF(0, 0, width, 1200), flags, text)
                painter.setFont(font)
                painter.setPen(colour)
                painter.drawText(QRectF(left, y, width, bounds.height() + 10), flags, text)
                y += bounds.height() + gap
            painter.setOpacity(1.0)

    def frame(self, t, fmt):
        image = QImage(fmt.width * fmt.ratio, fmt.height * fmt.ratio, QImage.Format.Format_RGB32)
        image.fill(PAPER)
        painter = QPainter(image)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                               | QPainter.RenderHint.TextAntialiasing)
        painter.scale(fmt.ratio, fmt.ratio)
        view = self._draw_stage(painter, t, fmt)
        if not self._full_frame:  # the cursor and boxes are placed on the desktop captures
            self._draw_highlights(painter, t, view)
            self._draw_cursor(painter, t, view)
        self._draw_notes(painter, t, fmt, view)
        self._draw_header(painter, fmt)
        self._draw_caption(painter, t, fmt)
        self._draw_badges(painter, t, fmt)
        self._draw_tickers(painter, t, fmt)
        self._draw_title(painter, t, fmt)
        self._draw_end(painter, t, fmt)
        self._draw_cover(painter, t, fmt)
        painter.end()
        return image

    def thumbnails(self, folder, slug, t=1.0):
        """The opening slide, held, as pictures: 1920 x 1080 for YouTube (well under its
        2 MB limit) and 1080 x 1920 for an Instagram cover."""
        import os
        os.makedirs(folder, exist_ok=True)
        paths = []
        for fmt, width, name in ((LANDSCAPE, 1920, "youtube"), (VERTICAL, 1080, "instagram")):
            path = self.still(t, fmt, os.path.join(folder, f"{slug}-{name}.jpg"), width=width, quality=92)
            print("thumbnail", path, f"{os.path.getsize(path) / 1e6:.2f} MB")
            paths.append(path)
        return paths

    def still(self, t, fmt, path, width=None, quality=90):
        """One frame as a picture file, scaled to *width* if given: a thumbnail, say."""
        image = self.frame(t, fmt)
        if width:
            image = image.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        image.save(path, quality=quality)
        return path

    def render(self, path, fmt, stills=()):
        command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
                   "-s", f"{fmt.width * fmt.ratio}x{fmt.height * fmt.ratio}", "-r", str(FPS), "-i", "-",
                   "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
                   "-movflags", "+faststart", path]
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
        for index in range(int(round(self.duration * FPS))):
            t = index / FPS
            image = self.frame(t, fmt)
            encoder.stdin.write(image.constBits().asstring(image.sizeInBytes()))
            for still_t, still_path in stills:
                if abs(t - still_t) < 0.5 / FPS:
                    image.save(still_path)
        encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError(f"ffmpeg failed writing {path}")

    def render_all(self, slug, out_dir, still_times=(), still_dir=None):
        """Render every format, as out/<format>/<slug>.mp4."""
        import os
        for fmt in FORMATS.values():
            folder = os.path.join(out_dir, fmt.name)
            os.makedirs(folder, exist_ok=True)
            stills = []
            if still_dir:
                stills = [(t, os.path.join(still_dir, f"{slug}_{fmt.name}_{t:04.1f}.png")) for t in still_times]
            self.render(os.path.join(folder, f"{slug}.mp4"), fmt, stills)


# ── Timeline helpers, shared by the films' scripts ─────────────────────────

class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def wait(self, seconds):
        self.t += seconds
        return self.t


def left_part(rect, inset=14):
    x, y, w, h = rect
    return (x + inset, y + h / 2)


def cut(film, t, landscape=None, vertical=None, duration=0.8):
    if landscape is not None:
        film.camera("landscape", moves=[(t, t + duration, landscape)])
    if vertical is not None:
        film.camera("vertical", moves=[(t, t + duration, vertical)])


def walk(film, clock, items, per=3.0, gap=0.2):
    """Point at each control, box it and say what it is; click it if asked.

    Each item is (rect, title, text) and optionally the state shown once it is
    reached (or clicked), whether it is clicked, a state that follows, and the
    (16:9, 9:16) framings to move to as it is reached (either may be None).
    """
    for item in items:
        rect, title, text = item[:3]
        state = item[3] if len(item) > 3 else None
        click = item[4] if len(item) > 4 else False
        after = item[5] if len(item) > 5 else None
        views = item[6] if len(item) > 6 else (None, None)
        t = clock.t
        cut(film, t - 0.3, *views)
        film.move_cursor(t, t + 0.5, left_part(rect, min(18, rect[2] / 2)) if rect[2] > 300 else centre(rect))
        if click:
            film.click(t + 0.55)
        if state:
            film.state(t + (0.62 if click else 0.1), film.png(state), crossfade=0.12)
        if after:
            film.state(t + 1.7, film.png(after), crossfade=0.15)
        film.highlight(t + 0.45, t + per, rect, pad=3)
        film.note(t + 0.5, t + per, title, text, rect)
        clock.wait(per + gap)


def write_chapters(path, chapters):
    """YouTube chapters, for the description: one 'm:ss title' line each."""
    with open(path, "w") as handle:
        for t, title in chapters:
            handle.write(f"{mmss(t)} {title}\n")
