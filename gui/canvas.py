# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QFrame, QVBoxLayout
from PySide6.QtCore import Qt, QEvent, QObject
from pyvistaqt import QtInteractor
import os

# Find a Chinese-capable font once at import time (used by save_side_view and vtk labels)
_FONT_PATH = None
_SEARCH_PATHS = [
    r'C:\Windows\Fonts\msyh.ttc',
    r'C:\Windows\Fonts\simhei.ttf',
    r'C:\Windows\Fonts\simsun.ttc',
    # Linux / ARM common paths (RK3588 Ubuntu/Debian)
    '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    '/usr/share/fonts/wqy-microhei/wqy-microhei.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
]

for _f in _SEARCH_PATHS:
    if os.path.exists(_f):
        _FONT_PATH = _f
        print(f"[FONT] Loaded Chinese-capable font: {_f}")
        break

if not _FONT_PATH:
    print("[FONT] WARNING: No suitable Chinese-capable font found. Labels might not render correctly on Linux.")


# --- 手势过滤器 ---
class ZoomEventFilter(QObject):
    def __init__(self, plotter):
        super().__init__()
        self.plotter = plotter
        self.last_scale = 1.0

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Gesture:
            return self.handle_gesture(event)
        if event.type() in [QEvent.TouchBegin, QEvent.TouchEnd, QEvent.TouchCancel]:
            self.last_scale = 1.0
        return False

    def handle_gesture(self, event):
        gesture = event.gesture(Qt.PinchGesture)
        if gesture:
            change_factor = gesture.scaleFactor()
            if abs(change_factor - 1.0) < 0.005: return True
            self.plotter.camera.Dolly(change_factor)
            self.plotter.renderer.ResetCameraClippingRange()
            self.plotter.render()
            return True
        return False


# --- 主画布类 ---
class PointCloudCanvas(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_AcceptTouchEvents, True)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        self.plotter = QtInteractor(self)
        self.plotter.set_background("black")

        # 角落方向标识（ASCII 标签 — VTK 默认字体不支持 CJK，截图时用 PIL 叠加中文）
        self.plotter.add_axes(
            xlabel='E', ylabel='N', zlabel='Z',
            color='white',
            viewport=(0.8, 0.0, 1.0, 0.2)
        )

        self.plotter.enable_trackball_style()
        if hasattr(self.plotter.render_window, 'SetMultiSamples'):
            # 关闭抗锯齿 (MSAA) 以大幅提升点云渲染和切换性能
            self.plotter.render_window.SetMultiSamples(0)

        vtk_widget = self.plotter.interactor
        vtk_widget.setAttribute(Qt.WA_AcceptTouchEvents, True)
        vtk_widget.grabGesture(Qt.PinchGesture)

        self.zoom_filter = ZoomEventFilter(self.plotter)
        vtk_widget.installEventFilter(self.zoom_filter)
        self.main_actor = None

        layout.addWidget(vtk_widget)

    def render_mesh(self, data_manager):
        self.plotter.clear()
        self.main_actor = None
        # Invalidate VTK compass actors (cleared by plotter.clear) so they get recreated
        self._invalidate_compass_hint = True
        self.plotter.add_axes(
            xlabel='E', ylabel='N', zlabel='Z',
            color='white',
            viewport=(0.8, 0.0, 1.0, 0.2)
        )

        if data_manager.mesh and data_manager.mesh.n_points > 0:
            mesh = data_manager.mesh
            has_uv = 'TCoords' in mesh.point_data or 'texture_u' in mesh.point_data
            if data_manager.current_texture and has_uv:
                self.main_actor = self.plotter.add_mesh(
                    mesh,
                    texture=data_manager.current_texture,
                    show_scalar_bar=False,
                    lighting=False,
                    render_points_as_spheres=False,
                    opacity="linear",
                )
            elif 'RGB' in mesh.point_data:
                self.main_actor = self.plotter.add_mesh(
                    mesh,
                    scalars='RGB',
                    rgb=True,
                    point_size=2,
                    lighting=False,
                    render_points_as_spheres=False,
                )
            else:
                self.main_actor = self.plotter.add_mesh(
                    mesh,
                    color="cyan",
                    point_size=2,
                    lighting=False,
                )
