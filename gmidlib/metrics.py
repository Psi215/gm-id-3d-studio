# -*- coding: utf-8 -*-
"""
指标类型识别与显示单位适配
==========================
同一个 gm/ID 设计数据浏览器需要处理不同 Y 指标:
  自增益(线性 V/V 或 dB)、fT/GBW(Hz)、Vdsat/Vgs/Vov(V)、
  Id(A)/Inor(A/m, 归一化电流密度)、Cgg(F)、gds(S) 等。
不同量纲用同一套 dB/单位显然不对, 因此这里给每种指标建“档案”:

  * kind        : 物理量类别(gain/freq/volt/current/current_density/capacitance/other)
  * unit        : 显示基准单位(无前缀)
  * direction   : 反向查表的默认方向 'max'(指标 ≥ 阈值, 越大越好)/ 'min'(≤ 阈值)
  * db_capable  : 是否支持 dB 视图(仅增益类)
  * raw_is_db   : 由列名是否含 "db" 自动判断“原始数据已是 dB”

显示单位自动选择工程前缀(median 落到 [1,1000) 的档位):
  Hz->GHz, A->µA, V->mV, A/m->kA/m 等; 前缀只影响显示与筛查,
  内部计算始终用原始值。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MetricProfile:
    key: str
    aliases: tuple = ()
    unit: str = ""              # 显示基准单位(无前缀); 无量纲比可用 "V/V"
    kind: str = "other"         # gain/freq/volt/current/current_density/capacitance/other
    direction: str = "max"      # 查表默认方向: max(≥) / min(≤)
    db_capable: bool = False
    name: str = ""              # 友好显示名(空则用列头原文)


_PROFILES = (
    MetricProfile(
        "selfgain",
        ("selfgain", "self_gain", "self gain", "intrinsic gain", "gmro",
         "gm_ro", "gm*rds", "gm/gds", "gds ratio", "gain", "av", "av0",
         "voltage gain", "open loop gain", "openloopgain", "opengain",
         "dc gain", "dcgain", "gm*r0", "gmr0", "gain(v/v)", "av(v/v)",
         "intrinsicgain"),
        unit="V/V", kind="gain", direction="max", db_capable=True,
        name="自增益",
    ),
    MetricProfile(
        "ft",
        ("ft", "f_t", "ft(hz)", "ft(ghz)", "ft(g)", "transition frequency",
         "transitionfrequency", "unity gain frequency",
         "unitygainfrequency", "gbw", "gbwp", "gbw(hz)", "f-3db", "f3db",
         "bandwidth", "bw", "bw(hz)", "wt", "ft(1/s)", "f-3db(hz)"),
        unit="Hz", kind="freq", direction="max", name="fT",
    ),
    MetricProfile(
        "vdsat",
        ("vdsat", "vds_sat", "vdsat(v)", "vdssat", "vds(sat)", "vds,sat",
         "vds sat", "vds(sat)(v)", "vdsats"),
        unit="V", kind="volt", direction="min", name="Vdsat",
    ),
    MetricProfile(
        "vgs",
        ("vgs", "vg", "vgs(v)", "v_g", "vg(v)", "gate voltage",
         "gatevoltage", "vg(1/v)"),
        unit="V", kind="volt", direction="min", name="Vgs",
    ),
    MetricProfile(
        "vov",
        ("vov", "vgt", "vgs-vth", "vgsth", "overdrive", "overdrive voltage",
         "overdrivevoltage", "vov(v)", "vgst", "vdsat_th"),
        unit="V", kind="volt", direction="min", name="Vov",
    ),
    MetricProfile(
        "idnor",
        ("idnor", "inor", "i_nor", "id_nor", "idnorm", "idnorm(a)",
         "id/w", "idw", "normalized current", "normalizedcurrent",
         "inor(a)", "id_norm", "i/w", "id/w(a/m)", "id/w(a/um)", "id_n",
         "idn(a/m)", "id_normalized"),
        unit="A/m", kind="current_density", direction="min", name="Inor",
    ),
    MetricProfile(
        "id",
        ("id", "ids", "current", "drain current", "draincurrent",
         "id(a)", "ids(a)", "i(a)", "i_d", "i_d(a)"),
        unit="A", kind="current", direction="min", name="Id",
    ),
    MetricProfile(
        "cgg",
        ("cgg", "cgs", "cgd", "cgb", "css", "cdd", "cgg(f)", "cgs(f)",
         "total gate capacitance", "totalgatecapacitance",
         "gate capacitance", "gatecapacitance"),
        unit="F", kind="capacitance", direction="min", name="Cgg",
    ),
    MetricProfile(
        "gds",
        ("gds", "go", "gds(s)", "output conductance",
         "outputconductance"),
        unit="S", kind="other", direction="min", name="gds",
    ),
    MetricProfile(
        "gmid",
        ("gmid", "gm_id", "gmoverid", "gm_over_id", "gm/id", "gm id",
         "gm/id(1/v)", "gm/id(a/a)", "gmid(1/v)", "gmoverid(1/v)"),
        unit="1/V", kind="other", direction="max", name="gm/ID",
    ),
    MetricProfile(
        "gm",
        ("gm", "g_m", "gm(s)", "transconductance"),
        unit="S", kind="other", direction="max", name="gm",
    ),
)

_NORM_RE = re.compile(r"[\s_\-\(\)]")
_PREFIXES = ((12, "T"), (9, "G"), (6, "M"), (3, "k"), (0, ""),
             (-3, "m"), (-6, "µ"), (-9, "n"), (-12, "p"))
_PREFIXABLE = {"Hz", "V", "A", "F", "A/m", "V/m"}


def _norm(name: str) -> str:
    return _NORM_RE.sub("", str(name)).lower()


_ALIAS_MAP = {}
for _p in _PROFILES:
    for _a in _p.aliases:
        _ALIAS_MAP.setdefault(_norm(_a), _p)
_ALIASES_SORTED = sorted(_ALIAS_MAP.items(), key=lambda kv: -len(kv[0]))


def detect_metric(name: str) -> MetricProfile:
    """按列头/指标名识别指标类型; 未知类型返回 other 档案(原样显示)。

    导出列头常带器件前缀(如 "M0:vdsat" / "M0:gmoverid" / "M0:4"):
    先试全名, 再试冒号/点号之后的后段(纯数字后段不回退, 避免误判)。
    """
    n = _norm(name)
    if n in _ALIAS_MAP:
        return _ALIAS_MAP[n]
    for alias, prof in _ALIASES_SORTED:
        if alias and n.startswith(alias):
            return prof
    for sep in (":", "."):
        if sep in n:
            tail = n.rsplit(sep, 1)[-1].strip()
            if tail and not tail.isdigit():
                if tail in _ALIAS_MAP:
                    return _ALIAS_MAP[tail]
                for alias, prof in _ALIASES_SORTED:
                    if tail.startswith(alias):
                        return prof
    return MetricProfile(key="other", kind="other", direction="max",
                         db_capable=False, unit="")


def is_raw_db(name: str, prof: MetricProfile) -> bool:
    """列名含 db(如 selfgain (dB))且为增益类 -> 原始数据即 dB。"""
    return bool(prof.db_capable) and ("db" in _norm(name))


def pick_display(vals, base_unit: str):
    """返回 (factor, unit_str): 显示值 = 原始值 × factor。"""
    if not base_unit or base_unit not in _PREFIXABLE:
        return 1.0, base_unit
    arr = np.asarray([abs(float(v)) for v in vals
                      if v is not None and np.isfinite(v)], float)
    if arr.size == 0:
        return 1.0, base_unit
    med = float(np.median(arr))
    if not np.isfinite(med) or med <= 0:
        return 1.0, base_unit
    for e, prefix in _PREFIXES:
        factor = 10.0 ** (-e)
        if 1.0 <= med * factor < 1000.0:
            return factor, prefix + base_unit
    return 1.0, base_unit
