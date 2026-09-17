"""The four diagnostic tools, each parsing its results into a table.

Every tool follows the same shape: a target row at the top, a Run button that
becomes a Stop button, and results that appear as they arrive rather than in one
batch at the end. The work happens on a :class:`Task` thread so the window never
freezes mid-trace.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import dns_tools, ping, portscan, traceroute
from ..core.export import suggested_filename, to_csv
from ..core.formatting import human_latency
from .theme import Palette, Type, mono_font, ui_font
from .widgets import Panel, Readout, SectionHeader, Sparkline, Task


class DiagnosticsView(QWidget):
    """Container for the individual tools."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        root.addWidget(
            SectionHeader(
                "Diagnostics",
                "Results are parsed into structured readings, not dumped as console text.",
            )
        )

        self.tabs = QTabWidget()
        self.ping_panel = PingPanel()
        self.trace_panel = TracePanel()
        self.dns_panel = DnsPanel()
        self.ports_panel = PortsPanel()

        self.tabs.addTab(self.ping_panel, "Ping")
        self.tabs.addTab(self.trace_panel, "Traceroute")
        self.tabs.addTab(self.dns_panel, "DNS")
        self.tabs.addTab(self.ports_panel, "Port scan")
        root.addWidget(self.tabs, 1)

    def stop(self) -> None:
        for panel in (self.ping_panel, self.trace_panel, self.dns_panel, self.ports_panel):
            panel.stop()


class ToolPanel(QWidget):
    """Shared behaviour: a target row, run/stop handling, and status text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task: Task | None = None

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 12, 0, 0)
        self.root.setSpacing(12)

        self.controls = QHBoxLayout()
        self.controls.setSpacing(9)
        self.root.addLayout(self.controls)

        self.target = QLineEdit()
        self.target.setPlaceholderText("Host name or IP address")
        self.target.returnPressed.connect(self._run_clicked)
        self.controls.addWidget(self.target, 1)

        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("Primary")
        self.run_button.clicked.connect(self._run_clicked)

        self.status = QLabel("")
        self.status.setFont(ui_font(Type.label))
        self.status.setStyleSheet(f"color: {Palette.muted};")

    def finish_controls(self) -> None:
        """Call once subclasses have added their own control widgets."""
        self.controls.addWidget(self.run_button)

    @property
    def running(self) -> bool:
        return self._task is not None and self._task.isRunning()

    def _run_clicked(self) -> None:
        if self.running:
            self.stop()
            return
        host = self.target.text().strip()
        if not host:
            self.set_status("Enter a host name or IP address to continue.", Palette.warn)
            self.target.setFocus()
            return
        self.start(host)

    def start(self, host: str) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def launch(self, work) -> None:
        """Run ``work`` on a background thread and flip the button to Stop."""
        self._task = Task(work, self)
        self._task.failed.connect(lambda message: self.set_status(message, Palette.alert))
        self._task.completed.connect(self._task_finished)
        self.run_button.setText("Stop")
        self.run_button.setObjectName("Danger")
        self._restyle(self.run_button)
        self._task.start()

    def _task_finished(self) -> None:
        self.run_button.setText("Run")
        self.run_button.setObjectName("Primary")
        self._restyle(self.run_button)
        self.on_finished()

    def on_finished(self) -> None:
        """Hook for subclasses; the default does nothing."""

    def stop(self) -> None:
        if self._task is not None and self._task.isRunning():
            self._task.cancel()
            self._task.wait(2500)

    def set_status(self, text: str, colour: str = Palette.muted) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {colour};")

    @staticmethod
    def _restyle(widget: QWidget) -> None:
        # Qt only re-evaluates the stylesheet when the object name changes if
        # the style is explicitly refreshed.
        widget.style().unpolish(widget)
        widget.style().polish(widget)


def make_table(columns: list[str], stretch: int = 0) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setFont(mono_font(Type.label))

    header = table.horizontalHeader()
    for column in range(len(columns)):
        mode = (
            QHeaderView.ResizeMode.Stretch
            if column == stretch
            else QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionResizeMode(column, mode)
    return table


def cell(text: str, colour: str | None = None, centre: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if colour:
        item.setForeground(QColor(colour))
    if centre:
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


# --------------------------------------------------------------------------- #
# Ping
# --------------------------------------------------------------------------- #


class PingPanel(ToolPanel):
    """Continuous ping with latency trace, loss counter and jitter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stats = ping.PingStats()

        self.count = QSpinBox()
        self.count.setRange(0, 10000)
        self.count.setValue(0)
        self.count.setSpecialValueText("Continuous")
        self.count.setToolTip("Number of requests to send. Zero runs until you stop it.")
        self.count.setPrefix("Count  ")
        self.controls.addWidget(self.count)

        self.interval = QSpinBox()
        self.interval.setRange(200, 10000)
        self.interval.setSingleStep(100)
        self.interval.setValue(1000)
        self.interval.setSuffix(" ms")
        self.interval.setPrefix("Every  ")
        self.controls.addWidget(self.interval)

        self.finish_controls()

        readouts = QHBoxLayout()
        readouts.setSpacing(24)
        self.latest = Readout("Latest", Palette.download, Type.title)
        self.average = Readout("Average", Palette.text, Type.title)
        self.jitter = Readout("Jitter", Palette.upload, Type.title)
        self.loss = Readout("Packet loss", Palette.ok, Type.title)
        for widget in (self.latest, self.average, self.jitter, self.loss):
            readouts.addWidget(widget, 1)
        self.root.addLayout(readouts)

        trace = Panel(padding=12)
        self.sparkline = Sparkline(Palette.download)
        trace.body().addWidget(self.sparkline)
        self.root.addWidget(trace)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono_font(Type.label))
        self.log.setMaximumBlockCount(500)
        self.root.addWidget(self.log, 1)

        self.root.addWidget(self.status)

    def start(self, host: str) -> None:
        self.stats = ping.PingStats()
        self.sparkline.clear()
        self.log.clear()
        self.set_status(f"Pinging {host}…")

        count = self.count.value() or None
        interval = self.interval.value() / 1000

        def work(task: Task) -> None:
            for reply in ping.ping_stream(
                host, count=count, interval=interval, stop=task.stop_event
            ):
                task.produced.emit(reply)

        self.launch(work)
        self._task.produced.connect(self._reply)

    def _reply(self, reply: ping.Reply) -> None:
        self.stats.add(reply)
        self.sparkline.push(reply.rtt_ms if reply.success else None)
        self.log.appendPlainText(str(reply))

        self.latest.set_text(*_latency_parts(reply.rtt_ms if reply.success else None))
        self.average.set_text(*_latency_parts(self.stats.average))
        self.jitter.set_text(*_latency_parts(self.stats.jitter))

        loss = self.stats.loss_pct
        self.loss.set_text(f"{loss:.0f}", "%")
        self.loss.set_accent(
            Palette.ok if loss == 0 else Palette.warn if loss < 5 else Palette.alert
        )
        self.loss.set_footnote(f"{self.stats.lost} of {self.stats.sent} lost")
        self.latest.set_footnote(f"connection quality: {self.stats.quality.lower()}")

    def on_finished(self) -> None:
        if self.stats.sent:
            self.set_status(
                f"{self.stats.received} of {self.stats.sent} replies · "
                f"min {human_latency(self.stats.minimum)} · "
                f"max {human_latency(self.stats.maximum)} · "
                f"{self.stats.quality.lower()}"
            )


def _latency_parts(value: float | None) -> tuple[str, str]:
    if value is None:
        return "—", ""
    text = human_latency(value)
    number, _, unit = text.partition(" ")
    return number, unit


# --------------------------------------------------------------------------- #
# Traceroute
# --------------------------------------------------------------------------- #


class TracePanel(ToolPanel):
    """Hop-by-hop path to a destination."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hops: list[traceroute.Hop] = []

        self.max_hops = QSpinBox()
        self.max_hops.setRange(5, 64)
        self.max_hops.setValue(30)
        self.max_hops.setPrefix("Max hops  ")
        self.controls.addWidget(self.max_hops)

        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self._export)
        self.controls.addWidget(self.export_button)

        self.finish_controls()

        self.table = make_table(["Hop", "Address", "Host name", "Best", "Average", "Network"], stretch=2)
        self.root.addWidget(self.table, 1)
        self.root.addWidget(self.status)

    def start(self, host: str) -> None:
        self._hops = []
        self.table.setRowCount(0)
        self.set_status(f"Tracing the route to {host}. This can take up to a minute.")

        max_hops = self.max_hops.value()

        def work(task: Task) -> None:
            for hop in traceroute.trace(host, max_hops=max_hops, stop=task.stop_event):
                task.produced.emit(hop)

        self.launch(work)
        self._task.produced.connect(self._hop)

    def _hop(self, hop: traceroute.Hop) -> None:
        self._hops.append(hop)
        row = self.table.rowCount()
        self.table.insertRow(row)

        timed_out = hop.timed_out or hop.average is None
        colour = Palette.faint if timed_out else None
        network = "—" if not hop.address else ("Local network" if hop.is_private else "Internet")

        self.table.setItem(row, 0, cell(str(hop.number), colour, centre=True))
        self.table.setItem(row, 1, cell(hop.address or "no response", colour))
        self.table.setItem(row, 2, cell(hop.hostname or "—", colour or Palette.muted))
        self.table.setItem(row, 3, cell(human_latency(hop.best), colour))
        self.table.setItem(row, 4, cell(human_latency(hop.average), colour))
        self.table.setItem(
            row, 5,
            cell(network, Palette.faint if timed_out else (Palette.upload if hop.is_private else Palette.download)),
        )
        self.table.scrollToBottom()

    def on_finished(self) -> None:
        answered = [h for h in self._hops if h.average is not None]
        if not self._hops:
            self.set_status("No hops returned. The host may be unreachable or blocking probes.", Palette.warn)
            return
        last = answered[-1] if answered else None
        self.set_status(
            f"{len(self._hops)} hops · {len(answered)} answered"
            + (f" · {human_latency(last.average)} to the far end" if last else "")
        )

    def _export(self) -> None:
        if not self._hops:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export route", suggested_filename("traceroute"), "CSV files (*.csv)"
        )
        if not path:
            return
        to_csv(
            path,
            [
                {
                    "hop": h.number,
                    "address": h.address or "",
                    "hostname": h.hostname or "",
                    "best_ms": round(h.best, 2) if h.best else "",
                    "average_ms": round(h.average, 2) if h.average else "",
                }
                for h in self._hops
            ],
        )


# --------------------------------------------------------------------------- #
# DNS
# --------------------------------------------------------------------------- #


class DnsPanel(ToolPanel):
    """Record lookups against the system resolver."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.record_type = QComboBox()
        self.record_type.addItems(dns_tools.available_types())
        self.controls.addWidget(self.record_type)
        self.finish_controls()

        self.table = make_table(["Type", "Value", "TTL"], stretch=1)
        self.root.addWidget(self.table, 1)

        note = "Resolvers in use: " + (", ".join(dns_tools.resolver_addresses()) or "system default")
        if not dns_tools.HAS_DNSPYTHON:
            note += "  ·  install dnspython for MX, NS, TXT and SOA records"
        self.set_status(note)
        self.root.addWidget(self.status)

    def start(self, host: str) -> None:
        self.table.setRowCount(0)
        record_type = self.record_type.currentText()
        self.set_status(f"Looking up {record_type} records for {host}…")

        def work(task: Task) -> None:
            task.produced.emit(dns_tools.lookup(host, record_type))

        self.launch(work)
        self._task.produced.connect(self._records)

    def _records(self, records: list[dns_tools.Record]) -> None:
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            self.table.setItem(row, 0, cell(record.type, Palette.download, centre=True))
            self.table.setItem(row, 1, cell(record.value))
            self.table.setItem(row, 2, cell(f"{record.ttl}s" if record.ttl else "—", Palette.muted, centre=True))
        plural = "record" if len(records) == 1 else "records"
        self.set_status(f"{len(records)} {plural} returned.", Palette.ok)


# --------------------------------------------------------------------------- #
# Port scan
# --------------------------------------------------------------------------- #


class PortsPanel(ToolPanel):
    """Concurrent TCP connect scan."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._results: list[portscan.PortResult] = []

        self.ports = QLineEdit(",".join(str(p) for p in portscan.QUICK_SCAN_PORTS[:20]))
        self.ports.setPlaceholderText("22,80,443,8000-8100")
        self.ports.setToolTip("Individual ports and ranges, separated by commas")
        self.ports.setMinimumWidth(220)
        self.controls.addWidget(self.ports, 1)

        self.preset = QComboBox()
        self.preset.addItems(["Common ports", "Top 1024", "Web ports", "Everything"])
        self.preset.currentTextChanged.connect(self._preset_changed)
        self.controls.addWidget(self.preset)

        self.finish_controls()

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.root.addWidget(self.progress)

        self.table = make_table(["Port", "Service", "Response", "Banner"], stretch=3)
        self.root.addWidget(self.table, 1)

        self.set_status(
            "Scan only hosts you own or have permission to test. "
            "Port scanning other people's systems can be unlawful."
        )
        self.root.addWidget(self.status)

    def _preset_changed(self, name: str) -> None:
        presets = {
            "Common ports": ",".join(str(p) for p in portscan.QUICK_SCAN_PORTS),
            "Top 1024": "1-1024",
            "Web ports": "80,443,3000,5000,8000,8008,8080,8443,8888,9000,9090",
            "Everything": "1-65535",
        }
        self.ports.setText(presets.get(name, self.ports.text()))

    def start(self, host: str) -> None:
        try:
            ports = portscan.parse_port_range(self.ports.text())
        except ValueError as exc:
            self.set_status(str(exc), Palette.alert)
            return

        self._results = []
        self.table.setRowCount(0)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(ports))
        self.progress.setValue(0)
        self.set_status(f"Scanning {len(ports):,} ports on {host}…")

        def work(task: Task) -> None:
            portscan.scan(
                host,
                ports,
                grab_banner=True,
                on_result=task.produced.emit,
                on_progress=lambda done, total: task.progressed.emit(done, total),
                stop=task.stop_event,
            )

        self.launch(work)
        self._task.produced.connect(self._found)
        self._task.progressed.connect(self._progress)

    def _progress(self, done: int, total: int) -> None:
        self.progress.setValue(done)

    def _found(self, result: portscan.PortResult) -> None:
        self._results.append(result)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, cell(str(result.port), Palette.ok, centre=True))
        self.table.setItem(row, 1, cell(result.service))
        self.table.setItem(row, 2, cell(human_latency(result.latency_ms), Palette.muted, centre=True))
        self.table.setItem(row, 3, cell(result.banner or "—", Palette.muted))

    def on_finished(self) -> None:
        self.progress.setVisible(False)
        count = len(self._results)
        if count == 0:
            self.set_status("No open ports found in that range.")
        else:
            listed = ", ".join(str(r.port) for r in sorted(self._results, key=lambda r: r.port)[:12])
            self.set_status(f"{count} open: {listed}" + (" …" if count > 12 else ""), Palette.ok)
