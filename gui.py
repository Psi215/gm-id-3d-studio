# -*- coding: utf-8 -*-
"""
gm/ID 设计数据浏览器 —— 桌面 GUI(PySide6 + matplotlib)
========================================================
视图:
  * 曲线族 (2D): 每条 L 一条线, 颜色映射 L; 可叠加多数据集(nmos/pmos/不同 VDD/工艺角)
  * 三维曲面:     z = 指标(gm/ID, L), 可旋转/缩放; 支持多条数据集叠加对比
  * 剖面与等高线: 等高线 + 固定 gm/ID 的 L 剖面、固定 L 位置标注
筛查:
  * 范围过滤(gm/ID、L、指标)全联动
  * 数据清洗(扫描回折剔除 / Savgol 平滑 / MAD 坏点剔除)
  * 反向设计查表(指标下限 -> 可行 (gm/ID, L) 区间 + 推荐设计点)
  * 导出(视图图片 / 清洗数据 / 曲面公共栅格 / 查表结果)
"""
from __future__ import annotations

import csv
import os
import time

import numpy as np
from matplotlib import colormaps
from matplotlib import rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavToolbar
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (注册 3d 投影)

rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
    "Arial Unicode MS", "DejaVu Sans",
]
rcParams["axes.unicode_minus"] = False
# 3D 鼠标旋转风格(matplotlib>=3.9 的四元数旋转, 比默认 azel 更顺滑自然)
try:
    rcParams["axes3d.mouserotationstyle"] = "trackball"
except Exception:
    pass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDockWidget, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from gmidlib import clean as cleanmod
from gmidlib import lookup as lookupmod
from gmidlib import parse as parsemod
from gmidlib import surface as surfmod

CMAPS = ["viridis", "plasma", "cividis", "magma", "coolwarm", "turbo"]
LSTYLES = ["-", "--", "-.", ":"]


def _getcmap(name):
    return colormaps[name]


def fmt(x, sig=4):
    try:
        return f"{x:.{sig}g}"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
class MplPanel(QWidget):
    """一个 matplotlib 画布 + 导航工具栏的容器。可 1/2 个主坐标轴。"""

    def __init__(self, parent=None, nrows=1, projection=None):
        super().__init__(parent)
        self.fig = Figure(figsize=(7.5, 5.2), layout="constrained")
        if projection == "3d":
            self.axes = self.fig.add_subplot(111, projection="3d")
            self.axes2 = None
        elif nrows == 2:
            gs = self.fig.add_gridspec(2, 1, height_ratios=[3, 2])
            self.axes = self.fig.add_subplot(gs[0])
            self.axes2 = self.fig.add_subplot(gs[1])
        else:
            self.axes = self.fig.add_subplot(111)
            self.axes2 = None
        self.canvas = FigureCanvas(self.fig)
        self.cbar_ax = None       # 色标的坐标轴(用于复用/删除/保留)
        self._cbar_obj = None     # Colorbar 对象(用于更新与 set_label)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(NavToolbar(self.canvas, self))
        lay.addWidget(self.canvas)

    def clear_all(self):
        """清空主坐标轴, 但保留(复用的)色标轴——反复新建/删除色标会让布局
        管理器每次多占一格空间, 导致主图越缩越小。"""
        keep = {id(self.axes)}
        if self.axes2 is not None:
            keep.add(id(self.axes2))
        if getattr(self, "cbar_ax", None) is not None:
            keep.add(id(self.cbar_ax))
        for a in list(self.fig.axes):
            if id(a) not in keep:
                self.fig.delaxes(a)
        for ax in (self.axes, self.axes2):
            if ax is not None:
                ax.clear()

    def set_colorbar(self, mappable, label=None, **kw):
        """创建(仅一次)或更新色标, 始终复用同一个色标轴。"""
        if getattr(self, "cbar_ax", None) is None:
            cb = self.fig.colorbar(mappable, ax=self.axes, **kw)
            self.cbar_ax = cb.ax
            self._cbar_obj = cb
        else:
            try:
                self._cbar_obj = self.fig.colorbar(mappable, cax=self.cbar_ax)
            except Exception:
                self.fig.delaxes(self.cbar_ax)
                cb = self.fig.colorbar(mappable, ax=self.axes, **kw)
                self.cbar_ax = cb.ax
                self._cbar_obj = cb
        if label is not None and self._cbar_obj is not None:
            self._cbar_obj.set_label(label)
        return self.cbar_ax

    def clear_colorbar(self):
        cax = getattr(self, "cbar_ax", None)
        if cax is not None:
            try:
                self.fig.delaxes(cax)
            except Exception:
                pass
        self.cbar_ax = None
        self._cbar_obj = None


# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, initial_files=None):
        super().__init__()
        self.setWindowTitle("gm/ID 设计数据浏览器 · 三维曲面与筛查")
        self.resize(1520, 960)
        self.datasets: dict[str, parsemod.Dataset] = {}
        self.visible: set[str] = set()
        self.current_key: str = ""
        self._lookup = None          # lookupmod.LookupResult(当前数据集)
        self._surf = {}              # key -> build_surface() 结果
        self._loading = False
        self._replot_timer = QTimer(self)
        self._replot_timer.setSingleShot(True)
        self._replot_timer.timeout.connect(self.replot_all)

        self._build_ui()
        self._make_menu()
        self.statusBar().showMessage("就绪: 打开 gm/ID 曲线文件(宽表/长表均可)")
        if initial_files:
            QTimer.singleShot(80, lambda: self.open_paths(initial_files))

    # ============================= UI =============================
    def _build_ui(self):
        self._loading = True
        left = QWidget()
        left.setMinimumWidth(340)
        lay = QVBoxLayout(left)
        lay.setSpacing(6)

        # --- ① 文件与数据集 ---
        g = QGroupBox("① 数据文件与数据集")
        v = QVBoxLayout(g)
        row = QHBoxLayout()
        b1 = QPushButton("打开文件…"); b1.clicked.connect(self._open_files)
        b2 = QPushButton("打开文件夹…"); b2.clicked.connect(self._open_dir)
        row.addWidget(b1); row.addWidget(b2)
        v.addLayout(row)
        self.lst = QListWidget(); self.lst.setMaximumHeight(140)
        self.lst.itemChanged.connect(self._on_vis_toggle)
        v.addWidget(QLabel("数据集(勾选 = 显示并参与叠加):"))
        v.addWidget(self.lst)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("当前数据集:"))
        self.cmb_cur = QComboBox()
        self.cmb_cur.currentIndexChanged.connect(self._on_cur_change)
        row2.addWidget(self.cmb_cur, 1)
        v.addLayout(row2)
        self.lb_parse = QLabel(""); self.lb_parse.setWordWrap(True)
        self.lb_parse.setStyleSheet("color:#777;")
        v.addWidget(self.lb_parse)
        lay.addWidget(g)

        # --- ② 数据清洗 ---
        g = QGroupBox("② 数据清洗(作用于当前数据集)")
        v = QVBoxLayout(g)
        self.cb_fold = QCheckBox("剔除扫描头部回折(保留单调主支)")
        self.cb_fold.setChecked(True); v.addWidget(self.cb_fold)
        self.cb_smooth = QCheckBox("Savitzky-Golay 平滑")
        v.addWidget(self.cb_smooth)
        row = QHBoxLayout()
        row.addWidget(QLabel("窗口(奇):"))
        self.sp_swin = QSpinBox(); self.sp_swin.setRange(3, 51)
        self.sp_swin.setSingleStep(2); self.sp_swin.setValue(9)
        row.addWidget(self.sp_swin)
        row.addWidget(QLabel("阶:"))
        self.sp_sord = QSpinBox(); self.sp_sord.setRange(1, 5)
        self.sp_sord.setValue(2)
        row.addWidget(self.sp_sord); row.addStretch(1)
        v.addLayout(row)
        self.cb_outlier = QCheckBox("MAD 坏点剔除"); v.addWidget(self.cb_outlier)
        row = QHBoxLayout(); row.addWidget(QLabel("k×MAD:"))
        self.sp_madk = QDoubleSpinBox(); self.sp_madk.setRange(1.0, 20.0)
        self.sp_madk.setValue(5.0)
        row.addWidget(self.sp_madk); row.addStretch(1); v.addLayout(row)
        b = QPushButton("重新清洗并刷新"); b.clicked.connect(self._reclean)
        v.addWidget(b)
        lay.addWidget(g)

        # --- ③ 过滤 / 显示 ---
        g = QGroupBox("③ 范围过滤 · 显示")
        v = QVBoxLayout(g)
        row = QHBoxLayout()
        self.cb_db = QCheckBox("增益类指标以 dB 显示"); self.cb_db.setChecked(True)
        row.addWidget(self.cb_db)
        self.cb_rawdb = QCheckBox("原始数据已是 dB(自动识别)")
        row.addWidget(self.cb_rawdb); v.addLayout(row)
        row = QHBoxLayout()
        self.cb_xlog = QCheckBox("gm/ID 对数轴")
        row.addWidget(self.cb_xlog)
        self.cb_Llog = QCheckBox("L 对数轴")
        row.addWidget(self.cb_Llog); v.addLayout(row)

        def mk_sp(lo, hi, val, dec=4, step=0.1):
            s = QDoubleSpinBox(); s.setRange(lo, hi); s.setDecimals(dec)
            s.setValue(val); s.setSingleStep(step); s.setKeyboardTracking(False)
            return s

        self.sp_xmin = mk_sp(-1e9, 1e9, 0.0)
        self.sp_xmax = mk_sp(-1e9, 1e9, 30.0)
        self.sp_Lmin = mk_sp(0.0, 1e6, 0.0, 4)
        self.sp_Lmax = mk_sp(0.0, 1e6, 10.0, 4)
        self.sp_gmin = mk_sp(-1e12, 1e12, 0.0, 4)
        self.sp_gmax = mk_sp(-1e12, 1e12, 100.0, 4)
        for lab, a, b in (("gm/ID 范围:", self.sp_xmin, self.sp_xmax),
                          ("L 范围 (µm):", self.sp_Lmin, self.sp_Lmax),
                          ("指标范围:", self.sp_gmin, self.sp_gmax)):
            row = QHBoxLayout()
            row.addWidget(QLabel(lab))
            row.addWidget(a, 1); row.addWidget(QLabel("~")); row.addWidget(b, 1)
            v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("曲面栅格:"))
        self.sp_npts = QSpinBox(); self.sp_npts.setRange(50, 1500)
        self.sp_npts.setValue(240); self.sp_npts.setSingleStep(20)
        row.addWidget(self.sp_npts)
        b = QPushButton("自动范围"); b.clicked.connect(self._auto_range_full)
        row.addWidget(b); v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("3D 旋转:"))
        self.cmb_rot = QComboBox()
        for label, val in (("转台式 (azel)", "azel"),
                           ("轨迹球 (trackball)", "trackball"),
                           ("球面 (sphere)", "sphere"),
                           ("弧球 (arcball)", "arcball")):
            self.cmb_rot.addItem(label, val)
        self.cmb_rot.setCurrentIndex(1)     # 默认轨迹球, 手感更顺
        row.addWidget(self.cmb_rot, 1); v.addLayout(row)
        self.cmb_rot.currentIndexChanged.connect(self._on_rot_style)
        row = QHBoxLayout()
        b = QPushButton("⟲ 3D 视角复位 (Ctrl+R)")
        b.clicked.connect(self._reset_3d_view)
        row.addWidget(b); v.addLayout(row)
        lay.addWidget(g)

        # --- ④ 反向查表 ---
        g = QGroupBox("④ 反向设计查表(当前数据集)")
        v = QVBoxLayout(g)
        self.cb_lk = QCheckBox("启用: 指标满足阈值约束即视为可行")
        self.cb_lk.setChecked(True); v.addWidget(self.cb_lk)
        row = QHBoxLayout()
        row.addWidget(QLabel("方向:"))
        self.cb_dir = QComboBox()
        self.cb_dir.addItem("≥ 指标不小于阈值(增益/fT 等)", "max")
        self.cb_dir.addItem("≤ 指标不大于阈值(Vdsat/电流等)", "min")
        row.addWidget(self.cb_dir, 1); v.addLayout(row)
        row = QHBoxLayout(); row.addWidget(QLabel("阈值:"))
        self.sp_thr = mk_sp(-1e12, 1e12, 50.0, 4)
        row.addWidget(self.sp_thr); row.addStretch(1); v.addLayout(row)
        self.lb_lk = QLabel(
            "推荐点取可行区贴阈值的一端(≥ 取最小 gm/ID 保速度;≤ 取最大 "
            "gm/ID 不浪费裕量);可行区在 2D 用红色竖条、3D/等高线用红圈标出。")
        self.lb_lk.setWordWrap(True); self.lb_lk.setStyleSheet("color:#777;")
        v.addWidget(self.lb_lk)
        b = QPushButton("立即执行查表"); b.clicked.connect(self._do_lookup)
        v.addWidget(b)
        lay.addWidget(g)

        lay.addStretch(1)
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(left)

        # --- 视图 ---
        self.tabs = QTabWidget()
        self.p_curves = MplPanel(); self.tabs.addTab(self.p_curves, "曲线族 2D")
        self.p_surf = MplPanel(projection="3d")
        self.tabs.addTab(self.p_surf, "三维曲面 3D")
        self.p_prof = MplPanel(nrows=2)
        bar = QWidget(); hb = QHBoxLayout(bar); hb.setContentsMargins(4, 2, 4, 0)
        hb.addWidget(QLabel("固定 gm/ID(看 L 剖面):"))
        self.sp_fix_x = mk_sp(1e-6, 1e9, 10.0)
        hb.addWidget(self.sp_fix_x)
        hb.addWidget(QLabel("   标注 L (µm):"))
        self.sp_fix_L = mk_sp(1e-6, 1e6, 1.0, 4)
        hb.addWidget(self.sp_fix_L); hb.addStretch(1)
        tw = QWidget(); vl = QVBoxLayout(tw); vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(bar); vl.addWidget(self.p_prof)
        self.tabs.addTab(tw, "剖面与等高线")

        # --- 查表结果 ---
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["L (µm)", "可行区 左 gm/ID", "可行区 右 gm/ID",
             "推荐 gm/ID", "指标@推荐(显示单位)", "指标原始值", "栅格点数"])
        self.table.horizontalHeader().setStretchLastSection(True)
        dock = QDockWidget("反向查表结果(当前数据集)", self)
        dock.setWidget(self.table)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.tabs)          # 图形主体在左
        split.addWidget(sa)                 # 控制面板在右
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 0)
        split.setSizes([1150, 370])
        self.setCentralWidget(split)

        for w in (self.cb_xlog, self.cb_Llog, self.cb_lk):
            w.toggled.connect(self._schedule)
        self.cb_dir.currentIndexChanged.connect(self._schedule)
        # dB/线性 切换属于“显示域”变化: 指标范围过滤器要跟着数据自动复位,
        # 否则旧单位下的上下限会静默滤掉大部分曲线(看起来“图消失了”)
        self.cb_db.toggled.connect(self._on_display_mode)
        self.cb_rawdb.toggled.connect(self._on_display_mode)
        # 清洗参数变化 -> 真正重新清洗(而不是只重绘旧结果)
        for w in (self.cb_fold, self.cb_smooth, self.cb_outlier):
            w.toggled.connect(self._on_clean_change)
        for w in (self.sp_swin, self.sp_sord, self.sp_madk):
            w.valueChanged.connect(self._on_clean_change)
        for w in (self.sp_npts, self.sp_xmin, self.sp_xmax, self.sp_Lmin,
                  self.sp_Lmax, self.sp_gmin, self.sp_gmax, self.sp_thr,
                  self.sp_fix_x, self.sp_fix_L):
            w.valueChanged.connect(self._schedule)
        self._loading = False
        self._sync_spin_suffix()
        self._sc_reset = QShortcut(QKeySequence("Ctrl+R"), self)
        self._sc_reset.activated.connect(self._reset_3d_view)

    def _on_clean_change(self):
        if self._loading:
            return
        self._reclean(refresh=True)

    def _on_display_mode(self):
        if self._loading:
            return
        self._sync_spin_suffix()
        self._auto_range()
        self._replot_timer.start(120)

    def _on_rot_style(self):
        """切换 3D 鼠标旋转手感(matplotlib axes3d.mouserotationstyle)。"""
        val = self.cmb_rot.currentData()
        try:
            rcParams["axes3d.mouserotationstyle"] = val
        except Exception:
            pass
        self.p_surf.canvas.draw_idle()

    def _reset_3d_view(self):
        """3D 视角复位: 默认俯仰/方位角 + 范围回到数据。"""
        p = self.p_surf
        try:
            p.axes.view_init(elev=24.0, azim=-125.0, roll=0.0)
        except Exception:
            try:
                p.axes.view_init(elev=24.0, azim=-125.0)
            except Exception:
                pass
        self._auto_view(p)
        self.statusBar().showMessage("3D 视角已复位", 3000)
        p.canvas.draw_idle()

    def _make_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("文件")
        m.addAction("打开文件…", self._open_files)
        m.addAction("打开文件夹…", self._open_dir)
        m.addAction("手动映射解析(长表列名不标准时)…", self._open_manual)
        m.addAction("关闭全部数据", self._clear_all_data)
        m.addSeparator(); m.addAction("退出", self.close)
        m = mb.addMenu("导出")
        m.addAction("当前视图图片 (PNG/SVG/PDF)…", self._export_fig)
        m.addAction("当前数据集 清洗后长表 (CSV)…", self._export_data)
        m.addAction("曲面公共栅格 (CSV)…", self._export_grid)
        m.addAction("查表结果 (CSV)…", self._export_lookup)
        m = mb.addMenu("帮助")
        m.addAction("关于 / 使用说明", self._about)

    # ================= 显示单位(按指标类型适配) =================
    def _db_view_on(self, ds=None) -> bool:
        ds = ds if ds is not None else self._current_ds()
        prof = getattr(ds, "profile", None)
        return bool(prof is not None and prof.db_capable
                    and self.cb_db.isChecked())

    def ds_disp(self, ds, y):
        """把某数据集的原始值换算成显示值:
        增益类 + dB 视图 -> 20log10(线性原始值)(原始即 dB 则原样);
        其它情况 -> 原始值 × 工程前缀因子(如 Hz->GHz);
        原始即 dB 且线性视图 -> 先 10^(y/20) 还原。"""
        a = np.asarray(y, float)
        prof = getattr(ds, "profile", None)
        raw_db = bool(getattr(ds, "raw_db", False))
        if self._db_view_on(ds):
            if raw_db:
                return a
            with np.errstate(divide="ignore"):
                return np.where(np.isfinite(a) & (a > 0),
                                20.0 * np.log10(a), -np.inf)
        if raw_db:
            a = 10.0 ** (a / 20.0)
        return a * float(getattr(ds, "disp_factor", 1.0) or 1.0)

    def _unit_str(self, ds=None) -> str:
        """当前显示单位的字符串(用于 spin 后缀/状态栏), 如 'dB' / 'GHz'。"""
        ds = ds if ds is not None else self._current_ds()
        if self._db_view_on(ds):
            return "dB"
        return getattr(ds, "disp_unit", "") or ""

    def _sync_spin_suffix(self):
        ds = self._current_ds()
        unit = self._unit_str(ds)
        suffix = f" {unit}" if unit else ""
        for w in (self.sp_gmin, self.sp_gmax, self.sp_thr):
            w.setSuffix(suffix)
        if ds is None:
            return            # 无数据时不改动 dB 勾选框状态(保留默认)
        # 非增益类指标没有 dB 视图; 两个 dB 勾选框自动禁用
        prof = getattr(ds, "profile", None)
        gain_ok = bool(prof is not None and prof.db_capable)
        self._loading = True
        self.cb_db.setEnabled(gain_ok)
        self.cb_rawdb.setEnabled(gain_ok)
        if not gain_ok:
            if self.cb_db.isChecked():
                self.cb_db.setChecked(False)
            if self.cb_rawdb.isChecked():
                self.cb_rawdb.setChecked(False)
        self._loading = False

    def _ylab(self):
        ds = self._current_ds()
        if ds is None:
            return "指标"
        prof = getattr(ds, "profile", None)
        base = (prof.name if prof is not None and prof.name else ds.metric)
        if self._db_view_on(ds):
            return f"{base} (dB)"
        return f"{base} ({ds.disp_unit})" if ds.disp_unit else base

    def _xlab(self):
        ds = self._current_ds()
        name = getattr(ds, "x_name", "") if ds is not None else ""
        return name if name and name not in ("X", "x") else "gm/ID (1/V)"

    # ================= 装载 =================
    def _open_files(self):
        fs, _ = QFileDialog.getOpenFileNames(
            self, "选择 gm/ID 曲线数据文件", "",
            "数据文件 (*.csv *.txt *.dat *.tsv);;所有文件 (*)")
        if fs:
            self.open_paths(fs)

    def _open_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择数据文件夹(批量导入同型文件)")
        if d:
            self.open_paths([d])

    def _adopt(self, dss: dict, note: str = ""):
        """把解析出的 {key: Dataset} 并入界面并刷新。"""
        added = []
        for key, ds in dss.items():
            if key not in self.datasets:
                self.datasets[key] = ds
                added.append(key)
        if not added:
            self._rebuild_selector()
            return 0
        for k in added:
            self.visible.add(k)
        if self.current_key not in self.datasets:
            self.current_key = added[0]
        self._rebuild_selector()
        self._sync_metric_state()
        self._reclean(refresh=False)
        self._auto_range()
        if note:
            self.lb_parse.setText(note)
        self.replot_all()
        return len(added)

    def open_paths(self, paths):
        t0 = time.time()
        dss, errs = parsemod.parse_paths(paths)
        if not dss and not errs:
            QMessageBox.information(self, "提示", "没有找到 CSV/TXT/DAT 文件。")
            return
        n = self._adopt(dss)
        msg = f"已载入 {n} 个数据集 ({time.time()-t0:.2f} s)"
        if errs:
            self.lb_parse.setText("以下文件自动识别失败(可改用『手动映射解析』):\n"
                                  + "\n".join(errs[:6]))
            msg += f"; {len(errs)} 个文件跳过"
        else:
            self.lb_parse.setText("自动识别成功; 勾选框可叠加多个数据集对比。")
        self.statusBar().showMessage(msg, 8000)

    # ---------------- 手动映射解析 ----------------
    def _open_manual(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "手动映射解析的文件", "",
            "数据文件 (*.csv *.txt *.dat *.tsv);;所有文件 (*)")
        if not path:
            return
        try:
            header, _ = parsemod._read_csv(path)
        except Exception as e:
            QMessageBox.warning(self, "无法读取", str(e))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("手动列映射 · " + os.path.basename(path))
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("表头:" + " | ".join(header[:10])
                             + (" …" if len(header) > 10 else "")))
        auto_opts = ["(自动检测)"] + header
        row = QHBoxLayout(); row.addWidget(QLabel("参数列(L):"))
        cb_p = QComboBox(); cb_p.addItems(auto_opts)
        row.addWidget(cb_p, 1); lay.addLayout(row)
        row = QHBoxLayout(); row.addWidget(QLabel("X 列(gm/ID):"))
        cb_x = QComboBox(); cb_x.addItems(auto_opts)
        row.addWidget(cb_x, 1); lay.addLayout(row)
        lay.addWidget(QLabel("指标列(Y, 可多选; 每列一个数据集):"))
        lw = QListWidget()
        for h in header:
            it = QListWidgetItem(h)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            lw.addItem(it)
        lay.addWidget(lw)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        p = cb_p.currentText() if cb_p.currentIndex() > 0 else None
        x = cb_x.currentText() if cb_x.currentIndex() > 0 else None
        ms = [lw.item(i).text() for i in range(lw.count())
              if lw.item(i).checkState() == Qt.Checked]
        try:
            dss = parsemod.parse_file(path, param_col=p, x_col=x,
                                      metric_cols=ms or None)
        except Exception as e:
            QMessageBox.warning(self, "解析失败", str(e))
            return
        n = self._adopt({d.key: d for d in dss}, note="手动映射解析成功。")
        if not n:
            return
        self.statusBar().showMessage(f"手动映射载入 {n} 个数据集", 6000)

    def _clear_all_data(self):
        self.datasets.clear(); self.visible.clear()
        self.current_key = ""; self._lookup = None
        self._rebuild_selector(); self.replot_all()

    def _rebuild_selector(self):
        self._loading = True
        self.lst.blockSignals(True)
        self.lst.clear()
        for key in sorted(self.datasets):
            ds = self.datasets[key]
            it = QListWidgetItem(
                f"{ds.file_group} · {ds.metric}  ({len(ds.series)} 条曲线)")
            it.setData(Qt.UserRole, key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if key in self.visible
                             else Qt.Unchecked)
            self.lst.addItem(it)
        self.lst.blockSignals(False)
        self.cmb_cur.blockSignals(True)
        self.cmb_cur.clear()
        for key in sorted(self.datasets):
            ds = self.datasets[key]
            self.cmb_cur.addItem(f"{ds.file_group} · {ds.metric}", key)
        if self.current_key in self.datasets:
            i = self.cmb_cur.findData(self.current_key)
            if i >= 0:
                self.cmb_cur.setCurrentIndex(i)
        self.cmb_cur.blockSignals(False)
        self._loading = False

    # ================= 交互 =================
    def _on_vis_toggle(self, item):
        key = item.data(Qt.UserRole)
        on = item.checkState() == Qt.Checked
        (self.visible.add if on else self.visible.discard)(key)
        self.replot_all()

    def _on_cur_change(self, _):
        if self._loading:
            return
        key = self.cmb_cur.currentData()
        if key and key in self.datasets:
            self.current_key = key
            self._sync_metric_state()
            self._reclean(refresh=False)
            self._auto_range()
            self.replot_all()

    def _sync_metric_state(self):
        """按当前数据集的指标类型同步 原始dB勾选 / 查表方向。"""
        ds = self._current_ds()
        if ds is None:
            return
        prof = getattr(ds, "profile", None)
        self._loading = True
        if prof is not None and prof.db_capable:
            self.cb_rawdb.setChecked(bool(getattr(ds, "raw_db", False)))
        if prof is not None:
            i = self.cb_dir.findData(prof.direction)
            if i >= 0:
                self.cb_dir.setCurrentIndex(i)
        self._loading = False

    def _schedule(self):
        if self._loading:
            return
        self._sync_spin_suffix()
        self._replot_timer.start(120)

    def _current_ds(self):
        ds = self.datasets.get(self.current_key)
        if ds is None and self.datasets:
            ds = self.datasets[next(iter(self.datasets))]
        return ds

    def _reclean(self, refresh=True):
        ds = self._current_ds()
        if ds is None:
            return
        stats = cleanmod.clean_dataset(
            ds,
            drop_fold=self.cb_fold.isChecked(), sort_x=True,
            smooth=self.cb_smooth.isChecked(),
            window=self.sp_swin.value(), order=self.sp_sord.value(),
            outlier=self.cb_outlier.isChecked(), k_mad=self.sp_madk.value())
        removed = sum(s.get("dropped", 0) for s in stats)
        n = sum(1 for s in stats if s.get("kept", 0) >= 2)
        self.statusBar().showMessage(
            f"清洗完成: {len(stats)} 条曲线, {n} 条可用, "
            f"共剔除/去重 {removed} 点", 6000)
        if refresh:
            self.replot_all()

    def _auto_range_full(self):
        self._auto_range()
        self.replot_all()

    def _auto_range(self):
        """自动范围 = 所有已勾选(可见)数据集的并集(各自换算到显示域),
        保证叠加对比一致; 同时按当前指标类型给出阈值/方向默认值。"""
        keys = list(self.visible)
        if not keys:
            cur = self._current_ds()
            if cur is not None:
                keys = [next(k for k, d in self.datasets.items() if d is cur)]
        if not keys:
            return
        xs_all, yd_all, Ls = [], [], []
        per_key = {}
        for key in keys:
            ds = self.datasets.get(key)
            if ds is None:
                continue
            dsp = []
            for s in surfmod.cleaned_series_of(ds, require_param=False):
                if s[1].size:
                    xs_all.append(s[1])
                    dsp.append(self.ds_disp(ds, s[2]))
                if s[0] is not None:
                    Ls.append(s[0])
            if dsp:
                per_key[key] = np.concatenate(dsp)
        if not xs_all:
            return
        xs_all = np.concatenate(xs_all)
        for arr in per_key.values():
            yd_all.append(arr)
        yd_all = np.concatenate(yd_all)
        fin = np.isfinite(yd_all)
        if fin.sum() == 0 or xs_all.size == 0:
            return
        xlo, xhi = float(np.min(xs_all)), float(np.max(xs_all))
        xpad = 0.03 * (xhi - xlo) or 1.0
        ylo = float(np.min(yd_all[fin]))
        yhi = float(np.max(yd_all[fin]))
        ypad = max(0.05 * (yhi - ylo), 1e-12)
        self._loading = True
        self.sp_xmin.setValue(xlo - xpad)
        self.sp_xmax.setValue(xhi + xpad)
        if Ls:
            Larr = np.array(Ls, float)
            self.sp_Lmin.setValue(max(0.0, float(Larr.min()) * 0.9))
            self.sp_Lmax.setValue(float(Larr.max()) * 1.1)
        self.sp_gmin.setValue(ylo - ypad)
        self.sp_gmax.setValue(yhi + ypad)
        if Ls:
            self.sp_fix_L.setValue(float(np.median(Ls)))
        self.sp_fix_x.setValue(min(max(0.5 * (xlo + xhi), 1e-6), xhi))
        # 查表方向与阈值默认: 只用“当前数据集”的显示值范围(避免其它量纲
        # 的数据集污染阈值, 如 fT(GHz) 与自增益(V/V) 混叠时)
        ds = self._current_ds()
        prof = getattr(ds, "profile", None)
        direction = self.cb_dir.currentData() or (
            prof.direction if prof is not None else "max")
        i = self.cb_dir.findData(direction)
        if i >= 0:
            self.cb_dir.setCurrentIndex(i)
        if self.current_key in per_key:
            cur_fin = per_key[self.current_key]
            cur_fin = cur_fin[np.isfinite(cur_fin)]
            if cur_fin.size:
                c_lo, c_hi = float(cur_fin.min()), float(cur_fin.max())
                if direction == "max":
                    self.sp_thr.setValue(c_lo + 0.8 * (c_hi - c_lo))
                else:
                    self.sp_thr.setValue(c_lo + 0.2 * (c_hi - c_lo))
        self._sync_spin_suffix()
        self._loading = False

    # ================= 计算 =================
    def _filters(self):
        return dict(xmin=self.sp_xmin.value(), xmax=self.sp_xmax.value(),
                    Lmin=self.sp_Lmin.value(), Lmax=self.sp_Lmax.value(),
                    gmin=self.sp_gmin.value(), gmax=self.sp_gmax.value(),
                    xlog=self.cb_xlog.isChecked(), Llog=self.cb_Llog.isChecked(),
                    npts=self.sp_npts.value())

    def _build_surfaces(self):
        self._surf.clear()
        f = self._filters()
        for key in list(self.visible):
            ds = self.datasets.get(key)
            if ds is None:
                continue
            sers = [s for s in surfmod.cleaned_series_of(ds)
                    if s[0] is not None and f["Lmin"] <= s[0] <= f["Lmax"]]
            if not sers:
                continue
            xmin, xmax = f["xmin"], f["xmax"]
            if f["xlog"]:
                # 对数 X 轴不允许非正边界: 否则栅格会从 ~1e-308 开始,
                # 曲线被压到右边缘一点, 看起来“消失/被无限缩小”
                pos = np.concatenate([s[1][s[1] > 0] for s in sers])
                if pos.size:
                    dlo, dhi = float(pos.min()), float(pos.max())
                    if xmin <= 0:
                        xmin = dlo * 0.8
                    if xmax <= 0 or xmax <= xmin:
                        xmax = dhi * 1.2
            try:
                sf = surfmod.build_surface(sers, xmin=xmin, xmax=xmax,
                                           n=f["npts"], xlog=f["xlog"])
            except Exception:
                continue
            sf["sers"] = sers
            self._surf[key] = sf

    def _compute_lookup(self):
        key = self.current_key or (next(iter(self.visible), None))
        sf = self._surf.get(key)
        if sf is None or not np.isfinite(sf["Z"]).any():
            return None
        ds = self.datasets.get(key)
        if ds is None:
            return None
        Zd = self.ds_disp(ds, sf["Z"])           # 阈值比较在显示域进行
        direction = self.cb_dir.currentData() or "max"
        res = lookupmod.run_lookup(Zd, sf["xs"], sf["Ls"],
                                   float(self.sp_thr.value()),
                                   direction=direction)
        return res

    def _do_lookup(self):
        self.replot_all()

    def _auto_view(self, panel):
        """让坐标轴始终跟随当前数据自动定标, 防止工具栏缩放/平移留下的
        旧视图范围把新画的数据压成“无限小”(用户调范围过滤/显示时图消失)。"""
        for ax in (panel.axes, panel.axes2):
            if ax is None:
                continue
            try:
                if str(getattr(ax, "name", "")).startswith("3d"):
                    ax.autoscale(enable=True)
                    ax.margins(0.05)
                else:
                    ax.relim()
                    ax.autoscale_view()
                    ax.margins(0.03, 0.05)
            except Exception:
                pass

    def replot_all(self):
        if not self.datasets:
            for p in (self.p_curves, self.p_surf, self.p_prof):
                p.clear_all()
                p.canvas.draw_idle()
            return
        t0 = time.time()
        f = self._filters()
        self._build_surfaces()
        self._lookup = self._compute_lookup() if self.cb_lk.isChecked() else None
        try:
            self._plot_curves(f)
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(f"2D 绘图错误: {e}")
        self._auto_view(self.p_curves)
        try:
            self._plot_surface(f)
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(f"3D 绘图错误: {e}")
        self._auto_view(self.p_surf)
        try:
            self._plot_profiles(f)
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(f"剖面绘图错误: {e}")
        self._auto_view(self.p_prof)
        self._fill_table()
        lk_s = (lookupmod.summarize(self._lookup, unit=self._unit_str())
                if self._lookup else "查表未启用")
        self.statusBar().showMessage(
            f"刷新 {1000*(time.time()-t0):.0f} ms · {lk_s}")
        for p in (self.p_curves, self.p_surf, self.p_prof):
            p.canvas.draw_idle()

    # ---------------- 2D ----------------
    def _plot_curves(self, f):
        p = self.p_curves
        p.clear_all()
        ax = p.axes
        Lall = []
        for key in self.visible:
            sf = self._surf.get(key)
            if sf and sf["Ls"].size:
                Lall.extend(sf["Ls"].tolist())
        cmap = _getcmap(CMAPS[0])
        norm = Normalize(vmin=min(Lall), vmax=max(Lall)) if Lall else None
        drawn = 0
        cur = self._current_ds()
        for di, key in enumerate(sorted(self.visible)):
            ds = self.datasets.get(key)
            if ds is None:
                continue
            ls = LSTYLES[di % len(LSTYLES)]
            # 指标范围过滤只在“同类指标”上生效(其它单位的数据集仅作参考叠加)
            same_metric = (cur is not None and
                           getattr(cur, "metric", "") == ds.metric)
            for s in ds.series:
                x = s.x_c if s.x_c is not None else s.x
                y = s.y_c if s.y_c is not None else s.y
                if x is None or y is None or x.size < 2:
                    continue
                if s.param_um is not None and not (f["Lmin"] <= s.param_um <= f["Lmax"]):
                    continue
                m = (x >= f["xmin"]) & (x <= f["xmax"])
                if m.sum() < 2:
                    continue
                yd = self.ds_disp(ds, y[m])
                if same_metric:
                    mm = (yd >= f["gmin"]) & (yd <= f["gmax"])
                else:
                    mm = np.isfinite(yd)
                if mm.sum() < 2:
                    continue
                col = (cmap(norm(s.param_um)) if norm is not None
                       else cmap(0.55))
                ax.plot(x[m][mm], yd[mm], ls, color=col, lw=1.1)
                drawn += 1
        # 数据集图例
        for di, key in enumerate(sorted(self.visible)):
            ds = self.datasets.get(key)
            if ds is None:
                continue
            ax.plot([], [], LSTYLES[di % len(LSTYLES)], color="0.4",
                    label=f"{ds.file_group}·{ds.metric}")
        # 查表可行区 -> 红色竖条
        lk = self._lookup
        if lk and lk.ok:
            for r in lk.rows:
                ax.axvspan(r.x_lo, r.x_hi, color="red", alpha=0.08)
            sign = "≥" if lk.direction == "max" else "≤"
            ax.plot([], [], color="red", alpha=0.55, lw=4,
                    label=f"可行区 {sign} {lk.thr:.4g} {self._unit_str()}".rstrip())
        # 阈值参考线(显示域, 与当前指标单位一致)
        if lk is not None:
            ax.axhline(float(self.sp_thr.value()), color="crimson", ls=":",
                       lw=1.0)
        ax.set_xlabel(self._xlab() + ("  [log 轴]" if f["xlog"] else ""))
        ax.set_ylabel(self._ylab())
        ax.set_title(f"曲线族 · 每条曲线对应一个 L · 共 {drawn} 段")
        if f["xlog"]:
            ax.set_xscale("log")
        ax.grid(True, alpha=0.3)
        if norm is not None:
            sm = ScalarMappable(norm=norm, cmap=cmap)
            sm.set_array(np.array(Lall))
            p.set_colorbar(sm, "L (µm)", pad=0.02)
        else:
            p.clear_colorbar()
        leg = ax.legend(fontsize=8, loc="best", framealpha=0.6)
        if leg is not None:
            leg.set_draggable(True)
        if drawn == 0:
            ax.text(0.5, 0.5,
                    "当前过滤范围内没有可显示的曲线\n"
                    "(请放宽 gm/ID / L / 指标范围, 或检查 ② 清洗开关)",
                    ha="center", va="center", transform=ax.transAxes,
                    color="#888", fontsize=10)

    # ---------------- 3D ----------------
    def _plot_surface(self, f):
        p = self.p_surf
        # 记录用户上次旋转好的视角(避免每次刷新都复位成默认角度)
        prev_view = None
        try:
            prev_view = (float(p.axes.elev), float(p.axes.azim))
        except Exception:
            prev_view = None
        p.clear_all()
        ax = p.axes
        keys = sorted(self.visible)
        if not keys:
            p.clear_colorbar()
            ax.text2D(0.5, 0.5, "无可见数据集", ha="center",
                      transform=ax.transAxes)
            return
        any_ok = False
        for di, key in enumerate(keys):
            sf = self._surf.get(key)
            if sf is None or not np.isfinite(sf["Z"]).any():
                continue
            ds = self.datasets.get(key)
            Z = self.ds_disp(ds, sf["Z"]) if ds is not None else sf["Z"]
            Ls, xs = sf["Ls"], sf["xs"]
            # 显示面片抽稀: 3D 每帧渲染成本与面片数成正比, 栅格点数调大时
            # 旋转会变卡; 这里只抽稀“显示”, 数据网格/查表/等高线不受影响
            rstep = max(1, int(np.ceil(Ls.size / 40)))
            cstep = max(1, int(np.ceil(xs.size / 180)))
            if rstep > 1 or cstep > 1:
                Lsd, xsd = Ls[::rstep], xs[::cstep]
                Zd = Z[::rstep, ::cstep]
            else:
                Lsd, xsd, Zd = Ls, xs, Z
            Xd, Yd = np.meshgrid(xsd, Lsd)
            Zm = np.ma.masked_invalid(Zd)
            cmapname = CMAPS[di % len(CMAPS)]
            ds = self.datasets.get(key)
            name = f"{ds.file_group}·{ds.metric}" if ds else key
            alpha = 1.0 if len(keys) == 1 else 0.7
            # 面片多时关闭抗锯齿进一步提速(旋转中感知差别很小)
            aa = (Lsd.size - 1) * (xsd.size - 1) <= 9000
            ax.plot_surface(Xd, Yd, Zm, cmap=cmapname, alpha=alpha,
                            linewidth=0, antialiased=aa)
            if len(keys) == 1:
                sm = ScalarMappable(norm=Normalize(
                    vmin=float(np.nanmin(Z)), vmax=float(np.nanmax(Z))),
                    cmap=_getcmap(cmapname))
                sm.set_array(Zm)
                p.set_colorbar(sm, self._ylab(), shrink=0.7, pad=0.06)
            any_ok = True
        if len(keys) != 1:
            p.clear_colorbar()
        lk = self._lookup
        if lk and lk.ok and self.current_key in self._surf:
            csf = self._surf[self.current_key]
            cds = self.datasets.get(self.current_key)
            if cds is not None:
                Zd = self.ds_disp(cds, csf["Z"])
                try:
                    ax.contour(csf["xs"], csf["Ls"], Zd, levels=[lk.thr],
                               colors="red", linewidths=1.8)
                except Exception:
                    pass
        if not any_ok:
            ax.text2D(0.5, 0.5, "过滤范围内无有效曲面数据", ha="center",
                      transform=ax.transAxes)
        ax.set_xlabel(self._xlab() + ("  [log]" if f["xlog"] else ""))
        ax.set_ylabel("L (µm)" + ("  [log]" if f["Llog"] else ""))
        ax.set_zlabel(self._ylab())
        ax.set_title("三维曲面 z = 指标(gm/ID, L) · 红线 = 查表阈值边界")
        if prev_view is not None:
            try:
                ax.view_init(elev=prev_view[0], azim=prev_view[1])
            except Exception:
                pass
        else:
            try:
                ax.view_init(elev=24, azim=-125)
            except Exception:
                pass
        if f["Llog"]:
            ax.set_yscale("log")

    # ---------------- 等高线 + 剖面 ----------------
    def _plot_profiles(self, f):
        p = self.p_prof
        p.clear_all()
        axc, axp = p.axes, p.axes2
        sf = self._surf.get(self.current_key or "")
        if sf is None or not np.isfinite(sf["Z"]).any():
            p.clear_colorbar()
            axc.text(0.5, 0.5, "当前数据集在过滤范围内无曲面数据",
                     ha="center", va="center", transform=axc.transAxes)
            axp.text(0.5, 0.5, "(无)", ha="center", va="center",
                     transform=axp.transAxes)
            return
        ds = self.datasets.get(self.current_key or "")
        Z = self.ds_disp(ds, sf["Z"]) if ds is not None else sf["Z"]
        X, Y = np.meshgrid(sf["xs"], sf["Ls"])
        Zm = np.ma.masked_invalid(Z)
        nlev = 26
        cf = axc.contourf(X, Y, Zm, levels=nlev, cmap=CMAPS[0])
        axc.contour(X, Y, Zm, levels=nlev, colors="k", linewidths=0.3,
                    alpha=0.35)
        p.set_colorbar(cf, self._ylab(), pad=0.02)
        lk = self._lookup
        if lk and lk.ok:
            try:
                axc.contour(X, Y, Z, levels=[lk.thr], colors="red",
                            linewidths=1.8)
            except Exception:
                pass
        axc.set_xlabel(self._xlab() + ("  [log]" if f["xlog"] else ""))
        axc.set_ylabel("L (µm)")
        axc.set_title("等高线(颜色=指标; 红线=查表阈值边界)")
        if f["xlog"]:
            axc.set_xscale("log")
        if f["Llog"]:
            axc.set_yscale("log")

        # 下半: 固定 gm/ID -> 指标 vs L; 标注固定 L 处取值
        xfix = float(self.sp_fix_x.value())
        Ls, vals = surfmod.slice_at_x(sf["sers"], xfix)
        vd = self.ds_disp(ds, vals) if ds is not None else vals
        fin = np.isfinite(vd)
        if fin.any():
            axp.plot(Ls[fin], vd[fin], "o-", color="tab:blue", ms=4,
                     label=f"gm/ID = {xfix:g} 1/V 剖面")
        else:
            axp.text(0.5, 0.5,
                     f"固定 gm/ID = {xfix:g} 1/V 处没有有效数据\n"
                     "(超出各 L 的实测 gm/ID 覆盖范围, 或已被过滤)",
                     ha="center", va="center", transform=axp.transAxes,
                     color="#888", fontsize=9)
        Lf = float(self.sp_fix_L.value())
        if Ls.size:
            order = np.argsort(Ls)
            Lso, vdo = Ls[order], vd[order]
            ok = np.isfinite(vdo)
            if ok.sum() >= 2:
                Lso, vdo = Lso[ok], vdo[ok]
                if Lso.min() <= Lf <= Lso.max():
                    vf = float(np.interp(Lf, Lso, vdo))
                    axp.plot([Lf], [vf], "rs", ms=9,
                             label=f"L={Lf:g} µm → {vf:.2f}")
        axp.set_xlabel("L (µm)")
        axp.set_ylabel(self._ylab())
        axp.grid(True, alpha=0.3)
        if axp.get_legend_handles_labels()[0]:
            axp.legend(fontsize=8)
        if f["Llog"]:
            axp.set_xscale("log")

    def _fill_table(self):
        lk = self._lookup
        self.table.setRowCount(0)
        if not lk or not lk.ok:
            return
        ds = self._current_ds()
        sf = self._surf.get(self.current_key or "")
        rows = []
        for r in lk.rows:
            raw = float("nan")
            if sf is not None:
                try:
                    ri = int(np.argmin(np.abs(sf["Ls"] - r.L_um)))
                    ci = int(np.argmin(np.abs(sf["xs"] - r.x_rec)))
                    raw = float(sf["Z"][ri, ci])
                except Exception:
                    raw = float("nan")
            rows.append([r.L_um, r.x_lo, r.x_hi, r.x_rec, r.value_rec, raw,
                         r.n_pts])
        rows.sort(key=lambda t: (t[0], t[1]))
        self.table.setRowCount(len(rows))
        for i, rw in enumerate(rows):
            for j, val in enumerate(rw):
                if isinstance(val, float) and not np.isfinite(val):
                    txt = "-"
                else:
                    txt = fmt(val)
                it = QTableWidgetItem(txt)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, j, it)

    # ================= 导出 =================
    def _active_panel(self):
        i = self.tabs.currentIndex()
        if i == 1:
            return self.p_surf
        if i == 2:
            return self.p_prof
        return self.p_curves

    def _export_fig(self):
        fn, fl = QFileDialog.getSaveFileName(
            self, "导出当前视图", "gm_id_view.png",
            "PNG (*.png);;SVG (*.svg);;PDF (*.pdf)")
        if not fn:
            return
        try:
            self._active_panel().fig.savefig(fn, dpi=200, bbox_inches="tight")
            self.statusBar().showMessage(f"已导出: {fn}", 5000)
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _export_data(self):
        ds = self._current_ds()
        if ds is None:
            return
        fn, _ = QFileDialog.getSaveFileName(
            self, "导出当前数据集(清洗后)长表", f"{ds.metric}_cleaned.csv",
            "CSV (*.csv)")
        if not fn:
            return
        f = self._filters()
        unit = self._unit_str(ds)
        disp_hdr = f"value_display[{unit}]" if unit else "value_display"
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["L_um", "gm_id", "value_raw", disp_hdr])
            for s in ds.series:
                x = s.x_c if s.x_c is not None else s.x
                y = s.y_c if s.y_c is not None else s.y
                if x is None:
                    continue
                if s.param_um is not None and not (f["Lmin"] <= s.param_um <= f["Lmax"]):
                    continue
                m = (x >= f["xmin"]) & (x <= f["xmax"])
                xd, yd = x[m], y[m]
                dd = self.ds_disp(ds, yd)
                Ltxt = fmt(s.param_um) if s.param_um is not None else ""
                for xx, rv, dv in zip(xd, yd, dd):
                    w.writerow([Ltxt, fmt(xx), fmt(rv), fmt(dv)])
        self.statusBar().showMessage(f"已导出: {fn}", 5000)

    def _export_grid(self):
        sf = self._surf.get(self.current_key or "")
        if not sf:
            QMessageBox.information(self, "提示", "当前数据集没有有效曲面。")
            return
        fn, _ = QFileDialog.getSaveFileName(
            self, "导出公共栅格曲面(原始单位)", "metric_surface_grid.csv",
            "CSV (*.csv)")
        if not fn:
            return
        Z = sf["Z"]
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["gm_id"] + [f"L={fmt(l)}um" for l in sf["Ls"]])
            for j, xv in enumerate(sf["xs"]):
                w.writerow([fmt(xv)] + [
                    fmt(Z[r, j]) if np.isfinite(Z[r, j]) else ""
                    for r in range(Z.shape[0])])
        self.statusBar().showMessage(f"已导出: {fn}", 5000)

    def _export_lookup(self):
        lk = self._lookup
        if not lk or not lk.ok:
            QMessageBox.information(self, "提示", "当前没有查表结果。")
            return
        fn, _ = QFileDialog.getSaveFileName(self, "导出查表结果", "lookup.csv",
                                            "CSV (*.csv)")
        if not fn:
            return
        unit = self._unit_str()
        val_hdr = f"value_rec[{unit}]" if unit else "value_rec"
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["L_um", "gm_id_lo", "gm_id_hi", "gm_id_rec",
                        val_hdr])
            for r in sorted(lk.rows, key=lambda t: (t.L_um, t.x_lo)):
                w.writerow([r.L_um, r.x_lo, r.x_hi, r.x_rec,
                            r.value_rec])
        self.statusBar().showMessage(f"已导出: {fn}", 5000)

    def _about(self):
        QMessageBox.about(
            self, "gm/ID 设计数据浏览器",
            "把“gm/ID 为自变量、L 为参量”的指标曲线族转成三维曲面并做筛查。\n\n"
            "· 指标适配: 自增益(V/V↔dB)、fT(Hz)、Vdsat/Vgs/Vov(V)、\n"
            "  Inor/Id(A/m, A)、Cgg(F) 等按列头自动识别, 工程前缀自动选择,\n"
            "  阈值/过滤/Y 轴单位随当前指标联动; 查表方向默认 增益、fT 用\n"
            "  “≥”, 电压/电流类用“≤”, 可手动切换。\n"
            "· 自动识别 宽表 / 长表 / 多指标宽表 / 简单两列; 分隔符、编码、\n"
            "  L 单位(µm)自适应。\n"
            "· 数据清洗: 扫描回折剔除、Savgol 平滑、MAD 坏点剔除。\n"
            "· 反向查表: 阈值约束 → 可行 (gm/ID, L) 区间 + 推荐设计点,\n"
            "  3D/等高线红圈 = 阈值边界。\n\n"
            "操作: 打开文件 → 勾选数据集 → (调清洗) → 设阈值 → 3D 旋转查看。")
