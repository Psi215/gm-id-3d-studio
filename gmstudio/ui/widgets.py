# -*- coding: utf-8 -*-
"""绘图控件: matplotlib 画布 + 工具栏 + 持久色标。"""
from __future__ import annotations

import numpy as np
from matplotlib import colormaps, rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavToolbar
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

from PySide6.QtWidgets import QVBoxLayout, QWidget

rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
    "Arial Unicode MS", "DejaVu Sans",
]
rcParams["axes.unicode_minus"] = False
try:
    rcParams["axes3d.mouserotationstyle"] = "trackball"
except Exception:
    pass

CMAPS = ["viridis", "plasma", "cividis", "magma", "coolwarm", "turbo"]


def getcmap(name):
    return colormaps[name]


class MplPanel(QWidget):
    """单图(matplotlib + 工具栏 + 持久色标)控件。"""

    def __init__(self, parent=None, nrows=1, projection=None):
        super().__init__(parent)
        self.fig = Figure(figsize=(7.5, 5.2), layout="constrained")
        if projection == "3d":
            self.axes = self.fig.add_subplot(111, projection="3d")
            self.axes2 = None
        elif nrows == 2:
            gs = self.fig.add_gridspec(2, 1, height_ratios=[3, 2])
            self.axes = self.fig.add_subplot(gs[0])
            self.axes2 = self.fig.add_subplot(gs[1])
        else:
            self.axes = self.fig.add_subplot(111)
            self.axes2 = None
        self.canvas = FigureCanvas(self.fig)
        self.cbar_ax = None
        self._cbar_obj = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(NavToolbar(self.canvas, self))
        lay.addWidget(self.canvas)

    def clear_all(self):
        keep = {id(self.axes)}
        if self.axes2 is not None:
            keep.add(id(self.axes2))
        if self.cbar_ax is not None:
            keep.add(id(self.cbar_ax))
        for a in list(self.fig.axes):
            if id(a) not in keep:
                self.fig.delaxes(a)
        for ax in (self.axes, self.axes2):
            if ax is not None:
                ax.clear()

    def set_colorbar(self, mappable, label=None, **kw):
        if self.cbar_ax is None:
            cb = self.fig.colorbar(mappable, ax=self.axes, **kw)
            self.cbar_ax = cb.ax
            self._cbar_obj = cb
        else:
            try:
                self._cbar_obj = self.fig.colorbar(mappable, cax=self.cbar_ax)
            except Exception:
                self.fig.delaxes(self.cbar_ax)
                cb = self.fig.colorbar(mappable, ax=self.axes, **kw)
                self.cbar_ax = cb.ax
                self._cbar_obj = cb
        if label is not None and self._cbar_obj is not None:
            self._cbar_obj.set_label(label)
        return self.cbar_ax

    def clear_colorbar(self):
        if self.cbar_ax is not None:
            try:
                self.fig.delaxes(self.cbar_ax)
            except Exception:
                pass
        self.cbar_ax = None
        self._cbar_obj = None

    def auto_view(self):
        for ax in (self.axes, self.axes2):
            if ax is None:
                continue
            try:
                if str(getattr(ax, "name", "")).startswith("3d"):
                    ax.autoscale(enable=True)
                    ax.margins(0.05)
                else:
                    ax.relim()
                    ax.autoscale_view()
                    ax.margins(0.03, 0.05)
            except Exception:
                pass


def mkspin(lo, hi, val, dec=4, step=0.1):
    from PySide6.QtWidgets import QDoubleSpinBox
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    s.setSingleStep(step)
    s.setKeyboardTracking(False)
    return s
