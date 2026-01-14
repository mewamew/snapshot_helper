# -*- coding: utf-8 -*-
"""
截屏工具 - 按 Shift+Alt+B 触发框选截图
截图保存到下载目录，路径自动复制到剪贴板
"""

import sys
import os
import ctypes
import math
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
    QPainter, QColor, QPen, QPixmap, QCursor, QIcon, QAction, QImage, QGuiApplication,
    QFontMetrics, QFont
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
        self.current_tool = 'move'  # 'move', 'pen', 'rect', 'circle', 'arrow', 'line', 'eraser'
        self.is_moving = False  # 是否正在移动选择框
        self.move_start_pos = None  # 移动起始位置
        self.current_color = QColor(255, 60, 60)  # 红色
        self.current_width = 4  # 笔触粗细（默认中等）
        self.draw_start_pos = None  # 绘制形状的起始位置
        self.text_input = None  # QLineEdit 文字输入框
        self.text_input_pos = None  # 文字输入位置
        self.current_font_size = 20  # 默认中等字号
        # 图形拖拽状态
        self.dragging_shape_index = None  # 正在拖拽的图形索引
        self.hovered_shape_index = None   # 鼠标悬停的图形索引
        self.drag_start_pos = None        # 拖拽起始位置

        # 参数面板状态
        self.param_panel_open = False  # 参数面板是否打开
        self.param_panel_rect = None   # 参数面板矩形区域
        self.param_panel_items = []    # [(rect, type, value), ...] type: 'color'|'width'|'font_size'
        self.current_tool_btn_rect = None  # 当前工具按钮的矩形（用于定位参数面板）

        # 窗口检测状态（用于自动选中窗口）
        self.detected_windows = []      # 检测到的窗口列表
        self.hovered_window_rect = None # 当前悬停的窗口矩形
        self.hovered_window_id = None   # 当前悬停的窗口ID
        self.selected_window_id = None  # 选中的窗口ID（用于单窗口截图）
        self.selected_window_pixmap = None  # 选中窗口的截图（用于编辑时显示）
        self.last_window_refresh = 0    # 上次刷新窗口列表的时间

        # 文字直接输入状态（无输入框模式）
        self.text_editing = False       # 是否正在输入文字
        self.text_editing_pos = None    # 输入位置
        self.text_editing_content = ""  # 当前输入的内容
        self.cursor_visible = True      # 光标是否可见（用于闪烁）
        self.cursor_timer = None        # 光标闪烁定时器

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

        # 启用鼠标追踪（用于窗口悬停检测）
        self.setMouseTracking(True)

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

    def _refresh_windows(self):
        """刷新屏幕上的窗口列表"""
        import time
        current_time = time.time()

        # 限制刷新频率（200ms 一次）
        if current_time - self.last_window_refresh < 0.2:
            return
        self.last_window_refresh = current_time

        if sys.platform == 'darwin':
            self._refresh_windows_macos()
        elif sys.platform == 'win32':
            self._refresh_windows_windows()

    def _refresh_windows_macos(self):
        """macOS: 使用 Quartz 获取窗口列表"""
        try:
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGWindowListExcludeDesktopElements,
                kCGNullWindowID
            )

            # 获取屏幕上的窗口（排除桌面元素）
            options = kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements
            window_list = CGWindowListCopyWindowInfo(options, kCGNullWindowID)

            self.detected_windows = []
            for win_info in window_list:
                bounds = win_info.get('kCGWindowBounds', {})
                width = bounds.get('Width', 0)
                height = bounds.get('Height', 0)

                # 跳过太小的窗口
                if width < 50 or height < 50:
                    continue

                # 跳过自己的窗口
                owner_pid = win_info.get('kCGWindowOwnerPID', 0)
                if owner_pid == os.getpid():
                    continue

                window = {
                    'id': win_info.get('kCGWindowNumber', 0),  # 窗口ID，用于单窗口截图
                    'layer': win_info.get('kCGWindowLayer', 0),
                    'name': win_info.get('kCGWindowName', ''),
                    'owner': win_info.get('kCGWindowOwnerName', ''),
                    'rect': QRect(
                        int(bounds.get('X', 0)),
                        int(bounds.get('Y', 0)),
                        int(width),
                        int(height)
                    )
                }
                self.detected_windows.append(window)

            # 注意：CGWindowListCopyWindowInfo 已按前后顺序返回窗口，无需排序

        except Exception as e:
            print(f"窗口检测失败: {e}")
            self.detected_windows = []

    def _refresh_windows_windows(self):
        """Windows: 使用 win32gui 获取窗口列表"""
        try:
            import win32gui
            import win32process

            self.detected_windows = []
            current_pid = os.getpid()

            def enum_windows_callback(hwnd, _):
                # 跳过不可见窗口
                if not win32gui.IsWindowVisible(hwnd):
                    return True

                # 跳过最小化窗口
                if win32gui.IsIconic(hwnd):
                    return True

                # 获取窗口位置
                try:
                    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                except Exception:
                    return True

                width = right - left
                height = bottom - top

                # 跳过太小的窗口
                if width < 50 or height < 50:
                    return True

                # 跳过自己的窗口
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if pid == current_pid:
                        return True
                except Exception:
                    pass

                # 获取窗口标题
                try:
                    title = win32gui.GetWindowText(hwnd)
                except Exception:
                    title = ''

                # 跳过没有标题的窗口（通常是系统窗口）
                if not title:
                    return True

                window = {
                    'id': hwnd,  # 窗口句柄，用于单窗口截图
                    'layer': 0,  # Windows 没有 layer 概念，统一设为 0
                    'name': title,
                    'owner': '',
                    'rect': QRect(left, top, width, height)
                }
                self.detected_windows.append(window)
                return True

            win32gui.EnumWindows(enum_windows_callback, None)

            # Windows 的 EnumWindows 按 Z-order 返回（前面的窗口先返回）

        except ImportError:
            print("窗口检测需要 pywin32，请运行: pip install pywin32")
            self.detected_windows = []
        except Exception as e:
            print(f"窗口检测失败: {e}")
            self.detected_windows = []

    def _get_window_at_pos(self, pos):
        """获取指定位置的窗口矩形和ID，返回 (rect, window_id) 或 (None, None)"""
        # 先刷新窗口列表
        self._refresh_windows()

        if not self.detected_windows:
            return None, None

        # 转换为屏幕绝对坐标
        screen_pos = QPoint(
            pos.x() + self.screen_geometry.x(),
            pos.y() + self.screen_geometry.y()
        )

        # 按层级从高到低遍历（跳过 layer > 0 的系统窗口如菜单栏）
        for window in self.detected_windows:
            # 只匹配正常窗口（layer <= 0）
            if window['layer'] > 0:
                continue
            if window['rect'].contains(screen_pos):
                # 转换回窗口内坐标
                window_rect = QRect(
                    window['rect'].x() - self.screen_geometry.x(),
                    window['rect'].y() - self.screen_geometry.y(),
                    window['rect'].width(),
                    window['rect'].height()
                )
                return window_rect, window['id']

        return None, None

    def _capture_single_window(self, window_id):
        """截取单个窗口的图像"""
        if sys.platform == 'darwin':
            return self._capture_single_window_macos(window_id)
        elif sys.platform == 'win32':
            return self._capture_single_window_windows(window_id)
        return None

    def _capture_single_window_macos(self, window_id):
        """macOS: 使用 Quartz 截取单个窗口"""
        try:
            import Quartz
            from Quartz import (
                CGWindowListCreateImage, kCGWindowListOptionIncludingWindow,
                kCGWindowImageBoundsIgnoreFraming, CGRectNull
            )

            # 使用 kCGWindowListOptionIncludingWindow 只截取指定窗口
            # CGRectNull 表示截取整个窗口
            cg_image = CGWindowListCreateImage(
                CGRectNull,
                kCGWindowListOptionIncludingWindow,
                window_id,
                kCGWindowImageBoundsIgnoreFraming
            )

            if cg_image is None:
                return None

            # 获取图像尺寸
            width = Quartz.CGImageGetWidth(cg_image)
            height = Quartz.CGImageGetHeight(cg_image)
            bytes_per_row = Quartz.CGImageGetBytesPerRow(cg_image)

            # 转换为 QPixmap
            from Quartz import CGImageGetDataProvider, CGDataProviderCopyData
            data_provider = CGImageGetDataProvider(cg_image)
            data = CGDataProviderCopyData(data_provider)

            qimg = QImage(data, width, height, bytes_per_row, QImage.Format.Format_ARGB32)
            pixmap = QPixmap.fromImage(qimg.copy())
            pixmap.setDevicePixelRatio(self.dpr)

            return pixmap

        except Exception as e:
            print(f"单窗口截图失败: {e}")
            return None

    def _capture_single_window_windows(self, hwnd):
        """Windows: 使用 PrintWindow 截取单个窗口"""
        try:
            import win32gui
            import win32ui
            import win32con

            # 获取窗口尺寸
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top

            if width <= 0 or height <= 0:
                return None

            # 创建设备上下文
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            # 创建位图
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(bitmap)

            # 使用 PrintWindow 截取窗口（包括被遮挡部分）
            # PW_RENDERFULLCONTENT = 2，可以截取 DWM 合成的内容
            result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)

            if not result:
                # 如果 PrintWindow 失败，尝试使用 BitBlt
                save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)

            # 获取位图数据
            bmp_info = bitmap.GetInfo()
            bmp_bits = bitmap.GetBitmapBits(True)

            # 转换为 QImage (BGRA 格式)
            qimg = QImage(
                bmp_bits,
                bmp_info['bmWidth'],
                bmp_info['bmHeight'],
                QImage.Format.Format_ARGB32
            )

            # 清理资源
            win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)

            pixmap = QPixmap.fromImage(qimg.copy())
            pixmap.setDevicePixelRatio(self.dpr)

            return pixmap

        except ImportError:
            print("单窗口截图需要 pywin32，请运行: pip install pywin32")
            return None
        except Exception as e:
            print(f"单窗口截图失败: {e}")
            return None

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

        # 绘制窗口高亮边框（选择前）
        if self.hovered_window_rect and not self.edit_mode:
            # 先清除窗口区域的遮罩
            if self.background_pixmap:
                src_rect = self._rect_to_screen_pixels(self.hovered_window_rect)
                painter.drawPixmap(self.hovered_window_rect, self.background_pixmap, src_rect)
            # 绘制高亮边框
            painter.setPen(QPen(QColor(0, 200, 83), 3))  # 绿色边框
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.hovered_window_rect)

        # 如果正在选择，绘制选择区域
        if self.start_pos and self.end_pos:
            rect = self._get_selection_rect()

            # 清除选择区域的遮罩，显示原始截图
            if self.selected_window_pixmap:
                # 使用单窗口截图显示（窗口选择模式）
                painter.drawPixmap(rect, self.selected_window_pixmap)
            elif self.background_pixmap:
                # 计算源矩形（考虑 DPI 缩放）
                src_rect = self._rect_to_screen_pixels(rect)
                painter.drawPixmap(rect, self.background_pixmap, src_rect)

            # 绘制已完成的图形
            for idx, item in enumerate(self.drawing_paths):
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
                elif shape_type == 'line' and len(data) == 2:
                    # 直线
                    painter.drawLine(data[0], data[1])
                elif shape_type == 'text' and len(data) == 2:
                    # 文字
                    pos, text = data
                    font = painter.font()
                    font.setPointSize(width)  # width 这里实际是 font_size
                    font.setBold(True)
                    painter.setFont(font)
                    painter.setPen(color)
                    painter.drawText(pos, text)

                # 如果正在拖拽或悬停这个图形，绘制虚线矩形框
                if idx == self.dragging_shape_index or idx == self.hovered_shape_index:
                    bounds = self._get_shape_bounds(idx)
                    if not bounds.isEmpty():
                        # 添加一些 padding
                        bounds = bounds.adjusted(-4, -4, 4, 4)
                        dash_pen = QPen(QColor(0, 122, 255), 2, Qt.PenStyle.DashLine)
                        painter.setPen(dash_pen)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawRect(bounds)

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
                    elif self.current_tool == 'line' and self.draw_start_pos and len(self.current_path) > 0:
                        # 直线预览
                        painter.drawLine(self.draw_start_pos, self.current_path[-1])

            # 绘制正在输入的文字和光标
            if self.text_editing and self.text_editing_pos:
                font = painter.font()
                font.setPointSize(self.current_font_size)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(self.current_color)

                # 绘制已输入的文字
                if self.text_editing_content:
                    painter.drawText(self.text_editing_pos, self.text_editing_content)

                # 绘制光标
                if self.cursor_visible:
                    font_metrics = QFontMetrics(font)
                    if self.text_editing_content:
                        cursor_x = self.text_editing_pos.x() + font_metrics.horizontalAdvance(self.text_editing_content)
                    else:
                        cursor_x = self.text_editing_pos.x()
                    cursor_y = self.text_editing_pos.y()
                    cursor_height = font_metrics.height()

                    # 绘制光标线
                    cursor_pen = QPen(self.current_color, 2)
                    painter.setPen(cursor_pen)
                    painter.drawLine(cursor_x, cursor_y - cursor_height + 4, cursor_x, cursor_y + 4)

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

        # 按钮数量：8个工具 + 1撤销 + 2操作按钮 = 11个
        total_btn_count = 11

        # 计算工具栏总宽度
        toolbar_width = (btn_size * total_btn_count) + (spacing * (total_btn_count - 1)) + (separator_width * 2) + (padding * 2)
        toolbar_height = btn_size + padding * 2

        # 工具栏位置：底部居中
        toolbar_x = rect.center().x() - toolbar_width // 2
        toolbar_y = rect.bottom() + 15

        # 如果超出屏幕底部，则显示在选择框上方
        if toolbar_y + toolbar_height > self.height():
            toolbar_y = rect.top() - toolbar_height - 15

        # 如果超出屏幕左侧边界，调整到左侧边缘
        if toolbar_x < 5:
            toolbar_x = 5
        # 如果超出屏幕右侧边界，调整到右侧边缘
        if toolbar_x + toolbar_width > self.width() - 5:
            toolbar_x = self.width() - toolbar_width - 5

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

        # 5. 直线工具
        line_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.line_btn_rect = line_btn
        self._draw_tool_button(painter, line_btn, "╱", self.current_tool == 'line')
        current_x += btn_size + spacing

        # 6. 橡皮擦工具
        eraser_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.eraser_btn_rect = eraser_btn
        self._draw_tool_button(painter, eraser_btn, "⌫", self.current_tool == 'eraser')
        current_x += btn_size + spacing

        # 8. 文字工具
        text_btn = QRect(current_x, toolbar_y + padding, btn_size, btn_size)
        self.text_btn_rect = text_btn
        self._draw_tool_button(painter, text_btn, "A", self.current_tool == 'text')
        current_x += btn_size + spacing

        # 记录当前工具按钮的位置（用于定位参数面板）
        tool_btn_map = {
            'move': self.move_btn_rect,
            'rect': self.rect_btn_rect,
            'circle': self.circle_btn_rect,
            'pen': self.pen_btn_rect,
            'arrow': self.arrow_btn_rect,
            'line': self.line_btn_rect,
            'eraser': self.eraser_btn_rect,
            'text': self.text_btn_rect,
        }
        self.current_tool_btn_rect = tool_btn_map.get(self.current_tool)

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

        # 绘制参数面板（如果打开）
        self._draw_param_panel(painter)

    def _draw_param_panel(self, painter):
        """绘制当前工具的参数面板"""
        # 判断当前工具是否需要参数面板
        tools_with_color_width = ['rect', 'circle', 'pen', 'arrow', 'line']
        tools_with_color_fontsize = ['text']

        if self.current_tool not in tools_with_color_width + tools_with_color_fontsize:
            self.param_panel_open = False
            return

        if not self.param_panel_open or not self.current_tool_btn_rect:
            return

        # 参数面板尺寸
        btn_size = 36
        spacing = 6
        padding = 10

        # 根据工具类型决定面板内容
        if self.current_tool in tools_with_color_width:
            # 颜色 + 线宽
            colors = [QColor(255, 60, 60), QColor(76, 217, 100), QColor(0, 122, 255)]
            widths = [2, 4, 6]
            item_count = len(colors) + len(widths) + 1  # +1 是分隔线
        else:
            # 颜色 + 字体大小
            colors = [QColor(255, 60, 60), QColor(76, 217, 100), QColor(0, 122, 255)]
            font_sizes = [(14, "S"), (20, "M"), (28, "L")]
            item_count = len(colors) + len(font_sizes) + 1

        # 计算面板尺寸
        panel_width = (btn_size * item_count) + (spacing * (item_count - 1)) + (padding * 2) - btn_size // 2
        panel_height = btn_size + padding * 2

        # 面板位置：工具按钮正下方（下拉）
        tool_btn_center_x = self.current_tool_btn_rect.center().x()
        panel_x = tool_btn_center_x - panel_width // 2
        panel_y = self.current_tool_btn_rect.bottom() + 8

        # 边界检查
        if panel_x < 5:
            panel_x = 5
        if panel_x + panel_width > self.width() - 5:
            panel_x = self.width() - panel_width - 5
        if panel_y + panel_height > self.height() - 5:
            # 如果下方空间不足，显示在按钮上方
            panel_y = self.current_tool_btn_rect.top() - panel_height - 8

        # 保存面板矩形
        self.param_panel_rect = QRect(panel_x, panel_y, panel_width, panel_height)

        # 绘制阴影
        shadow_offset = 2
        shadow_rect = self.param_panel_rect.adjusted(shadow_offset, shadow_offset, shadow_offset, shadow_offset)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 50))
        painter.drawRoundedRect(shadow_rect, 8, 8)

        # 绘制面板背景
        painter.setBrush(QColor(255, 255, 255, 250))
        painter.drawRoundedRect(self.param_panel_rect, 8, 8)

        # 绘制面板内容
        current_x = panel_x + padding
        self.param_panel_items = []

        # 绘制颜色选项
        for color in colors:
            color_rect = QRect(current_x, panel_y + padding, btn_size, btn_size)
            is_selected = (self.current_color.red() == color.red() and
                          self.current_color.green() == color.green() and
                          self.current_color.blue() == color.blue())
            self._draw_color_button(painter, color_rect, color, is_selected)
            self.param_panel_items.append((color_rect, 'color', color))
            current_x += btn_size + spacing

        # 绘制分隔线
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        line_x = current_x - spacing // 2
        painter.drawLine(
            line_x, panel_y + padding + 6,
            line_x, panel_y + padding + btn_size - 6
        )
        current_x += spacing

        # 根据工具类型绘制第二组选项
        if self.current_tool in tools_with_color_width:
            # 绘制线宽选项
            for width in widths:
                width_rect = QRect(current_x, panel_y + padding, btn_size, btn_size)
                self._draw_width_button(painter, width_rect, width, self.current_width == width)
                self.param_panel_items.append((width_rect, 'width', width))
                current_x += btn_size + spacing
        else:
            # 绘制字体大小选项
            for size, label in font_sizes:
                font_rect = QRect(current_x, panel_y + padding, btn_size, btn_size)
                is_selected = (self.current_font_size == size)
                self._draw_font_size_button(painter, font_rect, label, is_selected, True)
                self.param_panel_items.append((font_rect, 'font_size', size))
                current_x += btn_size + spacing

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

    def _draw_font_size_button(self, painter, rect, label, is_selected, is_active):
        """绘制字体大小按钮"""
        if is_selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 122, 255, 50))
            painter.drawRoundedRect(rect, 6, 6)

        # 非激活状态（非文字工具）显示灰色
        if is_active:
            color = QColor(0, 122, 255) if is_selected else QColor(60, 60, 60)
        else:
            color = QColor(180, 180, 180)

        painter.setPen(color)
        font = painter.font()
        font.setPointSize(16)
        font.setBold(is_selected)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _get_text_at_pos(self, pos):
        """检测点击位置是否有文字，返回文字索引或 None"""
        for i, (shape_type, color, size, data) in enumerate(self.drawing_paths):
            if shape_type == 'text' and len(data) == 2:
                text_pos, text = data
                # 估算文字边界框
                font_metrics = QFontMetrics(QFont("", size))
                text_width = font_metrics.horizontalAdvance(text)
                text_height = font_metrics.height()
                text_rect = QRect(
                    text_pos.x(),
                    text_pos.y() - text_height,
                    text_width,
                    text_height
                )
                if text_rect.contains(pos):
                    return i
        return None

    def _get_shape_at_pos(self, pos):
        """检测点击位置的图形，返回索引或 None（后绘制的优先）"""
        # 从后往前遍历（后绘制的在上层）
        for i in range(len(self.drawing_paths) - 1, -1, -1):
            shape_type, color, size, data = self.drawing_paths[i]
            if self._point_in_shape(pos, shape_type, data, size):
                return i
        return None

    def _point_in_shape(self, pos, shape_type, data, size):
        """判断点是否在图形内或边框附近"""
        tolerance = 8  # 检测容差（像素）

        if shape_type == 'text' and len(data) == 2:
            text_pos, text = data
            font_metrics = QFontMetrics(QFont("", size))
            text_width = font_metrics.horizontalAdvance(text)
            text_height = font_metrics.height()
            text_rect = QRect(
                text_pos.x() - tolerance,
                text_pos.y() - text_height - tolerance,
                text_width + tolerance * 2,
                text_height + tolerance * 2
            )
            return text_rect.contains(pos)

        elif shape_type == 'rect' and len(data) == 2:
            # 矩形：检测是否在矩形区域内（包含边框容差）
            rect = QRect(data[0], data[1]).normalized()
            expanded = rect.adjusted(-tolerance, -tolerance, tolerance, tolerance)
            return expanded.contains(pos)

        elif shape_type == 'circle' and len(data) == 2:
            # 椭圆：检测是否在椭圆区域内（包含边框容差）
            rect = QRect(data[0], data[1]).normalized()
            center_x = rect.center().x()
            center_y = rect.center().y()
            a = rect.width() / 2 + tolerance  # 半长轴 + 容差
            b = rect.height() / 2 + tolerance  # 半短轴 + 容差
            if a == 0 or b == 0:
                return False
            # 计算点到椭圆中心的归一化距离
            dx = pos.x() - center_x
            dy = pos.y() - center_y
            dist = (dx * dx) / (a * a) + (dy * dy) / (b * b)
            # dist <= 1.0 表示在椭圆内
            return dist <= 1.0

        elif shape_type in ['arrow', 'line'] and len(data) == 2:
            # 线段：检测点到线段的距离（线条较细，用更大的容差）
            return self._point_to_line_distance(pos, data[0], data[1]) < tolerance * 1.5

        elif shape_type == 'pen' and len(data) > 1:
            # 笔画：检测点到任意线段的距离（用更大的容差）
            for i in range(len(data) - 1):
                if self._point_to_line_distance(pos, data[i], data[i + 1]) < tolerance * 1.5:
                    return True
            return False

        return False

    def _point_to_line_distance(self, point, line_start, line_end):
        """计算点到线段的距离"""
        px, py = point.x(), point.y()
        x1, y1 = line_start.x(), line_start.y()
        x2, y2 = line_end.x(), line_end.y()

        # 线段长度的平方
        line_len_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
        if line_len_sq == 0:
            # 线段退化为点
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

        # 计算投影参数 t
        t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_len_sq))

        # 投影点
        proj_x = x1 + t * (x2 - x1)
        proj_y = y1 + t * (y2 - y1)

        # 返回距离
        return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)

    def _get_shape_bounds(self, index):
        """获取图形的边界矩形"""
        shape_type, color, size, data = self.drawing_paths[index]

        if shape_type == 'text' and len(data) == 2:
            text_pos, text = data
            font_metrics = QFontMetrics(QFont("", size))
            text_width = font_metrics.horizontalAdvance(text)
            text_height = font_metrics.height()
            return QRect(text_pos.x(), text_pos.y() - text_height, text_width, text_height)

        elif shape_type in ['rect', 'circle'] and len(data) == 2:
            return QRect(data[0], data[1]).normalized()

        elif shape_type in ['arrow', 'line'] and len(data) == 2:
            return QRect(data[0], data[1]).normalized()

        elif shape_type == 'pen' and len(data) > 0:
            min_x = min(p.x() for p in data)
            min_y = min(p.y() for p in data)
            max_x = max(p.x() for p in data)
            max_y = max(p.y() for p in data)
            return QRect(min_x, min_y, max_x - min_x, max_y - min_y)

        return QRect()

    def _move_shape(self, index, new_pos):
        """移动图形到新位置"""
        if self.drag_start_pos is None:
            return

        shape_type, color, size, data = self.drawing_paths[index]
        dx = new_pos.x() - self.drag_start_pos.x()
        dy = new_pos.y() - self.drag_start_pos.y()

        if shape_type == 'text' and len(data) == 2:
            data[0] = QPoint(data[0].x() + dx, data[0].y() + dy)
        elif shape_type in ['rect', 'circle', 'arrow', 'line'] and len(data) == 2:
            data[0] = QPoint(data[0].x() + dx, data[0].y() + dy)
            data[1] = QPoint(data[1].x() + dx, data[1].y() + dy)
        elif shape_type == 'pen' and len(data) > 0:
            data = [QPoint(p.x() + dx, p.y() + dy) for p in data]

        self.drawing_paths[index] = (shape_type, color, size, data)
        self.drag_start_pos = new_pos
        self.update()

    def _show_text_input(self, pos):
        """在指定位置开始文字输入（无输入框模式）"""
        # 如果正在输入，先提交
        if self.text_editing:
            self._commit_text_editing()

        self.text_editing = True
        self.text_editing_pos = pos
        self.text_editing_content = ""
        self.cursor_visible = True

        # 启动光标闪烁定时器
        if self.cursor_timer is None:
            self.cursor_timer = QTimer(self)
            self.cursor_timer.timeout.connect(self._toggle_cursor)
        self.cursor_timer.start(500)  # 500ms 闪烁

        self.update()

    def _toggle_cursor(self):
        """切换光标可见性"""
        if self.text_editing:
            self.cursor_visible = not self.cursor_visible
            self.update()

    def _commit_text_editing(self):
        """提交当前输入的文字"""
        if self.text_editing and self.text_editing_content:
            self.drawing_paths.append((
                'text',
                self.current_color,
                self.current_font_size,
                [self.text_editing_pos, self.text_editing_content]
            ))

        # 停止光标闪烁
        if self.cursor_timer:
            self.cursor_timer.stop()

        self.text_editing = False
        self.text_editing_pos = None
        self.text_editing_content = ""
        self.update()

    def _commit_text_input(self):
        """提交文字输入"""
        if self.text_input and self.text_input_pos:
            text = self.text_input.text().strip()
            if text:
                self.drawing_paths.append((
                    'text',
                    self.current_color,
                    self.current_font_size,
                    [self.text_input_pos, text]
                ))
            self.text_input.deleteLater()
            self.text_input = None
            self.text_input_pos = None
            self.update()

    def _close_text_input(self):
        """关闭文字输入框（不提交）"""
        if self.text_input:
            self.text_input.deleteLater()
            self.text_input = None
            self.text_input_pos = None

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

                # 首先检查参数面板内的选项
                if self.param_panel_open and self.param_panel_items:
                    for item_rect, item_type, item_value in self.param_panel_items:
                        if item_rect.contains(event.pos()):
                            if item_type == 'color':
                                self.current_color = item_value
                            elif item_type == 'width':
                                self.current_width = item_value
                            elif item_type == 'font_size':
                                self.current_font_size = item_value
                            self.update()
                            return

                # 定义需要参数面板的工具
                tools_with_params = ['rect', 'circle', 'pen', 'arrow', 'line', 'text']

                # 检查工具选择按钮
                old_tool = self.current_tool
                new_tool = None

                if hasattr(self, 'move_btn_rect') and self.move_btn_rect.contains(event.pos()):
                    new_tool = 'move'
                    clicked_button = True

                if hasattr(self, 'pen_btn_rect') and self.pen_btn_rect.contains(event.pos()):
                    new_tool = 'pen'
                    clicked_button = True

                if hasattr(self, 'rect_btn_rect') and self.rect_btn_rect.contains(event.pos()):
                    new_tool = 'rect'
                    clicked_button = True

                if hasattr(self, 'circle_btn_rect') and self.circle_btn_rect.contains(event.pos()):
                    new_tool = 'circle'
                    clicked_button = True

                if hasattr(self, 'arrow_btn_rect') and self.arrow_btn_rect.contains(event.pos()):
                    new_tool = 'arrow'
                    clicked_button = True

                if hasattr(self, 'line_btn_rect') and self.line_btn_rect.contains(event.pos()):
                    new_tool = 'line'
                    clicked_button = True

                if hasattr(self, 'eraser_btn_rect') and self.eraser_btn_rect.contains(event.pos()):
                    new_tool = 'eraser'
                    clicked_button = True

                if hasattr(self, 'text_btn_rect') and self.text_btn_rect.contains(event.pos()):
                    new_tool = 'text'
                    clicked_button = True

                # 处理工具切换和参数面板
                if new_tool is not None:
                    # 切换工具前，提交正在输入的文字
                    if self.text_editing:
                        self._commit_text_editing()

                    if new_tool == old_tool and new_tool in tools_with_params:
                        # 点击同一个有参数的工具，切换面板显示状态
                        self.param_panel_open = not self.param_panel_open
                    else:
                        # 切换到新工具
                        self.current_tool = new_tool
                        if new_tool in tools_with_params:
                            # 新工具有参数，打开面板
                            self.param_panel_open = True
                        else:
                            # 新工具没有参数，关闭面板
                            self.param_panel_open = False

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
                    # 点击画布区域，关闭参数面板
                    self.param_panel_open = False

                    # 任何工具下，先检测是否点击了已有图形（文字工具除外，因为需要特殊处理）
                    if self.current_tool != 'text':
                        shape_index = self._get_shape_at_pos(event.pos())
                        if shape_index is not None:
                            # 开始拖拽图形
                            self.dragging_shape_index = shape_index
                            self.drag_start_pos = event.pos()
                            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                            return

                    if self.current_tool == 'move':
                        # 移动模式：没有点击图形时，移动选择框
                        self.is_moving = True
                        self.move_start_pos = event.pos()
                        # 移动选择框后，清除单窗口截图标记
                        self.selected_window_id = None
                        self.selected_window_pixmap = None
                    elif self.current_tool == 'text':
                        # 文字模式
                        # 如果正在输入文字，先提交
                        if self.text_editing:
                            self._commit_text_editing()
                            # 如果点击的是同一位置附近，不再开启新输入
                            self.update()
                            return

                        # 检查是否点击了已有图形（包括文字）
                        shape_index = self._get_shape_at_pos(event.pos())
                        if shape_index is not None:
                            # 开始拖拽图形
                            self.dragging_shape_index = shape_index
                            self.drag_start_pos = event.pos()
                            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
                        else:
                            # 开始文字输入
                            self._show_text_input(event.pos())
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
        # 未开始选择时，检测悬停的窗口
        if not self.edit_mode and not self.is_selecting:
            window_rect, window_id = self._get_window_at_pos(event.pos())
            if window_rect != self.hovered_window_rect:
                self.hovered_window_rect = window_rect
                self.hovered_window_id = window_id
                self.update()

        # 编辑模式下，检测悬停在图形上（用于显示移动光标）- 任何工具下都可以
        if self.edit_mode and not self.is_drawing and not self.is_moving and self.dragging_shape_index is None:
            rect = self._get_selection_rect()
            if rect.contains(event.pos()):
                shape_index = self._get_shape_at_pos(event.pos())
                if shape_index != self.hovered_shape_index:
                    self.hovered_shape_index = shape_index
                    if shape_index is not None:
                        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                    else:
                        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                    self.update()

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
        elif self.dragging_shape_index is not None:
            # 拖拽图形
            self._move_shape(self.dragging_shape_index, event.pos())
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
                    # 拖拽选择了足够大的区域
                    self.edit_mode = True
                    self.hovered_window_rect = None  # 清除窗口高亮
                    self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                elif self.hovered_window_rect:
                    # 单击且有悬停窗口，选中整个窗口
                    self.start_pos = self.hovered_window_rect.topLeft()
                    self.end_pos = self.hovered_window_rect.bottomRight()
                    self.selected_window_id = self.hovered_window_id  # 保存窗口ID用于单窗口截图
                    # 立即截取窗口内容用于编辑时显示
                    self.selected_window_pixmap = self._capture_single_window(self.hovered_window_id)
                    self.edit_mode = True
                    self.hovered_window_rect = None  # 清除窗口高亮
                    self.hovered_window_id = None
                    self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                else:
                    self.close()
                self.update()
            elif self.is_moving:
                # 完成移动
                self.is_moving = False
                self.move_start_pos = None
                self.update()
            elif self.dragging_shape_index is not None:
                # 完成图形拖拽
                self.dragging_shape_index = None
                self.drag_start_pos = None
                self.hovered_shape_index = None
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
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
                elif self.current_tool in ['rect', 'circle', 'arrow', 'line'] and self.draw_start_pos and len(self.current_path) > 0:
                    # 矩形/圆形/箭头/直线：保存起点和终点
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
            elif shape_type == 'line' and len(data) == 2:
                # 检查直线是否与橡皮擦相交
                p1 = data[0]
                p2 = data[1]
                for eraser_point in eraser_path:
                    dist = point_to_segment_distance(
                        eraser_point.x(), eraser_point.y(),
                        p1.x(), p1.y(), p2.x(), p2.y()
                    )
                    if dist <= erase_radius:
                        return True
            elif shape_type == 'text' and len(data) == 2:
                # 检查文字位置是否与橡皮擦相交
                text_pos = data[0]
                for eraser_point in eraser_path:
                    dist = math.sqrt(
                        (eraser_point.x() - text_pos.x()) ** 2 +
                        (eraser_point.y() - text_pos.y()) ** 2
                    )
                    if dist <= erase_radius + 30:  # 文字区域判定范围稍大
                        return True
            return False

        # 过滤掉与橡皮擦相交的路径
        self.drawing_paths = [
            item for item in self.drawing_paths
            if not path_intersects_eraser(item[0], item[3])
        ]

    def keyPressEvent(self, event):
        """处理键盘事件"""
        # 如果正在输入文字
        if self.text_editing:
            key = event.key()

            if key == Qt.Key.Key_Escape:
                # ESC 取消输入
                if self.cursor_timer:
                    self.cursor_timer.stop()
                self.text_editing = False
                self.text_editing_content = ""
                self.update()
            elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                # 回车确认输入
                self._commit_text_editing()
            elif key == Qt.Key.Key_Backspace:
                # 退格删除
                if self.text_editing_content:
                    self.text_editing_content = self.text_editing_content[:-1]
                    self.update()
            else:
                # 普通字符输入
                text = event.text()
                if text and text.isprintable():
                    self.text_editing_content += text
                    self.update()
            return

        # 非文字输入模式，ESC 取消截图
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
                'line_btn_rect', 'eraser_btn_rect', 'text_btn_rect', 'undo_btn_rect'
            ]

            for btn_name in toolbar_buttons:
                if hasattr(self, btn_name):
                    btn_rect = getattr(self, btn_name)
                    if btn_rect.contains(event.pos()):
                        clicked_on_toolbar = True
                        break

            # 检查参数面板
            if not clicked_on_toolbar and self.param_panel_open:
                if self.param_panel_rect and self.param_panel_rect.contains(event.pos()):
                    clicked_on_toolbar = True

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

        # 如果是单窗口选择，使用已截取的窗口截图
        if self.selected_window_pixmap:
            cropped = self.selected_window_pixmap.copy()
        elif self.selected_window_id:
            # 备用：重新截取单窗口
            cropped = self._capture_single_window(self.selected_window_id)
            if cropped is None:
                # 单窗口截图失败，回退到屏幕截图
                src_rect = self._rect_to_screen_pixels(rect)
                cropped = self.background_pixmap.copy(src_rect)
        elif self.background_pixmap:
            # 从背景截图中裁剪选择区域（使用物理像素坐标）
            src_rect = self._rect_to_screen_pixels(rect)
            cropped = self.background_pixmap.copy(src_rect)
        else:
            return

        if cropped:

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
                    elif shape_type == 'line' and len(data) == 2:
                        # 直线：绘制直线
                        p1 = QPoint(
                            data[0].x() - rect.x(),
                            data[0].y() - rect.y()
                        )
                        p2 = QPoint(
                            data[1].x() - rect.x(),
                            data[1].y() - rect.y()
                        )
                        painter.drawLine(p1, p2)
                    elif shape_type == 'text' and len(data) == 2:
                        # 文字：绘制文字
                        pos = QPoint(
                            data[0].x() - rect.x(),
                            data[0].y() - rect.y()
                        )
                        text = data[1]
                        font = painter.font()
                        font.setPointSize(width)
                        font.setBold(True)
                        painter.setFont(font)
                        painter.setPen(color)
                        painter.drawText(pos, text)

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
