"""Shared building blocks for the interface.

The chart is drawn with ``QPainter`` rather than a plotting library. At one
sample a second with a two-minute window there is nothing to optimise, and
owning the paint loop means the grid, the scale easing and the hover crosshair
can behave exactly as the instrument metaphor wants them to.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.formatting import human_speed, split_speed
from .theme import Palette, Type, mono_font, ui_font

# --------------------------------------------------------------------------- #
# Background work
# --------------------------------------------------------------------------- #


class Task(QThread):
    """Runs a blocking function off the UI thread.

    The work function receives this object, so it can push results back with
    ``task.produced.emit(...)`` and watch ``task.stop_event`` to bail out early.
    Qt delivers those signals to the UI thread as queued events, which is what
    keeps the window responsive while a scan is running.
    """

    produced = Signal(object)
    progressed = Signal(int, int)
    failed = Signal(str)
    completed = Signal()

    def __init__(self, work: Callable[[Task], None], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._work = work
        self.stop_event = threading.Event()

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            self._work(self)
        except Exception as exc:  # surfaced in the UI, never printed to a console
            self.failed.emit(str(exc))
        finally:
            self.completed.emit()

    def cancel(self) -> None:
        """Ask the work function to wind up at the next safe point."""
        self.stop_event.set()

    @property
    def cancelled(self) -> bool:
        return self.stop_event.is_set()


# --------------------------------------------------------------------------- #
# Layout primitives
# --------------------------------------------------------------------------- #


class Panel(QFrame):
    """A bordered surface. Used sparingly — most content sits directly on the base."""

    def __init__(self, parent: QWidget | None = None, padding: int = 16) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(12)

    def body(self) -> QVBoxLayout:
        return self._layout


class SectionHeader(QWidget):
    """A title with an optional explanatory note underneath."""

    def __init__(self, title: str, note: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.title = QLabel(title)
        self.title.setObjectName("SectionTitle")
        layout.addWidget(self.title)

        self.note = QLabel(note)
        self.note.setObjectName("SectionNote")
        self.note.setVisible(bool(note))
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

    def set_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


class Readout(QWidget):
    """A live number with its unit and caption.

    The colour bar on the left ties the number to its trace in the chart, which
    removes the need for a separate legend.
    """

    def __init__(
        self,
        caption: str,
        accent: str = Palette.text,
        value_size: int = Type.readout,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._accent = accent

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self._bar = QFrame()
        self._bar.setFixedWidth(2)
        self._bar.setStyleSheet(f"background-color: {accent}; border: none;")
        self._bar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        outer.addWidget(self._bar)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)

        self._caption = QLabel(caption)
        self._caption.setFont(ui_font(Type.label))
        self._caption.setStyleSheet(f"color: {Palette.muted};")
        column.addWidget(self._caption)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)

        self._value = QLabel("0")
        self._value.setFont(mono_font(value_size, QFont.Weight.DemiBold))
        self._value.setStyleSheet(f"color: {accent};")
        row.addWidget(self._value)

        self._unit = QLabel("")
        self._unit.setFont(ui_font(Type.label))
        self._unit.setStyleSheet(f"color: {Palette.muted};")
        self._unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        row.addWidget(self._unit)
        row.addStretch(1)
        column.addLayout(row)

        self._footnote = QLabel("")
        self._footnote.setFont(ui_font(Type.small))
        self._footnote.setStyleSheet(f"color: {Palette.faint};")
        self._footnote.setVisible(False)
        column.addWidget(self._footnote)

        outer.addLayout(column, 1)

    def set_speed(self, bytes_per_second: float) -> None:
        value, unit = split_speed(bytes_per_second)
        self._value.setText(value)
        self._unit.setText(unit)

    def set_text(self, value: str, unit: str = "") -> None:
        self._value.setText(value)
        self._unit.setText(unit)

    def set_footnote(self, text: str) -> None:
        self._footnote.setText(text)
        self._footnote.setVisible(bool(text))

    def set_accent(self, colour: str) -> None:
        self._accent = colour
        self._bar.setStyleSheet(f"background-color: {colour}; border: none;")
        self._value.setStyleSheet(f"color: {colour};")


class FactGrid(QWidget):
    """Label/value pairs in two columns. Used for adapter and session details."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[str, QLabel] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(7)

    def add(self, label: str, value: str = "—", monospace: bool = False) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        caption = QLabel(label)
        caption.setFont(ui_font(Type.label))
        caption.setStyleSheet(f"color: {Palette.muted};")
        caption.setMinimumWidth(104)
        row.addWidget(caption)

        display = QLabel(value)
        display.setFont(mono_font(Type.label) if monospace else ui_font(Type.label))
        display.setStyleSheet(f"color: {Palette.text};")
        display.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(display, 1, Qt.AlignmentFlag.AlignRight)

        self._layout.addLayout(row)
        self._rows[label] = display

    def set(self, label: str, value: str, colour: str | None = None) -> None:
        widget = self._rows.get(label)
        if widget is None:
            return
        widget.setText(value)
        widget.setStyleSheet(f"color: {colour or Palette.text};")


# --------------------------------------------------------------------------- #
# The chart
# --------------------------------------------------------------------------- #


class TrafficChart(QWidget):
    """Two-channel scrolling area chart for download and upload rates.

    Vertical scale eases toward the window's peak instead of snapping to it, so
    a single burst does not make the whole trace jump. Hovering reads out the
    values under the cursor.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._down: list[float] = []
        self._up: list[float] = []
        self._capacity = 120
        self._scale = 65536.0     # eased vertical maximum, floors at 64 KB/s
        self._hover_index: int | None = None

        self._left_margin = 74
        self._right_margin = 14
        self._top_margin = 14
        self._bottom_margin = 22

    # ------------------------------------------------------------------ data

    def set_capacity(self, samples: int) -> None:
        self._capacity = max(20, samples)
        self._trim()
        self.update()

    def push(self, down: float, up: float) -> None:
        self._down.append(max(0.0, down))
        self._up.append(max(0.0, up))
        self._trim()
        self.update()

    def load(self, down: Sequence[float], up: Sequence[float]) -> None:
        self._down = [max(0.0, v) for v in down][-self._capacity :]
        self._up = [max(0.0, v) for v in up][-self._capacity :]
        self.update()

    def clear(self) -> None:
        self._down.clear()
        self._up.clear()
        self._scale = 65536.0
        self.update()

    def _trim(self) -> None:
        if len(self._down) > self._capacity:
            del self._down[: len(self._down) - self._capacity]
        if len(self._up) > self._capacity:
            del self._up[: len(self._up) - self._capacity]

    # ----------------------------------------------------------- interaction

    def mouseMoveEvent(self, event) -> None:
        plot = self._plot_rect()
        if not plot.contains(event.position()) or not self._down:
            if self._hover_index is not None:
                self._hover_index = None
                self.update()
            return
        fraction = (event.position().x() - plot.left()) / max(plot.width(), 1)
        index = round(fraction * (self._capacity - 1)) - (self._capacity - len(self._down))
        index = max(0, min(len(self._down) - 1, index))
        if index != self._hover_index:
            self._hover_index = index
            self.update()

    def leaveEvent(self, event) -> None:
        self._hover_index = None
        self.update()

    # ---------------------------------------------------------------- paint

    def _plot_rect(self) -> QRectF:
        return QRectF(
            self._left_margin,
            self._top_margin,
            max(1.0, self.width() - self._left_margin - self._right_margin),
            max(1.0, self.height() - self._top_margin - self._bottom_margin),
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        plot = self._plot_rect()
        self._paint_background(painter)
        self._ease_scale()
        self._paint_grid(painter, plot)

        if len(self._down) >= 2:
            self._paint_series(painter, plot, self._down, Palette.download)
            self._paint_series(painter, plot, self._up, Palette.upload)
            self._paint_hover(painter, plot)
        else:
            self._paint_placeholder(painter, plot)

        painter.end()

    def _paint_background(self, painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Palette.panel))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 6, 6)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(Palette.rule), 1))
        painter.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 6, 6)

    def _ease_scale(self) -> None:
        """Move the vertical maximum toward the current peak, gradually."""
        window = self._down + self._up
        peak = max(window) if window else 0.0
        target = max(peak * 1.25, 65536.0)
        # Rise quickly so a spike is never clipped; fall slowly so the baseline
        # stays comparable from one second to the next.
        rate = 0.5 if target > self._scale else 0.06
        self._scale += (target - self._scale) * rate

    def _paint_grid(self, painter: QPainter, plot: QRectF) -> None:
        painter.setFont(mono_font(Type.small))
        divisions = 4
        for step in range(divisions + 1):
            fraction = step / divisions
            y = plot.bottom() - plot.height() * fraction

            painter.setPen(QPen(QColor(Palette.rule), 1, Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

            painter.setPen(QPen(QColor(Palette.faint)))
            label = human_speed(self._scale * fraction, 0 if fraction == 0 else 1)
            painter.drawText(
                QRectF(0, y - 9, self._left_margin - 10, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

        painter.setPen(QPen(QColor(Palette.faint)))
        painter.setFont(ui_font(Type.small))
        seconds = self._capacity
        painter.drawText(
            QRectF(plot.left(), plot.bottom() + 4, 90, 16),
            Qt.AlignmentFlag.AlignLeft,
            f"{seconds}s ago",
        )
        painter.drawText(
            QRectF(plot.right() - 40, plot.bottom() + 4, 40, 16),
            Qt.AlignmentFlag.AlignRight,
            "now",
        )

    def _points(self, plot: QRectF, values: Sequence[float]) -> list[QPointF]:
        step = plot.width() / max(1, self._capacity - 1)
        offset = self._capacity - len(values)
        points = []
        for index, value in enumerate(values):
            x = plot.left() + (index + offset) * step
            y = plot.bottom() - (min(value, self._scale) / self._scale) * plot.height()
            points.append(QPointF(x, y))
        return points

    def _paint_series(self, painter: QPainter, plot: QRectF, values: Sequence[float], colour: str) -> None:
        points = self._points(plot, values)
        if len(points) < 2:
            return

        fill = QPainterPath()
        fill.moveTo(points[0].x(), plot.bottom())
        for point in points:
            fill.lineTo(point)
        fill.lineTo(points[-1].x(), plot.bottom())
        fill.closeSubpath()

        gradient = QLinearGradient(0, plot.top(), 0, plot.bottom())
        gradient.setColorAt(0.0, Palette.rgba(colour, 0.26))
        gradient.setColorAt(1.0, Palette.rgba(colour, 0.02))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(fill)

        stroke = QPainterPath()
        stroke.moveTo(points[0])
        for point in points[1:]:
            stroke.lineTo(point)
        pen = QPen(QColor(colour), 1.8)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawPath(stroke)

        # A dot on the newest sample marks where the trace is being written.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colour))
        painter.drawEllipse(points[-1], 2.6, 2.6)

    def _paint_hover(self, painter: QPainter, plot: QRectF) -> None:
        if self._hover_index is None or self._hover_index >= len(self._down):
            return

        step = plot.width() / max(1, self._capacity - 1)
        offset = self._capacity - len(self._down)
        x = plot.left() + (self._hover_index + offset) * step

        pen = QPen(QColor(Palette.faint), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))

        down = self._down[self._hover_index]
        up = self._up[self._hover_index]
        ago = len(self._down) - 1 - self._hover_index
        lines = [
            f"{ago}s ago" if ago else "now",
            f"down  {human_speed(down)}",
            f"up    {human_speed(up)}",
        ]

        painter.setFont(mono_font(Type.small))
        metrics = painter.fontMetrics()
        width = max(metrics.horizontalAdvance(line) for line in lines) + 16
        height = metrics.height() * len(lines) + 12
        left = min(x + 10, plot.right() - width)
        box = QRectF(left, plot.top() + 8, width, height)

        painter.setPen(QPen(QColor(Palette.rule)))
        painter.setBrush(QColor(Palette.panel_high))
        painter.drawRoundedRect(box, 4, 4)

        colours = [Palette.muted, Palette.download, Palette.upload]
        for index, (line, colour) in enumerate(zip(lines, colours, strict=True)):
            painter.setPen(QPen(QColor(colour)))
            painter.drawText(
                QRectF(box.left() + 8, box.top() + 6 + index * metrics.height(), width, metrics.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                line,
            )

    def _paint_placeholder(self, painter: QPainter, plot: QRectF) -> None:
        painter.setPen(QPen(QColor(Palette.faint)))
        painter.setFont(ui_font(Type.label))
        painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Collecting samples")


class Sparkline(QWidget):
    """A small inline trace. Used for ping latency next to the statistics."""

    def __init__(self, colour: str = Palette.download, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: list[float | None] = []
        self._colour = colour
        self._capacity = 90
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def push(self, value: float | None) -> None:
        self._values.append(value)
        if len(self._values) > self._capacity:
            del self._values[: len(self._values) - self._capacity]
        self.update()

    def clear(self) -> None:
        self._values.clear()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(1, 4, self.width() - 2, self.height() - 8)
        present = [v for v in self._values if v is not None]
        if len(present) < 2:
            painter.setPen(QPen(QColor(Palette.faint)))
            painter.setFont(ui_font(Type.small))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Waiting for replies")
            painter.end()
            return

        ceiling = max(present) * 1.2 or 1.0
        step = rect.width() / max(1, self._capacity - 1)
        offset = self._capacity - len(self._values)

        pen = QPen(QColor(self._colour), 1.6)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        path = QPainterPath()
        drawing = False
        for index, value in enumerate(self._values):
            x = rect.left() + (index + offset) * step
            if value is None:
                # A dropped reply breaks the line and leaves a marker behind.
                drawing = False
                painter.setPen(QPen(QColor(Palette.alert), 1.4))
                painter.drawLine(QPointF(x, rect.bottom()), QPointF(x, rect.bottom() - 5))
                painter.setPen(pen)
                continue
            y = rect.bottom() - (value / ceiling) * rect.height()
            if drawing:
                path.lineTo(QPointF(x, y))
            else:
                path.moveTo(QPointF(x, y))
                drawing = True

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()
