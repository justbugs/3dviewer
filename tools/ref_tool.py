import vtk
import numpy as np
import pyvista as pv
from PySide6.QtCore import QObject, Signal, Qt
from .base import BaseTool

class ReferenceTool(BaseTool, QObject):
    # 信号：类型('line'/'point'), ID, 数据1(p1/pt), 数据2(p2/None)
    ref_added = Signal(str, int, object, object) 

    def __init__(self, canvas, data_manager):
        BaseTool.__init__(self, canvas, data_manager)
        QObject.__init__(self)
        
        self.mode = 'line' # 'line' or 'point'
        self.active_points = []
        self.refs = [] 
        self.count_line = 0
        self.count_point = 0
        
        # 【核心修复】初始化状态变量
        self.is_active = False
        self.pan_start_pos = None

    def set_mode(self, mode):
        self.mode = mode
        self.active_points = []
        # 切换子模式时，如果当前处于激活状态，刷新一下状态（比如更新光标）
        if self.is_active: 
            # 如果当前是打点模式，切换光标样式
            if self.plotter.interactor.GetInteractorStyle().IsA("vtkInteractorStyleTrackballCamera"):
                 self._update_cursor_for_draw()
            self.plotter.render()

    def activate(self):
        if not self.plotter: return
        self.is_active = True
        # 默认进入 View 模式，等待用户点击顶部“打点”按钮才开始画
        self.set_interaction_mode('view')
        print(f"【基准】工具激活: {self.mode}")

    def deactivate(self):
        self.is_active = False
        self.active_points = []
        # 清理临时点
        self.plotter.remove_actor("temp_ref_pt")
        
        self.plotter.enable_trackball_style()
        self.canvas.setCursor(Qt.ArrowCursor)
        super().deactivate()

    # --- 全局交互接口 (必须实现) ---
    def set_interaction_mode(self, mode):
        """响应顶部栏：旋转 / 平移 / 打点"""
        self.clear_observers()
        iren = self.plotter.interactor
        
        # 保存相机
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
            
        elif mode == 'draw':
            # 定点模式
            style = vtk.vtkInteractorStyleTrackballCamera()
            iren.SetInteractorStyle(style)
            
            # 劫持左键：不再旋转，改为点击
            iren.RemoveObservers("LeftButtonPressEvent")
            iren.RemoveObservers("LeftButtonReleaseEvent")
            self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_click))
            
            self._update_cursor_for_draw()
            
        # 恢复相机
        camera.SetPosition(pos); camera.SetFocalPoint(focal); camera.SetViewUp(view_up)
        self.plotter.render()

    def _update_cursor_for_draw(self):
        if self.mode == 'line': 
            self.canvas.setCursor(Qt.SplitVCursor)
        else: 
            self.canvas.setCursor(Qt.CrossCursor)

    def on_click(self, obj, event):
        pos = self.plotter.interactor.GetEventPosition()
        picker = vtk.vtkPointPicker()
        picker.Pick(pos[0], pos[1], 0, self.plotter.renderer)
        pt = picker.GetPickPosition() if picker.GetPointId() != -1 else None
        
        if not pt:
             # Fallback
             wp = vtk.vtkWorldPointPicker()
             wp.Pick(pos[0], pos[1], 0, self.plotter.renderer)
             pt = wp.GetPickPosition()

        if pt:
            self.active_points.append(np.array(pt))
            
            if self.mode == 'line':
                # 临时画点
                self.plotter.add_mesh(pv.PolyData([pt]), color="white", point_size=15, 
                                      render_points_as_spheres=True, name="temp_ref_pt", reset_camera=False)
                if len(self.active_points) == 2:
                    self._create_ref_line(self.active_points[0], self.active_points[1])
                    self.active_points = []
                    self.plotter.remove_actor("temp_ref_pt")
            
            elif self.mode == 'point':
                self._create_ref_point(self.active_points[0])
                self.active_points = []

    def _create_ref_line(self, p1, p2):
        self.count_line += 1
        vec = p2 - p1
        length = np.linalg.norm(vec)
        if length < 1e-3: return
        unit_vec = vec / length
        
        # 视觉延伸
        ext_p1 = p1 - unit_vec * 500
        ext_p2 = p2 + unit_vec * 500
        
        line_mesh = pv.Line(ext_p1, ext_p2)
        actor = self.plotter.add_mesh(line_mesh, color="white", line_width=3, lighting=False, reset_camera=False)
        self._apply_xray(actor)
        
        data = {'type': 'line', 'p1': p1, 'p2': p2, 'actor': actor, 'idx': self.count_line}
        self.refs.append(data)
        self.ref_added.emit('line', self.count_line, p1, p2)

    def _create_ref_point(self, pt):
        self.count_point += 1
        
        actor_pt = self.plotter.add_mesh(pv.PolyData([pt]), color="white", point_size=20, 
                                         render_points_as_spheres=True, lighting=False, reset_camera=False)
        self._apply_xray(actor_pt)
        
        label_pos = [pt[0], pt[1], pt[2] + 0.5]
        actor_lbl = self.plotter.add_point_labels([label_pos], [f"基准点-{self.count_point}"], 
                                                  point_size=0, font_size=24, text_color="white", 
                                                  show_points=False, always_visible=True)
        
        data = {'type': 'point', 'pt': pt, 'actors': [actor_pt, actor_lbl], 'idx': self.count_point}
        self.refs.append(data)
        self.ref_added.emit('point', self.count_point, pt, None)

    def _apply_xray(self, actor):
        mapper = actor.GetMapper()
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(0, -66000)

    def delete_by_data(self, data):
        if 'actor' in data: self.plotter.remove_actor(data['actor'])
        if 'actors' in data: 
            for a in data['actors']: self.plotter.remove_actor(a)
        if data in self.refs: self.refs.remove(data)
        self.plotter.render()

    # --- Pan Logic ---
    def on_pan_start(self, obj, event): self.pan_start_pos = self.plotter.interactor.GetEventPosition()
    def on_pan_move(self, obj, event):
        if not self.pan_start_pos: return
        curr = self.plotter.interactor.GetEventPosition()
        cam = self.plotter.camera
        pos, foc, up = np.array(cam.GetPosition()), np.array(cam.GetFocalPoint()), np.array(cam.GetViewUp())
        norm = foc - pos; norm /= np.linalg.norm(norm)
        right = np.cross(norm, up); right /= np.linalg.norm(right)
        scale = np.linalg.norm(pos - foc) / 800.0
        dx, dy = (self.pan_start_pos[0]-curr[0])*scale, (self.pan_start_pos[1]-curr[1])*scale
        motion = right*dx + up*dy
        cam.SetPosition(pos+motion); cam.SetFocalPoint(foc+motion)
        self.plotter.render()
        self.pan_start_pos = curr
    def on_pan_end(self, obj, event): self.pan_start_pos = None