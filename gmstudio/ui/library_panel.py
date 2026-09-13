# -*- coding: utf-8 -*-
"""数据库面板: 把常用文件收进本地库, 勾选即加载, 不必每次导入。"""
from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)


class LibraryPanel(QWidget):
    """库条目列表(勾选=加载到会话)。回调: on_load(entry) / on_unload(entry)。"""

    def __init__(self, library, on_load, on_unload, parent=None):
        super().__init__(parent)
        self.lib = library
        self.on_load = on_load
        self.on_unload = on_unload
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText("过滤库(名称/标签)…")
        self.ed_filter.textChanged.connect(self.rebuild)
        row.addWidget(self.ed_filter, 1)
        lay.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("导入文件到库…"); b.clicked.connect(self._import_files)
        row.addWidget(b)
        b = QPushButton("导入文件夹…"); b.clicked.connect(self._import_dir)
        row.addWidget(b)
        lay.addLayout(row)
        self.lst = QListWidget()
        # 不设固定高度: 内容多长就多长(配合可折叠区块, 小窗口也能滚动看全)
        self.lst.setMinimumHeight(110)
        self.lst.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 双击 = 打开(已加载再双击 = 卸载); 不再用勾选触发
        self.lst.itemDoubleClicked.connect(self._on_dclick)
        self.lst.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lst.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.lst, 1)
        row = QHBoxLayout()
        b = QPushButton("打开(双击等效)")
        b.setObjectName("primary"); b.clicked.connect(self._open_current)
        row.addWidget(b)
        b = QPushButton("卸载选中"); b.clicked.connect(self._unload_current)
        row.addWidget(b)
        lay.addLayout(row)
        row = QHBoxLayout()
        b = QPushButton("打开库目录"); b.clicked.connect(self._open_dir)
        row.addWidget(b)
        b = QPushButton("打标签 / 重命名"); b.clicked.connect(self._tag_item)
        row.addWidget(b)
        b = QPushButton("移出库"); b.clicked.connect(self._remove_item)
        row.addWidget(b)
        lay.addLayout(row)
        self.lb_info = QLabel("")
        self.lb_info.setStyleSheet("color:#777;")
        lay.addWidget(self.lb_info)
        self.loaded_ids: set[str] = set()
        self.rebuild()

    # ---------------- 列表 ----------------
    def rebuild(self):
        self._loading = True
        self.lst.blockSignals(True)
        self.lst.clear()
        text = self.ed_filter.text().strip().lower()
        n = 0
        for e in self.lib.entries:
            hay = (e.get("name", "") + " " + " ".join(e.get("tags") or [])).lower()
            if text and text not in hay:
                continue
            n += 1
            missing = self.lib.resolve(e) is None
            loaded = e["id"] in self.loaded_ids
            tags = ("  #" + " #".join(e.get("tags") or [])) if e.get("tags") else ""
            mark = "●" if loaded else "○"
            it = QListWidgetItem(f"{mark} {e['name']}{tags}"
                                 + ("   [文件缺失]" if missing else ""))
            it.setData(Qt.UserRole, e["id"])
            size = e.get("size") or 0
            hint = "已加载(双击卸载)" if loaded else "双击加载"
            it.setToolTip(f"{e.get('path', '')}\n大小 {size/1024:.0f} KB · "
                          f"加入 {e.get('added', '')}\n{hint}"
                          + (f"\n{e.get('note')}" if e.get("note") else ""))
            self.lst.addItem(it)
        self.lst.blockSignals(False)
        self._loading = False
        self.lb_info.setText(
            f"库内 {len(self.lib.entries)} 个, 显示 {n} 个; 已加载 "
            f"{len(self.loaded_ids)} 个(● 已加载 / ○ 未加载, **双击**切换)")

    def _entry_of(self, item):
        return self.lib.get(item.data(Qt.UserRole)) if item else None

    def _current(self):
        return self._entry_of(self.lst.currentItem())

    def _on_dclick(self, item):
        """双击库条目: 未加载 -> 加载并打开; 已加载 -> 卸载。"""
        e = self._entry_of(item)
        if e is None:
            return
        if self.lib.resolve(e) is None:
            QMessageBox.warning(self, "文件缺失",
                                f"「{e.get('name')}」的文件不存在:\n"
                                f"{e.get('path')}")
            return
        if e["id"] in self.loaded_ids:
            self.loaded_ids.discard(e["id"])
            self.on_unload(e)
        else:
            self.loaded_ids.add(e["id"])
            self.on_load(e)
        self.rebuild()

    def _open_current(self):
        item = self.lst.currentItem()
        if item is not None:
            self._on_dclick(item)

    def _unload_current(self):
        e = self._current()
        if e is None or e["id"] not in self.loaded_ids:
            return
        self.loaded_ids.discard(e["id"])
        self.on_unload(e)
        self.rebuild()

    def mark_loaded(self, entry_id: str, loaded: bool):
        self.loaded_ids.add(entry_id) if loaded else self.loaded_ids.discard(entry_id)
        self.rebuild()

    # ---------------- 操作 ----------------
    def _import_files(self):
        from PySide6.QtWidgets import QFileDialog
        fs, _ = QFileDialog.getOpenFileNames(
            self, "导入数据文件到库", "",
            "数据文件 (*.csv *.txt *.dat *.tsv);;所有文件 (*)")
        self._add(fs)

    def _import_dir(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "导入文件夹中的所有数据文件")
        if not d:
            return
        exts = {".csv", ".txt", ".dat", ".tsv"}
        fs = [os.path.join(d, f) for f in sorted(os.listdir(d))
              if os.path.splitext(f)[1].lower() in exts]
        self._add(fs)

    def _add(self, files):
        if not files:
            return
        added = 0
        for f in files:
            try:
                self.lib.add_file(f, copy=True)
                added += 1
            except Exception as ex:  # noqa: BLE001
                print("import failed:", f, ex)
        self.rebuild()
        self.lb_info.setText(f"已入库 {added} 个文件(复制到 library/files)")

    def _menu(self, pos):
        item = self.lst.itemAt(pos)
        if item is None:
            return
        e = self._entry_of(item)
        loaded = bool(e and e["id"] in self.loaded_ids)
        m = QMenu(self)
        m.addAction("卸载" if loaded else "打开(加载)",
                    lambda: self._on_dclick(item))
        m.addAction("打标签 / 重命名…", self._tag_item)
        m.addAction("移出库(保留文件)", lambda: self._remove_item(False))
        m.addAction("移出库并删除副本", lambda: self._remove_item(True))
        m.exec(self.lst.mapToGlobal(pos))

    def _tag_item(self):
        e = self._current()
        if e is None:
            return
        name, ok = QInputDialog.getText(self, "重命名", "库中显示名:",
                                        text=e.get("name", ""))
        if ok and name.strip():
            e["name"] = name.strip()
        tags, ok = QInputDialog.getText(
            self, "标签", "标签(空格分隔):",
            text=" ".join(e.get("tags") or []))
        if ok:
            e["tags"] = [t for t in tags.split() if t]
        self.lib.save()
        self.rebuild()

    def _remove_item(self, delete_copy=False):
        e = self._current()
        if e is None:
            return
        if delete_copy:
            r = QMessageBox.question(self, "确认", f"删除库副本并移出?\n{e['name']}")
            if r != QMessageBox.Yes:
                return
        if e["id"] in self.loaded_ids:
            self.on_unload(e)
            self.loaded_ids.discard(e["id"])
        self.lib.remove(e["id"], delete_copy=delete_copy)
        self.rebuild()

    def _open_dir(self):
        try:
            os.startfile(self.lib.root)  # noqa: S606
        except Exception:
            subprocess.Popen(["explorer", self.lib.root])
