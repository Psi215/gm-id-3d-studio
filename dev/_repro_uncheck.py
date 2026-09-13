# -*- coding: utf-8 -*-
"""回归: 反复勾选/取消参数(开窗/关窗), 不应崩溃。"""
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FT = os.path.join(ROOT, "csvdata", "ft_nch_2.5V.csv")
INOR = os.path.join(ROOT, "csvdata_extras", "inor_nch_2.5V.csv")
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
    from gmstudio.ui.viewer import MainWindow
    w = MainWindow(restore=False)
    w.open_paths([FT, INOR])
    pump(app, 30)
    # 默认每个文件勾选第一个参数 -> 两个窗口
    assert len(w.sess.sources) == 2
    for path, bases in w.sess.checked.items():
        for b in list(bases):
            pass
    w._on_tree()
    pump(app, 20)
    print("打开窗口数:", len(w.windows), "| 树顶层:", w.tree.tree.topLevelItemCount())
    assert len(w.windows) == 2

    tree = w.tree.tree
    for k in range(4):
        state = Qt.Unchecked if k % 2 == 0 else Qt.Checked
        item = tree.topLevelItem(1).child(0)     # 每次开/关窗后重新取条目
        print(f"toggle {k} -> {state.name} on {item.text(0)}", flush=True)
        item.setCheckState(0, state)
        pump(app, 25)
        n = len(w.windows)
        print("    survived; 窗口数:", n)
        assert n == (1 if state == Qt.Unchecked else 2), n
    if FAILS:
        print(FAILS[-1][:500])
        return 1
    print("UNCHECK STRESS PASSED (新窗口架构)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
