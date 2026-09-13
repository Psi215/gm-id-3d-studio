# -*- coding: utf-8 -*-
"""
独立绘图窗口
============
* PlotWindow   : 一个参数 → 一个 2D 窗口, 拥有**自己的约束**(范围/对数轴/
  平滑/显示单位/查表阈值), 互不影响; 内置竖线/横线/取点测斜率; 查表结果
  表格在窗口底部。
* SurfaceWindow: 三维曲面窗口, **不常驻**, 由某个 2D 窗口中「三维曲面…」
  按钮打开; 默认继承该窗口的约束, 也可单独修改。
"""
from __future__ import annotations

import csv
import time

import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .interact import PlotInteractor
from .widgets import CMAPS, MplPanel, getcmap, mkspin


def fmt(x, sig=5):
    try:
        return f"{x:.{sig}g}"
    except Exception:
        return ""


class PlotWindow(QMainWindow):
    """单参数的 2D 曲线窗口(独立约束)。"""

    def __init__(self, session, metric, view, on_close=None):
        super().__init__()
        self.sess = session
        self.mt = metric
        self.view = view
        self.on_close = on_close
        self.surface_win = None
        self._series = []
        self._last_sig = None
        self._loading = False
        src = self.mt.source_label
        self.setWindowTitle(f"{metric.display} · {src} — 2D")
        self.resize(920, 640)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        self.refresh(force=True)

    # ---------------- UI ----------------
    def _build_ui(self):
        self.panel = MplPanel()
        self.interactor = PlotInteractor(self.panel.canvas, self._series_of,
                                         on_threshold=self._on_thr, parent=self)
        self.interactor.changed.connect(self._on_interact)

        right = QWidget(); right.setMinimumWidth(320)
        rl = QVBoxLayout(right); rl.setSpacing(6)

        g = QGroupBox("本窗口约束(独立于其它窗口)")
        v = QVBoxLayout(g)
        self.sp_xmin = mkspin(-1e12, 1e12, self.view.xmin)
        self.sp_xmax = mkspin(-1e12, 1e12, self.view.xmax)
        self.sp_Lmin = mkspin(0, 1e6, self.view.Lmin, 4)
        self.sp_Lmax = mkspin(0, 1e6, self.view.Lmax, 4)
        self.sp_ymin = mkspin(-1e12, 1e12, self.view.ymin)
        self.sp_ymax = mkspin(-1e12, 1e12, self.view.ymax)
        for lab, a, b in (("X 范围:", self.sp_xmin, self.sp_xmax),
                          ("L (µm):", self.sp_Lmin, self.sp_Lmax),
                          ("指标范围:", self.sp_ymin, self.sp_ymax)):
            row = QHBoxLayout()
            row.addWidget(QLabel(lab)); row.addWidget(a, 1)
            row.addWidget(QLabel("~")); row.addWidget(b, 1)
            v.addLayout(row)
        row = QHBoxLayout()
        self.cb_xlog = QCheckBox("X 对数"); self.cb_Llog = QCheckBox("L 对数")
        self.cb_xlog.setChecked(self.view.xlog)
        self.cb_Llog.setChecked(self.view.Llog)
        row.addWidget(self.cb_xlog); row.addWidget(self.cb_Llog)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("显示:"))
        self.cmb_disp = QComboBox()
        self.cmb_disp.addItems(["原始值(不换算)", "工程前缀", "dB(仅增益类)"])
        self.cmb_disp.setCurrentIndex(
            {"raw": 0, "prefix": 1, "dB": 2}[self.view.display_mode])
        row.addWidget(self.cmb_disp, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        self.cb_smooth = QCheckBox("平滑")
        self.cb_smooth.setChecked(bool(self.view.clean.get("smooth")))
        row.addWidget(self.cb_smooth)
        row.addWidget(QLabel("窗:"))
        self.sp_win = QSpinBox(); self.sp_win.setRange(3, 51)
        self.sp_win.setSingleStep(2)
        self.sp_win.setValue(int(self.view.clean.get("window", 9)))
        row.addWidget(self.sp_win)
        row.addWidget(QLabel("阶:"))
        self.sp_ord = QSpinBox(); self.sp_ord.setRange(1, 5)
        self.sp_ord.setValue(int(self.view.clean.get("order", 2)))
        row.addWidget(self.sp_ord)
        v.addLayout(row)
        row = QHBoxLayout()
        self.cb_lk = QCheckBox("查表约束")
        self.cb_lk.setChecked(self.view.lookup_on)
        row.addWidget(self.cb_lk)
        self.cmb_dir = QComboBox()
        self.cmb_dir.addItem("≥", "max"); self.cmb_dir.addItem("≤", "min")
        j = self.cmb_dir.findData(self.view.direction)
        if j >= 0:
            self.cmb_dir.setCurrentIndex(j)
        row.addWidget(self.cmb_dir)
        self.sp_thr = mkspin(-1e12, 1e12, self.view.thr)
        row.addWidget(self.sp_thr, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("自动范围"); b.clicked.connect(self._auto_range)
        row.addWidget(b)
        b = QPushButton("三维曲面…")
        b.setObjectName("primary"); b.clicked.connect(self.open_surface)
        row.addWidget(b)
        v.addLayout(row)
        rl.addWidget(g)

        g = QGroupBox("图上测量")
        v = QVBoxLayout(g)
        row = QHBoxLayout()
        for text, fn in (("＋ 竖线", lambda: self.interactor.add_cursor()),
                         ("＋ 横线", lambda: self.interactor.add_hcursor()),
                         ("清空游标", lambda: self.interactor.clear_cursors())):
            b = QPushButton(text); b.clicked.connect(fn); row.addWidget(b)
        v.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("测斜率(A→B)"); b.clicked.connect(
            lambda: self.interactor.start_measure())
        row.addWidget(b)
        b = QPushButton("清除测量"); b.clicked.connect(
            lambda: self.interactor.clear_measure())
        row.addWidget(b)
        v.addLayout(row)
        self.lb_measure = QLabel("竖线/横线交点值见下方读数")
        self.lb_measure.setWordWrap(True)
        self.lb_measure.setStyleSheet("color:#1e6fd9;")
        v.addWidget(self.lb_measure)
        rl.addWidget(g)

        g = QGroupBox("导出")
        v = QVBoxLayout(g)
        row = QHBoxLayout()
        for text, fn in (("图片…", self._export_fig),
                         ("数据 CSV…", self._export_csv),
                         ("查表 CSV…", self._export_lookup)):
            b = QPushButton(text); b.clicked.connect(fn); row.addWidget(b)
        v.addLayout(row)
        rl.addWidget(g)
        rl.addStretch(0)

        split = QWidget()
        hl = QHBoxLayout(split); hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.panel, 1); hl.addWidget(right)
        self.setCentralWidget(split)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["L (µm)", "可行区左 X", "可行区右 X", "推荐 X", "指标@推荐", "点数"])
        dock = QDockWidget("查表结果", self)
        dock.setWidget(self.table)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

        for w in (self.sp_xmin, self.sp_xmax, self.sp_Lmin, self.sp_Lmax,
                  self.sp_ymin, self.sp_ymax, self.sp_thr):
            w.valueChanged.connect(self._on_ctl)
        for w in (self.cb_xlog, self.cb_Llog, self.cb_lk, self.cb_smooth):
            w.toggled.connect(self._on_ctl)
        self.sp_win.valueChanged.connect(self._on_ctl)
        self.sp_ord.valueChanged.connect(self._on_ctl)
        self.cmb_disp.currentIndexChanged.connect(self._on_ctl)
        self.cmb_dir.currentIndexChanged.connect(self._on_ctl)
        self._sc = QShortcut(QKeySequence("Ctrl+R"), self)
        self._sc.activated.connect(self._auto_range)

    # ---------------- 约束 <-> 控件 ----------------
    def _on_ctl(self):
        if self._loading:
            return
        v = self.view
        v.xmin, v.xmax = self.sp_xmin.value(), self.sp_xmax.value()
        v.Lmin, v.Lmax = self.sp_Lmin.value(), self.sp_Lmax.value()
        v.ymin, v.ymax = self.sp_ymin.value(), self.sp_ymax.value()
        v.xlog, v.Llog = self.cb_xlog.isChecked(), self.cb_Llog.isChecked()
        v.display_mode = ["raw", "prefix", "dB"][self.cmb_disp.currentIndex()]
        v.clean.update(smooth=self.cb_smooth.isChecked(),
                       window=self.sp_win.value(),
                       order=self.sp_ord.value())
        v.lookup_on = self.cb_lk.isChecked()
        v.direction = self.cmb_dir.currentData()
        v.thr = self.sp_thr.value()
        self.sess.dirty("filters")
        unit = self.sess.unit_str(self.mt, view=v)
        for w in (self.sp_ymin, self.sp_ymax, self.sp_thr):
            w.setSuffix(f" {unit}" if unit else "")
        self._timer.start(120)

    def _sync_spins(self):
        self._loading = True
        v = self.view
        self.sp_xmin.setValue(v.xmin); self.sp_xmax.setValue(v.xmax)
        self.sp_Lmin.setValue(v.Lmin); self.sp_Lmax.setValue(v.Lmax)
        self.sp_ymin.setValue(v.ymin); self.sp_ymax.setValue(v.ymax)
        self.sp_thr.setValue(v.thr)
        self.cb_xlog.setChecked(v.xlog); self.cb_Llog.setChecked(v.Llog)
        self.cb_lk.setChecked(v.lookup_on)
        j = self.cmb_dir.findData(v.direction)
        if j >= 0:
            self.cmb_dir.setCurrentIndex(j)
        self.cmb_disp.setCurrentIndex(
            {"raw": 0, "prefix": 1, "dB": 2}[v.display_mode])
        self.cb_smooth.setChecked(bool(v.clean.get("smooth")))
        self._loading = False

    def _on_thr(self, value):
        self.view.thr = float(value)
        self._loading = True
        self.sp_thr.setValue(value)
        self._loading = False
        self.sess.dirty("filters")
        self._timer.start(80)

    def _on_interact(self):
        self.lb_measure.setText(self.interactor.summary() or "—")

    def _auto_range(self):
        self.sess.default_ranges(self.view, [self.mt])
        self._sync_spins()
        self.refresh(force=True)

    # ---------------- 绘制 ----------------
    def _series_of(self, idx):
        return self._series

    def _signature(self):
        v = self.view
        return (v.xmin, v.xmax, v.Lmin, v.Lmax, v.ymin, v.ymax, v.xlog,
                v.Llog, v.npts, v.display_mode, v.lookup_on, v.thr,
                v.direction, tuple(sorted(v.clean.items())),
                self.mt.display)

    def refresh(self, force=False):
        sig = self._signature()
        if not force and sig == self._last_sig:
            self.interactor.set_threshold(self.view.thr)
            self.interactor.on_replot()
            return
        self._last_sig = sig
        axis = self.panel.axes
        self.panel.clear_all()
        self._series = []
        v = self.view
        sers = self.sess.effective_series(self.mt, v)
        Ls = [l for (l, _, _) in sers if l is not None]
        norm = Normalize(vmin=min(Ls), vmax=max(Ls)) if Ls else None
        cmap = getcmap(CMAPS[0])
        for (l, x, y) in sers:
            if l is not None and not (v.Lmin <= l <= v.Lmax):
                continue
            mask = (x >= v.xmin) & (x <= v.xmax)
            if mask.sum() < 2:
                continue
            xd = x[mask]
            if float(np.ptp(xd)) <= 0:
                continue
            yd = self.sess.disp(self.mt, y[mask], view=v)
            mm = (yd >= v.ymin) & (yd <= v.ymax)
            if mm.sum() < 2:
                continue
            xs_, ys_ = xd[mm], yd[mm]
            if xs_.size > 3000:
                step = int(np.ceil(xs_.size / 3000))
                xs_, ys_ = xs_[::step], ys_[::step]
            axis.plot(xs_, ys_, color=(cmap(norm(l)) if norm is not None
                                       and l is not None else cmap(0.55)),
                      lw=1.1)
            self._series.append((np.asarray(xs_, float),
                                 np.asarray(ys_, float),
                                 (f"L={l:g}µm" if l is not None
                                  else self.mt.display)))
        if v.lookup_on:
            res = self.sess.lookup_of(self.mt, v)
            if res is not None and res.ok:
                for r in res.rows:
                    axis.axvspan(r.x_lo, r.x_hi, color="red", alpha=0.08)
                axis.axhline(v.thr, color="crimson", ls=":", lw=1.0)
        unit = self.sess.unit_str(self.mt, view=v)
        axis.set_xlabel(self.sess.x_label(v)
                        + ("  [log]" if v.xlog else ""))
        axis.set_ylabel(f"{self.mt.display}"
                        + (f" ({unit})" if unit else ""))
        axis.set_title(f"{self.mt.display} · {self.mt.source_label}"
                       + (f" · 平滑 {v.clean.get('window')}"
                          if v.clean.get("smooth") else ""))
        if v.xlog:
            axis.set_xscale("log")
        axis.grid(True, alpha=0.3)
        if norm is not None:
            sm = ScalarMappable(norm=norm, cmap=cmap)
            sm.set_array(np.array([norm.vmin, norm.vmax]))
            self.panel.set_colorbar(sm, "L (µm)", pad=0.02)
        else:
            self.panel.clear_colorbar()
        axis.relim(); axis.autoscale_view(); axis.margins(0.03, 0.05)
        self.interactor.set_threshold(v.thr)
        self.interactor.on_replot()
        self._fill_table()
        self._sync_spins()
        self.panel.canvas.draw_idle()

    def _fill_table(self):
        self.table.setRowCount(0)
        v = self.view
        if not v.lookup_on:
            return
        res = self.sess.lookup_of(self.mt, v)
        if res is None or not res.ok:
            return
        rows = sorted([[r.L_um, r.x_lo, r.x_hi, r.x_rec, r.value_rec,
                        r.n_pts] for r in res.rows],
                      key=lambda t: (t[0], t[1]))
        self.table.setRowCount(len(rows))
        for i, rw in enumerate(rows):
            for j, val in enumerate(rw):
                txt = "-" if (isinstance(val, float)
                              and not np.isfinite(val)) else fmt(val)
                it = QTableWidgetItem(txt)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, j, it)

    # ---------------- 三维窗口 ----------------
    def open_surface(self):
        if self.surface_win is None:
            self.surface_win = SurfaceWindow(self.sess, self.mt,
                                             self.view.copy(), owner=self)
        self.surface_win.refresh(force=True)
        self.surface_win.show()
        self.surface_win.raise_()

    # ---------------- 导出 ----------------
    def _export_fig(self):
        fn, _ = QFileDialog.getSaveFileName(self, "导出图片",
                                            f"{self.mt.base}_2d.png",
                                            "PNG (*.png);;SVG (*.svg);;PDF (*.pdf)")
        if fn:
            self.panel.fig.savefig(fn, dpi=200, bbox_inches="tight")

    def _export_csv(self):
        v = self.view
        fn, _ = QFileDialog.getSaveFileName(self, "导出曲线数据",
                                            f"{self.mt.base}_2d.csv",
                                            "CSV (*.csv)")
        if not fn:
            return
        unit = self.sess.unit_str(self.mt, view=v)
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["L_um", "x", "value_raw",
                        f"value_display[{unit}]" if unit else "value_display"])
            for (l, x, y) in self.sess.effective_series(self.mt, v):
                dd = self.sess.disp(self.mt, y, view=v)
                lt = fmt(l) if l is not None else ""
                for xx, rv, dv in zip(x, y, dd):
                    w.writerow([lt, fmt(xx), fmt(rv), fmt(dv)])

    def _export_lookup(self):
        res = self.sess.lookup_of(self.mt, self.view) \
            if self.view.lookup_on else None
        if res is None or not res.ok:
            QMessageBox.information(self, "提示", "当前无查表结果。")
            return
        fn, _ = QFileDialog.getSaveFileName(self, "导出查表结果",
                                            f"{self.mt.base}_lookup.csv",
                                            "CSV (*.csv)")
        if not fn:
            return
        with open(fn, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["L_um", "x_lo", "x_hi", "x_rec", "value_rec"])
            for r in sorted(res.rows, key=lambda t: (t.L_um, t.x_lo)):
                w.writerow([r.L_um, r.x_lo, r.x_hi, r.x_rec, r.value_rec])

    def closeEvent(self, ev):
        if self.surface_win is not None:
            self.surface_win.close()
        if self.on_close:
            self.on_close(self)
        super().closeEvent(ev)


class SurfaceWindow(QMainWindow):
    """三维曲面窗口(按需打开, 不常驻)。"""

    def __init__(self, session, metric, view, owner=None):
        super().__init__()
        self.sess = session
        self.mt = metric
        self.view = view
        self.owner = owner
        self._render = None
        self._low = False
        self.setWindowTitle(f"{metric.display} · 三维曲面 — {metric.source_label}")
        self.resize(1000, 720)
        self._build_ui()
        self.refresh(force=True)

    def _build_ui(self):
        self.panel = MplPanel(projection="3d", constrained=False)
        self.panel.canvas.mpl_connect("button_press_event", self._on_press)
        self.panel.canvas.mpl_connect("button_release_event", self._on_release)

        right = QWidget(); right.setMinimumWidth(260)
        rl = QVBoxLayout(right); rl.setSpacing(6)
        g = QGroupBox("三维视图约束")
        v = QVBoxLayout(g)
        self.sp_xmin = mkspin(-1e12, 1e12, self.view.xmin)
        self.sp_xmax = mkspin(-1e12, 1e12, self.view.xmax)
        self.sp_Lmin = mkspin(0, 1e6, self.view.Lmin, 4)
        self.sp_Lmax = mkspin(0, 1e6, self.view.Lmax, 4)
        for lab, a, b in (("X 范围:", self.sp_xmin, self.sp_xmax),
                          ("L (µm):", self.sp_Lmin, self.sp_Lmax)):
            row = QHBoxLayout()
            row.addWidget(QLabel(lab)); row.addWidget(a, 1)
            row.addWidget(QLabel("~")); row.addWidget(b, 1)
            v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("栅格:"))
        self.sp_npts = QSpinBox(); self.sp_npts.setRange(50, 1200)
        self.sp_npts.setValue(int(self.view.npts))
        row.addWidget(self.sp_npts)
        v.addLayout(row)
        row = QHBoxLayout()
        self.cb_lk = QCheckBox("阈值线")
        self.cb_lk.setChecked(self.view.lookup_on)
        row.addWidget(self.cb_lk)
        self.sp_thr = mkspin(-1e12, 1e12, self.view.thr)
        row.addWidget(self.sp_thr, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("⟲ 复位视角"); b.clicked.connect(self._reset)
        row.addWidget(b)
        b = QPushButton("与 2D 窗口同步")
        b.clicked.connect(self._sync_from_owner)
        row.addWidget(b)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("旋转:"))
        self.cmb_rot = QComboBox()
        for label, val in (("轨迹球", "trackball"), ("转台式", "azel"),
                           ("球面", "sphere"), ("弧球", "arcball")):
            self.cmb_rot.addItem(label, val)
        self.cmb_rot.currentIndexChanged.connect(self._on_rot)
        row.addWidget(self.cmb_rot, 1)
        v.addLayout(row)
        rl.addWidget(g)
        rl.addStretch(0)

        central = QWidget(); hl = QHBoxLayout(central)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.panel, 1); hl.addWidget(right)
        self.setCentralWidget(central)

        for w in (self.sp_xmin, self.sp_xmax, self.sp_Lmin, self.sp_Lmax,
                  self.sp_npts, self.sp_thr):
            w.valueChanged.connect(self._on_ctl)
        self.cb_lk.toggled.connect(self._on_ctl)

    def _on_ctl(self):
        v = self.view
        v.xmin, v.xmax = self.sp_xmin.value(), self.sp_xmax.value()
        v.Lmin, v.Lmax = self.sp_Lmin.value(), self.sp_Lmax.value()
        v.npts = self.sp_npts.value()
        v.lookup_on = self.cb_lk.isChecked()
        v.thr = self.sp_thr.value()
        self.sess.dirty("filters")
        self.refresh(force=True)

    def _sync_from_owner(self):
        if self.owner is None:
            return
        o = self.owner.view
        self.view.xmin, self.view.xmax = o.xmin, o.xmax
        self.view.Lmin, self.view.Lmax = o.Lmin, o.Lmax
        self.view.thr = o.thr
        self.view.lookup_on = o.lookup_on
        self.view.display_mode = o.display_mode
        self.sp_xmin.setValue(o.xmin); self.sp_xmax.setValue(o.xmax)
        self.sp_Lmin.setValue(o.Lmin); self.sp_Lmax.setValue(o.Lmax)
        self.sp_thr.setValue(o.thr); self.cb_lk.setChecked(o.lookup_on)
        self.refresh(force=True)

    def _on_rot(self):
        from matplotlib import rcParams
        try:
            rcParams["axes3d.mouserotationstyle"] = self.cmb_rot.currentData()
        except Exception:
            pass

    def _reset(self):
        try:
            self.panel.axes.view_init(elev=24.0, azim=-125.0, roll=0.0)
        except Exception:
            pass
        self.panel.auto_view()
        self.panel.canvas.draw_idle()

    # 旋转降级渲染
    def _on_press(self, ev):
        if self._render and not self._low and ev.inaxes is self.panel.axes:
            self._render_surface(low=True)

    def _on_release(self, ev):
        if self._render and self._low:
            self._render_surface(low=False)

    def _render_surface(self, low=False):
        info = self._render
        if not info:
            return
        ax = self.panel.axes
        Ls, xs, Z = info["Ls"], info["xs"], info["Z"]
        rows, cols = (12, 90) if low else (40, 180)
        rs = max(1, int(np.ceil(Ls.size / rows)))
        cs = max(1, int(np.ceil(xs.size / cols)))
        Lsd, xsd = Ls[::rs], xs[::cs]
        Zd = Z[::rs, ::cs]
        X, Y = np.meshgrid(xsd, Lsd)
        Zm = np.ma.masked_invalid(Zd)
        cells = (Lsd.size - 1) * (xsd.size - 1)
        old = info.get("coll")
        if old is not None:
            try:
                old.remove()
            except Exception:
                pass
        info["coll"] = ax.plot_surface(
            X, Y, Zm, cmap=CMAPS[0], alpha=1.0, linewidth=0,
            antialiased=(not low and cells <= 9000))
        self._low = bool(low)
        self.panel.canvas.draw_idle()

    def refresh(self, force=False):
        p = self.panel
        prev = None
        try:
            prev = (float(p.axes.elev), float(p.axes.azim))
        except Exception:
            pass
        p.clear_all()
        ax = p.axes
        v = self.view
        sf = self.sess.surface_of(self.mt, v)
        if sf is None or not np.isfinite(sf["Z"]).any():
            p.clear_colorbar()
            ax.text2D(0.5, 0.5, "当前约束下无曲面数据", ha="center",
                      transform=ax.transAxes)
            self._render = None
            return
        Z = self.sess.disp(self.mt, sf["Z"], view=v)
        self._render = {"Ls": sf["Ls"], "xs": sf["xs"], "Z": Z, "coll": None}
        self._render_surface(low=False)
        vlo, vhi = float(np.nanmin(Z)), float(np.nanmax(Z))
        if not np.isfinite(vlo) or not np.isfinite(vhi) or vhi - vlo <= 0:
            vlo, vhi = vlo - 1e-12, vlo + 1e-12
        sm = ScalarMappable(norm=Normalize(vmin=vlo, vmax=vhi),
                            cmap=getcmap(CMAPS[0]))
        sm.set_array(Z)
        unit = self.sess.unit_str(self.mt, view=v)
        p.set_colorbar(sm, f"{self.mt.display}"
                       + (f" ({unit})" if unit else ""), shrink=0.7, pad=0.06)
        if v.lookup_on:
            res = self.sess.lookup_of(self.mt, v)
            if res is not None and res.ok:
                try:
                    ax.contour(sf["xs"], sf["Ls"], Z, levels=[v.thr],
                               colors="red", linewidths=1.8)
                except Exception:
                    pass
        ax.set_xlabel(self.sess.x_label(v) + ("  [log]" if v.xlog else ""))
        ax.set_ylabel("L (µm)")
        ax.set_zlabel(f"{self.mt.display}"
                      + (f" ({unit})" if unit else ""))
        ax.set_title(f"{self.mt.display} · 三维曲面"
                     f" · 红线 = 阈值 {fmt(v.thr)} {unit}".rstrip())
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
        p.auto_view()
        p.canvas.draw_idle()
