# -*- coding: utf-8 -*-
"""
数据清洗
========
对每条 Series(按导出顺序, X 为扫描自变量)做:
  1. 回折剔除: gm/ID 扫描经常在弱反型端出现“先升后降 / 先降后升”的头部回折,
     这里检测并仅保留从全局极值点开始的单调主支(只作用于确实存在干净长尾的情形)。
  2. 按 X 排序 + 去重。
  3. (可选) Savitzky-Golay 平滑。
  4. (可选) MAD 坏点剔除: 相对平滑基线的残差超过 k×MAD 的点被剔除。
清洗结果写入 Series.x_c / y_c, 备注写入 Series.note。
"""
from __future__ import annotations

from typing import Optional

import numpy as np


def _monotone_ok(tail: np.ndarray, decreasing: bool, tol_frac: float = 0.05) -> bool:
    if tail.size < 3:
        return True
    d = np.diff(tail)
    bad = (d > 0).sum() if decreasing else (d < 0).sum()
    return int(bad) <= max(1, int(tol_frac * d.size))


def fold_cut_index(x: np.ndarray) -> Optional[int]:
    """若头部存在回折, 返回应保留的起始下标; 否则 None。"""
    n = int(x.size)
    if n < 8:
        return None
    imax = int(np.argmax(x))
    imin = int(np.argmin(x))

    def tail_ok(start: int, decreasing: bool) -> bool:
        if start >= n - 1:
            return False
        if (n - start) < 0.35 * n:      # 主支须占相当比例
            return False
        return _monotone_ok(x[start:], decreasing)

    # 驼峰头: 前面上升一段后在 imax 见顶, 之后是干净的长下降主支
    if 0 < imax <= 0.6 * n and tail_ok(imax, decreasing=True):
        return imax
    # 谷头: 前面下降一段后在 imin 见底, 之后是干净的长上升主支
    if 0 < imin <= 0.6 * n and tail_ok(imin, decreasing=False):
        return imin
    return None


def _savgol(y: np.ndarray, window: int, order: int) -> np.ndarray:
    from scipy.signal import savgol_filter
    w = int(window)
    if w < 3 or w % 2 == 0:
        w = 5
    if w > y.size:
        w = y.size if y.size % 2 == 1 else y.size - 1
    if w < 3:
        return y.copy()
    o = min(int(order), w - 1, 4)
    if o < 1:
        return y.copy()
    try:
        return savgol_filter(y, w, o, mode="interp")
    except Exception:
        return y.copy()


def clean_series(s, drop_fold: bool = True, sort_x: bool = True,
                 smooth: bool = False, window: int = 7, order: int = 2,
                 outlier: bool = False, k_mad: float = 5.0) -> dict:
    """清洗单条 Series。s 需有 .x/.y(原始), 结果写 .x_c/.y_c。
    返回统计信息 {保留点数, 剔除点数, 备注}。"""
    x = np.asarray(s.x, float)
    y = np.asarray(s.y, float)
    notes = []
    stats = {"dropped": 0, "kept": int(x.size)}

    if x.size < 2:
        s.x_c, s.y_c = x, y
        return {**stats, "note": "点数不足"}

    mask = np.ones(x.size, bool)

    # 1) 回折剔除
    if drop_fold:
        cut = fold_cut_index(x)
        if cut is not None:
            n_before = int(mask.sum())
            mask[:cut] = False
            notes.append(f"剔除扫描头部回折 {cut} 点")
            stats["dropped"] += n_before - int(mask.sum())

    # 2) 排序 + 去重(按 X)
    #    注意: 别用 order 做排序变量名——它是“多项式阶数”参数, 会被覆盖成数组
    sort_idx = np.argsort(x[mask], kind="stable")
    idx = np.nonzero(mask)[0][sort_idx]
    xi = x[idx]
    yi = y[idx]
    if sort_x and xi.size > 1:
        dup = np.empty(xi.size, bool)
        dup[0] = False
        dup[1:] = np.isclose(xi[1:], xi[:-1], rtol=1e-9, atol=0)
        if dup.any():
            n_d = int(dup.sum())
            keep = ~dup
            xi, yi = xi[keep], yi[keep]
            notes.append(f"去重 {n_d} 点")
            stats["dropped"] += n_d

    # 3) 平滑
    if smooth and yi.size >= 5:
        yi = _savgol(yi, window, order)

    # 4) MAD 坏点剔除(相对平滑基线)
    if outlier and yi.size >= 9:
        base = _savgol(yi, min(11, yi.size if yi.size % 2 else yi.size - 1), 2)
        res = yi - base
        mad = np.median(np.abs(res - np.median(res))) or 1e-12
        bad = np.abs(res) > float(k_mad) * 1.4826 * mad
        # 两端各保底 1 点, 且最多剔除 30%
        if bad.sum() > 0 and bad.sum() < 0.3 * yi.size:
            bad[0] = bad[-1] = False
            n_b = int(bad.sum())
            xi, yi = xi[~bad], yi[~bad]
            notes.append(f"MAD 剔除 {n_b} 个坏点(k={k_mad})")
            stats["dropped"] += n_b

    s.x_c = np.asarray(xi, float)
    s.y_c = np.asarray(yi, float)
    stats["kept"] = int(s.x_c.size)
    if notes:
        s.note = s.note + (" | " if s.note else "") + "; ".join(notes)
    return {**stats, "note": "; ".join(notes) if notes else "无需清洗"}


def clean_dataset(ds, drop_fold=True, sort_x=True, smooth=False,
                  window=7, order=2, outlier=False, k_mad=5.0) -> list:
    """清洗 Dataset 的全部 Series, 返回每条统计。"""
    out = []
    for s in ds.series:
        st = clean_series(s, drop_fold, sort_x, smooth, window, order,
                          outlier, k_mad)
        st["L"] = s.param_um
        out.append(st)
    return out
