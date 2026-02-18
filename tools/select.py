import vtk
import numpy as np
import pyvista as pv
from PySide6.QtCore import Signal, QObject
from .base import BaseTool

try:
    from matplotlib.path import Path
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

class SelectTool(BaseTool, QObject):
    request_delete_measurements = Signal(list)

    def __init__(self, canvas, data_manager):
        BaseTool.__init__(self, canvas, data_manager)
        QObject.__init__(self)
        self.lasso_points = []       
        self.lasso_visual_points = [] 
        self.is_active = False
        self.selection_actor = None
        self.selected_indices = []
        self.interaction_mode = 'view' 
        self.pan_start_pos = None
        self.last_screen_pos = None

    def activate(self):
        if not HAS_MATPLOTLIB: return
        self.is_active = True
        self.plotter.render()
        self.set_interaction_mode('view')
        print("【系统】套索工具已激活")

    def deactivate(self):
        self.is_active = False
        self._clear_trace()
        self.plotter.enable_trackball_style()
        super().deactivate()

    # --- 【核心修复】退出清理 ---
    def cleanup(self):
        """退出时清理资源"""
        if not self.plotter: return
        try:
            self._clear_trace()
            self._clear_selection_visuals()
        except: pass
        print("SelectTool 资源已释放")

    # ... (以下逻辑保持不变) ...
    def set_interaction_mode(self, mode):
        camera = self.plotter.camera
        pos = camera.GetPosition(); focal = camera.GetFocalPoint(); view_up = camera.GetViewUp()
        
        self.interaction_mode = mode
        self._clear_trace()
        self.clear_observers() 
        iren = self.plotter.interactor

        if mode == 'view':
            style = vtk.vtkInteractorStyleTrackballCamera()
            self.plotter.interactor.SetInteractorStyle(style)
        elif mode == 'pan':
            style = vtk.vtkInteractorStyleUser()
            self.plotter.interactor.SetInteractorStyle(style)
            self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_pan_start))
            self.observers.append(iren.AddObserver("MouseMoveEvent", self.on_pan_move))
            self.observers.append(iren.AddObserver("LeftButtonReleaseEvent", self.on_pan_end))
        elif mode == 'draw':
            style = vtk.vtkInteractorStyleTrackballCamera()
            self.plotter.interactor.SetInteractorStyle(style)
            iren.RemoveObservers("LeftButtonPressEvent")
            iren.RemoveObservers("LeftButtonReleaseEvent")
            self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_start))
            self.observers.append(iren.AddObserver("MouseMoveEvent", self.on_move))
            self.observers.append(iren.AddObserver("LeftButtonReleaseEvent", self.on_end))

        camera.SetPosition(pos); camera.SetFocalPoint(focal); camera.SetViewUp(view_up)
        self.plotter.render()

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

    def on_start(self, obj, event):
        pos = self.plotter.interactor.GetEventPosition()
        self.lasso_points = [pos]
        self.lasso_visual_points = []
        self.last_screen_pos = pos
        self._clear_selection_visuals()
        self.is_drawing = True
        self._add_visual_point_safe(pos)
        self._update_trace_actor()

    def on_move(self, obj, event):
        if not hasattr(self, 'is_drawing') or not self.is_drawing: return
        curr = self.plotter.interactor.GetEventPosition()
        if self.last_screen_pos:
            dist = np.linalg.norm(np.array(curr) - np.array(self.last_screen_pos))
            if dist > 10:
                steps = int(dist / 5)
                for i in range(1, steps + 1):
                    t = i / (steps + 1)
                    ix = int(self.last_screen_pos[0] + (curr[0] - self.last_screen_pos[0]) * t)
                    iy = int(self.last_screen_pos[1] + (curr[1] - self.last_screen_pos[1]) * t)
                    self._add_visual_point_safe((ix, iy))
        self.lasso_points.append(curr)
        self._add_visual_point_safe(curr)
        self.last_screen_pos = curr
        self._update_trace_actor()

    def on_end(self, obj, event):
        self.is_drawing = False
        self.last_screen_pos = None
        if len(self.lasso_points) > 2: self.calculate_selection()
        self._clear_trace()

    def _add_visual_point_safe(self, pos):
        try:
            renderer = self.plotter.renderer
            renderer.SetDisplayPoint(pos[0], pos[1], 0)
            renderer.DisplayToWorld()
            world_pt = renderer.GetWorldPoint()
            if world_pt[3] != 0:
                pt = np.array(world_pt[:3]) / world_pt[3]
                self.lasso_visual_points.append(pt)
        except: pass

    def _update_trace_actor(self):
        if len(self.lasso_visual_points) < 2: return
        self.plotter.remove_actor("lasso_trace_dynamic")
        line = pv.lines_from_points(np.array(self.lasso_visual_points))
        self.plotter.add_mesh(line, color="#FF00FF", line_width=4, name="lasso_trace_dynamic", 
                              reset_camera=False, lighting=False)
        self.plotter.render()

    def _clear_trace(self):
        self.plotter.remove_actor("lasso_trace_dynamic")
        self.lasso_points = []
        self.lasso_visual_points = []
        self.last_screen_pos = None
        self.is_drawing = False
        self.plotter.render()

    def calculate_selection(self):
        if not self.data_manager.mesh: return
        self.plotter.render()
        path = Path(self.lasso_points)
        w, h = self.plotter.window_size
        mat = self.plotter.camera.GetCompositeProjectionTransformMatrix(self.plotter.renderer.GetTiledAspectRatio(), -1, 1)
        np_mat = np.zeros((4, 4))
        for r in range(4):
            for c in range(4): np_mat[r, c] = mat.GetElement(r, c)
        
        pts = self.data_manager.mesh.points
        pts4 = np.hstack((pts, np.ones((len(pts), 1))))
        clip = pts4 @ np_mat.T
        ndc = clip[:, :3] / (clip[:, 3:4] + 1e-10)
        
        scr = np.zeros((len(pts), 2))
        scr[:, 0] = (ndc[:, 0] + 1) / 2.0 * w
        scr[:, 1] = (ndc[:, 1] + 1) / 2.0 * h
        
        mask = path.contains_points(scr, radius=0) & (clip[:, 3] > 0)
        self.selected_indices = np.where(mask)[0]
        if len(self.selected_indices) > 0: self._highlight_selection()

    def _highlight_selection(self):
        self._clear_selection_visuals()
        if len(self.selected_indices) == 0: return
        sub = self.data_manager.mesh.extract_points(self.selected_indices)
        self.selection_actor = self.plotter.add_mesh(sub, color="red", point_size=4, 
                                                     lighting=False, name="selection_highlight", reset_camera=False)
        mapper = self.selection_actor.GetMapper()
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(0, -66000)
        self.plotter.render()

    def _clear_selection_visuals(self):
        if self.selection_actor: self.plotter.remove_actor(self.selection_actor); self.selection_actor = None
        self.plotter.remove_actor("selection_highlight")

    def delete_selection(self):
        if len(self.selected_indices) == 0: return
        if len(self.lasso_points) > 2: self.request_delete_measurements.emit(self.lasso_points)
        self.data_manager.push_history()
        all_ids = np.arange(self.data_manager.mesh.n_points)
        keep = ~np.isin(all_ids, self.selected_indices)
        self.data_manager.mesh = self.data_manager.mesh.extract_points(keep)
        self.selected_indices = []
        self._clear_selection_visuals()

    def invert_selection(self):
        if not self.data_manager.mesh: return
        all_ids = np.arange(self.data_manager.mesh.n_points)
        self.selected_indices = np.setdiff1d(all_ids, self.selected_indices)
        self._highlight_selection()
        
    def get_crop_bbox(self):
        if len(self.selected_indices) < 4: return None
        try:
            import open3d as o3d
            sub = self.data_manager.mesh.extract_points(self.selected_indices)
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(sub.points)
            bbox = pcd.get_oriented_bounding_box()
            bbox.scale(1.05, bbox.get_center())
            return bbox
        except: return None