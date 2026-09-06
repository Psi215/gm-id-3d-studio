# -*- coding: utf-8 -*-
"""参数浏览器(树) 与 独立的参数选择窗口。

所有参数都在导入时载入内存(不绘图); 用户在这里实时勾选要看哪些参数。
双击条目可重命名(显示名, 持久化到 <文件>.meta.json)。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


class ParamTree(QWidget):
    """源文件 -> 参数 的可勾选树; 支持搜索过滤与双击重命名。

    注意: 勾选/重命名会触发回调(主窗口重绘并重建参数树), 但 Qt 的
    itemChanged 信号在发射过程中不能清掉这个树——否则会访问违例崩溃。
    因此回调统一推迟到事件循环下一拍再执行。
    """

    def __init__(self, session, on_changed=None, parent=None):
        super().__init__(parent)
        self.session = session
        self.on_changed = on_changed or (lambda: None)
        self._notify_pending = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索参数(名称/序号, 如 ft、M0:12)…")
        self.search.textChanged.connect(self.rebuild)
        row.addWidget(self.search, 1)
        lay.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["参数 (勾选即显示)", "L 数"])
        self.tree.setColumnWidth(0, 210)
        self.tree.itemChanged.connect(self._on_item)
        self.tree.itemDoubleClicked.connect(self._on_dclick)
        lay.addWidget(self.tree, 1)
        self.rebuild()

    def _defer_notify(self):
        """把 on_changed 推迟到下一拍, 避免在 itemChanged 发射期间重建树。"""
        if self._notify_pending:
            return
        self._notify_pending = True
        QTimer.singleShot(0, self._flush_notify)

    def _flush_notify(self):
        self._notify_pending = False
        self.on_changed()

    def rebuild(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        text = self.search.text().strip().lower()
        for path, src in self.session.sources.items():
            top = QTreeWidgetItem([f"📁 {src.label}", ""])
            top.setData(0, Qt.UserRole, ("src", path))
            top.setFlags(top.flags() & ~Qt.ItemIsUserCheckable)
            n_shown = 0
            for m in src.sorted_metrics():
                if text and text not in m.display.lower() \
                        and text not in m.base.lower():
                    continue
                n_shown += 1
                it = QTreeWidgetItem(
                    [m.display, str(m.n_curves)])
                it.setData(0, Qt.UserRole, ("metric", path, m.base))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(
                    0, Qt.Checked
                    if m.base in self.session.checked.get(path, set())
                    else Qt.Unchecked)
                it.setToolTip(0, f"{m.base} · {m.x_name} · "
                                 f"{m.note or '—'}")
                top.addChild(it)
            top.setText(0, f"📁 {src.label} ({n_shown}/{len(src.metrics)})")
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        self.tree.blockSignals(False)

    def _on_item(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if not data or data[0] != "metric":
            return
        _, path, base = data
        on = item.checkState(0) == Qt.Checked
        self.session.toggle(path, base, on)
        self._defer_notify()

    def _on_dclick(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if not data or data[0] != "metric":
            return
        _, path, base = data
        src = self.session.sources.get(path)
        if src is None:
            return
        m = src.metrics.get(base)
        if m is None:
            return
        name, ok = QInputDialog.getText(
            self, "重命名参数", f"参数 {m.base} 的显示名(含单位也可以):",
            text=m.display)
        if ok and name.strip():
            self.session.rename_metric(src, base, name)
            self._defer_notify()


class SelectorWindow(QDialog):
    """独立(非模态)参数选择窗口: 勾选后主窗口实时刷新。"""

    def __init__(self, session, on_changed=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("参数选择器 · 实时勾选查看")
        self.resize(380, 620)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("全部参数已驻留内存; 勾选要查看的参数:"))
        lay.addLayout(bar)
        self.tree = ParamTree(session, on_changed=on_changed, parent=self)
        lay.addWidget(self.tree, 1)
        btn = QPushButton("关闭")
        btn.clicked.connect(self.hide)
        lay.addWidget(btn)

    def refresh(self):
        self.tree.rebuild()

    def closeEvent(self, ev):
        self.hide()
        ev.ignore()
