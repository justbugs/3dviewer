import vtk
import numpy as np
import pyvista as pv
import time
from PySide6.QtCore import Signal, QObject
from .base import BaseTool

try:
    from matplotlib.path import Path
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

class SelectTool(BaseTool, QObject):
    request_delete_measurements = Signal(list)
    selection_deleted = Signal()

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
        self._last_trace_render_t = 0.0
        self._trace_render_interval_s = 1.0 / 30.0
        self._min_move_px = 4.0
        self._max_highlight_points = 200000

    def activate(self):
        if not HAS_MATPLOTLIB: return
        self.is_active = True
        self.plotter.render()
        self.set_interaction_mode('view')


    def deactivate(self):
        self.is_active = False
        self.clear_observers()
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
            try:
                iren.RemoveObservers("LeftButtonPressEvent")
                iren.RemoveObservers("LeftButtonReleaseEvent")
            except Exception:
                pass
            self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_start))
            self.observers.append(iren.AddObserver("MouseMoveEvent", self.on_move))
            self.observers.append(iren.AddObserver("LeftButtonReleaseEvent", self.on_end))

        camera.SetPosition(pos); camera.SetFocalPoint(focal); camera.SetViewUp(view_up)
        self.plotter.render()

    def on_pan_start(self, obj, event): self.pan_start_pos = self.plotter.interactor.GetEventPosition()
    def on_pan_move(self, obj, event):
        if not getattr(self, 'pan_start_pos', None): return
        from tools.pan_utils import perform_pan
        curr = self.plotter.interactor.GetEventPosition()
        self.pan_start_pos = perform_pan(self.plotter, self.pan_start_pos, curr)
    def on_pan_end(self, obj, event): self.pan_start_pos = None

    def on_start(self, obj, event):
        pos = self.plotter.interactor.GetEventPosition()
        self.lasso_points = [pos]
        self.lasso_visual_points = []
        self.last_screen_pos = pos
        self._last_trace_render_t = 0.0
        self._clear_selection_visuals()
        self.is_drawing = True
        self._add_visual_point_safe(pos)
        self._update_trace_actor()

    def on_move(self, obj, event):
        if not hasattr(self, 'is_drawing') or not self.is_drawing: return
        curr = self.plotter.interactor.GetEventPosition()
        if self.last_screen_pos:
            dist = np.linalg.norm(np.array(curr) - np.array(self.last_screen_pos))
            if dist < self._min_move_px:
                return
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
        now = time.time()
        if (now - self._last_trace_render_t) < self._trace_render_interval_s:
            return
        self._last_trace_render_t = now
        self.plotter.remove_actor("lasso_trace_dynamic")
        line = pv.lines_from_points(np.array(self.lasso_visual_points))
        actor = self.plotter.add_mesh(line, color="#FF00FF", line_width=4, name="lasso_trace_dynamic", 
                              reset_camera=False, lighting=False)
        mapper = actor.GetMapper()
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(0, -66000)
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
        if len(self.lasso_points) < 3:
            return
        path = Path(np.asarray(self.lasso_points, dtype=np.float32))
        w, h = self.plotter.window_size
        mat = self.plotter.camera.GetCompositeProjectionTransformMatrix(self.plotter.renderer.GetTiledAspectRatio(), -1, 1)
        np_mat = np.zeros((4, 4), dtype=np.float64)
        for r in range(4):
            for c in range(4): np_mat[r, c] = mat.GetElement(r, c)

        # Keep math in float32 to reduce allocations/CPU on 4M+ points.
        pts = np.asarray(self.data_manager.mesh.points, dtype=np.float32)
        m = np_mat.astype(np.float32, copy=False)
        x = pts[:, 0]
        y = pts[:, 1]
        z = pts[:, 2]
        clip_w = x * m[3, 0] + y * m[3, 1] + z * m[3, 2] + m[3, 3]
        visible = clip_w > 1e-8
        if not np.any(visible):
            self.selected_indices = np.array([], dtype=np.int64)
            self._clear_selection_visuals()
            return

        clip_x = x * m[0, 0] + y * m[0, 1] + z * m[0, 2] + m[0, 3]
        clip_y = x * m[1, 0] + y * m[1, 1] + z * m[1, 2] + m[1, 3]
        inv_w = np.zeros_like(clip_w, dtype=np.float32)
        inv_w[visible] = 1.0 / clip_w[visible]
        scr_x = ((clip_x * inv_w) + 1.0) * (0.5 * float(w))
        scr_y = ((clip_y * inv_w) + 1.0) * (0.5 * float(h))

        lasso_arr = np.asarray(self.lasso_points, dtype=np.float32)
        min_x, max_x = float(lasso_arr[:, 0].min()), float(lasso_arr[:, 0].max())
        min_y, max_y = float(lasso_arr[:, 1].min()), float(lasso_arr[:, 1].max())
        coarse = visible & (scr_x >= min_x) & (scr_x <= max_x) & (scr_y >= min_y) & (scr_y <= max_y)
        if not np.any(coarse):
            self.selected_indices = np.array([], dtype=np.int64)
            self._clear_selection_visuals()
            return

        candidate_idx = np.where(coarse)[0]
        candidate_scr = np.column_stack((scr_x[candidate_idx], scr_y[candidate_idx]))
        inside = path.contains_points(candidate_scr, radius=0)
        self.selected_indices = candidate_idx[inside]
        if len(self.selected_indices) > 0:
            self._highlight_selection()
        else:
            self._clear_selection_visuals()
        
    def clear_selection(self):
        """清除当前所有选区和高亮，重置选择状态"""
        self.selected_indices = np.array([], dtype=int)
        self._clear_selection_visuals()

    def _highlight_selection(self):
        self._clear_selection_visuals()
        if len(self.selected_indices) == 0: return
        draw_indices = self.selected_indices
        if len(draw_indices) > self._max_highlight_points:
            # Keep selection result full-resolution for edit operations,
            # but render only a sampled subset to keep interaction smooth.
            step = max(1, len(draw_indices) // self._max_highlight_points)
            draw_indices = draw_indices[::step]
        sub = self.data_manager.mesh.extract_points(draw_indices)
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
        self.selection_deleted.emit()


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
