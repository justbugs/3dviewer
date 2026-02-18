import os
import numpy as np
from PySide6.QtCore import QThread, Signal
import open3d as o3d

class GeometryProcessor(QThread):
    progress = Signal(int, str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, raw_path, crop_bbox=None, transform_matrix=None, preview_points=None):
        super().__init__()
        self.raw_path = raw_path
        self.crop_bbox = crop_bbox
        self.transform_matrix = transform_matrix
        self.preview_points = preview_points # 【新增】接收一阶段剩下的点

    def run(self):
        try:
            self.progress.emit(10, "正在读取原始文件...")
            pcd = o3d.io.read_point_cloud(self.raw_path)
            if pcd.is_empty():
                self.error.emit("文件为空")
                return

            # --- 1. 自动地面 / 变换 ---
            if self.transform_matrix is not None:
                self.progress.emit(20, "应用空间校准...")
                pcd.transform(self.transform_matrix)
            else:
                # 如果没有矩阵，尝试自动校准（兜底逻辑）
                self.progress.emit(20, "自动找平地面...")
                try:
                    plane_model, inliers = pcd.segment_plane(distance_threshold=0.1, ransac_n=3, num_iterations=1000)
                    [a, b, c, d] = plane_model
                    normal = np.array([a, b, c]); normal = normal / np.linalg.norm(normal)
                    target = np.array([0, 0, 1])
                    axis = np.cross(normal, target); axis_len = np.linalg.norm(axis)
                    if axis_len > 1e-6:
                        axis = axis / axis_len
                        angle = np.arccos(np.dot(normal, target))
                        K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
                        R = np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)
                        pcd.rotate(R, center=(0,0,0))
                except: pass

            # --- 2. 粗剪裁 (Bounding Box) ---
            self.progress.emit(40, "正在进行粗剪裁 (BBox)...")
            if self.crop_bbox is not None:
                pcd = pcd.crop(self.crop_bbox)
            
            # --- 3. 【核心新增】精细去噪 (Distance Mask) ---
            # 如果提供了预览点，就用它做掩模，过滤掉离预览点太远的点（比如已删除的屋顶）
            if self.preview_points is not None and len(self.preview_points) > 0:
                self.progress.emit(60, "正在进行精细雕刻 (去除屋顶/杂点)...")
                
                # 构建预览点的 KDTree (作为参考骨架)
                pcd_ref = o3d.geometry.PointCloud()
                pcd_ref.points = o3d.utility.Vector3dVector(self.preview_points)
                
                # 计算每个高清点到最近预览点的距离
                # 这一步计算量较大，但比重建网格快得多
                dists = pcd.compute_point_cloud_distance(pcd_ref)
                dists = np.asarray(dists)
                
                # 设定阈值：0.15米 (15cm)
                # 意味着：如果你在一阶段删了个点，那么这个点周围 15cm 半径内的高清点都会被连坐删掉
                ind = np.where(dists < 0.15)[0] 
                pcd = pcd.select_by_index(ind)
                
                print(f"精细去噪完成，保留了 {len(ind)} 个点")

            # --- 4. 降采样保存 ---
            self.progress.emit(80, "生成精修模型 (2cm)...")
            pcd = pcd.voxel_down_sample(voxel_size=0.02) 

            self.progress.emit(90, "保存文件...")
            dir_name = os.path.dirname(self.raw_path)
            base_name = os.path.splitext(os.path.basename(self.raw_path))[0]
            output_path = os.path.join(dir_name, f"{base_name}_work.ply")
            
            o3d.io.write_point_cloud(output_path, pcd)
            
            self.progress.emit(100, "完成")
            self.finished.emit(output_path)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))