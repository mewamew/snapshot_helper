# -*- coding: utf-8 -*-
"""
截屏工具 - 按 Shift+Alt+B 触发框选截图
截图保存到下载目录，路径自动复制到剪贴板
"""

import sys
import os
import ctypes
from datetime import datetime
from pathlib import Path

# 设置 DPI 感知 (必须在导入 PyQt 之前)
if sys.platform == 'win32':
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

from PyQt6.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QPixmap, QCursor, QIcon, QAction, QImage, QGuiApplication
)
from pynput import keyboard
import mss


class HotkeySignal(QObject):
    """用于在线程间传递信号"""
    triggered = pyqtSignal()


class ScreenshotOverlay(QWidget):
    """全屏透明覆盖层，用于框选截图区域"""

    def __init__(self, on_capture_done, screen_info):
        super().__init__()
        self.on_capture_done = on_capture_done
        self.screen_info = screen_info  # (geometry, mss_monitor, device_pixel_ratio, screen)
        self.start_pos = None
        self.end_pos = None
        self.is_selecting = False
        self.edit_mode = False  # 编辑模式：框选完成后进入
        self.drawing_paths = []  # 涂鸦路径列表 [(type, color, width, data)]
        self.current_path = []  # 当前正在绘制的路径
        self.is_drawing = False  # 是否正在涂鸦

        # 绘图工具设置
        self.current_tool = 'move'  # 'move', 'pen', 'rect', 'circle', 'arrow', 'eraser'
        self.is_moving = False  # 是否正在移动选择框
        self.move_start_pos = None  # 移动起始位置
        self.current_color = QColor(255, 60, 60)  # 红色
        self.current_width = 4  # 笔触粗细（默认中等）
        self.draw_start_pos = None  # 绘制形状的起始位置

        geometry, mss_monitor, dpr, screen = screen_info
        self.screen = screen
        self.screen_geometry = geometry
        self.window_offset = QPoint(0, 0)

        # 设置窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 设置窗口位置和大小（使用逻辑坐标）
        self.setGeometry(geometry)

        # 保存 DPI 缩放比例（必须在 _capture_screen 之前）
        self.dpr = dpr

        # 先初始化，避免 _capture_screen 中访问未定义属性
        self.background_pixmap = None

        # 使用 mss 截取当前显示器
        self.background_pixmap = self._capture_screen(mss_monitor)

        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def _capture_screen(self, monitor):
        """截取指定显示器 - macOS 使用 Quartz 获取物理像素，其他平台用 mss"""
        if sys.platform == 'darwin':
            return self._capture_screen_macos(monitor)
        else:
            return self._capture_screen_mss(monitor)

    def _capture_screen_macos(self, monitor):
        """macOS: 使用 Quartz 截取物理像素"""
        try:
            import Quartz
            from Quartz import CGWindowListCreateImage, kCGWindowListOptionOnScreenOnly, kCGNullWindowID
            from Quartz import CGRectMake, kCGWindowImageDefault

            # 使用逻辑坐标创建截图区域
            region = CGRectMake(monitor['left'], monitor['top'], monitor['width'], monitor['height'])

            # 截取屏幕 - Quartz 会返回物理像素
            cg_image = CGWindowListCreateImage(region, kCGWindowListOptionOnScreenOnly, kCGNullWindowID, kCGWindowImageDefault)

            if cg_image is None:
                return self._capture_screen_mss(monitor)

            # 获取图像尺寸（物理像素）
            width = Quartz.CGImageGetWidth(cg_image)
            height = Quartz.CGImageGetHeight(cg_image)
            bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)

            # 校准 DPR
            self._sync_dpr_with_capture(width, height)

            # 转换为 QImage
            from Quartz import CGImageGetDataProvider, CGDataProviderCopyData
            data_provider = CGImageGetDataProvider(cg_image)
            data = CGDataProviderCopyData(data_provider)

            # Quartz 返回 BGRA 格式，使用正确的 bytes_per_row
            qimg = QImage(data, width, height, bytes_per_row, QImage.Format.Format_ARGB32)
            pixmap = QPixmap.fromImage(qimg.copy())

            # 设置正确的 DPR，让 Qt 按逻辑坐标绘制
            pixmap.setDevicePixelRatio(self.dpr)
            return pixmap

        except ImportError:
            return self._capture_screen_mss(monitor)

    def _capture_screen_mss(self, monitor):
        """使用 mss 截取屏幕（fallback）"""
        with mss.mss() as sct:
            screenshot = sct.grab(monitor)

            # 根据实际截图尺寸校准 DPR
            self._sync_dpr_with_capture(screenshot.width, screenshot.height)

            # mss 返回 BGRA
            qimg = QImage(
                screenshot.bgra,
                screenshot.width,
                screenshot.height,
                screenshot.width * 4,
                QImage.Format.Format_ARGB32
            )

            pixmap = QPixmap.fromImage(qimg.copy())
            # 设置 DPR，让 Qt 按逻辑坐标绘制（与 macOS Quartz 行为一致）
            pixmap.setDevicePixelRatio(self.dpr)
            return pixmap

    def _sync_dpr_with_capture(self, pixel_width, pixel_height):
        """用实际截图像素尺寸校准逻辑坐标与像素的比例"""
        logical_width = self.width()
        logical_height = self.height()

        if logical_width <= 0 or logical_height <= 0:
            return

        dpr_x = pixel_width / logical_width
        dpr_y = pixel_height / logical_height

        if dpr_x <= 0 or dpr_y <= 0:
            return

        effective_dpr = (dpr_x + dpr_y) / 2.0
        if abs(effective_dpr - self.dpr) > 0.01:
            self.dpr = effective_dpr
            if self.background_pixmap:
                self.background_pixmap.setDevicePixelRatio(self.dpr)

    def _post_show_sync(self):
        """窗口尺寸稳定后重新校准 DPR（修复 macOS 全屏缩放导致的偏差）"""
        if not self.background_pixmap:
            return

        if sys.platform == 'darwin' and self.screen is not None:
            self.window_offset = self.geometry().topLeft() - self.screen_geometry.topLeft()
            # DPR 已在 _capture_screen 中通过 _sync_dpr_with_capture 校准
            self.update()
            return

        self._sync_dpr_with_capture(
            self.background_pixmap.width(),
            self.background_pixmap.height()
        )
        self.update()

    def _rect_to_screen_pixels(self, rect):
        """将窗口内逻辑坐标矩形转换为屏幕像素坐标矩形"""
        offset = self.window_offset if sys.platform == 'darwin' else QPoint(0, 0)
        return QRect(
            int((rect.x() + offset.x()) * self.dpr),
            int((rect.y() + offset.y()) * self.dpr),
            int(rect.width() * self.dpr),
            int(rect.height() * self.dpr)
        )

    def paintEvent(self, event):
        """绘制覆盖层"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制背景截图（设置了 devicePixelRatio 后 Qt 自动处理缩放）
        if self.background_pixmap:
            if sys.platform == 'darwin':
                painter.drawPixmap(-self.window_offset.x(), -self.window_offset.y(),
                                   self.background_pixmap)
            else:
                painter.drawPixmap(0, 0, self.background_pixmap)

        # 绘制半透明遮罩
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        # 如果正在选择，绘制选择区域
        if self.start_pos and self.end_pos:
            rect = self._get_selection_rect()

            # 清除选择区域的遮罩，显示原始截图
            if self.background_pixmap:
                # 计算源矩形（考虑 DPI 缩放）
                src_rect = self._rect_to_screen_pixels(rect)
                painter.drawPixmap(rect, self.background_pixmap, src_rect)

            # 绘制已完成的图形
            for item in self.drawing_paths:
                shape_type = item[0]
                color = item[1]
                width = item[2]
                data = item[3]

                pen = QPen(color, width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)

                if shape_type == 'pen' and len(data) > 1:
                    # 自由画笔
                    for i in range(len(data) - 1):
                        painter.drawLine(data[i], data[i + 1])
                elif shape_type == 'rect' and len(data) == 2:
                    # 矩形
                    rect_to_draw = QRect(data[0], data[1])
                    painter.drawRect(rect_to_draw)
                elif shape_type == 'circle' and len(data) == 2:
                    # 圆形（椭圆）
                    rect_to_draw = QRect(data[0], data[1])
                    painter.drawEllipse(rect_to_draw)
                elif shape_type == 'arrow' and len(data) == 2:
                    # 箭头
                    self._draw_arrow(painter, data[0], data[1], color, width)

            # 绘制当前正在绘制的图形
            if self.is_drawing:
                if self.current_tool == 'eraser':
                    # 橡皮擦：显示为白色半透明圆形
                    pen = QPen(QColor(255, 255, 255, 200), self.current_width)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    if len(self.current_path) > 1:
                        for i in range(len(self.current_path) - 1):
                            painter.drawLine(self.current_path[i], self.current_path[i + 1])
                else:
                    pen = QPen(self.current_color, self.current_width)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)

                    if self.current_tool == 'pen' and len(self.current_path) > 1:
                        # 自由画笔
                        for i in range(len(self.current_path) - 1):
                            painter.drawLine(self.current_path[i], self.current_path[i + 1])
                    elif self.current_tool == 'rect' and self.draw_start_pos and len(self.current_path) > 0:
                        # 矩形预览
                        rect_to_draw = QRect(self.draw_start_pos, self.current_path[-1])
                        painter.drawRect(rect_to_draw)
                    elif self.current_tool == 'circle' and self.draw_start_pos and len(self.current_path) > 0:
                        # 圆形预览
                        rect_to_draw = QRect(self.draw_start_pos, self.current_path[-1])
                        painter.drawEllipse(rect_to_draw)
                    elif self.current_tool == 'arrow' and self.draw_start_pos and len(self.current_path) > 0:
                        # 箭头预览
                        self._draw_arrow(painter, self.draw_start_pos, self.current_path[-1],
                                       self.current_color, self.current_width)

            # 绘制选择框边框（蓝色，较细）
            pen = QPen(QColor(0, 120, 215), 2)
            painter.setPen(pen)
            painter.drawRect(rect)

            # 绘制8个拖拽控制点（四角+四边中点）
            self._draw_resize_handles(painter, rect)

            # 显示尺寸信息（显示实际像素尺寸）- 在顶部中央，带圆角背景
            if not self.edit_mode:
                self._draw_size_info(painter, rect)

            # 绘制工具栏（编辑模式下）
            if self.edit_mode:
                self._draw_toolbar(painter, rect)

    def _draw_resize_handles(self, painter, rect):
        """绘制8个拖拽控制点"""
        handle_size = 8
        handle_radius = handle_size // 2

        # 8个控制点的位置
        handles = [
            (rect.left(), rect.top()),           # 左上
            (rect.center().x(), rect.top()),     # 上中
            (rect.right(), rect.top()),          # 右上
            (rect.right(), rect.center().y()),   # 右中
            (rect.right(), rect.bottom()),       # 右下
            (rect.center().x(), rect.bottom()),  # 下中
            (rect.left(), rect.bottom()),        # 左下
            (rect.left(), rect.center().y()),    # 左中
        ]

        painter.setPen(QPen(QColor(0, 120, 215), 2))
        painter.setBrush(QColor(255, 255, 255))

        for x, y in handles:
            painter.drawEllipse(QPoint(x, y), handle_radius, handle_radius)

    def _draw_size_info(self, painter, rect):
        """绘制尺寸信息（顶部中央，带圆角背景）"""
        actual_w = int(rect.width() * self.dpr)
        actual_h = int(rect.height() * self.dpr)
        size_text = f"{actual_w} × {actual_h}"

        # 计算文字尺寸
        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(size_text)
        text_height = fm.height()

        # 背景矩形（圆角）
        padding = 8
        bg_width = text_width + padding * 2
        bg_height = text_height + padding
        bg_x = rect.center().x() - bg_width // 2
        bg_y = rect.top() - bg_height - 10

        # 如果超出屏幕顶部，则显示在选择框内部
        if bg_y < 5:
            bg_y = rect.top() + 5

        bg_rect = QRect(bg_x, bg_y, bg_width, bg_height)

        # 绘制半透明圆角背景
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(50, 50, 50, 180))
        painter.drawRoundedRect(bg_rect, 4, 4)

        # 绘制文字
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, size_text)

    def _draw_arrow(self, painter, start_point, end_point, color, width):
        """绘制箭头"""
        import math

        # 保存 painter 状态
        painter.save()

        # 设置画笔和画刷
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(color)

        # 绘制箭头主线
        painter.drawLine(start_point, end_point)

        # 计算箭头头部
        dx = end_point.x() - start_point.x()
        dy = end_point.y() - start_point.y()
        length = math.sqrt(dx * dx + dy * dy)

        if length > 0:
            # 箭头头部的大小（根据线条粗细调整）
            arrow_size = max(10, width * 3)

            # 单位向量
            ux = dx / length
            uy = dy / length

            # 箭头头部的两个翼点
            angle = math.pi / 6  # 30度角
            wing1_x = end_point.x() - arrow_size * (ux * math.cos(angle) + uy * math.sin(angle))
            wing1_y = end_point.y() - arrow_size * (uy * math.cos(angle) - ux * math.sin(angle))
            wing2_x = end_point.x() - arrow_size * (ux * math.cos(angle) - uy * math.sin(angle))
            wing2_y = end_point.y() - arrow_size * (uy * math.cos(angle) + ux * math.sin(angle))

            # 绘制箭头头部（实心三角形）
            from PyQt6.QtCore import QPointF
            from PyQt6.QtGui import QPolygonF
            arrow_head = QPolygonF([
                QPointF(end_point.x(), end_point.y()),
                QPointF(wing1_x, wing1_y),
                QPointF(wing2_x, wing2_y)
            ])
            painter.drawPolygon(arrow_head)

        # 恢复 painter 状态
        painter.restore()

    def _draw_toolbar(self, painter, rect):
        """绘制现代化工具栏（底部居中圆角卡片）"""
        # 工具栏尺寸
        btn_size = 40
        spacing = 4
        padding = 12
        separator_width = 8  # 分隔线占用的宽度

        # 计算工具栏总宽度：15个按钮 + 14个间距 + 2个分隔线 + 2个padding
        toolbar_width = (btn_size * 15) + (spacing * 14) + (separator_width * 2) + (padding * 2)
        toolbar_height = btn_size + padding * 2

        # 工具栏位置：底部居中
        toolbar_x = rect.center().x() - toolbar_width // 2
        toolbar_y = rect.bottom() + 15

        # 如果超出屏幕底部，则显示在选择框上方
        if toolbar_y + toolbar_height > self.height():
            toolbar_y = rect.top() - toolbar_height - 15

        # 绘制工具栏背景（圆角白色卡片，带阴影）
        toolbar_rect = QRect(toolbar_x, toolbar_y, toolbar_width, toolbar_height)

        # 绘制阴影
        shadow_offset = 2
        shadow_rect = toolbar_rect.adjusted(shadow_offset, shadow_offset, shadow_offset, shadow_offset)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 50))
        painter.drawRoundedRect(shadow_rect, 8, 8)

        # 绘制工具栏背景
        painter.setBrush(QColor(255, 255, 255, 250))
        painter.drawRoundedRect(toolbar_rect, 8, 8)

        # 当前按钮x坐标
        current_x = toolbar_x + padding

        # 1. 移动工具
        move_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.move_btn_rect = move_btn
        self._draw_tool_button(painter, move_btn, "✥", self.current_tool == 'move')
        current_x += btn_size + spacing

        # 2. 矩形工具
        rect_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.rect_btn_rect = rect_btn
        self._draw_tool_button(painter, rect_btn, "□", self.current_tool == 'rect')
        current_x += btn_size + spacing

        # 2. 圆形工具
        circle_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.circle_btn_rect = circle_btn
        self._draw_tool_button(painter, circle_btn, "○", self.current_tool == 'circle')
        current_x += btn_size + spacing

        # 3. 画笔工具
        pen_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.pen_btn_rect = pen_btn
        self._draw_tool_button(painter, pen_btn, "✎", self.current_tool == 'pen')
        current_x += btn_size + spacing

        # 4. 箭头工具
        arrow_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.arrow_btn_rect = arrow_btn
        self._draw_tool_button(painter, arrow_btn, "→", self.current_tool == 'arrow')
        current_x += btn_size + spacing

        # 5. 橡皮擦工具
        eraser_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.eraser_btn_rect = eraser_btn
        self._draw_tool_button(painter, eraser_btn, "⌫", self.current_tool == 'eraser')
        current_x += btn_size + spacing

        # 6-8. 颜色选择（红、绿、蓝）
        colors = [QColor(255, 60, 60), QColor(76, 217, 100), QColor(0, 122, 255)]
        self.color_btn_rects = []
        for color in colors:
            color_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
            self.color_btn_rects.append((color_btn, color))
            is_selected = (self.current_color.red() == color.red() and
                          self.current_color.green() == color.green() and
                          self.current_color.blue() == color.blue())
            self._draw_color_button(painter, color_btn, color, is_selected)
            current_x += btn_size + spacing

        # 9-11. 笔触粗细
        widths = [2, 4, 6]
        self.width_btn_rects = []
        for width in widths:
            width_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
            self.width_btn_rects.append((width_btn, width))
            self._draw_width_button(painter, width_btn, width, self.current_width == width)
            current_x += btn_size + spacing

        # 第一个分隔线
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        line_x = current_x + separator_width // 2 - spacing // 2
        painter.drawLine(
            line_x, toolbar_y + padding + 8,
            line_x, toolbar_y + padding + btn_size - 8
        )
        current_x += separator_width

        # 12. 撤回按钮
        undo_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.undo_btn_rect = undo_btn
        self._draw_edit_button(painter, undo_btn, "↶", len(self.drawing_paths) > 0)
        current_x += btn_size + spacing

        # 第二个分隔线
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        line_x = current_x + separator_width // 2 - spacing // 2
        painter.drawLine(
            line_x, toolbar_y + padding + 8,
            line_x, toolbar_y + padding + btn_size - 8
        )
        current_x += separator_width

        # 13. 取消按钮
        cancel_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.cancel_btn_rect = cancel_btn
        self._draw_action_button(painter, cancel_btn, "✕", QColor(255, 59, 48))
        current_x += btn_size + spacing

        # 14. 确定按钮
        confirm_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.confirm_btn_rect = confirm_btn
        self._draw_action_button(painter, confirm_btn, "✓", QColor(52, 199, 89))

    def _draw_tool_button(self, painter, rect, text, is_selected):
        """绘制工具按钮"""
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 122, 255, 50))
            painter.drawRoundedRect(rect, 6, 6)

        # 获取按钮中心
        center = rect.center()
        icon_size = 24  # 图标尺寸

        # 设置绘制颜色和粗细
        color = QColor(0, 122, 255) if is_selected else QColor(60, 60, 60)
        pen_width = 3 if is_selected else 2

        if text == "□":
            # 绘制矩形图标
            painter.setPen(QPen(color, pen_width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            icon_rect = QRect(
                center.x() - icon_size // 2,
                center.y() - icon_size // 2,
                icon_size,
                icon_size
            )
            painter.drawRect(icon_rect)
        elif text == "○":
            # 绘制圆形图标
            painter.setPen(QPen(color, pen_width))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, icon_size // 2, icon_size // 2)
        elif text == "→":
            # 绘制箭头图标
            import math
            from PyQt6.QtCore import QPointF
            from PyQt6.QtGui import QPolygonF

            # 保存当前状态
            saved_brush = painter.brush()

            painter.setPen(QPen(color, pen_width))
            painter.setBrush(color)

            # 箭头起点和终点
            start_x = center.x() - icon_size // 2 + 2
            end_x = center.x() + icon_size // 2 - 2
            y = center.y()

            # 绘制箭头主线
            painter.drawLine(int(start_x), y, int(end_x), y)

            # 绘制箭头头部
            arrow_size = 8
            arrow_head = QPolygonF([
                QPointF(end_x, y),
                QPointF(end_x - arrow_size, y - arrow_size // 2),
                QPointF(end_x - arrow_size, y + arrow_size // 2)
            ])
            painter.drawPolygon(arrow_head)

            # 恢复画刷设置
            painter.setBrush(saved_brush)
        elif text == "✥":
            # 绘制移动图标（四方箭头）
            from PyQt6.QtCore import QPointF
            from PyQt6.QtGui import QPolygonF

            saved_brush = painter.brush()
            painter.setPen(QPen(color, pen_width))
            painter.setBrush(color)

            # 十字线长度
            line_len = icon_size // 2 - 2
            arrow_size = 5

            # 绘制水平线
            painter.drawLine(center.x() - line_len, center.y(), center.x() + line_len, center.y())
            # 绘制垂直线
            painter.drawLine(center.x(), center.y() - line_len, center.x(), center.y() + line_len)

            # 右箭头
            right_arrow = QPolygonF([
                QPointF(center.x() + line_len, center.y()),
                QPointF(center.x() + line_len - arrow_size, center.y() - arrow_size // 2 - 1),
                QPointF(center.x() + line_len - arrow_size, center.y() + arrow_size // 2 + 1)
            ])
            painter.drawPolygon(right_arrow)

            # 左箭头
            left_arrow = QPolygonF([
                QPointF(center.x() - line_len, center.y()),
                QPointF(center.x() - line_len + arrow_size, center.y() - arrow_size // 2 - 1),
                QPointF(center.x() - line_len + arrow_size, center.y() + arrow_size // 2 + 1)
            ])
            painter.drawPolygon(left_arrow)

            # 上箭头
            up_arrow = QPolygonF([
                QPointF(center.x(), center.y() - line_len),
                QPointF(center.x() - arrow_size // 2 - 1, center.y() - line_len + arrow_size),
                QPointF(center.x() + arrow_size // 2 + 1, center.y() - line_len + arrow_size)
            ])
            painter.drawPolygon(up_arrow)

            # 下箭头
            down_arrow = QPolygonF([
                QPointF(center.x(), center.y() + line_len),
                QPointF(center.x() - arrow_size // 2 - 1, center.y() + line_len - arrow_size),
                QPointF(center.x() + arrow_size // 2 + 1, center.y() + line_len - arrow_size)
            ])
            painter.drawPolygon(down_arrow)

            painter.setBrush(saved_brush)
        else:
            # 其他图标（画笔、橡皮擦等）用文字
            painter.setPen(color)
            font = painter.font()
            font.setPointSize(20)
            font.setBold(is_selected)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_color_button(self, painter, rect, color, is_selected):
        """绘制颜色按钮"""
        # 绘制颜色圆形
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        center = rect.center()
        radius = 14
        painter.drawEllipse(center, radius, radius)

        # 如果选中，绘制白色边框
        if is_selected:
            painter.setPen(QPen(QColor(255, 255, 255), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, radius, radius)
            painter.setPen(QPen(color, 2))
            painter.drawEllipse(center, radius + 2, radius + 2)

    def _draw_width_button(self, painter, rect, width, is_selected):
        """绘制笔触粗细按钮"""
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 122, 255, 50))
            painter.drawRoundedRect(rect, 6, 6)

        # 绘制线条示意
        painter.setPen(QPen(QColor(60, 60, 60) if not is_selected else QColor(0, 122, 255), width))
        painter.drawLine(
            rect.center().x() - 12, rect.center().y(),
            rect.center().x() + 12, rect.center().y()
        )

    def _draw_action_button(self, painter, rect, text, color):
        """绘制操作按钮（确定/取消）"""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, 6, 6)

        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setPointSize(18)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_edit_button(self, painter, rect, text, enabled):
        """绘制编辑按钮（撤回/清空）"""
        # 根据是否启用设置颜色
        if enabled:
            bg_color = QColor(240, 240, 240)
            text_color = QColor(60, 60, 60)
        else:
            bg_color = QColor(250, 250, 250)
            text_color = QColor(180, 180, 180)

        # 绘制背景
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(rect, 6, 6)

        # 绘制文字/图标
        painter.setPen(text_color)
        font = painter.font()
        font.setPointSize(18)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _get_selection_rect(self):
        """获取选择区域的矩形"""
        if not self.start_pos or not self.end_pos:
            return QRect()

        x1, y1 = self.start_pos.x(), self.start_pos.y()
        x2, y2 = self.end_pos.x(), self.end_pos.y()

        return QRect(
            min(x1, x2), min(y1, y2),
            abs(x2 - x1), abs(y2 - y1)
        )

    def mousePressEvent(self, event):
        """鼠标按下开始选择或涂鸦"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.edit_mode:
                # 编辑模式：检查是否点击了工具栏按钮
                clicked_button = False

                # 检查取消按钮
                if hasattr(self, 'cancel_btn_rect') and self.cancel_btn_rect.contains(event.pos()):
                    self.close()
                    return

                # 检查确定按钮
                if hasattr(self, 'confirm_btn_rect') and self.confirm_btn_rect.contains(event.pos()):
                    rect = self._get_selection_rect()
                    if rect.width() > 5 and rect.height() > 5:
                        self._save_screenshot(rect)
                    self.close()
                    return

                # 检查工具选择按钮
                if hasattr(self, 'move_btn_rect') and self.move_btn_rect.contains(event.pos()):
                    self.current_tool = 'move'
                    clicked_button = True

                if hasattr(self, 'pen_btn_rect') and self.pen_btn_rect.contains(event.pos()):
                    self.current_tool = 'pen'
                    clicked_button = True

                if hasattr(self, 'rect_btn_rect') and self.rect_btn_rect.contains(event.pos()):
                    self.current_tool = 'rect'
                    clicked_button = True

                if hasattr(self, 'circle_btn_rect') and self.circle_btn_rect.contains(event.pos()):
                    self.current_tool = 'circle'
                    clicked_button = True

                if hasattr(self, 'arrow_btn_rect') and self.arrow_btn_rect.contains(event.pos()):
                    self.current_tool = 'arrow'
                    clicked_button = True

                if hasattr(self, 'eraser_btn_rect') and self.eraser_btn_rect.contains(event.pos()):
                    self.current_tool = 'eraser'
                    clicked_button = True

                # 检查颜色选择按钮
                if hasattr(self, 'color_btn_rects'):
                    for btn_rect, color in self.color_btn_rects:
                        if btn_rect.contains(event.pos()):
                            self.current_color = color
                            clicked_button = True
                            break

                # 检查笔触粗细按钮
                if hasattr(self, 'width_btn_rects'):
                    for btn_rect, width in self.width_btn_rects:
                        if btn_rect.contains(event.pos()):
                            self.current_width = width
                            clicked_button = True
                            break

                # 检查撤回按钮
                if hasattr(self, 'undo_btn_rect') and self.undo_btn_rect.contains(event.pos()):
                    if len(self.drawing_paths) > 0:
                        self.drawing_paths.pop()  # 移除最后一个绘制
                        clicked_button = True

                # 如果点击了按钮，更新界面并返回
                if clicked_button:
                    self.update()
                    return

                # 在选择区域内开始绘制或移动
                rect = self._get_selection_rect()
                if rect.contains(event.pos()):
                    if self.current_tool == 'move':
                        # 移动模式：开始拖拽选择框
                        self.is_moving = True
                        self.move_start_pos = event.pos()
                    else:
                        # 绘制模式
                        self.is_drawing = True
                        self.draw_start_pos = event.pos()
                        if self.current_tool in ['pen', 'eraser']:
                            self.current_path = [event.pos()]
                        else:
                            # 矩形和圆形只需要起点
                            self.current_path = [event.pos()]
            else:
                # 选择模式：开始框选
                self.start_pos = event.pos()
                self.end_pos = event.pos()
                self.is_selecting = True
            self.update()

    def mouseMoveEvent(self, event):
        """鼠标移动更新选择区域、涂鸦或移动选择框"""
        if self.is_selecting:
            self.end_pos = event.pos()
            self.update()
        elif self.is_moving:
            # 移动选择框
            if self.move_start_pos:
                delta = event.pos() - self.move_start_pos
                self.start_pos = self.start_pos + delta
                self.end_pos = self.end_pos + delta
                self.move_start_pos = event.pos()
                self.update()
        elif self.is_drawing:
            if self.current_tool in ['pen', 'eraser']:
                # 画笔/橡皮擦：记录所有移动点
                self.current_path.append(event.pos())
            else:
                # 矩形/圆形：只更新终点
                if len(self.current_path) > 0:
                    self.current_path[-1] = event.pos()
                else:
                    self.current_path.append(event.pos())
            self.update()

    def mouseReleaseEvent(self, event):
        """鼠标释放完成选择、涂鸦或移动"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.is_selecting:
                # 完成框选，进入编辑模式
                self.end_pos = event.pos()
                self.is_selecting = False

                rect = self._get_selection_rect()
                if rect.width() > 5 and rect.height() > 5:
                    self.edit_mode = True
                    self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                else:
                    self.close()
                self.update()
            elif self.is_moving:
                # 完成移动
                self.is_moving = False
                self.move_start_pos = None
                self.update()
            elif self.is_drawing:
                # 完成绘制
                self.is_drawing = False

                if self.current_tool == 'eraser' and len(self.current_path) > 1:
                    # 橡皮擦：删除与橡皮擦路径相交的绘制
                    self._erase_paths(self.current_path)
                elif self.current_tool == 'pen' and len(self.current_path) > 1:
                    # 画笔：保存所有点
                    self.drawing_paths.append((
                        self.current_tool,
                        self.current_color,
                        self.current_width,
                        self.current_path.copy()
                    ))
                elif self.current_tool in ['rect', 'circle', 'arrow'] and self.draw_start_pos and len(self.current_path) > 0:
                    # 矩形/圆形/箭头：保存起点和终点
                    self.drawing_paths.append((
                        self.current_tool,
                        self.current_color,
                        self.current_width,
                        [self.draw_start_pos, self.current_path[-1]]
                    ))

                self.current_path = []
                self.draw_start_pos = None
                self.update()

    def _erase_paths(self, eraser_path):
        """删除与橡皮擦路径相交的绘制"""
        import math

        # 橡皮擦的擦除半径（基于当前笔触粗细）
        erase_radius = self.current_width * 3

        # 计算点到线段的距离
        def point_to_segment_distance(px, py, x1, y1, x2, y2):
            """计算点(px, py)到线段(x1,y1)-(x2,y2)的最短距离"""
            dx = x2 - x1
            dy = y2 - y1
            if dx == 0 and dy == 0:
                return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

            t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
            closest_x = x1 + t * dx
            closest_y = y1 + t * dy
            return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)

        # 检查路径是否与橡皮擦相交
        def path_intersects_eraser(shape_type, data):
            if shape_type == 'pen' and len(data) > 1:
                # 检查画笔路径的每个线段
                for i in range(len(data) - 1):
                    p1 = data[i]
                    p2 = data[i + 1]
                    # 检查橡皮擦的每个点是否接近这条线段
                    for eraser_point in eraser_path:
                        dist = point_to_segment_distance(
                            eraser_point.x(), eraser_point.y(),
                            p1.x(), p1.y(), p2.x(), p2.y()
                        )
                        if dist <= erase_radius:
                            return True
            elif shape_type == 'rect' and len(data) == 2:
                # 检查矩形的四条边是否与橡皮擦相交
                rect = QRect(data[0], data[1])
                # 四条边的端点
                edges = [
                    (rect.left(), rect.top(), rect.right(), rect.top()),      # 上边
                    (rect.right(), rect.top(), rect.right(), rect.bottom()),  # 右边
                    (rect.right(), rect.bottom(), rect.left(), rect.bottom()), # 下边
                    (rect.left(), rect.bottom(), rect.left(), rect.top())     # 左边
                ]
                for x1, y1, x2, y2 in edges:
                    for eraser_point in eraser_path:
                        dist = point_to_segment_distance(
                            eraser_point.x(), eraser_point.y(), x1, y1, x2, y2
                        )
                        if dist <= erase_radius:
                            return True
            elif shape_type == 'circle' and len(data) == 2:
                # 检查圆形边界是否与橡皮擦相交
                rect = QRect(data[0], data[1])
                center_x = (rect.left() + rect.right()) / 2
                center_y = (rect.top() + rect.bottom()) / 2
                radius_x = abs(rect.width()) / 2
                radius_y = abs(rect.height()) / 2

                for eraser_point in eraser_path:
                    # 计算点到椭圆中心的距离
                    dx = eraser_point.x() - center_x
                    dy = eraser_point.y() - center_y

                    # 归一化到单位圆
                    if radius_x > 0 and radius_y > 0:
                        normalized_dist = math.sqrt((dx / radius_x) ** 2 + (dy / radius_y) ** 2)
                        # 检查是否在椭圆边界附近（允许一定误差）
                        if abs(normalized_dist - 1.0) * max(radius_x, radius_y) <= erase_radius:
                            return True
            elif shape_type == 'arrow' and len(data) == 2:
                # 检查箭头线段是否与橡皮擦相交
                p1 = data[0]
                p2 = data[1]
                for eraser_point in eraser_path:
                    dist = point_to_segment_distance(
                        eraser_point.x(), eraser_point.y(),
                        p1.x(), p1.y(), p2.x(), p2.y()
                    )
                    if dist <= erase_radius:
                        return True
            return False

        # 过滤掉与橡皮擦相交的路径
        self.drawing_paths = [
            item for item in self.drawing_paths
            if not path_intersects_eraser(item[0], item[3])
        ]

    def keyPressEvent(self, event):
        """按 ESC 取消截图"""
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def mouseDoubleClickEvent(self, event):
        """双击鼠标左键确认截图"""
        if event.button() == Qt.MouseButton.LeftButton and self.edit_mode:
            # 检查是否点击在工具栏按钮上
            clicked_on_toolbar = False

            # 检查所有工具栏按钮
            toolbar_buttons = [
                'cancel_btn_rect', 'confirm_btn_rect', 'pen_btn_rect',
                'rect_btn_rect', 'circle_btn_rect', 'arrow_btn_rect',
                'eraser_btn_rect', 'undo_btn_rect'
            ]

            for btn_name in toolbar_buttons:
                if hasattr(self, btn_name):
                    btn_rect = getattr(self, btn_name)
                    if btn_rect.contains(event.pos()):
                        clicked_on_toolbar = True
                        break

            # 检查颜色和粗细按钮
            if not clicked_on_toolbar:
                if hasattr(self, 'color_btn_rects'):
                    for btn_rect, _ in self.color_btn_rects:
                        if btn_rect.contains(event.pos()):
                            clicked_on_toolbar = True
                            break

                if hasattr(self, 'width_btn_rects') and not clicked_on_toolbar:
                    for btn_rect, _ in self.width_btn_rects:
                        if btn_rect.contains(event.pos()):
                            clicked_on_toolbar = True
                            break

            # 如果不是点击在工具栏上，则保存截图
            if not clicked_on_toolbar:
                rect = self._get_selection_rect()
                if rect.width() > 5 and rect.height() > 5:
                    self._save_screenshot(rect)
                self.close()

    def _save_screenshot(self, rect):
        """保存截图到临时目录（包含涂鸦）"""
        import tempfile
        # 获取系统临时目录
        temp_dir = Path(tempfile.gettempdir()) / "screenshots"
        temp_dir.mkdir(exist_ok=True)

        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"
        filepath = temp_dir / filename

        # 从背景截图中裁剪选择区域（使用物理像素坐标）
        if self.background_pixmap:
            src_rect = self._rect_to_screen_pixels(rect)
            cropped = self.background_pixmap.copy(src_rect)

            # 如果有涂鸦，将涂鸦绘制到截图上
            # 注意：cropped 继承了 background_pixmap 的 devicePixelRatio
            # Qt painter 会自动处理 DPR 缩放，所以使用逻辑坐标即可
            if self.drawing_paths:
                painter = QPainter(cropped)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                # 计算涂鸦相对于选择区域的逻辑坐标
                for item in self.drawing_paths:
                    shape_type = item[0]
                    color = item[1]
                    width = item[2]
                    data = item[3]

                    pen = QPen(color, width)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)

                    if shape_type == 'pen' and len(data) > 1:
                        # 画笔：绘制所有点连接的线
                        for i in range(len(data) - 1):
                            p1 = QPoint(
                                data[i].x() - rect.x(),
                                data[i].y() - rect.y()
                            )
                            p2 = QPoint(
                                data[i + 1].x() - rect.x(),
                                data[i + 1].y() - rect.y()
                            )
                            painter.drawLine(p1, p2)
                    elif shape_type == 'rect' and len(data) == 2:
                        # 矩形：绘制矩形
                        p1 = QPoint(
                            data[0].x() - rect.x(),
                            data[0].y() - rect.y()
                        )
                        p2 = QPoint(
                            data[1].x() - rect.x(),
                            data[1].y() - rect.y()
                        )
                        rect_to_draw = QRect(p1, p2)
                        painter.drawRect(rect_to_draw)
                    elif shape_type == 'circle' and len(data) == 2:
                        # 圆形：绘制椭圆
                        p1 = QPoint(
                            data[0].x() - rect.x(),
                            data[0].y() - rect.y()
                        )
                        p2 = QPoint(
                            data[1].x() - rect.x(),
                            data[1].y() - rect.y()
                        )
                        rect_to_draw = QRect(p1, p2)
                        painter.drawEllipse(rect_to_draw)
                    elif shape_type == 'arrow' and len(data) == 2:
                        # 箭头：绘制箭头
                        p1 = QPoint(
                            data[0].x() - rect.x(),
                            data[0].y() - rect.y()
                        )
                        p2 = QPoint(
                            data[1].x() - rect.x(),
                            data[1].y() - rect.y()
                        )
                        self._draw_arrow(painter, p1, p2, color, width)

                painter.end()

            cropped.save(str(filepath), "PNG")

            # 同时复制图片和路径到剪贴板
            clipboard = QApplication.clipboard()
            # 先复制图片
            clipboard.setPixmap(cropped)
            # 然后复制路径（作为备用，某些应用可能需要路径）
            # 注意：这会覆盖图片，所以我们使用 MimeData 同时设置两者
            from PyQt6.QtCore import QMimeData, QUrl
            mime_data = QMimeData()
            mime_data.setImageData(cropped.toImage())
            mime_data.setText(str(filepath))
            mime_data.setUrls([QUrl.fromLocalFile(str(filepath))])
            clipboard.setMimeData(mime_data)

            # 通知回调
            self.on_capture_done(str(filepath))

    def showEvent(self, event):
        """显示时激活窗口"""
        super().showEvent(event)
        self.activateWindow()
        self.raise_()
        QTimer.singleShot(0, self._post_show_sync)

    def resizeEvent(self, event):
        """窗口尺寸变化时校准 DPR（macOS 全屏切换会触发）"""
        super().resizeEvent(event)
        if sys.platform == 'darwin' and self.background_pixmap:
            QTimer.singleShot(0, self._post_show_sync)


class SnapTool(QApplication):
    """截屏工具主程序"""

    def __init__(self, argv):
        super().__init__(argv)

        self.setQuitOnLastWindowClosed(False)

        # macOS: 隐藏 Dock 图标，只显示托盘图标
        if sys.platform == 'darwin':
            try:
                from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
                NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
            except ImportError:
                pass

        # 创建热键信号
        self.hotkey_signal = HotkeySignal()
        self.hotkey_signal.triggered.connect(self._on_hotkey_triggered)

        # 创建系统托盘
        self._setup_tray()

        # 当前截图窗口
        self.overlay = None

        # 启动全局热键监听
        self._setup_hotkey()

    def _setup_tray(self):
        """设置系统托盘图标"""
        self.tray_icon = QSystemTrayIcon(self)

        # 创建截图工具图标
        icon_size = 22 if sys.platform == 'darwin' else 32
        pixmap = QPixmap(icon_size, icon_size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制相机/截图图标
        margin = 2
        rect_size = icon_size - margin * 2

        # 背景圆角矩形
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 122, 255))  # iOS 蓝色
        painter.drawRoundedRect(margin, margin, rect_size, rect_size, 4, 4)

        # 绘制剪刀/裁剪图标
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # 内部矩形框（表示截图区域）
        inner_margin = 5
        inner_size = icon_size - inner_margin * 2
        painter.drawRect(inner_margin, inner_margin, inner_size, inner_size)

        # 四个角的标记
        corner_len = 4
        # 左上角
        painter.drawLine(inner_margin, inner_margin, inner_margin + corner_len, inner_margin)
        painter.drawLine(inner_margin, inner_margin, inner_margin, inner_margin + corner_len)
        # 右上角
        painter.drawLine(inner_margin + inner_size, inner_margin, inner_margin + inner_size - corner_len, inner_margin)
        painter.drawLine(inner_margin + inner_size, inner_margin, inner_margin + inner_size, inner_margin + corner_len)
        # 左下角
        painter.drawLine(inner_margin, inner_margin + inner_size, inner_margin + corner_len, inner_margin + inner_size)
        painter.drawLine(inner_margin, inner_margin + inner_size, inner_margin, inner_margin + inner_size - corner_len)
        # 右下角
        painter.drawLine(inner_margin + inner_size, inner_margin + inner_size, inner_margin + inner_size - corner_len, inner_margin + inner_size)
        painter.drawLine(inner_margin + inner_size, inner_margin + inner_size, inner_margin + inner_size, inner_margin + inner_size - corner_len)

        painter.end()
        self.tray_icon.setIcon(QIcon(pixmap))

        # 根据平台显示不同热键
        hotkey_text = "Ctrl+A" if sys.platform == 'darwin' else "Shift+Alt+B"

        # 创建托盘菜单
        menu = QMenu()

        screenshot_action = QAction(f"截图 ({hotkey_text})", self)
        screenshot_action.triggered.connect(self._start_screenshot)
        menu.addAction(screenshot_action)

        menu.addSeparator()

        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.setToolTip(f"截屏工具 - {hotkey_text}")
        self.tray_icon.show()

        # 显示启动提示
        self.tray_icon.showMessage(
            "截屏工具已启动",
            f"按 {hotkey_text} 开始截图",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )

    def _setup_hotkey(self):
        """设置全局热键 - Mac: Ctrl+A (使用 Quartz), Windows: Shift+Alt+B (使用 pynput)"""
        if sys.platform == 'darwin':
            self._setup_hotkey_macos()
        else:
            self._setup_hotkey_pynput()

    def _setup_hotkey_macos(self):
        """macOS: 使用 Quartz CGEventTap 监听全局按键"""
        import Quartz
        from Quartz import (
            CGEventTapCreate, kCGSessionEventTap, kCGHeadInsertEventTap,
            kCGEventKeyDown, CGEventTapEnable, CFMachPortCreateRunLoopSource,
            CFRunLoopGetCurrent, CFRunLoopAddSource, kCFRunLoopCommonModes,
            CGEventGetFlags, CGEventGetIntegerValueField, kCGKeyboardEventKeycode,
            kCGEventFlagMaskControl
        )
        import threading

        def callback(proxy, event_type, event, refcon):
            if event_type == kCGEventKeyDown:
                # 检查是否按下 Ctrl
                flags = CGEventGetFlags(event)
                ctrl_pressed = (flags & kCGEventFlagMaskControl) != 0

                # 获取按键码 (A 键的 keycode 是 0)
                keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)

                if ctrl_pressed and keycode == 0:  # Ctrl + A
                    self.hotkey_signal.triggered.emit()

            return event

        # 创建事件监听
        event_mask = (1 << kCGEventKeyDown)
        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            0,  # 不修改事件
            event_mask,
            callback,
            None
        )

        if tap:
            run_loop_source = CFMachPortCreateRunLoopSource(None, tap, 0)

            def run_tap():
                CFRunLoopAddSource(CFRunLoopGetCurrent(), run_loop_source, kCFRunLoopCommonModes)
                CGEventTapEnable(tap, True)
                Quartz.CFRunLoopRun()

            tap_thread = threading.Thread(target=run_tap, daemon=True)
            tap_thread.start()

    def _setup_hotkey_pynput(self):
        """Windows: 使用 pynput 监听全局按键"""
        self.current_keys = set()

        def on_press(key):
            self.current_keys.add(key)

            # Windows: Shift+Alt+B
            shift_pressed = (
                keyboard.Key.shift in self.current_keys or
                keyboard.Key.shift_l in self.current_keys or
                keyboard.Key.shift_r in self.current_keys
            )
            alt_pressed = (
                keyboard.Key.alt in self.current_keys or
                keyboard.Key.alt_l in self.current_keys or
                keyboard.Key.alt_r in self.current_keys or
                keyboard.Key.alt_gr in self.current_keys
            )
            try:
                b_pressed = hasattr(key, 'char') and key.char and key.char.lower() == 'b'
            except AttributeError:
                b_pressed = False

            if shift_pressed and alt_pressed and b_pressed:
                self.hotkey_signal.triggered.emit()
                self.current_keys.clear()

        def on_release(key):
            self.current_keys.discard(key)

        self.keyboard_listener = keyboard.Listener(
            on_press=on_press,
            on_release=on_release
        )
        self.keyboard_listener.start()

    def _on_hotkey_triggered(self):
        """热键触发时启动截图"""
        # macOS: 先激活应用，确保事件循环正常工作
        if sys.platform == 'darwin':
            try:
                from AppKit import NSApplication
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            except ImportError:
                pass
        # 使用 QTimer 确保在主线程执行
        QTimer.singleShot(0, self._start_screenshot)
        # 强制处理事件
        self.processEvents()

    def _get_current_screen_info(self):
        """获取鼠标所在屏幕的信息"""
        cursor_pos = QCursor.pos()

        # 使用 mss 获取显示器信息
        # 注意：Mac 上 mss.monitors 返回逻辑像素坐标，Windows 上返回物理像素坐标
        with mss.mss() as sct:
            # monitors[0] 是所有显示器的组合，monitors[1:] 是各个显示器
            monitors = sct.monitors[1:]

        # 找到鼠标所在的 Qt 屏幕
        screens = QGuiApplication.screens()
        current_screen = None

        for screen in screens:
            if screen.geometry().contains(cursor_pos):
                current_screen = screen
                break

        if current_screen is None:
            current_screen = QGuiApplication.primaryScreen()

        geometry = current_screen.geometry()
        dpr = current_screen.devicePixelRatio()

        # Qt geometry 使用逻辑像素
        screen_left = geometry.x()
        screen_top = geometry.y()
        screen_width = geometry.width()
        screen_height = geometry.height()

        # 在 mss monitors 中找到匹配的显示器（通过位置匹配）
        mss_monitor = None
        for mon in monitors:
            # 位置匹配（允许小误差）
            if abs(mon["left"] - screen_left) < 10 and abs(mon["top"] - screen_top) < 10:
                mss_monitor = mon
                break

        # 如果位置匹配失败，尝试尺寸匹配（使用逻辑像素，Mac 上 mss 返回逻辑像素）
        if mss_monitor is None:
            for mon in monitors:
                if mon["width"] == screen_width and mon["height"] == screen_height:
                    mss_monitor = mon
                    break

        # 最后兜底：使用逻辑像素坐标
        if mss_monitor is None:
            mss_monitor = {
                "left": screen_left,
                "top": screen_top,
                "width": screen_width,
                "height": screen_height
            }

        return (geometry, mss_monitor, dpr, current_screen)

    def _start_screenshot(self):
        """开始截图"""
        if self.overlay and self.overlay.isVisible():
            return

        # macOS: 强制激活应用到前台，确保窗口能正确显示
        if sys.platform == 'darwin':
            try:
                from AppKit import NSApplication
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            except ImportError:
                pass

        screen_info = self._get_current_screen_info()
        self.overlay = ScreenshotOverlay(self._on_capture_done, screen_info)
        if sys.platform == 'darwin':
            self.overlay.show()
            self.overlay.raise_()
            self.overlay.activateWindow()
        else:
            self.overlay.showFullScreen()

    def _on_capture_done(self, filepath):
        """截图完成回调"""
        self.tray_icon.showMessage(
            "截图已保存",
            f"图片和路径已复制到剪贴板\n{filepath}",
            QSystemTrayIcon.MessageIcon.Information,
            3000
        )


def main():
    app = SnapTool(sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
