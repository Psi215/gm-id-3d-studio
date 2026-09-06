# -*- coding: utf-8 -*-
"""数据模型: 一次导入文件里的“全部参数”, 但不立即绘图。"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Curve:
    """一条 (X, Y) 曲线, 属于某个参数的某个 L。"""
    L_um: float | None
    x: np.ndarray
    y: np.ndarray
    x_c: np.ndarray | None = None     # 清洗后
    y_c: np.ndarray | None = None
    note: str = ""                    # 清洗备注(gmidlib.clean 需要)


@dataclass
class Metric:
    """一个参数(指标)的全部曲线族。"""
    base: str                 # 原始列名基名, 如 "M0:1" / "selfgain"
    display: str              # 显示名(可重命名)
    source_label: str         # 来源文件标签
    x_name: str = "X"         # X 轴名称(可重命名, 如 "vgs (V)")
    profile: object = None    # gmidlib.metrics.MetricProfile
    raw_db: bool = False
    curves: list = field(default_factory=list)   # list[Curve]
    note: str = ""

    def series_cleaned(self):
        out = []
        for c in self.curves:
            x = c.x_c if c.x_c is not None else c.x
            y = c.y_c if c.y_c is not None else c.y
            if x is None or y is None:
                continue
            ok = np.isfinite(x) & np.isfinite(y)
            if ok.sum() < 2:
                continue
            out.append((c.L_um, x[ok], y[ok]))
        out.sort(key=lambda t: (t[0] is None, t[0] or 0.0))
        return out

    @property
    def n_curves(self):
        return len(self.curves)

    @property
    def L_range(self):
        ls = [c.L_um for c in self.curves if c.L_um is not None]
        return (min(ls), max(ls)) if ls else (None, None)


@dataclass
class Source:
    """一个数据文件。metrics 按 base 索引, 全部驻留内存。"""
    path: str
    label: str = ""
    metrics: dict = field(default_factory=dict)    # base -> Metric
    x_name: str = "X"
    notes: list = field(default_factory=list)
    n_rows: int = 0

    def sorted_metrics(self):
        return sorted(self.metrics.values(),
                      key=lambda m: _natural_key(m.base))


def _natural_key(s: str):
    import re
    parts = re.split(r"(\d+)", s)
    return [int(p) if p.isdigit() else p for p in parts]
