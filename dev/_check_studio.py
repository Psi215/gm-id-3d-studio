# -*- coding: utf-8 -*-
"""全参数工作室自检(新窗口架构): total.csv 装载 / 开窗 / X 轴 / 勾选联动。"""
from __future__ import annotations

import os
import sys
import time
import traceback

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

TOTAL = os.path.join(ROOT, "csvdata_extras", "total.csv")
SELFGAIN = os.path.join(ROOT, "csvdata", "selfgain_nch_2.5V.csv")
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
    if not os.path.exists(TOTAL):
        print("SKIP: 找不到 total.csv(已删除), 本测试跳过。")
        print("  如需测试全参数宽表: 把导出的 total.csv 放到 csvdata_extras/ 即可。")
        return 0
    from gmstudio.core.loader import load_file
    src = load_file(TOTAL)
    print("== 装载 total.csv ==")
    print("  参数数:", len(src.metrics), "| 每参数曲线:",
          next(iter(src.metrics.values())).n_curves)
    assert len(src.metrics) == 114

    app = QApplication([])
    from gmstudio.ui.viewer import MainWindow
    w = MainWindow(restore=False)
    w.open_paths([TOTAL])
    pump(app, 40)
    print("== 控制台 ==")
    top = w.tree.tree.topLevelItem(0)
    print("  参数树:", top.text(0))
    assert top.childCount() == 114
    assert w.sess.x_metric and "gmoverid" in w.sess.x_metric[1], w.sess.x_metric
    print("  默认 X 轴:", w.sess.x_metric[1])

    wsrc = w.sess.sources[TOTAL]
    bases = [m.base for m in wsrc.sorted_metrics()[:3]]
    # 载入后自动为“已勾选的首个参数”开窗
    assert len(w.windows) == 1, f"应自动开 1 个窗口, 实际 {len(w.windows)}"
    win = next(iter(w.windows.values()))
    print(f"  自动开窗: {win.mt.display} | 曲线 {len(win._series)} 条"
          f" | 查表行 {win.table.rowCount()}")
    assert len(win._series) > 0
    assert win.surface_win is None            # 三维窗口不常驻

    w.sess.toggle(TOTAL, bases[1], True)
    w.sess.toggle(TOTAL, bases[2], True)
    w._on_tree()
    pump(app, 30)
    assert len(w.windows) == 3 and w.lst_wins.count() == 3
    print("  打开窗口数:", len(w.windows))

    w.sess.rename_metric(wsrc, bases[2], "fT (Hz)")
    assert os.path.exists(TOTAL + ".meta.json")
    os.remove(TOTAL + ".meta.json")
    w.tree.rebuild()
    print("  重命名持久化 OK")

    w.sess.toggle(TOTAL, bases[1], False)     # 取消勾选 = 关窗
    w._on_tree()
    pump(app, 20)
    assert len(w.windows) == 2
    print("  取消勾选后窗口数:", len(w.windows))

    w.open_paths([SELFGAIN])
    pump(app, 30)
    assert w.tree.tree.topLevelItemCount() == 2
    print("  追加 selfgain 后文件数: 2")

    if FAILS:
        print("FAILED:", FAILS[:2])
        return 1
    print("STUDIO CHECK PASSED (新窗口架构)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
