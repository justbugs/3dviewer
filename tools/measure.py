import vtk
import numpy as np
import pyvista as pv
from PySide6.QtCore import QObject, Signal, Qt
from .base import BaseTool

try:
    from matplotlib.path import Path
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

class MeasureTool(BaseTool, QObject):
    measurement_added = Signal(str, object) 
    measurement_deleted_by_tool = Signal(int) 

    def __init__(self, canvas, data_manager):
        BaseTool.__init__(self, canvas, data_manager)
        QObject.__init__(self)
        
        self.mode = 'poly' # poly or perp
        self.segments = [] 
        self.current_points = []
        self.current_actors = []
        
        self.count = 0
        self.is_active = False
        self.is_xray_enabled = True 
        
        self.ref_p1 = None
        self.ref_p2 = None
        self.ref_point_pt = None 
        
        self.pan_start_pos = None
        self.start_pos = None 

    def activate(self):
        if not self.plotter: return
        self.is_active = True
        
        if self.mode in ['poly', 'perp', 'direct']:
            self.set_interaction_mode('draw')
        else:
            self.set_interaction_mode('view')
            
        self.set_xray_enabled(self.is_xray_enabled)
        self.redraw_all()
        print(f"【系统】测距工具激活: {self.mode}")

    def deactivate(self):
        self.is_active = False
        self.plotter.enable_trackball_style()
        self.canvas.setCursor(Qt.ArrowCursor)
        self._clear_temp()
        super().deactivate()

    def set_mode(self, mode):
        self.mode = mode
        if self.is_active:
            self.deactivate()
            self.activate() 

    def set_active_ref_line(self, p1, p2):
        self.ref_p1 = np.array(p1)
        self.ref_p2 = np.array(p2)
        print("当前基准线已更新")
    
    def set_active_ref_point(self, pt):
        self.ref_point_pt = np.array(pt)
        print("当前基准点已更新")

    # --- 【核心修复】高亮逻辑 ---
    def highlight_segment(self, target_data):
        """
        根据传入的数据对象高亮对应的 3D 线条
        """
        for seg in self.segments:
            is_selected = (seg is target_data)
            
            # 1. 确定目标颜色
            base_color = "yellow"
            if seg.get('type') == 'perp': base_color = "cyan"
            elif seg.get('type') == 'direct': base_color = "#00FF00"
            
            final_color = "#FF00FF" if is_selected else base_color
            
            # 2. 遍历该段的所有 Actor (包含点和线)
            for actor in seg['actors']:
                try:
                    # 获取当前颜色 (RGB 0-1)
                    c = actor.GetProperty().GetColor()
                    
                    # 【关键修复】
                    # 判断是否是红球端点：Red高, Green低, Blue低
                    # 之前的 Bug: 紫色 (1, 0, 1) 也满足 R>0.9, G<0.1
                    # 现在的 修复: 增加 c[2] < 0.1 (排除蓝色成分高的紫色)
                    is_red_endpoint = (c[0] > 0.9 and c[1] < 0.1 and c[2] < 0.1)
                    
                    if is_red_endpoint:
                        continue # 如果是红球，跳过，不改色
                    
                    # 如果是线，改色
                    actor.GetProperty().SetColor(pv.Color(final_color).float_rgb)
                except:
                    pass
        
        self.plotter.render()

    # --- 退出清理函数 ---
    def cleanup(self):
        if not self.plotter: return
        try:
            self._clear_temp()
            for seg in self.segments:
                for a in seg['actors']:
                    self.plotter.remove_actor(a)
            self.segments = []
        except Exception as e:
            pass
        print("MeasureTool 资源已释放")

    def _clear_temp(self):
        for a in self.current_actors:
            self.plotter.remove_actor(a)
        self.current_actors = []
        self.current_points = []

    # --- 核心：重绘与持久化 ---
    def redraw_all(self):
        if not self.data_manager.mesh: return
        pass 

    def _create_segment_visuals(self, points, is_new=True):
        actors = []
        for p in points:
            a = self.plotter.add_mesh(pv.PolyData([p]), color="red", point_size=20, render_points_as_spheres=True, lighting=False, reset_camera=False)
            self._apply_style(a); actors.append(a)
            
        dist = 0
        if len(points) > 1:
            line = pv.MultipleLines(points)
            tube = line.tube(radius=0.03)
            a_line = self.plotter.add_mesh(tube, color="yellow", lighting=False, reset_camera=False)
            self._apply_style(a_line); actors.append(a_line)
            pts = np.array(points)
            for i in range(len(pts)-1): dist += np.linalg.norm(pts[i]-pts[i+1])
        
        seg_data = {'points': points, 'actors': actors, 'distance': dist, 'type': 'poly'}
        self.segments.append(seg_data)
        if is_new:
            self.count += 1
            self.measurement_added.emit(f"测量-{self.count}: {dist:.2f}m", seg_data)

    # --- 交互：删除 ---
    def delete_by_data(self, data):
        if data in self.segments:
            for a in data['actors']: self.plotter.remove_actor(a)
            self.segments.remove(data)
            self.plotter.render()

    def delete_segment_by_index(self, index):
        if 0 <= index < len(self.segments):
            seg = self.segments[index]
            self.delete_by_data(seg)

    def delete_points_inside_polygon(self, polygon_points):
        if not HAS_MATPLOTLIB or not self.segments: return
        polygon_path = Path(polygon_points)
        width, height = self.plotter.window_size
        renderer = self.plotter.renderer
        mat = self.plotter.camera.GetCompositeProjectionTransformMatrix(renderer.GetTiledAspectRatio(), -1, 1)

        to_remove = []
        for seg in self.segments:
            if 'points' not in seg: continue
            hit = False
            for pt in seg['points']:
                pt4 = np.array([pt[0], pt[1], pt[2], 1.0])
                np_mat = np.zeros((4, 4))
                for r in range(4):
                    for c in range(4): np_mat[r, c] = mat.GetElement(r, c)
                clip = np_mat @ pt4
                w = clip[3]
                if w == 0: continue
                ndc = clip[:3] / w
                sx = (ndc[0] + 1) / 2.0 * width
                sy = (ndc[1] + 1) / 2.0 * height
                if polygon_path.contains_point((sx, sy)):
                    hit = True; break
            if hit: to_remove.append(seg)
        
        for seg in to_remove:
            self.delete_by_data(seg)

    # --- 基础绘制逻辑 ---
    def add_measure_point(self, point):
        self.current_points.append(point)
        a = self.plotter.add_mesh(pv.PolyData([point]), color="red", point_size=20, render_points_as_spheres=True, lighting=False, reset_camera=False)
        self._apply_style(a); self.current_actors.append(a)
        if len(self.current_points) > 1:
            line = pv.Line(self.current_points[-2], self.current_points[-1])
            tube = line.tube(radius=0.03) 
            l_actor = self.plotter.add_mesh(tube, color="yellow", lighting=False, reset_camera=False)
            self._apply_style(l_actor); self.current_actors.append(l_actor)
        self.plotter.render()

    def finish_segment(self):
        if self.mode == 'poly' and len(self.current_points) > 1:
            self._create_segment_visuals(self.current_points, is_new=True)
            self._clear_temp(); self.plotter.render()

    def clear_all(self):
        for s in self.segments:
            for a in s['actors']: self.plotter.remove_actor(a)
        self.segments = []; self._clear_temp(); self.plotter.render()

    # --- 辅助方法 ---
    def set_interaction_mode(self, mode):
        self.clear_observers() 
        iren = self.plotter.interactor
        camera = self.plotter.camera; pos = camera.GetPosition(); focal = camera.GetFocalPoint(); view_up = camera.GetViewUp()

        if mode == 'view':
            style = vtk.vtkInteractorStyleTrackballCamera()
            self.plotter.interactor.SetInteractorStyle(style)
            self.canvas.setCursor(Qt.ArrowCursor)
        elif mode == 'pan':
            style = vtk.vtkInteractorStyleUser()
            self.plotter.interactor.SetInteractorStyle(style)
            self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_pan_start, 100))
            self.observers.append(iren.AddObserver("MouseMoveEvent", self.on_pan_move, 100))
            self.observers.append(iren.AddObserver("LeftButtonReleaseEvent", self.on_pan_end, 100))
            self.canvas.setCursor(Qt.OpenHandCursor)
        elif mode == 'draw':
            style = vtk.vtkInteractorStyleTrackballCamera()
            self.plotter.interactor.SetInteractorStyle(style)
            iren.RemoveObservers("LeftButtonPressEvent"); iren.RemoveObservers("LeftButtonReleaseEvent")
            self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_press, 100))
            self.observers.append(iren.AddObserver("LeftButtonReleaseEvent", self.on_release, 100))
            self.canvas.setCursor(Qt.CrossCursor)

        camera.SetPosition(pos); camera.SetFocalPoint(focal); camera.SetViewUp(view_up); self.plotter.render()

    def set_xray_enabled(self, enabled):
        self.is_xray_enabled = enabled
        for seg in self.segments:
            for actor in seg['actors']: self._apply_style(actor)
        for a in self.current_actors: self._apply_style(a)
        self.plotter.render()

    def _apply_style(self, actor):
        mapper = actor.GetMapper()
        if self.is_xray_enabled:
            mapper.SetResolveCoincidentTopologyToPolygonOffset()
            mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(0, -66000)
        else: mapper.SetResolveCoincidentTopologyToOff()

    # --- Pick / Mouse / Pan ---
    def pick_measure_point(self, pos):
        picker = vtk.vtkPointPicker(); picker.SetTolerance(0.01); picker.Pick(pos[0], pos[1], 0, self.plotter.renderer)
        final_pt = picker.GetPickPosition() if picker.GetPointId() != -1 else None
        if not final_pt:
            wp = vtk.vtkWorldPointPicker(); wp.Pick(pos[0], pos[1], 0, self.plotter.renderer); final_pt = wp.GetPickPosition()
        if final_pt: 
            if self.mode == 'poly': self.add_measure_point(final_pt)
            elif self.mode == 'perp': self._handle_perp_click(np.array(final_pt))
            elif self.mode == 'direct': self._handle_direct(np.array(final_pt))

    def _handle_perp_click(self, pt):
        if self.ref_p1 is None: print("请先在列表中选中一条基准线！"); return
        ab = self.ref_p2 - self.ref_p1; ab_norm_sq = np.dot(ab, ab)
        if ab_norm_sq < 1e-6: return 
        t = np.dot(pt - self.ref_p1, ab) / ab_norm_sq
        h = self.ref_p1 + t * ab
        dist = np.linalg.norm(pt - h)
        line = pv.Line(pt, h); actor = self.plotter.add_mesh(line, color="cyan", line_width=3, reset_camera=False)
        actor.GetProperty().SetLineStipplePattern(0xf0f0); actor.GetProperty().SetLineStippleRepeatFactor(1); self._apply_style(actor)
        a_pt = self.plotter.add_mesh(pv.PolyData([pt]), color="cyan", point_size=15, render_points_as_spheres=True, reset_camera=False); self._apply_style(a_pt)
        seg_data = {'actors': [actor, a_pt], 'distance': dist, 'type': 'perp'}
        self.segments.append(seg_data); self.measurement_added.emit(f"垂距: {dist:.2f}m", seg_data)

    def _handle_direct(self, pt):
        if self.ref_point_pt is None: print("请先在列表中选中一个基准点！"); return
        dist = np.linalg.norm(pt - self.ref_point_pt)
        arrow = pv.Arrow(start=self.ref_point_pt, direction=(pt-self.ref_point_pt), scale=dist, tip_length=0.2/dist if dist>0 else 0)
        actor = self.plotter.add_mesh(arrow, color="#00FF00", lighting=False, reset_camera=False); self._apply_style(actor)
        a_pt = self.plotter.add_mesh(pv.PolyData([pt]), color="#00FF00", point_size=15, render_points_as_spheres=True, reset_camera=False); self._apply_style(a_pt)
        data = {'actors': [actor, a_pt], 'distance': dist, 'type': 'direct'}
        self.segments.append(data); self.measurement_added.emit(f"斜距: {dist:.2f}m", data)

    def on_press(self, obj, event): self.start_pos = self.plotter.interactor.GetEventPosition()
    def on_release(self, obj, event):
        if not self.start_pos: return
        ep = self.plotter.interactor.GetEventPosition()
        if ((ep[0]-self.start_pos[0])**2 + (ep[1]-self.start_pos[1])**2)**0.5 < 10: self.pick_measure_point(ep)
        self.start_pos = None
    def on_pan_start(self, o, e): self.pan_start_pos = self.plotter.interactor.GetEventPosition()
    def on_pan_move(self, o, e):
        if not self.pan_start_pos: return
        curr = self.plotter.interactor.GetEventPosition()
        cam = self.plotter.camera; pos = np.array(cam.GetPosition()); foc = np.array(cam.GetFocalPoint()); up = np.array(cam.GetViewUp())
        n = foc-pos; n/=np.linalg.norm(n); r = np.cross(n, up); r/=np.linalg.norm(r)
        scale = np.linalg.norm(pos-foc)/800.0
        cam.SetPosition(pos + r*(self.pan_start_pos[0]-curr[0])*scale + up*(self.pan_start_pos[1]-curr[1])*scale)
        cam.SetFocalPoint(foc + r*(self.pan_start_pos[0]-curr[0])*scale + up*(self.pan_start_pos[1]-curr[1])*scale)
        self.plotter.render(); self.pan_start_pos = curr
    def on_pan_end(self, o, e): self.pan_start_pos = None