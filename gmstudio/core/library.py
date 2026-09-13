# -*- coding: utf-8 -*-
"""
数据库管理:把常用数据文件收进一个本地库, 下次直接勾选加载, 不必再翻文件。
=================================================================
库目录结构(默认 <项目>/library):
    library.json          库索引(条目 + 标签 + 备注)
    session.json          上次会话(打开的文件、勾选参数、范围、游标…)
    files/                入库时复制进来的数据文件(可选“引用原路径”模式)
    meta/                 每个文件的参数重命名记录

对外接口: Library.add_file / remove / entries / resolve / save_session …
纯 Python, 不依赖 Qt, 方便脚本化。
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid


def default_root(project_root: str | None = None) -> str:
    if project_root is None:
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(project_root, "library")


class Library:
    def __init__(self, root: str | None = None):
        self.root = root or default_root()
        self.files_dir = os.path.join(self.root, "files")
        self.index_path = os.path.join(self.root, "library.json")
        self.session_path = os.path.join(self.root, "session.json")
        self.entries: list[dict] = []
        os.makedirs(self.files_dir, exist_ok=True)
        self.load()

    # ---------------- 索引 ----------------
    def load(self):
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.entries = list(data.get("entries") or [])
        except Exception:
            self.entries = []

    def save(self):
        try:
            with open(self.index_path, "w", encoding="utf-8") as f:
                json.dump({"entries": self.entries}, f,
                          ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------- 条目 ----------------
    def get(self, entry_id: str):
        for e in self.entries:
            if e["id"] == entry_id:
                return e
        return None

    def find_by_path(self, path: str):
        p = os.path.abspath(path)
        for e in self.entries:
            if os.path.abspath(e.get("path", "")) == p:
                return e
            src = e.get("source_path")
            if src and os.path.abspath(src) == p:
                return e
        return None

    def add_file(self, path: str, copy: bool = True, tags=None,
                 name: str | None = None) -> dict:
        path = os.path.abspath(path)
        exist = self.find_by_path(path)
        if exist:
            return exist
        stored = path
        if copy:
            base = os.path.basename(path)
            stem, ext = os.path.splitext(base)
            target = os.path.join(self.files_dir, base)
            n = 1
            while os.path.exists(target):
                target = os.path.join(self.files_dir, f"{stem}_{n}{ext}")
                n += 1
            shutil.copy2(path, target)
            stored = target
        entry = {
            "id": uuid.uuid4().hex[:12],
            "name": name or os.path.splitext(os.path.basename(path))[0],
            "path": stored,
            "source_path": path if copy else "",
            "copied": bool(copy),
            "tags": list(tags or []),
            "note": "",
            "added": time.strftime("%Y-%m-%d %H:%M"),
            "size": os.path.getsize(path) if os.path.exists(path) else 0,
        }
        self.entries.append(entry)
        self.save()
        return entry

    def update(self, entry_id: str, **kw):
        e = self.get(entry_id)
        if e:
            e.update(kw)
            self.save()
        return e

    def remove(self, entry_id: str, delete_copy: bool = False):
        e = self.get(entry_id)
        if not e:
            return
        if delete_copy and e.get("copied") and os.path.exists(e["path"]):
            try:
                os.remove(e["path"])
            except Exception:
                pass
        self.entries = [x for x in self.entries if x["id"] != entry_id]
        self.save()

    def resolve(self, entry: dict) -> str | None:
        """返回可用路径; 文件不存在则返回 None(条目置 missing)。"""
        for key in ("path", "source_path"):
            p = entry.get(key)
            if p and os.path.exists(p):
                return p
        return None

    def all_tags(self) -> list[str]:
        tags = set()
        for e in self.entries:
            tags.update(e.get("tags") or [])
        return sorted(tags)

    # ---------------- 会话记忆 ----------------
    def save_session(self, state: dict):
        try:
            with open(self.session_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def load_session(self) -> dict:
        try:
            with open(self.session_path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}
