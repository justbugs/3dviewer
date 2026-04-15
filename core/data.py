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

    def clear_all(self):
        self.mesh = None
        self.original_mesh = None
        self.current_texture = None
        self.history = []

    def load_data(self, mesh_or_points, colors=None, texture=None, faces=None, uvs=None):
        """加载数据并清空历史。
        mesh_or_points: pv.DataSet (PolyData/UnstructuredGrid) 或 numpy array 格式的点云
        texture: pv.Texture 对象或 None（已在后台线程读好，不再是路径）
        """
        self.history = []

        if mesh_or_points is None or (not isinstance(mesh_or_points, pv.DataSet) and len(mesh_or_points) == 0):
            self.clear_all()
            return

        # 创建 Mesh
        if isinstance(mesh_or_points, pv.DataSet):
            cloud = mesh_or_points
        else:
            if faces is not None and len(faces) > 0:
                cloud = pv.PolyData(mesh_or_points, faces)
            else:
                cloud = pv.PolyData(mesh_or_points)

            if colors is not None and len(colors) > 0:
                cloud.point_data['RGB'] = colors

            if uvs is not None and len(uvs) > 0:
                cloud.active_t_coords = uvs

        # 为存活点记录初始序号，用于自动保存时的状态掩码 (Stage 2)
        if '_orig_idx' not in cloud.point_data:
            cloud.point_data['_orig_idx'] = np.arange(cloud.n_points)

        self.mesh = cloud
        # n_faces_strict 只统计三角/多边形面，不统计顶点单元格
        # 点云 n_faces_strict==0，带面片网格 >0
        has_faces = cloud.n_faces_strict > 0 if hasattr(cloud, 'n_faces_strict') else cloud.n_cells > 0
        if has_faces:
            self.original_mesh = cloud  # 带面片网格直接引用，不拷贝
        else:
            self.original_mesh = cloud.copy()

        # 接受已在后台线程读好的纹理对象
        if texture is not None and hasattr(texture, 'GetMTime'):  # pv.Texture check
            self.current_texture = texture
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

    def undo(self):
        """执行撤回"""
        if not self.history:
            return False
            
        # 恢复上一步
        prev_mesh = self.history.pop()
        self.mesh = prev_mesh
        return True

    def set_max_history(self, limit):
        self.max_history = limit
        # 如果当前超出，裁剪
        while len(self.history) > limit:
            self.history.pop(0)
