import os
import re
import sys
import numpy as np
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QTimer

from core.autosave import AutosaveManager
from core.data import DataManager
from core.loader import ModelLoader
from core.processor import GeometryProcessor
from gui.canvas import PointCloudCanvas
from gui.dialogs import MarkerDialog, MarkerDetailsDialog
from gui.panels import ActionPanel, ObjectListPanel
from tools.calibration import CalibrationTool
from tools.marker import MarkerTool
from tools.measure import MeasureTool
from tools.ref_tool import ReferenceTool
from tools.selection_tool import SelectTool


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CrashSite3D - Engineering Suite (Touch Optimized)")
        self.resize(1600, 900)
        self.showMaximized()

        self.current_stage = "PREPARE"
        self.raw_file_path = None
        self.scan_dir = None
        self.scan_name = None
        self.texture_path = None
        self.has_texture_input = False
        self._restore_after_work_load = False
        self.progress_dialog = None

        self.stage1_div = 500.0
        self.stage2_div = 200.0
        self.random_target_points = 4_000_000
        self.initial_font_size = 20
        self.initial_linewidth = 3
        self._load_downsample_params()

        self._ground_calib_locked = False
        self._ground_manual_pick = False
        self._north_locked = False
        self._north_is_calibrated = False
        self._ground_history_pushed = False
        self._north_history_pushed = False
        self._ground_prev_camera_state = None
        self._stage1_select_mode = "view"
        self._top_dir_key = "N"
        self._bulk_ui_update = False
        self._suspend_autosave = False
        self._is_closing = False
        self._objects_visible = True
        self._autosave_delay_ms = 250
        self._style_lock_depth = 0
        self._style_apply_delay_ms = 80
        self._pending_style_change = None

        self.data_manager = DataManager()
        self.autosave = AutosaveManager(self)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._autosave_flush)
        self._style_apply_timer = QTimer(self)
        self._style_apply_timer.setSingleShot(True)
        self._style_apply_timer.timeout.connect(self._flush_pending_style_change)
        self._init_ui()
        if hasattr(self.panel_action, "set_mesh_output_visible"):
            self.panel_action.set_mesh_output_visible(False)

        self.tool_measure = MeasureTool(self.canvas, self.data_manager)
        self.tool_select = SelectTool(self.canvas, self.data_manager)
        self.tool_calibration = CalibrationTool(self.canvas, self.data_manager)
        self.tool_ref = ReferenceTool(self.canvas, self.data_manager)
        self.tool_marker = MarkerTool(self.canvas, self.data_manager)
        self.current_tool = None
        self._apply_initial_style_params()

        self._connect_signals()
        self.set_stage_prepare()

    def _load_downsample_params(self):
        try:
            base_dir = (
                os.path.dirname(sys.executable)
                if getattr(sys, "frozen", False)
                else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            param_path = ""
            for name in ("参数.txt", "params.txt"):
                p = os.path.join(base_dir, name)
                if os.path.exists(p):
                    param_path = p
                    break
            if not param_path:
                return
            values = []
            with open(param_path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    left = line
                    rhs = ""
                    for sep in ["：", ":"]:
                        if sep in line:
                            left, rhs = line.split(sep, 1)
                            break
                    rhs = rhs.strip().replace(",", "")
                    m = re.search(r"[-+]?\d*\.?\d+", rhs)
                    if not m:
                        continue
                    val = float(m.group(0))
                    key = left.strip()
                    if "一阶段" in key:
                        self.stage1_div = val
                    elif "二阶段" in key:
                        self.stage2_div = val
                    elif "随机" in key:
                        self.random_target_points = max(1, int(val))
                    elif "初始字号" in key:
                        self.initial_font_size = max(1, int(val))
                    elif "初始线宽" in key:
                        self.initial_linewidth = max(1, int(val))
                    else:
                        values.append(val)
            if len(values) >= 1:
                self.stage1_div = values[0]
            if len(values) >= 2:
                self.stage2_div = values[1]
            if len(values) >= 3:
                self.random_target_points = max(1, int(values[2]))
            print(
                f"[PARAM] Loaded downsample params: "
                f"Stage1={self.stage1_div}, Stage2={self.stage2_div}, "
                f"RandomTarget={self.random_target_points}, "
                f"InitFont={self.initial_font_size}, InitLineWidth={self.initial_linewidth}, "
                f"File={param_path}"
            )
        except Exception as e:
            print(f"[PARAM] Failed to parse params.txt: {e}")

    def _apply_initial_style_params(self):
        # Apply tool defaults first.
        self.tool_measure.update_style_defaults("font", self.initial_font_size)
        self.tool_ref.update_style_defaults("font", self.initial_font_size)
        self.tool_marker.update_style_defaults("font", self.initial_font_size)
        self.tool_measure.update_style_defaults("linewidth", self.initial_linewidth)
        self.tool_ref.update_style_defaults("linewidth", self.initial_linewidth)
        self.tool_marker.update_style_defaults("linewidth", self.initial_linewidth)

        # Sync right-panel sliders without emitting style-change signals.
        try:
            if hasattr(self.panel_action, "sld_font"):
                s = self.panel_action.sld_font
                fv = max(s.minimum(), min(s.maximum(), int(self.initial_font_size)))
                old = s.blockSignals(True)
                s.setValue(fv)
                s.blockSignals(old)
            if hasattr(self.panel_action, "sld_lw"):
                s = self.panel_action.sld_lw
                wv = max(s.minimum(), min(s.maximum(), int(self.initial_linewidth)))
                old = s.blockSignals(True)
                s.setValue(wv)
                s.blockSignals(old)
        except Exception:
            pass

    def _enter_stage2_view_only_state(self):
        # Stage2 should start in plain rotate mode without auto-entering any measure/ref/marker workflow.
        if self.current_tool:
            try:
                self.current_tool.deactivate()
            except Exception:
                pass
        self.current_tool = None
        try:
            self.canvas.plotter.enable_trackball_style()
        except Exception:
            pass
        try:
            if hasattr(self.panel_action, "grp_tools"):
                checked = self.panel_action.grp_tools.checkedButton()
                if checked:
                    self.panel_action.grp_tools.setExclusive(False)
                    checked.setChecked(False)
                    self.panel_action.grp_tools.setExclusive(True)
            if hasattr(self.panel_action, "btn_g_draw"):
                self.panel_action.btn_g_draw.hide()
            if hasattr(self.panel_action, "btn_g_view"):
                self.panel_action.btn_g_view.setChecked(True)
            self.on_global_mode("view")
        except Exception:
            pass

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.top_bar_layout = QHBoxLayout()
        self.top_bar_layout.setContentsMargins(5, 5, 5, 5)
        self.lbl_stage = QLabel("阶段 1: 粗修")
        self.lbl_stage.setStyleSheet("font-size: 24px; font-weight: bold; margin-right: 20px;")
        self.top_bar_layout.addWidget(self.lbl_stage)

        btn_style = (
            "QPushButton { min-height: 70px; font-size: 20px; font-weight: bold; "
            "border-radius: 8px; padding: 10px; margin: 5px; }"
        )
        self.btn_next = QPushButton("下一步")
        self.btn_next.setStyleSheet(btn_style + "background-color: #0275d8; color: white;")
        self.btn_undo = QPushButton("撤回")
        self.btn_undo.setStyleSheet(btn_style)
        self.btn_exit = QPushButton("退出")
        self.btn_exit.setStyleSheet(btn_style + "background-color: #d9534f; color: white;")
        self.btn_exit.clicked.connect(self.close)

        # scanpath.txt is mandatory now: no manual open button in top bar
        for btn in [self.btn_next, self.btn_undo, self.btn_exit]:
            self.top_bar_layout.addWidget(btn)

        self.top_bar_layout.addStretch()
        top_btn_style = (
            "QPushButton { min-height: 56px; min-width: 96px; font-size: 18px; "
            "font-weight: bold; border-radius: 8px; padding: 6px 10px; margin: 4px; }"
        )
        self.btn_view_front = QPushButton("正视")
        self.btn_view_side = QPushButton("侧视")
        self.btn_view_top = QPushButton("俯视")
        for b in (self.btn_view_front, self.btn_view_side, self.btn_view_top):
            b.setStyleSheet(top_btn_style)
            self.top_bar_layout.addWidget(b)

        self.btn_toggle_objects = QPushButton("隐藏所有元素")
        self.btn_toggle_objects.setCheckable(True)
        self.btn_toggle_objects.setStyleSheet(top_btn_style + "background-color: #555; color: white;")
        self.top_bar_layout.addWidget(self.btn_toggle_objects)
        main_layout.addLayout(self.top_bar_layout)

        splitter = QSplitter(Qt.Horizontal)
        self.panel_list = ObjectListPanel()
        splitter.addWidget(self.panel_list)
        self.canvas = PointCloudCanvas()
        splitter.addWidget(self.canvas)
        self.panel_action = ActionPanel()
        splitter.addWidget(self.panel_action)
        splitter.setSizes([280, 1000, 380])
        main_layout.addWidget(splitter)

    def _connect_signals(self):
        self.btn_next.clicked.connect(self.process_and_advance)
        self.btn_undo.clicked.connect(self.undo_action)

        self.panel_action.calibration_triggered.connect(self.handle_calibration)
        self.panel_action.select_triggered.connect(self.handle_select_action)
        self.panel_action.select_mode_changed.connect(self.on_select_mode_changed)

        self.panel_action.global_mode_changed.connect(self.on_global_mode)
        self.panel_action.tool_selected.connect(self.on_tool_selected)
        self.panel_action.action_triggered.connect(self.on_action_triggered)
        self.panel_action.measure_style_changed.connect(self.on_measure_style_changed)
        self.panel_action.style_edit_lock_changed.connect(self._set_style_view_lock)
        self.panel_action.marker_label_changed.connect(self.tool_marker.set_label_prefix)
        self.panel_action.xray_toggled.connect(self.tool_measure.set_xray_enabled)
        self.panel_action.view_change_triggered.connect(self.on_view_change)
        self.btn_view_front.clicked.connect(lambda: self.on_view_change("front"))
        self.btn_view_side.clicked.connect(lambda: self.on_view_change("side"))
        self.btn_view_top.clicked.connect(lambda: self.on_view_change("top"))
        self.btn_toggle_objects.clicked.connect(self._on_toggle_all_objects)

        self.tool_ref.ref_added.connect(self.on_ref_added)
        self.tool_measure.measurement_added.connect(self.on_measurement_added)
        self.tool_marker.marker_added.connect(self.on_marker_added)
        self.tool_marker.request_marker_details.connect(self.on_request_marker_details)
        self.panel_list.item_clicked.connect(self.on_item_clicked)
        self.panel_list.item_deleted.connect(self.on_item_deleted)
        self.panel_list.items_deleted_batch.connect(self.on_items_deleted_batch)
        self.tool_select.request_delete_measurements.connect(self.tool_measure.delete_points_inside_polygon)

    def _capture_camera_state(self):
        cam = self.canvas.plotter.camera
        return {
            "position": tuple(cam.GetPosition()),
            "focal_point": tuple(cam.GetFocalPoint()),
            "view_up": tuple(cam.GetViewUp()),
            "parallel_projection": int(cam.GetParallelProjection()),
            "parallel_scale": float(cam.GetParallelScale()),
        }

    def _apply_dynamic_initial_view(self):
        mesh = self.data_manager.mesh
        if mesh is None or mesh.n_points <= 0:
            return
        b = mesh.bounds
        x_len = float(b[1] - b[0])
        y_len = float(b[3] - b[2])
        z_len = float(b[5] - b[4])
        diag = float(np.linalg.norm([x_len, y_len, z_len]))
        if diag <= 1e-6:
            return

        cx = (b[0] + b[1]) * 0.5
        cy = (b[2] + b[3]) * 0.5
        cz = (b[4] + b[5]) * 0.5

        view_dir = np.array([1.0, -1.0, 0.7], dtype=np.float64)
        view_dir /= np.linalg.norm(view_dir)
        dist = max(diag * 1.35, max(x_len, y_len, z_len) * 1.8)

        cam = self.canvas.plotter.camera
        cam.SetFocalPoint(cx, cy, cz)
        cam.SetPosition(*(np.array([cx, cy, cz], dtype=np.float64) + view_dir * dist))
        cam.SetViewUp(0.0, 0.0, 1.0)
        cam.SetParallelProjection(0)
        self.canvas.plotter.renderer.ResetCameraClippingRange()
        self.canvas.plotter.render()

    def _restore_camera_state(self, state):
        if not state:
            return
        cam = self.canvas.plotter.camera
        cam.SetPosition(*state["position"])
        cam.SetFocalPoint(*state["focal_point"])
        cam.SetViewUp(*state["view_up"])
        cam.SetParallelProjection(state["parallel_projection"])
        cam.SetParallelScale(state["parallel_scale"])
        self.canvas.plotter.renderer.ResetCameraClippingRange()
        self.canvas.plotter.render()

    def _apply_stage1_lock_ui(self):
        pa = self.panel_action
        if not hasattr(pa, "btn_s1_draw"):
            return

        pa.btn_s1_view.setEnabled(True)
        pa.btn_s1_pan.setEnabled(True)
        pa.btn_s1_draw.setEnabled(True)
        pa.btn_calib_start.setEnabled(True)
        if hasattr(pa, "btn_set_north"):
            pa.btn_set_north.setEnabled(True)
        if hasattr(pa, "btn_confirm_north"):
            pa.btn_confirm_north.hide()
        if hasattr(pa, "btn_cancel_north"):
            pa.btn_cancel_north.hide()

        if self._ground_calib_locked:
            pa.btn_calib_start.setEnabled(False)
            if hasattr(pa, "btn_set_north"):
                pa.btn_set_north.setEnabled(False)
            if not self._ground_manual_pick:
                pa.btn_s1_draw.setEnabled(False)
            else:
                pa.btn_s1_draw.setEnabled(True)
                pa.update_select_button_text("标点")
                pa.set_stage1_mode_selection("draw")
        else:
            pa.update_select_button_text("区域选择")

        if self._north_locked:
            pa.btn_calib_start.setEnabled(False)
            pa.btn_s1_draw.setEnabled(False)
            if hasattr(pa, "btn_set_north"):
                pa.btn_set_north.setEnabled(False)
            if hasattr(pa, "btn_confirm_north"):
                pa.btn_confirm_north.show()
            if hasattr(pa, "btn_cancel_north"):
                pa.btn_cancel_north.show()

        show_select_ops = (
            (self._stage1_select_mode == "draw")
            and (not self._ground_calib_locked)
            and (not self._north_locked)
        )
        for name in ("btn_s1_delete_inner", "btn_s1_invert", "btn_s1_undo"):
            b = getattr(pa, name, None)
            if b is not None:
                b.setVisible(show_select_ops)

    def switch_tool(self, tool):
        if self.current_tool and self.current_tool != tool:
            self.current_tool.deactivate()
        self.current_tool = tool
        if self.current_tool:
            self.current_tool.activate()

    def on_tool_selected(self, tool_type, sub_mode):
        if tool_type == "ref":
            self.tool_ref.set_mode(sub_mode)
            self.switch_tool(self.tool_ref)
        elif tool_type == "measure":
            self.tool_measure.set_mode(sub_mode)
            self.switch_tool(self.tool_measure)
        elif tool_type == "marker":
            self.switch_tool(self.tool_marker)
        elif tool_type == "edit":
            self.switch_tool(self.tool_select)
            self.tool_select.set_interaction_mode("draw" if sub_mode == "select" else "view")

    def on_global_mode(self, mode):
        if self.current_tool:
            self.current_tool.set_interaction_mode(mode)

    def on_action_triggered(self, action):
        if action == "finish":
            self.tool_measure.finish_segment()
            self._autosave_now()
        elif action == "clear":
            self.tool_measure.clear_all()
            self.panel_list.clear_all()
            self._autosave_now()
        elif action == "delete":
            self.tool_select.delete_selection()
            self._render_scene_with_overlays()
            self._autosave_now()
        elif action == "undo":
            self.undo_action()
        elif action == "go_output":
            self._enter_output_stage()
        elif action == "back_to_stage2":
            self._back_to_stage2()
        elif action.startswith("set_top_dir:"):
            self._top_dir_key = action.split(":", 1)[1]
            self._apply_top_direction_camera()
        elif action == "enter_top_edit":
            self._apply_top_direction_camera()
            self._show_top_direction_hint()
        elif action == "exit_top_edit":
            self._hide_top_direction_hint()
        elif action == "enter_side_edit":
            self._hide_top_direction_hint()
            self.on_view_change("front")
        elif action == "save_top":
            self._save_output_image(kind="top")
        elif action == "save_side":
            self._save_output_image(kind="side")
        elif action == "gen_mesh":
            self._save_output_mesh()
        elif action == "gen_primitive":
            self._save_output_image(kind="primitive")

    def on_ref_added(self, rtype, idx, d1, d2):
        txt = f"基准线 {idx}" if rtype == "line" else f"基准点 {idx}"
        data = {"type": "ref", "subtype": rtype, "d1": d1, "d2": d2, "idx": idx}
        self.panel_list.add_item("ref", txt, data)
        if rtype == "line":
            self.tool_measure.set_active_ref_line(d1, d2)
        elif rtype == "point":
            self.tool_measure.set_active_ref_point(d1)
        self._autosave_now()

    def on_measurement_added(self, text, data_ref):
        self.panel_list.add_item("measure", text, data_ref)
        self._autosave_now()

    def on_marker_added(self, text, data_ref):
        self.panel_list.add_item("marker", text, data_ref, emit_click=False)
        self._autosave_now()

    def on_item_clicked(self, item):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        cat, real_data = data
        if cat == "ref":
            if real_data["subtype"] == "line":
                self.tool_measure.set_active_ref_line(real_data["d1"], real_data["d2"])
            elif real_data["subtype"] == "point":
                self.tool_measure.set_active_ref_point(real_data["d1"])
        elif cat == "measure":
            self.tool_measure.highlight_segment(real_data)
        elif cat == "marker":
            try:
                dlg = MarkerDetailsDialog(real_data, self)
                dlg.exec()
            except Exception:
                pass

    def on_item_deleted(self, item):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        cat, real_data = data
        if cat == "measure":
            self.tool_measure.delete_by_data(real_data)
        elif cat == "marker":
            self.tool_marker.delete_by_data(real_data)
        elif cat == "ref":
            self.tool_ref.delete_by_data(real_data)
        self._autosave_now()

    def on_items_deleted_batch(self, payload):
        for cat, real_data in payload:
            if cat == "measure":
                self.tool_measure.delete_by_data(real_data, render=False)
            elif cat == "marker":
                self.tool_marker.delete_by_data(real_data, render=False)
            elif cat == "ref":
                self.tool_ref.delete_by_data(real_data, render=False)
        self.canvas.plotter.render()
        self._autosave_now()

    def set_stage_prepare(self):
        self._reset_style_view_lock()
        self._hide_top_direction_hint()
        self.current_stage = "PREPARE"
        self.lbl_stage.setText("阶段 1: 粗修 (校准/裁剪)")
        self.panel_action.switch_stage(0)
        self.panel_list.hide()
        self.switch_tool(self.tool_select)
        self.data_manager.set_max_history(1)

        self._ground_calib_locked = False
        self._ground_manual_pick = False
        self._north_locked = False
        self._north_is_calibrated = False
        self._ground_history_pushed = False
        self._north_history_pushed = False
        self._ground_prev_camera_state = None
        self._stage1_select_mode = "view"
        if hasattr(self.panel_action, "widget_calib_ops"):
            self.panel_action.widget_calib_ops.hide()
            self.panel_action.btn_calib_start.show()
        self.btn_toggle_objects.hide()
        self._objects_visible = True
        self.btn_toggle_objects.setChecked(False)
        self.btn_toggle_objects.setText("隐藏所有元素")
        self._apply_stage1_lock_ui()

    def set_stage_editor(self, work_file_path):
        self._reset_style_view_lock()
        self._hide_top_direction_hint()
        self.current_stage = "EDITOR"
        self.lbl_stage.setText("阶段 2: 精修 (测量/标注)")
        self.panel_action.switch_stage(1)
        self.panel_list.show()
        tex = self.texture_path if self.has_texture_input else None
        self.load_work_file(work_file_path, texture_path=tex)
        self.data_manager.set_max_history(5)
        self._enter_stage2_view_only_state()
        self.btn_toggle_objects.show()
        self._objects_visible = True
        self.btn_toggle_objects.setChecked(False)
        self.btn_toggle_objects.setText("隐藏所有元素")

    def set_scan_context(self, input_dir):
        if not input_dir:
            return False
        if os.path.isdir(input_dir):
            cands = [
                os.path.join(input_dir, "sparse", "0", "map.pcd"),
                os.path.join(input_dir, "sparse", "0", "map.las"),
                os.path.join(input_dir, "sparse", "0", "map.laz"),
                os.path.join(input_dir, "sparse", "0", "points3D.txt"),
                os.path.join(input_dir, "sparse", "0", "point3D.txt"),
                os.path.join(input_dir, "sparse", "0", "points3D.ply"),
                os.path.join(input_dir, "sparse", "0", "point3D.ply"),
            ]
            for p in cands:
                if os.path.exists(p):
                    self.raw_file_path = p
                    self.scan_dir = input_dir
                    self.scan_name = os.path.basename(os.path.normpath(input_dir))
                    return True
            return False
        if os.path.isfile(input_dir):
            self.raw_file_path = input_dir
            self.scan_dir = os.path.dirname(input_dir)
            self.scan_name = os.path.splitext(os.path.basename(input_dir))[0]
            return True
        return False

    def _get_project_root_dir(self):
        base = self.scan_dir if self.scan_dir else os.path.dirname(self.raw_file_path or "")
        if not base:
            return ""
        d = os.path.normpath(base)
        bname = os.path.basename(d).lower()
        parent = os.path.dirname(d)
        pname = os.path.basename(parent).lower()
        # ...\sparse\0 or ...\sparse\1 -> project root
        if bname.isdigit() and pname == "sparse":
            return os.path.dirname(parent)
        # ...\sparse -> project root
        if bname == "sparse":
            return parent
        return d

    def load_from_scan_folder(self, scan_folder, texture_path=None, loading_text="正在加载..."):
        if not self.set_scan_context(scan_folder):
            QMessageBox.critical(self, "路径错误", f"找不到指定路径或文件:\n{scan_folder}")
            return
        self.texture_path = texture_path
        self.has_texture_input = bool(texture_path)
        if hasattr(self.panel_action, "set_mesh_output_visible"):
            self.panel_action.set_mesh_output_visible(self.has_texture_input)
        self._start_loading_raw(texture_path=texture_path, loading_text=loading_text)

    def _start_loading_raw(self, texture_path=None, loading_text="正在加载原始模型..."):
        self.progress_dialog = QProgressDialog(loading_text, None, 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.show()
        QApplication.processEvents()
        self.loader = ModelLoader(self.raw_file_path, texture_path=texture_path)
        self.loader.stage1_div = self.stage1_div
        self.loader.random_target_points = self.random_target_points
        print(
            f"[PARAM][APPLY] stage1_div={self.stage1_div}, "
            f"stage2_div={self.stage2_div}, random_target={self.random_target_points}",
            flush=True,
        )
        self.loader.loaded.connect(self.on_raw_loaded)
        self.loader.start()

    def on_raw_loaded(self, mesh, points, colors, texture, orig, final):
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        autosave_dir = os.path.join(self._get_project_root_dir(), "autosave")
        edit_path = os.path.join(autosave_dir, f"{self.scan_name}_edit.ply")
        if self.autosave.has_autosave() and os.path.exists(edit_path):
            self._restore_after_work_load = True
            self.set_stage_editor(edit_path)
            return
        self.data_manager.load_data(mesh if mesh is not None else points, colors, texture)
        self.canvas.render_mesh(self.data_manager)
        self._apply_dynamic_initial_view()
        try:
            if self.autosave.has_autosave():
                self.autosave.restore()
        except Exception:
            pass
        self.switch_tool(self.tool_select)

    def load_work_file(self, path, texture_path=None):
        self.progress_dialog = QProgressDialog("加载精修编辑进度...", None, 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.show()
        QApplication.processEvents()
        self.loader = ModelLoader(path, texture_path=texture_path)
        self.loader.loaded.connect(self.on_work_loaded)
        self.loader.start()

    def on_work_loaded(self, mesh, points, colors, texture, orig, final):
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        self.setEnabled(True)
        self.data_manager.load_data(mesh if mesh is not None else points, colors, texture)
        self.canvas.render_mesh(self.data_manager)
        self._apply_dynamic_initial_view()
        if self.current_tool == self.tool_calibration:
            self.tool_calibration.deactivate()
        if self._restore_after_work_load:
            self._restore_after_work_load = False
            try:
                if self.autosave.has_autosave():
                    self.autosave.restore()
            except Exception:
                pass
        self._autosave_now()

    def process_and_advance(self):
        if not self.raw_file_path:
            return
        if not self._north_is_calibrated:
            QMessageBox.warning(self, "提示", "请先设置并确认指北方向，再进入阶段二。")
            return

        # Textured mesh path: preserve faces/UV by saving current mesh directly.
        mesh = self.data_manager.mesh
        if (
            self.has_texture_input
            and self.texture_path
            and mesh is not None
            and hasattr(mesh, "n_faces_strict")
            and mesh.n_faces_strict > 0
        ):
            try:
                result_dir = os.path.join(self._get_project_root_dir(), "autosave")
                os.makedirs(result_dir, exist_ok=True)
                scan_name = self.scan_name or os.path.splitext(os.path.basename(self.raw_file_path))[0]
                edit_path = os.path.join(result_dir, f"{scan_name}_edit.ply")
                mesh.save(edit_path, binary=True)
                self.set_stage_editor(edit_path)
                self._autosave_now(force=True)
                return
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存贴图模型失败: {e}")
                return

        self.setEnabled(False)
        QApplication.processEvents()
        self.progress_dialog = QProgressDialog("后台处理中...", None, 0, 100, self)
        self.progress_dialog.show()
        QApplication.processEvents()

        crop_bbox = self.tool_select.get_crop_bbox()
        if crop_bbox is None and self.data_manager.mesh is None:
            self.progress_dialog.close()
            self.setEnabled(True)
            return

        transform_matrix = self.tool_calibration.get_transform_matrix()
        preview_points = None
        input_points = None
        input_colors = None

        use_in_memory_source = False
        try:
            raw_size = os.path.getsize(self.raw_file_path)
            if self.data_manager.mesh is not None and raw_size <= 2 * 1024 * 1024 * 1024:
                use_in_memory_source = True
        except Exception:
            pass

        if use_in_memory_source:
            input_points = self.data_manager.mesh.points
            if "RGB" in self.data_manager.mesh.point_data:
                input_colors = self.data_manager.mesh.point_data["RGB"]
            transform_matrix = None
        elif self.data_manager.mesh is not None:
            preview_points = np.array(self.data_manager.mesh.points)

        result_dir = os.path.join(self._get_project_root_dir(), "autosave")
        os.makedirs(result_dir, exist_ok=True)
        scan_name = self.scan_name or os.path.splitext(os.path.basename(self.raw_file_path))[0]
        edit_path = os.path.join(result_dir, f"{scan_name}_edit.ply")

        self.processor = GeometryProcessor(
            raw_path=self.raw_file_path,
            crop_bbox=crop_bbox,
            transform_matrix=transform_matrix,
            preview_points=preview_points,
            output_path=edit_path,
            input_points=input_points,
            input_colors=input_colors,
        )
        self.processor.stage2_div = self.stage2_div
        self.processor.random_target_points = self.random_target_points
        self.processor.progress.connect(
            lambda v, t: (self.progress_dialog.setValue(v), self.progress_dialog.setLabelText(t))
        )
        self.processor.finished.connect(self.on_process_finished)
        self.processor.error.connect(self.on_process_error)
        self.processor.start()

    def on_process_finished(self, work_file_path):
        self.progress_dialog.close()
        self.set_stage_editor(work_file_path)
        self._autosave_now()

    def on_process_error(self, msg):
        self.progress_dialog.close()
        self.setEnabled(True)
        QMessageBox.critical(self, "错误", msg)

    def _enter_ground_calibration(self):
        self._ground_prev_camera_state = self._capture_camera_state()
        self._ground_calib_locked = True
        self._ground_manual_pick = False
        self._ground_history_pushed = False
        self._north_locked = False
        self._apply_stage1_lock_ui()
        self.panel_action.widget_calib_ops.show()
        self.panel_action.btn_calib_start.hide()
        self.panel_action.set_stage1_mode_selection("view")
        self.tool_calibration.start_ground_calibration_flow()
        self.switch_tool(self.tool_calibration)

    def _exit_ground_calibration(self):
        self._ground_calib_locked = False
        self._ground_manual_pick = False
        self._ground_history_pushed = False
        self._ground_prev_camera_state = None
        self.panel_action.widget_calib_ops.hide()
        self.panel_action.btn_calib_start.show()
        self.panel_action.update_select_button_text("区域选择")
        self._apply_stage1_lock_ui()

    def _enter_north_calibration(self):
        self._north_locked = True
        self._north_history_pushed = True
        self._apply_stage1_lock_ui()
        self.tool_calibration.start_set_north()
        self.switch_tool(self.tool_calibration)

    def _exit_north_calibration(self):
        self._north_locked = False
        self._north_history_pushed = False
        self._apply_stage1_lock_ui()

    def handle_calibration(self, action):
        if action == "start_ground_calib":
            if self._north_locked:
                return
            self._enter_ground_calibration()
        elif action == "manual_ground_3pt":
            if not self._ground_calib_locked:
                return
            self._ground_manual_pick = True
            self._ground_history_pushed = True
            self._apply_stage1_lock_ui()
            self.tool_calibration.start_manual_ground_3pt()
        elif action == "confirm_ground":
            if not self._ground_calib_locked:
                return
            self.tool_calibration.confirm_ground()
            self.switch_tool(self.tool_select)
            self._exit_ground_calibration()
        elif action == "cancel_ground":
            if not self._ground_calib_locked:
                return
            self.tool_calibration.deactivate()
            if self._ground_history_pushed and self.data_manager.undo():
                self.canvas.render_mesh(self.data_manager)
            self._restore_camera_state(self._ground_prev_camera_state)
            self.switch_tool(self.tool_select)
            self._exit_ground_calibration()
        elif action == "set_north":
            if self._ground_calib_locked or self._north_locked:
                return
            self.tool_select.clear_selection()
            self.canvas.plotter.render()
            self.panel_action.set_stage1_mode_selection("view")
            self.tool_select.set_interaction_mode("view")
            self._enter_north_calibration()
        elif action == "confirm_north":
            if not self._north_locked:
                return
            self.tool_calibration.confirm_north()
            self._north_is_calibrated = True
            self.switch_tool(self.tool_select)
            self._exit_north_calibration()
        elif action == "cancel_north":
            if not self._north_locked:
                return
            self.tool_calibration.deactivate()
            if self._north_history_pushed and self.data_manager.undo():
                self.canvas.render_mesh(self.data_manager)
            self.switch_tool(self.tool_select)
            self._exit_north_calibration()

    def handle_select_action(self, action):
        if action == "delete_inner":
            self.tool_select.delete_selection()
            self._render_scene_with_overlays()
            self._autosave_now()
        elif action == "invert":
            self.tool_select.invert_selection()
            self.canvas.plotter.render()

    def on_select_mode_changed(self, mode):
        self._stage1_select_mode = mode
        self._apply_stage1_lock_ui()
        if self._north_locked:
            return
        if self._ground_calib_locked:
            if self._ground_manual_pick:
                if mode == "draw":
                    self.tool_calibration.set_interaction_mode("pick")
                else:
                    self.tool_calibration.set_interaction_mode(mode)
            else:
                if mode in ("view", "pan"):
                    self.tool_calibration.set_interaction_mode(mode)
            return
        self.tool_select.set_interaction_mode(mode)

    def _render_scene_with_overlays(self):
        self.canvas.render_mesh(self.data_manager)
        try:
            if hasattr(self.tool_ref, "redraw_all"):
                self.tool_ref.redraw_all()
        except Exception:
            pass
        try:
            if hasattr(self.tool_measure, "redraw_all"):
                self.tool_measure.redraw_all()
        except Exception:
            pass
        try:
            if hasattr(self.tool_marker, "redraw_all"):
                self.tool_marker.redraw_all()
        except Exception:
            pass
        self.canvas.plotter.render()

    def on_view_change(self, mode):
        cam = self.canvas.plotter.camera
        if mode == "top":
            self.canvas.plotter.view_xy()
        elif mode == "front":
            self.canvas.plotter.view_xz()
            cam.SetViewUp(0, 0, 1)
        elif mode == "side":
            self.canvas.plotter.view_yz()
            cam.SetViewUp(0, 0, 1)
        elif mode == "ortho_toggle":
            cam.SetParallelProjection(1 if self.panel_action.chk_ortho.isChecked() else 0)
            self.canvas.plotter.render()

    def undo_action(self):
        if self.data_manager.undo():
            self._render_scene_with_overlays()
            self._autosave_now()
        else:
            QMessageBox.information(self, "提示", "没有可撤回的操作")

    def on_request_marker_details(self, pos, default_label):
        dlg = MarkerDialog(self, default_label=default_label)
        if dlg.exec():
            data = dlg.get_data()
            label = data.get("label", "").strip() or default_label
            self.tool_marker.add_marker(pos, label, data.get("desc", ""), data.get("image", ""))

    def on_measure_style_changed(self, key, value, extra):
        self.tool_measure.update_style_defaults(key, value)
        self.tool_ref.update_style_defaults(key, value)
        self.tool_marker.update_style_defaults(key, value)
        if extra == "drag":
            self._pending_style_change = (key, value)
            self._style_apply_timer.start(self._style_apply_delay_ms)
            return

        if self._style_apply_timer.isActive():
            self._style_apply_timer.stop()
        self._pending_style_change = None
        self._apply_style_change_now(key, value)
        if extra == "final":
            self._autosave_now()

    def _collect_style_targets(self):
        targets = list(self.panel_list.get_all_checked_items())
        if not targets:
            item = self.panel_list.tree.currentItem()
            if item:
                data = item.data(0, Qt.UserRole)
                if data:
                    targets = [data]
        return targets

    def _apply_style_change_now(self, key, value):
        targets = self._collect_style_targets()
        if not targets:
            return

        measure_targets = []
        ref_targets = []
        marker_targets = []
        for cat, real_data in targets:
            if cat == "measure":
                measure_targets.append(real_data)
            elif cat == "ref":
                ref_targets.append(real_data)
            elif cat == "marker":
                marker_targets.append(real_data)

        if measure_targets:
            self.tool_measure.apply_style_to_segments(key, value, measure_targets)
        for real_data in ref_targets:
            self.tool_ref.apply_style(key, value, real_data, render=False)
        for real_data in marker_targets:
            self.tool_marker.apply_style(key, value, real_data, render=False)
        self.canvas.plotter.render()

    def _flush_pending_style_change(self):
        if not self._pending_style_change:
            return
        key, value = self._pending_style_change
        self._pending_style_change = None
        self._apply_style_change_now(key, value)

    def _on_toggle_all_objects(self, checked):
        visible = not bool(checked)
        self._objects_visible = visible
        try:
            self.tool_measure.set_visible(visible)
            self.tool_ref.set_visible(visible)
            self.tool_marker.set_visible(visible)
        except Exception:
            pass
        self.btn_toggle_objects.setText("显示所有元素" if checked else "隐藏所有元素")
        self.canvas.plotter.render()

    def _set_style_view_lock(self, locked):
        iren = getattr(self.canvas.plotter, "interactor", None)
        if iren is None:
            return
        if locked:
            self._style_lock_depth += 1
        else:
            self._style_lock_depth = max(0, self._style_lock_depth - 1)
        try:
            if self._style_lock_depth > 0:
                iren.Disable()
            else:
                iren.Enable()
        except Exception:
            pass

    def _reset_style_view_lock(self):
        self._style_lock_depth = 0
        iren = getattr(self.canvas.plotter, "interactor", None)
        if iren is None:
            return
        try:
            iren.Enable()
        except Exception:
            pass

    def _output_dir(self):
        base = self._get_project_root_dir()
        out_dir = os.path.join(base, "autosave") if base else ""
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        return out_dir

    def _runtime_base_dir(self):
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _touch_empty_file(self, path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8"):
                pass
        except Exception:
            pass

    def _apply_top_direction_camera(self):
        self.on_view_change("top")
        key = (self._top_dir_key or "N").upper()
        angles = {
            "N": 0.0, "NE": 45.0, "E": 90.0, "SE": 135.0,
            "S": 180.0, "SW": 225.0, "W": 270.0, "NW": 315.0,
        }
        deg = angles.get(key, 0.0)
        rad = np.deg2rad(deg)
        up = (float(np.sin(rad)), float(np.cos(rad)), 0.0)
        cam = self.canvas.plotter.camera
        cam.SetViewUp(*up)
        self.canvas.plotter.renderer.ResetCameraClippingRange()
        self.canvas.plotter.render()
        self._refresh_top_direction_hint()

    def _dir_label(self, key):
        mapping = {
            "N": "北", "NE": "东北", "E": "东", "SE": "东南",
            "S": "南", "SW": "西南", "W": "西", "NW": "西北",
        }
        return mapping.get((key or "N").upper(), "北")

    def _refresh_top_direction_hint(self):
        actor = self._actor_by_name("top_dir_hint")
        if actor is None:
            return
        try:
            actor.SetInput(f"↑ {self._dir_label(self._top_dir_key)}")
            self.canvas.plotter.render()
        except Exception:
            pass

    def _show_top_direction_hint(self):
        try:
            self.canvas.plotter.remove_actor("top_dir_hint")
        except Exception:
            pass
        try:
            self.canvas.plotter.add_text(
                f"↑ {self._dir_label(self._top_dir_key)}",
                position="upper_right",
                font_size=18,
                color="yellow",
                name="top_dir_hint",
            )
            self.canvas.plotter.render()
        except Exception:
            pass

    def _hide_top_direction_hint(self):
        try:
            self.canvas.plotter.remove_actor("top_dir_hint")
            self.canvas.plotter.render()
        except Exception:
            pass

    def _actor_by_name(self, name):
        try:
            return self.canvas.plotter.actors.get(name)
        except Exception:
            return None

    def _set_actor_visible(self, actor, visible):
        if actor is None:
            return
        try:
            actor.SetVisibility(bool(visible))
        except Exception:
            pass

    def _capture_frame(self, hide_axes=False, hide_annotations=False):
        toggled = []
        axes_hidden = False
        ann_hidden = False
        try:
            if hide_axes:
                try:
                    self.canvas.plotter.hide_axes()
                    axes_hidden = True
                except Exception:
                    pass

            if hide_annotations:
                for tool in (self.tool_measure, self.tool_ref, self.tool_marker):
                    if hasattr(tool, "set_visible"):
                        tool.set_visible(False)
                        ann_hidden = True

            for name in (
                "selection_highlight",
                "lasso_trace_dynamic",
                "calib_grid",
                "static_north_arrow",
                "north_temp_1",
                "ground_pt_1",
                "ground_pt_2",
                "ground_pt_3",
                "ground_pt_4",
            ):
                actor = self._actor_by_name(name)
                if actor is not None:
                    try:
                        prev = bool(actor.GetVisibility())
                    except Exception:
                        prev = True
                    toggled.append((actor, prev))
                    self._set_actor_visible(actor, False)

            self.canvas.plotter.render()
            img = self.canvas.plotter.screenshot(return_img=True)
            return np.asarray(img)
        finally:
            for actor, prev in toggled:
                self._set_actor_visible(actor, prev)
            if ann_hidden:
                for tool in (self.tool_measure, self.tool_ref, self.tool_marker):
                    if hasattr(tool, "set_visible"):
                        tool.set_visible(True)
            if axes_hidden:
                try:
                    self.canvas.plotter.show_axes()
                except Exception:
                    pass
            self.canvas.plotter.render()

    def _crop_black_margins(self, img, threshold=8, pad=4):
        if img is None or getattr(img, "size", 0) == 0:
            return img
        arr = np.asarray(img)
        if arr.ndim != 3 or arr.shape[0] == 0 or arr.shape[1] == 0:
            return arr
        rgb = arr[:, :, :3]
        mask = np.any(rgb > threshold, axis=2)
        ys, xs = np.where(mask)
        if ys.size == 0 or xs.size == 0:
            return arr
        y0 = max(0, int(ys.min()) - pad)
        y1 = min(arr.shape[0], int(ys.max()) + pad + 1)
        x0 = max(0, int(xs.min()) - pad)
        x1 = min(arr.shape[1], int(xs.max()) + pad + 1)
        return arr[y0:y1, x0:x1]

    def _save_image_np(self, out_path, img):
        from PIL import Image

        arr = np.asarray(img)
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        Image.fromarray(arr).save(out_path)

    def _world_to_display(self, world_pt):
        ren = self.canvas.plotter.renderer
        ren.SetWorldPoint(float(world_pt[0]), float(world_pt[1]), float(world_pt[2]), 1.0)
        ren.WorldToDisplay()
        x, y, z = ren.GetDisplayPoint()
        return np.array([float(x), float(y), float(z)], dtype=np.float64)

    def _calc_pixels_per_meter(self):
        mesh = self.data_manager.mesh
        if mesh is None or mesh.n_points <= 0:
            return 0.0
        c = np.array(mesh.center, dtype=np.float64)
        d0 = self._world_to_display(c)
        d1 = self._world_to_display(c + np.array([1.0, 0.0, 0.0], dtype=np.float64))
        px = float(np.linalg.norm(d1[:2] - d0[:2]))
        if px > 1e-6:
            return px
        cam = self.canvas.plotter.camera
        if cam.GetParallelProjection():
            h = max(1.0, float(self.canvas.plotter.window_size[1]))
            return h / max(1e-6, 2.0 * float(cam.GetParallelScale()))
        return 0.0

    def _camera_axis_dirs_for_overlay(self):
        mesh = self.data_manager.mesh
        if mesh is None or mesh.n_points <= 0:
            return {"E": np.array([1.0, 0.0]), "N": np.array([0.0, -1.0]), "Z": np.array([0.0, -1.0])}
        c = np.array(mesh.center, dtype=np.float64)
        p0 = self._world_to_display(c)
        dirs = {}
        for key, vec in (
            ("E", np.array([1.0, 0.0, 0.0], dtype=np.float64)),
            ("N", np.array([0.0, 1.0, 0.0], dtype=np.float64)),
            ("Z", np.array([0.0, 0.0, 1.0], dtype=np.float64)),
        ):
            p1 = self._world_to_display(c + vec)
            v = np.array([p1[0] - p0[0], -(p1[1] - p0[1])], dtype=np.float64)
            n = np.linalg.norm(v)
            dirs[key] = (v / n) if n > 1e-6 else np.array([0.0, -1.0], dtype=np.float64)
        return dirs

    def _compose_sideview_with_axis(self, img):
        from PIL import Image, ImageDraw, ImageFont
        from gui.canvas import _FONT_PATH

        arr = np.asarray(img)
        h, w = arr.shape[:2]
        extra_w = max(180, int(w * 0.14))
        extra_h = max(140, int(h * 0.14))
        canvas = np.zeros((h + extra_h, w + extra_w, arr.shape[2]), dtype=np.uint8)
        canvas[:h, :w, :] = arr[:, :, :]

        im = Image.fromarray(canvas)
        draw = ImageDraw.Draw(im)
        ox = w + extra_w - 95
        oy = h + extra_h - 70
        axis_len = 55

        dirs = self._camera_axis_dirs_for_overlay()
        label_map = {"E": "东", "N": "北", "Z": "Z"}
        color_map = {"E": (240, 80, 80), "N": (255, 220, 40), "Z": (100, 220, 255)}
        try:
            font = ImageFont.truetype(_FONT_PATH, 22) if _FONT_PATH else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()

        draw.ellipse((ox - 4, oy - 4, ox + 4, oy + 4), fill=(255, 255, 255))
        for key in ("E", "N", "Z"):
            v = dirs.get(key, np.array([0.0, -1.0], dtype=np.float64))
            ex = int(round(ox + v[0] * axis_len))
            ey = int(round(oy + v[1] * axis_len))
            draw.line((ox, oy, ex, ey), fill=color_map[key], width=4)
            hx = int(round(ex - v[0] * 10 + v[1] * 5))
            hy = int(round(ey - v[1] * 10 - v[0] * 5))
            hx2 = int(round(ex - v[0] * 10 - v[1] * 5))
            hy2 = int(round(ey - v[1] * 10 + v[0] * 5))
            draw.polygon([(ex, ey), (hx, hy), (hx2, hy2)], fill=color_map[key])
            draw.text((ex + 4, ey + 2), label_map[key], fill=color_map[key], font=font)
        return np.asarray(im)

    def _enter_output_stage(self):
        self._reset_style_view_lock()
        self._hide_top_direction_hint()
        # Leave Stage2 selection/draw state before entering output.
        try:
            self.tool_select.clear_selection()
            self.tool_select.set_interaction_mode("view")
        except Exception:
            pass
        try:
            self.panel_action.btn_g_view.setChecked(True)
            self.panel_action.global_mode_changed.emit("view")
        except Exception:
            pass
        try:
            self.panel_action.btn_s3_pan.setChecked(False)
            self.panel_action.btn_s3_view.setChecked(True)
        except Exception:
            pass
        self.current_stage = "OUTPUT"
        self.lbl_stage.setText("阶段 3: 输出")
        self.panel_action.switch_stage(2)
        self.btn_toggle_objects.show()

    def _back_to_stage2(self):
        self._hide_top_direction_hint()
        self.current_stage = "EDITOR"
        self.lbl_stage.setText("阶段 2: 精修 (测量/标注)")
        self.panel_action.switch_stage(1)
        self.btn_toggle_objects.show()

    def _save_output_image(self, kind="side"):
        base = self._get_project_root_dir()
        if kind == "primitive":
            out_dir = os.path.join(base, "图元图") if base else ""
        else:
            out_dir = os.path.join(base, "实景图") if base else ""
        if not out_dir:
            return
        os.makedirs(out_dir, exist_ok=True)
        scan_name = self.scan_name or "scan"
        try:
            if kind == "primitive":
                self._apply_top_direction_camera()
                img = self._capture_frame(hide_axes=True, hide_annotations=True)
                img = self._crop_black_margins(img)
                out_path = os.path.join(out_dir, f"{scan_name}_primitive.png")
                self._save_image_np(out_path, img)
                self._touch_empty_file(os.path.join(self._runtime_base_dir(), "tuyuan.txt"))
                QMessageBox.information(self, "提示", f"图元图已保存: {out_path}")
                return

            if kind == "top":
                self._apply_top_direction_camera()
                img = self._capture_frame(hide_axes=True, hide_annotations=False)
                img = self._crop_black_margins(img)
                out_path = os.path.join(out_dir, f"{scan_name}_top.png")
                self._save_image_np(out_path, img)
                scale_path = os.path.join(out_dir, "scale.txt")
                px_per_m = self._calc_pixels_per_meter()
                with open(scale_path, "w", encoding="utf-8") as f:
                    f.write(f"{px_per_m:.6f}\n")
                    f.write(f"{self._top_dir_key}\n")
                self._touch_empty_file(os.path.join(self._runtime_base_dir(), "realimage.txt"))
                QMessageBox.information(self, "提示", f"俯视图已保存: {out_path}")
                return

            # side
            img = self._capture_frame(hide_axes=True, hide_annotations=False)
            img = self._crop_black_margins(img)
            raw_side = os.path.join(out_dir, f"{scan_name}_side.png")
            self._save_image_np(raw_side, img)
            sideview = self._compose_sideview_with_axis(img)
            side_path = os.path.join(out_dir, f"{scan_name}_sideview.png")
            self._save_image_np(side_path, sideview)
            self._touch_empty_file(os.path.join(self._runtime_base_dir(), "realimage.txt"))
            QMessageBox.information(self, "提示", f"实景图已保存: {side_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def _save_output_mesh(self):
        base = self._get_project_root_dir()
        out_dir = os.path.join(base, "mesh模型") if base else ""
        if not out_dir or self.data_manager.mesh is None:
            return
        os.makedirs(out_dir, exist_ok=True)
        scan_name = self.scan_name or "scan"
        out_path = os.path.join(out_dir, f"{scan_name}_mesh.ply")
        try:
            self.data_manager.mesh.save(out_path)
            QMessageBox.information(self, "提示", f"已保存: {out_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def _autosave_flush(self):
        if self._bulk_ui_update:
            return
        try:
            self.autosave.save()
        except Exception:
            pass

    def _autosave_now(self, force=False):
        if self._bulk_ui_update:
            return
        if force:
            if self._autosave_timer.isActive():
                self._autosave_timer.stop()
            self._autosave_flush()
            return
        self._autosave_timer.start(self._autosave_delay_ms)

    def closeEvent(self, event):
        self._autosave_now(force=True)
        self._is_closing = True
        if self.current_tool:
            self.current_tool.deactivate()
        if hasattr(self, "tool_select"):
            self.tool_select.cleanup()
        if hasattr(self, "tool_measure"):
            self.tool_measure.cleanup()
        if hasattr(self, "data_manager"):
            self.data_manager.clear_all()
        if hasattr(self, "canvas") and hasattr(self.canvas, "plotter"):
            self.canvas.plotter.close()
        super().closeEvent(event)







