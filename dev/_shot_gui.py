# -*- coding: utf-8 -*-
"""离屏截图(新架构): 控制台 / 2D 绘图窗口 / 3D 曲面窗口 -> docs/screenshots。"""
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


def pump(app, n=30, dt=0.03):
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


def main() -> int:
    app = QApplication([])
    from gmstudio.ui.viewer import MainWindow
    outdir = os.path.join(ROOT, "docs", "screenshots")
    os.makedirs(outdir, exist_ok=True)
    csv = os.path.join(ROOT, "csvdata", "selfgain_nch_2.5V.csv")

    w = MainWindow(restore=False)
    w.resize(1200, 820)
    w.show()
    w.open_paths([csv])
    pump(app, 40)
    # 打开一个参数窗口(等价于用户双击)
    src = next(iter(w.sess.sources.values()))
    base = next(iter(src.metrics))
    w.sess.toggle(list(w.sess.sources)[0], base, True)
    w._on_tree()
    pump(app, 40)
    win = next(iter(w.windows.values()))
    # 加两条游标, 让读数面板有内容
    win.interactor.add_cursor(0)
    win.interactor.add_hcursor(0)
    pump(app, 15)

    w.grab().save(os.path.join(outdir, "studio.png"))
    print("saved studio.png")
    win.grab().save(os.path.join(outdir, "curves.png"))
    print("saved curves.png")

    # 3D 窗口(按需进入)
    win.open_surface()
    pump(app, 40)
    sw = win.surface_win
    if sw is not None:
        sw.resize(1000, 720)
        pump(app, 20)
        sw.grab().save(os.path.join(outdir, "surface3d.png"))
        print("saved surface3d.png")
    # 清理: 不再需要旧的剖面截图
    stale = os.path.join(outdir, "profiles.png")
    if os.path.exists(stale):
        os.remove(stale)
        print("removed stale profiles.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
