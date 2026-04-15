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
        self.two_point_start = None
        self.two_point_start_actor = None

        # --- 鍏ㄥ眬鏍峰紡鐘舵€?---
        self.style_color = "#ffff00"
        self.style_font_size = 20
        self.style_tube_radius = 0.03
        self.style_text_color = "#ffffff"

    def update_style_defaults(self, key, value):
        """浠呮洿鏂伴粯璁ゆ牱寮忕姸鎬侊紝褰卞搷鍚庣画鏂版祴閲忥紝涓嶄慨鏀瑰凡鏈塧ctor"""
        if key == 'color':
            self.style_color = value
        elif key == 'font':
            self.style_font_size = int(value)
        elif key == 'linewidth':
            self.style_tube_radius = max(int(value) * 0.01, 0.005)
        elif key == 'text_color':
            self.style_text_color = value

    def apply_style_to_segments(self, key, value, segments):
        """瀵规寚瀹氱殑 segment 鍒楄〃搴旂敤鏍峰紡鍙樺寲"""
        if key == 'color':
            rgb = self._hex_to_rgb(value)
            for seg in segments:
                seg['color'] = value  # persist per-segment
                for actor in seg.get('actors', []):
                    try:
                        if hasattr(actor.GetMapper(), 'SetResolveCoincidentTopologyToPolygonOffset'):
                            actor.GetProperty().SetColor(*rgb)
                    except Exception:
                        pass
        elif key == 'linewidth':
            radius = max(int(value) * 0.01, 0.005)
            for seg in segments:
                stype = seg.get('type', 'poly')
                color = seg.get('color', self.style_color)
                # Remove old geometric actors (not label or point actors)
                keep, to_remove = [], []
                for a in seg.get('actors', []):
                    try:
                        if a.GetProperty().GetPointSize() > 10:
                            keep.append(a)  # point sphere
                        else:
                            to_remove.append(a)
                    except Exception:
                        keep.append(a)
                # Keep label_actor out of to_remove
                lbl = seg.get('label_actor')
                if lbl and lbl in to_remove:
                    to_remove.remove(lbl); keep.append(lbl)
                for a in to_remove:
                    try: self.plotter.renderer.RemoveActor(a)
                    except: pass
                new_actors = []
                if stype == 'poly':
                    pts = seg.get('points', [])
                    for i in range(len(pts) - 1):
                        line = pv.Line(pts[i], pts[i+1])
                        tube = line.tube(radius=radius)
                        a = self.plotter.add_mesh(tube, color=color, lighting=False, reset_camera=False)
                        self._apply_style(a); new_actors.append(a)
                elif stype == 'perp':
                    ap = seg.get('arrow_pts')
                    if ap:
                        pt, h = ap['pt'], ap['h']
                        dist = np.linalg.norm(pt - h)
                        half = dist / 2.0
                        # Normalize like original: visual shaft width = radius (world units)
                        s_r = radius / half; t_r = s_r * 3; t_l = min(0.2 / half, 0.4)
                        mid = (pt + h) / 2.0
                        for d in [(pt - h), (h - pt)]:
                            arr = pv.Arrow(start=mid, direction=d, scale=half, shaft_radius=s_r, tip_radius=t_r, tip_length=t_l)
                            a = self.plotter.add_mesh(arr, color=color, lighting=False, reset_camera=False)
                            self._apply_style(a); new_actors.append(a)
                elif stype == 'direct':
                    ap = seg.get('arrow_pts')
                    if ap:
                        p1, p2 = ap['p1'], ap['p2']
                        dist = np.linalg.norm(p2 - p1)
                        if dist > 1e-4:
                            # Normalize: visual shaft width = radius (world units)
                            s_r = radius / dist; t_r = s_r * 3; t_l = min(0.2 / dist, 0.4)
                            arr = pv.Arrow(start=p1, direction=(p2 - p1), scale=dist, shaft_radius=s_r, tip_radius=t_r, tip_length=t_l)
                            a = self.plotter.add_mesh(arr, color=color, lighting=False, reset_camera=False)
                            self._apply_style(a); new_actors.append(a)
                elif stype == 'two_point':
                    ap = seg.get('arrow_pts')
                    if ap:
                        p1, p2 = ap['p1'], ap['p2']
                        dist = np.linalg.norm(p2 - p1)
                        if dist > 1e-4:
                            half = dist / 2.0
                            s_r = radius / half
                            t_r = s_r * 3
                            t_l = min(0.2 / half, 0.4)
                            mid = (p1 + p2) / 2.0
                            for d in [(p2 - p1), (p1 - p2)]:
                                arr = pv.Arrow(start=mid, direction=d, scale=half, shaft_radius=s_r, tip_radius=t_r, tip_length=t_l)
                                a = self.plotter.add_mesh(arr, color=color, lighting=False, reset_camera=False)
                                self._apply_style(a); new_actors.append(a)
                seg['actors'] = keep + new_actors
        elif key == 'font':
            # Rebuild label actors with new font size
            font_size = int(value)
            for seg in segments:
                label_info = seg.get('label_info')  # {pt, text}
                if not label_info: continue
                # Remove old label actor
                old_lbl = seg.get('label_actor')
                if old_lbl is not None:
                    try: self.plotter.renderer.RemoveActor(old_lbl)
                    except: pass
                new_lbl = vtk.vtkTextActor()
                new_lbl.SetInput(label_info['text'])
                
                prop = new_lbl.GetTextProperty()
                prop.SetFontSize(font_size)
                self._style_text_prop(prop, seg.get('text_color', self.style_text_color))
                
                from gui.canvas import _FONT_PATH
                if _FONT_PATH:
                    try:
                        prop.SetFontFamily(vtk.VTK_FONT_FILE)
                        prop.SetFontFile(_FONT_PATH)
                    except Exception: pass
                    
                pt3d = label_info['pt']
                new_lbl.SetPosition(pt3d[0], pt3d[1])
                new_lbl.GetPositionCoordinate().SetCoordinateSystemToWorld()
                new_lbl.GetPositionCoordinate().SetValue(pt3d[0], pt3d[1], pt3d[2])
                
                self.plotter.renderer.AddActor(new_lbl)
                seg['label_actor'] = new_lbl
                # Replace in actors list
                seg['actors'] = [a for a in seg.get('actors', []) if a is not old_lbl] + [new_lbl]
        elif key == 'text_color':
            rgb = self._hex_to_rgb(value)
            for seg in segments:
                seg['text_color'] = value
                lbl = seg.get('label_actor')
                if lbl is not None:
                    try:
                        lbl.GetTextProperty().SetColor(*rgb)
                    except Exception:
                        pass
        self.plotter.render()

    @staticmethod
    def _hex_to_rgb(hex_str):
        h = hex_str.lstrip('#')
        return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))

    @staticmethod
    def _style_text_prop(prop, text_color="#ffffff"):
        h = text_color.lstrip('#')
        r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        prop.SetColor(r, g, b)
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToCentered()
        if hasattr(prop, 'SetBackgroundColor'):
            prop.SetBackgroundColor(0.0, 0.0, 0.0)
        if hasattr(prop, 'SetBackgroundOpacity'):
            prop.SetBackgroundOpacity(0.6)

    def activate(self):
        if not self.plotter: return
        print(f"[TRACE][MeasureTool] activate mode={self.mode}")
        self.is_active = True
        
        if self.mode in ['poly', 'perp', 'direct', 'two_point']:
            self.set_interaction_mode('draw')
        else:
            self.set_interaction_mode('view')
            
        self.set_xray_enabled(self.is_xray_enabled)
        self.redraw_all()
        print("[TRACE][MeasureTool] activate done")


    def deactivate(self):
        self.is_active = False
        self.plotter.enable_trackball_style()
        self.canvas.setCursor(Qt.ArrowCursor)
        self._clear_temp()
        super().deactivate()

    def set_mode(self, mode):
        print(f"[TRACE][MeasureTool] set_mode {self.mode} -> {mode}")
        self.mode = mode
        if self.is_active:
            self.deactivate()
            self.activate() 

    def set_active_ref_line(self, p1, p2):
        self.ref_p1 = np.array(p1)
        self.ref_p2 = np.array(p2)

    
    def set_active_ref_point(self, pt):
        self.ref_point_pt = np.array(pt)


    # --- 楂樹寒閫昏緫 ---
    def highlight_segment(self, target_data, color="#FF00FF"):
        for seg in self.segments:
            is_selected = (target_data is not None and seg is target_data)
                
            # Use the stored per-segment color, fall back to style_color
            base_color = seg.get('color', self.style_color)
            final_color = color if is_selected else base_color
            rgb_color = tuple(int(final_color.lstrip('#')[i:i+2], 16) / 255.0 for i in (0, 2, 4))
            for actor in seg.get('actors', []):
                try:
                    if hasattr(actor.GetMapper(), 'SetResolveCoincidentTopologyToPolygonOffset'):
                        actor.GetProperty().SetColor(*rgb_color)
                except:
                    pass
        self.plotter.render()

    def set_visible(self, visible):
        vis = bool(visible)
        for seg in self.segments:
            for actor in seg.get('actors', []):
                try:
                    actor.SetVisibility(vis)
                except Exception:
                    pass

    # --- 閫€鍑烘竻鐞嗗嚱鏁?---
    def cleanup(self, fast=False):
        if not self.plotter:
            return
        try:
            self._clear_temp(render=not fast)
            for seg in self.segments:
                for a in seg.get('actors', []):
                    try:
                        if fast:
                            self.plotter.renderer.RemoveActor(a)
                        else:
                            self.plotter.remove_actor(a)
                    except Exception:
                        pass
            self.segments = []
        except Exception:
            pass
        print("MeasureTool cleanup done")
    def _clear_temp(self, render=True):
        for a in self.current_actors:
            try:
                if render:
                    self.plotter.remove_actor(a)
                else:
                    self.plotter.renderer.RemoveActor(a)
            except Exception:
                pass
        self.current_actors = []
        self.current_points = []
        if self.two_point_start_actor is not None:
            try:
                if render:
                    self.plotter.remove_actor(self.two_point_start_actor)
                else:
                    self.plotter.renderer.RemoveActor(self.two_point_start_actor)
            except Exception:
                pass
        self.two_point_start_actor = None
        self.two_point_start = None
    def redraw_all(self):
        """Re-add measurement actors after plotter.clear()."""
        new_segments = []
        for seg in self.segments:
            seg_type = seg.get('type', 'poly')
            pts = seg.get('points')
            actors = []
            if seg_type == 'poly' and pts and len(pts) >= 2:
                # Re-draw poly measurement with current style
                for p in pts:
                    a = self.plotter.add_mesh(pv.PolyData([p]), color=self.style_color, point_size=20,
                                              render_points_as_spheres=True, lighting=False, reset_camera=False)
                    self._apply_style(a); actors.append(a)
                line = pv.MultipleLines(pts)
                tube = line.tube(radius=self.style_tube_radius)
                a_line = self.plotter.add_mesh(tube, color=self.style_color, lighting=False, reset_camera=False)
                self._apply_style(a_line); actors.append(a_line)
                seg['actors'] = actors
                new_segments.append(seg)
            elif seg_type in ('perp', 'direct', 'two_point'):
                # perp/direct store raw VTK geometry behind actors 鈥?just re-add the same actors
                # The actors are already VTK objects; re-add them to the renderer directly
                for a in seg['actors']:
                    try:
                        self.plotter.renderer.AddActor(a)
                    except Exception:
                        pass
                new_segments.append(seg)
            else:
                new_segments.append(seg)
        self.segments = new_segments
        self.plotter.render()

    def _create_segment_visuals(self, points, is_new=True):
        actors = []
        for p in points:
            a = self.plotter.add_mesh(pv.PolyData([p]), color=self.style_color, point_size=20,
                                      render_points_as_spheres=True, lighting=False, reset_camera=False)
            self._apply_style(a); actors.append(a)
            
        dist = 0
        if len(points) > 1:
            line = pv.MultipleLines(points)
            tube = line.tube(radius=self.style_tube_radius)
            a_line = self.plotter.add_mesh(tube, color=self.style_color, lighting=False, reset_camera=False)
            self._apply_style(a_line); actors.append(a_line)
            pts = np.array(points)
            for i in range(len(pts)-1): dist += np.linalg.norm(pts[i]-pts[i+1])
        
        seg_data = {'points': points, 'actors': actors, 'distance': dist, 'type': 'poly',
                    'color': self.style_color}
        self.segments.append(seg_data)
        if is_new:
            self.count += 1
            self.measurement_added.emit(f"测量-{self.count}: {dist:.2f}m", seg_data)

    # --- 浜や簰锛氬垹闄?---
    def delete_by_data(self, data, render=True):
        if data in self.segments:
            for a in data['actors']: self.plotter.remove_actor(a)
            self.segments.remove(data)
            if render:
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

    # --- 鍩虹缁樺埗閫昏緫 ---
    def add_measure_point(self, point):
        self.current_points.append(point)
        a = self.plotter.add_mesh(pv.PolyData([point]), color=self.style_color, point_size=20,
                                   render_points_as_spheres=True, lighting=False, reset_camera=False)
        self._apply_style(a); self.current_actors.append(a)
        if len(self.current_points) > 1:
            line = pv.Line(self.current_points[-2], self.current_points[-1])
            tube = line.tube(radius=self.style_tube_radius)
            l_actor = self.plotter.add_mesh(tube, color=self.style_color, lighting=False, reset_camera=False)
            self._apply_style(l_actor); self.current_actors.append(l_actor)
        self.plotter.render()

    def finish_segment(self):
        if self.mode == 'poly' and len(self.current_points) > 1:
            self._create_segment_visuals(self.current_points, is_new=True)
            self._clear_temp(); self.plotter.render()

    def clear_all(self, render=True):
        for s in self.segments:
            for a in s.get('actors', []):
                try:
                    if render:
                        self.plotter.remove_actor(a)
                    else:
                        self.plotter.renderer.RemoveActor(a)
                except Exception:
                    pass
        self.segments = []
        self._clear_temp(render=render)
        if render:
            self.plotter.render()
    def set_interaction_mode(self, mode):
        print(f"[TRACE][MeasureTool] set_interaction_mode mode={mode}")
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
            try:
                iren.RemoveObservers("LeftButtonPressEvent")
                iren.RemoveObservers("LeftButtonReleaseEvent")
            except Exception:
                pass
            self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_press, 100))
            self.observers.append(iren.AddObserver("LeftButtonReleaseEvent", self.on_release, 100))
            self.canvas.setCursor(Qt.CrossCursor)

        camera.SetPosition(pos); camera.SetFocalPoint(focal); camera.SetViewUp(view_up); self.plotter.render()

    def set_visible(self, visible):
        for seg in self.segments:
            for actor in seg['actors']: actor.SetVisibility(visible)
        for actor in self.current_actors: actor.SetVisibility(visible)
        if self.two_point_start_actor is not None:
            self.two_point_start_actor.SetVisibility(visible)
        if hasattr(self, 'ref_p1_actor') and self.ref_p1_actor: self.ref_p1_actor.SetVisibility(visible)
        if hasattr(self, 'ref_p2_actor') and self.ref_p2_actor: self.ref_p2_actor.SetVisibility(visible)
        if hasattr(self, 'ref_line_actor') and self.ref_line_actor: self.ref_line_actor.SetVisibility(visible)
        if hasattr(self, 'distance_actor') and self.distance_actor: self.distance_actor.SetVisibility(visible)

    def set_xray_enabled(self, enabled):
        self.is_xray_enabled = enabled
        for seg in self.segments:
            for actor in seg['actors']: self._apply_style(actor)
        for a in self.current_actors: self._apply_style(a)
        if self.two_point_start_actor is not None:
            self._apply_style(self.two_point_start_actor)
        self.plotter.render()

    def _apply_style(self, actor):
        mapper = actor.GetMapper()
        if not hasattr(mapper, 'SetResolveCoincidentTopologyToPolygonOffset'):
            return
            
        if self.is_xray_enabled:
            mapper.SetResolveCoincidentTopologyToPolygonOffset()
            mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(0, -66000)
        else: 
            if hasattr(mapper, 'SetResolveCoincidentTopologyToOff'):
                mapper.SetResolveCoincidentTopologyToOff()

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
            elif self.mode == 'two_point': self._handle_two_point(np.array(final_pt))

    def _handle_two_point(self, pt):
        if self.two_point_start is None:
            self.two_point_start = pt.copy()
            self.two_point_start_actor = self.plotter.add_mesh(
                pv.PolyData([pt]),
                color=self.style_color,
                point_size=15,
                render_points_as_spheres=True,
                reset_camera=False
            )
            self._apply_style(self.two_point_start_actor)
            self.plotter.render()
            return

        p1 = self.two_point_start.copy()
        p2 = pt.copy()
        dist = np.linalg.norm(p2 - p1)
        if dist < 1e-4:
            return

        TARGET_SHAFT_RAD = 0.02
        TARGET_TIP_RAD = 0.06
        TARGET_TIP_LEN = 0.2

        half_dist = dist / 2.0
        s_rad = TARGET_SHAFT_RAD / half_dist
        t_rad = TARGET_TIP_RAD / half_dist
        t_len = TARGET_TIP_LEN / half_dist
        midpoint = (p1 + p2) / 2.0

        arrow1 = pv.Arrow(start=midpoint, direction=(p2 - p1), scale=half_dist, shaft_radius=s_rad, tip_radius=t_rad, tip_length=t_len)
        arrow2 = pv.Arrow(start=midpoint, direction=(p1 - p2), scale=half_dist, shaft_radius=s_rad, tip_radius=t_rad, tip_length=t_len)

        a1 = self.plotter.add_mesh(arrow1, color=self.style_color, lighting=False, reset_camera=False); self._apply_style(a1)
        a2 = self.plotter.add_mesh(arrow2, color=self.style_color, lighting=False, reset_camera=False); self._apply_style(a2)

        a_p1 = self.two_point_start_actor
        a_p2 = self.plotter.add_mesh(pv.PolyData([p2]), color=self.style_color, point_size=15, render_points_as_spheres=True, reset_camera=False); self._apply_style(a_p2)

        lbl_pt = midpoint.copy(); lbl_pt[2] += 0.3
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput(f"{dist:.2f}m")
        prop = text_actor.GetTextProperty()
        prop.SetFontSize(self.style_font_size)
        self._style_text_prop(prop, self.style_text_color)

        from gui.canvas import _FONT_PATH
        if _FONT_PATH:
            try:
                prop.SetFontFamily(vtk.VTK_FONT_FILE)
                prop.SetFontFile(_FONT_PATH)
            except Exception:
                pass

        text_actor.SetPosition(lbl_pt[0], lbl_pt[1])
        text_actor.GetPositionCoordinate().SetCoordinateSystemToWorld()
        text_actor.GetPositionCoordinate().SetValue(lbl_pt[0], lbl_pt[1], lbl_pt[2])
        self.plotter.renderer.AddActor(text_actor)

        data = {
            'actors': [a1, a2, a_p1, a_p2, text_actor],
            'distance': dist,
            'type': 'two_point',
            'color': self.style_color,
            'label_info': {'pt': lbl_pt, 'text': f"{dist:.2f}m"},
            'label_actor': text_actor,
            'text_color': self.style_text_color,
            'arrow_pts': {'p1': p1.copy(), 'p2': p2.copy()}
        }
        self.segments.append(data)
        self.measurement_added.emit(f"两点距: {dist:.2f}m", data)

        self.two_point_start = None
        self.two_point_start_actor = None

    def _handle_perp_click(self, pt):
        if self.ref_p1 is None:
            print("请先在列表中选中一条基准线")
            return
        
        # 寮哄埗骞宠浜庡湴闈細鍙傝€冧娇鐢ㄥ熀鍑嗙嚎 p1 鐨?Z 鍧愭爣
        ref_z = self.ref_p1[2]
        pt[2] = ref_z
        p1 = self.ref_p1.copy(); p1[2] = ref_z
        p2 = self.ref_p2.copy(); p2[2] = ref_z
        
        ab = p2 - p1; ab_norm_sq = np.dot(ab, ab)
        if ab_norm_sq < 1e-6: return 
        t = np.dot(pt - p1, ab) / ab_norm_sq
        h = p1 + t * ab
        
        dist = np.linalg.norm(pt - h)
        if dist < 1e-4: return
        
        # 鍙屽悜绠ご璁捐 (棰滆壊 #00FF00)
        TARGET_SHAFT_RAD = 0.02
        TARGET_TIP_RAD = 0.06
        TARGET_TIP_LEN = 0.2
        
        half_dist = dist / 2.0
        s_rad = TARGET_SHAFT_RAD / half_dist
        t_rad = TARGET_TIP_RAD / half_dist
        t_len = TARGET_TIP_LEN / half_dist
        
        midpoint = (pt + h) / 2.0
        
        # 灞呬腑鍚戝鐨勪袱涓澶?
        arrow1 = pv.Arrow(start=midpoint, direction=(pt - h), scale=half_dist, shaft_radius=s_rad, tip_radius=t_rad, tip_length=t_len)
        arrow2 = pv.Arrow(start=midpoint, direction=(h - pt), scale=half_dist, shaft_radius=s_rad, tip_radius=t_rad, tip_length=t_len)
        
        a1 = self.plotter.add_mesh(arrow1, color=self.style_color, lighting=False, reset_camera=False); self._apply_style(a1)
        a2 = self.plotter.add_mesh(arrow2, color=self.style_color, lighting=False, reset_camera=False); self._apply_style(a2)
        a_pt = self.plotter.add_mesh(pv.PolyData([pt]), color=self.style_color, point_size=15, render_points_as_spheres=True, reset_camera=False); self._apply_style(a_pt)
        
        # 璺濈鏂囧瓧鏍囨敞
        lbl_pt = midpoint.copy(); lbl_pt[2] += 0.3
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput(f"{dist:.2f}m")
        prop = text_actor.GetTextProperty()
        prop.SetFontSize(self.style_font_size)
        self._style_text_prop(prop, self.style_text_color)
        
        from gui.canvas import _FONT_PATH
        if _FONT_PATH:
            try:
                prop.SetFontFamily(vtk.VTK_FONT_FILE)
                prop.SetFontFile(_FONT_PATH)
            except Exception: pass
            
        text_actor.SetPosition(lbl_pt[0], lbl_pt[1])
        text_actor.GetPositionCoordinate().SetCoordinateSystemToWorld()
        text_actor.GetPositionCoordinate().SetValue(lbl_pt[0], lbl_pt[1], lbl_pt[2])
        self.plotter.renderer.AddActor(text_actor)
        
        seg_data = {'actors': [a1, a2, a_pt, text_actor], 'distance': dist, 'type': 'perp',
                    'color': self.style_color,
                    'label_info': {'pt': lbl_pt, 'text': f"{dist:.2f}m"},
                    'label_actor': text_actor,
                    'text_color': self.style_text_color,
                    'arrow_pts': {'pt': pt.copy(), 'h': h.copy()}}  # for linewidth rebuild
        self.segments.append(seg_data); self.measurement_added.emit(f"垂距: {dist:.2f}m", seg_data)

    def _handle_direct(self, pt):
        if self.ref_point_pt is None:
            print("请先在列表中选中一个基准点")
            return
        
        # 寮哄埗骞宠浜庡湴闈?
        pt[2] = self.ref_point_pt[2]
        
        dist = np.linalg.norm(pt - self.ref_point_pt)
        if dist < 1e-4: return
        
        TARGET_SHAFT_RAD = 0.02
        TARGET_TIP_RAD = 0.06
        TARGET_TIP_LEN = 0.2
        
        s_rad = TARGET_SHAFT_RAD / dist
        t_rad = TARGET_TIP_RAD / dist
        t_len = TARGET_TIP_LEN / dist
        
        arrow = pv.Arrow(start=self.ref_point_pt, direction=(pt-self.ref_point_pt), scale=dist, 
                         shaft_radius=s_rad, tip_radius=t_rad, tip_length=t_len)
        actor = self.plotter.add_mesh(arrow, color=self.style_color, lighting=False, reset_camera=False); self._apply_style(actor)
        a_pt = self.plotter.add_mesh(pv.PolyData([pt]), color=self.style_color, point_size=15, render_points_as_spheres=True, reset_camera=False); self._apply_style(a_pt)
        
        # 璺濈鏂囧瓧鏍囨敞
        mid_pt = (self.ref_point_pt + pt) / 2.0; mid_pt[2] += 0.3
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput(f"{dist:.2f}m")
        prop = text_actor.GetTextProperty()
        prop.SetFontSize(self.style_font_size)
        self._style_text_prop(prop, self.style_text_color)
        
        from gui.canvas import _FONT_PATH
        if _FONT_PATH:
            try:
                prop.SetFontFamily(vtk.VTK_FONT_FILE)
                prop.SetFontFile(_FONT_PATH)
            except Exception: pass
            
        text_actor.SetPosition(mid_pt[0], mid_pt[1])
        text_actor.GetPositionCoordinate().SetCoordinateSystemToWorld()
        text_actor.GetPositionCoordinate().SetValue(mid_pt[0], mid_pt[1], mid_pt[2])
        self.plotter.renderer.AddActor(text_actor)
        
        data = {'actors': [actor, a_pt, text_actor], 'distance': dist, 'type': 'direct',
                'color': self.style_color,
                'label_info': {'pt': mid_pt, 'text': f"{dist:.2f}m"},
                'label_actor': text_actor,
                'text_color': self.style_text_color,
                'arrow_pts': {'p1': self.ref_point_pt.copy(), 'p2': pt.copy()}}  # for linewidth rebuild
        self.segments.append(data)
        self.measurement_added.emit(f"斜距: {dist:.2f}m", data)
    def _restore_perp(self, pt, h, dist, color):
        old_color = self.style_color
        self.style_color = color
        
        # 鍙屽悜绠ご璁捐 
        TARGET_SHAFT_RAD = 0.02
        TARGET_TIP_RAD = 0.06
        TARGET_TIP_LEN = 0.2
        
        half_dist = dist / 2.0
        s_rad = TARGET_SHAFT_RAD / half_dist
        t_rad = TARGET_TIP_RAD / half_dist
        t_len = TARGET_TIP_LEN / half_dist
        
        midpoint = (pt + h) / 2.0
        
        arrow1 = pv.Arrow(start=midpoint, direction=(pt - h), scale=half_dist, shaft_radius=s_rad, tip_radius=t_rad, tip_length=t_len)
        arrow2 = pv.Arrow(start=midpoint, direction=(h - pt), scale=half_dist, shaft_radius=s_rad, tip_radius=t_rad, tip_length=t_len)
        
        a1 = self.plotter.add_mesh(arrow1, color=color, lighting=False, reset_camera=False); self._apply_style(a1)
        a2 = self.plotter.add_mesh(arrow2, color=color, lighting=False, reset_camera=False); self._apply_style(a2)
        a_pt = self.plotter.add_mesh(pv.PolyData([pt]), color=color, point_size=15, render_points_as_spheres=True, reset_camera=False); self._apply_style(a_pt)
        
        lbl_pt = midpoint.copy(); lbl_pt[2] += 0.3
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput(f"{dist:.2f}m")
        prop = text_actor.GetTextProperty()
        prop.SetFontSize(self.style_font_size)
        self._style_text_prop(prop, self.style_text_color)
        
        from gui.canvas import _FONT_PATH
        if _FONT_PATH:
            try:
                prop.SetFontFamily(vtk.VTK_FONT_FILE)
                prop.SetFontFile(_FONT_PATH)
            except Exception: pass
            
        text_actor.SetPosition(lbl_pt[0], lbl_pt[1])
        text_actor.GetPositionCoordinate().SetCoordinateSystemToWorld()
        text_actor.GetPositionCoordinate().SetValue(lbl_pt[0], lbl_pt[1], lbl_pt[2])
        self.plotter.renderer.AddActor(text_actor)
        
        seg_data = {'actors': [a1, a2, a_pt, text_actor], 'distance': dist, 'type': 'perp',
                    'color': color,
                    'label_info': {'pt': lbl_pt, 'text': f"{dist:.2f}m"},
                    'label_actor': text_actor,
                    'text_color': self.style_text_color,
                    'arrow_pts': {'pt': pt.copy(), 'h': h.copy()}}
        self.segments.append(seg_data); self.measurement_added.emit(f"垂距: {dist:.2f}m", seg_data)
        
        self.style_color = old_color

    def _restore_direct(self, p1, p2, dist, color):
        old_color = self.style_color
        self.style_color = color
        
        TARGET_SHAFT_RAD = 0.02
        TARGET_TIP_RAD = 0.06
        TARGET_TIP_LEN = 0.2
        
        s_rad = TARGET_SHAFT_RAD / dist
        t_rad = TARGET_TIP_RAD / dist
        t_len = TARGET_TIP_LEN / dist
        
        arrow = pv.Arrow(start=p1, direction=(p2-p1), scale=dist, 
                         shaft_radius=s_rad, tip_radius=t_rad, tip_length=t_len)
        actor = self.plotter.add_mesh(arrow, color=color, lighting=False, reset_camera=False); self._apply_style(actor)
        a_pt = self.plotter.add_mesh(pv.PolyData([p2]), color=color, point_size=15, render_points_as_spheres=True, reset_camera=False); self._apply_style(a_pt)
        
        mid_pt = (p1 + p2) / 2.0; mid_pt[2] += 0.3
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput(f"{dist:.2f}m")
        prop = text_actor.GetTextProperty()
        prop.SetFontSize(self.style_font_size)
        self._style_text_prop(prop, self.style_text_color)
        
        from gui.canvas import _FONT_PATH
        if _FONT_PATH:
            try:
                prop.SetFontFamily(vtk.VTK_FONT_FILE)
                prop.SetFontFile(_FONT_PATH)
            except Exception: pass
            
        text_actor.SetPosition(mid_pt[0], mid_pt[1])
        text_actor.GetPositionCoordinate().SetCoordinateSystemToWorld()
        text_actor.GetPositionCoordinate().SetValue(mid_pt[0], mid_pt[1], mid_pt[2])
        self.plotter.renderer.AddActor(text_actor)
        
        seg_data = {'actors': [actor, a_pt, text_actor], 'distance': dist, 'type': 'direct',
                'color': color,
                'label_info': {'pt': mid_pt, 'text': f"{dist:.2f}m"},
                'label_actor': text_actor,
                'text_color': self.style_text_color,
                'arrow_pts': {'p1': p1.copy(), 'p2': p2.copy()}}
        self.segments.append(seg_data); self.measurement_added.emit(f"斜距: {dist:.2f}m", seg_data)
        
        self.style_color = old_color

    def _restore_two_point(self, p1, p2, dist, color):
        old_color = self.style_color
        self.style_color = color

        TARGET_SHAFT_RAD = 0.02
        TARGET_TIP_RAD = 0.06
        TARGET_TIP_LEN = 0.2

        half_dist = dist / 2.0
        s_rad = TARGET_SHAFT_RAD / half_dist
        t_rad = TARGET_TIP_RAD / half_dist
        t_len = TARGET_TIP_LEN / half_dist
        midpoint = (p1 + p2) / 2.0

        arrow1 = pv.Arrow(start=midpoint, direction=(p2 - p1), scale=half_dist, shaft_radius=s_rad, tip_radius=t_rad, tip_length=t_len)
        arrow2 = pv.Arrow(start=midpoint, direction=(p1 - p2), scale=half_dist, shaft_radius=s_rad, tip_radius=t_rad, tip_length=t_len)
        a1 = self.plotter.add_mesh(arrow1, color=color, lighting=False, reset_camera=False); self._apply_style(a1)
        a2 = self.plotter.add_mesh(arrow2, color=color, lighting=False, reset_camera=False); self._apply_style(a2)
        a_p1 = self.plotter.add_mesh(pv.PolyData([p1]), color=color, point_size=15, render_points_as_spheres=True, reset_camera=False); self._apply_style(a_p1)
        a_p2 = self.plotter.add_mesh(pv.PolyData([p2]), color=color, point_size=15, render_points_as_spheres=True, reset_camera=False); self._apply_style(a_p2)

        lbl_pt = midpoint.copy(); lbl_pt[2] += 0.3
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput(f"{dist:.2f}m")
        prop = text_actor.GetTextProperty()
        prop.SetFontSize(self.style_font_size)
        self._style_text_prop(prop, self.style_text_color)

        from gui.canvas import _FONT_PATH
        if _FONT_PATH:
            try:
                prop.SetFontFamily(vtk.VTK_FONT_FILE)
                prop.SetFontFile(_FONT_PATH)
            except Exception: pass

        text_actor.SetPosition(lbl_pt[0], lbl_pt[1])
        text_actor.GetPositionCoordinate().SetCoordinateSystemToWorld()
        text_actor.GetPositionCoordinate().SetValue(lbl_pt[0], lbl_pt[1], lbl_pt[2])
        self.plotter.renderer.AddActor(text_actor)

        seg_data = {'actors': [a1, a2, a_p1, a_p2, text_actor], 'distance': dist, 'type': 'two_point',
                'color': color,
                'label_info': {'pt': lbl_pt, 'text': f"{dist:.2f}m"},
                'label_actor': text_actor,
                'text_color': self.style_text_color,
                'arrow_pts': {'p1': p1.copy(), 'p2': p2.copy()}}
        self.segments.append(seg_data); self.measurement_added.emit(f"两点距: {dist:.2f}m", seg_data)

        self.style_color = old_color

    def on_press(self, obj, event): self.start_pos = self.plotter.interactor.GetEventPosition()
    def on_release(self, obj, event):
        if not self.start_pos: return
        ep = self.plotter.interactor.GetEventPosition()
        if ((ep[0]-self.start_pos[0])**2 + (ep[1]-self.start_pos[1])**2)**0.5 < 10: self.pick_measure_point(ep)
        self.start_pos = None
    def on_pan_start(self, o, e): self.pan_start_pos = self.plotter.interactor.GetEventPosition()
    def on_pan_move(self, o, e):
        if not getattr(self, 'pan_start_pos', None): return
        from tools.pan_utils import perform_pan
        curr = self.plotter.interactor.GetEventPosition()
        self.pan_start_pos = perform_pan(self.plotter, self.pan_start_pos, curr)
    def on_pan_end(self, o, e): self.pan_start_pos = None

