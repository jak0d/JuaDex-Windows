"""Application startup and the global error boundary."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .logging_config import configure_logging
from .settings import APPLICATION, DISPLAY_NAME, ORGANISATION
from .ui.theme import apply_theme

logger = logging.getLogger(__name__)


def _install_exception_hook(app: QApplication) -> None:
    """Show a dialog instead of dying silently on an unhandled exception."""

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):  # pragma: no cover
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_tb)
        )
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("Unexpected error")
            box.setText(
                "JuaDex PDFs Separator ran into an unexpected problem.\n\n"
                "Your source PDFs have not been changed. You can continue working, "
                "but it is safer to restart the application."
            )
            box.setDetailedText(details)
            box.exec()
        except Exception:  # pragma: no cover - GUI already broken
            print(details, file=sys.stderr)

    sys.excepthook = hook


def create_application(argv: list[str] | None = None) -> QApplication:
    """Create and configure the QApplication."""

    argv = list(argv if argv is not None else sys.argv)

    # High-DPI: Qt 6 scales automatically; request per-monitor rounding that
    # keeps text crisp at 125% and 150%.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APPLICATION)
    app.setOrganizationName(ORGANISATION)
    app.setApplicationVersion(__version__)
    app.setApplicationDisplayName(DISPLAY_NAME)
    apply_theme(app)

    icon_path = Path(__file__).parent / "resources" / "app.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    return app


def main(argv: list[str] | None = None) -> int:
    """Entry point used by the console script and the packaged executable."""

    log_path = configure_logging()
    logger.info("Starting %s %s", DISPLAY_NAME, __version__)
    if log_path:
        logger.debug("Logging to %s", log_path)

    app = create_application(argv)
    _install_exception_hook(app)

    # Imported late so a UI import error is caught by the hook above.
    from .ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
