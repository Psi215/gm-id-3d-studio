# -*- coding: utf-8 -*-
"""
反向设计查表(通用指标版)
=========================
给定指标阈值, 在 (gm/ID, L) 曲面上找出全部可行区。

阈值比较在**显示域**进行(调用方已把原始值换算成显示单位: 增益 dB、
fT GHz、vdsat mV、Inor µA/µm 等), 并带方向:
  direction='max'  (默认): 指标 ≥ 阈值 视为可行 —— 增益/fT 等“越大越好”;
  direction='min'        : 指标 ≤ 阈值 视为可行 —— vdsat/vgs/电流等“上限约束”。

推荐点取可行区“贴阈值的那一端”:
  max -> 区间最左(最小 gm/ID, 最强反型, 保速度);
  min -> 区间最右(最接近上限、不浪费裕量)。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class LookupRow:
    L_um: float
    x_lo: float            # 可行区间的 gm/ID 下界
    x_hi: float            # 可行区间的 gm/ID 上界
    x_rec: float           # 推荐设计点 gm/ID(贴阈值端)
    value_rec: float       # 推荐点指标值(显示单位)
    n_pts: int             # 栅格上满足条件的点数


@dataclass
class LookupResult:
    rows: list = field(default_factory=list)
    region: np.ndarray = None       # (nL, n) bool, 与 Ls/xs 对齐
    xs: np.ndarray = None
    Ls: np.ndarray = None
    thr: float = 0.0                # 阈值(显示单位)
    direction: str = "max"

    @property
    def ok(self) -> bool:
        return bool(self.rows)


def _contiguous_true(mask: np.ndarray, min_pts: int = 1):
    """把布尔向量拆成连续区间 [(i0, i1), ...](闭开)。"""
    out = []
    n = mask.size
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            if (j - i) >= min_pts:
                out.append((i, j))
            i = j
        else:
            i += 1
    return out


def run_lookup(Z_disp: np.ndarray, xs: np.ndarray, Ls: np.ndarray,
               thr: float, direction: str = "max",
               min_pts: int = 2) -> LookupResult:
    """在 (L, gm/ID) 子网格上反查可行区。

    Z_disp   : (nL, n) 指标显示域网格(与 Ls/xs 行、列对齐)
    direction: 'max' 可行 = 值 ≥ thr; 'min' 可行 = 值 ≤ thr
    """
    xs = np.asarray(xs, float)
    Ls = np.asarray(Ls, float)
    Z_disp = np.asarray(Z_disp, float)
    direction = "max" if direction not in ("max", "min") else direction
    res = LookupResult(xs=xs, Ls=Ls, thr=float(thr), direction=direction)
    nL, nX = Z_disp.shape
    if nL == 0 or nX == 0:
        return res
    region = np.zeros((nL, nX), bool)
    for r in range(nL):
        row = Z_disp[r]
        mask = np.isfinite(row) & ((row >= float(thr)) if direction == "max"
                                   else (row <= float(thr)))
        region[r, :] = mask
        for (i0, i1) in _contiguous_true(mask, min_pts):
            if direction == "max":
                idx_rec = i0                # 贴阈值的最左端
            else:
                idx_rec = i1 - 1            # 贴上限的最右端
            res.rows.append(LookupRow(
                L_um=float(Ls[r]),
                x_lo=float(xs[i0]),
                x_hi=float(xs[i1 - 1]),
                x_rec=float(xs[idx_rec]),
                value_rec=float(row[idx_rec]),
                n_pts=int(mask.sum()),
            ))
    res.region = region
    return res


def summarize(res: LookupResult, unit: str = "") -> str:
    if not res.ok:
        return (f"{'≥' if res.direction == 'max' else '≤'} {res.thr:.4g}"
                f" {unit}:所选范围内无可行 (gm/ID, L)")
    nL = len({r.L_um for r in res.rows})
    if res.direction == "max":
        x_best = min(r.x_rec for r in res.rows)
        x_word = "最小可行 gm/ID"
    else:
        x_best = max(r.x_rec for r in res.rows)
        x_word = "最大可行 gm/ID"
    return (f"{len(res.rows)} 个可行区间 / {nL} 个 L 可用; "
            f"{x_word} ≈ {x_best:.3g} 1/V"
            + (f" ({unit})" if unit else ""))
