import vtk
import numpy as np
import pyvista as pv
from PySide6.QtCore import QObject, Signal, Qt
from .base import BaseTool

class ReferenceTool(BaseTool, QObject):
    # 淇″彿锛氱被鍨?'line'/'point'), ID, 鏁版嵁1(p1/pt), 鏁版嵁2(p2/None)
    ref_added = Signal(str, int, object, object) 

    def __init__(self, canvas, data_manager):
        BaseTool.__init__(self, canvas, data_manager)
        QObject.__init__(self)
        
        self.mode = 'line' # 'line' or 'point'
        self.active_points = []
        self.refs = [] 
        self.count_line = 0
        self.count_point = 0
        
        # 銆愭牳蹇冧慨澶嶃€戝垵濮嬪寲鐘舵€佸彉閲?
        self.is_active = False
        self.pan_start_pos = None

        self.style_color = "#ffffff"
        self.style_tube_radius = 0.03
        self.style_font_size = 20
        self.style_text_color = "#ffffff"

    def update_style_defaults(self, key, value):
        if key == 'color': self.style_color = value
        elif key == 'font': self.style_font_size = int(value)
        elif key == 'text_color': self.style_text_color = value
        elif key == 'linewidth': self.style_tube_radius = max(int(value) * 0.01, 0.005)

    def set_mode(self, mode):
        self.mode = mode
        self.active_points = []
        # 鍒囨崲瀛愭ā寮忔椂锛屽鏋滃綋鍓嶅浜庢縺娲荤姸鎬侊紝鍒锋柊涓€涓嬬姸鎬侊紙姣斿鏇存柊鍏夋爣锛?
        if self.is_active: 
            # 濡傛灉褰撳墠鏄墦鐐规ā寮忥紝鍒囨崲鍏夋爣鏍峰紡
            if self.plotter.interactor.GetInteractorStyle().IsA("vtkInteractorStyleTrackballCamera"):
                 self._update_cursor_for_draw()
            self.plotter.render()

    def activate(self):
        if not self.plotter: return
        self.is_active = True
        # 榛樿杩涘叆 View 妯″紡锛岀瓑寰呯敤鎴风偣鍑婚《閮ㄢ€滄墦鐐光€濇寜閽墠寮€濮嬬敾
        self.set_interaction_mode('view')


    def deactivate(self):
        self.is_active = False
        self.active_points = []
        # 娓呯悊涓存椂鐐?
        self.plotter.remove_actor("temp_ref_pt")
        
        self.plotter.enable_trackball_style()
        self.canvas.setCursor(Qt.ArrowCursor)
        super().deactivate()

    # --- 鍏ㄥ眬浜や簰鎺ュ彛 (蹇呴』瀹炵幇) ---
    def set_interaction_mode(self, mode):
        """鍝嶅簲椤堕儴鏍忥細鏃嬭浆 / 骞崇Щ / 鎵撶偣"""
        self.clear_observers()
        iren = self.plotter.interactor
        
        # 淇濆瓨鐩告満
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
            # 瀹氱偣妯″紡
            style = vtk.vtkInteractorStyleTrackballCamera()
            iren.SetInteractorStyle(style)
            
            # 鍔寔宸﹂敭锛氫笉鍐嶆棆杞紝鏀逛负鐐瑰嚮
            try:
                iren.RemoveObservers("LeftButtonPressEvent")
                iren.RemoveObservers("LeftButtonReleaseEvent")
            except Exception:
                pass
            self.observers.append(iren.AddObserver("LeftButtonPressEvent", self.on_click))
            
            self._update_cursor_for_draw()
            
        # 鎭㈠鐩告満
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
                # 涓存椂鐢荤偣
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
        idx = self._next_free_index('line')
        self.count_line = idx
        vec = p2 - p1
        length = np.linalg.norm(vec)
        if length < 1e-3: return

        # Use tube (same as measure tool) so line_width matches visually
        line_mesh = pv.Line(p1, p2)
        tube = line_mesh.tube(radius=self.style_tube_radius)
        actor = self.plotter.add_mesh(tube, color=self.style_color, lighting=False, reset_camera=False)
        self._apply_xray(actor)
        
        data = {'type': 'line', 'p1': p1, 'p2': p2, 'actor': actor, 'actors': [actor], 'idx': idx, 'color': self.style_color}
        self.refs.append(data)
        self.ref_added.emit('line', idx, p1, p2)

    def _create_ref_point(self, pt):
        idx = self._next_free_index('point')
        self.count_point = idx
        
        actor_pt = self.plotter.add_mesh(pv.PolyData([pt]), color=self.style_color, point_size=15 + self.style_tube_radius*100, 
                                         render_points_as_spheres=True, lighting=False, reset_camera=False)
        self._apply_xray(actor_pt)
        
        data = {'type': 'point', 'pt': pt, 'actors': [actor_pt], 'idx': idx, 
                'color': self.style_color}
        self.refs.append(data)
        self.ref_added.emit('point', idx, pt, None)

    def _next_free_index(self, rtype):
        used = {int(r.get('idx', 0)) for r in self.refs if r.get('type') == rtype}
        idx = 1
        while idx in used:
            idx += 1
        return idx

    def _apply_xray(self, actor):
        mapper = actor.GetMapper()
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(0, -66000)

    def set_visible(self, visible):
        vis = bool(visible)
        for ref in self.refs:
            for actor in ref.get('actors', []):
                try:
                    actor.SetVisibility(vis)
                except Exception:
                    pass

    def apply_style(self, key, value, tree_data, render=True):
        """Apply style to a ref item. tree_data is the summary dict from the tree item."""
        # The tree stores {'type':'ref','subtype':...,'idx':...} but we need the live ref dict
        subtype = tree_data.get('subtype')
        idx = tree_data.get('idx')
        ref_data = next((r for r in self.refs if r.get('type') == subtype and r.get('idx') == idx), None)
        if not ref_data: return
        elif key == 'color':
            rgb = tuple(int(value.lstrip('#')[i:i+2], 16) / 255.0 for i in (0, 2, 4))
            ref_data['color'] = value
            actors = ([ref_data['actor']] if 'actor' in ref_data else []) + ref_data.get('actors', [])
            for a in actors:
                try:
                    if hasattr(a.GetMapper(), 'SetResolveCoincidentTopologyToPolygonOffset'):
                        a.GetProperty().SetColor(*rgb)
                except: pass
        elif key == 'linewidth':
            if subtype == 'line' and 'actor' in ref_data:
                radius = max(int(value) * 0.01, 0.005)
                p1, p2 = ref_data['p1'], ref_data['p2']
                color = ref_data.get('color', self.style_color)
                
                self.plotter.remove_actor(ref_data['actor'])
                line_mesh = pv.Line(p1, p2)
                tube = line_mesh.tube(radius=radius)
                new_actor = self.plotter.add_mesh(tube, color=color, lighting=False, reset_camera=False)
                self._apply_xray(new_actor)
                ref_data['actor'] = new_actor
            elif subtype == 'point':
                pt_size = max(int(value) * 2, 5)
                for a in ref_data.get('actors', []):
                    try:
                        if hasattr(a, 'GetProperty') and a.GetProperty() and a.GetProperty().GetPointSize() >= 5:
                            a.GetProperty().SetPointSize(pt_size)
                    except: pass
        elif key == 'font':
            if subtype == 'point' and 'label_info' in ref_data:
                font_size = int(value)
                label_info = ref_data['label_info']
                old_lbl = ref_data.get('label_actor')
                if old_lbl:
                    try: self.plotter.renderer.RemoveActor(old_lbl)
                    except: pass
                    if old_lbl in ref_data.get('actors', []):
                        ref_data['actors'].remove(old_lbl)
                
                new_lbl = vtk.vtkTextActor()
                new_lbl.SetInput(label_info['text'])
                
                prop = new_lbl.GetTextProperty()
                prop.SetFontSize(font_size)
                tc = ref_data.get('text_color', self.style_text_color).lstrip('#')
                prop.SetColor(int(tc[0:2],16)/255.0, int(tc[2:4],16)/255.0, int(tc[4:6],16)/255.0)
                prop.SetJustificationToCentered()
                prop.SetVerticalJustificationToCentered()
                
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
                    
                ref_data['label_actor'] = new_lbl
                if 'actors' not in ref_data:
                    ref_data['actors'] = []
                ref_data['actors'].append(new_lbl)
        elif key == 'text_color':
            ref_data['text_color'] = value
            lbl = ref_data.get('label_actor')
            if lbl is not None:
                try:
                    h = value.lstrip('#')
                    lbl.GetTextProperty().SetColor(int(h[0:2],16)/255.0, int(h[2:4],16)/255.0, int(h[4:6],16)/255.0)
                except Exception:
                    pass
                
        if render:
            self.plotter.render()

    def redraw_all(self):
        """Re-add all reference actors to the renderer after a plotter.clear()"""
        new_refs = []
        for ref in self.refs:
            ref_type = ref.get('type')
            actors = []
            
            # Recreate Line
            if ref_type == 'line':
                color = ref.get('color', self.style_color)
                # Ensure the line tube is recreated properly to keep line-width/color
                p1, p2 = ref['p1'], ref['p2']
                line_mesh = pv.Line(p1, p2)
                tube = line_mesh.tube(radius=self.style_tube_radius)
                new_actor = self.plotter.add_mesh(tube, color=color, lighting=False, reset_camera=False)
                self._apply_xray(new_actor)
                ref['actor'] = new_actor
                new_refs.append(ref)
                
            # Recreate Point
            elif ref_type == 'point':
                pt = ref['pt']
                color = ref.get('color', self.style_color)
                
                actor_pt = self.plotter.add_mesh(pv.PolyData([pt]), color=color, point_size=15 + self.style_tube_radius*100, 
                                                 render_points_as_spheres=True, lighting=False, reset_camera=False)
                self._apply_xray(actor_pt)
                actors.append(actor_pt)
                
                if 'label_info' in ref:
                    label_info = ref['label_info']
                    new_lbl = vtk.vtkTextActor()
                    new_lbl.SetInput(label_info['text'])
                    
                    prop = new_lbl.GetTextProperty()
                    prop.SetFontSize(self.style_font_size)
                    tc = ref.get('text_color', self.style_text_color).lstrip('#')
                    prop.SetColor(int(tc[0:2],16)/255.0, int(tc[2:4],16)/255.0, int(tc[4:6],16)/255.0)
                    prop.SetJustificationToCentered()
                    prop.SetVerticalJustificationToCentered()
                    
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
                    
                    ref['label_actor'] = new_lbl
                    actors.append(new_lbl)
                ref['actors'] = actors
                new_refs.append(ref)
                
        self.refs = new_refs
        self.plotter.render()

    def highlight_segment(self, target_data, color="#FF00FF"):
        for ref in self.refs:
            # Matches based on dictionary values rather than identity because main_window passes a proxy dictionary
            is_selected = False
            if target_data is not None and target_data.get('type') == 'ref':
                is_selected = (ref.get('idx') == target_data.get('idx') and ref.get('type') == target_data.get('subtype'))
                
            base_color = ref.get('color', self.style_color)
            final_color = color if is_selected else base_color
            rgb_color = tuple(int(final_color.lstrip('#')[i:i+2], 16) / 255.0 for i in (0, 2, 4))
            
            actors = ([ref['actor']] if 'actor' in ref else []) + ref.get('actors', [])
            for actor in actors:
                try:
                    if hasattr(actor.GetMapper(), 'SetResolveCoincidentTopologyToPolygonOffset'):
                        actor.GetProperty().SetColor(*rgb_color)
                except Exception:
                    pass
        self.plotter.render()

    def delete_by_data(self, data_from_ui, render=True):
        idx = data_from_ui.get('idx')
        rtype = data_from_ui.get('subtype')
        target = None
        for r in self.refs:
            if r['idx'] == idx and r['type'] == rtype:
                target = r
                break
                
        if target:
            if 'actor' in target: self.plotter.remove_actor(target['actor'])
            if 'actors' in target: 
                for a in target['actors']: self.plotter.remove_actor(a)
            self.refs = [r for r in self.refs if r is not target]
            if render:
                self.plotter.render()

    def clear_all(self, render=True):
        while self.refs:
            self.delete_by_data({'idx': self.refs[0]['idx'], 'subtype': self.refs[0]['type']}, render=False)
        if render:
            self.plotter.render()
    def on_pan_start(self, obj, event): self.pan_start_pos = self.plotter.interactor.GetEventPosition()

    def set_visible(self, visible):
        vis = bool(visible)
        for ref in self.refs:
            if 'actor' in ref and ref['actor'] is not None:
                ref['actor'].SetVisibility(vis)
            if 'actors' in ref:
                for a in ref['actors']:
                    a.SetVisibility(vis)

    def on_pan_move(self, obj, event):
        if not getattr(self, 'pan_start_pos', None): return
        from tools.pan_utils import perform_pan
        curr = self.plotter.interactor.GetEventPosition()
        self.pan_start_pos = perform_pan(self.plotter, self.pan_start_pos, curr)
    def on_pan_end(self, obj, event): self.pan_start_pos = None

