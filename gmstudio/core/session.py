# -*- coding: utf-8 -*-
"""会话状态 + 处理操作(清洗 / 曲面 / 查表) + 重命名持久化。"""
from __future__ import annotations

import json
import os

import numpy as np

from gmidlib import clean as _clean
from gmidlib import lookup as _lookup
from gmidlib import surface as _surface
from gmidlib.metrics import detect_metric, is_raw_db

from .model import Curve, Metric, Source

DB_DEFAULT = "dB"
PREFIX_DEFAULT = "prefix"
RAW_DEFAULT = "raw"

_CLEAN_STATE = dict(drop_fold=False, sort_x=True, smooth=False,
                    window=9, order=2, outlier=False, k_mad=5.0)
# 数据清洗已精简: 只保留“可选平滑”, 回折剔除/坏点剔除默认且不再暴露
_SMOOTH_ONLY = dict(drop_fold=False, sort_x=True, outlier=False)


class ViewState:
    """一个视图(一张图/一个窗口)的**独立约束**。

    每个绘图窗口都有自己的 ViewState: 自己的 X/L/指标范围、对数轴、
    平滑设置、显示模式、查表阈值与方向、X 轴参数。互不影响。
    """

    __slots__ = ("xmin", "xmax", "Lmin", "Lmax", "ymin", "ymax",
                 "xlog", "Llog", "npts", "clean", "lookup_on", "thr",
                 "direction", "display_mode", "x_metric")

    def __init__(self, **kw):
        self.xmin = kw.get("xmin", 0.0)
        self.xmax = kw.get("xmax", 30.0)
        self.Lmin = kw.get("Lmin", 0.0)
        self.Lmax = kw.get("Lmax", 10.0)
        self.ymin = kw.get("ymin", 0.0)
        self.ymax = kw.get("ymax", 100.0)
        self.xlog = bool(kw.get("xlog", False))
        self.Llog = bool(kw.get("Llog", False))
        self.npts = int(kw.get("npts", 240))
        self.clean = dict(kw.get("clean") or _CLEAN_STATE)
        self.lookup_on = bool(kw.get("lookup_on", True))
        self.thr = float(kw.get("thr", 50.0))
        self.direction = kw.get("direction", "max")
        self.display_mode = kw.get("display_mode", RAW_DEFAULT)
        self.x_metric = kw.get("x_metric", None)

    def copy(self) -> "ViewState":
        v = ViewState()
        for name in self.__slots__:
            val = getattr(self, name)
            setattr(v, name, dict(val) if isinstance(val, dict) else val)
        return v

    def as_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__slots__}
        d["x_metric"] = list(d["x_metric"]) if d["x_metric"] else None
        return d


class Session:
    """所有窗口共享的数据与状态。"""

    def __init__(self):
        self.sources: dict[str, Source] = {}
        self.checked: dict[str, set] = {}       # path -> set(base)
        self.active: dict[str, str] = {}        # path -> base(3D/查表用)
        self.xmin = 0.0
        self.xmax = 30.0
        self.Lmin = 0.0
        self.Lmax = 10.0
        self.ymin = 0.0
        self.ymax = 100.0
        self.xlog = False
        self.Llog = False
        self.npts = 240
        self.clean = dict(_CLEAN_STATE)
        self.lookup_on = True
        self.thr = 50.0
        self.direction = "max"
        self.display_mode = RAW_DEFAULT      # raw / prefix / dB
        self.x_metric = None                # (path, base) 或 None=参数自带X
        self._surf_cache: dict = {}
        self._lookup_cache: dict = {}
        self._eff_cache: dict = {}
        self._display_cache: dict = {}      # (path, base, unit) -> (factor, unit)
        self._dirty = True

    # ---------------- 数据装载 / 选择 ----------------
    def add_source(self, src: Source):
        self._display_cache = {k: v for k, v in self._display_cache.items()
                               if k[0] != src.path}
        self.sources[src.path] = src
        self.checked.setdefault(src.path, set())
        self._load_meta(src)
        # 库管理恢复: 若状态里有该文件的勾选/当前指标, 优先采用
        pending = getattr(self, "_pending_checked", {}).get(src.path)
        if pending:
            self.checked[src.path] = {b for b in pending if b in src.metrics}
        if not self.checked[src.path] and src.metrics:
            first = next(iter(src.sorted_metrics()))
            self.checked[src.path].add(first.base)
        pa = getattr(self, "_pending_active", {}).get(src.path)
        if pa in src.metrics:
            self.active[src.path] = pa
        else:
            self.active.setdefault(src.path,
                                   next(iter(self.checked[src.path])))
        self.dirty()

    def remove_all(self):
        self.sources.clear(); self.checked.clear(); self.active.clear()
        self._display_cache.clear()
        self.dirty()

    def close_source(self, path: str):
        """关闭一个数据源(库管理用: 从会话中卸载, 不动磁盘文件)。"""
        self.sources.pop(path, None)
        self.checked.pop(path, None)
        self.active.pop(path, None)
        if self.x_metric and self.x_metric[0] == path:
            self.x_metric = None
        self.dirty()

    def toggle(self, path: str, base: str, on: bool):
        if path not in self.checked:
            return
        s = self.checked[path]
        if on:
            s.add(base)
        else:
            s.discard(base)
        if self.active.get(path) not in s:
            self.active[path] = next(iter(s)) if s else ""
        self.dirty()

    def set_active(self, path: str, base: str):
        if base and base in self.sources[path].metrics:
            self.active[path] = base
            self.dirty()

    def checked_metrics(self) -> list[Metric]:
        out = []
        for path, bases in self.checked.items():
            src = self.sources.get(path)
            if src is None:
                continue
            for b in bases:
                m = src.metrics.get(b)
                if m is not None:
                    out.append(m)
        return out

    def active_metric(self) -> Metric | None:
        for path, base in self.active.items():
            src = self.sources.get(path)
            if src and base in src.metrics:
                return src.metrics[base]
        return None

    def dirty(self, level: str = "all"):
        """分级失效缓存, 提升流畅度:
        level='filters' 只清曲面/查表(改范围/栅格时用, 清洗结果仍有效);
        level='clean'   清曲面/查表/配对清洗(改清洗参数或换 X 轴时用);
        level='all'     全部(数据源增删等)。"""
        self._surf_cache.clear()
        self._lookup_cache.clear()
        if level in ("clean", "all"):
            self._eff_cache.clear()

    # ---------------- 会话状态(库管理 / 记忆上次) ----------------
    def export_state(self) -> dict:
        return {
            "open_sources": list(self.sources.keys()),
            "checked": {p: sorted(b) for p, b in self.checked.items()},
            "active": dict(self.active),
            "x_metric": list(self.x_metric) if self.x_metric else None,
            "ranges": [self.xmin, self.xmax, self.Lmin, self.Lmax,
                       self.ymin, self.ymax],
            "xlog": self.xlog, "Llog": self.Llog, "npts": self.npts,
            "clean": dict(self.clean),
            "lookup_on": self.lookup_on, "thr": self.thr,
            "direction": self.direction, "display_mode": self.display_mode,
        }

    def apply_state(self, st: dict):
        """恢复上次的视图状态(数据源由调用方负责重新装载)。"""
        if not st:
            return
        rng = st.get("ranges") or []
        if len(rng) == 6:
            (self.xmin, self.xmax, self.Lmin, self.Lmax,
             self.ymin, self.ymax) = rng
        self.xlog = bool(st.get("xlog", self.xlog))
        self.Llog = bool(st.get("Llog", self.Llog))
        self.npts = int(st.get("npts", self.npts))
        self.clean.update(st.get("clean") or {})
        self.lookup_on = bool(st.get("lookup_on", self.lookup_on))
        self.thr = float(st.get("thr", self.thr))
        self.direction = st.get("direction", self.direction)
        self.display_mode = st.get("display_mode", self.display_mode)
        xm = st.get("x_metric")
        self.x_metric = tuple(xm) if xm else self.x_metric
        self._pending_checked = {p: set(b) for p, b in
                                 (st.get("checked") or {}).items()}
        self._pending_active = dict(st.get("active") or {})

    # ---------------- 重命名持久化 ----------------
    def _meta_path(self, src: Source):
        return src.path + ".meta.json"

    def _load_meta(self, src: Source):
        mp = self._meta_path(src)
        if not os.path.exists(mp):
            return
        try:
            with open(mp, "r", encoding="utf-8") as f:
                meta = json.load(f)
            names = meta.get("metric_names", {})
            for base, name in names.items():
                m = src.metrics.get(base)
                if m and name:
                    m.display = name
            if meta.get("x_name"):
                src.x_name = meta["x_name"]
                for m in src.metrics.values():
                    m.x_name = meta["x_name"]
        except Exception:
            pass

    def save_meta(self, src: Source):
        meta = {
            "metric_names": {b: m.display for b, m in src.metrics.items()
                             if m.display != m.base},
            "x_name": src.x_name,
        }
        try:
            with open(self._meta_path(src), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def rename_metric(self, src: Source, base: str, name: str):
        m = src.metrics.get(base)
        if m is None:
            return
        name = (name or "").strip()
        if not name:
            return
        m.display = name
        prof = detect_metric(name)
        m.profile = prof
        m.raw_db = is_raw_db(name, prof)
        self._display_cache = {k: v for k, v in self._display_cache.items()
                               if k[:2] != (m.source_path or m.source_label,
                                            m.base)}
        self.save_meta(src)
        self.dirty()

    # ---------------- 显示换算(默认原始值) ----------------
    def disp(self, m: Metric, y, view=None, **kw):
        """按视图的显示模式把原始值换算成显示值(view=None 用会话默认)。"""
        v = view if view is not None else self
        mode = kw.get("mode", v.display_mode)
        a = np.asarray(y, float)
        prof = m.profile
        if mode == DB_DEFAULT and prof is not None and prof.db_capable:
            if m.raw_db:
                return a
            with np.errstate(divide="ignore"):
                return np.where(np.isfinite(a) & (a > 0),
                                20.0 * np.log10(a), -np.inf)
        if mode == PREFIX_DEFAULT and prof is not None and prof.unit:
            return a * self._metric_display(m)[0]
        return a

    def _metric_display(self, m: Metric):
        """为一个指标**固定**一个工程前缀(曲线/曲面/过滤/查表共用),
        避免同一指标在不同视图里用不同刻度导致读数不一致。"""
        prof = m.profile
        if prof is None or not prof.unit:
            return 1.0, ""
        key = (m.source_path or m.source_label, m.base, prof.unit)
        if key in self._display_cache:
            return self._display_cache[key]
        vals = [np.asarray(c.y, float).ravel() for c in m.curves
                if c.y is not None and np.asarray(c.y).size]
        data = np.concatenate(vals) if vals else np.array([1.0])
        result = _pick_prefix(data, prof.unit)
        self._display_cache[key] = result
        return result

    def unit_str(self, m: Metric | None, mode=None, view=None) -> str:
        v = view if view is not None else self
        mode = mode if mode is not None else v.display_mode
        if m is None:
            return ""
        if mode == DB_DEFAULT and m.profile is not None \
                and m.profile.db_capable:
            return "dB"
        if mode == PREFIX_DEFAULT and m.profile is not None and m.profile.unit:
            return self._metric_display(m)[1]
        return m.profile.unit if m.profile is not None else ""

    # ---------------- X 轴选择 / 配对 / 清洗 ----------------
    def x_metric_obj(self, view=None) -> Metric | None:
        v = view if view is not None else self
        if v.x_metric:
            src = self.sources.get(v.x_metric[0])
            if src is not None:
                return src.metrics.get(v.x_metric[1])
        return None

    def x_label(self, view=None) -> str:
        v = view if view is not None else self
        xm = self.x_metric_obj(v)
        if xm is not None:
            return xm.display
        am = self.active_metric()
        return am.x_name if am is not None else "X"

    def _clean_sig(self, view=None):
        c = (view if view is not None else self).clean
        return (c.get("drop_fold"), c.get("sort_x"), c.get("smooth"),
                c.get("window"), c.get("order"), c.get("outlier"),
                c.get("k_mad"))

    def effective_series(self, m: Metric, view=None):
        """返回 (L, x, y) 列表: 若视图选了 X 轴参数, 则 Y 与所选 X 按行索引
        配对后再清洗排序; 否则用参数自带的 X 列。结果按视图设置缓存。"""
        v = view if view is not None else self
        key = (m.source_path or m.source_label, m.base,
               tuple(v.x_metric) if v.x_metric else None,
               self._clean_sig(v))
        if key in self._eff_cache:
            return self._eff_cache[key]
        sers = self._build_effective(m, v)
        self._eff_cache[key] = sers
        return sers

    def _build_effective(self, m: Metric, view=None):
        v = view if view is not None else self
        xm = self.x_metric_obj(v)
        out = []
        for c in m.curves:
            if c.L_um is None:
                continue
            if xm is None or xm is m:
                ok = np.isfinite(c.x) & np.isfinite(c.y)
                if ok.sum() < 2:
                    continue
                x, y = c.x[ok], c.y[ok]
            else:
                xc = next((cc for cc in xm.curves
                           if cc.L_um is not None
                           and abs(cc.L_um - c.L_um) < 1e-9), None)
                if xc is None:
                    continue
                n = min(c.x.size, xc.x.size)
                if n < 2:
                    continue
                ok = (np.isfinite(c.x[:n]) & np.isfinite(c.y[:n])
                      & np.isfinite(xc.x[:n]))
                if ok.sum() < 2:
                    continue
                x, y = xc.x[:n][ok], c.y[:n][ok]
            tc = Curve(c.L_um, x, y)
            _clean.clean_series(
                tc, drop_fold=False, sort_x=True,
                smooth=v.clean.get("smooth", False),
                window=v.clean.get("window", 9),
                order=v.clean.get("order", 2),
                outlier=False, k_mad=v.clean.get("k_mad", 5.0))
            if tc.x_c is not None and tc.x_c.size >= 2:
                out.append((tc.L_um, tc.x_c, tc.y_c))
        out.sort(key=lambda t: (t[0] is None, t[0] or 0.0))
        return out

    def clean_metric(self, m: Metric, view=None) -> str:
        """触发(并缓存)该视图 X 轴选择下的清洗。"""
        self.effective_series(m, view)
        return "ok"

    # ---------------- 曲面 / 查表 ----------------
    def surface_of(self, m: Metric, view=None) -> dict | None:
        v = view if view is not None else self
        key = (m.source_path or m.source_label, m.base, v.xmin, v.xmax, v.Lmin,
               v.Lmax, v.npts, v.xlog,
               tuple(v.x_metric) if v.x_metric else None,
               self._clean_sig(v))
        if key in self._surf_cache:
            return self._surf_cache[key]
        sers = [(l, x, y) for (l, x, y) in self.effective_series(m, v)
                if l is not None and v.Lmin <= l <= v.Lmax]
        if len(sers) < 1:
            return None
        xs_all = np.concatenate([x for _, x, _ in sers])
        if xs_all.size == 0 or not np.isfinite(xs_all).any() \
                or float(np.ptp(xs_all[np.isfinite(xs_all)])) <= 0:
            return None                       # 常数 X(如参数自带值)退化
        xmin, xmax = v.xmin, v.xmax
        if v.xlog:
            pos = np.concatenate([x[x > 0] for _, x, _ in sers])
            if pos.size:
                if xmin <= 0:
                    xmin = pos.min() * 0.8
                if xmax <= 0 or xmax <= xmin:
                    xmax = pos.max() * 1.2
        if not (xmin < xmax):
            return None
        try:
            sf = _surface.build_surface(sers, xmin=xmin, xmax=xmax,
                                        n=int(v.npts), xlog=v.xlog)
        except Exception:
            return None
        sf["sers"] = sers
        self._surf_cache[key] = sf
        return sf

    def lookup_of(self, m: Metric, view=None) -> object | None:
        v = view if view is not None else self
        sf = self.surface_of(m, v)
        if sf is None or not np.isfinite(sf["Z"]).any():
            return None
        key = (m.source_path or m.source_label, m.base, v.thr, v.direction, v.display_mode,
               v.xmin, v.xmax, v.Lmin, v.Lmax, v.npts)
        if key in self._lookup_cache:
            return self._lookup_cache[key]
        Zd = self.disp(m, sf["Z"], mode=v.display_mode)
        res = _lookup.run_lookup(Zd, sf["xs"], sf["Ls"], float(v.thr),
                                 direction=v.direction)
        self._lookup_cache[key] = res
        return res

    def default_ranges(self, view=None, metrics=None):
        """依据给定参数(默认已勾选的)设置**该视图**的默认范围与阈值。"""
        v = view if view is not None else self
        if metrics is None:
            metrics = self.checked_metrics()
        xs_all, Ls = [], []
        for m in metrics:
            for (l, x, y) in self.effective_series(m, v):
                xs_all.append(x)
                if l is not None:
                    Ls.append(l)
        if not xs_all:
            return
        xs_all = np.concatenate(xs_all)
        xs_all = xs_all[np.isfinite(xs_all)]
        if xs_all.size == 0:
            return
        xlo, xhi = float(xs_all.min()), float(xs_all.max())
        pad = 0.03 * (xhi - xlo) or 1.0
        v.xmin, v.xmax = xlo - pad, xhi + pad
        if Ls:
            Larr = np.array(Ls, float)
            v.Lmin = max(0.0, float(Larr.min()) * 0.9)
            v.Lmax = float(Larr.max()) * 1.1
        am = metrics[0] if metrics else self.active_metric()
        if am is not None:
            sf = self.surface_of(am, v)
            if sf is not None and np.isfinite(sf["Z"]).any():
                Zd = self.disp(am, sf["Z"], mode=v.display_mode)
                fin = Zd[np.isfinite(Zd)]
                if fin.size:
                    lo, hi = float(fin.min()), float(fin.max())
                    v.ymin = lo - 0.05 * (hi - lo)
                    v.ymax = hi + 0.05 * (hi - lo)
                    prof = am.profile
                    direction = v.direction or (
                        prof.direction if prof is not None else "max")
                    if direction == "max":
                        v.thr = lo + 0.8 * (hi - lo)
                    else:
                        v.thr = lo + 0.2 * (hi - lo)
                    if not np.isfinite(v.thr):
                        v.thr = lo
                    if not np.isfinite(v.ymin) or not np.isfinite(v.ymax):
                        v.ymin, v.ymax = lo, hi + 1.0
        self.dirty()

    def make_view(self, metric: Metric | None = None, **over) -> ViewState:
        """按会话默认值(外加覆盖项)生成一个新视图状态(每个窗口一份)。"""
        v = ViewState(
            xmin=self.xmin, xmax=self.xmax, Lmin=self.Lmin, Lmax=self.Lmax,
            ymin=self.ymin, ymax=self.ymax, xlog=self.xlog, Llog=self.Llog,
            npts=self.npts, clean=dict(self.clean), lookup_on=self.lookup_on,
            thr=self.thr, direction=self.direction,
            display_mode=self.display_mode, x_metric=self.x_metric,
        )
        if metric is not None:
            # 单参数窗口: 按该参数自身的数据范围给默认值与阈值(方向随指标类型)
            prof = getattr(metric, "profile", None)
            if prof is not None and getattr(prof, "direction", None):
                v.direction = prof.direction
            self.default_ranges(v, [metric])
        for k, val in over.items():
            setattr(v, k, val)
        return v
        self.dirty()


def _pick_prefix(vals, base_unit):
    from gmidlib.metrics import pick_display
    return pick_display(vals, base_unit)
