import os
import numpy as np
from PySide6.QtCore import QThread, Signal


class GeometryProcessor(QThread):
    progress = Signal(int, str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        raw_path=None,
        crop_bbox=None,
        transform_matrix=None,
        preview_points=None,
        output_path=None,
        input_points=None,
        input_colors=None,
    ):
        super().__init__()
        self.raw_path = raw_path
        self.crop_bbox = crop_bbox
        self.transform_matrix = transform_matrix
        self.preview_points = preview_points
        self.output_path = output_path
        self.input_points = input_points
        self.input_colors = input_colors

    def run(self):
        import shutil
        import tempfile
        import time

        total_t0 = time.time()
        stage_times = []

        def mark(stage, t0):
            stage_times.append((stage, time.time() - t0))

        temp_dir = tempfile.mkdtemp()
        try:
            t0 = time.time()
            import open3d as o3d
            mark("import_open3d", t0)

            self.progress.emit(10, "正在读取原始文件...")
            t0 = time.time()
            if self.input_points is not None:
                pcd = o3d.geometry.PointCloud()
                pcd.points = o3d.utility.Vector3dVector(np.asarray(self.input_points))
                if self.input_colors is not None and len(self.input_colors) > 0:
                    pcd.colors = o3d.utility.Vector3dVector(np.asarray(self.input_colors))
                mark("read_source=in_memory", t0)
            else:
                if not self.raw_path:
                    self.error.emit("未提供原始文件路径")
                    return
                from core.io import safe_load_point_cloud

                pcd = safe_load_point_cloud(self.raw_path, temp_dir)
                mark("read_source=file", t0)

            if pcd.is_empty():
                self.error.emit("文件为空")
                return

            orig_count = len(pcd.points)
            random_count = orig_count

            if self.transform_matrix is not None:
                self.progress.emit(20, "应用空间校准 (地面与指北)...")
                t0 = time.time()
                pcd.transform(self.transform_matrix)
                mark("apply_transform", t0)
            else:
                self.progress.emit(20, "未检测到校准矩阵，尝试自动校准...")
                t0 = time.time()
                try:
                    plane_model, _ = pcd.segment_plane(distance_threshold=0.1, ransac_n=3, num_iterations=1000)
                    a, b, c, _d = plane_model
                    normal = np.array([a, b, c], dtype=np.float64)
                    normal = normal / np.linalg.norm(normal)
                    target = np.array([0.0, 0.0, 1.0], dtype=np.float64)
                    axis = np.cross(normal, target)
                    axis_len = np.linalg.norm(axis)
                    if axis_len > 1e-6:
                        axis = axis / axis_len
                        angle = np.arccos(np.clip(np.dot(normal, target), -1.0, 1.0))
                        k = np.array(
                            [[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]],
                            dtype=np.float64,
                        )
                        r = np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * (k @ k)
                        pcd.rotate(r, center=(0, 0, 0))
                except Exception:
                    pass
                mark("auto_calibration", t0)

            self.progress.emit(40, "正在进行粗裁剪 (BBox)...")
            t0 = time.time()
            if self.crop_bbox is not None:
                pcd = pcd.crop(self.crop_bbox)
            mark("crop_bbox", t0)

            self.progress.emit(60, "生成精修模型并随机降采样...")
            source_count = float(max(1, len(pcd.points)))
            random_target_points = int(getattr(self, "random_target_points", 0) or 0)
            if random_target_points > 0:
                random_target = min(int(source_count), random_target_points)
                ratio = min(1.0, random_target / source_count)
                target_mode = f"config({random_target})"
            else:
                ratio = 1.0
                target_mode = "config(disabled)"
            t0 = time.time()
            pcd = pcd.random_down_sample(sampling_ratio=ratio)
            mark("random_downsample", t0)
            random_count = len(pcd.points)
            print(
                "[TIME][PROCESS][downsample_random] "
                f"target={target_mode}, random_ratio={ratio:.6f}, points={orig_count}->{random_count}",
                flush=True,
            )

            if self.preview_points is not None and len(self.preview_points) > 0:
                self.progress.emit(80, "正在进行精细雕刻 (距离掩码)...")
                t0 = time.time()
                pcd_ref = o3d.geometry.PointCloud()
                pcd_ref.points = o3d.utility.Vector3dVector(self.preview_points)
                dists = np.asarray(pcd.compute_point_cloud_distance(pcd_ref))
                keep_idx = np.where(dists < 0.15)[0]
                pcd = pcd.select_by_index(keep_idx)
                mark("distance_mask", t0)

            self.progress.emit(90, "保存文件...")
            if self.output_path:
                output_path = self.output_path
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
            else:
                base_path = self.raw_path if self.raw_path else "in_memory"
                dir_name = os.path.dirname(base_path) if os.path.dirname(base_path) else "."
                base_name = os.path.splitext(os.path.basename(base_path))[0] or "in_memory"
                output_path = os.path.join(dir_name, f"{base_name}_work.ply")

            t0 = time.time()
            safe_write_path = os.path.join(temp_dir, "temp_write.ply")
            o3d.io.write_point_cloud(safe_write_path, pcd)
            shutil.copyfile(safe_write_path, output_path)
            mark("save_output", t0)

            final_count = len(pcd.points)
            total_s = time.time() - total_t0
            stage_str = ", ".join([f"{name}={sec:.2f}s" for name, sec in stage_times])
            print(
                f"[TIME][PROCESS] {stage_str}, total={total_s:.2f}s, "
                f"points_total={orig_count}, points_random={random_count}, "
                f"points_final={final_count}",
                flush=True,
            )

            self.progress.emit(100, "完成")
            self.finished.emit(output_path)

        except Exception as e:
            import traceback

            traceback.print_exc()
            self.error.emit(str(e))
        finally:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
