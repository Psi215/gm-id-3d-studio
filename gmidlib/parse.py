# -*- coding: utf-8 -*-
"""
自适应数据解析器
================
把常见 Cadence Calculator / WaveScan / AWAVE / Virtuoso 导出的 gm/ID 类曲线文件
统一解析为 Dataset(每个指标一个 Dataset, 每条 L 一条 Series)。支持四类版式:

  A. 宽表(参数在列头):  列头成对出现且末位为 X/Y,
     参数 L 编码在括号里, 例如
         "selfgain (L=5.5e-07) X, selfgain (L=5.5e-07) Y, ..."
     同一指标的多个 L 自动合并为一个 Dataset(每个 L 一条 Series)。
  B. 宽表(多指标、无参数): 列头成对出现 X/Y, 但括号里没有 L=...,
     如 "gm/id (1/V) X, gm/id (1/V) Y, ft X, ft Y" -> 每个指标一个 Dataset,
     Series 参数为 None。
  C. 长表: 每行一个采样点, 含参数列(如 L/长度) + X 列(如 gm/id) + 一个或多个指标列。
  D. 简单两列: 只有 X、Y 两列(无参数), 单条曲线。

分隔符自动探测(逗号 / 分号 / 制表符), 编码按 utf-8(-sig) -> gb18030 回退。
所有参数值统一换算成 µm 存储(Series.param_um), X/Y 保持原始数值。
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np

# --------------------------------------------------------------------------
# 正则 / 别名
# --------------------------------------------------------------------------
AXIS_SUFFIX = re.compile(
    r"^\s*(?P<base>.+?)\s*(?:\((?P<inner>[^()]*)\))?\s*(?P<axis>[XY])\s*$"
)
PARAM_IN_HEADER = re.compile(
    r"(?i)\bL\s*=\s*(?P<val>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
)
NUM_RE = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")

# 长表中“参数列 / X列”的常见命名(已小写、去空格)
PARAM_NAMES = {
    "l", "l(m)", "l(um)", "l(µm)", "length", "len", "lch", "l_ch",
    "channellength", "channel_length", "l(μ m)",
}
X_NAMES = {
    "gmid", "gm_id", "gm/id", "gmoverid", "gm/id(1/v)", "gm_id(1/v)",
    "x", "gm/id(v^-1)", "gm/id(a/a)", "gm_over_id",
}
# 明确是“扫描自变量”但名字不在上面的常见列(避免把指标列当 X)
X_CONTAINS = ("gm/id", "gmid", "gm_id", "gmoverid")

DEFAULT_X_LABEL = "gm/ID (1/V)"


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", name).lower()


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------
@dataclass
class Series:
    """一条以 L 为参数的曲线: 自有 X 栅格(x) 与 指标 y。"""
    param_um: Optional[float]      # L, 统一为 µm; 未知为 None
    x: np.ndarray
    y: np.ndarray
    label: str = ""                # 例如 "L=0.55 µm" 或原始头
    note: str = ""                 # 解析/清洗备注
    # 清洗后(clean.py 结果)填充:
    x_c: Optional[np.ndarray] = None
    y_c: Optional[np.ndarray] = None

    @property
    def has_param(self) -> bool:
        return self.param_um is not None


@dataclass
class Dataset:
    """一个指标的一组曲线(通常按 L 分列)。"""
    key: str                        # 唯一键: "<文件路径>#<指标名>"
    file: str                       # 来源文件路径
    name: str                       # 显示名 = 文件名主干#指标
    metric: str                     # 指标名, 例如 "selfgain"
    x_name: str = "X"
    y_name: str = "Y"
    series: list = field(default_factory=list)      # list[Series]
    notes: list = field(default_factory=list)       # 解析过程备注
    file_group: str = ""            # 批量时的分组标签(默认文件名主干)
    # ---- 指标适配(metrics.py 附加) ----
    profile: object = None          # MetricProfile
    disp_factor: float = 1.0        # 显示值 = 原始值 × disp_factor
    disp_unit: str = ""             # 显示单位(含工程前缀), 如 GHz / µA
    raw_db: bool = False            # 原始数据是否已是 dB

    def sorted_by_param(self) -> list:
        return sorted(self.series, key=lambda s: (s.param_um is None, s.param_um or 0.0))

    @property
    def y_label(self) -> str:
        return self.metric if self.metric else self.y_name


# --------------------------------------------------------------------------
# 底层读取
# --------------------------------------------------------------------------
def _read_text_lines(path: str):
    data = None
    for enc in ("utf-8-sig", "gb18030", "latin-1"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                data = f.read()
            break
        except UnicodeDecodeError:
            continue
    if data is None:
        raise ValueError(f"无法解码文件: {path}")
    return data.splitlines()


def _detect_delimiter(raw_lines: list, header: list) -> str:
    if len(raw_lines) == 0:
        return ","
    sample = "\n".join(raw_lines[:5])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except Exception:
        return ","


def _read_csv(path: str):
    """返回 (headers, rows); rows 是字符串二维表。"""
    raw_lines = [ln for ln in _read_text_lines(path) if ln.strip() != ""]
    if not raw_lines:
        raise ValueError(f"空文件: {path}")
    delim = _detect_delimiter(raw_lines, None)
    reader = csv.reader(raw_lines, delimiter=delim)
    rows = [r for r in reader if any(c.strip() != "" for c in r)]
    if not rows:
        raise ValueError(f"没有读到数据: {path}")
    header = [c.strip() for c in rows[0]]
    # 有些导出把表头分成两行(如 “L” 上还有单位行), 这里只取第一行做启发式
    data_rows = rows[1:]
    return header, data_rows


def _to_float(s: str) -> Optional[float]:
    s = (s or "").strip()
    if not s:
        return None
    if not NUM_RE.match(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# 宽表解析
# --------------------------------------------------------------------------
def _parse_wide(header, data_rows, path, file_group):
    """返回 list[Dataset]。"""
    parsed = []
    for h in header:
        m = AXIS_SUFFIX.match(h)
        if not m:
            return None  # 不是宽表
        parsed.append(m)
    xs = [i for i, m in enumerate(parsed) if m.group("axis") == "X"]
    ys = [i for i, m in enumerate(parsed) if m.group("axis") == "Y"]
    if not xs or len(xs) != len(ys) or len(xs) + len(ys) != len(header):
        return None

    # 以 (指标基名, 参数值) 分组
    groups: dict[tuple, dict] = {}
    order = []
    for i, m in enumerate(parsed):
        base = m.group("base").strip()
        inner = m.group("inner") or ""
        pm = PARAM_IN_HEADER.search(m.group("inner") or "")
        pval = float(pm.group("val")) if pm else None
        # 指标基名: 去掉单位噪音(如 “selfgain(linear)”)——保持原样即可, 但去首尾空格
        key = (base, pval)
        if key not in groups:
            groups[key] = {"x": [], "y": []}
            order.append(key)
        groups[key]["x" if i in xs else "y"].append(i)

    datasets = []
    for (base, pval) in order:
        g = groups[(base, pval)]
        if not g["x"] or not g["y"] or len(g["x"]) != len(g["y"]):
            continue
        for k in ("x", "y"):
            g[k].sort()
        cols_x, cols_y = g["x"], g["y"]

        # 若同一 (base,pval) 出现多次且都匹配成对, 取第一次; 一般不会发生
        cols_x = cols_x[: len(cols_y)]
        series_list = []
        for xi, yi in zip(cols_x, cols_y):
            xrow, yrow = [], []
            for row in data_rows:
                if max(xi, yi) >= len(row):
                    continue
                xv, yv = _to_float(row[xi]), _to_float(row[yi])
                if xv is None or yv is None:
                    continue
                xrow.append(xv)
                yrow.append(yv)
            if len(xrow) < 2:
                continue
            series_list.append(
                Series(param_um=pval, x=np.asarray(xrow, float),
                       y=np.asarray(yrow, float), label=str(pval))
            )
        if not series_list:
            continue
        # 多个 (base,pval) 因 pval 不同而分成多组时, 应合并成同一 Dataset
        # 因此这里按 base 聚合所有 series, 而不是按 (base,pval) 单个建
        # —— 见 _merge_datasets
        datasets.append(Dataset(
            key="__merge__", file=path, name=base, metric=base,
            x_name="gm/ID" if _looks_like_gmid(header, cols_x) else "X",
            y_name=base, series=series_list, file_group=file_group,
        ))
    return _merge_datasets(datasets, path, file_group)


def _looks_like_gmid(header, xcols) -> bool:
    if not xcols:
        return False
    h = _norm(header[xcols[0]])
    return any(a in h for a in X_CONTAINS) or h == "x"


def _merge_datasets(datasets, path, file_group):
    """把同一指标 base 的多个 Dataset(不同 pval 拆分)合并。"""
    merged: dict[str, Dataset] = {}
    for d in datasets:
        if d.key != "__merge__":
            merged[d.key] = d
            continue
        m = merged.setdefault(d.metric, Dataset(
            key=f"{path}#{d.metric}", file=path, name=d.metric,
            metric=d.metric, x_name=d.x_name, y_name=d.metric,
            file_group=file_group,
        ))
        m.series.extend(d.series)
        if "宽表: 参数 L 编码在列头" not in m.notes:
            m.notes.append("宽表: 参数 L 编码在列头")
    return list(merged.values())


# --------------------------------------------------------------------------
# 长表解析
# --------------------------------------------------------------------------
def _norm_name(h: str) -> str:
    return re.sub(r"\s+", "", h).lower()


def _is_param_col(h: str) -> bool:
    n = _norm_name(h)
    if n in PARAM_NAMES:
        return True
    return "length" in n and len(n) < 24


def _is_x_col(h: str) -> bool:
    n = _norm_name(h)
    if n in X_NAMES or n == "gmid(a/a)":
        return True
    return any(t in n for t in X_CONTAINS) and ("gm" in n)


def _parse_long(header, data_rows, path, file_group,
                param_col=None, x_col=None, metric_cols=None):
    """长表(或任意“参数列+数值列”)解析。

    可显式指定列名(手动映射); 否则按别名启发式。
    """
    idx = {h: i for i, h in enumerate(header)}
    p_col = param_col if param_col is not None else next(
        (h for h in header if _is_param_col(h)), None)
    if p_col is None:
        return None
    xi_col = x_col if x_col is not None else next(
        (h for h in header if _is_x_col(h)), None)
    if metric_cols is None:
        metric_cols = [h for h in header
                       if h not in (p_col, xi_col) and h != p_col]
    numeric_cols = [h for h in metric_cols if h not in (p_col, xi_col)]
    # 把候选指标列里真的能转成数字的挑出来
    keep = []
    for h in numeric_cols:
        cnt = 0
        for row in data_rows:
            j = idx.get(h)
            if j is not None and j < len(row) and _to_float(row[j]) is not None:
                cnt += 1
            if cnt >= 5:
                break
        if cnt >= 5 or len(data_rows) <= 5:
            keep.append(h)
    numeric_cols = keep

    rows_par = []
    for row in data_rows:
        jp = idx.get(p_col)
        if jp is None or jp >= len(row):
            continue
        pv = _to_float(row[jp])
        if pv is None:
            continue
        rows_par.append((pv, row))
    if not rows_par:
        return None

    param_unit_factor, unit_name = _pick_unit([p for p, _ in rows_par])

    datasets = []
    x_label = None
    if xi_col is not None:
        x_label = xi_col if xi_col not in ("X", "x") else DEFAULT_X_LABEL
    ycols = numeric_cols if xi_col is not None else numeric_cols[:1]
    for h in ycols:
        jh = idx[h]
        jx = idx[xi_col] if xi_col is not None else None
        by_p: dict[float, list] = {}
        for pv, row in rows_par:
            yv = _to_float(row[jh]) if jh < len(row) else None
            if xi_col is not None:
                xv = _to_float(row[jx]) if jx < len(row) else None
            else:
                xv = None
            if yv is None or (xi_col is not None and xv is None):
                continue
            by_p.setdefault(round(pv, 12), []).append((xv, yv))
        series = []
        for pv, pts in sorted(by_p.items()):
            pts.sort(key=lambda t: (t[0] is None, t[0] or 0.0))
            xarr = np.array([t[0] if t[0] is not None else np.nan
                             for t in pts], float)
            yarr = np.array([t[1] for t in pts], float)
            if xi_col is None:
                xarr = yarr.copy()          # 退化: 只有一列数值 -> 用自身做 X
                yarr = np.arange(len(yarr), dtype=float)
            series.append(Series(
                param_um=(pv * param_unit_factor),
                x=xarr, y=yarr, label=str(pv * param_unit_factor),
            ))
        if not series:
            continue
        datasets.append(Dataset(
            key=f"{path}#{h}", file=path, name=h, metric=h,
            x_name=x_label or DEFAULT_X_LABEL, y_name=h,
            series=series, file_group=file_group,
        ))
        datasets[-1].notes.append(
            f"长表: 参数列<{p_col}>(单位≈{unit_name}), "
            f"X列<{xi_col or '无'}>")
    return datasets


def _pick_unit(vals):
    """参数值单位启发式: 统一换算成 µm 的倍率。"""
    vals = [abs(float(v)) for v in vals if v is not None]
    if not vals:
        return 1.0, "?"
    med = float(np.median(vals))
    if med < 1e-5:      # 0.55e-6 ... 视为 m
        return 1e6, "m"
    if med <= 100.0:    # 0.55 ... 视为 µm
        return 1.0, "µm"
    if med <= 1e6:      # 550 ... 视为 nm
        return 1e-3, "nm"
    return 1.0, "?"


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def _to_um(datasets):
    """把各 Dataset 的参数值统一换算为 µm(宽表里的 L 常以米为单位)。"""
    vals = []
    for d in datasets:
        for s in d.series:
            if s.param_um is not None:
                vals.append(s.param_um)
    if not vals:
        return
    factor, unit = _pick_unit(vals)
    if abs(factor - 1.0) > 1e-12:
        for d in datasets:
            for s in d.series:
                if s.param_um is not None:
                    s.param_um = float(np.round(s.param_um * factor, 12))
                    s.label = str(s.param_um)
            d.notes.append(f"参数单位换算: {unit} -> µm")
        return factor
    return 1.0


def parse_file(path: str, file_group: str = "",
               param_col=None, x_col=None, metric_cols=None,
               quiet: bool = True):
    """解析单个文件 -> list[Dataset]。格式自适应; 也可显式指定长表列名。"""
    base = os.path.splitext(os.path.basename(path))[0]
    fg = file_group or base
    header, data_rows = _read_csv(path)
    if not header:
        raise ValueError(f"无表头: {path}")

    datasets = None
    mode = ""
    # 1) 宽表(成对 X/Y, L 编码在列头)
    datasets = _parse_wide(header, data_rows, path, fg)
    if datasets:
        mode = "wide"
    # 2) 长表(含参数列 L)
    if not datasets:
        datasets = _parse_long(header, data_rows, path, fg,
                               param_col, x_col, metric_cols)
        if datasets:
            mode = "long"
    # 3) 简单两列(无参数单曲线)
    if not datasets:
        if len(header) == 2:
            xv, yv = [], []
            for row in data_rows:
                if len(row) < 2:
                    continue
                a, b = _to_float(row[0]), _to_float(row[1])
                if a is None or b is None:
                    continue
                xv.append(a)
                yv.append(b)
            if len(xv) >= 2:
                m = re.sub(r"\s*\(.*\)", "", header[1]).strip() or "y"
                datasets = [Dataset(
                    key=f"{path}#{m}", file=path, name=m, metric=m,
                    x_name=header[0], y_name=m,
                    series=[Series(param_um=None, x=np.array(xv, float),
                                   y=np.array(yv, float), label="(无参数)")],
                    file_group=fg)]
                datasets[0].notes.append("简单两列: 无 L 参数")
                mode = "simple"
    if not datasets:
        raise ValueError(
            f"无法识别的版式: {path}\n"
            f"表头: {header[:6]}{' …' if len(header) > 6 else ''}\n"
            f"可尝试用『手动映射』指定 参数列/X列/指标列。")
    _to_um(datasets)
    _attach_metrics(datasets)
    for d in datasets:
        d.notes.append(f"格式: {mode}; 曲线数={len(d.series)}")
    return datasets


def _attach_metrics(datasets):
    """识别每个数据集的指标类型并配好显示单位(见 metrics.py)。"""
    from .metrics import detect_metric, is_raw_db, pick_display
    for d in datasets:
        prof = detect_metric(d.metric)
        d.profile = prof
        vals = [v for s in d.series for v in s.y.tolist()]
        factor, unit = pick_display(vals, prof.unit)
        d.disp_factor = factor
        d.disp_unit = unit
        d.raw_db = is_raw_db(d.metric, prof)
        if not d.x_name or d.x_name in ("X", "x"):
            d.x_name = "gm/ID (1/V)"
        if prof.key != "other":
            d.notes.append(
                f"指标类型: {prof.name or d.metric}"
                f"(单位 {unit or '无量纲'}, 查表默认方向 "
                f"{'≥(越大越好)' if prof.direction == 'max' else '≤(上限)'})")


def parse_paths(paths: Iterable[str]) -> dict:
    """解析多个文件/目录 -> {dataset_key: Dataset}。"""
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
    out = {}
    errors = []
    for f in files:
        try:
            for d in parse_file(f):
                out[d.key] = d
        except Exception as e:  # noqa: BLE001
            errors.append(f"{os.path.basename(f)}: {e}")
    return out, errors
