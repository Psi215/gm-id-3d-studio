# -*- coding: utf-8 -*-
"""全参数工作室专项自检: total.csv 装载、X 轴选择、勾选联动、重命名。"""
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


def pump(app, n=20, dt=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def main() -> int:
    # 1) 核心装载
    from gmstudio.core.loader import load_file
    t0 = time.time()
    src = load_file(TOTAL)
    print(f"== 装载 total.csv ({time.time()-t0:.2f}s) ==")
    print("  参数数:", len(src.metrics))
    assert len(src.metrics) == 114
    m0 = next(iter(src.metrics.values()))
    assert m0.n_curves == 15
    assert 0.5 < m0.L_range[0] < 0.6 and 1.9 < m0.L_range[1] < 2.0

    # 2) 会话
    from gmstudio.core.session import Session
    sess = Session()
    sess.add_source(src)
    sess.default_ranges()
    sf = sess.surface_of(m0)
    assert sf is not None and sf["Z"].shape == (15, 240)
    res = sess.lookup_of(m0)
    print("  曲面:", sf["Z"].shape, "| 查表可行区间:",
          len(res.rows) if res else 0)

    # 3) GUI
    app = QApplication([])
    from gmstudio.ui.viewer import MainWindow
    w = MainWindow()
    w.open_paths([TOTAL])
    pump(app, 40)
    print("== GUI ==")
    print("  参数树顶层:", w.tree.tree.topLevelItemCount(),
          "| 2D 子图:", len(w.stacked.axes),
          "| 3D 集合:", len(w.p3d.axes.collections))
    assert w.tree.tree.topLevelItemCount() == 1
    assert len(w.stacked.axes) == 1
    # 默认 X 应自动选 gmid
    assert "gmoverid" in w.lb_xlab.text(), w.lb_xlab.text()
    print("  默认 X 轴:", w.lb_xlab.text())

    # 4) 勾选联动
    wsrc = w.sess.sources[TOTAL]
    bases = [m.base for m in wsrc.sorted_metrics()[:3]]
    w.sess.toggle(TOTAL, bases[1], True)
    w.sess.toggle(TOTAL, bases[2], True)
    w._on_tree()
    pump(app, 30)
    assert len(w.stacked.axes) == 3
    print("  勾选 3 个参数后 2D 子图数:", len(w.stacked.axes))

    # 5) 重命名 + 持久化 + 清理
    w.sess.rename_metric(wsrc, bases[2], "fT (Hz)")
    assert os.path.exists(TOTAL + ".meta.json")
    print("  重命名持久化 OK")
    os.remove(TOTAL + ".meta.json")

    # 6) 老格式共存
    w.open_paths([SELFGAIN])
    pump(app, 30)
    assert w.tree.tree.topLevelItemCount() == 2
    print("  追加 selfgain 后顶层文件数: 2")

    if FAILS:
        print("FAILED:", FAILS[:2])
        return 1
    print("STUDIO CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
