import io
import os
import shutil
import tempfile
import time

import numpy as np
from PySide6.QtCore import QThread, Signal

from core.io import safe_load_point_cloud


class ModelLoader(QThread):
    # signal: mesh object, points, colors, texture, original point count, final point count
    loaded = Signal(object, np.ndarray, np.ndarray, object, int, int)
    error = Signal(str)

    def __init__(self, file_path, texture_path=None):
        super().__init__()
        self.file_path = file_path
        self.texture_path = texture_path

    def run(self):
        total_t0 = time.time()
        stage_times = []
        suffix = os.path.splitext(self.file_path)[1].lower()

        def mark(stage, t0):
            stage_times.append((stage, time.time() - t0))

        def emit_with_summary(mode, mesh, points, colors, texture, orig_count, final_count):
            total_s = time.time() - total_t0
            stage_str = ", ".join([f"{name}={sec:.2f}s" for name, sec in stage_times])
            print(
                f"[TIME][LOAD][{mode}] {stage_str}, total={total_s:.2f}s, "
                f"points={orig_count}->{final_count}",
                flush=True,
            )
            self.loaded.emit(mesh, points, colors, texture, orig_count, final_count)

        try:
            t0 = time.time()
            temp_dir = tempfile.mkdtemp()
            mark("mkdtemp", t0)
        except Exception as e:
            self.error.emit(f"鏃犳硶鍒涘缓涓存椂鐩綍: {e}")
            return

        try:
            t0 = time.time()
            import open3d as _o3d  # noqa: F401
            mark("import_open3d", t0)

            temp_model_path = self.file_path

            t0 = time.time()
            texture_real_path = ""
            if suffix not in [".las", ".laz"]:
                if self.texture_path and os.path.exists(self.texture_path):
                    texture_real_path = self.texture_path
                else:
                    texture_real_path = self._find_texture(self.file_path)
            mark("find_texture", t0)

            if texture_real_path:
                from PIL import Image
                import pyvista as pv

                t0 = time.time()
                with open(texture_real_path, "rb") as f:
                    img = Image.open(io.BytesIO(f.read()))
                    img.load()
                mark("read_texture", t0)

                t0 = time.time()
                max_dim = 4096
                if max(img.size) > max_dim:
                    img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                img_rgb = img.convert("RGB")
                mark("prepare_texture", t0)

                t0 = time.time()
                try:
                    mesh = pv.read(temp_model_path)
                    mark("read_mesh_direct", t0)
                except Exception:
                    t_copy = time.time()
                    safe_name = "temp_safe_load" + suffix
                    temp_model_path = os.path.join(temp_dir, safe_name)
                    shutil.copyfile(self.file_path, temp_model_path)
                    mark("copy_input_fallback", t_copy)

                    t_read = time.time()
                    mesh = pv.read(temp_model_path)
                    mark("read_mesh_fallback", t_read)

                pd = mesh.point_data
                uv_key = None
                if "TCoords" in pd:
                    uv_key = "TCoords"
                elif "texture_u" in pd and "texture_v" in pd:
                    mesh.point_data["TCoords"] = np.column_stack((pd["texture_u"], pd["texture_v"]))
                    uv_key = "TCoords"
                elif "u" in pd and "v" in pd:
                    mesh.point_data["TCoords"] = np.column_stack((pd["u"], pd["v"]))
                    uv_key = "TCoords"

                if uv_key:
                    try:
                        mesh.point_data.set_active_texture_coordinates(uv_key)
                    except Exception:
                        pass

                    t0 = time.time()
                    texture_obj = self._create_transparent_texture_from_pil(img)
                    points = np.asarray(mesh.points).astype(np.float32)
                    mark("build_textured_mesh", t0)

                    emit_with_summary(
                        "mesh+texture",
                        mesh,
                        points,
                        np.array([]),
                        texture_obj,
                        len(points),
                        len(points),
                    )
                    return

                t0 = time.time()
                baked = self._bake_with_open3d_optimized(temp_model_path, img_rgb)
                mark("bake_vertex_color", t0)
                if baked is not None:
                    points = np.asarray(mesh.points).astype(np.float32)
                    emit_with_summary(
                        "mesh+baked_color",
                        mesh,
                        points,
                        baked,
                        None,
                        len(points),
                        len(points),
                    )
                    return

                print("[LOAD] 纹理存在但未找到可用UV，回退到点云读取流程", flush=True)

            t0 = time.time()
            pcd = safe_load_point_cloud(self.file_path, temp_dir)
            mark("read_point_cloud", t0)

            if pcd.is_empty():
                self.error.emit("鏂囦欢涓虹┖")
                return

            orig_count = len(pcd.points)
            final_count = orig_count
            random_count = orig_count

            random_target_points = int(getattr(self, "random_target_points", 0) or 0)
            if random_target_points > 0 and random_target_points < orig_count:
                random_target = min(orig_count, random_target_points)
                ratio = min(1.0, random_target / float(orig_count))
                target_mode = f"config({random_target})"
                t0 = time.time()
                pcd = pcd.random_down_sample(sampling_ratio=ratio)
                mark("random_downsample", t0)
                final_count = len(pcd.points)
                random_count = final_count
                print(
                    "[TIME][LOAD][downsample_random] "
                    f"target={target_mode}, random_ratio={ratio:.6f}, points={orig_count}->{final_count}",
                    flush=True,
                )
            else:
                print(
                    "[TIME][LOAD][downsample_random] "
                    f"target=config(disabled_or_not_needed), points={orig_count}->{final_count}",
                    flush=True,
                )

            t0 = time.time()
            points = np.asarray(pcd.points).astype(np.float32)
            colors = np.array([])
            if pcd.has_colors():
                colors = np.asarray(pcd.colors).astype(np.float32)
            mark("to_numpy", t0)

            total_s = time.time() - total_t0
            stage_str = ", ".join([f"{name}={sec:.2f}s" for name, sec in stage_times])
            print(
                f"[TIME][LOAD][point_cloud] {stage_str}, total={total_s:.2f}s, "
                f"points_total={orig_count}, points_random={random_count}",
                flush=True,
            )
            self.loaded.emit(None, points, colors, None, orig_count, final_count)

        except Exception as e:
            import traceback

            self.error.emit(f"{e}\n{traceback.format_exc()}")
        finally:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

    def _bake_with_open3d_optimized(self, ply_path, pil_img):
        try:
            import open3d as o3d

            img_arr = np.array(pil_img, dtype=np.float32) / 255.0
            h, w = img_arr.shape[:2]

            mesh_o3d = o3d.io.read_triangle_mesh(ply_path)
            if not mesh_o3d.has_triangle_uvs():
                return None

            triangles = np.asarray(mesh_o3d.triangles)
            tri_uvs = np.asarray(mesh_o3d.triangle_uvs)
            n_verts = len(mesh_o3d.vertices)

            face_vertex_indices = triangles.ravel()
            u = np.clip(tri_uvs[:, 0], 0.0, 1.0)
            v = np.clip(tri_uvs[:, 1], 0.0, 1.0)

            def sample_all(v_img):
                col = np.clip((u * (w - 1)).round().astype(int), 0, w - 1)
                row = np.clip((v_img * (h - 1)).round().astype(int), 0, h - 1)
                return img_arr[row, col]

            c_a = sample_all(1.0 - v)
            c_b = sample_all(v)
            chosen = c_a if np.var(c_a) >= np.var(c_b) else c_b

            bg_color = self._detect_bg_color(chosen)
            color_sum = np.zeros((n_verts, 3), dtype=np.float64)
            weight_sum = np.zeros(n_verts, dtype=np.float64)

            dist_to_bg = np.linalg.norm(chosen - bg_color, axis=1)
            fg_mask = dist_to_bg >= 0.18

            if fg_mask.sum() > 0:
                np.add.at(color_sum, face_vertex_indices[fg_mask], chosen[fg_mask])
                np.add.at(weight_sum, face_vertex_indices[fg_mask], 1.0)

            vertex_colors = np.where(
                weight_sum[:, np.newaxis] > 0,
                color_sum / np.maximum(weight_sum[:, np.newaxis], 1.0),
                np.array([0.5, 0.5, 0.5]),
            ).astype(np.float32)
            return vertex_colors

        except Exception as e:
            print(f"[LOAD] bake failed: {e}", flush=True)
            return None

    def _create_transparent_texture_from_pil(self, pil_img):
        try:
            import pyvista as pv

            img_arr = np.array(pil_img.convert("RGBA"))
            corners = [img_arr[0, 0, :3], img_arr[0, -1, :3], img_arr[-1, 0, :3], img_arr[-1, -1, :3]]
            bg_est = np.median(corners, axis=0)

            colors_rgb = img_arr[:, :, :3].astype(np.float32)
            dist = np.linalg.norm(colors_rgb - bg_est, axis=2)
            img_arr[dist < 50.0, 3] = 0
            return pv.Texture(img_arr)
        except Exception:
            import pyvista as pv

            return pv.Texture(pil_img)

    def _find_texture(self, original_path):
        base_dir = os.path.dirname(original_path)
        base_name = os.path.splitext(os.path.basename(original_path))[0]

        clean_base = base_name
        if clean_base.lower().endswith("texture"):
            clean_base = clean_base[:-7]

        for b_name in dict.fromkeys([base_name, clean_base]):
            if not b_name:
                continue
            for ext in [".png", ".jpg", ".jpeg"]:
                for suffix in ["", "0", "_texture", "Texture"]:
                    src = os.path.join(base_dir, b_name + suffix + ext)
                    if os.path.exists(src):
                        return src
        return ""

    def _detect_bg_color(self, colors):
        if len(colors) < 100:
            return np.array([0, 0, 0])
        return np.median(colors[:100], axis=0)
