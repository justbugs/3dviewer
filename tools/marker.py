import vtk
import pyvista as pv
from PySide6.QtCore import QObject, Signal
from .base import BaseTool

class MarkerTool(BaseTool, QObject):
    marker_added = Signal(str, object) # label, data_ref

    def __init__(self, canvas, data_manager):
        BaseTool.__init__(self, canvas, data_manager)
        QObject.__init__(self)
        self.markers = []
        self.count = 0
        self.current_prefix = "Evidence"

    def activate(self):
        self.is_active = True
        self.set_cursor_cross()
        self.observers.append(self.plotter.interactor.AddObserver("LeftButtonPressEvent", self.on_click))

    def deactivate(self):
        self.is_active = False
        self.plotter.enable_trackball_style()
        super().deactivate()

    def set_label_prefix(self, text):
        self.current_prefix = text

    def on_click(self, obj, event):
        pos = self.plotter.interactor.GetEventPosition()
        picker = vtk.vtkPointPicker()
        picker.Pick(pos[0], pos[1], 0, self.plotter.renderer)
        pt = picker.GetPickPosition() if picker.GetPointId() != -1 else None
        
        if pt:
            self.count += 1
            label_text = f"{self.current_prefix}-{self.count}"
            
            # 1. 绘制图标 (蓝色小球代表旗帜根部)
            actor_pt = self.plotter.add_mesh(pv.PolyData([pt]), color="blue", point_size=20, render_points_as_spheres=True, reset_camera=False)
            
            # 2. 绘制文字标签 (始终朝向屏幕)
            # 稍微抬高一点 z
            label_pos = [pt[0], pt[1], pt[2] + 0.2]
            actor_lbl = self.plotter.add_point_labels([label_pos], [label_text], point_size=0, font_size=20, 
                                                      text_color="white", show_points=False, always_visible=True)
            
            data = {'actors': [actor_pt, actor_lbl]}
            self.markers.append(data)
            self.marker_added.emit(label_text, data)

    def delete_by_data(self, data):
        if data in self.markers:
            for a in data['actors']: self.plotter.remove_actor(a)
            self.markers.remove(data)
            self.plotter.render()