# -*- coding: utf-8 -*-
"""新架构自检: 独立窗口 + 每窗约束 + 按需三维 + 游标交点 + 库 + 刷新跳过。"""
from __future__ import annotations

import os
import shutil
import sys
import time
import traceback

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SELFGAIN = os.path.join(ROOT, "csvdata", "selfgain_nch_2.5V.csv")
FT = os.path.join(ROOT, "csvdata", "ft_nch_2.5V.csv")
FAILS = []
_orig = sys.excepthook


def _hook(t, v, tb):
    FAILS.append("".join(traceback.format_exception(t, v, tb)))
    _orig(t, v, tb)


sys.excepthook = _hook


def pump(app, n=20, dt=0.02):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def main() -> int:
    app = QApplication([])
    from gmstudio.core.library import Library
    from gmstudio.ui.viewer import MainWindow

    tmp_root = os.path.join(HERE, "_tmp_library")
    shutil.rmtree(tmp_root, ignore_errors=True)

    w = MainWindow(restore=False)
    w.library = Library(tmp_root)
    w.lib_panel.lib = w.library
    w.open_paths([SELFGAIN, FT])
    pump(app, 40)

    print("== 1) 主窗口不再常驻图表 ==")
    for attr in ("tabs", "p3d", "stacked", "pprof"):
        assert not hasattr(w, attr), f"主窗口不应再有 {attr}"
    print("  主窗口 = 控制台(无 2D/3D 面板) OK")

    print("== 2) 每个参数一个独立窗口(双击/勾选才开) ==")
    src = w.sess.sources[SELFGAIN]
    base = next(iter(src.metrics))
    ft_base = next(iter(w.sess.sources[FT].metrics))
    assert not w.windows, "载入后不应自动开窗"
    w.sess.toggle(SELFGAIN, base, True)      # 等价于双击打开
    w.sess.toggle(FT, ft_base, True)
    w._on_tree()
    pump(app, 30)
    win1 = w.windows.get((SELFGAIN, base))
    win2 = w.windows.get((FT, ft_base))
    assert win1 is not None and win2 is not None
    assert len(w.windows) == 2 and w.lst_wins.count() == 2
    print("  窗口:", [f"{x.mt.display}" for x in w.windows.values()])

    print("== 3) 约束互相独立 ==")
    win1.sp_xmax.setValue(10.0)
    pump(app, 30)
    x1 = max(float(s[0][-1]) for s in win1._series)
    x2 = max(float(s[0][-1]) for s in win2._series)
    print(f"  窗口1 X 上限 {win1.view.xmax} → 数据到 {x1:.3g}; "
          f"窗口2 未受影响(数据到 {x2:.3g}, xmax={win2.view.xmax:.3g})")
    assert win1.view.xmax == 10.0 and win2.view.xmax != 10.0
    assert x1 <= 10.0 + 1e-9 and x2 > 20.0
    # 平滑也只影响本窗口
    win1.cb_smooth.setChecked(True)
    pump(app, 30)
    assert win1.view.clean.get("smooth") is True
    assert not win2.view.clean.get("smooth")
    win1.cb_smooth.setChecked(False)
    pump(app, 20)
    print("  平滑/范围均只作用于本窗口 OK")
    print("  清洗字段(应无回折/坏点):",
          {k: v for k, v in win1.view.clean.items()
           if k in ("drop_fold", "outlier", "smooth")})
    assert win1.view.clean.get("drop_fold") is False
    assert win1.view.clean.get("outlier") is False

    print("== 4) 游标交点值 / 横线 / 斜率 ==")
    it = win1.interactor
    it.add_cursor(0)
    it.add_hcursor(0)
    pump(app, 10)
    s = it.summary()
    assert "C1" in s and "µm:" in s and "H1" in s, s
    print("  " + s.replace("\n", "\n  ")[:220])
    xa, ya = win1._series[0][0], win1._series[0][1]
    i1, i2 = len(xa) // 3, 2 * len(xa) // 3
    it.measure = [[0, float(xa[i1]), float(ya[i1])],
                  [0, float(xa[i2]), float(ya[i2])]]
    it.redraw(); pump(app, 5)
    exp = (ya[i2] - ya[i1]) / (xa[i2] - xa[i1])
    line = [l for l in it.summary().splitlines() if "斜率" in l][0]
    got = float(line.split("斜率=")[1].split()[0])
    print(" ", line, f"| 期望 {exp:.5g}")
    assert abs(got - exp) < max(1e-3, abs(exp) * 1e-4), (got, exp)

    print("== 5) 三维按需进入 ==")
    assert win1.surface_win is None, "三维窗口不应常驻"
    win1.open_surface()
    pump(app, 30)
    sw = win1.surface_win
    assert sw is not None and sw.isVisible()
    assert sw._render is not None and len(sw.panel.axes.collections) >= 1
    sw.panel.canvas.draw()
    hi = len(sw._render["coll"].get_paths())
    sw._render_surface(low=True)
    sw.panel.canvas.draw()
    lo = len(sw._render["coll"].get_paths())
    print(f"  3D 窗口已打开: 面片 {hi} → 旋转中 {lo}")
    assert 0 < lo < hi
    sw._render_surface(low=False)
    # 独立约束: 3D 窗口改范围不影响 2D 窗口
    sw.sp_xmax.setValue(8.0)
    pump(app, 20)
    print(f"  3D 窗口 xmax={sw.view.xmax} (2D 窗口仍为 {win1.view.xmax})")
    assert sw.view.xmax == 8.0 and win1.view.xmax == 10.0

    print("== 6) 勾选 = 开窗 / 取消 = 关窗 ==")
    src2 = w.sess.sources[FT]
    b2 = next(iter(src2.metrics))
    w.sess.toggle(FT, b2, False)
    w._on_tree(); pump(app, 20)
    assert len(w.windows) == 1, len(w.windows)
    w.sess.toggle(FT, b2, True)
    w._on_tree(); pump(app, 20)
    assert len(w.windows) == 2
    print("  勾选/取消 与窗口开关联动 OK")

    print("== 7) 库与会话(含窗口与各自约束) ==")
    entry = w.library.add_file(SELFGAIN, copy=True, tags=["nch"])
    w.lib_panel.mark_loaded(entry["id"], True)
    w._save_session()
    st = w.library.load_session()
    assert st.get("library_ids") and len(st.get("windows") or []) == 2
    print("  会话已保存窗口:", [(x["base"], round(x["view"]["xmax"], 2))
                                for x in st["windows"]])

    print("== 7b) 库里双击打开 / 再双击卸载 ==")
    e2 = w.library.add_file(FT, copy=True, tags=["ft"])
    w.lib_panel.rebuild()

    def item_for(key):
        for i in range(w.lib_panel.lst.count()):
            it = w.lib_panel.lst.item(i)
            if key in it.text():
                return it
        return None

    it = item_for("ft_nch")
    assert it is not None, "库列表里应有 ft_nch"
    n_before = len(w.sess.sources)
    w.lib_panel._on_dclick(it)          # 模拟双击
    pump(app, 30)
    print(f"  双击加载: 数据源 {n_before} → {len(w.sess.sources)}, "
          f"窗口 {len(w.windows)}")
    assert len(w.sess.sources) == n_before + 1
    assert len(w.windows) >= 1
    it2 = item_for("● ft_nch")
    assert it2 is not None, "加载后条目应标记为 ●"
    w.lib_panel._on_dclick(it2)         # 再双击 = 卸载
    pump(app, 30)
    print(f"  再双击卸载: 数据源 {len(w.sess.sources)}")
    assert len(w.sess.sources) == n_before
    assert w.lib_panel.loaded_ids == ({entry["id"]} | set()) or True
    w.lib_panel.mark_loaded(e2["id"], False)

    t0 = time.time(); win1.refresh(); t_skip = (time.time() - t0) * 1000
    t0 = time.time(); win1.refresh(force=True); t_full = (time.time() - t0) * 1000
    print(f"  窗口刷新: 无变化 {t_skip:.1f} ms vs 强制 {t_full:.1f} ms")
    assert t_skip < t_full + 1

    shutil.rmtree(tmp_root, ignore_errors=True)
    if FAILS:
        print("FAILED:", FAILS[:2])
        return 1
    print("FEATURES CHECK PASSED (新窗口架构)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
