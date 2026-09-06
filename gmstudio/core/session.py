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

_CLEAN_STATE = dict(drop_fold=True, sort_x=True, smooth=False,
                    window=9, order=2, outlier=False, k_mad=5.0)


class Session:
    """所有窗口共享的数据与状态。"""

    def __init__(self):
        self.sources: dict[str, Source] = {}
        self.checked: dict[str, set] = {}       # path -> set(base)
        self.active: tuple[str, str] | None = None  # 当前 3D/查表指标
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
        self._display_cache: dict = {}
        self._dirty = True

    # ---------------- 数据装载 / 选择 ----------------
    def add_source(self, src: Source):
        self._display_cache = {
            k: v for k, v in self._display_cache.items() if k[0] != src.path
        }
        self.sources[src.path] = src
        self.checked.setdefault(src.path, set())
        self._load_meta(src)
        # 默认只勾选第一个参数(全部导入, 但只显示选中的)
        if not self.checked[src.path] and src.metrics:
            first = next(iter(src.sorted_metrics()))
            self.checked[src.path].add(first.base)
        if self.active is None and self.checked[src.path]:
            self.set_active(src.path, next(iter(self.checked[src.path])))
        self.dirty()

    def remove_all(self):
        self.sources.clear(); self.checked.clear(); self.active = None
        self._surf_cache.clear(); self._lookup_cache.clear()
        self._display_cache.clear()
        self.dirty()

    def toggle(self, path: str, base: str, on: bool):
        if path not in self.checked:
            return
        s = self.checked[path]
        if on:
            s.add(base)
        else:
            s.discard(base)
        if self.active == (path, base) and not on:
            self.active = None
            for p, bases in self.checked.items():
                if bases:
                    self.set_active(p, next(iter(bases)))
                    break
        elif self.active is None and on:
            self.set_active(path, base)
        self.dirty()

    def set_active(self, path: str, base: str):
        src = self.sources.get(path)
        if src is None or not base or base not in src.metrics:
            return
        self.active = (path, base)
        m = src.metrics[base]
        if m.profile is not None:
            self.direction = m.profile.direction
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
        if self.active is not None:
            path, base = self.active
            src = self.sources.get(path)
            if src and base in src.metrics:
                return src.metrics[base]
        return None

    def dirty(self):
        self._surf_cache.clear()
        self._lookup_cache.clear()
        self._eff_cache.clear()

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
        self._display_cache = {
            k: v for k, v in self._display_cache.items()
            if k[:2] != (m.source_path, m.base)
        }
        self.save_meta(src)
        self.dirty()

    # ---------------- 显示换算(默认原始值) ----------------
    def disp(self, m: Metric, y, **kw):
        """按会话显示模式把原始值换算成显示值。"""
        mode = kw.get("mode", self.display_mode)
        a = np.asarray(y, float)
        prof = m.profile
        if mode == DB_DEFAULT and prof is not None and prof.db_capable:
            if m.raw_db:
                return a
            with np.errstate(divide="ignore"):
                return np.where(np.isfinite(a) & (a > 0),
                                20.0 * np.log10(a), -np.inf)
        if mode == PREFIX_DEFAULT and prof is not None and prof.unit:
            fac, _ = self._metric_display(m)
            return a * fac
        return a

    def unit_str(self, m: Metric | None, mode=None) -> str:
        mode = mode if mode is not None else self.display_mode
        if m is None:
            return ""
        if mode == DB_DEFAULT and m.profile is not None \
                and m.profile.db_capable:
            return "dB"
        if mode == PREFIX_DEFAULT and m.profile is not None and m.profile.unit:
            return self._metric_display(m)[1]
        return m.profile.unit if m.profile is not None else ""

    def _metric_display(self, m: Metric):
        """为一个指标固定工程前缀，避免不同曲线使用不同刻度。"""
        prof = m.profile
        if prof is None or not prof.unit:
            return 1.0, ""
        key = (m.source_path, m.base, prof.unit)
        if key in self._display_cache:
            return self._display_cache[key]
        vals = [np.asarray(c.y, float).ravel() for c in m.curves
                if c.y is not None and np.asarray(c.y).size]
        data = np.concatenate(vals) if vals else np.array([1.0])
        result = _pick_prefix(data, prof.unit)
        self._display_cache[key] = result
        return result

    # ---------------- X 轴选择 / 配对 / 清洗 ----------------
    def x_metric_obj(self) -> Metric | None:
        if self.x_metric:
            src = self.sources.get(self.x_metric[0])
            if src is not None:
                return src.metrics.get(self.x_metric[1])
        return None

    def x_label(self) -> str:
        xm = self.x_metric_obj()
        if xm is not None:
            return xm.display
        am = self.active_metric()
        return am.x_name if am is not None else "X"

    def _clean_sig(self):
        c = self.clean
        return (c["drop_fold"], c["sort_x"], c["smooth"], c["window"],
                c["order"], c["outlier"], c["k_mad"])

    def effective_series(self, m: Metric):
        """返回 (L, x, y) 列表: 若选了 X 轴参数, 则 Y 与所选 X 按行索引
        配对后再清洗排序; 否则用参数自带的 X 列。结果按清洗参数缓存。"""
        key = (m.source_path, m.base,
               tuple(self.x_metric) if self.x_metric else None,
               self._clean_sig())
        if key in self._eff_cache:
            return self._eff_cache[key]
        sers = self._build_effective(m)
        self._eff_cache[key] = sers
        return sers

    def _build_effective(self, m: Metric):
        xm = self.x_metric_obj()
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
                tc, drop_fold=self.clean["drop_fold"],
                sort_x=self.clean["sort_x"], smooth=self.clean["smooth"],
                window=self.clean["window"], order=self.clean["order"],
                outlier=self.clean["outlier"], k_mad=self.clean["k_mad"])
            if tc.x_c is not None and tc.x_c.size >= 2:
                out.append((tc.L_um, tc.x_c, tc.y_c))
        out.sort(key=lambda t: (t[0] is None, t[0] or 0.0))
        return out

    def clean_metric(self, m: Metric) -> str:
        """触发(并缓存)当前 X 轴选择下的清洗。"""
        self.effective_series(m)
        return "ok"

    # ---------------- 曲面 / 查表 ----------------
    def surface_of(self, m: Metric) -> dict | None:
        key = (m.source_path, m.base, self.xmin, self.xmax, self.Lmin,
               self.Lmax, self.npts, self.xlog,
               tuple(self.x_metric) if self.x_metric else None,
               self._clean_sig())
        if key in self._surf_cache:
            return self._surf_cache[key]
        sers = [(l, x, y) for (l, x, y) in self.effective_series(m)
                if l is not None and self.Lmin <= l <= self.Lmax]
        if len(sers) < 1:
            return None
        xs_all = np.concatenate([x for _, x, _ in sers])
        if xs_all.size == 0 or not np.isfinite(xs_all).any() \
                or float(np.ptp(xs_all[np.isfinite(xs_all)])) <= 0:
            return None                       # 常数 X(如参数自带值)退化
        xmin, xmax = self.xmin, self.xmax
        if self.xlog:
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
                                        n=int(self.npts), xlog=self.xlog)
        except Exception:
            return None
        sf["sers"] = sers
        self._surf_cache[key] = sf
        return sf

    def lookup_of(self, m: Metric) -> object | None:
        sf = self.surface_of(m)
        if sf is None or not np.isfinite(sf["Z"]).any():
            return None
        key = (m.source_path, m.base, self.thr, self.direction,
               self.display_mode)
        if key in self._lookup_cache:
            return self._lookup_cache[key]
        Zd = self.disp(m, sf["Z"], mode=self.display_mode)
        res = _lookup.run_lookup(Zd, sf["xs"], sf["Ls"], float(self.thr),
                                 direction=self.direction)
        self._lookup_cache[key] = res
        return res

    def default_ranges(self):
        """依据所有已勾选参数并集(当前 X 轴选择下)设置默认范围与阈值。"""
        xs_all, Ls = [], []
        for m in self.checked_metrics():
            for (l, x, y) in self.effective_series(m):
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
        self.xmin, self.xmax = xlo - pad, xhi + pad
        if Ls:
            Larr = np.array(Ls, float)
            self.Lmin = max(0.0, float(Larr.min()) * 0.9)
            self.Lmax = float(Larr.max()) * 1.1
        am = self.active_metric()
        if am is not None:
            sf = self.surface_of(am)
            if sf is not None and np.isfinite(sf["Z"]).any():
                Zd = self.disp(am, sf["Z"], mode=self.display_mode)
                fin = Zd[np.isfinite(Zd)]
                if fin.size:
                    lo, hi = float(fin.min()), float(fin.max())
                    self.ymin = lo - 0.05 * (hi - lo)
                    self.ymax = hi + 0.05 * (hi - lo)
                    prof = am.profile
                    direction = self.direction or (
                        prof.direction if prof is not None else "max")
                    if direction == "max":
                        self.thr = lo + 0.8 * (hi - lo)
                    else:
                        self.thr = lo + 0.2 * (hi - lo)
                    if not np.isfinite(self.thr):
                        self.thr = lo
                    if not np.isfinite(self.ymin) or not np.isfinite(self.ymax):
                        self.ymin, self.ymax = lo, hi + 1.0
        self.dirty()


def _pick_prefix(vals, base_unit):
    from gmidlib.metrics import pick_display
    return pick_display(vals, base_unit)
