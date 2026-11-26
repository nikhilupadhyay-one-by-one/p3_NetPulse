"""The application window.

Navigation is a vertical rail rather than a tab strip. Each screen is a full
working surface, and the rail keeps the current one obvious without eating the
horizontal space the tables need.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..core.formatting import human_speed
from ..core.interfaces import hostname, primary_interface
from ..version import APP_NAME, __version__
from .connections_view import ConnectionsView
from .devices import DevicesView
from .diagnostics import DiagnosticsView
from .theme import Palette, Type, mono_font, ui_font
from .traffic import TrafficView

SCREENS = [
    ("Traffic", "Live download and upload rates"),
    ("Connections", "Open sockets by process"),
    ("Diagnostics", "Ping, traceroute, DNS, ports"),
    ("Devices", "Who else is on this network"),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1180, 760)
        self.setMinimumSize(920, 620)

        self.traffic = TrafficView()
        self.connections = ConnectionsView()
        self.diagnostics = DiagnosticsView()
        self.devices = DevicesView()

        self._build()
        self._build_status_bar()
        self._bind_shortcuts()

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_rail())

        self.stack = QStackedWidget()
        for view in (self.traffic, self.connections, self.diagnostics, self.devices):
            self.stack.addWidget(view)
        layout.addWidget(self.stack, 1)

        self.setCentralWidget(central)

    def _build_rail(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("NavRail")
        rail.setFixedWidth(188)

        layout = QVBoxLayout(rail)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(0)

        wordmark = QLabel(APP_NAME)
        wordmark.setObjectName("Wordmark")
        wordmark.setFont(ui_font(Type.title, QFont.Weight.DemiBold))
        layout.addWidget(wordmark)

        subtitle = QLabel(f"v{__version__} · {hostname()}")
        subtitle.setObjectName("WordmarkSub")
        layout.addWidget(subtitle)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)

        for index, (name, tooltip) in enumerate(SCREENS):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setToolTip(f"{tooltip}   (Ctrl+{index + 1})")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._nav_group.addButton(button, index)
            layout.addWidget(button)

        layout.addStretch(1)

        self.rail_note = QLabel("")
        self.rail_note.setFont(ui_font(Type.small))
        self.rail_note.setStyleSheet(f"color: {Palette.faint}; padding: 0 16px;")
        self.rail_note.setWordWrap(True)
        layout.addWidget(self.rail_note)

        self._nav_group.idClicked.connect(self._switch)
        self._nav_group.button(0).setChecked(True)
        return rail

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.setStatusBar(bar)

        self.adapter_label = QLabel("")
        self.adapter_label.setFont(ui_font(Type.small))
        bar.addWidget(self.adapter_label)

        self.rate_label = QLabel("")
        self.rate_label.setFont(mono_font(Type.small))
        bar.addPermanentWidget(self.rate_label)

        # The status bar mirrors the live rate so it stays visible on every
        # screen, not just the traffic view.
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._update_status)
        self._status_timer.start()
        self._update_status()

    def _bind_shortcuts(self) -> None:
        for index in range(len(SCREENS)):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda i=index: self._select(i))
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self.traffic.refresh_interfaces)
        QShortcut(QKeySequence.StandardKey.Quit, self).activated.connect(self.close)

    # ----------------------------------------------------------- interaction

    def _select(self, index: int) -> None:
        button = self._nav_group.button(index)
        if button is not None:
            button.setChecked(True)
        self._switch(index)

    def _switch(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.rail_note.setText(SCREENS[index][1])

    def _update_status(self) -> None:
        nic = primary_interface()
        if nic is None:
            self.adapter_label.setText("No active network adapter")
            self.rate_label.setText("")
            return

        self.adapter_label.setText(f"{nic.name} · {nic.ipv4 or 'no address'} · {nic.status}")
        sample = self.traffic.monitor.latest
        if sample is None:
            self.rate_label.setText("measuring…")
            return
        self.rate_label.setText(
            f"↓ {human_speed(sample.down_bps)}    ↑ {human_speed(sample.up_bps)}"
        )

    def closeEvent(self, event) -> None:
        """Wind down every background thread before the window disappears."""
        self._status_timer.stop()
        for view in (self.traffic, self.connections, self.diagnostics, self.devices):
            view.stop()
        super().closeEvent(event)
