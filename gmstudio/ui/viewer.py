# -*- coding: utf-8 -*-
"""主窗口: 左侧视图(2D 曲线族 / 3D 曲面 / 剖面等高线), 右侧参数与控制面板。"""
from __future__ import annotations

import csv
import os
import time

import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import session as sessmod
from .param_browser import ParamTree, SelectorWindow
from .theme import apply as apply_theme
from .widgets import CMAPS, MplPanel, getcmap, mkspin


def fmt(x, sig=5):
    try:
        return f"{x:.{sig}g}"
    except Exception:
        return ""


class StackedView(QWidget):
    """N 个参数各自一个子图、共享 X 轴的 2D 视图(数量变化时重建图)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QVBoxLayout as _L
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qtagg import (
            FigureCanvasQTAgg as _FC, NavigationToolbar2QT as _TB)
        self.fig = Figure(figsize=(8, 3.5), layout="constrained")
        self.canvas = _FC(self.fig)
        self._toolbar = _TB(self.canvas, self)
        lay = _L(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._toolbar)
        lay.addWidget(self.canvas)
        self.axes = []
        self.cbar_ax = None
        self.n = 0

    def set_count(self, n: int):
        if n == self.n and self.axes:
            for ax in self.axes:
                ax.clear()
            return
        for ax in list(self.fig.axes):
            self.fig.delaxes(ax)
        self.axes = []
        self.cbar_ax = None
        self.n = max(int(n), 1)
        gs = self.fig.add_gridspec(self.n, 1)
        for i in range(self.n):
            self.axes.append(self.fig.add_subplot(
                gs[i], sharex=(self.axes[0] if self.axes else None)))
    def set_colorbar(self, sm, label):
        if self.cbar_ax is None:
            cb = self.fig.colorbar(sm, ax=self.axes, pad=0.02)
            self.cbar_ax = cb.ax
        else:
            try:
                self.fig.colorbar(sm, cax=self.cbar_ax)
            except Exception:
                self.fig.delaxes(self.cbar_ax)
                self.cbar_ax = self.fig.colorbar(sm, ax=self.axes,
                                                 pad=0.02).ax
        self.cbar_ax.set_label(label)

    def clear_colorbar(self):
        if self.cbar_ax is not None:
            try:
                self.fig.delaxes(self.cbar_ax)
            except Exception:
                pass
            self.cbar_ax = None


class MainWindow(QMainWindow):
    def __init__(self, initial_files=None):
        super().__init__()
        self.setWindowTitle("gm/ID 设计数据工作室 · 全参数浏览与三维筛查")
        self.resize(1560, 940)
        self.sess = sessmod.Session()
        self.dark = False
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        self._build_ui()
        self._make_menu()
        self.statusBar().showMessage(
            "就绪: 打开 DC 全参数导出文件(total.csv 等), 右侧勾选参数即可实时查看")
        if initial_files:
            QTimer.singleShot(80, lambda: self.open_paths(initial_files))

    # ================= UI =================
    def _build_ui(self):
        # ---- 左: 视图 ----
        self.tabs = QTabWidget()
        self.stacked = StackedView()
        self.tabs.addTab(self.stacked, "曲线族 2D")
        self.p3d = MplPanel(projection="3d")
        self.tabs.addTab(self.p3d, "三维曲面 3D")
        self.pprof = MplPanel(nrows=2)
        bar = QWidget()
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(4, 2, 4, 0)
        hb.addWidget(QLabel("固定 X 剖面:"))
        self.sp_fix_x = mkspin(-1e9, 1e9, 1.0)
        hb.addWidget(self.sp_fix_x)
        hb.addWidget(QLabel("  标注 L (µm):"))
        self.sp_fix_L = mkspin(0, 1e6, 1.0, 4)
        hb.addWidget(self.sp_fix_L)
        hb.addStretch(1)
        tw = QWidget()
        vl = QVBoxLayout(tw)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(bar)
        vl.addWidget(self.pprof)
        self.tabs.addTab(tw, "剖面与等高线")

        # ---- 右: 面板 ----
        right = QWidget()
        right.setMinimumWidth(350)
        rl = QVBoxLayout(right)
        rl.setSpacing(6)

        g = QGroupBox("① 数据与参数(全部载入, 勾选才显示)")
        v = QVBoxLayout(g)
        row = QHBoxLayout()
        b = QPushButton("打开文件…"); b.clicked.connect(self._open_files)
        row.addWidget(b)
        b = QPushButton("打开文件夹…"); b.clicked.connect(self._open_dir)
        row.addWidget(b)
        v.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("参数选择窗口…"); b.setObjectName("primary")
        b.clicked.connect(self._open_selector)
        row.addWidget(b)
        b = QPushButton("清空数据"); b.clicked.connect(self._clear_all)
        row.addWidget(b)
        v.addLayout(row)
        self.tree = ParamTree(self.sess, on_changed=self._on_tree)
        v.addWidget(self.tree, 1)
        rl.addWidget(g, 3)

        g = QGroupBox("② 当前指标(X 轴 / 显示)")
        v = QVBoxLayout(g)
        row = QHBoxLayout()
        row.addWidget(QLabel("当前指标:"))
        self.cmb_active = QComboBox()
        row.addWidget(self.cmb_active, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("X 轴参数:"))
        self.cmb_x = QComboBox()
        row.addWidget(self.cmb_x, 1)
        v.addLayout(row)
        self.lb_xlab = QLabel("X 轴: (参数自带)")
        self.lb_xlab.setStyleSheet("color:#555;")
        v.addWidget(self.lb_xlab)
        row = QHBoxLayout()
        row.addWidget(QLabel("数值显示:"))
        self.cmb_disp = QComboBox()
        self.cmb_disp.addItems(["原始值(不换算)", "工程前缀", "dB(仅增益类)"])
        row.addWidget(self.cmb_disp, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        self.cb_xlog = QCheckBox("X 对数轴")
        self.cb_Llog = QCheckBox("L 对数轴")
        row.addWidget(self.cb_xlog)
        row.addWidget(self.cb_Llog)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("3D 旋转:"))
        self.cmb_rot = QComboBox()
        for label, val in (("轨迹球", "trackball"), ("转台式", "azel"),
                           ("球面", "sphere"), ("弧球", "arcball")):
            self.cmb_rot.addItem(label, val)
        self.cmb_rot.setCurrentIndex(0)
        row.addWidget(self.cmb_rot, 1)
        b = QPushButton("⟲ 3D 复位")
        b.clicked.connect(self._reset_3d)
        row.addWidget(b)
        v.addLayout(row)
        rl.addWidget(g)

        g = QGroupBox("③ 范围过滤")
        v = QVBoxLayout(g)
        self.sp_xmin = mkspin(-1e9, 1e9, 0.0)
        self.sp_xmax = mkspin(-1e9, 1e9, 30.0)
        self.sp_Lmin = mkspin(0, 1e6, 0.0, 4)
        self.sp_Lmax = mkspin(0, 1e6, 10.0, 4)
        self.sp_ymin = mkspin(-1e12, 1e12, 0.0)
        self.sp_ymax = mkspin(-1e12, 1e12, 100.0)
        for lab, a, b in (("X 范围:", self.sp_xmin, self.sp_xmax),
                          ("L (µm):", self.sp_Lmin, self.sp_Lmax),
                          ("指标范围:", self.sp_ymin, self.sp_ymax)):
            row = QHBoxLayout()
            row.addWidget(QLabel(lab))
            row.addWidget(a, 1); row.addWidget(QLabel("~")); row.addWidget(b, 1)
            v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("曲面栅格:"))
        self.sp_npts = QSpinBox()
        self.sp_npts.setRange(50, 1500); self.sp_npts.setValue(240)
        row.addWidget(self.sp_npts)
        b = QPushButton("自动范围")
        b.clicked.connect(self._auto_range)
        row.addWidget(b)
        v.addLayout(row)
        rl.addWidget(g)

        g = QGroupBox("④ 数据清洗(作用于勾选参数)")
        v = QVBoxLayout(g)
        self.cb_fold = QCheckBox("剔除扫描头部回折")
        self.cb_fold.setChecked(True)
        v.addWidget(self.cb_fold)
        self.cb_smooth = QCheckBox("Savitzky-Golay 平滑")
        v.addWidget(self.cb_smooth)
        row = QHBoxLayout()
        row.addWidget(QLabel("窗口:"))
        self.sp_swin = QSpinBox(); self.sp_swin.setRange(3, 51)
        self.sp_swin.setSingleStep(2); self.sp_swin.setValue(9)
        row.addWidget(self.sp_swin)
        row.addWidget(QLabel("阶:"))
        self.sp_sord = QSpinBox(); self.sp_sord.setRange(1, 5)
        self.sp_sord.setValue(2)
        row.addWidget(self.sp_sord)
        self.cb_outlier = QCheckBox("MAD 剔除")
        row.addWidget(self.cb_outlier)
        v.addLayout(row)
        rl.addWidget(g)

        g = QGroupBox("⑤ 反向查表(当前指标)")
        v = QVBoxLayout(g)
        self.cb_lk = QCheckBox("启用阈值约束")
        self.cb_lk.setChecked(True)
        v.addWidget(self.cb_lk)
        row = QHBoxLayout()
        row.addWidget(QLabel("方向:"))
        self.cmb_dir = QComboBox()
        self.cmb_dir.addItem("≥ (增益/fT)", "max")
        self.cmb_dir.addItem("≤ (电压/电流)", "min")
        row.addWidget(self.cmb_dir, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("阈值:"))
        self.sp_thr = mkspin(-1e12, 1e12, 50.0)
        row.addWidget(self.sp_thr, 1)
        v.addLayout(row)
        rl.addWidget(g)

        rl.addStretch(0)
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(right)

        # ---- 查表结果 ----
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["L (µm)", "可行区左 X", "可行区右 X", "推荐 X",
             "指标@推荐(显示)", "指标原始值", "栅格点数"])
        dock = QDockWidget("反向查表结果(当前指标)", self)
        dock.setWidget(self.table)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.tabs)
        split.addWidget(sa)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([1150, 380])
        self.setCentralWidget(split)

        # ---- 信号 ----
        for w in (self.cb_xlog, self.cb_Llog, self.cb_lk, self.cb_fold,
                  self.cb_smooth, self.cb_outlier):
            w.toggled.connect(self._on_ctl)
        for w in (self.sp_xmin, self.sp_xmax, self.sp_Lmin, self.sp_Lmax,
                  self.sp_ymin, self.sp_ymax, self.sp_npts, self.sp_thr,
                  self.sp_swin, self.sp_sord, self.sp_fix_x, self.sp_fix_L):
            w.valueChanged.connect(self._on_ctl)
        self.cmb_disp.currentIndexChanged.connect(self._on_ctl)
        self.cmb_dir.currentIndexChanged.connect(self._on_ctl)
        self.cmb_x.currentIndexChanged.connect(self._on_xsel)
        self.cmb_rot.currentIndexChanged.connect(self._on_rot)
        self.cmb_active.currentIndexChanged.connect(self._on_active)
        self._sc = QShortcut(QKeySequence("Ctrl+R"), self)
        self._sc.activated.connect(self._reset_3d)

    def _make_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("文件")
        m.addAction("打开文件…", self._open_files)
        m.addAction("打开文件夹…", self._open_dir)
        m.addAction("清空数据", self._clear_all)
        m.addSeparator()
        m.addAction("退出", self.close)
        m = mb.addMenu("视图")
        m.addAction("参数选择窗口", self._open_selector)
        m.addAction("切换深色主题", self._toggle_theme)
        m = mb.addMenu("导出")
        m.addAction("当前视图图片…", self._export_fig)
        m.addAction("当前指标 清洗后长表 (CSV)…", self._export_metric_csv)
        m.addAction("当前指标 曲面公共栅格 (CSV)…", self._export_grid)
        m.addAction("查表结果 (CSV)…", self._export_lookup)
        m.addAction("全部勾选参数 汇总长表 (CSV)…", self._export_all)
        m = mb.addMenu("帮助")
        m.addAction("关于 / 使用说明", self._about)

    # ================= 会话 <-> 控件 =================
    def _sync_from_session(self, fill_spins=False):
        self._loading = True
        am = self.sess.active_metric()
        # 单位后缀
        unit = self.sess.unit_str(am) or ""
        suffix = f" {unit}" if unit else ""
        for w in (self.sp_ymin, self.sp_ymax, self.sp_thr):
            w.setSuffix(suffix)
        # 当前指标 combo
        self.cmb_active.blockSignals(True)
        self.cmb_active.clear()
        for m in self.sess.checked_metrics():
            self.cmb_active.addItem(f"{m.source_label} · {m.display}", ())
        idx = -1
        for i, m in enumerate(self.sess.checked_metrics()):
            if m is am:
                idx = i
                break
        if idx >= 0:
            self.cmb_active.setCurrentIndex(idx)
        self.cmb_active.blockSignals(False)
        # X 轴参数选择器
        self.cmb_x.blockSignals(True)
        self.cmb_x.clear()
        self.cmb_x.addItem("(参数自带 X)", None)
        sel = -1
        for src in self.sess.sources.values():
            for m in src.sorted_metrics():
                key = src.path + "\u0001" + m.base
                self.cmb_x.addItem(f"{src.label} · {m.display}", key)
        if self.sess.x_metric is not None:
            sel = self.cmb_x.findData(self.sess.x_metric[0] + "\u0001"
                                      + self.sess.x_metric[1])
        if sel < 0:
            sel = 0
        self.cmb_x.setCurrentIndex(sel)
        self.cmb_x.blockSignals(False)
        self.lb_xlab.setText("X 轴: " + self.sess.x_label())
        # 查表方向默认
        if am is not None and am.profile is not None:
            j = self.cmb_dir.findData(am.profile.direction)
            if j >= 0:
                self.cmb_dir.setCurrentIndex(j)
        # 显示模式 -> 控件
        mode_i = {"raw": 0, "prefix": 1, "dB": 2}[self.sess.display_mode]
        self.cmb_disp.setCurrentIndex(mode_i)
        if fill_spins:
            if np.isfinite(self.sess.xmin):
                self.sp_xmin.setValue(self.sess.xmin)
            if np.isfinite(self.sess.xmax):
                self.sp_xmax.setValue(self.sess.xmax)
            self.sp_Lmin.setValue(self.sess.Lmin)
            self.sp_Lmax.setValue(self.sess.Lmax)
            if np.isfinite(self.sess.ymin):
                self.sp_ymin.setValue(self.sess.ymin)
            if np.isfinite(self.sess.ymax):
                self.sp_ymax.setValue(self.sess.ymax)
            self.sp_npts.setValue(self.sess.npts)
            if np.isfinite(self.sess.thr):
                self.sp_thr.setValue(self.sess.thr)
        self.cb_xlog.setChecked(self.sess.xlog)
        self.cb_Llog.setChecked(self.sess.Llog)
        self._loading = False

    def _on_tree(self):
        self._sync_from_session(fill_spins=True)
        self._rebuild_tree_views()
        self.refresh()

    def _rebuild_tree_views(self):
        self.tree.rebuild()
        if self._selector is not None:
            self._selector.refresh()

    _selector = None

    def _open_selector(self):
        if self._selector is None:
            self._selector = SelectorWindow(self.sess,
                                            on_changed=self._on_tree)
        self._selector.refresh()
        self._selector.show()
        self._selector.raise_()

    def _on_ctl(self):
        if self._loading:
            return
        self.sess.xmin = self.sp_xmin.value()
        self.sess.xmax = self.sp_xmax.value()
        self.sess.Lmin = self.sp_Lmin.value()
        self.sess.Lmax = self.sp_Lmax.value()
        self.sess.ymin = self.sp_ymin.value()
        self.sess.ymax = self.sp_ymax.value()
        self.sess.npts = self.sp_npts.value()
        self.sess.thr = self.sp_thr.value()
        self.sess.xlog = self.cb_xlog.isChecked()
        self.sess.Llog = self.cb_Llog.isChecked()
        self.sess.lookup_on = self.cb_lk.isChecked()
        self.sess.direction = self.cmb_dir.currentData()
        mode = ["raw", "prefix", "dB"][self.cmb_disp.currentIndex()]
        self.sess.display_mode = mode
        self.sess.clean.update(
            drop_fold=self.cb_fold.isChecked(),
            smooth=self.cb_smooth.isChecked(),
            window=self.sp_swin.value(),
            order=self.sp_sord.value(),
            outlier=self.cb_outlier.isChecked())
        self.sess.dirty()
        self._sync_from_session(fill_spins=False)
        self._timer.start(120)

    def _on_active(self):
        if self._loading:
            return
        i = self.cmb_active.currentIndex()
        ms = self.sess.checked_metrics()
        if 0 <= i < len(ms):
            m = ms[i]
            path = None
            for p, src in self.sess.sources.items():
                if m.base in src.metrics and m.source_label == src.label:
                    path = p
                    break
            if path:
                self.sess.set_active(path, m.base)
                self._sync_from_session(fill_spins=False)
                self.refresh()

    def _on_xsel(self):
        """用户选择 X 轴参数(默认 gmid 之类) -> 重配对并重绘。"""
        if self._loading:
            return
        data = self.cmb_x.currentData()
        if data:
            path, base = str(data).split("\u0001", 1)
            self.sess.x_metric = (path, base)
        else:
            self.sess.x_metric = None
        self.sess.dirty()
        self._auto_range()
        self._sync_from_session(fill_spins=False)
        self.refresh()

    def _on_rot(self):
        from matplotlib import rcParams
        try:
            rcParams["axes3d.mouserotationstyle"] = self.cmb_rot.currentData()
        except Exception:
            pass

    def _toggle_theme(self):
        from PySide6.QtWidgets import QApplication
        self.dark = not self.dark
        apply_theme(QApplication.instance(), self.dark)

    def _reset_3d(self):
        try:
            self.p3d.axes.view_init(elev=24.0, azim=-125.0, roll=0.0)
        except Exception:
            pass
        self.p3d.auto_view()
        self.p3d.canvas.draw_idle()

    # ================= 数据装载 =================
    def _open_files(self):
        fs, _ = QFileDialog.getOpenFileNames(
            self, "选择数据文件(total.csv / selfgain 等)", "",
            "数据文件 (*.csv *.txt *.dat *.tsv);;所有文件 (*)")
        if fs:
            self.open_paths(fs)

    def _open_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择数据文件夹")
        if d:
            self.open_paths([d])

    def open_paths(self, paths):
        from ..core.loader import load_files
        t0 = time.time()
        sources, errs = load_files(paths)
        if not sources and not errs:
            QMessageBox.information(self, "提示", "没有找到数据文件。")
            return
        for src in sources.values():
            self.sess.add_source(src)
        # 默认 X 轴: 若数据里有 gmid 类参数(gmoverid 等)自动选用
        if self.sess.x_metric is None:
            for path, src in self.sess.sources.items():
                for m in src.sorted_metrics():
                    if getattr(m.profile, "key", None) == "gmid":
                        self.sess.x_metric = (path, m.base)
                        break
                else:
                    continue
                break
        n_metrics = sum(len(s.metrics) for s in sources.values())
        msg = f"已载入 {len(sources)} 个文件 / {n_metrics} 个参数 "
        msg += f"({time.time()-t0:.2f} s), 全部驻留内存; 勾选后实时显示"
        if errs:
            msg += f"; {len(errs)} 个文件失败(见状态栏)"
            print("load errors:", errs)
        self.statusBar().showMessage(msg, 9000)
        self._auto_range()
        self._sync_from_session(fill_spins=True)
        self._rebuild_tree_views()
        self.refresh()

    def _clear_all(self):
        self.sess.remove_all()
        self._sync_from_session(fill_spins=True)
        self._rebuild_tree_views()
        self.refresh()

    def _auto_range(self):
        self.sess.default_ranges()
        self._sync_from_session(fill_spins=True)

    # ================= 刷新绘图 =================
    def refresh(self):
        t0 = time.time()
        metrics = self.sess.checked_metrics()
        am = self.sess.active_metric()
        for m in metrics:
            self.sess.clean_metric(m)
        try:
            self._plot_2d(metrics, am)
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(f"2D 绘图错误: {e}")
        try:
            self._plot_3d(am)
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(f"3D 绘图错误: {e}")
        try:
            self._plot_profile(am)
        except Exception as e:  # noqa: BLE001
            self.statusBar().showMessage(f"剖面绘图错误: {e}")
        self._fill_table(am)
        self._sync_from_session(fill_spins=False)
        self.statusBar().showMessage(
            f"刷新 {1000*(time.time()-t0):.0f} ms · 显示 {len(metrics)} 个参数"
            + (f" · 当前 {am.display}" if am is not None else ""))
        for p in (self.stacked, self.p3d, self.pprof):
            p.canvas.draw_idle()

    def _global_Lnorm(self, metrics):
        Ls = []
        for m in metrics:
            for c in m.curves:
                if c.L_um is not None:
                    Ls.append(c.L_um)
        if not Ls:
            return None
        return Normalize(vmin=min(Ls), vmax=max(Ls))

    def _plot_2d(self, metrics, am):
        sv = self.stacked
        sv.set_count(len(metrics) or 1)
        norm = self._global_Lnorm(metrics)
        cmap = getcmap(CMAPS[0])
        if not metrics:
            sv.clear_colorbar()
            sv.axes[0].clear()
            sv.axes[0].text(0.5, 0.5, "请在右侧勾选要查看的参数",
                            ha="center", va="center",
                            transform=sv.axes[0].transAxes, color="#888")
            return
        for i, m in enumerate(metrics):
            ax = sv.axes[i]
            ax.clear()
            for (l, x, y) in self.sess.effective_series(m):
                if l is not None and not (self.sess.Lmin <= l <= self.sess.Lmax):
                    continue
                mask = (x >= self.sess.xmin) & (x <= self.sess.xmax)
                if mask.sum() < 2:
                    continue
                xd = x[mask]
                if float(np.ptp(xd)) <= 0:      # 常数 X 曲线(如参数自带值)
                    continue
                yd = self.sess.disp(m, y[mask])
                mm = (yd >= self.sess.ymin) & (yd <= self.sess.ymax)
                if mm.sum() < 2:
                    continue
                col = cmap(norm(l)) if norm is not None and l is not None \
                    else cmap(0.55)
                ax.plot(xd[mm], yd[mm], color=col, lw=1.1)
            if m is am and self.sess.lookup_on:
                res = self.sess.lookup_of(m)
                if res is not None and res.ok:
                    for r in res.rows:
                        ax.axvspan(r.x_lo, r.x_hi, color="red", alpha=0.08)
                    ax.axhline(self.sess.thr, color="crimson", ls=":",
                               lw=1.0)
            unit = self.sess.unit_str(m) or ""
            ax.set_ylabel(f"{m.display}" + (f" ({unit})" if unit else ""))
            ax.grid(True, alpha=0.3)
        sv.axes[-1].set_xlabel(self.sess.x_label())
        if self.sess.xlog:
            for ax in sv.axes:
                ax.set_xscale("log")
        if norm is not None:
            sm = ScalarMappable(norm=norm, cmap=cmap)
            sm.set_array(np.array([norm.vmin, norm.vmax]))
            sv.set_colorbar(sm, "L (µm)")
        else:
            sv.clear_colorbar()
        sv.fig.suptitle("曲线族 · 每个子图一个参数 · 颜色 = L",
                        fontsize=11, color="#33405c")
        for ax in sv.axes:
            ax.relim()
            ax.autoscale_view()
            ax.margins(0.03, 0.05)

    def _plot_3d(self, am):
        p = self.p3d
        prev = None
        try:
            prev = (float(p.axes.elev), float(p.axes.azim))
        except Exception:
            pass
        p.clear_all()
        ax = p.axes
        if am is None:
            p.clear_colorbar()
            ax.text2D(0.5, 0.5, "请先勾选参数", ha="center",
                      transform=ax.transAxes)
            return
        sf = self.sess.surface_of(am)
        if sf is None or not np.isfinite(sf["Z"]).any():
            p.clear_colorbar()
            ax.text2D(0.5, 0.5, "当前过滤范围内无曲面数据", ha="center",
                      transform=ax.transAxes)
            return
        Z = self.sess.disp(am, sf["Z"])
        Ls, xs = sf["Ls"], sf["xs"]
        rstep = max(1, int(np.ceil(Ls.size / 40)))
        cstep = max(1, int(np.ceil(xs.size / 180)))
        Lsd, xsd = (Ls[::rstep], xs[::cstep]) if (rstep > 1 or cstep > 1) \
            else (Ls, xs)
        Zd = Z[::rstep, ::cstep] if (rstep > 1 or cstep > 1) else Z
        Xd, Yd = np.meshgrid(xsd, Lsd)
        Zm = np.ma.masked_invalid(Zd)
        cells = (Lsd.size - 1) * (xsd.size - 1)
        ax.plot_surface(Xd, Yd, Zm, cmap=CMAPS[0], alpha=1.0,
                        linewidth=0, antialiased=(cells <= 9000))
        vlo, vhi = float(np.nanmin(Z)), float(np.nanmax(Z))
        if not np.isfinite(vlo) or not np.isfinite(vhi) or vhi - vlo <= 0:
            vlo, vhi = vlo - 1e-12 if np.isfinite(vlo) else 0.0, \
                vlo + 1e-12 if np.isfinite(vlo) else 1.0
        sm = ScalarMappable(norm=Normalize(vmin=vlo, vmax=vhi),
                            cmap=getcmap(CMAPS[0]))
        sm.set_array(Zm)
        unit = self.sess.unit_str(am) or ""
        p.set_colorbar(sm, f"{am.display}" + (f" ({unit})" if unit else ""),
                       shrink=0.7, pad=0.06)
        if self.sess.lookup_on:
            res = self.sess.lookup_of(am)
            if res is not None and res.ok:
                try:
                    ax.contour(xs, Ls, Z, levels=[self.sess.thr],
                               colors="red", linewidths=1.8)
                except Exception:
                    pass
        ax.set_xlabel(self.sess.x_label() + ("  [log]" if self.sess.xlog else ""))
        ax.set_ylabel("L (µm)" + ("  [log]" if self.sess.Llog else ""))
        ax.set_zlabel(f"{am.display}"
                      + (f" ({unit})" if unit else ""))
        ax.set_title(f"三维曲面 · {am.display} · 红线 = 查表阈值边界")
        if prev is not None:
            try:
                ax.view_init(elev=prev[0], azim=prev[1])
            except Exception:
                pass
        else:
            try:
                ax.view_init(elev=24, azim=-125)
            except Exception:
                pass
        if self.sess.Llog:
            ax.set_yscale("log")
        p.auto_view()

    def _plot_profile(self, am):
        p = self.pprof
        p.clear_all()
        axc, axp = p.axes, p.axes2
        if am is None:
            p.clear_colorbar()
            axc.text(0.5, 0.5, "请先勾选参数", ha="center", va="center",
                     transform=axc.transAxes)
            return
        sf = self.sess.surface_of(am)
        if sf is None or not np.isfinite(sf["Z"]).any():
            p.clear_colorbar()
            axc.text(0.5, 0.5, "无曲面数据", ha="center", va="center",
                     transform=axc.transAxes)
            return
        Z = self.sess.disp(am, sf["Z"])
        X, Y = np.meshgrid(sf["xs"], sf["Ls"])
        Zm = np.ma.masked_invalid(Z)
        nlev = 26
        cf = axc.contourf(X, Y, Zm, levels=nlev, cmap=CMAPS[0])
        axc.contour(X, Y, Zm, levels=nlev, colors="k", linewidths=0.3,
                    alpha=0.35)
        unit = self.sess.unit_str(am) or ""
        p.set_colorbar(cf, f"{am.display}"
                       + (f" ({unit})" if unit else ""), pad=0.02)
        if self.sess.lookup_on:
            res = self.sess.lookup_of(am)
            if res is not None and res.ok:
                try:
                    axc.contour(X, Y, Z, levels=[self.sess.thr],
                                colors="red", linewidths=1.8)
                except Exception:
                    pass
        axc.set_xlabel(self.sess.x_label() + ("  [log]" if self.sess.xlog else ""))
        axc.set_ylabel("L (µm)")
        axc.set_title(f"等高线 · {am.display} · 红线 = 阈值边界")
        if self.sess.xlog:
            axc.set_xscale("log")
        if self.sess.Llog:
            axc.set_yscale("log")

        xfix = float(self.sp_fix_x.value())
        Ls2, vals = [], []
        for (l, x, y) in sf["sers"]:
            if xfix < x.min() or xfix > x.max() or float(np.ptp(x)) <= 0:
                Ls2.append(l); vals.append(np.nan)
                continue
            from scipy.interpolate import PchipInterpolator
            try:
                p2 = PchipInterpolator(x, y, extrapolate=False)
                v = float(p2(xfix))
            except Exception:
                v = np.nan
            Ls2.append(l)
            vals.append(v)
        Ls2 = np.array(Ls2, float)
        vd = self.sess.disp(am, np.array(vals, float))
        fin = np.isfinite(vd)
        if fin.any():
            axp.plot(Ls2[fin], vd[fin], "o-", color="tab:blue", ms=4,
                     label=f"{self.sess.x_label()} = {xfix:g} 剖面")
        else:
            axp.text(0.5, 0.5, f"{self.sess.x_label()} = {xfix:g} 处无有效数据",
                     ha="center", va="center", transform=axp.transAxes,
                     color="#888")
        Lf = float(self.sp_fix_L.value())
        if fin.sum() >= 2:
            order = np.argsort(Ls2[fin])
            Lso, vdo = Ls2[fin][order], vd[fin][order]
            if Lso.min() <= Lf <= Lso.max():
                vf = float(np.interp(Lf, Lso, vdo))
                axp.plot([Lf], [vf], "rs", ms=9,
                         label=f"L={Lf:g} µm → {vf:.3g}")
        axp.set_xlabel("L (µm)")
        axp.set_ylabel(f"{am.display}" + (f" ({unit})" if unit else ""))
        axp.grid(True, alpha=0.3)
        if axp.get_legend_handles_labels()[0]:
            axp.legend(fontsize=8)
        if self.sess.Llog:
            axp.set_xscale("log")
        for ax in (axc, axp):
            try:
                ax.relim()
                ax.autoscale_view()
                ax.margins(0.03, 0.05)
            except Exception:
                pass

    def _fill_table(self, am):
        self.table.setRowCount(0)
        if am is None or not self.sess.lookup_on:
            return
        res = self.sess.lookup_of(am)
        if res is None or not res.ok:
            return
        sf = self.sess.surface_of(am)
        rows = []
        for r in res.rows:
            raw = float("nan")
            if sf is not None:
                try:
                    ri = int(np.argmin(np.abs(sf["Ls"] - r.L_um)))
                    ci = int(np.argmin(np.abs(sf["xs"] - r.x_rec)))
                    raw = float(sf["Z"][ri, ci])
                except Exception:
                    pass
            rows.append([r.L_um, r.x_lo, r.x_hi, r.x_rec, r.value_rec,
                         raw, r.n_pts])
        rows.sort(key=lambda t: (t[0], t[1]))
        self.table.setRowCount(len(rows))
        for i, rw in enumerate(rows):
            for j, val in enumerate(rw):
                txt = "-" if (isinstance(val, float)
                              and not np.isfinite(val)) else fmt(val)
                it = QTableWidgetItem(txt)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, j, it)

    # ================= 导出 =================
    def _active_panel(self):
        i = self.tabs.currentIndex()
        return (self.stacked, self.p3d, self.pprof)[i] if i < 3 \
            else self.stacked

    def _export_fig(self):
        fn, _ = QFileDialog.getSaveFileName(self, "导出当前视图",
                                            "gm_id_view.png",
                                            "PNG (*.png);;SVG (*.svg);;PDF (*.pdf)")
        if not fn:
            return
        try:
            self._active_panel().fig.savefig(fn, dpi=200,
                                             bbox_inches="tight")
            self.statusBar().showMessage(f"已导出: {fn}", 5000)
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    def _export_metric_csv(self):
        am = self.sess.active_metric()
        if am is None:
            return
        fn, _ = QFileDialog.getSaveFileName(
            self, "导出当前指标(清洗后)长表", f"{am.display}_cleaned.csv",
            "CSV (*.csv)")
        if not fn:
            return
        unit = self.sess.unit_str(am) or ""
        xhdr = self.sess.x_label().replace(" ", "_")
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["L_um", f"x[{xhdr}]", "value_raw",
                        f"value_display[{unit}]" if unit else "value_display"])
            for (l, x, y) in self.sess.effective_series(am):
                if l is not None and not (self.sess.Lmin <= l <= self.sess.Lmax):
                    continue
                mask = (x >= self.sess.xmin) & (x <= self.sess.xmax)
                if mask.sum() == 0:
                    continue
                xd, yd = x[mask], y[mask]
                dd = self.sess.disp(am, yd)
                Ltxt = fmt(l) if l is not None else ""
                for xx, rv, dv in zip(xd, yd, dd):
                    w.writerow([Ltxt, fmt(xx), fmt(rv), fmt(dv)])
        self.statusBar().showMessage(f"已导出: {fn}", 5000)

    def _export_grid(self):
        am = self.sess.active_metric()
        if am is None:
            return
        sf = self.sess.surface_of(am)
        if sf is None:
            QMessageBox.information(self, "提示", "当前指标无有效曲面。")
            return
        fn, _ = QFileDialog.getSaveFileName(self, "导出曲面公共栅格(原始值)",
                                            f"{am.display}_grid.csv",
                                            "CSV (*.csv)")
        if not fn:
            return
        Z = sf["Z"]
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["x"] + [f"L={fmt(l)}um" for l in sf["Ls"]])
            for j, xv in enumerate(sf["xs"]):
                w.writerow([fmt(xv)] + [
                    fmt(Z[r, j]) if np.isfinite(Z[r, j]) else ""
                    for r in range(Z.shape[0])])
        self.statusBar().showMessage(f"已导出: {fn}", 5000)

    def _export_lookup(self):
        am = self.sess.active_metric()
        if am is None:
            return
        res = self.sess.lookup_of(am)
        if res is None or not res.ok:
            QMessageBox.information(self, "提示", "当前无查表结果。")
            return
        fn, _ = QFileDialog.getSaveFileName(self, "导出查表结果",
                                            "lookup.csv", "CSV (*.csv)")
        if not fn:
            return
        unit = self.sess.unit_str(am) or ""
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["L_um", "x_lo", "x_hi", "x_rec",
                        f"value_rec[{unit}]" if unit else "value_rec"])
            for r in sorted(res.rows, key=lambda t: (t.L_um, t.x_lo)):
                w.writerow([r.L_um, r.x_lo, r.x_hi, r.x_rec, r.value_rec])
        self.statusBar().showMessage(f"已导出: {fn}", 5000)

    def _export_all(self):
        metrics = self.sess.checked_metrics()
        if not metrics:
            return
        fn, _ = QFileDialog.getSaveFileName(
            self, "导出全部勾选参数汇总长表", "all_metrics.csv", "CSV (*.csv)")
        if not fn:
            return
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "metric", "L_um", "x", "value_raw"])
            for m in metrics:
                for (l, x, y) in self.sess.effective_series(m):
                    if l is not None and not (self.sess.Lmin <= l <= self.sess.Lmax):
                        continue
                    mask = (x >= self.sess.xmin) & (x <= self.sess.xmax)
                    for xx, vv in zip(x[mask], y[mask]):
                        w.writerow([m.source_label, m.base,
                                    fmt(l) if l is not None else "",
                                    fmt(xx), fmt(vv)])
        self.statusBar().showMessage(f"已导出: {fn}", 5000)

    def _about(self):
        QMessageBox.about(
            self, "gm/ID 设计数据工作室",
            "一次导入 DC 全参数导出文件(如 total.csv, 114 参数 × 15 L),\n"
            "全部数据驻留内存; 在右侧参数树(或独立选择窗口)实时勾选\n"
            "要查看的参数, 曲线族/3D 曲面/等高线即时更新。\n\n"
            "· 显示默认使用原始数值(不换算单位); 可切工程前缀或 dB;\n"
            "· 双击参数名可重命名(持久化到 <文件>.meta.json);\n"
            "· 反向查表方向 ≥/≤ 与阈值单位跟随当前参数;\n"
            "· Ctrl+R 复位 3D 视角。")
