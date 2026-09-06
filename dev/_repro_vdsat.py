# -*- coding: utf-8 -*-
"""全参数勾选压力扫描(自带 X / gmid 作 X), 捕获任何异常。"""
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

TOTAL = os.path.join(ROOT, "csvdata_extras", "total.csv")
FAILS = []

_orig = sys.excepthook


def _hook(t, v, tb):
    FAILS.append("".join(traceback.format_exception(t, v, tb)))
    _orig(t, v, tb)


sys.excepthook = _hook


def pump(app, n=10, dt=0.02):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def main() -> int:
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from gmstudio.ui.viewer import MainWindow
    w = MainWindow()
    w.open_paths([TOTAL])
    pump(app, 30)
    src = w.sess.sources[TOTAL]
    bases = [m.base for m in src.sorted_metrics()]
    print("metrics:", len(bases))
    assert len(bases) == 114

    def check(tag):
        pump(app, 8)
        if FAILS:
            print("ERROR at", tag, ":", FAILS[-1][:300])
            FAILS.clear()
            return False
        return True

    gm_base = next(b for b in bases if "gmoverid" in b.lower())
    for xkey, tag in ((None, "own-X"), (gm_base, "gmoverid-X")):
        if xkey is None:
            w.cmb_x.setCurrentIndex(0)
        else:
            w.cmb_x.setCurrentIndex(
                w.cmb_x.findData(TOTAL + "\u0001" + xkey))
        bad = 0
        for i, b in enumerate(bases):
            w.sess.toggle(TOTAL, b, True)
            w._on_tree()
            if not check(f"{tag} {b}"):
                bad += 1
            if i % 20 == 0:
                print(tag, i, flush=True)
        print(tag, "bad:", bad)
    print("SWEEP DONE; FAILS:", len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
