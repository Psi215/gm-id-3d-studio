# -*- coding: utf-8 -*-
"""
主窗口 = 控制台
===============
* 库管理(勾选即加载) + 参数树(勾选即**打开该参数的独立 2D 窗口**);
* 每个绘图窗口拥有自己的约束(范围/对数轴/平滑/显示单位/查表阈值), 互不影响;
* 三维曲面不常驻: 在任意 2D 窗口里点「三维曲面…」按需打开;
* 主窗口里的「默认约束」只作为**新建窗口的初值**, 也可一键推给所有窗口。
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from ..core import session as sessmod
from ..core.library import Library
from .library_panel import LibraryPanel
from .param_browser import ParamTree, SelectorWindow
from .plot_window import PlotWindow
from .theme import apply as apply_theme
from .widgets import install_no_wheel_filter, mkspin


class MainWindow(QMainWindow):
    def __init__(self, initial_files=None, restore: bool = True):
        super().__init__()
        self.setWindowTitle("gm/ID 设计数据工作室 · 控制台")
        self.resize(1180, 820)
        self.sess = sessmod.Session()
        self.library = Library()
        self.windows: dict[tuple, PlotWindow] = {}
        self.wheel_filter = install_no_wheel_filter()
        self.dark = False
        self._loading = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_session)
        self._build_ui()
        self._make_menu()
        self.statusBar().showMessage(
            "控制台就绪: 库里勾选数据 → 参数树勾选参数 = 打开该参数的独立绘图窗口")
        if initial_files:
            QTimer.singleShot(80, lambda: self.open_paths(initial_files))
        elif restore:
            QTimer.singleShot(120, self._restore_session)

    # ================= UI =================
    def _build_ui(self):
        # ---- 左: 打开的窗口 + 提示 ----
        left = QWidget(); ll = QVBoxLayout(left)
        g = QGroupBox("打开的绘图窗口(双击置前)")
        v = QVBoxLayout(g)
        self.lst_wins = QListWidget()
        self.lst_wins.itemDoubleClicked.connect(self._raise_win)
        v.addWidget(self.lst_wins, 1)
        row = QHBoxLayout()
        b = QPushButton("全部置前"); b.clicked.connect(self._raise_all)
        row.addWidget(b)
        b = QPushButton("全部关闭"); b.clicked.connect(self.close_all_windows)
        row.addWidget(b)
        b = QPushButton("全部重绘"); b.clicked.connect(lambda: self.refresh(True))
        row.addWidget(b)
        v.addLayout(row)
        ll.addWidget(g, 1)
        g = QGroupBox("用法")
        v = QVBoxLayout(g)
        hint = QLabel(
            "1) 「库」导入数据文件 → 勾选即加载(不必每次导入)\n"
            "2) 「参数」树勾选/双击 = 打开该参数的独立 2D 窗口\n"
            "3) 每个窗口有自己的范围、对数轴、平滑、显示单位、查表阈值\n"
            "4) 窗口里「三维曲面…」按需打开 3D 窗口(不常驻)\n"
            "5) 窗口内: ＋竖线/＋横线 可拖动看交点值; 测斜率(A→B) 取两点\n"
            "6) Ctrl+R 窗口内自动范围; 主窗口默认约束只影响新建窗口")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#555;")
        v.addWidget(hint)
        ll.addWidget(g)
        left.setMinimumWidth(300)

        # ---- 右: 控制面板 ----
        right = QWidget(); right.setMinimumWidth(360)
        rl = QVBoxLayout(right); rl.setSpacing(6)

        g = QGroupBox("⓪ 数据库(勾选即加载)")
        v = QVBoxLayout(g)
        self.lib_panel = LibraryPanel(self.library, on_load=self._lib_load,
                                      on_unload=self._lib_unload)
        v.addWidget(self.lib_panel)
        rl.addWidget(g)

        g = QGroupBox("① 参数(勾选/双击 = 打开独立窗口)")
        v = QVBoxLayout(g)
        row = QHBoxLayout()
        b = QPushButton("打开选中为窗口")
        b.setObjectName("primary"); b.clicked.connect(self._open_selected)
        row.addWidget(b)
        b = QPushButton("重命名选中")
        b.clicked.connect(self.rename_selected)
        row.addWidget(b)
        v.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("参数选择窗口…"); b.clicked.connect(self._open_selector)
        row.addWidget(b)
        b = QPushButton("打开文件…"); b.clicked.connect(self._open_files)
        row.addWidget(b)
        b = QPushButton("清空数据"); b.clicked.connect(self._clear_all)
        row.addWidget(b)
        v.addLayout(row)
        self.tree = ParamTree(self.sess, on_changed=self._on_tree)
        self.tree.dclick_handler = self._tree_dclick   # 双击 = 打开窗口
        v.addWidget(self.tree, 1)
        rl.addWidget(g, 3)

        g = QGroupBox("② 新窗口默认约束(不影响已开的窗口)")
        v = QVBoxLayout(g)
        self.sp_xmin = mkspin(-1e12, 1e12, 0.0)
        self.sp_xmax = mkspin(-1e12, 1e12, 30.0)
        self.sp_Lmin = mkspin(0, 1e6, 0.0, 4)
        self.sp_Lmax = mkspin(0, 1e6, 10.0, 4)
        self.sp_ymin = mkspin(-1e12, 1e12, 0.0)
        self.sp_ymax = mkspin(-1e12, 1e12, 100.0)
        for lab, a, b in (("X 范围:", self.sp_xmin, self.sp_xmax),
                          ("L (µm):", self.sp_Lmin, self.sp_Lmax),
                          ("指标范围:", self.sp_ymin, self.sp_ymax)):
            row = QHBoxLayout()
            row.addWidget(QLabel(lab)); row.addWidget(a, 1)
            row.addWidget(QLabel("~")); row.addWidget(b, 1)
            v.addLayout(row)
        row = QHBoxLayout()
        self.cb_xlog = QCheckBox("X 对数"); self.cb_Llog = QCheckBox("L 对数")
        row.addWidget(self.cb_xlog); row.addWidget(self.cb_Llog)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("显示:"))
        self.cmb_disp = QComboBox()
        self.cmb_disp.addItems(["原始值(不换算)", "工程前缀", "dB(仅增益类)"])
        row.addWidget(self.cmb_disp, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        self.cb_smooth = QCheckBox("新窗口默认平滑")
        row.addWidget(self.cb_smooth)
        row.addWidget(QLabel("窗:"))
        self.sp_win = QSpinBox(); self.sp_win.setRange(3, 51)
        self.sp_win.setSingleStep(2); self.sp_win.setValue(9)
        row.addWidget(self.sp_win)
        row.addWidget(QLabel("阶:"))
        self.sp_ord = QSpinBox(); self.sp_ord.setRange(1, 5)
        self.sp_ord.setValue(2)
        row.addWidget(self.sp_ord)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("查表默认:"))
        self.cmb_dir = QComboBox()
        self.cmb_dir.addItem("≥", "max"); self.cmb_dir.addItem("≤", "min")
        row.addWidget(self.cmb_dir)
        self.sp_thr = mkspin(-1e12, 1e12, 50.0)
        row.addWidget(self.sp_thr, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("自动(按已开窗口数据)")
        b.clicked.connect(self._auto_defaults)
        row.addWidget(b)
        b = QPushButton("推给所有窗口")
        b.clicked.connect(self._push_defaults)
        row.addWidget(b)
        v.addLayout(row)
        rl.addWidget(g)
        rl.addStretch(0)

        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(right)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left); split.addWidget(sa)
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 1)
        split.setSizes([420, 700])
        self.setCentralWidget(split)

        for w in (self.sp_xmin, self.sp_xmax, self.sp_Lmin, self.sp_Lmax,
                  self.sp_ymin, self.sp_ymax, self.sp_thr):
            w.valueChanged.connect(self._on_default_ctl)
        for w in (self.cb_xlog, self.cb_Llog, self.cb_smooth):
            w.toggled.connect(self._on_default_ctl)
        self.sp_win.valueChanged.connect(self._on_default_ctl)
        self.sp_ord.valueChanged.connect(self._on_default_ctl)
        self.cmb_disp.currentIndexChanged.connect(self._on_default_ctl)
        self.cmb_dir.currentIndexChanged.connect(self._on_default_ctl)
        self._sc = QShortcut(QKeySequence("Ctrl+Shift+A"), self)
        self._sc.activated.connect(self._auto_defaults)
        self._selector = None

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
        act = m.addAction("滚轮不调数值(防误触)")
        act.setCheckable(True); act.setChecked(True)
        act.toggled.connect(self._toggle_wheel_guard)
        self.act_wheel = act
        m.addAction("切换深色主题", self._toggle_theme)
        m = mb.addMenu("窗口")
        m.addAction("全部置前", self._raise_all)
        m.addAction("全部关闭", self.close_all_windows)
        m.addAction("全部重绘", lambda: self.refresh(True))
        m.addAction("重命名选中参数", self.rename_selected)
        m = mb.addMenu("帮助")
        m.addAction("关于 / 使用说明", self._about)

    # ================= 默认约束 =================
    def _defaults_from_ui(self):
        """把主窗口控件读成一份"新窗口默认值"。"""
        v = sessmod.ViewState(
            xmin=self.sp_xmin.value(), xmax=self.sp_xmax.value(),
            Lmin=self.sp_Lmin.value(), Lmax=self.sp_Lmax.value(),
            ymin=self.sp_ymin.value(), ymax=self.sp_ymax.value(),
            xlog=self.cb_xlog.isChecked(), Llog=self.cb_Llog.isChecked(),
            display_mode=["raw", "prefix", "dB"][self.cmb_disp.currentIndex()],
            lookup_on=True, thr=self.sp_thr.value(),
            direction=self.cmb_dir.currentData(),
            clean=dict(self.sess.clean),
            x_metric=self.sess.x_metric,
        )
        v.clean.update(smooth=self.cb_smooth.isChecked(),
                       window=self.sp_win.value(), order=self.sp_ord.value())
        return v

    def _on_default_ctl(self):
        if self._loading:
            return
        d = self._defaults_from_ui()
        self.sess.xmin, self.sess.xmax = d.xmin, d.xmax
        self.sess.Lmin, self.sess.Lmax = d.Lmin, d.Lmax
        self.sess.ymin, self.sess.ymax = d.ymin, d.ymax
        self.sess.xlog, self.sess.Llog = d.xlog, d.Llog
        self.sess.display_mode = d.display_mode
        self.sess.thr = d.thr
        self.sess.direction = d.direction
        self.sess.clean.update(d.clean)
        self.sess.dirty("clean" if d.clean.get("smooth") !=
                        getattr(self, "_last_smooth", None) else "filters")
        self._last_smooth = d.clean.get("smooth")
        self._save_timer.start(1500)

    def _sync_defaults_ui(self):
        self._loading = True
        for w, val in ((self.sp_xmin, self.sess.xmin),
                       (self.sp_xmax, self.sess.xmax),
                       (self.sp_Lmin, self.sess.Lmin),
                       (self.sp_Lmax, self.sess.Lmax),
                       (self.sp_ymin, self.sess.ymin),
                       (self.sp_ymax, self.sess.ymax),
                       (self.sp_thr, self.sess.thr)):
            if hasattr(val, "__float__"):
                w.setValue(float(val))
        self.cb_xlog.setChecked(self.sess.xlog)
        self.cb_Llog.setChecked(self.sess.Llog)
        self.cmb_disp.setCurrentIndex(
            {"raw": 0, "prefix": 1, "dB": 2}[self.sess.display_mode])
        self.cb_smooth.setChecked(bool(self.sess.clean.get("smooth")))
        self.sp_win.setValue(int(self.sess.clean.get("window", 9)))
        self.sp_ord.setValue(int(self.sess.clean.get("order", 2)))
        j = self.cmb_dir.findData(self.sess.direction)
        if j >= 0:
            self.cmb_dir.setCurrentIndex(j)
        self._loading = False

    def _auto_defaults(self):
        metrics = [w.mt for w in self.windows.values()] or \
            self.sess.checked_metrics()
        if not metrics:
            self.statusBar().showMessage("还没有打开任何参数", 4000)
            return
        self.sess.default_ranges(None, metrics)   # 写到会话默认值
        self._sync_defaults_ui()
        self.statusBar().showMessage("默认约束已按数据自动设置", 4000)

    def _push_defaults(self):
        d = self._defaults_from_ui()
        for win in self.windows.values():
            v = win.view
            v.xmin, v.xmax = d.xmin, d.xmax
            v.Lmin, v.Lmax = d.Lmin, d.Lmax
            v.ymin, v.ymax = d.ymin, d.ymax
            v.xlog, v.Llog = d.xlog, d.Llog
            v.display_mode = d.display_mode
            v.clean.update(d.clean)
            v.lookup_on = d.lookup_on
            v.direction = d.direction
            v.thr = d.thr
            win.refresh(force=True)
        self.statusBar().showMessage(
            f"默认约束已推送到 {len(self.windows)} 个窗口", 4000)

    # ================= 窗口管理 =================
    def open_metric_window(self, path: str, base: str):
        key = (path, base)
        if key in self.windows:
            win = self.windows[key]
            win.show(); win.raise_(); win.activateWindow()
            return win
        src = self.sess.sources.get(path)
        metric = src.metrics.get(base) if src else None
        if metric is None:
            return None
        view = self.sess.make_view(metric)      # 每个窗口一份独立约束
        win = PlotWindow(self.sess, metric, view,
                         on_close=lambda w, k=key: self._win_closed(k))
        self.windows[key] = win
        win.show()
        self._refresh_win_list()
        return win

    def _win_closed(self, key):
        self.windows.pop(key, None)
        self._refresh_win_list()
        self._save_timer.start(800)

    def close_all_windows(self):
        for key in list(self.windows):
            w = self.windows.pop(key)
            try:
                w.on_close = None
                w.close()
            except Exception:
                pass
        self._refresh_win_list()

    def _refresh_win_list(self):
        self.lst_wins.clear()
        for key, win in self.windows.items():
            it = QListWidgetItem(f"{win.mt.display} · "
                                 f"{win.mt.source_label}")
            it.setData(Qt.UserRole, key)
            self.lst_wins.addItem(it)

    def _raise_win(self, item):
        key = item.data(Qt.UserRole)
        win = self.windows.get(key)
        if win is not None:
            win.show(); win.raise_(); win.activateWindow()

    def _raise_all(self):
        for win in self.windows.values():
            win.show(); win.raise_()

    def refresh(self, force=False):
        for win in list(self.windows.values()):
            try:
                win.refresh(force=force)
            except Exception as e:  # noqa: BLE001
                self.statusBar().showMessage(f"窗口刷新失败: {e}")

    # ================= 参数树 / 选择 =================
    def _reconcile(self):
        """勾选集合 <-> 打开窗口: 勾选即开窗, 取消即关窗。"""
        want = set()
        for path, bases in self.sess.checked.items():
            for b in bases:
                want.add((path, b))
        for key in list(self.windows):
            if key not in want:
                win = self.windows.pop(key)
                try:
                    win.on_close = None
                    win.close()
                except Exception:
                    pass
        for key in want:
            if key not in self.windows:
                self.open_metric_window(*key)
        self._refresh_win_list()
        self._save_timer.start(800)

    def _on_tree(self):
        self.tree.sync_states()
        if self._selector is not None:
            self._selector.tree.sync_states()
        self._reconcile()

    def _tree_dclick(self, item, _col):
        data = item.data(0, Qt.UserRole) if item is not None else None
        if not data or data[0] != "metric":
            return
        _, path, base = data
        if base not in self.sess.checked.get(path, set()):
            self.sess.toggle(path, base, True)
            self.tree.sync_states()
        self.open_metric_window(path, base)

    def _open_selected(self):
        item = self.tree.tree.currentItem()
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if data and data[0] == "metric":
            self._tree_dclick(item, 0)

    def rename_selected(self):
        item = self.tree.tree.currentItem()
        data = item.data(0, Qt.UserRole) if item is not None else None
        if not data or data[0] != "metric":
            QMessageBox.information(self, "提示", "请先在参数树里选中一个参数")
            return
        _, path, base = data
        src = self.sess.sources.get(path)
        if src is None:
            return
        from PySide6.QtWidgets import QInputDialog
        m = src.metrics.get(base)
        name, ok = QInputDialog.getText(self, "重命名参数",
                                        f"{base} 的显示名:",
                                        text=(m.display if m else base))
        if ok and name.strip():
            self.sess.rename_metric(src, base, name.strip())
            # 名称变化会重新识别指标档案: 同步该指标窗口的默认查表方向/刻度
            win = self.windows.get((path, base))
            if win is not None and m is not None and m.profile is not None:
                win.view.direction = m.profile.direction
                win.refresh(force=True)
            self.tree.rebuild()
            self._refresh_win_list()
            self.refresh(force=True)

    def _open_selector(self):
        if self._selector is None:
            self._selector = SelectorWindow(self.sess,
                                            on_changed=self._on_tree)
        self._selector.refresh()
        self._selector.show(); self._selector.raise_()

    # ================= 库 =================
    def _lib_load(self, entry):
        path = self.library.resolve(entry)
        if path is None:
            QMessageBox.warning(self, "文件缺失",
                                f"库条目「{entry.get('name')}」文件找不到")
            return
        if path in self.sess.sources:
            return
        try:
            from ..core.loader import load_file
            src = load_file(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "载入失败", str(e))
            return
        self.sess.add_source(src)
        if entry.get("id"):
            self.lib_panel.loaded_ids.add(entry["id"])
        self.tree.rebuild()
        self.lib_panel.rebuild()
        self._reconcile()          # 打开该文件的第一个参数窗口(双击即见)
        self.statusBar().showMessage(
            f"已打开 {entry.get('name')}({len(src.metrics)} 个参数)", 5000)

    def _lib_unload(self, entry):
        path = self.library.resolve(entry)
        for cand in (path, entry.get("path")):
            if cand and cand in self.sess.sources:
                self.sess.close_source(cand)
        if entry.get("id"):
            self.lib_panel.loaded_ids.discard(entry["id"])
        self.tree.rebuild()
        self.lib_panel.rebuild()
        self._reconcile()

    # ================= 会话 =================
    def _save_session(self):
        try:
            st = self.sess.export_state()
            st["library_ids"] = sorted(self.lib_panel.loaded_ids)
            st["windows"] = [
                {"path": k[0], "base": k[1], "view": w.view.as_dict()}
                for k, w in self.windows.items()]
            self.library.save_session(st)
        except Exception:
            pass

    def _restore_session(self):
        st = self.library.load_session()
        if not st:
            return
        self.sess.apply_state(st)
        n = 0
        for eid in (st.get("library_ids") or []):
            e = self.library.get(eid)
            if e is None:
                continue
            path = self.library.resolve(e)
            if path is None:
                continue
            try:
                from ..core.loader import load_file
                self.sess.add_source(load_file(path))
                self.lib_panel.loaded_ids.add(eid)
                n += 1
            except Exception:
                continue
        self.lib_panel.rebuild()
        self.tree.rebuild()
        self._sync_defaults_ui()
        self._reconcile()
        # 恢复上次的窗口(含各自约束)
        for item in (st.get("windows") or []):
            key = (item.get("path"), item.get("base"))
            win = self.windows.get(key)
            if win is None:
                continue
            vd = item.get("view") or {}
            for k, val in vd.items():
                if hasattr(win.view, k):
                    setattr(win.view, k,
                            tuple(val) if k == "x_metric" and val else val)
            win.refresh(force=True)
        if n or self.windows:
            self.statusBar().showMessage(
                f"已恢复上次会话: {n} 个库文件 / {len(self.windows)} 个窗口",
                6000)

    def closeEvent(self, ev):
        self._save_session()
        self.close_all_windows()
        super().closeEvent(ev)

    # ================= 其它 =================
    def _open_files(self):
        from PySide6.QtWidgets import QFileDialog
        fs, _ = QFileDialog.getOpenFileNames(
            self, "打开数据文件", "",
            "数据文件 (*.csv *.txt *.dat *.tsv);;所有文件 (*)")
        if fs:
            self.open_paths(fs)

    def _open_dir(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "打开文件夹")
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
        if self.sess.x_metric is None:
            for path, src in self.sess.sources.items():
                for m in src.sorted_metrics():
                    if getattr(m.profile, "key", None) == "gmid":
                        self.sess.x_metric = (path, m.base)
                        break
                else:
                    continue
                break
        self.tree.rebuild()
        self._auto_defaults()
        self._reconcile()          # 已勾选的参数(每个文件默认第一个)自动开窗
        self.statusBar().showMessage(
            f"已载入 {len(sources)} 个文件 "
            f"({sum(len(s.metrics) for s in sources.values())} 个参数, "
            f"{time.time()-t0:.2f}s)", 8000)
        if errs:
            print("load errors:", errs)

    def _clear_all(self):
        self.close_all_windows()
        self.sess.remove_all()
        self.lib_panel.loaded_ids.clear()
        self.lib_panel.rebuild()
        self.tree.rebuild()

    def _toggle_wheel_guard(self, on: bool):
        if self.wheel_filter is not None:
            self.wheel_filter.enabled = bool(on)

    def _toggle_theme(self):
        from PySide6.QtWidgets import QApplication
        self.dark = not self.dark
        apply_theme(QApplication.instance(), self.dark)

    def _about(self):
        QMessageBox.about(
            self, "gm/ID 设计数据工作室",
            "控制台负责数据与窗口;每个参数在**独立窗口**里绘制,各自拥有\n"
            "范围/对数轴/平滑/显示单位/查表阈值,互不影响。\n\n"
            "· 三维曲面不常驻: 在 2D 窗口里点「三维曲面…」按需打开;\n"
            "· 2D 窗口内: ＋竖线/＋横线 拖动读交点值, 测斜率(A→B) 取两点;\n"
            "· 库管理: 导入一次, 以后勾选即加载; 会话(窗口与各自约束)自动恢复。")
