import os
import shutil
import tempfile
import numpy as np
import open3d as o3d
import pyvista as pv
import vtk
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
)
from PySide6.QtCore import Qt
from pyvistaqt import QtInteractor

# Edit this path on target machine
PCD_PATH = r"/home/cat/桌面/Scan/build-Scan-unknown-Release/data/2026-04-13 08-29 /粗略点云/粗略点云.pcd"
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
        self.setWindowTitle("show_test Step1+2+3")
        self.resize(1400, 900)

        root = QWidget(self)
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(4, 4, 4, 4)

        # Top controls
        top = QHBoxLayout()
        self.info = QLabel("ready")
        self.btn_step1 = QPushButton("Run Step1")
        self.btn_step2 = QPushButton("Run Step2")
        self.btn_step3 = QPushButton("Apply Step3 UI")
        self.btn_view = QPushButton("View")
        self.btn_pan = QPushButton("Pan")
        self.btn_draw = QPushButton("Draw")
        self.btn_step1.clicked.connect(self.run_step1)
        self.btn_step2.clicked.connect(self.run_step2)
        self.btn_step3.clicked.connect(self.run_step3)
        self.btn_view.clicked.connect(lambda: self.set_interaction_mode("view"))
        self.btn_pan.clicked.connect(lambda: self.set_interaction_mode("pan"))
        self.btn_draw.clicked.connect(lambda: self.set_interaction_mode("draw"))
        for b in [self.btn_step1, self.btn_step2, self.btn_step3, self.btn_view, self.btn_pan, self.btn_draw]:
            top.addWidget(b)
        top.addWidget(self.info, 1)
        main.addLayout(top)

        # Splitter to mimic main app layout
        self.splitter = QSplitter(Qt.Horizontal)
        self.left_panel = QLabel("Left panel\n(Object list placeholder)")
        self.left_panel.setAlignment(Qt.AlignCenter)
        self.right_panel = QLabel("Right panel\n(Action panel placeholder)")
        self.right_panel.setAlignment(Qt.AlignCenter)

        self.plotter = QtInteractor(self)

        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.plotter)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([280, 1000, 380])
        main.addWidget(self.splitter)

        self.points = None
        self.colors = None

        self._load_data()
        self.run_step1()

    def _load_data(self):
        pcd = safe_read_point_cloud(PCD_PATH)
        pts = np.asarray(pcd.points)
        if len(pts) > TARGET_POINTS:
            pcd = pcd.random_down_sample(TARGET_POINTS / float(len(pts)))
        self.points = np.asarray(pcd.points).astype(np.float32)
        self.colors = np.asarray(pcd.colors).astype(np.float32) if pcd.has_colors() else None
        self.info.setText(f"loaded: points={len(self.points)}, has_colors={self.colors is not None}")

    def _draw_cloud_mainstyle(self):
        self.plotter.clear()
        self.plotter.set_background("black")
        self.plotter.add_axes(xlabel="E", ylabel="N", zlabel="Z", color="white", viewport=(0.8, 0.0, 1.0, 0.2))

        cloud = pv.PolyData(self.points)
        if self.colors is not None and len(self.colors) == len(self.points):
            cloud["RGB"] = self.colors
            self.plotter.add_mesh(
                cloud,
                scalars="RGB",
                rgb=True,
                point_size=2,
                lighting=False,
                render_points_as_spheres=False,
            )
        else:
            self.plotter.add_mesh(
                cloud,
                color="cyan",
                point_size=2,
                lighting=False,
                render_points_as_spheres=False,
            )

    def run_step1(self):
        # Step1: main program-like render params
        self._draw_cloud_mainstyle()
        self.plotter.reset_camera()
        self.plotter.render()
        self.info.setText("Step1 done: render params")

    def run_step2(self):
        # Step2: main program-like camera flow
        if self.points is None or len(self.points) == 0:
            return
        self._draw_cloud_mainstyle()

        b = np.array([
            float(self.points[:, 0].min()), float(self.points[:, 0].max()),
            float(self.points[:, 1].min()), float(self.points[:, 1].max()),
            float(self.points[:, 2].min()), float(self.points[:, 2].max()),
        ], dtype=np.float64)

        x_len = b[1] - b[0]
        y_len = b[3] - b[2]
        z_len = b[5] - b[4]
        diag = float(np.linalg.norm([x_len, y_len, z_len]))
        if diag <= 1e-6:
            self.info.setText("Step2 skipped: diag too small")
            return

        cx = (b[0] + b[1]) * 0.5
        cy = (b[2] + b[3]) * 0.5
        cz = (b[4] + b[5]) * 0.5

        view_dir = np.array([1.0, -1.0, 0.7], dtype=np.float64)
        view_dir /= np.linalg.norm(view_dir)
        dist = max(diag * 1.35, max(x_len, y_len, z_len) * 1.8)

        cam = self.plotter.camera
        cam.SetFocalPoint(cx, cy, cz)
        cam.SetPosition(*(np.array([cx, cy, cz], dtype=np.float64) + view_dir * dist))
        cam.SetViewUp(0.0, 0.0, 1.0)
        cam.SetParallelProjection(0)
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.render()
        self.info.setText("Step2 done: camera flow")

    def run_step3(self):
        # Step3: maximize + splitter + interactor mode switching
        self.showMaximized()
        self.run_step2()
        self.set_interaction_mode("view")
        self.info.setText("Step3 done: UI/layout+mode state")

    def set_interaction_mode(self, mode):
        iren = self.plotter.interactor
        cam = self.plotter.camera
        pos = cam.GetPosition()
        focal = cam.GetFocalPoint()
        view_up = cam.GetViewUp()

        if mode == "view":
            style = vtk.vtkInteractorStyleTrackballCamera()
            iren.SetInteractorStyle(style)
        elif mode == "pan":
            style = vtk.vtkInteractorStyleUser()
            iren.SetInteractorStyle(style)
        elif mode == "draw":
            style = vtk.vtkInteractorStyleTrackballCamera()
            iren.SetInteractorStyle(style)
            try:
                iren.RemoveObservers("LeftButtonPressEvent")
                iren.RemoveObservers("LeftButtonReleaseEvent")
            except Exception:
                pass

        cam.SetPosition(pos)
        cam.SetFocalPoint(focal)
        cam.SetViewUp(view_up)
        self.plotter.render()


if __name__ == "__main__":
    app = QApplication([])
    w = MainWindow()
    w.show()
    app.exec()
