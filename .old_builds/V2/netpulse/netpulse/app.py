"""GUI entry point."""

from __future__ import annotations

import sys


def main() -> int:
    """Start the desktop application."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write(
            "NetPulse needs PySide6 for the desktop interface.\n"
            "Install it with:  pip install -r requirements.txt\n"
            "Or run the terminal version instead:  python -m netpulse --cli\n"
        )
        return 1

    from .ui.main_window import MainWindow
    from .ui.theme import stylesheet, ui_font
    from .version import APP_NAME, __version__

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(ui_font())
    app.setStyleSheet(stylesheet())

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
