"""The live traffic screen.

This is the first thing the app shows, and the chart is the centre of it: the
adapter picker and the numeric readouts sit around it rather than competing
with it for attention.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.bandwidth import ALL_INTERFACES, BandwidthMonitor
from ..core.export import suggested_filename, to_csv
from ..core.formatting import human_bits, human_bytes, human_duration, human_speed
from ..core.interfaces import Interface, hostname, list_interfaces, primary_interface
from .theme import Palette, Type
from .widgets import FactGrid, Panel, Readout, SectionHeader, TrafficChart

WINDOW_SECONDS = 120
SAMPLE_INTERVAL_MS = 1000


class TrafficView(QWidget):
    """Real-time download and upload rates for one adapter or the whole machine."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.monitor = BandwidthMonitor(ALL_INTERFACES, history=WINDOW_SECONDS)
        self._interfaces: list[Interface] = []

        self._build()
        self.refresh_interfaces()

        self._timer = QTimer(self)
        self._timer.setInterval(SAMPLE_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        # Re-read adapter details less often; they rarely change.
        self._details_timer = QTimer(self)
        self._details_timer.setInterval(5000)
        self._details_timer.timeout.connect(self._update_details)
        self._details_timer.start()

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        self.header = SectionHeader(
            "Live traffic",
            f"Reading adapter byte counters on {hostname()} once a second.",
        )
        header_row.addWidget(self.header, 1)

        self.adapter_picker = QComboBox()
        self.adapter_picker.setMinimumWidth(210)
        self.adapter_picker.currentIndexChanged.connect(self._adapter_changed)
        header_row.addWidget(self.adapter_picker, 0, Qt.AlignmentFlag.AlignBottom)

        self.reset_button = QPushButton("Reset session")
        self.reset_button.clicked.connect(self._reset)
        header_row.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignBottom)

        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self._export)
        header_row.addWidget(self.export_button, 0, Qt.AlignmentFlag.AlignBottom)

        root.addLayout(header_row)

        self.chart = TrafficChart()
        self.chart.set_capacity(WINDOW_SECONDS)
        root.addWidget(self.chart, 1)

        root.addLayout(self._build_readouts())
        root.addLayout(self._build_lower(), 0)

    def _build_readouts(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(28)
        row.setContentsMargins(2, 4, 2, 4)

        self.download_readout = Readout("Download", Palette.download)
        self.upload_readout = Readout("Upload", Palette.upload)
        self.session_readout = Readout("Transferred this session", Palette.text, Type.title)
        self.peak_readout = Readout("Peak rate", Palette.muted, Type.title)

        for widget in (
            self.download_readout,
            self.upload_readout,
            self.session_readout,
            self.peak_readout,
        ):
            row.addWidget(widget, 1)
        return row

    def _build_lower(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        adapter_panel = Panel()
        adapter_panel.body().addWidget(SectionHeader("Adapter"))
        self.adapter_facts = FactGrid()
        for label in ("Status", "IPv4 address", "Subnet", "MAC address", "Link speed", "MTU"):
            self.adapter_facts.add(label, monospace=label != "Status")
        adapter_panel.body().addWidget(self.adapter_facts)
        adapter_panel.body().addStretch(1)
        row.addWidget(adapter_panel, 1)

        session_panel = Panel()
        session_panel.body().addWidget(SectionHeader("Session"))
        self.session_facts = FactGrid()
        for label in (
            "Running for", "Received", "Sent",
            "Average down", "Average up", "Line rate now",
        ):
            self.session_facts.add(label, monospace=True)
        session_panel.body().addWidget(self.session_facts)
        session_panel.body().addStretch(1)
        row.addWidget(session_panel, 1)

        return row

    # ----------------------------------------------------------- interaction

    def refresh_interfaces(self) -> None:
        """Rebuild the adapter list, keeping the current choice if it survives."""
        previous = self.adapter_picker.currentData()
        self._interfaces = list_interfaces()

        self.adapter_picker.blockSignals(True)
        self.adapter_picker.clear()
        self.adapter_picker.addItem("All interfaces", ALL_INTERFACES)
        for nic in self._interfaces:
            suffix = f"  ({nic.ipv4})" if nic.ipv4 else ""
            self.adapter_picker.addItem(f"{nic.name}{suffix}", nic.name)

        target = previous
        if target is None:
            active = primary_interface()
            target = active.name if active else ALL_INTERFACES

        index = self.adapter_picker.findData(target)
        self.adapter_picker.setCurrentIndex(index if index >= 0 else 0)
        self.adapter_picker.blockSignals(False)

        self.monitor.set_interface(self.adapter_picker.currentData() or ALL_INTERFACES)
        self._update_details()

    def _adapter_changed(self) -> None:
        name = self.adapter_picker.currentData() or ALL_INTERFACES
        self.monitor.set_interface(name)
        self.chart.clear()
        self._update_details()

    def _reset(self) -> None:
        self.monitor.reset()
        self.chart.clear()
        self._update_details()

    def _export(self) -> None:
        if not self.monitor.history:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export traffic samples", suggested_filename("traffic"), "CSV files (*.csv)"
        )
        if not path:
            return
        rows = [
            {
                "seconds_ago": round(offset),
                "download_bytes_per_sec": round(down),
                "upload_bytes_per_sec": round(up),
            }
            for offset, down, up in zip(*self.monitor.series(), strict=True)
        ]
        to_csv(path, rows)

    # -------------------------------------------------------------- sampling

    def _tick(self) -> None:
        sample = self.monitor.sample()
        if sample is None:
            return

        self.chart.push(sample.down_bps, sample.up_bps)
        self.download_readout.set_speed(sample.down_bps)
        self.download_readout.set_footnote(human_bits(sample.down_bps))
        self.upload_readout.set_speed(sample.up_bps)
        self.upload_readout.set_footnote(human_bits(sample.up_bps))

        total = sample.session_down + sample.session_up
        self.session_readout.set_text(*_split(human_bytes(total)))
        self.session_readout.set_footnote(
            f"{human_bytes(sample.session_down)} in · {human_bytes(sample.session_up)} out"
        )

        peak = max(self.monitor.peak_down, self.monitor.peak_up)
        self.peak_readout.set_text(*_split(human_speed(peak)))
        self.peak_readout.set_footnote(
            f"{human_speed(self.monitor.peak_down)} down · {human_speed(self.monitor.peak_up)} up"
        )

        self._update_session_facts(sample)

    def _update_session_facts(self, sample) -> None:
        average_down, average_up = self.monitor.average()
        self.session_facts.set("Running for", human_duration(self.monitor.elapsed))
        self.session_facts.set("Received", human_bytes(sample.session_down), Palette.download)
        self.session_facts.set("Sent", human_bytes(sample.session_up), Palette.upload)
        self.session_facts.set("Average down", human_speed(average_down))
        self.session_facts.set("Average up", human_speed(average_up))
        self.session_facts.set("Line rate now", human_bits(sample.down_bps + sample.up_bps))

    def _update_details(self) -> None:
        name = self.adapter_picker.currentData() or ALL_INTERFACES
        if name == ALL_INTERFACES:
            active = primary_interface()
            self.adapter_facts.set("Status", "Every adapter combined", Palette.muted)
            self.adapter_facts.set("IPv4 address", active.ipv4 if active and active.ipv4 else "—")
            self.adapter_facts.set("Subnet", active.cidr if active and active.cidr else "—")
            self.adapter_facts.set("MAC address", active.mac if active and active.mac else "—")
            self.adapter_facts.set("Link speed", "—")
            self.adapter_facts.set("MTU", "—")
            return

        nic = next((i for i in self._interfaces if i.name == name), None)
        if nic is None:
            self._interfaces = list_interfaces()
            nic = next((i for i in self._interfaces if i.name == name), None)
        if nic is None:
            return

        self.adapter_facts.set(
            "Status", nic.status, Palette.ok if nic.is_up else Palette.alert
        )
        self.adapter_facts.set("IPv4 address", nic.ipv4 or "—")
        self.adapter_facts.set("Subnet", nic.cidr or "—")
        self.adapter_facts.set("MAC address", nic.mac or "—")
        self.adapter_facts.set(
            "Link speed", f"{nic.speed_mbps} Mbps" if nic.speed_mbps else "Not reported"
        )
        self.adapter_facts.set("MTU", str(nic.mtu) if nic.mtu else "—")

    def stop(self) -> None:
        self._timer.stop()
        self._details_timer.stop()


def _split(text: str) -> tuple[str, str]:
    value, _, unit = text.partition(" ")
    return value, unit
