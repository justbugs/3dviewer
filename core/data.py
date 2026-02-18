import pyvista as pv
import numpy as np

class DataManager:
    def __init__(self):
        self.mesh = None            # 当前显示的 PyVista PolyData
        self.original_mesh = None   # 原始备份 (用于重置)
        self.current_texture = None # 纹理
        
        # 撤回栈
        self.history = []
        self.max_history = 1 # 默认限制，会在 main_window 动态调整

    def load_data(self, points, colors, texture_path=None):
        """加载数据并清空历史"""
        self.history = [] # 新文件加载时清空历史
        
        if points is None or len(points) == 0:
            self.mesh = None
            self.original_mesh = None
            self.current_texture = None
            return

        # 创建 Mesh
        cloud = pv.PolyData(points)
        if colors is not None and len(colors) > 0:
            cloud.point_data['RGB'] = colors

        self.mesh = cloud
        self.original_mesh = cloud.copy() # 备份一份

        # 加载纹理
        if texture_path and len(texture_path) > 0:
            try:
                self.current_texture = pv.read_texture(texture_path)
                # 处理纹理坐标 (假设 ply 自带 UV)
            except:
                self.current_texture = None
        else:
            self.current_texture = None

    def push_history(self):
        """保存当前状态到历史栈"""
        if self.mesh is None: return
        
        # 深拷贝当前 mesh
        snapshot = self.mesh.copy()
        self.history.append(snapshot)
        
        # 限制长度
        if len(self.history) > self.max_history:
            self.history.pop(0) # 移除最旧的
            
        print(f"DEBUG: 历史记录步数 {len(self.history)}")

    def undo(self):
        """执行撤回"""
        if not self.history:
            print("没有可撤回的操作")
            return False
            
        # 恢复上一步
        prev_mesh = self.history.pop()
        self.mesh = prev_mesh
        print(f"DEBUG: 撤回成功，剩余步数 {len(self.history)}")
        return True

    def set_max_history(self, limit):
        self.max_history = limit
        # 如果当前超出，裁剪
        while len(self.history) > limit:
            self.history.pop(0)