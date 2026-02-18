from PySide6.QtWidgets import (QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, 
                               QPushButton, QLabel, QStackedWidget, QCheckBox, 
                               QButtonGroup, QHBoxLayout, QFrame, QTabWidget, 
                               QLineEdit, QFormLayout)
from PySide6.QtCore import Signal, Qt

# ================= 触摸屏专用样式 =================
STYLE_TOUCH_BTN_BIG = """
    QPushButton { 
        height: 80px; 
        font-size: 22px; 
        font-weight: bold;
        border: 2px solid #bbb; 
        border-radius: 10px; 
        margin: 4px;
        background-color: #f0f0f0;
    }
    QPushButton:checked { 
        background-color: #0275d8; 
        color: white; 
        border: 2px solid #0056b3; 
    }
    QPushButton:pressed {
        background-color: #aaa;
    }
"""

STYLE_TOUCH_BTN_NORMAL = """
    QPushButton { 
        height: 70px; 
        font-size: 20px; 
        border: 2px solid #ccc; 
        border-radius: 8px; 
        margin: 3px;
    }
    QPushButton:checked { 
        background-color: #5bc0de; 
        color: white; 
    }
"""

STYLE_TOUCH_TAB = """
    QTabBar::tab { 
        height: 60px; 
        width: 100px; 
        font-size: 18px; 
    }
    QTabWidget::pane { 
        border: 1px solid #ccc; 
    }
"""

# ==========================================
#  左侧：对象树 (分层管理)
# ==========================================
class ObjectListPanel(QWidget):
    item_deleted = Signal(QTreeWidgetItem) 
    item_clicked = Signal(QTreeWidgetItem) 

    def __init__(self):
        super().__init__()
        self.setMaximumWidth(320) # 稍微加宽一点适配触摸
        layout = QVBoxLayout()
        self.setLayout(layout)

        l = QLabel("图层对象 (Layers)")
        l.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(l)
        
        # 升级为 TreeWidget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        # 列表项增高
        self.tree.setStyleSheet("""
            QTreeWidget::item { height: 50px; font-size: 18px; padding-left: 5px; }
            QTreeWidget::item:selected { background-color: #0275d8; color: white; }
        """)
        self.tree.itemClicked.connect(self.on_item_click)
        layout.addWidget(self.tree)

        # 预设分组节点
        self.root_ref = QTreeWidgetItem(self.tree, ["📂 基准 (Reference)"])
        self.root_meas = QTreeWidgetItem(self.tree, ["📂 测量 (Measure)"])
        self.root_mark = QTreeWidgetItem(self.tree, ["📂 标注 (Markers)"])
        self.tree.expandAll()

        btn_del = QPushButton("删除选中项")
        # 红色大按钮
        btn_del.setStyleSheet("background-color: #d9534f; color: white; height: 60px; font-size: 20px; border-radius: 8px;")
        btn_del.clicked.connect(self.delete_selected)
        layout.addWidget(btn_del)

    def add_item(self, category, text, data=None):
        """通用添加方法"""
        parent = self.root_meas # 默认
        if category == 'ref': parent = self.root_ref
        elif category == 'marker': parent = self.root_mark
        
        item = QTreeWidgetItem(parent, [text])
        item.setData(0, Qt.UserRole, (category, data))
        
        self.tree.expandItem(parent)
        self.tree.setCurrentItem(item)

    def on_item_click(self, item, column):
        if item in [self.root_ref, self.root_meas, self.root_mark]: return
        self.item_clicked.emit(item)

    def delete_selected(self):
        item = self.tree.currentItem()
        if item and item not in [self.root_ref, self.root_meas, self.root_mark]:
            parent = item.parent()
            parent.removeChild(item)
            self.item_deleted.emit(item) 

    def clear_all(self):
        for root in [self.root_ref, self.root_meas, self.root_mark]:
            root.takeChildren()


# ==========================================
#  右侧：Action Panel (重构版 - 大按钮适配)
# ==========================================
class ActionPanel(QWidget):
    # --- Stage 1 信号 ---
    select_mode_changed = Signal(str); select_triggered = Signal(str); calibration_triggered = Signal(str)
    view_change_triggered = Signal(str) 
    
    # --- Stage 2 信号 ---
    global_mode_changed = Signal(str) 
    tool_selected = Signal(str, str)  
    action_triggered = Signal(str)    
    xray_toggled = Signal(bool)
    marker_label_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setMaximumWidth(360) # 加宽面板以容纳大按钮
        self.main_layout = QVBoxLayout(); self.setLayout(self.main_layout)
        self.stack_stages = QStackedWidget(); self.main_layout.addWidget(self.stack_stages)

        # Page 0: Stage 1
        self.page_stage1 = QWidget(); self._init_stage1(self.page_stage1)
        self.stack_stages.addWidget(self.page_stage1)

        # Page 1: Stage 2
        self.page_stage2 = QWidget(); self._init_stage2(self.page_stage2)
        self.stack_stages.addWidget(self.page_stage2)

    # ================= Stage 1 UI =================
    def _init_stage1(self, parent):
        l = QVBoxLayout(parent)
        
        self._add_view_buttons(l); l.addWidget(self._line())

        lbl = QLabel("👆 操作模式:"); lbl.setStyleSheet("font-size: 18px; font-weight: bold;")
        l.addWidget(lbl)
        
        self.btn_s1_view = QPushButton("🔄 旋转")
        self.btn_s1_pan  = QPushButton("✋ 平移")
        self.btn_s1_draw = QPushButton("✏️ 画圈") 
        self._setup_group(l, [self.btn_s1_view, self.btn_s1_pan, self.btn_s1_draw], self.select_mode_changed)
        l.addWidget(self._line())

        lbl2 = QLabel("📐 空间校准"); lbl2.setStyleSheet("font-size: 18px; font-weight: bold;")
        l.addWidget(lbl2)
        
        self.btn_calib_start = QPushButton("🏗️ 校准地面")
        self.btn_calib_start.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #5bc0de; color: white;")
        self.btn_calib_start.clicked.connect(lambda: self.calibration_triggered.emit("start_ground_calib"))
        l.addWidget(self.btn_calib_start)
        
        self.widget_calib_ops = QWidget()
        l_calib_ops = QVBoxLayout(self.widget_calib_ops)
        l_calib_ops.setContentsMargins(0,0,0,0)
        
        btn_confirm = QPushButton("✅ 确认地面")
        btn_confirm.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #5cb85c; color: white;")
        btn_confirm.clicked.connect(lambda: self.calibration_triggered.emit("confirm_ground"))
        
        btn_manual = QPushButton("🔨 手动校准 (3点)")
        btn_manual.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #f0ad4e; color: white;")
        btn_manual.clicked.connect(lambda: self.calibration_triggered.emit("manual_ground_3pt"))
        
        l_calib_ops.addWidget(btn_confirm)
        l_calib_ops.addWidget(btn_manual)
        l.addWidget(self.widget_calib_ops)
        self.widget_calib_ops.hide() 

        btn_north = QPushButton("🧭 设定指北")
        btn_north.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #5bc0de; color: white;")
        btn_north.clicked.connect(lambda: self.calibration_triggered.emit("set_north"))
        l.addWidget(btn_north)

        self.btn_confirm_north = QPushButton("✅ 确认方向")
        self.btn_confirm_north.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #5cb85c; color: white;")
        self.btn_confirm_north.clicked.connect(lambda: self.calibration_triggered.emit("confirm_north"))
        self.btn_confirm_north.hide()
        l.addWidget(self.btn_confirm_north)

        l.addWidget(self._line())

        self._add_btn(l, "删除红色区域", lambda: self.select_triggered.emit("delete_inner"), "#d9534f")
        self._add_btn(l, "反选", lambda: self.select_triggered.emit("invert"))
        l.addStretch()

    # ================= Stage 2 UI =================
    def _init_stage2(self, parent):
        l = QVBoxLayout(parent); l.setContentsMargins(0,0,0,0)
        
        self._init_stage2_top_bar(l)
        
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(STYLE_TOUCH_TAB)
        l.addWidget(self.tabs)
        
        self._init_tab_measure()
        self._init_tab_annotate()
        self._init_tab_edit()
        
    def _init_stage2_top_bar(self, layout):
        container = QWidget()
        hl = QHBoxLayout(container); hl.setContentsMargins(0,5,0,5)
        
        self.btn_g_view = QPushButton("🔄 旋转")
        self.btn_g_pan = QPushButton("✋ 平移")
        self.btn_g_draw = QPushButton("➕ 打点") 
        
        self.grp_global = QButtonGroup(self)
        
        for b, m in [(self.btn_g_view, 'view'), (self.btn_g_pan, 'pan'), (self.btn_g_draw, 'draw')]:
            b.setCheckable(True)
            b.setStyleSheet(STYLE_TOUCH_BTN_BIG) # 顶部栏用超大按钮
            self.grp_global.addButton(b)
            hl.addWidget(b)
            b.clicked.connect(lambda c=False, mode=m: self.global_mode_changed.emit(mode))
            
        self.btn_g_view.setChecked(True) 
        self.btn_g_draw.hide() 
        layout.addWidget(container)

    def _init_tab_measure(self):
        w = QWidget(); l = QVBoxLayout(w)
        
        # Row 1: 基准
        h1 = QHBoxLayout()
        b_ref_line = QPushButton("➖ 设基准线"); b_ref_pt = QPushButton("⚪ 设基准点")
        h1.addWidget(b_ref_line); h1.addWidget(b_ref_pt)
        l.addLayout(h1)
        
        # Row 2: 测量
        h2 = QHBoxLayout()
        b_poly = QPushButton("📐 多段测距"); b_perp = QPushButton("⬇ 垂距 (线)")
        h2.addWidget(b_poly); h2.addWidget(b_perp)
        l.addLayout(h2)
        
        b_direct = QPushButton("↗ 斜距 (点)")
        l.addWidget(b_direct)
        
        self.grp_tools = QButtonGroup(self)
        
        tools = [
            (b_ref_line, 'ref', 'line', "➕ 定点"),
            (b_ref_pt,   'ref', 'point', "➕ 定点"),
            (b_poly,     'measure', 'poly', "➕ 打点"),
            (b_perp,     'measure', 'perp', "➕ 选点"),
            (b_direct,   'measure', 'direct', "➕ 选点")
        ]
        
        for btn, tool, mode, draw_text in tools:
            btn.setCheckable(True)
            btn.setStyleSheet(STYLE_TOUCH_BTN_NORMAL)
            self.grp_tools.addButton(btn)
            btn.clicked.connect(lambda c=False, t=tool, m=mode, txt=draw_text: self.on_tool_btn_clicked(t, m, txt))

        l.addWidget(self._line())
        
        h_ops = QHBoxLayout()
        b_fin = QPushButton("✅ 结束段")
        b_fin.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #5cb85c; color: white;")
        b_fin.clicked.connect(lambda: self.action_triggered.emit('finish'))
        
        b_clr = QPushButton("🗑️ 清空")
        b_clr.setStyleSheet(STYLE_TOUCH_BTN_NORMAL)
        b_clr.clicked.connect(lambda: self.action_triggered.emit('clear'))
        
        h_ops.addWidget(b_fin); h_ops.addWidget(b_clr)
        l.addLayout(h_ops)
        
        chk = QCheckBox("透视模式 (X-Ray)")
        chk.setStyleSheet("QCheckBox{font-size: 20px; height: 40px; margin: 10px;}")
        chk.setChecked(True)
        chk.toggled.connect(self.xray_toggled.emit)
        l.addWidget(chk)
        
        l.addStretch()
        self.tabs.addTab(w, "测量")

    def _init_tab_annotate(self):
        w = QWidget(); l = QVBoxLayout(w)
        
        b_mark = QPushButton("🚩 放置标记"); 
        b_mark.setCheckable(True); 
        b_mark.setStyleSheet(STYLE_TOUCH_BTN_NORMAL)
        b_mark.clicked.connect(lambda: self.on_tool_btn_clicked('marker', 'add', "➕ 放置"))
        self.grp_tools.addButton(b_mark) 
        l.addWidget(b_mark)
        
        form = QFormLayout()
        self.txt_marker = QLineEdit("证据")
        self.txt_marker.setStyleSheet("height: 50px; font-size: 18px;")
        self.txt_marker.textChanged.connect(self.marker_label_changed.emit) 
        
        lbl = QLabel("标签前缀:"); lbl.setStyleSheet("font-size: 18px;")
        form.addRow(lbl, self.txt_marker)
        l.addLayout(form)
        
        l.addStretch()
        self.tabs.addTab(w, "标注")

    def _init_tab_edit(self):
        w = QWidget(); l = QVBoxLayout(w)
        
        b_sel = QPushButton("⭕ 画圈选择"); 
        b_sel.setCheckable(True); 
        b_sel.setStyleSheet(STYLE_TOUCH_BTN_NORMAL)
        b_sel.clicked.connect(lambda: self.on_tool_btn_clicked('edit', 'select', "✏️ 画圈"))
        self.grp_tools.addButton(b_sel)
        l.addWidget(b_sel)
        
        l.addWidget(self._line())
        
        self._add_btn(l, "✂️ 删除选中", lambda: self.action_triggered.emit('delete'), "#d9534f")
        self._add_btn(l, "↩️ 撤回", lambda: self.action_triggered.emit('undo'))
        
        l.addStretch()
        self.tabs.addTab(w, "编辑")

    # ================= 辅助方法 =================
    def switch_stage(self, stage_index):
        self.stack_stages.setCurrentIndex(stage_index)

    def on_tool_btn_clicked(self, tool, mode, draw_text):
        self.tool_selected.emit(tool, mode)
        self.btn_g_draw.setText(draw_text)
        self.btn_g_draw.show()
        self.btn_g_draw.click()

    def update_select_button_text(self, text):
        self.btn_s1_draw.setText(text)

    def _add_view_buttons(self, layout):
        h_views = QHBoxLayout()
        for t, m in [("⬆ 俯视", "top"), ("⬇ 正视", "front"), ("➡ 侧视", "side")]:
            b = QPushButton(t)
            b.setStyleSheet(STYLE_TOUCH_BTN_NORMAL)
            b.clicked.connect(lambda c=False, mode=m: self.view_change_triggered.emit(mode))
            h_views.addWidget(b)
        layout.addLayout(h_views)

    def _setup_group(self, layout, buttons, signal):
        bg = QButtonGroup(self)
        buttons[0].setChecked(True)
        modes = ["view", "pan", "draw"]
        for i, b in enumerate(buttons):
            b.setCheckable(True)
            b.setStyleSheet(STYLE_TOUCH_BTN_BIG) # Stage 1 顶部按钮也用大的
            layout.addWidget(b)
            bg.addButton(b)
            b.clicked.connect(lambda c, m=modes[i]: signal.emit(m))

    def _add_btn(self, layout, text, callback, color=None):
        btn = QPushButton(text)
        style = STYLE_TOUCH_BTN_NORMAL
        if color:
            style += f"background-color: {color}; color: white;"
        btn.setStyleSheet(style)
        btn.clicked.connect(callback)
        layout.addWidget(btn)
    
    def _btn_style_s2(self):
        # 兼容旧接口，虽然实际上用 STYLE_TOUCH_BTN_NORMAL 替代了
        return STYLE_TOUCH_BTN_NORMAL

    def _line(self):
        line = QFrame(); line.setFrameShape(QFrame.HLine); line.setFrameShadow(QFrame.Sunken); return line