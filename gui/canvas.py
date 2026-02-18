from PySide6.QtWidgets import QFrame, QVBoxLayout
from PySide6.QtCore import Qt, QEvent, QObject
from pyvistaqt import QtInteractor

# --- 手势过滤器 (保持不变) ---
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
        
        # 坐标轴
        self.plotter.add_axes(
            xlabel='E', ylabel='N', zlabel='Z', 
            color='white',
            viewport=(0.8, 0.0, 1.0, 0.2)
        )
        
        self.plotter.enable_trackball_style()
        if hasattr(self.plotter.render_window, 'SetMultiSamples'):
            self.plotter.render_window.SetMultiSamples(4)

        vtk_widget = self.plotter.interactor
        vtk_widget.setAttribute(Qt.WA_AcceptTouchEvents, True)
        vtk_widget.grabGesture(Qt.PinchGesture)
        
        self.zoom_filter = ZoomEventFilter(self.plotter)
        vtk_widget.installEventFilter(self.zoom_filter)

        layout.addWidget(vtk_widget)

    def render_mesh(self, data_manager):
        self.plotter.clear()
        self.plotter.add_axes(xlabel='E', ylabel='N', zlabel='Z', color='white', viewport=(0.8, 0.0, 1.0, 0.2))
        
        # 【核心修复】增加空数据检查，防止 reset 时报错
        if data_manager.mesh and data_manager.mesh.n_points > 0:
            if data_manager.current_texture:
                self.plotter.add_mesh(data_manager.mesh, texture=data_manager.current_texture, 
                                      show_scalar_bar=False, lighting=False, render_points_as_spheres=False)
            elif 'RGB' in data_manager.mesh.point_data:
                self.plotter.add_mesh(data_manager.mesh, scalars='RGB', rgb=True, 
                                      point_size=2, lighting=False, render_points_as_spheres=False)
            else:
                self.plotter.add_mesh(data_manager.mesh, color="cyan", point_size=2, lighting=False)