import io
import os
import sys
import traceback

# Keep console output UTF-8 friendly when available.
if sys.stdout is not None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr is not None:
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _global_excepthook(exc_type, exc_value, exc_tb):
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print("[UNHANDLED]", msg, flush=True)


sys.excepthook = _global_excepthook

# GUI env defaults
if os.environ.get("DISPLAY") is None:
    os.environ["DISPLAY"] = ":0"
if sys.platform.startswith("linux"):
    os.environ["QT_IM_MODULE"] = "fcitx"
    os.environ["XMODIFIERS"] = "@im=fcitx"

from PySide6.QtCore import QTimer, Qt, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow


def _qt_message_handler(msg_type, context, message):
    if "DirectWrite: CreateFontFaceFromHDC() failed" in (message or ""):
        return
    print(f"[QT][{msg_type}] {message}", flush=True)


def _base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_scan_targets():
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip(), None

    scanpath_txt = os.path.join(_base_dir(), "scanpath.txt")
    if not os.path.exists(scanpath_txt):
        return None, None

    with open(scanpath_txt, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]

    if not lines:
        return None, None
    if len(lines) == 1:
        return lines[0], None
    return lines[0], lines[1]


def _force_foreground(window):
    try:
        state = window.windowState() & ~Qt.WindowMinimized
        window.setWindowState(state | Qt.WindowActive)
        window.raise_()
        window.activateWindow()
        window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        window.show()
        window.raise_()
        window.activateWindow()
        window.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        window.showMaximized()
    except Exception as e:
        print(f"[BOOT][foreground] {e}", flush=True)


if __name__ == "__main__":
    qInstallMessageHandler(_qt_message_handler)
    app = QApplication(sys.argv)
    window = MainWindow()

    scan_target, texture_target = _resolve_scan_targets()

    window.showMaximized()
    _force_foreground(window)
    QTimer.singleShot(0, lambda: _force_foreground(window))
    QTimer.singleShot(200, lambda: _force_foreground(window))

    if scan_target:
        print(f"Loading scan target: {scan_target}", flush=True)
        load_msg = "正在加载原始点云..."
        if texture_target:
            print(f"Loading texture target: {texture_target}", flush=True)
            load_msg = "正在加载原始模型和贴图..."

        def delayed_load():
            window.load_from_scan_folder(scan_target, texture_path=texture_target, loading_text=load_msg)

        # Let main window paint first, then load.
        QTimer.singleShot(200, delayed_load)

    sys.exit(app.exec())
