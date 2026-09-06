# -*- coding: utf-8 -*-
"""
公共栅格插值 -> 曲面数据
========================
不同 L 的曲线各自有独立的 gm/ID 栅格(宽表导出通常如此), 要画
z = f(gm/ID, L) 必须先插值到公共 gm/ID 栅格。这里:
  * 每条 L 用 PCHIP(单调保形三次)插值, 不引入龙格振荡;
  * 超出该 L 实测范围处自动置 NaN(曲面被裁剪到真实覆盖区);
  * L 轴使用各曲线真实 L 值(µm), 支持线性/对数 X 栅格。
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator


def cleaned_series_of(ds, require_param=True):
    sers = []
    for s in ds.series:
        if require_param and not s.has_param:
            continue
        x = s.x_c if s.x_c is not None else s.x
        y = s.y_c if s.y_c is not None else s.y
        if x is None or y is None or x.size < 2:
            continue
        sers.append((s.param_um, np.asarray(x, float), np.asarray(y, float)))
    sers.sort(key=lambda t: (t[0] is None, t[0] or 0.0))
    return sers


def coverage(sers):
    """返回各条曲线 X 范围 -> (minmax_all, 交叠区)。"""
    if not sers:
        return None
    lo = max(float(np.min(s[1])) for s in sers)
    hi = min(float(np.max(s[1])) for s in sers)
    all_lo = min(float(np.min(s[1])) for s in sers)
    all_hi = max(float(np.max(s[1])) for s in sers)
    return (all_lo, all_hi), (lo, hi)


def build_surface(sers, xmin=None, xmax=None, n: int = 200,
                  xlog: bool = False):
    """sers: [(L_um, x, y), ...] 见 cleaned_series_of。
    返回 dict: {Ls, xs, Z, xlog, xmin_used, xmax_used, valid}。
    Z 形状 (len(Ls), n), 无效处为 NaN。
    """
    if len(sers) < 1:
        raise ValueError("没有可用于曲面的数据(需含 L 参数且点数足够)")
    cov = coverage(sers)
    (alo, ahi), (ilo, ihi) = cov
    if xmin is None:
        xmin = max(ilo, ahi * 1e-6) if ahi > 0 else ilo
    if xmax is None:
        xmax = ihi
    if xmin >= xmax:
        # 交叠区为空 -> 退化为各曲线并集范围, 保证能画
        xmin, xmax = alo, ahi
    n = int(n)
    if xlog:
        if xmin <= 0:
            xmin = float(np.nextafter(0.0, 1.0))
        xs = np.geomspace(float(xmin), float(xmax), n)
    else:
        xs = np.linspace(float(xmin), float(xmax), n)

    Ls = np.array([s[0] for s in sers], float)
    Z = np.full((len(sers), n), np.nan)
    for r, (_, x, y) in enumerate(sers):
        # 仅当该条曲线覆盖栅格端点时才插值
        if x.size < 2:
            continue
        if xs[0] > np.max(x) or xs[-1] < np.min(x):
            continue
        p = PchipInterpolator(x, y, extrapolate=False)
        zr = p(xs)  # 栅格超出实测范围 -> NaN
        Z[r, :] = zr
    return {
        "Ls": Ls, "xs": xs, "Z": Z, "xlog": xlog,
        "xmin_used": float(xs[0]), "xmax_used": float(xs[-1]),
        "valid": int(np.isfinite(Z).sum()),
    }


def grid_db(Z):
    """线性增益 -> dB(20log10), 非正/无效置 -inf。"""
    Zd = np.full_like(Z, -np.inf, dtype=float)
    pos = np.isfinite(Z) & (Z > 0)
    Zd[pos] = 20.0 * np.log10(np.abs(Z[pos]))
    return Zd


def slice_at_x(sers, xval):
    """固定 gm/ID -> 各 L 处的指标值(L 剖面)。返回 (Ls, vals, ok)。"""
    Ls, vals = [], []
    for (l, x, y) in sers:
        if xval < np.min(x) or xval > np.max(x):
            Ls.append(l); vals.append(np.nan); continue
        p = PchipInterpolator(x, y, extrapolate=False)
        Ls.append(l); vals.append(float(p(xval)))
    return np.array(Ls, float), np.array(vals, float)


def slice_at_L(sers, L_um, tol_frac=0.02):
    """固定 L -> 找最近的 Series 返回其 (x, y)。"""
    best, bd = None, np.inf
    for (l, x, y) in sers:
        if l is None:
            continue
        d = abs(l - L_um)
        if d < bd:
            bd, best = d, (x, y)
    if best is None:
        return None
    # 容许误差: 若没有精确匹配的 L, 仍返回最近的一条(由调用方提示)
    return best
