import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen
from viewmodels.main_window_viewmodel import MainWindowViewModel
from views.main_window import MainWindow


def _build_splash() -> QSplashScreen:
    pixmap = QPixmap(420, 180)
    pixmap.fill(QColor("#f4f4f4"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.fillRect(0, 0, pixmap.width(), 6, QColor("#2f7ed8"))
    painter.setPen(QColor("#202020"))
    title_font = painter.font()
    title_font.setPointSize(15)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.drawText(24, 72, "CAN Log Viewer")

    body_font = painter.font()
    body_font.setPointSize(10)
    body_font.setBold(False)
    painter.setFont(body_font)
    painter.setPen(QColor("#505050"))
    painter.drawText(24, 104, "Starting application...")
    painter.end()

    splash = QSplashScreen(pixmap)
    splash.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    return splash


def main():
    app = QApplication(sys.argv)
    splash = _build_splash()
    splash.show()
    app.processEvents()

    vm = MainWindowViewModel()
    w = MainWindow(vm)
    w.show()
    app.processEvents()
    splash.finish(w)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
