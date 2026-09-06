# -*- coding: utf-8 -*-
"""无 GUI 自检: 验证 解析 -> 清洗 -> 公共栅格曲面 -> 反查 整条管线。
用法: python selftest.py [数据文件] [阈值dB]
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gmidlib import clean as cleanmod
from gmidlib import lookup as lookupmod
from gmidlib import parse as parsemod
from gmidlib import surface as surfmod


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "csvdata",
        "selfgain_nch_2.5V.csv")
    thr_db = float(sys.argv[2]) if len(sys.argv) > 2 else 50.0
    print("== 1) 解析 ==")
    dss = parsemod.parse_file(path)
    for d in dss:
        print(f"  dataset: {d.name}  curves={len(d.series)}  "
              f"L范围= {min(s.param_um for s in d.series):.4g}.."
              f"{max(s.param_um for s in d.series):.4g} µm  notes={d.notes}")
    ds = dss[0]
    print("== 2) 清洗(回折剔除, 平滑关, MAD 开) ==")
    stats = cleanmod.clean_dataset(ds, drop_fold=True, sort_x=True,
                                   smooth=False, outlier=True, k_mad=6.0)
    n_ok = sum(1 for s in stats if s.get("kept", 0) >= 2)
    tot_rm = sum(s.get("dropped", 0) for s in stats)
    print(f"  曲线 {len(stats)} 条, 可用 {n_ok}, 共剔除 {tot_rm} 点")
    for st in stats[:3]:
        print("   ", st)

    print("== 3) 公共栅格曲面 ==")
    sers = surfmod.cleaned_series_of(ds)
    xs_all = np.concatenate([s[1] for s in sers])
    xlo, xhi = float(xs_all.min()), float(xs_all.max())
    sf = surfmod.build_surface(sers, xmin=0.98 * xlo, xmax=1.02 * xhi,
                               n=240, xlog=False)
    print(f"  栅格: L {sf['Ls'].size} 条 × gm/ID {sf['xs'].size} 点; "
          f"有效面值 {sf['valid']} ({100*sf['valid']/(sf['Ls'].size*sf['xs'].size):.0f}%)")
    prof = getattr(ds, "profile", None)
    unit = ("dB" if (prof is not None and prof.db_capable)
            else (ds.disp_unit or ""))
    direction = (prof.direction if prof is not None else "max")
    print(f"  指标档案: {prof.key if prof else 'other'} | 显示单位: "
          f"{unit or '无量纲'} | 原始即dB: {ds.raw_db} | "
          f"查表方向: {'≥' if direction == 'max' else '≤'}")

    print(f"== 4) 反查(阈值 {thr_db:.1f} {unit}, 方向 {direction}) ==")
    if prof is not None and prof.db_capable:
        Zd = surfmod.grid_db(sf["Z"])
    else:
        Zd = sf["Z"] * float(getattr(ds, "disp_factor", 1.0) or 1.0)
    res = lookupmod.run_lookup(Zd, sf["xs"], sf["Ls"], thr_db,
                               direction=direction)
    print("  " + lookupmod.summarize(res, unit=unit))
    for r in res.rows[:8]:
        print(f"   L={r.L_um:.4g} µm 可行区 gm/ID "
              f"[{r.x_lo:.4g}, {r.x_hi:.4g}]  推荐 {r.x_rec:.4g}  "
              f"指标 {r.value_rec:.3g} {unit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
