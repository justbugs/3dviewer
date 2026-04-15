import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit,
                               QTextEdit, QPushButton, QDialogButtonBox,
                               QHBoxLayout, QFileDialog)
from PySide6.QtCore import Qt, QEvent, QProcess


class MarkerDialog(QDialog):
    def __init__(self, parent=None, default_label=""):
        super().__init__(parent)
        self.setWindowTitle("添加标记详情")
        self.setMinimumWidth(600)
        self.setStyleSheet("""
            QLabel { font-size: 24px; }
            QLineEdit { font-size: 24px; min-height: 54px; }
            QTextEdit { font-size: 24px; }
            QPushButton { font-size: 24px; min-height: 54px; }
            QDialogButtonBox QPushButton { font-size: 24px; min-height: 54px; min-width: 140px; }
        """)

        self._kb_process = None
        self.setAttribute(Qt.WA_InputMethodEnabled, True)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("标签名称:"))
        self.txt_label = QLineEdit(default_label)
        self.txt_label.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.txt_label.setInputMethodHints(Qt.ImhNone)
        self.txt_label.installEventFilter(self)
        layout.addWidget(self.txt_label)

        layout.addWidget(QLabel("描述信息:"))
        self.txt_desc = QTextEdit()
        self.txt_desc.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.txt_desc.setInputMethodHints(Qt.ImhNone)
        self.txt_desc.setPlaceholderText("请输入详细描述...")
        self.txt_desc.setMaximumHeight(150)
        self.txt_desc.installEventFilter(self)
        layout.addWidget(self.txt_desc)

        layout.addWidget(QLabel("关联媒体 (图片/视频/音频):"))
        h_img = QHBoxLayout()
        self.txt_img_path = QLineEdit()
        self.txt_img_path.setReadOnly(True)
        self.txt_img_path.setPlaceholderText("未选择媒体文件")

        btn_browse = QPushButton("浏览...")
        btn_browse.clicked.connect(self.browse_media)

        h_img.addWidget(self.txt_img_path)
        h_img.addWidget(btn_browse)
        layout.addLayout(h_img)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def eventFilter(self, obj, event):
        if obj in (self.txt_label, self.txt_desc) and event.type() in (QEvent.FocusIn, QEvent.MouseButtonPress):
            self._start_onboard()
        return super().eventFilter(obj, event)

    def _start_onboard(self):
        if self._kb_process is not None and self._kb_process.state() != QProcess.NotRunning:
            return
        self._kb_process = QProcess(self)
        self._kb_process.start("onboard")

    def _stop_onboard(self):
        if self._kb_process is None:
            return
        try:
            if self._kb_process.state() != QProcess.NotRunning:
                self._kb_process.terminate()
                if not self._kb_process.waitForFinished(800):
                    self._kb_process.kill()
                    self._kb_process.waitForFinished(500)
        except Exception:
            pass
        self._kb_process = None

    def closeEvent(self, event):
        self._stop_onboard()
        super().closeEvent(event)

    def done(self, r):
        self._stop_onboard()
        super().done(r)

    def browse_media(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择媒体",
            "",
            "Media Files (*.png *.jpg *.jpeg *.bmp *.mp4 *.avi *.mkv *.wav *.mp3);;Images (*.png *.jpg *.jpeg *.bmp);;Videos (*.mp4 *.avi *.mkv);;Audio (*.wav *.mp3)"
        )
        if filename:
            self.txt_img_path.setText(filename)

    def get_data(self):
        return {
            "label": self.txt_label.text().strip(),
            "desc": self.txt_desc.toPlainText().strip(),
            "image": self.txt_img_path.text().strip()
        }


class MarkerDetailsDialog(QDialog):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"详情: {data['label']}")
        self.setMinimumWidth(600)
        self.setStyleSheet("""
            QLabel { font-size: 24px; }
            QPushButton { font-size: 24px; min-height: 60px; }
        """)
        layout = QVBoxLayout(self)

        lbl_desc = QLabel(f"描述:\n{data['desc']}")
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("font-size: 24px; margin-bottom: 12px;")
        layout.addWidget(lbl_desc)

        media_path = data.get('image', '')
        if media_path and os.path.exists(media_path):
            ext = media_path.lower().split('.')[-1]
            if ext in ['png', 'jpg', 'jpeg', 'bmp']:
                from PySide6.QtGui import QPixmap
                lbl_img = QLabel()
                pix = QPixmap(media_path)
                if not pix.isNull():
                    pix = pix.scaled(400, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    lbl_img.setPixmap(pix)
                    lbl_img.setAlignment(Qt.AlignCenter)
                    layout.addWidget(lbl_img)
            else:
                lbl_media = QLabel(f"关联媒体: {os.path.basename(media_path)}")
                layout.addWidget(lbl_media)
                btn_open = QPushButton("▶️ 用系统播放器打开媒体")
                btn_open.setStyleSheet("height: 60px; font-size: 24px; font-weight: bold;")

                def _open_media():
                    try:
                        os.startfile(media_path)  # Windows
                    except Exception:
                        QProcess.startDetached("xdg-open", [media_path])  # Linux

                btn_open.clicked.connect(_open_media)
                layout.addWidget(btn_open)

        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet("height: 60px; font-size: 24px;")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

