import sys
import os

# 远程开发 GUI 修复
if os.environ.get('DISPLAY') is None:
    os.environ['DISPLAY'] = ':0'

from PySide6.QtWidgets import QApplication
from gui.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())