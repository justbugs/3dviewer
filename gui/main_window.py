import os
import numpy as np
from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QWidget, QHBoxLayout, 
                               QSplitter, QMessageBox, QFileDialog, QProgressDialog, 
                               QLabel, QPushButton, QApplication)
from PySide6.QtCore import Qt

from core.loader import ModelLoader
from core.data import DataManager
from core.processor import GeometryProcessor
from gui.canvas import PointCloudCanvas
from gui.panels import ObjectListPanel, ActionPanel

# --- Tools Import ---
from tools.measure import MeasureTool
from tools.select import SelectTool 
from tools.calibration import CalibrationTool
from tools.ref_tool import ReferenceTool
from tools.marker import MarkerTool

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CrashSite3D - Engineering Suite (Touch Optimized)")
        self.resize(1600, 900)
        self.showMaximized()
        
        self.current_stage = "PREPARE"
        self.raw_file_path = None
        self.progress_dialog = None
        
        self.data_manager = DataManager()
        self._init_ui()
        
        # --- Initialize Tools ---
        self.tool_measure = MeasureTool(self.canvas, self.data_manager)
        self.tool_select = SelectTool(self.canvas, self.data_manager)
        self.tool_calibration = CalibrationTool(self.canvas, self.data_manager)
        self.tool_ref = ReferenceTool(self.canvas, self.data_manager)
        self.tool_marker = MarkerTool(self.canvas, self.data_manager)
        
        self.current_tool = None
        
        self._connect_signals()
        self.set_stage_prepare() # Default to Stage 1

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0,0,0,0)

        # Top Bar
        self.top_bar_layout = QHBoxLayout()
        self.top_bar_layout.setContentsMargins(5, 5, 5, 5)
        self.lbl_stage = QLabel("阶段 1: 粗修")
        self.lbl_stage.setStyleSheet("font-size: 24px; font-weight: bold; margin-right: 20px;")
        self.top_bar_layout.addWidget(self.lbl_stage)
        
        # Large buttons for touch
        btn_style = "QPushButton { min-height: 70px; font-size: 20px; font-weight: bold; border-radius: 8px; padding: 10px; margin: 5px; }"
        self.btn_open = QPushButton("📂 打开原始点云")
        self.btn_open.setStyleSheet(btn_style + "background-color: #f0ad4e; color: white;")
        self.btn_next = QPushButton("➡️ 下一步 (Next)")
        self.btn_next.setStyleSheet(btn_style + "background-color: #0275d8; color: white;")
        self.btn_undo = QPushButton("↩️ 撤回 (Undo)")
        self.btn_undo.setStyleSheet(btn_style)
        self.btn_exit = QPushButton("🔴 退出")
        self.btn_exit.setStyleSheet(btn_style + "background-color: #d9534f; color: white;")
        self.btn_exit.clicked.connect(self.close)

        for btn in [self.btn_open, self.btn_next, self.btn_undo, self.btn_exit]:
            self.top_bar_layout.addWidget(btn)
        self.top_bar_layout.addStretch()
        main_layout.addLayout(self.top_bar_layout)
        
        # Splitter
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
        self.btn_open.clicked.connect(self.load_raw_file)
        self.btn_next.clicked.connect(self.process_and_advance)
        self.btn_undo.clicked.connect(self.undo_action)

        # === Stage 1 Signals ===
        self.panel_action.calibration_triggered.connect(self.handle_calibration)
        self.panel_action.select_triggered.connect(self.handle_select_action)
        self.panel_action.select_mode_changed.connect(self.on_select_mode_changed)
        
        self.tool_calibration.north_tuning_started.connect(lambda: self.panel_action.btn_confirm_north.show())
        self.tool_calibration.status_message.connect(lambda msg: QMessageBox.information(self, "指引", msg))
        
        # === Stage 2 Signals ===
        self.panel_action.global_mode_changed.connect(self.on_global_mode)
        self.panel_action.tool_selected.connect(self.on_tool_selected)
        self.panel_action.action_triggered.connect(self.on_action_triggered)
        
        self.panel_action.xray_toggled.connect(self.tool_measure.set_xray_enabled)
        self.panel_action.view_change_triggered.connect(self.on_view_change)
        
        # Tool Signals
        self.tool_ref.ref_added.connect(self.on_ref_added)
        self.tool_measure.measurement_added.connect(self.on_measurement_added)
        self.tool_marker.marker_added.connect(self.on_marker_added)
        
        # List Interaction
        self.panel_list.item_clicked.connect(self.on_item_clicked)
        self.panel_list.item_deleted.connect(self.on_item_deleted)
        
        # Linkage
        self.tool_select.request_delete_measurements.connect(self.tool_measure.delete_points_inside_polygon)

    # ================= Tool Switching =================
    def switch_tool(self, tool):
        if self.current_tool and self.current_tool != tool:
            self.current_tool.deactivate()
        self.current_tool = tool
        if self.current_tool:
            self.current_tool.activate()

    # --- Stage 2 Logic ---
    def on_tool_selected(self, tool_type, sub_mode):
        if tool_type == 'ref':
            self.tool_ref.set_mode(sub_mode)
            self.switch_tool(self.tool_ref)
        elif tool_type == 'measure':
            self.tool_measure.set_mode(sub_mode)
            self.switch_tool(self.tool_measure)
        elif tool_type == 'marker':
            self.switch_tool(self.tool_marker)
        elif tool_type == 'edit':
            self.switch_tool(self.tool_select)
            # Edit Mode logic: select -> draw, else -> view
            if sub_mode == 'select':
                self.tool_select.set_interaction_mode('draw')
            else:
                self.tool_select.set_interaction_mode('view')

    def on_global_mode(self, mode):
        if self.current_tool:
            self.current_tool.set_interaction_mode(mode)

    def on_action_triggered(self, action):
        if action == 'finish': 
            self.tool_measure.finish_segment()
        elif action == 'clear': 
            self.tool_measure.clear_all()
            self.panel_list.clear_all()
        elif action == 'delete': 
            self.tool_select.delete_selection()
            self.canvas.render_mesh(self.data_manager)
        elif action == 'undo': 
            self.undo_action()

    # ================= Data Update Handlers =================
    def on_ref_added(self, rtype, idx, d1, d2):
        txt = f"基准线-{idx}" if rtype == 'line' else f"基准点-{idx}"
        data = {'type': 'ref', 'subtype': rtype, 'd1': d1, 'd2': d2, 'idx': idx}
        self.panel_list.add_item('ref', txt, data)
        if rtype == 'line': self.tool_measure.set_active_ref_line(d1, d2)
        elif rtype == 'point': self.tool_measure.set_active_ref_point(d1)

    def on_measurement_added(self, text, data_ref):
        self.panel_list.add_item('measure', text, data_ref)

    def on_marker_added(self, text, data_ref):
        self.panel_list.add_item('marker', text, data_ref)

    def on_item_clicked(self, item):
        data = item.data(0, Qt.UserRole)
        if not data: return
        cat, real_data = data
        if cat == 'ref':
            if real_data['subtype'] == 'line':
                self.tool_measure.set_active_ref_line(real_data['d1'], real_data['d2'])
            elif real_data['subtype'] == 'point':
                self.tool_measure.set_active_ref_point(real_data['d1'])
        elif cat == 'measure':
            # 【核心功能】点击列表项，高亮对应的 3D 线条
            self.tool_measure.highlight_segment(real_data)

    def on_item_deleted(self, item):
        data = item.data(0, Qt.UserRole)
        if not data: return
        cat, real_data = data
        if cat == 'ref':
            # self.tool_ref.delete_by_data(real_data) 
            pass 
        elif cat == 'measure':
            self.tool_measure.delete_by_data(real_data)
        elif cat == 'marker':
            self.tool_marker.delete_by_data(real_data)

    # ================= Stage Logic =================
    def set_stage_prepare(self):
        """进入一阶段：粗修"""
        self.current_stage = "PREPARE"
        self.lbl_stage.setText("阶段 1: 粗修 (校准/剪裁)")
        self.btn_open.show(); self.btn_next.show()
        self.panel_action.switch_stage(0)
        self.switch_tool(self.tool_select)
        self.data_manager.set_max_history(1)

    def set_stage_editor(self, work_file_path):
        """进入二阶段：精修"""
        self.current_stage = "EDITOR"
        self.lbl_stage.setText("阶段 2: 精修 (测量/标注)")
        self.btn_open.hide(); self.btn_next.hide()
        self.panel_action.switch_stage(1)
        
        self.load_work_file(work_file_path)
        
        self.data_manager.set_max_history(5) 
        self.panel_action.grp_tools.buttons()[0].click()

    # ================= File & Process Ops =================
    def load_raw_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "打开", "", "Point Cloud (*.ply *.pcd)")
        if not fname: return
        self.raw_file_path = fname
        self.progress_dialog = QProgressDialog("加载预览...", None, 0, 0, self)
        self.progress_dialog.show()
        self.loader = ModelLoader(fname)
        self.loader.loaded.connect(self.on_raw_loaded)
        self.loader.start()

    def on_raw_loaded(self, points, colors, tex, orig, final):
        if self.progress_dialog: self.progress_dialog.close()
        self.data_manager.load_data(points, colors, tex)
        self.canvas.render_mesh(self.data_manager)
        QMessageBox.information(self, "提示", "请先[校准地面]，再[设定指北]，最后[画圈]剪裁。")
        self.switch_tool(self.tool_select)

    def load_work_file(self, path):
        self.loader = ModelLoader(path)
        self.loader.loaded.connect(self.on_work_loaded)
        self.loader.start()

    def on_work_loaded(self, points, colors, tex, orig, final):
        self.setEnabled(True)
        self.data_manager.load_data(points, colors, tex)
        self.canvas.render_mesh(self.data_manager)
        if self.current_tool == self.tool_calibration:
            self.tool_calibration.deactivate()

    def process_and_advance(self):
        if not self.raw_file_path: return
        self.setEnabled(False); QApplication.processEvents()
        self.progress_dialog = QProgressDialog("后台处理中...", None, 0, 100, self)
        self.progress_dialog.show(); QApplication.processEvents()
        
        crop_bbox = self.tool_select.get_crop_bbox()
        if crop_bbox is None:
            if self.data_manager.mesh:
                import open3d as o3d
                points = self.data_manager.mesh.points
                pcd_temp = o3d.geometry.PointCloud()
                pcd_temp.points = o3d.utility.Vector3dVector(points)
                crop_bbox = pcd_temp.get_oriented_bounding_box()
                crop_bbox.scale(1.05, crop_bbox.get_center())
            else:
                self.progress_dialog.close(); self.setEnabled(True); return

        transform_matrix = self.tool_calibration.get_transform_matrix()
        preview_points = None
        if self.data_manager.mesh is not None: preview_points = np.array(self.data_manager.mesh.points)

        self.processor = GeometryProcessor(self.raw_file_path, crop_bbox=crop_bbox, transform_matrix=transform_matrix, preview_points=preview_points)
        self.processor.progress.connect(lambda v, t: (self.progress_dialog.setValue(v), self.progress_dialog.setLabelText(t)))
        self.processor.finished.connect(self.on_process_finished)
        self.processor.error.connect(self.on_process_error)
        self.processor.start()

    def on_process_finished(self, work_file_path):
        self.progress_dialog.close()
        self.set_stage_editor(work_file_path)

    def on_process_error(self, msg):
        self.progress_dialog.close()
        self.setEnabled(True)
        QMessageBox.critical(self, "错误", msg)

    # ... Stage 1 Handlers ...
    def handle_calibration(self, action):
        self.current_tool = self.tool_calibration
        self.tool_calibration.activate()
        if action == "start_ground_calib":
            self.panel_action.widget_calib_ops.show(); self.tool_calibration.start_ground_calibration_flow()
        elif action == "manual_ground_3pt":
            self.panel_action.update_select_button_text("➕ 标点"); self.panel_action.btn_s1_draw.setChecked(True); self.tool_calibration.start_manual_ground_3pt()
        elif action == "confirm_ground":
            self.panel_action.widget_calib_ops.hide(); self.panel_action.update_select_button_text("✏️ 画圈"); self.tool_calibration.confirm_ground(); self.switch_tool(self.tool_select)
        elif action == "set_north": self.tool_calibration.start_set_north()
        elif action == "confirm_north": self.tool_calibration.confirm_north(); self.panel_action.btn_confirm_north.hide(); self.switch_tool(self.tool_select)

    def handle_select_action(self, action):
        if action == "delete_inner":
            self.tool_select.delete_selection(); self.canvas.render_mesh(self.data_manager); self.tool_measure.redraw_all()
        elif action == "invert":
            self.tool_select.invert_selection(); self.canvas.plotter.render()

    def on_select_mode_changed(self, mode):
        if self.current_tool == self.tool_calibration and self.tool_calibration.mode == 'manual_ground':
             self.tool_calibration.set_interaction_mode(mode)
        else:
             self.tool_select.set_interaction_mode(mode)

    def on_view_change(self, mode):
        cam = self.canvas.plotter.camera
        if mode == 'top': self.canvas.plotter.view_xy()
        elif mode == 'front': self.canvas.plotter.view_xz(); cam.SetViewUp(0,0,1)
        elif mode == 'side': self.canvas.plotter.view_yz(); cam.SetViewUp(0,0,1)
        elif mode == 'ortho_toggle': 
            if self.panel_action.chk_ortho.isChecked(): cam.SetParallelProjection(1)
            else: cam.SetParallelProjection(0)
            self.canvas.plotter.render()

    def undo_action(self):
        if self.data_manager.undo():
            self.canvas.render_mesh(self.data_manager)
            if self.current_tool == self.tool_measure: self.tool_measure.redraw_all()
        else:
            QMessageBox.information(self, "提示", "没有可撤回的操作")

    def closeEvent(self, event):
        if self.current_tool: self.current_tool.deactivate()
        if hasattr(self, 'tool_select'): self.tool_select.cleanup()
        if hasattr(self, 'tool_measure'): self.tool_measure.cleanup()
        if hasattr(self, 'canvas') and hasattr(self.canvas, 'plotter'): self.canvas.plotter.close()
        super().closeEvent(event)