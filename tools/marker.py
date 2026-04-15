import vtk
import numpy as np # Added for pan logic
import pyvista as pv
from PySide6.QtCore import QObject, Signal, Qt
from .base import BaseTool

class MarkerTool(BaseTool, QObject):
    marker_added = Signal(str, object) # label, data_ref
    request_marker_details = Signal(object, str) # pos (array), default_label

    def __init__(self, canvas, data_manager):
        BaseTool.__init__(self, canvas, data_manager)
        QObject.__init__(self)
        self.markers = []
        self.count = 0
        self.current_prefix = "标注" # Default changed from "Evidence"
        self.interaction_mode = 'draw'
        self.style_font_size = 20
        self.style_text_color = "#ffffff"


    @staticmethod
    def _hex_to_rgb(hex_str):
        h = hex_str.lstrip('#')
        return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))

    def activate(self):
        self.is_active = True
        self.set_interaction_mode(self.interaction_mode)

    def deactivate(self):
        self.is_active = False
        self.clear_observers() 
        
        # 恢复默认交互
        style = vtk.vtkInteractorStyleTrackballCamera()
        self.plotter.interactor.SetInteractorStyle(style)
        self.canvas.setCursor(Qt.ArrowCursor)

    def set_interaction_mode(self, mode):
        """
        响应顶部栏按钮：旋转(view)/平移(pan)/放置(draw)
        """
        self.interaction_mode = mode
        if not self.is_active: return

        self.clear_observers()
        iren = self.plotter.interactor
        
        # 保存相机状态
        camera = self.plotter.camera
        pos = camera.GetPosition(); focal = camera.GetFocalPoint(); view_up = camera.GetViewUp()

        if mode == 'view':
            style = vtk.vtkInteractorStyleTrackballCamera()
            iren.SetInteractorStyle(style)
            self.canvas.setCursor(Qt.ArrowCursor)
            
        elif mode == 'pan':
            style = vtk.vtkInteractorStyleUser()
            iren.SetInteractorStyle(style)
            self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_pan_start))
            self.observers.append(iren.AddObserver("MouseMoveEvent", self.on_pan_move))
            self.observers.append(iren.AddObserver("LeftButtonReleaseEvent", self.on_pan_end))
            self.canvas.setCursor(Qt.OpenHandCursor)
            
        elif mode == 'draw': # 放置标记
            style = vtk.vtkInteractorStyleTrackballCamera()
            iren.SetInteractorStyle(style)
            
            #禁止左键旋转
            try:
                iren.RemoveObservers("LeftButtonPressEvent")
                iren.RemoveObservers("LeftButtonReleaseEvent")
            except Exception:
                pass
            
            self.set_cursor_cross()
            self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_click))

        # 恢复相机
        camera.SetPosition(pos); camera.SetFocalPoint(focal); camera.SetViewUp(view_up)
        self.plotter.render()
        
    def set_cursor_cross(self):
        self.canvas.setCursor(Qt.CrossCursor)

    def set_label_prefix(self, text):
        self.current_prefix = text

    def on_click(self, obj, event):
        if self.interaction_mode != 'draw': return
        
        pos = self.plotter.interactor.GetEventPosition()
        
        # 1. 尝试拾取点
        picker = vtk.vtkPointPicker()
        picker.Pick(pos[0], pos[1], 0, self.plotter.renderer)
        pt = picker.GetPickPosition() if picker.GetPointId() != -1 else None
        
        # 2. 如果没拾取到点，尝试拾取世界坐标 (Fallback)
        if not pt:
             wp = vtk.vtkWorldPointPicker()
             wp.Pick(pos[0], pos[1], 0, self.plotter.renderer)
             pt = wp.GetPickPosition()
        
        if pt:
            # 不再直接添加，而是请求详情
            default_label = f"{self.current_prefix}{self.count + 1}"
            self.request_marker_details.emit(pt, default_label)

    def add_marker(self, pos, label, desc, image_path):
        """
        外部调用（如对话框确认后）添加标记
        """
        self.count += 1 # 确认添加才计数
        
        # 1. 绘制图标 (蓝色小球代表旗帜根部)
        actor_pt = self.plotter.add_mesh(pv.PolyData([pos]), color="blue", point_size=20, render_points_as_spheres=True, reset_camera=False)
        
        # 2. 绘制文字标签 (始终朝向屏幕)
        # 稍微抬高一点 z
        label_pos = [pos[0], pos[1], pos[2] + 0.2]
        
        new_lbl = vtk.vtkTextActor()
        new_lbl.SetInput(label)
        prop = new_lbl.GetTextProperty()
        prop.SetFontSize(self.style_font_size)
        tr, tg, tb = self._hex_to_rgb(self.style_text_color)
        prop.SetColor(tr, tg, tb)
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToCentered()
        if hasattr(prop, 'SetBackgroundColor'):
            prop.SetBackgroundColor(0.0, 0.0, 0.0)
        if hasattr(prop, 'SetBackgroundOpacity'):
            prop.SetBackgroundOpacity(0.6)
        
        from gui.canvas import _FONT_PATH
        if _FONT_PATH:
            try:
                prop.SetFontFamily(vtk.VTK_FONT_FILE)
                prop.SetFontFile(_FONT_PATH)
            except Exception: pass
            
        new_lbl.SetPosition(label_pos[0], label_pos[1])
        new_lbl.GetPositionCoordinate().SetCoordinateSystemToWorld()
        new_lbl.GetPositionCoordinate().SetValue(label_pos[0], label_pos[1], label_pos[2])
        self.plotter.renderer.AddActor(new_lbl)
        actor_lbl = new_lbl
        
        # 保存扩展数据
        # 保存扩展数据
        data = {
            'actors': [actor_pt, actor_lbl], 
            'label': label,
            'desc': desc,
            'image': image_path,
            'font_size': self.style_font_size,
            'text_color': self.style_text_color
        }
        self.markers.append(data)
        self.marker_added.emit(label, data)

    def update_style_defaults(self, key, value):
        if key == 'font':
            self.style_font_size = int(value)
        elif key == 'text_color':
            self.style_text_color = value
            
    def apply_style(self, key, value, data_ref, render=True):
        if key == 'font':
            new_size = int(value)
            data_ref['font_size'] = new_size
            if len(data_ref.get('actors', [])) > 1:
                lbl_actor = data_ref['actors'][1]
                if isinstance(lbl_actor, vtk.vtkTextActor):
                    lbl_actor.GetTextProperty().SetFontSize(new_size)
        elif key == 'text_color':
            data_ref['text_color'] = value
            if len(data_ref.get('actors', [])) > 1:
                lbl_actor = data_ref['actors'][1]
                if isinstance(lbl_actor, vtk.vtkTextActor):
                    r, g, b = self._hex_to_rgb(value)
                    lbl_actor.GetTextProperty().SetColor(r, g, b)
        if render:
            self.plotter.render()

    def delete_by_data(self, data, render=True):
        if data in self.markers:
            for a in data['actors']: self.plotter.remove_actor(a)
            self.markers.remove(data)
            if render:
                self.plotter.render()

    def clear_all(self, render=True):
        while self.markers:
            self.delete_by_data(self.markers[0], render=False)
        if render:
            self.plotter.render()
    def set_visible(self, visible):
        for marker in self.markers:
            for actor in marker.get('actors', []):
                if actor is not None:
                    actor.SetVisibility(visible)

    def redraw_all(self):
        """Re-add all marker actors to the renderer after a plotter.clear()"""
        for marker in self.markers:
            for actor in marker.get('actors', []):
                if actor is not None:
                    try: self.plotter.renderer.AddActor(actor)
                    except Exception: pass
        self.plotter.render()

    # --- Pan Logic (Copied from Base or RefTool) ---
    def on_pan_start(self, obj, event): self.pan_start_pos = self.plotter.interactor.GetEventPosition()
    def on_pan_move(self, obj, event):
        if not hasattr(self, 'pan_start_pos') or not self.pan_start_pos: return
        from tools.pan_utils import perform_pan
        curr = self.plotter.interactor.GetEventPosition()
        self.pan_start_pos = perform_pan(self.plotter, self.pan_start_pos, curr)
    def on_pan_end(self, obj, event): self.pan_start_pos = None

    def highlight_segment(self, target_data):
        for marker in self.markers:
            is_selected = (marker is target_data)
            final_color = "#FF00FF" if is_selected else "#00FF00" # Green is default for markers
            rgb_color = tuple(int(final_color.lstrip('#')[i:i+2], 16) / 255.0 for i in (0, 2, 4))
            for actor in marker.get('actors', []):
                try:
                    if hasattr(actor.GetMapper(), 'SetResolveCoincidentTopologyToPolygonOffset'):
                        actor.GetProperty().SetColor(*rgb_color)
                except Exception:
                    pass
        self.plotter.render()
