"""Who else is on this network.

The sweep pings every address in the subnet at once, then reads the ARP cache
those pings just populated to pick up hardware addresses. Vendor names come from
the bundled OUI table, so discovery works with no internet connection.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.export import suggested_filename, to_csv
from ..core.formatting import human_latency
from ..core.interfaces import hostname
from ..core.lanscan import Device, default_gateway, default_subnet, sweep
from .diagnostics import cell, make_table
from .theme import Palette, Type
from .widgets import Readout, SectionHeader, Task


class DevicesView(QWidget):
    """Local network discovery."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task: Task | None = None
        self._devices: list[Device] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        self.header = SectionHeader(
            "Devices",
            "Sweeps your subnet, then reads the ARP cache to identify what answered.",
        )
        root.addWidget(self.header)

        readouts = QHBoxLayout()
        readouts.setSpacing(28)
        self.found_readout = Readout("Devices found", Palette.download, Type.title)
        self.identified_readout = Readout("Vendor identified", Palette.text, Type.title)
        self.gateway_readout = Readout("Router", Palette.upload, Type.title)
        self.self_readout = Readout("This computer", Palette.accent, Type.title)
        for widget in (
            self.found_readout,
            self.identified_readout,
            self.gateway_readout,
            self.self_readout,
        ):
            readouts.addWidget(widget, 1)
        root.addLayout(readouts)

        controls = QHBoxLayout()
        controls.setSpacing(9)

        self.subnet = QLineEdit(default_subnet() or "192.168.1.0/24")
        self.subnet.setPlaceholderText("192.168.1.0/24")
        self.subnet.returnPressed.connect(self._toggle)
        controls.addWidget(self.subnet, 1)

        self.scan_button = QPushButton("Scan network")
        self.scan_button.setObjectName("Primary")
        self.scan_button.clicked.connect(self._toggle)
        controls.addWidget(self.scan_button)

        self.export_button = QPushButton("Export CSV")
        self.export_button.clicked.connect(self._export)
        controls.addWidget(self.export_button)

        root.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.table = make_table(
            ["IP address", "Host name", "MAC address", "Vendor", "Response", "Role"], stretch=1
        )
        root.addWidget(self.table, 1)

        self.status = self.header.note
        self._set_defaults()

    # ------------------------------------------------------------------ scan

    def _set_defaults(self) -> None:
        gateway = default_gateway()
        self.gateway_readout.set_text(gateway or "—")
        self.self_readout.set_text(hostname())
        self.found_readout.set_text("0")
        self.identified_readout.set_text("0")

    @property
    def running(self) -> bool:
        return self._task is not None and self._task.isRunning()

    def _toggle(self) -> None:
        if self.running:
            self._task.cancel()
            return
        self._start()

    def _start(self) -> None:
        subnet = self.subnet.text().strip()
        self._devices = []
        self.table.setRowCount(0)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.header.set_note(f"Sweeping {subnet}. Most home networks take under a minute.")

        def work(task: Task) -> None:
            sweep(
                subnet,
                on_device=task.produced.emit,
                on_progress=lambda done, total: task.progressed.emit(done, total),
                stop=task.stop_event,
            )

        self._task = Task(work, self)
        self._task.produced.connect(self._device)
        self._task.progressed.connect(self._progress)
        self._task.failed.connect(self._failed)
        self._task.completed.connect(self._finished)

        self.scan_button.setText("Stop")
        self.scan_button.setObjectName("Danger")
        self.scan_button.style().unpolish(self.scan_button)
        self.scan_button.style().polish(self.scan_button)
        self._task.start()

    def _progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def _device(self, device: Device) -> None:
        self._devices.append(device)
        row = self.table.rowCount()
        self.table.insertRow(row)

        accent = (
            Palette.accent if device.is_self
            else Palette.upload if device.is_gateway
            else None
        )
        vendor = device.vendor or "Unknown"

        self.table.setItem(row, 0, cell(device.ip, accent))
        self.table.setItem(row, 1, cell(device.hostname or "—", accent or Palette.muted))
        self.table.setItem(row, 2, cell(device.mac or "not in ARP cache", Palette.muted))
        self.table.setItem(
            row, 3, cell(vendor, Palette.faint if vendor in ("Unknown", "Randomised MAC") else None)
        )
        self.table.setItem(row, 4, cell(human_latency(device.rtt_ms), Palette.muted, centre=True))
        self.table.setItem(row, 5, cell(device.role, accent or (Palette.faint if device.role == '—' else None)))

        self.found_readout.set_text(str(len(self._devices)))
        identified = sum(
            1 for d in self._devices if d.vendor and d.vendor not in ("Unknown", "Randomised MAC")
        )
        self.identified_readout.set_text(str(identified))

    def _failed(self, message: str) -> None:
        self.header.set_note(message)

    def _finished(self) -> None:
        self.progress.setVisible(False)
        self.scan_button.setText("Scan network")
        self.scan_button.setObjectName("Primary")
        self.scan_button.style().unpolish(self.scan_button)
        self.scan_button.style().polish(self.scan_button)

        count = len(self._devices)
        if count:
            self.header.set_note(
                f"{count} device{'s' if count != 1 else ''} answered on {self.subnet.text().strip()}. "
                "Phones often randomise their MAC address, so some vendors stay unknown."
            )
        elif self._task is not None and self._task.cancelled:
            self.header.set_note("Scan stopped.")
        else:
            self.header.set_note(
                "Nothing answered. Many devices ignore ping by default, and some "
                "networks block it between clients."
            )

    def _export(self) -> None:
        if not self._devices:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export devices", suggested_filename("devices"), "CSV files (*.csv)"
        )
        if not path:
            return
        to_csv(
            path,
            [
                {
                    "ip": d.ip,
                    "hostname": d.hostname or "",
                    "mac": d.mac or "",
                    "vendor": d.vendor or "",
                    "rtt_ms": round(d.rtt_ms, 2) if d.rtt_ms else "",
                    "role": d.label,
                }
                for d in self._devices
            ],
        )

    def stop(self) -> None:
        if self.running:
            self._task.cancel()
            self._task.wait(3000)
