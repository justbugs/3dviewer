import os
import numpy as np
from PySide6.QtWidgets import (QMainWindow, QVBoxLayout, QWidget, QHBoxLayout, 
                               QSplitter, QPushButton, QFileDialog, QMessageBox, 
                               QProgressDialog, QLabel, QApplication)
from PySide6.QtCore import Qt

from core.loader import ModelLoader
from core.data import DataManager
from core.processor import GeometryProcessor
from gui.canvas import PointCloudCanvas
from gui.panels import ObjectListPanel, ActionPanel
from tools.measure import MeasureTool
from tools.select import SelectTool
from tools.calibration import CalibrationTool 

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CrashSite3D - N300 (Final Touch)")
        self.resize(1200, 800)
        
        # 【新增】默认最大化全屏
        self.showMaximized()

        self.current_stage = "PREPARE"
        self.raw_file_path = None
        self.progress_dialog = None 
        
        self.data_manager = DataManager()
        self._init_ui()

        self.tool_measure = MeasureTool(self.canvas, self.data_manager)
        self.tool_select = SelectTool(self.canvas, self.data_manager)
        self.tool_calibration = CalibrationTool(self.canvas, self.data_manager)
        self.current_tool = None
        
        self._connect_signals()
        self.set_stage_prepare()

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0,0,0,0)

        # Top Bar
        self.top_bar_layout = QHBoxLayout()
        self.top_bar_layout.setContentsMargins(5, 5, 5, 5)
        self.lbl_stage = QLabel("阶段 1: 粗修")
        self.lbl_stage.setStyleSheet("font-size: 20px; font-weight: bold; margin-right: 20px;")
        self.top_bar_layout.addWidget(self.lbl_stage)
        
        btn_style = "QPushButton { min-height: 80px; font-size: 20px; font-weight: bold; border-radius: 8px; padding: 10px; }"
        self.btn_open = QPushButton("📂 打开原始点云")
        self.btn_open.setStyleSheet(btn_style + "background-color: #f0ad4e; color: white;")
        self.btn_next = QPushButton("➡️ 下一步 (Next)")
        self.btn_next.setStyleSheet(btn_style + "background-color: #0275d8; color: white;")
        self.btn_undo = QPushButton("↩️ 撤回 (Undo)")
        self.btn_undo.setStyleSheet(btn_style)
        
        # 【新增】退出按钮
        self.btn_exit = QPushButton("🔴 退出")
        self.btn_exit.setStyleSheet(btn_style + "background-color: #d9534f; color: white;")
        self.btn_exit.clicked.connect(self.close) # 直接绑定关闭窗口

        self.btn_tab_measure = QPushButton("📐 测量模式")
        self.btn_tab_select = QPushButton("✏️ 编辑/删除")
        self.btn_tab_measure.setStyleSheet(btn_style)
        self.btn_tab_select.setStyleSheet(btn_style)
        
        # 添加按钮到顶部栏
        for btn in [self.btn_open, self.btn_next, self.btn_undo, self.btn_tab_measure, self.btn_tab_select, self.btn_exit]:
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
        splitter.setSizes([200, 800, 200])
        main_layout.addWidget(splitter)

    def _connect_signals(self):
        self.btn_open.clicked.connect(self.load_raw_file)
        self.btn_next.clicked.connect(self.process_and_advance)
        self.btn_undo.clicked.connect(self.undo_action)
        
        self.btn_tab_measure.clicked.connect(lambda: self.switch_tool("measure"))
        self.btn_tab_select.clicked.connect(lambda: self.switch_tool("select"))
        
        self.panel_action.measure_triggered.connect(self.handle_measure_action)
        self.panel_action.select_triggered.connect(self.handle_select_action)
        self.panel_action.xray_toggled.connect(self.tool_measure.set_xray_enabled)
        
        self.panel_action.select_mode_changed.connect(self.on_select_mode_changed)
        self.panel_action.measure_mode_changed.connect(self.tool_measure.set_interaction_mode)
        self.panel_action.view_change_triggered.connect(self.handle_view_change)

        self.tool_measure.measurement_added.connect(self.panel_list.add_item)
        self.panel_list.item_deleted.connect(self.tool_measure.delete_segment_by_index)
        self.tool_select.request_delete_measurements.connect(self.tool_measure.delete_points_inside_polygon)
        self.tool_measure.measurement_deleted_by_tool.connect(self.panel_list.remove_item_by_index)
        self.panel_list.item_clicked.connect(self.tool_measure.highlight_segment)
        self.panel_action.measure_triggered.connect(lambda a: self.panel_list.clear_all() if a == "clear" else None)

        self.panel_action.calibration_triggered.connect(self.handle_calibration)
        self.tool_calibration.north_tuning_started.connect(lambda: self.panel_action.btn_confirm_north.show())
        self.tool_calibration.status_message.connect(lambda msg: QMessageBox.information(self, "指引", msg))

    def on_select_mode_changed(self, mode):
        if self.current_tool == self.tool_calibration and self.tool_calibration.mode == 'manual_ground':
             self.tool_calibration.set_interaction_mode(mode)
        else:
             self.tool_select.set_interaction_mode(mode)

    def handle_view_change(self, view):
        if view == 'top': self.tool_calibration.view_top()
        elif view == 'front': self.tool_calibration.view_front()
        elif view == 'side': self.tool_calibration.view_side()

    def handle_calibration(self, action):
        self.current_tool = self.tool_calibration
        self.tool_calibration.activate()
        
        if action == "start_ground_calib":
            self.panel_action.widget_calib_ops.show()
            self.tool_calibration.start_ground_calibration_flow()
        elif action == "manual_ground_3pt":
            self.panel_action.update_select_button_text("➕ 标点")
            self.panel_action.btn_s_draw.setChecked(True)
            self.tool_calibration.start_manual_ground_3pt()
        elif action == "confirm_ground":
            self.panel_action.widget_calib_ops.hide()
            self.panel_action.update_select_button_text("✏️ 画圈")
            self.tool_calibration.confirm_ground()
            self.switch_tool("select")
        elif action == "set_north":
            self.tool_calibration.start_set_north()
        elif action == "confirm_north":
            self.tool_calibration.confirm_north()
            self.panel_action.btn_confirm_north.hide()
            self.switch_tool("select")

    def undo_action(self):
        if self.data_manager.undo():
            self.canvas.render_mesh(self.data_manager)
            if self.current_tool == self.tool_measure: self.tool_measure.redraw_all()
        else: QMessageBox.information(self, "提示", "没有可撤回的操作")
    def set_stage_prepare(self):
        self.current_stage = "PREPARE"
        self.lbl_stage.setText("阶段 1: 粗修")
        self.btn_open.show(); self.btn_next.show(); self.btn_undo.show()
        self.btn_tab_measure.hide(); self.btn_tab_select.hide() 
        self.switch_tool("select")
        self.data_manager.set_max_history(1)
    def set_stage_editor(self, work_file_path):
        self.current_stage = "EDITOR"
        self.lbl_stage.setText("阶段 2: 精修")
        self.btn_open.hide(); self.btn_next.hide(); self.btn_undo.show()
        self.btn_tab_measure.show(); self.btn_tab_select.show()
        self.load_work_file(work_file_path)
        self.switch_tool("measure")
        self.data_manager.set_max_history(2)
    def load_raw_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "打开", "", "Point Cloud (*.ply *.pcd)")
        if not fname: return
        self.raw_file_path = fname
        if self.progress_dialog: self.progress_dialog.close()
        self.progress_dialog = QProgressDialog("加载预览...", None, 0, 0, self)
        self.progress_dialog.show()
        self.loader = ModelLoader(fname)
        self.loader.loaded.connect(self.on_raw_loaded)
        self.loader.start()
    def on_raw_loaded(self, points, colors, tex, orig, final):
        if self.progress_dialog: self.progress_dialog.close()
        self.data_manager.load_data(points, colors, tex)
        self.canvas.render_mesh(self.data_manager)
        QMessageBox.information(self, "提示", "已自动校准地面。\n如需调整，请使用校准工具。")
        self.switch_tool("select")
    def update_progress(self, value, text):
        if self.progress_dialog: self.progress_dialog.setValue(value); self.progress_dialog.setLabelText(text)
    def process_and_advance(self):
        if not self.raw_file_path: return
        self.setEnabled(False); QApplication.processEvents()
        self.progress_dialog = QProgressDialog("准备中...", None, 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModal); self.progress_dialog.setCancelButton(None); self.progress_dialog.show(); QApplication.processEvents()
        crop_bbox = self.tool_select.get_crop_bbox()
        if crop_bbox is None:
            if self.data_manager.mesh and self.data_manager.mesh.n_points > 0:
                try:
                    import open3d as o3d
                    points = self.data_manager.mesh.points
                    pcd_temp = o3d.geometry.PointCloud()
                    pcd_temp.points = o3d.utility.Vector3dVector(points)
                    crop_bbox = pcd_temp.get_oriented_bounding_box()
                    crop_bbox.scale(1.05, crop_bbox.get_center())
                except: pass
            else: self.progress_dialog.close(); self.setEnabled(True); return
        self.progress_dialog.setLabelText("后台处理中...")
        transform_matrix = self.tool_calibration.get_transform_matrix()
        preview_points = None
        if self.data_manager.mesh is not None: preview_points = np.array(self.data_manager.mesh.points)
        self.processor = GeometryProcessor(self.raw_file_path, crop_bbox=crop_bbox, transform_matrix=transform_matrix, preview_points=preview_points)
        self.processor.progress.connect(self.update_progress)
        self.processor.finished.connect(self.on_process_finished)
        self.processor.error.connect(self.on_process_error)
        self.processor.start()
    def on_process_finished(self, work_file_path):
        self.progress_dialog.setLabelText("加载模型..."); self.progress_dialog.setValue(0); self.progress_dialog.setRange(0, 0)
        self.set_stage_editor(work_file_path)
    def on_process_error(self, msg):
        if self.progress_dialog: self.progress_dialog.close()
        self.setEnabled(True); QMessageBox.critical(self, "错误", msg)
    def load_work_file(self, path):
        self.loader = ModelLoader(path)
        self.loader.loaded.connect(self.on_work_loaded)
        self.loader.start()
    def on_work_loaded(self, points, colors, tex, orig, final):
        if self.progress_dialog: self.progress_dialog.close()
        self.setEnabled(True)
        self.data_manager.load_data(points, colors, tex)
        self.canvas.render_mesh(self.data_manager)
        self.tool_calibration.deactivate() 
    def switch_tool(self, mode):
        if self.current_tool: self.current_tool.deactivate()
        self.canvas.plotter.enable_trackball_style()
        if mode == "measure": self.current_tool = self.tool_measure; self.panel_action.switch_page(0); self.panel_action.btn_m_view.click()
        elif mode == "select": self.current_tool = self.tool_select; self.panel_action.switch_page(1); self.panel_action.btn_s_view.click() 
        if self.current_tool: self.current_tool.activate()
    def handle_measure_action(self, action):
        if action == "finish": self.tool_measure.finish_segment()
        elif action == "clear": self.tool_measure.clear_all()
    def handle_select_action(self, action):
        if action == "delete_inner":
            self.tool_select.delete_selection(); self.canvas.render_mesh(self.data_manager); self.tool_measure.redraw_all()
        elif action == "invert": self.tool_select.invert_selection(); self.canvas.plotter.render()
    def closeEvent(self, event):
        if self.current_tool: self.current_tool.deactivate()
        if hasattr(self, 'tool_measure'): self.tool_measure.cleanup()
        if hasattr(self, 'tool_select'): self.tool_select.cleanup()
        if hasattr(self, 'canvas') and hasattr(self.canvas, 'plotter'): self.canvas.plotter.close()
        super().closeEvent(event)