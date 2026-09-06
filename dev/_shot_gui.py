# -*- coding: utf-8 -*-
"""离屏截图: 载入样例 -> 三个视图 -> 保存到 docs/screenshots(开发用)。"""
from __future__ import annotations

import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402


def pump(app, n=40, dt=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def main() -> int:
    app = QApplication([])
    from gmstudio.ui.viewer import MainWindow
    w = MainWindow()
    w.resize(1460, 900)
    w.show()
    w.open_paths([os.path.join(ROOT, "csvdata", "selfgain_nch_2.5V.csv")])
    pump(app, 60)
    for p in (w.stacked, w.p3d, w.pprof):
        p.canvas.draw()
    pump(app, 10)
    outdir = os.path.join(ROOT, "docs", "screenshots")
    os.makedirs(outdir, exist_ok=True)
    for name, idx in (("curves", 0), ("3d", 1), ("profiles", 2)):
        w.tabs.setCurrentIndex(idx)
        pump(app, 12)
        fn = os.path.join(outdir, f"{name}.png")
        w.grab().save(fn)
        print("saved", fn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
