import sys
import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QPushButton, QListWidget, QLabel, 
                               QFileDialog, QSplitter, QFrame, QMessageBox)
from PySide6.QtCore import Qt, QTimer
import vtk
from PySide6.QtWidgets import QProgressDialog, QApplication # 记得加上这俩

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D Point Cloud Tool (PySide6 + PyVista)")
        self.resize(1200, 800)

        # --- 核心数据 ---
        self.mesh = None
        self.original_mesh = None
        self.current_texture = None  # <--- 新增：专门用来存当前的贴图对象

        # --- 新增：文件信息记忆 ---
        self.current_file_path = None     # 记录当前打开的完整路径 (用于判断是 ply 还是 pcd)
        self.texture_source_path = None   # 记录贴图文件的原始路径 (用于保存时复制图片)

        # --- 历史记录 (Undo) ---
        self.history_stack = [] # 存储 mesh 的深拷贝
        self.MAX_HISTORY = 3    # 最多存3步
        
        # --- 选区相关 ---
        self.select_points = []       # 屏幕上的多边形顶点
        self.selected_indices = []    # 被选中的点的 ID
        self.selection_actor = None   # 红色高亮对象
        
        # --- 新增：套索模式专用变量 ---
        self.is_lasso_active = False  # 是否正在拖拽
        self.lasso_observers = []     # 存储事件监听器的 ID，方便解绑


        # --- 测距相关修改 ---
        self.measure_points = []       # 存储当前路径的所有点坐标
        self.current_path_actors = []  # 存储当前路径所有 3D 对象（点和线）的名字
        self.measure_lines = {}        # 归档的测距数据
        self.measure_counter = 0
        
        self.mode = "view"

        # --- UI 初始化 ---
        self.init_ui()

    def init_ui(self):
        # 1. 创建主分割器
        self.splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(self.splitter)

        # --- 左侧：3D 渲染区域 ---
        self.frame_3d = QFrame()
        layout_3d = QVBoxLayout()
        layout_3d.setContentsMargins(0, 0, 0, 0)
        self.frame_3d.setLayout(layout_3d)
        
        # 嵌入 PyVistaQt
        self.plotter = QtInteractor(self.frame_3d)
        self.plotter.set_background("black")
        self.plotter.add_axes()
        layout_3d.addWidget(self.plotter.interactor)
        
        # --- 左侧悬浮：中间的大按钮 ---
        self.btn_center = QPushButton("打开模型", self.frame_3d)
        self.btn_center.clicked.connect(self.load_file)
        self.btn_center.setStyleSheet("""
            QPushButton {
                background-color: #0078D7;
                color: white;
                font-size: 24px;
                font-weight: bold;
                border-radius: 10px;
                border: 2px solid #005A9E;
            }
            QPushButton:hover {
                background-color: #0063B1;
            }
            QPushButton:pressed {
                background-color: #004E8C;
            }
        """)
        self.btn_center.resize(200, 80)
        self.btn_center.show()

        # 将左侧添加到分割器
        self.splitter.addWidget(self.frame_3d)

        # --- 右侧：控制面板 (找回消失的按钮) ---
        self.panel = QWidget()
        self.panel.setMaximumWidth(300)
        layout_panel = QVBoxLayout()
        self.panel.setLayout(layout_panel)
        
        # 将右侧添加到分割器
        self.splitter.addWidget(self.panel)

        # 1. 打开文件按钮
        btn_open = QPushButton("打开模型 (PCD/PLY)")
        btn_open.clicked.connect(self.load_file)
        layout_panel.addWidget(btn_open)

        btn_save = QPushButton("另存为 (Save)")
        btn_save.clicked.connect(self.save_model)
        btn_save.setStyleSheet("background-color: #2D89EF; color: white; font-weight: bold;")
        layout_panel.addWidget(btn_save)
        

        layout_panel.addWidget(self.create_line()) 

        # 2. 状态标签
        self.lbl_status = QLabel("当前模式: 浏览 (View)")
        self.lbl_status.setStyleSheet("font-weight: bold; color: blue;")
        layout_panel.addWidget(self.lbl_status)

        # 3. 模式按钮组
        btn_view = QPushButton("1. 浏览模式 (触屏/鼠标)")
        btn_view.clicked.connect(lambda: self.set_mode("view"))
        layout_panel.addWidget(btn_view)

        btn_measure = QPushButton("2. 测距模式 (点选两点)")
        btn_measure.clicked.connect(lambda: self.set_mode("measure"))
        layout_panel.addWidget(btn_measure)

        btn_select = QPushButton("3. 框选模式 (暂未实现)")
        btn_select.clicked.connect(lambda: self.set_mode("select"))
        layout_panel.addWidget(btn_select)

        layout_panel.addWidget(self.create_line())
        layout_panel.addWidget(QLabel("编辑操作:"))

        # 撤销按钮
        btn_undo = QPushButton("撤销 (Undo)")
        btn_undo.clicked.connect(self.undo_operation)
        # 绑定键盘快捷键 Ctrl+Z
        btn_undo.setShortcut("Ctrl+Z") 
        layout_panel.addWidget(btn_undo)

        # 删除按钮
        self.btn_delete = QPushButton("删除选中点 (Delete)")
        self.btn_delete.clicked.connect(self.delete_selection)
        self.btn_delete.setStyleSheet("color: red; font-weight: bold;")
        layout_panel.addWidget(self.btn_delete)

        # 反选按钮
        self.btn_invert = QPushButton("反选区域 (Invert)")
        self.btn_invert.clicked.connect(self.invert_selection)
        layout_panel.addWidget(self.btn_invert)

        # 4. 测距列表与删除
        layout_panel.addWidget(QLabel("测距列表:"))
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self.on_list_item_clicked)
        layout_panel.addWidget(self.list_widget)

        btn_del_line = QPushButton("删除选中测距")
        btn_del_line.clicked.connect(self.delete_selected_measurement)
        layout_panel.addWidget(btn_del_line)

        layout_panel.addWidget(self.create_line())

        # 5. 截图按钮
        btn_shot = QPushButton("截屏并保存")
        btn_shot.clicked.connect(self.take_screenshot)
        layout_panel.addWidget(btn_shot)

        # 弹簧 (把内容顶上去)
        layout_panel.addStretch()

        # 设置分割比例 8:2
        self.splitter.setSizes([900, 300])

        # --- 按钮居中修复逻辑 ---
        # 1. 监听分割条拖动
        self.splitter.splitterMoved.connect(self.update_button_center)
        # 2. 启动延迟修正 (修复启动时在左上角的问题)
        QTimer.singleShot(100, self.update_button_center)


    def resizeEvent(self, event):
        """关键修复 3: 窗口大小改变时触发"""
        super().resizeEvent(event)
        self.update_button_center()

    def update_button_center(self, *args):
        """通用的居中计算函数"""
        # 只有按钮存在且显示的时候才计算
        if hasattr(self, 'btn_center') and self.btn_center.isVisible():
            # 1. 获取容器尺寸
            area_width = self.frame_3d.width()
            area_height = self.frame_3d.height()
            
            # 2. 获取按钮尺寸
            btn_width = self.btn_center.width()
            btn_height = self.btn_center.height()
            
            # 3. 算坐标
            new_x = (area_width - btn_width) // 2
            new_y = (area_height - btn_height) // 2
            
            # 4. 移动
            self.btn_center.move(new_x, new_y)
    def create_line(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    # --- 逻辑功能 ---

    def set_mode(self, mode):
        """切换交互模式 (拦截版：测距时强制拦截左键)"""
        self.mode = mode
        
        # 1. 清理 PyVista 的追踪 (防止残留)
        try:
            self.plotter.untrack_click_position(side='left')
            self.plotter.untrack_click_position(side='right')
        except:
            pass

        # 2. 清理所有手动监听器
        if hasattr(self, 'lasso_observers') and self.lasso_observers:
            for obs_id in self.lasso_observers:
                self.plotter.interactor.RemoveObserver(obs_id)
            self.lasso_observers = []

        if hasattr(self, 'measure_observers') and self.measure_observers:
            for obs_id in self.measure_observers:
                self.plotter.interactor.RemoveObserver(obs_id)
            self.measure_observers = []
        
        # 3. 恢复默认交互 (View模式的基础)
        self.plotter.enable_trackball_style()

        # --- 分支逻辑 ---
        if mode == "view":
            self.lbl_status.setText("当前模式: 浏览 (View)")
            self.plotter.setFocus()
            self.clear_current_measurement()
            self._clear_select_visuals()

        elif mode == "measure":
            self.lbl_status.setText("模式: 测距 (左键加点 / 右键结束)")
            self.measure_points = []
            self.current_path_actors = []
            
            # === 核心修改：添加高优先级监听器 ===
            # 优先级设为 10.0 (默认是 0)，确保我们先收到消息
            # 只有 LeftButtonPressEvent，简单直接
            obs1 = self.plotter.interactor.AddObserver("LeftButtonPressEvent", self.on_measure_click, 10.0)
            self.measure_observers = [obs1]
            
            # 右键依然用 PyVista 的封装来结束
            self.plotter.track_click_position(callback=self.on_measure_finish, side='right', viewport=True)
            
        elif mode == "select":
            self.lbl_status.setText("模式: 套索框选 (按住左键画圈 -> 松开自动结算)")
            
            if self.selection_actor:
                self.plotter.remove_actor(self.selection_actor)
                self.selection_actor = None
            self.selected_indices = []
            self.select_points = []

            # 冻结相机
            import vtk
            dummy_style = vtk.vtkInteractorStyleUser()
            self.plotter.interactor.SetInteractorStyle(dummy_style)

            obs1 = self.plotter.interactor.AddObserver("LeftButtonPressEvent", self.on_lasso_start)
            obs2 = self.plotter.interactor.AddObserver("MouseMoveEvent", self.on_lasso_move)
            obs3 = self.plotter.interactor.AddObserver("LeftButtonReleaseEvent", self.on_lasso_end)
            self.lasso_observers = [obs1, obs2, obs3]


    def load_file(self):
        """打开文件 (修复版: 强制使用纯英文临时文件名，解决PCD打开报错)"""
        # 1. 获取文件路径
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Point Cloud", "", "Point Cloud Files (*.ply *.pcd)")
        if not file_name:
            return

        # 2. 记录当前文件路径
        self.current_file_path = file_name
        self.texture_source_path = None
        self.current_texture = None

        # 3. 进度条
        progress = QProgressDialog("正在读取数据...", None, 0, 0, self)
        progress.setWindowTitle("加载中")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        QApplication.processEvents()

        try:
            self.plotter.clear()
            
            import open3d as o3d
            import shutil
            import tempfile
            import os

            # --- 步骤 1: 解析 PLY 文件头 (如果是 PLY) ---
            texture_filename = None
            if file_name.lower().endswith('.ply'):
                try:
                    with open(file_name, 'rb') as f:
                        for _ in range(100):
                            line = f.readline()
                            if b"end_header" in line:
                                break
                            line_str = line.decode('utf-8', errors='ignore').strip()
                            if line_str.startswith("comment TextureFile"):
                                parts = line_str.split()
                                if len(parts) >= 3:
                                    texture_filename = " ".join(parts[2:])
                                    break
                except Exception:
                    pass

            # --- 步骤 2: 准备临时环境 (核心修复) ---
            temp_dir = tempfile.mkdtemp()
            
            try:
                # === 核心修改 START: 强制重命名为纯英文 ===
                # 不管原名叫 "测试.pcd" 还是 "lidar.ply"，统统改名为 "temp_load.xx"
                # 这样 Open3D 读取时路径里就不含中文了
                suffix = os.path.splitext(file_name)[1]  # 获取后缀 (.pcd / .ply)
                safe_name = "temp_safe_load" + suffix    # 纯英文名字
                temp_model_path = os.path.join(temp_dir, safe_name)
                
                shutil.copyfile(file_name, temp_model_path)
                # === 核心修改 END ===
                
                # 2.2 确定并复制贴图 (针对 PLY)
                # 虽然模型改名了，但贴图逻辑依然要找原来的名字
                base_name = os.path.basename(file_name)
                name_only = os.path.splitext(base_name)[0]
                
                original_dir = os.path.dirname(file_name)
                found_texture_path = None
                
                if file_name.lower().endswith('.ply'):
                    candidate_imgs = []
                    if texture_filename:
                        candidate_imgs.append(texture_filename)
                    candidate_imgs.append(name_only + ".png")
                    candidate_imgs.append(name_only + ".jpg")
                    
                    for img_name in candidate_imgs:
                        src_img = os.path.join(original_dir, img_name)
                        if os.path.exists(src_img):
                            # 图片也复制到临时目录，保持原名即可(PyVista读图对中文支持稍好，或者是显式读取)
                            dst_img = os.path.join(temp_dir, img_name)
                            shutil.copyfile(src_img, dst_img)
                            found_texture_path = dst_img
                            
                            self.texture_source_path = src_img 
                            print(f"成功加载贴图文件: {img_name}")
                            break

                # --- 步骤 3: 读取数据 ---
                # Open3D 读取 (现在路径是纯英文的 temp_safe_load.pcd，不会报错了)
                pcd = o3d.io.read_point_cloud(temp_model_path)
                o3d_colors = np.asarray(pcd.colors)
                has_vertex_color = len(o3d_colors) > 0
                
                # 分支判断
                if found_texture_path:
                    # [模式 A]: 纹理贴图
                    print("模式: 纹理贴图")
                    self.mesh = pv.read(temp_model_path)
                    
                    # 读取贴图 (极速版直接读)
                    texture = pv.read_texture(found_texture_path)
                    self.current_texture = texture
                    
                    self.plotter.add_mesh(self.mesh, texture=texture, show_scalar_bar=False, lighting=False)
                    
                elif has_vertex_color:
                    # [模式 B]: 顶点颜色
                    print("模式: 顶点颜色")
                    points = np.asarray(pcd.points)
                    self.mesh = pv.PolyData(points)
                    self.mesh.point_data['RGB'] = o3d_colors
                    self.plotter.add_mesh(self.mesh, scalars='RGB', rgb=True, point_size=2)
                    
                else:
                    # [模式 C]: 纯几何
                    print("模式: 纯几何")
                    points = np.asarray(pcd.points)
                    self.mesh = pv.PolyData(points)
                    self.plotter.add_mesh(self.mesh, point_size=2, color="cyan")

            finally:
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass

            # --- 步骤 4: 收尾 ---
            self.original_mesh = self.mesh.copy()
            self.plotter.add_axes()
            self.plotter.reset_camera()
            self.plotter.camera_set = True 
            
            if hasattr(self, 'btn_center'):
                self.btn_center.hide()
                
            print("加载完成！")

        except Exception as e:
            import traceback
            traceback.print_exc()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"读取失败: {str(e)}")
            
        finally:
            progress.close()


    def on_measure_add(self, point):
        """测距：添加一个点 (修复版：自动处理屏幕坐标转3D)"""
        if self.mode != "measure": return
        
        # === 核心修复 START: 处理 2D 坐标 ===
        # 如果传入的是 2D 屏幕坐标 (长度为2)，我们需要把它转换成 3D 坐标
        final_point = point
        if len(point) < 3:
            try:
                import vtk
                # 使用点云拾取器
                picker = vtk.vtkPointPicker()
                picker.SetTolerance(0.02)
                
                # 在渲染器中执行拾取 (输入是屏幕坐标 point[0], point[1])
                picker.Pick(point[0], point[1], 0, self.plotter.renderer)
                
                # 如果没点中任何东西
                if picker.GetPointId() == -1:
                    # 尝试用兜底拾取器 (WorldPointPicker) 抓取大概位置
                    # 这样至少能在点击处生成一个点，不至于没反应
                    world_picker = vtk.vtkWorldPointPicker()
                    world_picker.Pick(point[0], point[1], 0, self.plotter.renderer)
                    final_point = world_picker.GetPickPosition()
                else:
                    # 点中了，获取精确的 3D 坐标
                    final_point = picker.GetPickPosition()
            except Exception as e:
                print(f"坐标转换失败: {e}")
                return
        # === 核心修复 END ===

        # 存入列表 (注意存的是转换后的 3D 点)
        self.measure_points.append(final_point)
        
        # 1. 画球 (使用 final_point)
        point_actor = self.plotter.add_mesh(
            pv.PolyData([final_point]), 
            color="orange", 
            point_size=10, 
            render_points_as_spheres=True,
            reset_camera=False 
        )
        self.current_path_actors.append(point_actor)
        
        # 2. 画线
        if len(self.measure_points) > 1:
            line = pv.Line(self.measure_points[-2], self.measure_points[-1])
            line_actor = self.plotter.add_mesh(
                line, 
                color="yellow", 
                line_width=3,
                reset_camera=False
            )
            self.current_path_actors.append(line_actor)
            
            # 计算距离
            import numpy as np
            dist = np.linalg.norm(np.array(self.measure_points[-1]) - np.array(self.measure_points[-2]))
            self.lbl_status.setText(f"新增距离: {dist:.4f} | 总点数: {len(self.measure_points)}")
            
        self.plotter.render()

    def on_measure_finish(self, pos):
        """右键：结束测距并结算"""
        if self.mode != "measure": return
        
        # 如果点不够2个，直接取消
        if len(self.measure_points) < 2:
            self.clear_current_measurement()
            self.set_mode("view")
            return

        # 1. 计算总长度
        total_dist = 0.0
        points = np.array(self.measure_points)
        for i in range(len(points) - 1):
            dist = np.linalg.norm(points[i] - points[i+1])
            total_dist += dist

        # 2. 添加到列表
        self.measure_counter += 1
        count = len(points)
        item_text = f"Path {self.measure_counter}: {total_dist:.2f} (包含 {count} 点)"
        self.list_widget.addItem(item_text)

        # 3. 归档数据 (把所有 Actor 名字存起来，方便删除)
        self.measure_lines[item_text] = {
            'actors': list(self.current_path_actors), # 复制一份列表
            'dist': total_dist
        }

        # 4. 重置当前缓存
        self.measure_points = []
        self.current_path_actors = []

        # 5. 自动切回浏览模式
        self.set_mode("view")


    def on_click_pick(self, *args):
        """鼠标点击回调 (修复版：红点大小固定，不随缩放改变)"""
        if self.mode != "measure":
            return

        try:
            point = self.plotter.pick_mouse_position()
        except:
            return
            
        if point is None:
            return

        # --- 关键修改 START ---
        # 旧做法：创建一个物理球体 (随缩放变大)
        # sphere = pv.Sphere(radius=0.5, center=point)
        # self.plotter.add_mesh(sphere, ...)

        # 新做法：创建一个只包含这一个点的点云对象
        picked_point_cloud = pv.PolyData([point])
        
        actor_name = f"temp_pt_{len(self.measure_points)}"
        
        # 使用 add_points 渲染
        # render_points_as_spheres=True 让它看起来圆圆的
        # point_size=15 表示它在屏幕上固定为 15 像素大小
        self.plotter.add_points(picked_point_cloud, 
                                color="red", 
                                render_points_as_spheres=True,
                                point_size=15,  # 可以根据喜好调整这个像素值
                                name=actor_name, 
                                reset_camera=False)
        # --- 关键修改 END ---
        
        self.measure_points.append(point)

        # 2. 如果选中了两个点，开始连线
        if len(self.measure_points) == 2:
            p1 = np.array(self.measure_points[0])
            p2 = np.array(self.measure_points[1])
            dist = np.linalg.norm(p1 - p2)
            
            line = pv.Line(p1, p2)
            # 线条依然是物理对象，随缩放变粗细是正常的，保持不变
            line_actor = self.plotter.add_mesh(line, color="yellow", line_width=4, reset_camera=False)
            
            self.measure_counter += 1
            item_text = f"Line {self.measure_counter}: {dist:.2f}"
            self.list_widget.addItem(item_text)
            
            self.measure_lines[item_text] = {
                'points': (p1, p2),
                'line_actor': line_actor,
                'dist': dist
            }
            
            self.measure_points = []
            self.plotter.remove_actor("temp_pt_0")
            self.plotter.remove_actor("temp_pt_1")

    def on_list_item_clicked(self, item):
        """列表点击高亮"""
        text = item.text()
        if text in self.measure_lines:
            # 这里可以做高亮逻辑，例如把线变成绿色
            # PyVista修改颜色需要访问 actor.GetProperty().SetColor(...)
            # 简单起见，我们闪烁一下或重绘为绿色
            data = self.measure_lines[text]
            # 实际项目中需要更复杂的 Actor 管理
            print(f"选中了: {text}")

    def clear_current_measurement(self):
        """清理未完成的测距痕迹"""
        for actor_name in self.current_path_actors:
            self.plotter.remove_actor(actor_name)
        self.measure_points = []
        self.current_path_actors = []

    def delete_selected_measurement(self):
        """删除列表选中项 (支持多段线删除)"""
        row = self.list_widget.currentRow()
        if row == -1: return
        
        item = self.list_widget.takeItem(row)
        text = item.text()
        
        if text in self.measure_lines:
            data = self.measure_lines[text]
            # 遍历删除该路径下的所有点和线
            for actor_name in data['actors']:
                self.plotter.remove_actor(actor_name)
            del self.measure_lines[text]


    def save_history(self):
        """保存当前状态到历史记录 (仅保留最近3步)"""
        if self.mesh is None: return
        
        # 深拷贝当前网格状态
        current_state = self.mesh.copy()
        self.history_stack.append(current_state)
        
        # 如果超过3步，把最旧的丢掉
        if len(self.history_stack) > self.MAX_HISTORY:
            self.history_stack.pop(0)
            
        print(f"历史记录已保存，当前步数: {len(self.history_stack)}")

    def undo_operation(self):
        """撤销操作 (Ctrl+Z)"""
        if not self.history_stack:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "提示", "没有更多历史记录了 (仅保留最近3步)")
            return

        # 弹出最近的一个状态
        prev_mesh = self.history_stack.pop()
        self.mesh = prev_mesh
        
        # 刷新显示
        self.refresh_scene()
        print("已撤销上一步操作")

    def refresh_scene(self):
        """通用刷新函数：清空场景并重新画 mesh (支持 RGB 和 贴图)"""
        self.plotter.clear()
        self.plotter.add_axes()
        
        # 1. 优先检查是否有贴图 (因为你的模型大概率是这种情况)
        if self.current_texture is not None:
            # 必须再次传入 texture 对象，并关闭光照以保持原色
            self.plotter.add_mesh(self.mesh, 
                                  texture=self.current_texture, 
                                  show_scalar_bar=False, 
                                  lighting=False,   # 保持无光照
                                  reset_camera=False) # 保持视角

        # 2. 其次检查是否有顶点颜色 (RGB)
        elif 'RGB' in self.mesh.point_data:
            self.plotter.add_mesh(self.mesh, 
                                  scalars='RGB', 
                                  rgb=True, 
                                  point_size=2, 
                                  render_points_as_spheres=False,
                                  reset_camera=False)
        
        # 3. 都没有，就画纯色
        else:
            self.plotter.add_mesh(self.mesh, 
                                  point_size=2, 
                                  color="cyan", 
                                  render_points_as_spheres=False,
                                  reset_camera=False)
            
        # 这一步是为了防止刷新后选区高亮还在，但这会导致刚删完东西选区还红着
        # 通常刷新就意味着操作结束，清空选区索引是安全的
        self.selected_indices = []
    def _clear_select_visuals(self):
        """清理选区过程中的临时点"""
        for i in range(len(self.select_points) + 1):
            self.plotter.remove_actor(f"select_pt_{i}")
        self.select_points = []


    # --- 套索 (Lasso) 事件回调 ---

    def on_lasso_start(self, obj, event):
        """左键按下：开始记录轨迹 (极简版，防止触发重置)"""
        if self.mode != "select": return
        
        self.is_lasso_active = True
        self.select_points = []
        
        # 清空数据列表，但不要在这里调用 remove_actor！
        # 留给 on_lasso_move 去覆盖它，或者留给松开鼠标时去清理
        self.lasso_visual_points = [] 
        
        # 记录起点
        interactor = self.plotter.interactor
        self.select_points.append(interactor.GetEventPosition())

    def on_lasso_move(self, obj, event):
        """鼠标移动：记录路径并绘制连续线条"""
        if self.mode != "select" or not self.is_lasso_active: return

        interactor = self.plotter.interactor
        x, y = interactor.GetEventPosition()
        
        # 1. 记录 2D 坐标
        self.select_points.append((x, y))
        
        # 2. 视觉反馈 (投影到焦平面画线)
        try:
            renderer = self.plotter.renderer
            focal_point = self.plotter.camera.GetFocalPoint()
            renderer.SetWorldPoint(*focal_point, 1.0)
            renderer.WorldToDisplay()
            _, _, focal_depth = renderer.GetDisplayPoint()
            
            renderer.SetDisplayPoint(x, y, focal_depth)
            renderer.DisplayToWorld()
            world_pt_4d = renderer.GetWorldPoint()
            
            if world_pt_4d[3] != 0:
                pick_pos = np.array(world_pt_4d[:3]) / world_pt_4d[3]
                self.lasso_visual_points.append(pick_pos)
                
                if len(self.lasso_visual_points) > 1:
                    points_array = np.array(self.lasso_visual_points)
                    line_mesh = pv.lines_from_points(points_array)
                    
                    self.lasso_visual_actor = self.plotter.add_mesh(
                        line_mesh, 
                        color="magenta", 
                        line_width=4, 
                        name="lasso_trace_dynamic", 
                        reset_camera=False  # <--- 关键！必须设为 False
                    )
                    self.plotter.render()
        except Exception:
            pass

    def on_lasso_end(self, obj, event):
        """左键松开：结束并结算"""
        if self.mode != "select" or not self.is_lasso_active:
            return
            
        self.is_lasso_active = False
        
        # 如果点太少，视为误触
        if len(self.select_points) < 10:
            print("选区路径太短，已忽略")
            self._clear_select_visuals()
            return
            
        print(f"套索结束，路径点数: {len(self.select_points)}")
        
        # 直接调用之前的计算逻辑（稍微改一下参数传递方式）
        self.calculate_selection()

    def _clear_select_visuals(self):
        """清理套索轨迹"""
        self.plotter.remove_actor("lasso_trace_dynamic")
        self.lasso_visual_points = []

    def calculate_selection(self):
        """核心计算逻辑"""
        # 1. 准备工作
        try:
            from matplotlib.path import Path
        except ImportError:
            return

        polygon_path = Path(self.select_points)
        
        try:
            # ... (中间的矩阵计算逻辑保持不变，为了省篇幅我省略了中间那几十行数学公式) ...
            # ... 请保留原有的投影计算代码 ...
            
            # 这里我把中间省略了，直接快进到最后 add_mesh 的地方
            # 确保你之前的投影矩阵计算代码都在！
            
            # --- 假设你已经算出了 selected_indices ---
            # (如果需要我完整贴出中间代码请告诉我，否则只改下面这几行即可)
            
            # 获取 win_size, renderer, points_3d 等等...
            # 这里的代码和之前是一模一样的，不需要动
            win_size = self.plotter.window_size
            width, height = win_size
            renderer = self.plotter.renderer
            points_3d = self.mesh.points
            n_points = len(points_3d)
            mat = self.plotter.camera.GetCompositeProjectionTransformMatrix(renderer.GetTiledAspectRatio(), -1, 1)
            np_mat = np.zeros((4, 4))
            for r in range(4):
                for c in range(4):
                    np_mat[r, c] = mat.GetElement(r, c)
            points_4d = np.hstack((points_3d, np.ones((n_points, 1))))
            clip_coords = points_4d @ np_mat.T
            w = clip_coords[:, 3:4]
            ndc = clip_coords[:, :3] / (w + 1e-10)
            screen_coords = np.zeros((n_points, 2))
            screen_coords[:, 0] = (ndc[:, 0] + 1) / 2.0 * width
            screen_coords[:, 1] = (ndc[:, 1] + 1) / 2.0 * height
            mask = polygon_path.contains_points(screen_coords, radius=0)
            final_mask = mask & (clip_coords[:, 3] > 0)
            self.selected_indices = np.where(final_mask)[0]

            if len(self.selected_indices) == 0:
                print("未选中任何点")
                self._clear_select_visuals()
                # 就算没选中，切回浏览模式也顺便设一下
                self.set_mode("view")
                return

            # --- 高亮显示 ---
            if self.selection_actor:
                self.plotter.remove_actor(self.selection_actor)
            
            selected_mesh = self.mesh.extract_points(self.selected_indices)
            
            self.selection_actor = self.plotter.add_mesh(
                selected_mesh, 
                color="red", 
                point_size=3, 
                render_points_as_spheres=False, 
                name="selection_highlight",
                reset_camera=False  # <--- 关键！必须设为 False
            )
            
            print(f"选中了 {len(self.selected_indices)} 个点")
            
        except Exception as e:
            print(f"选区计算失败: {e}")
            import traceback
            traceback.print_exc()
            
        # 5. 清理轨迹 & 自动切回浏览模式
        self._clear_select_visuals()
        self.set_mode("view")



    def delete_selection(self):
        """删除当前选中的点"""
        if len(self.selected_indices) == 0:
            return
            
        # 1. 保存历史 (Ctrl+Z)
        self.save_history()
        
        # 2. 计算“要保留的点” (总集 - 选集)
        all_ids = np.arange(self.mesh.n_points)
        # 使用 np.isin 生成布尔掩码 (比 setdiff1d 快)
        mask_to_remove = np.isin(all_ids, self.selected_indices)
        mask_to_keep = ~mask_to_remove
        
        # 3. 提取新网格
        # PyVista 的 extract_points 接受布尔掩码或索引
        new_mesh = self.mesh.extract_points(mask_to_keep)
        
        # 4. 更新数据
        self.mesh = new_mesh
        
        # 5. 刷新画面
        self.refresh_scene()
        print("删除完成")

    def invert_selection(self):
        """反选 (针对整个文件)"""
        if self.mesh is None: return
        
        # 1. 全集
        all_ids = np.arange(self.mesh.n_points)
        
        # 2. 如果当前没选中，就是全选
        if len(self.selected_indices) == 0:
            new_selection = all_ids
        else:
            # 3. 计算补集 (反选)
            # distinct_ids = 全部ID 剔除 已选ID
            new_selection = np.setdiff1d(all_ids, self.selected_indices)
            
        self.selected_indices = new_selection
        
        # 4. 更新高亮显示
        # 提取这些点用于显示
        inverted_mesh = self.mesh.extract_points(new_selection)
        
        if self.selection_actor:
            self.plotter.remove_actor(self.selection_actor)
            
        # --- 错误修复：这里要传入 inverted_mesh ---
        self.selection_actor = self.plotter.add_mesh(
            inverted_mesh,  # <--- 之前写成了 selected_mesh，导致报错
            color="red", 
            point_size=3, 
            render_points_as_spheres=False, 
            name="selection_highlight",
            reset_camera=False # 保持视角不动
        )
        print(f"反选完成，当前选中 {len(self.selected_indices)} 个点")


    def save_model(self):
        """保存模型 (终极版: 修复中文文件名乱码 + 颜色变黑 + PLY格式支持)"""
        if self.mesh is None:
            return

        # 1. 判断源文件格式
        if self.current_file_path and self.current_file_path.lower().endswith('.pcd'):
            default_ext = "pcd"
            file_filter = "Point Cloud Data (*.pcd)"
        else:
            default_ext = "ply"
            file_filter = "Polygon File Format (*.ply)"

        # 2. 弹出保存对话框 (这里获取到的 save_path 是正确的中文路径)
        save_path, _ = QFileDialog.getSaveFileName(self, "Save Model", "", file_filter)
        if not save_path:
            return

        # 进度条
        progress = QProgressDialog("正在保存...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        QApplication.processEvents()

        try:
            import os
            import shutil
            import numpy as np

            # === 核心策略: 生成一个纯英文的临时路径 ===
            # 我们先存到 save_path 同级目录下，但名字叫 temp_safe_save_xyz.ext
            # 这样既避免了跨磁盘移动的耗时，又避开了中文路径 bug
            dir_name = os.path.dirname(save_path)
            file_ext = os.path.splitext(save_path)[1] # .pcd or .ply
            temp_filename = "temp_safe_save_buffer" + file_ext
            temp_save_path = os.path.join(dir_name, temp_filename)

            # --- 分支 A: 保存为 PCD (纯点云) ---
            if default_ext == "pcd":
                import open3d as o3d
                
                points = self.mesh.points
                pcd = o3d.geometry.PointCloud()
                pcd.points = o3d.utility.Vector3dVector(points)
                
                # 颜色修复 (智能判断 0-1 还是 0-255)
                if 'RGB' in self.mesh.point_data:
                    current_colors = self.mesh.point_data['RGB']
                    if current_colors.dtype.kind == 'f' and current_colors.max() <= 1.05:
                         final_colors = current_colors
                    else:
                         final_colors = current_colors / 255.0
                    pcd.colors = o3d.utility.Vector3dVector(final_colors)
                
                # [关键] 保存到纯英文临时路径
                o3d.io.write_point_cloud(temp_save_path, pcd)

            # --- 分支 B: 保存为 PLY (可能带贴图) ---
            else:
                # 格式修复 (转 PolyData)
                if not isinstance(self.mesh, pv.PolyData):
                    mesh_to_save = self.mesh.extract_surface()
                else:
                    mesh_to_save = self.mesh
                
                # [关键] 保存到纯英文临时路径
                mesh_to_save.save(temp_save_path, binary=True)
                
                # 处理贴图
                if self.texture_source_path and os.path.exists(self.texture_source_path):
                    # 1. 目标贴图名 (比如: 中文模型.png)
                    base_name_cn = os.path.splitext(os.path.basename(save_path))[0]
                    tex_ext = os.path.splitext(self.texture_source_path)[1]
                    new_tex_name_cn = base_name_cn + tex_ext # 中文文件名.png
                    
                    # 2. 目标贴图完整路径
                    new_tex_path = os.path.join(dir_name, new_tex_name_cn)
                    
                    # 3. 复制贴图 (Python 的 shutil 支持中文路径，这里可以直接复制到位)
                    shutil.copyfile(self.texture_source_path, new_tex_path)
                    print(f"贴图已复制: {new_tex_path}")
                    
                    # 4. 修改 PLY 文件头 (让它指向那个中文名的图片)
                    # 注意：如果 viewer 不支持 UTF-8 头文件，这里可能会有问题，但通常现代 viewer 都支持
                    patch_success = False
                    with open(temp_save_path, 'rb') as f:
                        content = f.read()
                    
                    header_end_tag = b"end_header"
                    split_idx = content.find(header_end_tag)
                    
                    if split_idx != -1:
                        # 注入 UTF-8 编码的中文文件名
                        injection = f"comment TextureFile {new_tex_name_cn}\n".encode('utf-8')
                        new_content = content[:split_idx] + injection + content[split_idx:]
                        
                        with open(temp_save_path, 'wb') as f:
                            f.write(new_content)
                        patch_success = True

            # === 核心策略收尾: 将临时英文文件重命名为目标中文文件 ===
            # Python 的 os.rename/replace 对 Unicode 支持很好
            if os.path.exists(save_path):
                os.remove(save_path) # 如果目标存在，先删除
            
            os.rename(temp_save_path, save_path)
            print(f"文件已重命名为: {save_path}")

            QMessageBox.information(self, "成功", f"模型已保存至:\n{save_path}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"保存失败: {str(e)}")
            # 出错时尝试清理临时文件
            try:
                if 'temp_save_path' in locals() and os.path.exists(temp_save_path):
                    os.remove(temp_save_path)
            except:
                pass
        
        finally:
            progress.close()

    # --- 测距模式专用交互 (解决冲突) ---

    def on_measure_click(self, obj, event):
        """测距模式点击处理 (点击即加点，并阻止旋转)"""
        # 再次确认模式 (双重保险)
        if self.mode != "measure":
            return

        try:
            import vtk
            interactor = self.plotter.interactor
            click_pos = interactor.GetEventPosition()

            # 1. 拾取点 (使用 PointPicker 抓取点云)
            picker = vtk.vtkPointPicker()
            picker.SetTolerance(0.02)
            picker.Pick(click_pos[0], click_pos[1], 0, self.plotter.renderer)

            final_point = None
            if picker.GetPointId() != -1:
                final_point = picker.GetPickPosition()
            else:
                # 兜底：如果没点中具体的点，抓一个大概的世界坐标
                world_picker = vtk.vtkWorldPointPicker()
                world_picker.Pick(click_pos[0], click_pos[1], 0, self.plotter.renderer)
                # 检查一下是否真的在相机视野内
                final_point = world_picker.GetPickPosition()

            if final_point:
                # 2. 存点与绘制
                self.measure_points.append(final_point)
                
                # 画点
                point_actor = self.plotter.add_mesh(
                    pv.PolyData([final_point]), 
                    color="orange", 
                    point_size=10, 
                    render_points_as_spheres=True,
                    reset_camera=False
                )
                self.current_path_actors.append(point_actor)
                
                # 画线 (如果有2个点以上)
                if len(self.measure_points) > 1:
                    import numpy as np
                    line = pv.Line(self.measure_points[-2], self.measure_points[-1])
                    line_actor = self.plotter.add_mesh(
                        line, 
                        color="yellow", 
                        line_width=3,
                        reset_camera=False
                    )
                    self.current_path_actors.append(line_actor)
                    
                    dist = np.linalg.norm(np.array(self.measure_points[-1]) - np.array(self.measure_points[-2]))
                    self.lbl_status.setText(f"新增距离: {dist:.4f} | 总点数: {len(self.measure_points)}")
                
                self.plotter.render()

            # === 核心核武器 ===
            # 打开“中止标志” (AbortFlag)
            # 这句代码的意思是：“这个点击事件到此为止，别再传给后面的旋转控制器了！”
            # 这样就完美实现了“点击加点”且“不旋转”。
            obj.SetAbortFlag(1) 

        except Exception as e:
            print(f"测距点击异常: {e}")


    def on_measure_press(self, obj, event):
        """测距模式 - 左键按下：只记录位置，不加点"""
        if self.mode != "measure": return
        # 记录按下时的屏幕坐标 (x, y)
        self.measure_start_pos = self.plotter.interactor.GetEventPosition()
        
        # 注意：这里我们不拦截事件，让 VTK 继续处理（这样相机旋转功能就能生效）

    def on_measure_release(self, obj, event):
        """测距模式 - 左键松开 (点云专用版)"""
        # 1. 基本检查
        if self.mode != "measure" or self.measure_start_pos is None: 
            return
        
        # 2. 获取松开时的坐标
        interactor = self.plotter.interactor
        end_pos = interactor.GetEventPosition()
        
        # 3. 计算移动距离
        dx = end_pos[0] - self.measure_start_pos[0]
        dy = end_pos[1] - self.measure_start_pos[1]
        move_dist = (dx**2 + dy**2) ** 0.5
        
        # 重置起始点
        self.measure_start_pos = None

        # 4. 判断点击 (把容错放大到 10 像素，适应触屏手抖)
        if move_dist < 10:
            try:
                import vtk
                # === 核心修改：改用 PointPicker ===
                # PointPicker 会寻找这根射线上最近的“点”，非常适合点云
                picker = vtk.vtkPointPicker()
                
                # 设置容差 (决定了鼠标偏离多少像素还能吸附到点上)
                # 0.02 是一个比较舒服的经验值
                picker.SetTolerance(0.02)
                
                renderer = self.plotter.renderer
                picker.Pick(end_pos[0], end_pos[1], 0, renderer)
                
                if picker.GetPointId() != -1:
                    # 击中了！获取点的 3D 坐标
                    pick_pos = picker.GetPickPosition()
                    self.on_measure_add(pick_pos)
                    print(f"选中点坐标: {pick_pos}")
                else:
                    # 如果 PointPicker 没抓到，尝试用 WorldPicker 兜底
                    # (防止用户点到了两个点中间的空隙)
                    world_picker = vtk.vtkWorldPointPicker()
                    world_picker.Pick(end_pos[0], end_pos[1], 0, renderer)
                    pick_pos = world_picker.GetPickPosition()
                    # 只有当抓到的 Z 不为 0 (或其他判断) 才认为是有效点击
                    # 这里简单粗暴直接加，或者你可以选择不加
                    self.on_measure_add(pick_pos)
                    print("触发兜底拾取")

            except Exception as e:
                print(f"拾取失败: {e}")





    def take_screenshot(self):
        """截屏"""
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Screenshot", "screenshot.png", "Images (*.png)")
        if file_name:
            self.plotter.screenshot(file_name)
            QMessageBox.information(self, "Success", "截图已保存")


    def closeEvent(self, event):
        """窗口关闭事件：手动清理 PyVista，防止退出时报错"""
        try:
            # 1. 显式关闭 plotter，停止渲染循环
            if hasattr(self, 'plotter'):
                self.plotter.close()
            
            # 2. 手动断开数据引用
            self.mesh = None
            self.original_mesh = None
            
        except Exception:
            pass # 如果清理过程出错，直接忽略，反正都要退出了
            
        # 3. 调用父类的关闭事件，正常退出
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())