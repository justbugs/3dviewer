import os
import shutil
import tempfile
import numpy as np
from PySide6.QtCore import QThread, Signal
try:
    import open3d as o3d
except ImportError:
    pass

class ModelLoader(QThread):
    # 信号：点坐标, 颜色, 纹理路径, 原始点数, 优化后点数
    loaded = Signal(np.ndarray, np.ndarray, str, int, int)
    error = Signal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        temp_dir = tempfile.mkdtemp()
        try:
            # 1. 安全重命名 (解决中文路径)
            suffix = os.path.splitext(self.file_path)[1]
            safe_name = "temp_safe_load" + suffix
            temp_model_path = os.path.join(temp_dir, safe_name)
            shutil.copyfile(self.file_path, temp_model_path)

            # 2. 纹理查找逻辑 (省略部分细节，保持之前逻辑)
            texture_path = self._find_texture(self.file_path, temp_dir)

            # 3. Open3D 读取与降采样
            pcd = o3d.io.read_point_cloud(temp_model_path)
            if pcd.is_empty():
                self.error.emit("文件为空")
                return

            orig_count = len(pcd.points)
            if orig_count > 3000000: # N300 阈值
                voxel_size = np.linalg.norm(pcd.get_axis_aligned_bounding_box().get_extent()) / 500.0
                pcd = pcd.voxel_down_sample(voxel_size=voxel_size)

            final_count = len(pcd.points)
            points = np.asarray(pcd.points).astype(np.float32) # 强制 float32
            
            colors = np.array([])
            if pcd.has_colors():
                colors = np.asarray(pcd.colors).astype(np.float32)

            self.loaded.emit(points, colors, texture_path, orig_count, final_count)

        except Exception as e:
            self.error.emit(str(e))
        finally:
            try: shutil.rmtree(temp_dir)
            except: pass

    def _find_texture(self, original_path, temp_dir):
        # 简化的纹理查找，保持原有逻辑
        base_dir = os.path.dirname(original_path)
        base_name = os.path.splitext(os.path.basename(original_path))[0]
        for ext in ['.png', '.jpg', '.jpeg']:
            src = os.path.join(base_dir, base_name + ext)
            if os.path.exists(src):
                dst = os.path.join(temp_dir, base_name + ext)
                shutil.copyfile(src, dst)
                return dst
        return ""