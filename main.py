import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen
from config.app_config import get_option
from config.theme import DEFAULT_THEME, apply_theme
from config.version import APP_VERSION
from services.app_logging import configure_logging
from services.app_paths import resolve_state_dir
from services.session_state import SessionStateStore
from viewmodels.main_window_viewmodel import MainWindowViewModel
from views.icons import app_icon
from views.main_window import MainWindow

logger = logging.getLogger(__name__)


def _build_splash() -> QSplashScreen:
    pixmap = QPixmap(420, 180)
    pixmap.fill(QColor("#f4f4f4"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.fillRect(0, 0, pixmap.width(), 6, QColor("#2f7ed8"))

    logo = app_icon().pixmap(96, 96)
    painter.drawPixmap(28, 42, logo)

    painter.setPen(QColor("#202020"))
    title_font = painter.font()
    title_font.setPointSize(15)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(148, 88, "Canlytics")

    body_font = painter.font()
    body_font.setPointSize(10)
    body_font.setBold(False)
    painter.setFont(body_font)
    painter.setPen(QColor("#505050"))
    painter.drawText(148, 114, "Starting application...")
    painter.end()

    splash = QSplashScreen(pixmap)
    splash.setWindowFlag(Qt.FramelessWindowHint, True)
    splash.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    return splash


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Canlytics")
    app.setApplicationDisplayName("Canlytics")
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(app_icon())
    try:
        session_state = SessionStateStore()
        debug_enabled = session_state.get_debug_mode()
        qt_log_handler = configure_logging(
            session_state.root, level=logging.DEBUG if debug_enabled else logging.INFO
        )
    except Exception as exc:
        print(f"Canlytics startup logging/state setup failed: {exc}", file=sys.stderr)
        logging.basicConfig(stream=sys.stderr, level=logging.INFO)
        session_state = SessionStateStore(root=resolve_state_dir())
        qt_log_handler = None
    logger.info("Canlytics v%s starting", APP_VERSION)
    try:
        saved_theme = session_state.get_theme()
    except Exception as exc:
        logger.exception("Could not read saved theme; using default: %s", exc)
        saved_theme = None
    apply_theme(app, saved_theme or get_option("theme", DEFAULT_THEME))
    splash = _build_splash()
    splash.show()
    app.processEvents()

    vm = MainWindowViewModel(
        qt_log_handler=qt_log_handler, enable_mcp_session=True, session_state=session_state
    )
    w = MainWindow(vm)
    w.show()
    app.processEvents()
    splash.finish(w)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
