import sys
from PySide6.QtWidgets import QApplication
from viewmodels.main_window_viewmodel import MainWindowViewModel
from views.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    vm = MainWindowViewModel()
    w = MainWindow(vm)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
