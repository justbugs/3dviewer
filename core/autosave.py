import os
import json
import numpy as np

class AutosaveManager:
    def __init__(self, main_window):
        self.mw = main_window

    def _autosave_dir(self):
        root = None
        try:
            if hasattr(self.mw, '_get_project_root_dir'):
                root = self.mw._get_project_root_dir()
        except Exception:
            root = None
        if not root:
            root = getattr(self.mw, 'scan_dir', None)
        if not root:
            return ""
        return os.path.join(root, "autosave")

    def save(self):
        """Background save of tool state and point mask."""
        if getattr(self.mw, '_suspend_autosave', False):
            return
        if getattr(self.mw, '_is_closing', False):
            return
            
        if not getattr(self.mw, 'scan_dir', None) or not getattr(self.mw, 'scan_name', None):
            return 

        autosave_dir = self._autosave_dir()
        if not autosave_dir:
            return
        os.makedirs(autosave_dir, exist_ok=True)

        mask_path = os.path.join(autosave_dir, f"{self.mw.scan_name}_mask.npz")
        state_path = os.path.join(autosave_dir, f"{self.mw.scan_name}_state.json")

        # 1. Save mask
        mesh = self.mw.data_manager.mesh
        if mesh is not None and '_orig_idx' in mesh.point_data:
            orig_idx = mesh.point_data['_orig_idx']
            np.savez_compressed(mask_path, orig_idx=orig_idx)

        # 2. Save Tool States
        state = {
            "version": "1.0",
            "camera": {},
            "measure": [],
            "marker": [],
            "ref": {},
            "calibration_matrix": []
        }

        # Camera
        if mesh is not None and self.mw.canvas.plotter.camera:
            cam = self.mw.canvas.plotter.camera
            state["camera"] = {
                "position": list(cam.GetPosition()),
                "focal_point": list(cam.GetFocalPoint()),
                "view_up": list(cam.GetViewUp()),
                "parallel_scale": cam.GetParallelScale()
            }

        # Measure 
        for seg in self.mw.tool_measure.segments:
            seg_data = {
                "type": seg.get('type', 'poly'),
                "color": seg.get('color', '#ffff00')
            }
            if seg_data['type'] == 'poly':
                seg_data['points'] = [list(p) for p in seg.get('points', [])]
            elif seg_data['type'] in ['perp', 'direct', 'two_point']:
                pts = seg.get('arrow_pts', {})
                if 'pt' in pts:
                    seg_data['pt'] = list(pts.get('pt', [0,0,0]))
                    seg_data['h'] = list(pts.get('h', [0,0,0]))
                if 'p1' in pts:
                    seg_data['p1'] = list(pts.get('p1', [0,0,0]))
                    seg_data['p2'] = list(pts.get('p2', [0,0,0]))
                seg_data['dist'] = seg.get('distance', 0)
            state["measure"].append(seg_data)

        # Marker
        for mk in self.mw.tool_marker.markers:
            # First actor is the point (sphere)
            center = mk['actors'][0].GetCenter()
            state["marker"].append({
                "pos": list(center),
                "label": mk['label'],
                "desc": mk.get('desc', ''),
                "image": mk.get('image', '')
            })

        # Ref
        state["ref"] = []
        for ref in getattr(self.mw.tool_ref, 'refs', []):
            if ref['type'] == 'line':
                state["ref"].append({"type": "line", "p1": list(ref['p1']), "p2": list(ref['p2'])})
            elif ref['type'] == 'point':
                state["ref"].append({"type": "point", "pt": list(ref['pt'])})

        # Calibration transform (ground + north)
        try:
            mat = getattr(self.mw.tool_calibration, 'accumulated_matrix', None)
            if mat is not None:
                state["calibration_matrix"] = np.array(mat, dtype=float).tolist()
        except Exception:
            pass

        with open(state_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def clear_autosave(self):
        """Delete autosave files to prevent resuming."""
        if not getattr(self.mw, 'scan_dir', None) or not getattr(self.mw, 'scan_name', None):
            return
        autosave_dir = self._autosave_dir()
        if not autosave_dir:
            return
        mask_path = os.path.join(autosave_dir, f"{self.mw.scan_name}_mask.npz")
        state_path = os.path.join(autosave_dir, f"{self.mw.scan_name}_state.json")
        edit_ply = os.path.join(autosave_dir, f"{self.mw.scan_name}_edit.ply")
        for p in [mask_path, state_path, edit_ply]:
            if os.path.exists(p):
                try: os.remove(p)
                except Exception: pass

    def has_autosave(self):
        if not getattr(self.mw, 'scan_dir', None) or not getattr(self.mw, 'scan_name', None):
            return False
        autosave_dir = self._autosave_dir()
        if not autosave_dir:
            return False
        mask_path = os.path.join(autosave_dir, f"{self.mw.scan_name}_mask.npz")
        state_path = os.path.join(autosave_dir, f"{self.mw.scan_name}_state.json")
        return os.path.exists(mask_path) and os.path.exists(state_path)

    def restore(self):
        """Restore tool state and point mask."""
        if not self.has_autosave(): return False
        
        autosave_dir = self._autosave_dir()
        mask_path = os.path.join(autosave_dir, f"{self.mw.scan_name}_mask.npz")
        state_path = os.path.join(autosave_dir, f"{self.mw.scan_name}_state.json")

        # 1. Restore mask
        mesh = self.mw.data_manager.mesh
        if mesh is not None and '_orig_idx' in mesh.point_data:
            try:
                data = np.load(mask_path)
                if 'orig_idx' in data:
                    saved_idx = data['orig_idx']
                    current_idx = mesh.point_data['_orig_idx']
                    keep = np.isin(current_idx, saved_idx)
                    self.mw.data_manager.mesh = mesh.extract_points(keep)
                    self.mw.canvas.render_mesh(self.mw.data_manager)
            except Exception as e:
                print(f"Failed to load mask: {e}")

        # 2. Restore Tool States
        original_render = None
        try:
            self.mw._suspend_autosave = True
            self.mw._bulk_ui_update = True
            plotter = self.mw.canvas.plotter
            original_render = plotter.render
            plotter.render = lambda *args, **kwargs: None

            with open(state_path, 'r', encoding='utf-8') as f:
                state = json.load(f)

            # Restore calibration transform before rebuilding overlays when restoring from Stage 1 raw load.
            # In Stage 2 restore paths mesh is typically already transformed, so skip to avoid double-apply.
            try:
                calib = state.get('calibration_matrix', [])
                if calib and getattr(self.mw, 'current_stage', '') == 'PREPARE' and self.mw.data_manager.mesh is not None:
                    mat = np.array(calib, dtype=float)
                    if mat.shape == (4, 4):
                        self.mw.data_manager.mesh.transform(mat, inplace=True)
                        if hasattr(self.mw, 'tool_calibration'):
                            self.mw.tool_calibration.accumulated_matrix = mat
                        self.mw.canvas.render_mesh(self.mw.data_manager)
            except Exception as e:
                print(f"Restore calibration matrix failed: {e}")

            # ref
            for ref_data in state.get('ref', []):
                if ref_data.get('type') == 'line':
                    self.mw.tool_ref.active_points = [np.array(ref_data['p1']), np.array(ref_data['p2'])]
                    self.mw.tool_ref._create_ref_line(np.array(ref_data['p1']), np.array(ref_data['p2']))
                    self.mw.tool_ref.active_points = []
                elif ref_data.get('type') == 'point':
                    self.mw.tool_ref._create_ref_point(np.array(ref_data['pt']))

            # marker
            for mk in state.get('marker', []):
                self.mw.tool_marker.add_marker(mk['pos'], mk['label'], mk.get('desc',''), mk.get('image',''))

            # measure
            for seg in state.get('measure', []):
                mtype = seg.get('type', 'poly')
                color = seg.get('color', '#ffff00')
                old_color = self.mw.tool_measure.style_color
                self.mw.tool_measure.style_color = color
                
                if mtype == 'poly':
                    pts = [np.array(p) for p in seg.get('points', [])]
                    if len(pts) > 1:
                        self.mw.tool_measure._create_segment_visuals(pts, is_new=True)
                elif mtype == 'perp':
                    if 'pt' in seg and 'h' in seg:
                        self.mw.tool_measure._restore_perp(np.array(seg['pt']), np.array(seg['h']), seg.get('dist', 0), color)
                elif mtype == 'direct':
                    if 'p1' in seg and 'p2' in seg:
                        self.mw.tool_measure._restore_direct(np.array(seg['p1']), np.array(seg['p2']), seg.get('dist', 0), color)
                elif mtype == 'two_point':
                    if 'p1' in seg and 'p2' in seg:
                        self.mw.tool_measure._restore_two_point(np.array(seg['p1']), np.array(seg['p2']), seg.get('dist', 0), color)
                
                self.mw.tool_measure.style_color = old_color

            # camera
            cam_data = state.get('camera', {})
            if cam_data and self.mw.canvas.plotter.camera:
                cam = self.mw.canvas.plotter.camera
                cam.SetPosition(cam_data['position'])
                cam.SetFocalPoint(cam_data['focal_point'])
                cam.SetViewUp(cam_data['view_up'])
                cam.SetParallelScale(cam_data['parallel_scale'])
            
            # Single final render after all restore operations are completed.
            plotter.render = original_render
            self.mw.canvas.plotter.render()
            
        except Exception as e:
            print(f"Restore state failed: {e}")
            return False
        finally:
            try:
                if original_render is not None:
                    self.mw.canvas.plotter.render = original_render
            except Exception:
                pass
            self.mw._bulk_ui_update = False
            self.mw._suspend_autosave = False
            
        return True
