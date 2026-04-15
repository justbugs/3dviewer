from PySide6.QtWidgets import (QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, 
                               QPushButton, QLabel, QStackedWidget, QCheckBox, 
                               QButtonGroup, QHBoxLayout, QFrame, QTabWidget, 
                               QLineEdit, QFormLayout, QSlider, QScrollArea, QGridLayout)
from PySide6.QtCore import Signal, Qt
import os
import sys
import traceback

# ================= 瑙︽懜灞忎笓鐢ㄦ牱寮?=================
STYLE_TOUCH_BTN_BIG = """
    QPushButton { 
        height: 80px; 
        font-size: 22px; 
        font-weight: bold;
        border: 2px solid #bbb; 
        border-radius: 10px; 
        margin: 4px;
        background-color: #f0f0f0;
        color: black;
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
        color: black;
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
#  宸︿晶锛氬璞℃爲 (鍒嗗眰绠＄悊)
# ==========================================
class ObjectListPanel(QWidget):
    item_deleted = Signal(QTreeWidgetItem) 
    item_clicked = Signal(QTreeWidgetItem) 
    items_deleted_batch = Signal(object)  # list[(category, data)]

    def __init__(self):
        super().__init__()
        self.setMaximumWidth(320)
        self._last_checked_item = None  # for Shift+click range selection
        layout = QVBoxLayout()
        self.setLayout(layout)

        h_header = QHBoxLayout()
        l = QLabel("图层对象")
        l.setStyleSheet("font-size: 18px; font-weight: bold;")
        h_header.addWidget(l, 1)

        self.btn_selall = QPushButton("☑ 全选")
        self.btn_selall.setCheckable(True)
        self.btn_selall.setStyleSheet(
            "QPushButton{font-size:14px;height:36px;padding:0 8px;border-radius:6px;"
            "border:1px solid #aaa;background:#e8e8e8;color:#333;}"
            "QPushButton:checked{background:#0275d8;color:white;border-color:#0275d8;}")
        self.btn_selall.clicked.connect(self._on_select_all)
        h_header.addWidget(self.btn_selall)
        layout.addLayout(h_header)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet("""
            QTreeWidget::item { height: 32px; font-size: 16px; padding-left: 2px; }
            QTreeWidget::item:selected { background-color: #0275d8; color: white; }
        """)
        self.tree.itemClicked.connect(self.on_item_click)
        layout.addWidget(self.tree, 1)  # 1 means tree takes all available middle space

        self.root_ref = QTreeWidgetItem(self.tree, [""])
        self.root_meas = QTreeWidgetItem(self.tree, [""])
        self.root_mark = QTreeWidgetItem(self.tree, [""])
        self.tree.expandAll()

        # Per-group header widgets
        self._setup_group_header(self.root_ref, "📂 基准", self.root_ref)
        self._setup_group_header(self.root_meas, "📂 测量", self.root_meas)
        self._setup_group_header(self.root_mark, "📂 标注", self.root_mark)

        # 閿佸畾鍒板簳閮ㄧ殑鍒犻櫎鎸夐挳
        btn_del = QPushButton("🗑 删除选中项")
        btn_del.setStyleSheet("background-color: #d9534f; color: white; height: 45px; font-size: 18px; border-radius: 6px; font-weight: bold;")
        btn_del.clicked.connect(self.delete_selected)
        layout.addWidget(btn_del)

    def _setup_group_header(self, root_item, label_text, root_ref):
        """Add a label + 鍏ㄩ€?mini-button widget to a group item header."""
        w = QWidget()
        h = QHBoxLayout(w); h.setContentsMargins(4, 2, 4, 2)
        lbl = QLabel(label_text); lbl.setStyleSheet("font-size: 17px; font-weight: bold;")
        h.addWidget(lbl, 1)
        btn = QPushButton("全选"); btn.setFixedWidth(60)
        btn.setStyleSheet("font-size: 13px; height: 30px; border-radius: 5px; border: 1px solid #aaa; background: #e0e0e0;")
        grp_ref = root_ref  # capture
        def toggle_group(checked, r=grp_ref, b=btn):
            state = Qt.Checked if checked else Qt.Unchecked
            for i in range(r.childCount()):
                r.child(i).setCheckState(0, state)
            b.setChecked(checked)
            b.setText("全不选" if checked else "全选")
        btn.setCheckable(True)
        btn.clicked.connect(toggle_group)
        h.addWidget(btn)
        self.tree.setItemWidget(root_item, 0, w)

    def _make_checkable(self, item):
        item.setCheckState(0, Qt.Unchecked)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)

    def add_item(self, category, text, data=None, emit_click=True):
        parent = self.root_meas
        if category == 'ref': parent = self.root_ref
        elif category == 'marker': parent = self.root_mark
        item = QTreeWidgetItem(parent, [text])
        item.setData(0, Qt.UserRole, (category, data))
        self._make_checkable(item)
        self.tree.expandItem(parent)
        self.tree.setCurrentItem(item)
        if emit_click:
            self.item_clicked.emit(item)

    def on_item_click(self, item, column):
        if item in [self.root_ref, self.root_meas, self.root_mark]: return
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt as _Qt
        modifiers = QApplication.keyboardModifiers()
        if (modifiers & _Qt.ShiftModifier) and self._last_checked_item:
            self._range_check(self._last_checked_item, item)
        else:
            self._last_checked_item = item
            self.item_clicked.emit(item)

    def _all_leaf_items(self):
        for root in [self.root_ref, self.root_meas, self.root_mark]:
            for i in range(root.childCount()):
                yield root.child(i)

    def _range_check(self, item_a, item_b):
        all_items = list(self._all_leaf_items())
        try:
            ia, ib = all_items.index(item_a), all_items.index(item_b)
        except ValueError:
            return
        if ia > ib: ia, ib = ib, ia
        for i in range(ia, ib + 1):
            all_items[i].setCheckState(0, Qt.Checked)
        self._last_checked_item = item_b

    def _on_select_all(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for item in self._all_leaf_items():
            item.setCheckState(0, state)
        self.btn_selall.setText("☐ 全不选" if checked else "☑ 全选")

    def get_all_checked_items(self):
        """Return list of (category, data) for all checked leaf items."""
        result = []
        for item in self._all_leaf_items():
            if item.checkState(0) == Qt.Checked:
                d = item.data(0, Qt.UserRole)
                if d: result.append(d)
        return result

    def get_checked_measure_data(self):
        return [d for cat, d in self.get_all_checked_items() if cat == 'measure']

    def delete_selected(self):
        checked = [item for item in self._all_leaf_items() if item.checkState(0) == Qt.Checked]
        if checked:
            payload = []
            for item in checked:
                d = item.data(0, Qt.UserRole)
                if d:
                    payload.append(d)
                item.parent().removeChild(item)
            if payload:
                self.items_deleted_batch.emit(payload)
        else:
            item = self.tree.currentItem()
            if item and item not in [self.root_ref, self.root_meas, self.root_mark]:
                item.parent().removeChild(item)
                self.item_deleted.emit(item)

    def clear_all(self):
        for root in [self.root_ref, self.root_meas, self.root_mark]:
            root.takeChildren()


# ==========================================
#  鍙充晶锛欰ction Panel (閲嶆瀯鐗?- 澶ф寜閽€傞厤)
# ==========================================
class ActionPanel(QWidget):
    # --- Stage 1 淇″彿 ---
    select_mode_changed = Signal(str); select_triggered = Signal(str); calibration_triggered = Signal(str)
    view_change_triggered = Signal(str) 
    
    # --- Stage 2 淇″彿 ---
    global_mode_changed = Signal(str) 
    tool_selected = Signal(str, str)  
    action_triggered = Signal(str)    
    xray_toggled = Signal(bool)
    marker_label_changed = Signal(str)
    measure_style_changed = Signal(str, str, str)  # key, value, extra
    style_edit_lock_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setMaximumWidth(360) # 鍔犲闈㈡澘浠ュ绾冲ぇ鎸夐挳
        self.main_layout = QVBoxLayout(); self.setLayout(self.main_layout)
        self.stack_stages = QStackedWidget(); self.main_layout.addWidget(self.stack_stages)

        # Page 0: Stage 1
        self.page_stage1 = QWidget(); self._init_stage1(self.page_stage1)
        self.stack_stages.addWidget(self.page_stage1)

        # Page 1: Stage 2
        self.page_stage2 = QWidget(); self._init_stage2(self.page_stage2)
        self.stack_stages.addWidget(self.page_stage2)

        # Page 2: Stage 3 (Output Phase)
        self.page_stage3 = QWidget(); self._init_stage3(self.page_stage3)
        self.stack_stages.addWidget(self.page_stage3)

    # ================= Stage 1 UI =================
    def _init_stage1(self, parent):
        l = QVBoxLayout(parent)
        
        self.btn_s1_view = QPushButton("🔄 旋转")
        self.btn_s1_pan  = QPushButton("✋ 平移")
        self.btn_s1_draw = QPushButton("✏️ 区域选择") 
        
        self.btn_s1_view.setCheckable(True)
        self.btn_s1_pan.setCheckable(True)
        self.btn_s1_draw.setCheckable(True)
        self.grp_stage1_mode = QButtonGroup(self)
        self.grp_stage1_mode.addButton(self.btn_s1_view)
        self.grp_stage1_mode.addButton(self.btn_s1_pan)
        self.grp_stage1_mode.addButton(self.btn_s1_draw)
        self.btn_s1_view.setChecked(True)
        
        self.btn_s1_view.clicked.connect(lambda: self.select_mode_changed.emit('view'))
        self.btn_s1_pan.clicked.connect(lambda: self.select_mode_changed.emit('pan'))
        self.btn_s1_draw.clicked.connect(lambda: self.select_mode_changed.emit('draw'))
        
        for b in [self.btn_s1_view, self.btn_s1_pan, self.btn_s1_draw]: 
            b.setStyleSheet(STYLE_TOUCH_BTN_BIG)
            l.addWidget(b)
            
        l.addWidget(self._line())

        lbl2 = QLabel("📐 空间校准"); lbl2.setStyleSheet("font-size: 18px; font-weight: bold;")
        l.addWidget(lbl2)
        
        self.btn_calib_start = QPushButton("🏗️ 校准地面")
        self.btn_calib_start.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #5bc0de; color: black;")
        self.btn_calib_start.clicked.connect(lambda: self.calibration_triggered.emit("start_ground_calib"))
        l.addWidget(self.btn_calib_start)
        
        self.widget_calib_ops = QWidget()
        l_calib_ops = QVBoxLayout(self.widget_calib_ops)
        l_calib_ops.setContentsMargins(0,0,0,0)
        
        btn_confirm = QPushButton("✅ 确认地面")
        btn_confirm.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #5cb85c; color: white;")
        btn_confirm.clicked.connect(lambda: self.calibration_triggered.emit("confirm_ground"))
        
        btn_manual = QPushButton("🔧 手动校准 (3点)")
        btn_manual.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #f0ad4e; color: white;")
        btn_manual.clicked.connect(lambda: self.calibration_triggered.emit("manual_ground_3pt"))
        
        btn_cancel = QPushButton("❌ 取消校准")
        btn_cancel.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #d9534f; color: white;")
        btn_cancel.clicked.connect(lambda: self.calibration_triggered.emit("cancel_ground"))
        
        l_calib_ops.addWidget(btn_manual)
        l_calib_ops.addWidget(btn_confirm)
        l_calib_ops.addWidget(btn_cancel)
        l.addWidget(self.widget_calib_ops)
        self.widget_calib_ops.hide() 

        self.btn_set_north = QPushButton("🧭 设定指北")
        self.btn_set_north.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #5bc0de; color: black;")
        self.btn_set_north.clicked.connect(lambda: self.calibration_triggered.emit("set_north"))
        l.addWidget(self.btn_set_north)

        self.btn_confirm_north = QPushButton("✅ 确认方向")
        self.btn_confirm_north.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #5cb85c; color: white;")
        self.btn_confirm_north.clicked.connect(lambda: self.calibration_triggered.emit("confirm_north"))
        self.btn_confirm_north.hide()
        l.addWidget(self.btn_confirm_north)

        self.btn_cancel_north = QPushButton("❌ 取消方向")
        self.btn_cancel_north.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #d9534f; color: white;")
        self.btn_cancel_north.clicked.connect(lambda: self.calibration_triggered.emit("cancel_north"))
        self.btn_cancel_north.hide()
        l.addWidget(self.btn_cancel_north)

        l.addWidget(self._line())

        self.btn_s1_delete_inner = self._add_btn(l, "删除红色区域", lambda: self.select_triggered.emit("delete_inner"), "#d9534f")
        self.btn_s1_invert = self._add_btn(l, "↔️ 反选", lambda: self.select_triggered.emit("invert"))
        self.btn_s1_undo = self._add_btn(l, "↩️ 撤回", lambda: self.action_triggered.emit('undo'))
        l.addStretch()

    # ================= Stage 2 UI =================
    def _init_stage2(self, parent):
        outer = QVBoxLayout(parent); outer.setContentsMargins(0, 0, 0, 0)
        
        self._init_stage2_top_bar(outer)
        
        # 涓棿鍐呭鍖轰娇鐢ㄦ粴鍔ㄦ潯鍖呰锛岄槻姝㈠睍寮€鈥滆緭鍑衡€濇椂鎾戝ぇ涓荤獥鍙?
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        l = QVBoxLayout(content); l.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(STYLE_TOUCH_TAB)
        l.addWidget(self.tabs)
        
        self._init_tab_measure()
        self._init_tab_annotate()
        self._init_tab_edit()
        
        self.tabs.currentChanged.connect(self._on_tab_changed)
        
        # 灏嗘牱寮忔帶鍒跺拰杈撳嚭鎸夐挳涔熸斁鍏ユ粴鍔ㄥ尯
        l.addWidget(self.widget_style_controls)
        l.addWidget(self._line())
        
        self.btn_output = QPushButton("➡️ 输出")
        self.btn_output.setCheckable(True)
        self.btn_output.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #0275d8; color: white; height: 50px; font-weight: bold;")
        self.btn_output.clicked.connect(self._on_toggle_output)
        l.addWidget(self.btn_output)
        
        self.widget_output_menu = QWidget()
        om = QVBoxLayout(self.widget_output_menu)
        om.setContentsMargins(0, 0, 0, 0)
        
        def _out_btn(text, action, color="#1a6fac"):
            b = QPushButton(text)
            b.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + f"background-color: {color}; color: white; margin-left: 10px; height: 45px;")
            b.clicked.connect(lambda: self.action_triggered.emit(action))
            return b
        
        self.btn_out_scene = _out_btn("📳 生成实景图", 'go_output')
        self.btn_out_mesh = _out_btn("🧱 生成Mesh模型", 'gen_mesh')
        self.btn_out_primitive = _out_btn("📷 生成图元图", 'gen_primitive')
        om.addWidget(self.btn_out_scene)
        om.addWidget(self.btn_out_mesh)
        om.addWidget(self.btn_out_primitive)
        
        self.widget_output_menu.hide()
        l.addWidget(self.widget_output_menu)
        l.addStretch(1)

    def _init_stage2_top_bar(self, layout):
        container = QWidget()
        hl = QHBoxLayout(container); hl.setContentsMargins(0,5,0,5)
        
        self.btn_g_view = QPushButton("🔄 旋转")
        self.btn_g_pan  = QPushButton("✋ 平移")
        self.btn_g_sel  = QPushButton("✏️ 区域选择")  # permanent circle-select
        self.btn_g_draw = QPushButton("➡️ 打点")  # dynamic: shown when a draw tool is active
        
        self.grp_global = QButtonGroup(self)
        
        for b, m in [(self.btn_g_view, 'view'), (self.btn_g_pan, 'pan'), (self.btn_g_sel, 'draw'), (self.btn_g_draw, 'draw')]:
            b.setCheckable(True)
            b.setStyleSheet(STYLE_TOUCH_BTN_BIG)
            self.grp_global.addButton(b)
            hl.addWidget(b)
            b.clicked.connect(lambda c=False, mode=m: self.global_mode_changed.emit(mode))
            
        # 鍖哄煙閫夋嫨 also activates the edit/select tool
        self.btn_g_sel.clicked.connect(
            lambda: self.tool_selected.emit('edit', 'select'))
        
        self.btn_g_view.setChecked(True)
        self.btn_g_draw.hide()
        self.btn_g_sel.hide()   # only visible when 缂栬緫 tab is active
        layout.addWidget(container)

    def _init_tab_measure(self):
        w = QWidget(); l = QVBoxLayout(w)
        
        # Row 1: 鍩哄噯绾?+ 鍨傝窛(绾?
        h1 = QHBoxLayout()
        b_ref_line = QPushButton("➡️ 设基准线"); b_perp = QPushButton("📏 垂距(线)")
        h1.addWidget(b_ref_line); h1.addWidget(b_perp)
        l.addLayout(h1)
        
        # Row 2: 鍩哄噯鐐?+ 鏂滆窛(鐐?
        h2 = QHBoxLayout()
        b_ref_pt = QPushButton("📍 设基准点"); b_direct = QPushButton("↗️ 斜距(点)")
        h2.addWidget(b_ref_pt); h2.addWidget(b_direct)
        l.addLayout(h2)

        h3 = QHBoxLayout()
        b_two_point = QPushButton("↔️ 两点距离")
        h3.addWidget(b_two_point)
        l.addLayout(h3)
        
        # 澶氭娴嬭窛宸叉牴鎹渶姹傝绉婚櫎
        # b_poly = QPushButton("馃搻 澶氭娴嬭窛")
        # b_poly.setCheckable(True)
        # b_poly.setStyleSheet(STYLE_TOUCH_BTN_NORMAL)
        # self._btn_poly = b_poly  # keep ref for state toggle
        
        self.grp_tools = QButtonGroup(self)
        
        tools = [
            (b_ref_line, 'ref', 'line', "➡️ 定点"),
            (b_ref_pt,   'ref', 'point', "➡️ 定点"),
            (b_perp,     'measure', 'perp', "➡️ 选点"),
            (b_direct,   'measure', 'direct', "➡️ 选点"),
            (b_two_point,'measure', 'two_point', "➡️ 选点")
        ]
        
        for btn, tool, mode, draw_text in tools:
            btn.setCheckable(True)
            btn.setStyleSheet(STYLE_TOUCH_BTN_NORMAL)
            self.grp_tools.addButton(btn)
            btn.clicked.connect(lambda c=False, t=tool, m=mode, txt=draw_text: self.on_tool_btn_clicked(t, m, txt))
        
        # self.grp_tools.addButton(b_poly)
        # def _on_poly_clicked(checked):
        #     if checked:
        #         b_poly.setText("鉁?缁撴潫澶氭娴嬮噺")
        #         b_poly.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #5cb85c; color: white;")
        #         self.on_tool_btn_clicked('measure', 'poly', "鉃?鎵撶偣")
        #     else:
        #         b_poly.setText("馃搻 澶氭娴嬭窛")
        #         b_poly.setStyleSheet(STYLE_TOUCH_BTN_NORMAL)
        #         self.action_triggered.emit('finish')
        # b_poly.clicked.connect(_on_poly_clicked)
        # l.addWidget(b_poly)

        l.addWidget(self._line())
        
        # --- 鏍峰紡璋冩暣鍖哄煙锛堝皢鍦?_init_stage2 涓坊鍔犲埌 stage2 layout锛?--
        self.widget_style_controls = QWidget()
        sl = QVBoxLayout(self.widget_style_controls)
        sl.setContentsMargins(0, 0, 0, 0)
        
        # 瀛楀彿璋冩暣瀛愮粍浠?
        self.widget_style_font = QWidget()
        sl_font = QVBoxLayout(self.widget_style_font)
        sl_font.setContentsMargins(0, 0, 0, 0)
        lbl_font = QLabel("字号调整"); lbl_font.setStyleSheet("font-size: 16px; margin-top: 4px;")
        sl_font.addWidget(lbl_font)
        h_font = QHBoxLayout()
        lbl_fm = QLabel("A-"); lbl_fm.setStyleSheet("font-size: 20px;")
        self.sld_font = QSlider(Qt.Horizontal)
        self.sld_font.setMinimum(8); self.sld_font.setMaximum(40); self.sld_font.setValue(20)
        self.sld_font.setTracking(True)
        self.sld_font.setStyleSheet("height: 40px;")
        lbl_fp = QLabel("A+"); lbl_fp.setStyleSheet("font-size: 20px;")
        h_font.addWidget(lbl_fm); h_font.addWidget(self.sld_font, 1); h_font.addWidget(lbl_fp)
        sl_font.addLayout(h_font)
        self.sld_font.sliderPressed.connect(lambda: self.style_edit_lock_changed.emit(True))
        self.sld_font.valueChanged.connect(lambda v: self.measure_style_changed.emit('font', str(v), 'drag'))
        self.sld_font.sliderReleased.connect(lambda: self.measure_style_changed.emit('font', str(self.sld_font.value()), 'final'))
        self.sld_font.sliderReleased.connect(lambda: self.style_edit_lock_changed.emit(False))
        sl.addWidget(self.widget_style_font)
        
        # 棰滆壊閫夋嫨涓庣嚎瀹斤紙鎭㈠鑸掗€傚ぇ灏哄锛?
        self.widget_style_color = QWidget()
        sl_col = QVBoxLayout(self.widget_style_color)
        sl_col.setContentsMargins(0, 0, 0, 0)
        
        # 绾垮
        h_lw = QHBoxLayout()
        lbl_lw = QLabel("线宽调整"); lbl_lw.setStyleSheet("font-size: 16px;")
        lbl_lwm = QLabel("细"); lbl_lwm.setStyleSheet("font-size: 18px;")
        self.sld_lw = QSlider(Qt.Horizontal)
        self.sld_lw.setMinimum(1); self.sld_lw.setMaximum(20); self.sld_lw.setValue(3)
        self.sld_lw.setTracking(True)
        self.sld_lw.setStyleSheet("height: 45px;")
        lbl_lwp = QLabel("粗"); lbl_lwp.setStyleSheet("font-size: 18px;")
        h_lw.addWidget(lbl_lw); h_lw.addWidget(lbl_lwm); h_lw.addWidget(self.sld_lw, 1); h_lw.addWidget(lbl_lwp)
        sl_col.addLayout(h_lw)
        self.sld_lw.sliderPressed.connect(lambda: self.style_edit_lock_changed.emit(True))
        self.sld_lw.valueChanged.connect(lambda v: self.measure_style_changed.emit('linewidth', str(v), 'drag'))
        self.sld_lw.sliderReleased.connect(lambda: self.measure_style_changed.emit('linewidth', str(self.sld_lw.value()), 'final'))
        self.sld_lw.sliderReleased.connect(lambda: self.style_edit_lock_changed.emit(False))
        
        # 线条颜色
        lbl_line_color = QLabel("线条颜色调整"); lbl_line_color.setStyleSheet("font-size: 16px;")
        sl_col.addWidget(lbl_line_color)
        h_col = QHBoxLayout()
        colors = [("白", "#ffffff", "#888"), ("黑", "#000000", "#333"),
                  ("绿", "#00FF00", "#5cb85c"), ("红", "#FF4444", "#d9534f")]
        for name, hex_val, bg in colors:
            b = QPushButton(name)
            b.setStyleSheet(f"QPushButton{{height:50px;font-size:18px;font-weight:bold;border-radius:6px;margin:2px;background:{bg};color:white;}}")
            def _emit_line_color(_checked=False, h=hex_val):
                self.style_edit_lock_changed.emit(True)
                self.measure_style_changed.emit('color', h, 'final')
                self.style_edit_lock_changed.emit(False)
            b.clicked.connect(_emit_line_color)
            h_col.addWidget(b)
        sl_col.addLayout(h_col)

        # 文字颜色
        self.widget_style_text_color = QWidget()
        sl_txt = QVBoxLayout(self.widget_style_text_color)
        sl_txt.setContentsMargins(0, 0, 0, 0)
        lbl_text_color = QLabel("文字颜色调整"); lbl_text_color.setStyleSheet("font-size: 16px;")
        sl_txt.addWidget(lbl_text_color)
        h_txt = QHBoxLayout()
        txt_colors = [("白", "#ffffff", "#888"), ("黑", "#000000", "#333"),
                      ("黄", "#ffff00", "#b8860b"), ("红", "#ff4444", "#d9534f")]
        for name, hex_val, bg in txt_colors:
            b = QPushButton(name)
            b.setStyleSheet(f"QPushButton{{height:50px;font-size:18px;font-weight:bold;border-radius:6px;margin:2px;background:{bg};color:white;}}")
            def _emit_text_color(_checked=False, h=hex_val):
                self.style_edit_lock_changed.emit(True)
                self.measure_style_changed.emit('text_color', h, 'final')
                self.style_edit_lock_changed.emit(False)
            b.clicked.connect(_emit_text_color)
            h_txt.addWidget(b)
        sl_txt.addLayout(h_txt)

        sl.addWidget(self.widget_style_color)
        sl.addWidget(self.widget_style_text_color)
        
        # Keep compatibility hook, but ensure it's parented to avoid top-level empty window popup.
        self.widget_style_width = QWidget(self.widget_style_controls)
        self.widget_style_width.hide()
        
        l.addStretch()
        self.tabs.addTab(w, "测量")

    def _init_tab_annotate(self):
        w = QWidget(); l = QVBoxLayout(w)
        
        b_mark = QPushButton("🏁 放置标记"); 
        b_mark.setCheckable(True); 
        b_mark.setStyleSheet(STYLE_TOUCH_BTN_NORMAL)
        b_mark.clicked.connect(lambda: self.on_tool_btn_clicked('marker', 'add', "➡️ 放置"))
        self.grp_tools.addButton(b_mark) 
        l.addWidget(b_mark)
        
        l.addStretch()
        self.tabs.addTab(w, "标注")

    def _init_tab_edit(self):
        w = QWidget(); l = QVBoxLayout(w)
        
        l.addWidget(self._line())
        
        self._add_btn(l, "🗑️ 删除选中", lambda: self.action_triggered.emit('delete'), "#d9534f")
        self._add_btn(l, "↩️ 撤回", lambda: self.action_triggered.emit('undo'))
        self._add_btn(l, "↔️ 反选", lambda: self.select_triggered.emit('invert'))
        
        l.addStretch()
        self.tabs.addTab(w, "编辑")

    # ================= Stage 3 UI =================
    def _init_stage3(self, parent):
        l = QVBoxLayout(parent); l.setContentsMargins(6, 6, 6, 6)

        lbl = QLabel("📦 输出阶段")
        lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #0275d8;")
        l.addWidget(lbl)
        l.addWidget(self._line())

        # 鈹€鈹€ Section 1: Top view 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        self.btn_s3_edit_top = QPushButton("📐 编辑 / 确认俯视图")
        self.btn_s3_edit_top.setCheckable(True)
        self.btn_s3_edit_top.setStyleSheet(STYLE_TOUCH_BTN_NORMAL)
        l.addWidget(self.btn_s3_edit_top)

        # Compass sub-panel
        self.widget_top_panel = QWidget()
        tl = QVBoxLayout(self.widget_top_panel); tl.setContentsMargins(0, 2, 0, 2)

        lbl_dir = QLabel("选择画面朝上方向:"); lbl_dir.setStyleSheet("font-size: 15px; color: #555;")
        tl.addWidget(lbl_dir)

        compass_grid = QWidget()
        cgrid = QGridLayout(compass_grid); cgrid.setSpacing(4)
        dirs = [("NW",0,0),("N",0,1),("NE",0,2),("W",1,0),("C",1,1),("E",1,2),("SW",2,0),("S",2,1),("SE",2,2)]
        CLABELS = {"NW":"西北↖","N":"北↑","NE":"东北↗","W":"西←","C":"·","E":"东→","SW":"西南↙","S":"南↓","SE":"东南↘"}
        self._compass_btns = {}
        cgrp = QButtonGroup(self)
        for key, r, c in dirs:
            btn = QPushButton(CLABELS[key]); btn.setFixedHeight(48)
            if key == "C":
                btn.setEnabled(False)
                btn.setStyleSheet("border:none; background:transparent; font-size:18px;")
            else:
                btn.setCheckable(True); btn.setStyleSheet("font-size:14px; border-radius:5px; border:1px solid #bbb;")
                cgrp.addButton(btn)
                def _on_dir(checked, k=key, b=btn):
                    if checked: self.action_triggered.emit(f'set_top_dir:{k}')
                btn.clicked.connect(_on_dir)
                self._compass_btns[key] = btn
            cgrid.addWidget(btn, r, c)
        self._compass_btns.get("N") and self._compass_btns["N"].setChecked(True)
        tl.addWidget(compass_grid)

        self.btn_s3_top = QPushButton("📳 确认并输出俯视图")
        self.btn_s3_top.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color:#5cb85c;color:white;")
        self.btn_s3_top.clicked.connect(lambda: self.action_triggered.emit('save_top'))
        tl.addWidget(self.btn_s3_top)
        self.widget_top_panel.hide()
        l.addWidget(self.widget_top_panel)

        l.addWidget(self._line())

        # 鈹€鈹€ Section 2: Scene view 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        self.btn_s3_edit_side = QPushButton("🎬 编辑 / 确认实景图")
        self.btn_s3_edit_side.setCheckable(True)
        self.btn_s3_edit_side.setStyleSheet(STYLE_TOUCH_BTN_NORMAL)
        l.addWidget(self.btn_s3_edit_side)

        self.widget_side_panel = QWidget()
        sl = QVBoxLayout(self.widget_side_panel); sl.setContentsMargins(0, 2, 0, 2)

        h_mode = QHBoxLayout()
        self.btn_s3_view  = QPushButton("🔄 旋转"); self.btn_s3_view.setCheckable(True)
        self.btn_s3_pan   = QPushButton("✋ 平移");  self.btn_s3_pan.setCheckable(True)
        grp_s3 = QButtonGroup(self)
        for b, m in [(self.btn_s3_view,'view'),(self.btn_s3_pan,'pan')]:
            b.setStyleSheet(STYLE_TOUCH_BTN_BIG)
            grp_s3.addButton(b); h_mode.addWidget(b)
            b.clicked.connect(lambda c=False, mode=m: self.global_mode_changed.emit(mode))
        self.btn_s3_view.setChecked(True)
        sl.addLayout(h_mode)

        self.btn_s3_side = QPushButton("📳 确认并输出实景图")
        self.btn_s3_side.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color:#5cb85c;color:white;")
        self.btn_s3_side.clicked.connect(lambda: self.action_triggered.emit('save_side'))
        sl.addWidget(self.btn_s3_side)
        self.widget_side_panel.hide()
        l.addWidget(self.widget_side_panel)

        # Toggle logic: mutual exclusion
        def _toggle_top(checked):
            if checked:
                self.btn_s3_edit_side.setChecked(False)
                self.widget_side_panel.hide()
                self.widget_top_panel.setVisible(True)
                self.action_triggered.emit('enter_top_edit')
            else:
                self.widget_top_panel.hide()
                self.action_triggered.emit('exit_top_edit')
        def _toggle_side(checked):
            if checked:
                self.btn_s3_edit_top.setChecked(False)
                self.widget_top_panel.hide()
                self.widget_side_panel.setVisible(True)
                self.action_triggered.emit('enter_side_edit')
            else:
                self.widget_side_panel.hide()
        self.btn_s3_edit_top.clicked.connect(_toggle_top)
        self.btn_s3_edit_side.clicked.connect(_toggle_side)

        l.addWidget(self._line())
        l.addStretch()

        b_back = QPushButton("↪️ 返回编辑阶段")
        b_back.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color:#f0ad4e;color:white;")
        b_back.clicked.connect(lambda: self.action_triggered.emit('back_to_stage2'))
        l.addWidget(b_back)

    # ================= 杈呭姪鏂规硶 =================
    def switch_stage(self, stage_index):
        self.stack_stages.setCurrentIndex(stage_index)

    def set_stage1_mode_selection(self, mode):
        btn_map = {
            'view': getattr(self, 'btn_s1_view', None),
            'pan': getattr(self, 'btn_s1_pan', None),
            'draw': getattr(self, 'btn_s1_draw', None),
        }
        target = btn_map.get(mode)
        if not target or not hasattr(self, 'grp_stage1_mode'):
            return
        self.grp_stage1_mode.setExclusive(False)
        for b in [self.btn_s1_view, self.btn_s1_pan, self.btn_s1_draw]:
            b.setChecked(False)
        self.grp_stage1_mode.setExclusive(True)
        target.setChecked(True)

    def clear_stage1_mode_selection(self):
        if not hasattr(self, 'grp_stage1_mode'):
            return
        self.grp_stage1_mode.setExclusive(False)
        for b in [self.btn_s1_view, self.btn_s1_pan, self.btn_s1_draw]:
            b.setChecked(False)
        self.grp_stage1_mode.setExclusive(True)

    def _append_error_log(self, text):
        try:
            base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            log_path = os.path.join(base_dir, "error_log.txt")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n=== ACTION_PANEL EXCEPTION ===\n")
                f.write((text or "").strip() + "\n")
        except Exception as e:
            print(f"[ACTION_PANEL][LOG_WRITE_FAILED] {e}")

    def _trace(self, msg):
        line = f"[TRACE][ActionPanel] {msg}"
        print(line)
        try:
            base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            with open(os.path.join(base_dir, "ui_trace.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def on_tool_btn_clicked(self, tool, mode, draw_text):
        try:
            self._trace(f"on_tool_btn_clicked tool={tool} mode={mode} draw_text={draw_text}")
            self.tool_selected.emit(tool, mode)
            self.btn_g_draw.setText(draw_text)
            self.btn_g_draw.show()
            self.btn_g_draw.click()
            self._trace("on_tool_btn_clicked done")
        except Exception as e:
            msg = f"[ACTION_PANEL][on_tool_btn_clicked] {e}\n{traceback.format_exc()}"
            print(msg)
            self._append_error_log(msg)

    def _on_tab_changed(self, index):
        """Tab switch reset: clear draw mode state and restore view mode."""
        try:
            self._trace(f"_on_tab_changed index={index}")
            checked = self.grp_tools.checkedButton()
            if checked:
                self.grp_tools.setExclusive(False)
                checked.setChecked(False)
                self.grp_tools.setExclusive(True)

            self.btn_g_draw.hide()
            self.btn_g_view.setChecked(True)
            self.global_mode_changed.emit('view')

            if index == 2:
                self.btn_g_sel.show()
            else:
                self.btn_g_sel.hide()
                if self.btn_g_sel.isChecked():
                    self.grp_global.setExclusive(False)
                    self.btn_g_sel.setChecked(False)
                    self.grp_global.setExclusive(True)

            if hasattr(self, 'widget_style_font'):
                self.widget_style_font.setVisible(index in [0, 1])
            if hasattr(self, 'widget_style_color'):
                self.widget_style_color.setVisible(index == 0)
            if hasattr(self, 'widget_style_text_color'):
                self.widget_style_text_color.setVisible(index in [0, 1])
            if hasattr(self, 'widget_style_width'):
                self.widget_style_width.setVisible(index == 0)
            self._trace("_on_tab_changed done")
        except Exception as e:
            msg = f"[ACTION_PANEL][_on_tab_changed] {e}\n{traceback.format_exc()}"
            print(msg)
            self._append_error_log(msg)

    def update_select_button_text(self, text):
        self.btn_s1_draw.setText(text)

    def _on_toggle_visibility(self, checked):
        """切换所有标注元素的显示/隐藏状态"""
        if checked:
            self.btn_toggle_vis.setText("🟢 显示所有标注")
            self.btn_toggle_vis.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #d9534f; color: white;")
            self.action_triggered.emit('toggle_vis_hide')
        else:
            self.btn_toggle_vis.setText("🔴 隐藏所有标注")
            self.btn_toggle_vis.setStyleSheet(STYLE_TOUCH_BTN_NORMAL + "background-color: #555; color: white;")
            self.action_triggered.emit('toggle_vis_show')

    def update_select_button_text(self, text):
        self.btn_s1_draw.setText(text)

    def _on_toggle_output(self, checked):
        """展开/收起输出菜单，并联动样式区显示。"""
        if checked:
            self.btn_output.setText("➡️ 输出")
            self.widget_output_menu.show()
            # 闅愯棌娴嬮噺 tab 涓殑鏍峰紡鎺т欢
            if hasattr(self, 'widget_style_controls'):
                self.widget_style_controls.hide()
        else:
            self.btn_output.setText("➡️ 输出")
            self.widget_output_menu.hide()
            if hasattr(self, 'widget_style_controls'):
                self.widget_style_controls.show()

    def set_mesh_output_visible(self, visible):
        if hasattr(self, "btn_out_mesh"):
            self.btn_out_mesh.setVisible(bool(visible))

    def _setup_group(self, layout, buttons, signal):
        bg = QButtonGroup(self)
        buttons[0].setChecked(True)
        modes = ["view", "pan", "draw"]
        for i, b in enumerate(buttons):
            b.setCheckable(True)
            b.setStyleSheet(STYLE_TOUCH_BTN_BIG) # Stage 1 椤堕儴鎸夐挳涔熺敤澶х殑
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
        return btn
    
    def _btn_style_s2(self):
        # 鍏煎鏃ф帴鍙ｏ紝铏界劧瀹為檯涓婄敤 STYLE_TOUCH_BTN_NORMAL 鏇夸唬浜?
        return STYLE_TOUCH_BTN_NORMAL

    def _line(self):
        line = QFrame(); line.setFrameShape(QFrame.HLine); line.setFrameShadow(QFrame.Sunken); return line



