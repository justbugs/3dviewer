import vtk
import numpy as np
import open3d as o3d
import pyvista as pv
from PySide6.QtCore import QObject, Signal
from .base import BaseTool

class CalibrationTool(BaseTool, QObject):
    matrix_updated = Signal(object) 
    status_message = Signal(str) 
    north_tuning_started = Signal() 

    def __init__(self, canvas, data_manager):
        BaseTool.__init__(self, canvas, data_manager)
        QObject.__init__(self)
        self.accumulated_matrix = np.eye(4)
        
        self.mode = None 
        self.north_p1 = None 
        self.north_p2 = None
        self.manual_ground_points = []
        self.visual_actors = []       
        self.static_actors = []       
        self.grid_actor = None
        
        self.is_debug_mode = False
        self.last_mouse_pos = None

    def activate(self):
        self.is_active = True
        self.plotter.enable_trackball_style()

    def deactivate(self):
        self.is_active = False
        self.mode = None
        self._clear_visuals()
        self.hide_grid()
        self.plotter.enable_trackball_style()
        super().deactivate()

    # --- 视图控制 ---
    def view_top(self):
        self.plotter.view_xy()
        self.plotter.render()
    def view_front(self):
        self.plotter.view_xz()
        self.plotter.camera.SetViewUp(0, 0, 1)
        self.plotter.render()
    def view_side(self):
        self.plotter.view_yz()
        self.plotter.camera.SetViewUp(0, 0, 1)
        self.plotter.render()

    # --- 流程 1: 地面校准 ---
    def start_ground_calibration_flow(self):
        self.mode = 'preview_grid'
        self.show_grid()
        self.view_side() 
        self.status_message.emit("检查地面是否与网格重合。如需调整，点击[手动校准]")

    def start_manual_ground_3pt(self):
        self.data_manager.push_history() 
        self.mode = 'manual_ground'
        self.manual_ground_points = []
        self._clear_visuals() 
        self.view_top() 
        self.status_message.emit("模式已切换：请在地面上点击 3 个点")
        self.set_interaction_mode('pick')

    def confirm_ground(self):
        self.deactivate() 
        self.status_message.emit("地面校准已确认")

    # --- 交互模式 ---
    def set_interaction_mode(self, mode_name):
        self.clear_observers() 
        iren = self.plotter.interactor
        if mode_name == 'view':
            style = vtk.vtkInteractorStyleTrackballCamera()
            self.plotter.interactor.SetInteractorStyle(style)
        elif mode_name == 'pan':
            style = vtk.vtkInteractorStyleUser()
            self.plotter.interactor.SetInteractorStyle(style)
            self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_pan_start))
            self.observers.append(iren.AddObserver("MouseMoveEvent", self.on_pan_move))
            self.observers.append(iren.AddObserver("LeftButtonReleaseEvent", self.on_pan_end))
        elif mode_name == 'draw' or mode_name == 'pick':
            if self.mode == 'manual_ground':
                style = vtk.vtkInteractorStyleTrackballCamera()
                self.plotter.interactor.SetInteractorStyle(style)
                iren.RemoveObservers("LeftButtonPressEvent")
                self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_click_ground))
            else:
                self.set_interaction_mode('view')
        self.plotter.render()

    def on_click_ground(self, obj, event):
        pos = self.plotter.interactor.GetEventPosition()
        pt = self._pick_point(pos)
        if pt is not None:
            self.manual_ground_points.append(pt)
            actor = self.plotter.add_mesh(pv.PolyData([pt]), render_points_as_spheres=True, 
                                          name=f"ground_pt_{len(self.manual_ground_points)}")
            self._apply_style(actor, color="cyan")
            self.visual_actors.append(actor)
            
            if len(self.manual_ground_points) == 3:
                self._compute_ground()
                self.manual_ground_points = [] 
                self.set_interaction_mode('view') 
                self.status_message.emit("计算完成，请检查网格。满意请点[确认]，不满意请重试。")

    def _compute_ground(self):
        p0, p1, p2 = np.array(self.manual_ground_points)
        v1 = p1 - p0; v2 = p2 - p0
        normal = np.cross(v1, v2)
        if np.linalg.norm(normal) < 1e-6:
            self.status_message.emit("无效点：共线")
            return
        normal = normal / np.linalg.norm(normal)
        if normal[2] < 0: normal = -normal 
        target = np.array([0, 0, 1])
        axis = np.cross(normal, target); axis_len = np.linalg.norm(axis)
        
        R = np.eye(3)
        if axis_len > 1e-6:
            axis = axis / axis_len
            angle = np.arccos(np.dot(normal, target))
            K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
            R = np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)
            
        T = np.eye(4); T[:3, :3] = R
        self._apply_transform(T, record_history=True) 
        if self.data_manager.mesh:
            z_min = self.data_manager.mesh.bounds[4]
            T_shift = np.eye(4); T_shift[2, 3] = -z_min
            self._apply_transform(T_shift, record_history=False)
        self.show_grid() # 刷新网格

    # --- 流程 2: 指北 ---
    def start_set_north(self):
        self.data_manager.push_history()
        self.mode = 'set_north_draw'
        self.north_p1 = None; self.north_p2 = None
        self._clear_visuals()
        self.view_top()
        style = vtk.vtkInteractorStyleTrackballCamera()
        self.plotter.interactor.SetInteractorStyle(style)
        self.plotter.interactor.RemoveObservers("LeftButtonPressEvent")
        self.observers.append(self.plotter.interactor.AddObserver("LeftButtonPressEvent", self.on_click_north))
        self.status_message.emit("【第1步】点击两点：画出当前地图的“北向”")

    def on_click_north(self, obj, event):
        if self.mode != 'set_north_draw': return
        pt = self._pick_point(self.plotter.interactor.GetEventPosition())
        if pt is None: return
        if self.north_p1 is None:
            self.north_p1 = pt
            a = self.plotter.add_mesh(pv.PolyData([pt]), render_points_as_spheres=True, name="north_temp_1")
            self._apply_style(a, "orange")
            self.visual_actors.append(a)
        else:
            self.north_p2 = pt
            self._align_north_to_y()
            self._clear_visuals()
            self._enter_tuning_mode()

    def _align_north_to_y(self):
        vec = np.array(self.north_p2) - np.array(self.north_p1)
        vec[2] = 0
        if np.linalg.norm(vec) < 1e-6: return
        vec = vec / np.linalg.norm(vec)
        target = np.array([0, 1, 0])
        cross_z = vec[0]*target[1] - vec[1]*target[0]
        dot = np.dot(vec, target)
        angle = np.arctan2(cross_z, dot)
        c, s = np.cos(angle), np.sin(angle)
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        T = np.eye(4); T[:3, :3] = R
        self._apply_transform(T, record_history=True)

    def _enter_tuning_mode(self):
        self.mode = 'set_north_tune'
        self.status_message.emit("【第2步】拖动屏幕旋转地图，使地图对齐黄色箭头")
        self.north_tuning_started.emit()
        self._draw_static_north_arrow()
        self.clear_observers() 
        style = vtk.vtkInteractorStyleTrackballCamera()
        self.plotter.interactor.SetInteractorStyle(style)
        iren = self.plotter.interactor
        iren.RemoveObservers("LeftButtonPressEvent")
        iren.RemoveObservers("LeftButtonReleaseEvent")
        self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_tune_start))
        self.observers.append(iren.AddObserver("MouseMoveEvent", self.on_tune_move))
        self.observers.append(iren.AddObserver("LeftButtonReleaseEvent", self.on_tune_end))

    def _draw_static_north_arrow(self):
        if not self.data_manager.mesh: return
        c = self.data_manager.mesh.center
        bounds = self.data_manager.mesh.bounds
        length = max(bounds[1]-bounds[0], bounds[3]-bounds[2]) * 0.4
        arrow = pv.Arrow(start=[c[0], c[1], c[2]], direction=[0, 1, 0], scale=length, 
                         tip_length=0.25, tip_radius=0.1, shaft_radius=0.03)
        actor_arrow = self.plotter.add_mesh(arrow, color="yellow", lighting=False, name="static_north_arrow")
        self._apply_style(actor_arrow, color="yellow", is_solid=True)
        self.static_actors.append(actor_arrow)
        label_pos = [c[0], c[1] + length * 1.1, c[2]]
        actor_label = self.plotter.add_point_labels([label_pos], ["N"], point_size=0, font_size=24, text_color="yellow", show_points=False, always_visible=True)
        self.static_actors.append(actor_label)

    def on_tune_start(self, obj, event):
        self.last_mouse_pos = self.plotter.interactor.GetEventPosition()
        self.is_dragging = True
    def on_tune_move(self, obj, event):
        if not hasattr(self, 'is_dragging') or not self.is_dragging: return
        if not self.last_mouse_pos: return
        curr_pos = self.plotter.interactor.GetEventPosition()
        dx = curr_pos[0] - self.last_mouse_pos[0]
        angle_deg = dx * 0.2
        self.rotate_by_delta(angle_deg, record_history=False)
        self.last_mouse_pos = curr_pos
    def on_tune_end(self, obj, event):
        self.is_dragging = False; self.last_mouse_pos = None
    def confirm_north(self):
        self.deactivate()
        self.status_message.emit("方向已锁定")

    # --- 辅助 ---
    def show_grid(self):
        self.hide_grid()
        if not self.data_manager.mesh: return
        
        # 【核心修改】动态计算网格大小
        bounds = self.data_manager.mesh.bounds
        c = self.data_manager.mesh.center
        x_size = bounds[1] - bounds[0]
        y_size = bounds[3] - bounds[2]
        
        # 设为模型最大边长的 2.5 倍，不再是写死的 200
        grid_size = max(x_size, y_size) * 2.5
        
        # 【核心修改】i_resolution=100
        plane = pv.Plane(center=(c[0], c[1], 0), direction=[0,0,1], 
                         i_size=grid_size, j_size=grid_size, 
                         i_resolution=100, j_resolution=100)
                         
        # reset_camera=False 保证相机不动
        self.grid_actor = self.plotter.add_mesh(plane, color="white", style="wireframe", 
                                                opacity=0.3, lighting=False, name="calib_grid",
                                                reset_camera=False) 

    def hide_grid(self):
        if self.grid_actor: self.plotter.remove_actor(self.grid_actor); self.grid_actor = None
        self.plotter.remove_actor("calib_grid")

    def rotate_by_delta(self, angle_deg, record_history=False):
        rad = np.deg2rad(angle_deg)
        c, s = np.cos(rad), np.sin(rad)
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        T = np.eye(4); T[:3, :3] = R
        self._apply_transform(T, record_history)

    def _apply_transform(self, matrix, record_history=False):
        if record_history: self.data_manager.push_history()
        self.accumulated_matrix = matrix @ self.accumulated_matrix
        self.data_manager.mesh.transform(matrix, inplace=True)
        for actor in self.visual_actors:
            try:
                poly = actor.GetMapper().GetInput()
                poly.transform(matrix, inplace=True)
            except: pass
        self.matrix_updated.emit(self.accumulated_matrix)
        self.plotter.render()

    def _pick_point(self, pos):
        picker = vtk.vtkPointPicker()
        picker.Pick(pos[0], pos[1], 0, self.plotter.renderer)
        return picker.GetPickPosition() if picker.GetPointId() != -1 else None
    def _clear_visuals(self):
        for actor in self.visual_actors: self.plotter.remove_actor(actor)
        self.visual_actors = []
        for actor in self.static_actors: self.plotter.remove_actor(actor)
        self.static_actors = []
        self.plotter.remove_actor("north_temp_1")
        for i in range(5): self.plotter.remove_actor(f"ground_pt_{i}")
    def _apply_style(self, actor, color=None, line_width=4, is_solid=False):
        if not actor: return
        mapper = actor.GetMapper()
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(0, -66000)
        prop = actor.GetProperty()
        if color: prop.SetColor(pv.Color(color).float_rgb)
        if is_solid: prop.SetLighting(False)
        else: prop.SetLineWidth(line_width); prop.SetPointSize(15); prop.SetRenderLinesAsTubes(True)
    def on_pan_start(self, obj, event): self.pan_start_pos = self.plotter.interactor.GetEventPosition()
    def on_pan_move(self, obj, event):
        if not getattr(self, 'pan_start_pos', None): return
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
    def get_transform_matrix(self): return self.accumulated_matrix