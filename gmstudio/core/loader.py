# -*- coding: utf-8 -*-
"""文件装载: 支持“全部参数宽表”(如 total.csv)、旧版每指标宽表、长表、两列。"""
from __future__ import annotations

import os
import re

import numpy as np

from .. import __version__
from .model import Curve, Metric, Source

# 复用旧解析器的底层读取(编码/分隔符探测)
import gmidlib.parse as _gp
from gmidlib import metrics as _gm

AXIS_SUFFIX = re.compile(
    r"^\s*(?P<base>.+?)\s*(?:\((?P<inner>[^()]*)\))?\s*(?P<axis>[XY])\s*$")
L_IN_HEADER = re.compile(r"(?i)\bL\s*=\s*(?P<val>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")
NUM_RE = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")


def _to_float(s):
    s = (s or "").strip()
    if not s or not NUM_RE.match(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _l_um(text: str):
    m = L_IN_HEADER.search(text or "")
    if not m:
        return None
    v = float(m.group("val"))
    factor, _unit = _gp._pick_unit([v])
    return v * factor


def _metric_name(base: str, path: str):
    prof = _gm.detect_metric(base)
    return base, prof


def load_file(path: str) -> Source:
    """装载一个文件 -> Source。自适应识别版式。"""
    label = os.path.splitext(os.path.basename(path))[0]
    header, data_rows = _gp._read_csv(path)
    src = Source(path=path, label=label)

    # ---- 版式 A: 宽表, 列头成对 X/Y ----
    parsed = [AXIS_SUFFIX.match(h) for h in header]
    if all(m is not None for m in parsed) and len(header) >= 2:
        return _load_wide(src, header, data_rows, parsed)

    # ---- 版式 B/C/D: 交给旧解析器, 转成 Metric 模型 ----
    try:
        dss = _gp.parse_file(path)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"无法解析 {label}: {e}") from e
    for d in dss:
        m = Metric(base=d.metric, display=d.metric,
                   source_label=label, source_path=src.path,
                   x_name=getattr(d, "x_name", "X"),
                   profile=getattr(d, "profile", None),
                   raw_db=bool(getattr(d, "raw_db", False)))
        for s in d.series:
            x = s.x_c if s.x_c is not None else s.x
            y = s.y_c if s.y_c is not None else s.y
            if x is None or y is None or x.size < 2:
                continue
            m.curves.append(Curve(s.param_um, x, y))
        m.note = "; ".join(d.notes[:2])
        src.metrics[m.base] = m
    src.n_rows = max(len(r) for r in data_rows)
    return src


def _load_wide(src: Source, header, data_rows, parsed) -> Source:
    """全部参数的宽表(每参数 × 每 L 一对 X/Y 列)。"""
    groups: dict[tuple, dict] = {}
    order: list[tuple] = []
    for i, m in enumerate(parsed):
        base = m.group("base").strip()
        inner = m.group("inner") or ""
        lv = _l_um(inner)
        key = (base, lv)
        if key not in groups:
            groups[key] = {"x": [], "y": []}
            order.append(key)
        groups[key]["x" if m.group("axis") == "X" else "y"].append(i)

    def col_values(ci: int):
        out = []
        for row in data_rows:
            if ci >= len(row):
                out.append(np.nan)
                continue
            v = _to_float(row[ci])
            out.append(v if v is not None else np.nan)
        return np.asarray(out, float)

    for (base, lv) in order:
        g = groups[(base, lv)]
        if not g["x"] or not g["y"] or len(g["x"]) != len(g["y"]):
            continue
        g["x"].sort(); g["y"].sort()
        metric = src.metrics.get(base)
        if metric is None:
            name, prof = _metric_name(base, src.path)
            metric = Metric(base=base, display=name,
                            source_label=src.label, source_path=src.path,
                            x_name=src.x_name, profile=prof,
                            raw_db=_gm.is_raw_db(base, prof))
            src.metrics[base] = metric
        for xi, yi in zip(g["x"], g["y"]):
            x = col_values(xi)
            y = col_values(yi)
            # 保留含 NaN 的等长数组: 换 X 轴时按“行索引”与其它参数配对
            metric.curves.append(Curve(lv, x, y))
    src.n_rows = len(data_rows)
    src.notes.append(f"宽表: {len(src.metrics)} 个参数, "
                     f"共 {sum(m.n_curves for m in src.metrics.values())} 条曲线")
    return src


def load_files(paths: list[str]) -> tuple[dict, list]:
    """批量装载 -> ({path: Source}, errors)。目录会递归收集数据文件。"""
    files = []
    for p in paths:
        if os.path.isdir(p):
            exts = {".csv", ".txt", ".dat", ".tsv"}
            for root, _, names in os.walk(p):
                for n in sorted(names):
                    if os.path.splitext(n)[1].lower() in exts:
                        files.append(os.path.join(root, n))
        else:
            files.append(p)
    out, errors = {}, []
    for f in files:
        try:
            out[f] = load_file(f)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{os.path.basename(f)}: {e}")
    return out, errors
