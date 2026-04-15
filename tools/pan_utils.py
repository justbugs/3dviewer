import numpy as np

def perform_pan(plotter, start_pos, curr_pos):
    """
    执行精准平移：根据 VTK Display 坐标系和 focal depth 准确推算每个像素对应的世界坐标物理距离，
    解决高分辨率屏幕 (High DPI) 和透视投影下平移计算不准确、放大缩小后平移不跟手的问题。
    """
    if not start_pos: return curr_pos
    
    cam = plotter.camera
    ren = plotter.renderer
    pos = np.array(cam.GetPosition())
    foc = np.array(cam.GetFocalPoint())
    up  = np.array(cam.GetViewUp())

    # 计算相机正交右方向与上方向
    forward = foc - pos
    dist = np.linalg.norm(forward)
    if dist < 1e-9: return curr_pos
    forward /= dist
    right = np.cross(forward, up)
    norm_r = np.linalg.norm(right)
    if norm_r < 1e-9: return curr_pos
    right /= norm_r
    up_n = np.cross(right, forward) 
    
    # 获取焦平面在 Display 坐标系下的位置与深度
    ren.SetWorldPoint(foc[0], foc[1], foc[2], 1.0)
    ren.WorldToDisplay()
    disp = ren.GetDisplayPoint()
    
    # 利用反投影 (DisplayToWorld) 精确计算焦平面上1个像素对应的世界坐标距离 (world_per_pixel)
    # 这从底层绕过了所有高分屏 (DPI) 的 scale 换算逻辑
    ren.SetDisplayPoint(disp[0], disp[1], disp[2])
    ren.DisplayToWorld()
    w0_h = ren.GetWorldPoint()
    w0 = np.array(w0_h[:3]) / w0_h[3]
    
    ren.SetDisplayPoint(disp[0], disp[1] + 1.0, disp[2])
    ren.DisplayToWorld()
    w1_h = ren.GetWorldPoint()
    w1 = np.array(w1_h[:3]) / w1_h[3]
    
    wpp = np.linalg.norm(w1 - w0)
    
    # 计算平移像素差
    dx = curr_pos[0] - start_pos[0]
    dy = curr_pos[1] - start_pos[1]
    
    # VTK Display 坐标 (0,0) 在左下角。鼠标往上 (dy>0)，说明画面中物体要往上走，即摄像机要往下走 (-up_n)
    translation = -right * dx * wpp - up_n * dy * wpp
    
    cam.SetPosition(pos + translation)
    cam.SetFocalPoint(foc + translation)
    plotter.render()
    
    return curr_pos
