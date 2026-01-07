# -*- coding: utf-8 -*-
import sys
import ctypes

if sys.platform == 'win32':
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except:
        pass

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QGuiApplication, QCursor
import mss

app = QApplication(sys.argv)

print("=== Qt Screens ===")
for i, screen in enumerate(QGuiApplication.screens()):
    g = screen.geometry()
    dpr = screen.devicePixelRatio()
    print(f"Screen {i}: geometry=({g.x()}, {g.y()}, {g.width()}x{g.height()}), DPR={dpr}")
    print(f"  Physical size: {int(g.width()*dpr)}x{int(g.height()*dpr)}")

print("\n=== MSS Monitors ===")
with mss.mss() as sct:
    for i, mon in enumerate(sct.monitors):
        print(f"Monitor {i}: {mon}")

print(f"\n=== Cursor ===")
pos = QCursor.pos()
print(f"Qt cursor pos: ({pos.x()}, {pos.y()})")
