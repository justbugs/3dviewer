#PCD_PATH = "/home/cat/桌面/Scan/build-Scan-unknown-Release/data/2026-04-13 08-29 /粗略点云/粗略点云.pcd"\
import sys
import os
import shutil
import tempfile
import numpy as np
import open3d as o3d
import pyvista as pv
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout
from pyvistaqt import QtInteractor

PCD_PATH = r"E:\3dgs\2026-03-22_15-50-13\sparse\0\粗略点云.pcd"
TARGET_POINTS = 200000

def safe_read_point_cloud(path):
    try:
        return o3d.io.read_point_cloud(path)
    except Exception:
        tmpdir = tempfile.mkdtemp()
        try:
            suffix = os.path.splitext(path)[1].lower() or ".pcd"
            safe_path = os.path.join(tmpdir, "temp_read" + suffix)
            shutil.copyfile(path, safe_path)
            return o3d.io.read_point_cloud(safe_path)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Minimal PyVistaQt Test")
        self.resize(1200, 800)

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plotter = QtInteractor(self)
        layout.addWidget(self.plotter.interactor)

        self.plotter.set_background("white")
        self.plotter.add_axes()
        self.load_and_show()

    def load_and_show(self):
        pcd = safe_read_point_cloud(PCD_PATH)
        pts = np.asarray(pcd.points)
        print("raw points:", len(pts))

        if len(pts) > TARGET_POINTS:
            pcd = pcd.random_down_sample(TARGET_POINTS / float(len(pts)))

        pts = np.asarray(pcd.points)
        print("downsampled:", len(pts))

        cloud = pv.PolyData(pts)
        if pcd.has_colors():
            colors = np.asarray(pcd.colors).astype(np.float32)
            cloud["RGB"] = colors
            self.plotter.add_mesh(
                cloud, scalars="RGB", rgb=True,
                point_size=4, render_points_as_spheres=True
            )
        else:
            self.plotter.add_mesh(
                cloud, color="red",
                point_size=4, render_points_as_spheres=True
            )

        self.plotter.reset_camera()
        self.plotter.render()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())