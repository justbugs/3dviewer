import os
import numpy as np


def safe_load_point_cloud(file_path, temp_dir=None):
    import open3d as o3d
    import shutil
    import tempfile
    import time

    if temp_dir is None:
        temp_dir = tempfile.mkdtemp()
        cleanup = True
    else:
        cleanup = False

    try:
        suffix = os.path.splitext(file_path)[1].lower()

        basename_lower = os.path.basename(file_path).lower()
        if suffix == ".txt" and ("points3d" in basename_lower or "point3d" in basename_lower):
            return parse_colmap_points3d(file_path)

        if suffix in [".las", ".laz"]:
            return parse_las_file(file_path)

        # Fast path: direct read original path (no copy).
        t0 = time.time()
        try:
            if suffix == ".ply":
                try:
                    tensor_pcd = o3d.t.io.read_point_cloud(file_path)
                    pcd = tensor_pcd.to_legacy()
                except Exception:
                    pcd = o3d.io.read_point_cloud(file_path)
            else:
                pcd = o3d.io.read_point_cloud(file_path)
            print(f"[TIME][IO][read_direct] {time.time()-t0:.2f}s", flush=True)
            return pcd
        except Exception:
            # Fallback: copy to ASCII-safe temp path for compatibility.
            t_copy = time.time()
            safe_read_path = os.path.join(temp_dir, "temp_read" + suffix)
            shutil.copyfile(file_path, safe_read_path)
            copy_s = time.time() - t_copy

            t_read = time.time()
            if suffix == ".ply":
                try:
                    tensor_pcd = o3d.t.io.read_point_cloud(safe_read_path)
                    pcd = tensor_pcd.to_legacy()
                except Exception:
                    pcd = o3d.io.read_point_cloud(safe_read_path)
            else:
                pcd = o3d.io.read_point_cloud(safe_read_path)
            print(f"[TIME][IO][read_fallback] copy={copy_s:.2f}s, read={time.time()-t_read:.2f}s", flush=True)
            return pcd
    finally:
        if cleanup:
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass


def parse_las_file(filepath):
    import laspy
    import open3d as o3d
    import time

    t0 = time.time()
    try:
        t_read = time.time()
        las = laspy.read(filepath)
        read_s = time.time() - t_read

        t_xyz = time.time()
        raw_xyz = np.stack([las.X, las.Y, las.Z], axis=1).astype(np.float64)
        points = raw_xyz * las.header.scales + las.header.offsets
        xyz_s = time.time() - t_xyz

        t_o3d = time.time()
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(points)
        o3d_s = time.time() - t_o3d

        color_s = 0.0
        if hasattr(las, "red"):
            t_color = time.time()
            colors = np.stack([las.red, las.green, las.blue], axis=1).astype(np.float32) / 65535.0
            pcd.colors = o3d.utility.Vector3dVector(colors)
            color_s = time.time() - t_color

        total_s = time.time() - t0
        print(
            f"[TIME][LAS] read={read_s:.2f}s, xyz={xyz_s:.2f}s, to_o3d={o3d_s:.2f}s, "
            f"color={color_s:.2f}s, total={total_s:.2f}s, points={len(points)}",
            flush=True,
        )
        return pcd

    except Exception as e:
        import traceback

        print(f"[ERROR] LAS parse failed: {e}\n{traceback.format_exc()}", flush=True)
        return o3d.geometry.PointCloud()


def parse_colmap_points3d(filepath):
    import open3d as o3d

    points = []
    colors = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 7:
                points.append([float(parts[1]), float(parts[2]), float(parts[3])])
                colors.append([float(parts[4]) / 255.0, float(parts[5]) / 255.0, float(parts[6]) / 255.0])

    pcd = o3d.geometry.PointCloud()
    if points:
        pcd.points = o3d.utility.Vector3dVector(np.array(points, dtype=np.float64))
        pcd.colors = o3d.utility.Vector3dVector(np.array(colors, dtype=np.float64))
    return pcd


def save_point_cloud(dataset, out_path):
    import open3d as o3d
    import pyvista as pv
    import shutil
    import tempfile

    temp_dir = tempfile.mkdtemp()
    try:
        suffix = os.path.splitext(out_path)[1].lower()
        safe_write_path = os.path.join(temp_dir, "temp_write" + suffix)

        if isinstance(dataset, pv.PolyData):
            dataset.save(safe_write_path)
        elif isinstance(dataset, pv.DataSet):
            poly = dataset.extract_surface()
            poly.save(safe_write_path)
        elif isinstance(dataset, o3d.geometry.PointCloud):
            o3d.io.write_point_cloud(safe_write_path, dataset)
        else:
            raise ValueError(f"Unknown point cloud dataset type: {type(dataset)}")

        shutil.copyfile(safe_write_path, out_path)
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass
