"""Open sockets, and the programs that opened them."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.connections import Connection, list_connections, summarise, top_talkers
from ..core.export import suggested_filename, to_csv
from .theme import Palette, Type, mono_font, ui_font
from .widgets import Readout, SectionHeader, Task

COLUMNS = ["Process", "PID", "Protocol", "Local", "Remote", "State"]
REFRESH_MS = 3000


class ConnectionsView(QWidget):
    """A sortable, filterable view of every socket on the machine."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._all: list[Connection] = []
        self._task: Task | None = None

        self._build()

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        self.header = SectionHeader(
            "Connections",
            "Every open socket, matched to the process that owns it. Refreshes every 3 seconds.",
        )
        root.addWidget(self.header)

        readouts = QHBoxLayout()
        readouts.setSpacing(28)
        self.total_readout = Readout("Open sockets", Palette.text, Type.title)
        self.established_readout = Readout("Established", Palette.download, Type.title)
        self.listening_readout = Readout("Listening", Palette.upload, Type.title)
        self.external_readout = Readout("Talking to the internet", Palette.accent, Type.title)
        for widget in (
            self.total_readout,
            self.established_readout,
            self.listening_readout,
            self.external_readout,
        ):
            readouts.addWidget(widget, 1)
        root.addLayout(readouts)

        controls = QHBoxLayout()
        controls.setSpacing(9)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by process, address, port or state")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        controls.addWidget(self.search, 1)

        self.state_filter = QComboBox()
        self.state_filter.addItems(["All states", "Established", "Listening", "Closing"])
        self.state_filter.currentIndexChanged.connect(self._apply_filter)
        controls.addWidget(self.state_filter)

        self.external_only = QCheckBox("Internet only")
        self.external_only.setToolTip("Hide loopback and local network sockets")
        self.external_only.stateChanged.connect(self._apply_filter)
        controls.addWidget(self.external_only)

        self.resolve_names = QCheckBox("Resolve host names")
        self.resolve_names.setToolTip("Reverse-DNS remote addresses. Adds a short delay per refresh.")
        controls.addWidget(self.resolve_names)

        export = QLabel('<a href="#">Export CSV</a>')
        export.setStyleSheet(f"color: {Palette.download};")
        export.linkActivated.connect(self._export)
        controls.addWidget(export)

        root.addLayout(controls)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSortingEnabled(True)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFont(mono_font(Type.label))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        root.addWidget(self.table, 1)

        self.talkers = QLabel("")
        self.talkers.setFont(ui_font(Type.small))
        self.talkers.setStyleSheet(f"color: {Palette.faint};")
        root.addWidget(self.talkers)

    # -------------------------------------------------------------- refresh

    def refresh(self) -> None:
        """Collect the socket table off the UI thread."""
        if self._task is not None and self._task.isRunning():
            return

        resolve = self.resolve_names.isChecked()

        def work(task: Task) -> None:
            task.produced.emit(list_connections(resolve_names=resolve))

        self._task = Task(work, self)
        self._task.produced.connect(self._received)
        self._task.start()

    def _received(self, connections: list[Connection]) -> None:
        self._all = connections
        stats = summarise(connections)

        self.total_readout.set_text(str(stats["total"]))
        self.total_readout.set_footnote(f"across {stats['processes']} processes")
        self.established_readout.set_text(str(stats["established"]))
        self.listening_readout.set_text(str(stats["listening"]))
        self.external_readout.set_text(str(stats["external"]))

        talkers = top_talkers(connections)
        if talkers:
            summary = " · ".join(f"{name} {count}" for name, count in talkers)
            self.talkers.setText(f"Most sockets open: {summary}")
        else:
            self.talkers.setText("")

        if not connections:
            self.header.set_note(
                "No sockets visible. On macOS and Linux this view needs elevated "
                "privileges to read other users' processes."
            )

        self._apply_filter()

    # --------------------------------------------------------------- filter

    def _visible(self) -> list[Connection]:
        rows = self._all
        needle = self.search.text().strip()
        if needle:
            rows = [c for c in rows if c.matches(needle)]

        state = self.state_filter.currentText()
        if state != "All states":
            rows = [c for c in rows if c.state == state]

        if self.external_only.isChecked():
            rows = [c for c in rows if c.is_external]
        return rows

    def _apply_filter(self) -> None:
        rows = self._visible()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))

        for index, connection in enumerate(rows):
            self._set(index, 0, connection.process, ui_font(Type.label))
            self._set(index, 1, str(connection.pid or "—"))
            self._set(index, 2, connection.protocol)
            self._set(index, 3, connection.local)
            self._set(
                index, 4, connection.remote,
                colour=Palette.accent if connection.is_external else None,
            )
            self._set(index, 5, connection.state, colour=_state_colour(connection.state))

        self.table.setSortingEnabled(True)

    def _set(self, row: int, column: int, text: str, font: QFont | None = None, colour: str | None = None) -> None:
        item = QTableWidgetItem(text)
        if font is not None:
            item.setFont(font)
        if colour is not None:
            item.setForeground(QColor(colour))
        if column in (1, 2):
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, column, item)

    def _export(self) -> None:
        rows = self._visible()
        if not rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export connections", suggested_filename("connections"), "CSV files (*.csv)"
        )
        if not path:
            return
        to_csv(
            path,
            [
                {
                    "process": c.process,
                    "pid": c.pid,
                    "protocol": c.protocol,
                    "local": c.local,
                    "remote": c.remote,
                    "state": c.state,
                }
                for c in rows
            ],
        )

    def stop(self) -> None:
        self._timer.stop()
        if self._task is not None and self._task.isRunning():
            self._task.cancel()
            self._task.wait(1500)


def _state_colour(state: str) -> str | None:
    return {
        "Established": Palette.ok,
        "Listening": Palette.upload,
        "Closing": Palette.faint,
        "Connecting": Palette.warn,
    }.get(state)
