#!/usr/bin/env python3
"""
Smooth Scrolling Logic Module
Replica en Python del smooth_scrolling_backend.ahk
"""

import math
from collections import deque
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ScrollState:
    """Estado global del smooth scroll"""
    active: bool = False
    accumulator_x: float = 0.0
    accumulator_y: float = 0.0
    accumulator_wheel: float = 0.0
    remainder_x: float = 0.0
    remainder_y: float = 0.0
    
    # Posición del cursor cuando se congela
    cursor_x: int = 0
    cursor_y: int = 0
    window_under_mouse: str = ""
    control_under_mouse: str = ""
    
    # Snap state
    snap_state: int = 0  # 0=undecided, 1=X-snapped, 2=Y-snapped
    snap_deviation: float = 0.0


class SmoothingWindow:
    """Ventana móvil para suavizado de movimiento"""
    
    def __init__(self, max_size: int):
        self.max_size = max_size
        self.window_x: deque = deque(maxlen=max_size)
        self.window_y: deque = deque(maxlen=max_size)
    
    def push(self, x: float, y: float) -> None:
        """Agregar valor a la ventana"""
        self.window_x.append(x)
        self.window_y.append(y)
    
    def mean_x(self) -> float:
        """Promedio en X"""
        if not self.window_x:
            return 0.0
        return sum(self.window_x) / len(self.window_x)
    
    def mean_y(self) -> float:
        """Promedio en Y"""
        if not self.window_y:
            return 0.0
        return sum(self.window_y) / len(self.window_y)
    
    def reset(self) -> None:
        """Limpiar ventana"""
        self.window_x.clear()
        self.window_y.clear()


class SmoothScrollLogic:
    """Lógica principal de smooth scrolling"""
    
    def __init__(self, config: dict):
        self.config = config
        self.state = ScrollState()
        
        # Parámetros de texture
        self.sensitivity = float(config['Texture']['sensitivity'])
        self.refresh_interval = int(config['Texture']['refreshInterval']) / 1000.0  # Convert to seconds
        self.smoothing = SmoothingWindow(int(config['Texture']['smoothingWindowMaxSize']))
        
        # Parámetros de axis snapping
        self.snap_on = config['Axis Snapping']['snapOnByDefault'].lower() == 'true'
        self.snap_ratio = float(config['Axis Snapping']['snapRatio'])
        self.snap_threshold = float(config['Axis Snapping']['snapThreshold'])
        
        # Aceleración
        self.acceleration_on = config['Acceleration']['accelerationOn'].lower() == 'true'
        acceleration_blend = float(config['Acceleration']['accelerationBlend'])
        acceleration_scale = float(config['Acceleration']['accelerationScale']) * self.refresh_interval
        
        # Parámetros de aceleración (fórmula: v_out = p*sq(v_in-r) + q*(v_in-r) + r)
        self.accel_p = acceleration_blend / acceleration_scale
        self.accel_q = acceleration_blend + 1
        self.accel_r = acceleration_scale
        
        # Modifier emulation
        self.add_shift = config['Modifier Emulation']['addShift'].lower() == 'true'
        self.add_ctrl = config['Modifier Emulation']['addCtrl'].lower() == 'true'
        self.add_alt = config['Modifier Emulation']['addAlt'].lower() == 'true'
        
        logger.info("SmoothScrollLogic initialized with config")
    
    def is_active(self) -> bool:
        """Retorna si smooth scrolling está activo"""
        return self.state.active
    
    def activate(self, cursor_x: int, cursor_y: int) -> None:
        """Activar smooth scrolling y congelar cursor"""
        self.state.active = True
        self.state.accumulator_x = 0.0
        self.state.accumulator_y = 0.0
        self.state.accumulator_wheel = 0.0
        self.state.remainder_x = 0.0
        self.state.remainder_y = 0.0
        self.state.cursor_x = cursor_x
        self.state.cursor_y = cursor_y
        self.state.snap_state = 0
        self.state.snap_deviation = 0.0
        self.smoothing.reset()
        logger.info(f"Smooth scrolling activated at ({cursor_x}, {cursor_y})")
    
    def deactivate(self) -> None:
        """Desactivar smooth scrolling"""
        self.state.active = False
        logger.info("Smooth scrolling deactivated")
    
    def add_mouse_movement(self, delta_x: float, delta_y: float) -> None:
        """Agregar movimiento de mouse al acumulador"""
        if self.state.active:
            self.state.accumulator_x += delta_x
            self.state.accumulator_y += delta_y
    
    def add_wheel_input(self, delta: float) -> None:
        """Agregar input del wheel"""
        if self.state.active:
            self.state.accumulator_wheel += delta
    
    def process_scroll(self) -> tuple[int, int]:
        """
        Procesar un tick del smooth scroll
        Retorna (scroll_x, scroll_y) a enviar
        """
        # Aplicar smoothing window
        self.smoothing.push(self.state.accumulator_x, self.state.accumulator_y)
        smoothed_x = self.smoothing.mean_x()
        smoothed_y = -self.smoothing.mean_y()  # Invertir Y
        
        # Reset acumuladores
        self.state.accumulator_x = 0.0
        self.state.accumulator_y = 0.0
        
        # Aplicar axis snapping
        if self.snap_on:
            smoothed_x, smoothed_y = self._apply_axis_snapping(smoothed_x, smoothed_y)
        
        # Aplicar aceleración
        if self.acceleration_on and (smoothed_x != 0 or smoothed_y != 0):
            smoothed_x, smoothed_y = self._apply_acceleration(smoothed_x, smoothed_y)
        
        # Aplicar sensibilidad
        smoothed_x *= self.sensitivity
        smoothed_y *= self.sensitivity
        
        # Aplicar rounding errors previos y guardar nuevos
        smoothed_x += self.state.remainder_x
        smoothed_y += self.state.remainder_y
        
        rounded_x = round(smoothed_x)
        rounded_y = round(smoothed_y)
        
        self.state.remainder_x = smoothed_x - rounded_x
        self.state.remainder_y = smoothed_y - rounded_y
        
        return (int(rounded_x), int(rounded_y))
    
    def _apply_axis_snapping(self, x: float, y: float) -> tuple[float, float]:
        """Aplicar axis snapping"""
        if self.state.snap_state == 0:  # Undecided
            if abs(x) > abs(y):
                self.state.snap_state = 1
                return (x, 0.0)
            elif abs(x) < abs(y):
                self.state.snap_state = 2
                return (0.0, y)
            else:
                return (x, y)
        
        elif self.state.snap_state == 1:  # X-snapped
            self.state.snap_deviation += y
            if self.state.snap_deviation > 0:
                self.state.snap_deviation = max(0, self.state.snap_deviation - abs(x) * self.snap_ratio)
            elif self.state.snap_deviation < 0:
                self.state.snap_deviation = min(0, self.state.snap_deviation + abs(x) * self.snap_ratio)
            
            if abs(self.state.snap_deviation) > self.snap_threshold:
                # Switch to Y-snap
                self.state.snap_state = 2
                self.state.snap_deviation = 0.0
                self.smoothing.reset()
                return (0.0, y)
            else:
                return (x, 0.0)
        
        elif self.state.snap_state == 2:  # Y-snapped
            self.state.snap_deviation += x
            if self.state.snap_deviation > 0:
                self.state.snap_deviation = max(0, self.state.snap_deviation - abs(y) * self.snap_ratio)
            elif self.state.snap_deviation < 0:
                self.state.snap_deviation = min(0, self.state.snap_deviation + abs(y) * self.snap_ratio)
            
            if abs(self.state.snap_deviation) > self.snap_threshold:
                # Switch to X-snap
                self.state.snap_state = 1
                self.state.snap_deviation = 0.0
                self.smoothing.reset()
                return (x, 0.0)
            else:
                return (0.0, y)
        
        return (x, y)
    
    def _apply_acceleration(self, x: float, y: float) -> tuple[float, float]:
        """Aplicar curva de aceleración"""
        speed = math.sqrt(x * x + y * y)
        if speed == 0:
            return (x, y)
        
        speed_offset = speed - self.accel_r
        scale_factor = self.accel_q * speed_offset + self.accel_r
        
        if speed_offset < 0:
            scale_factor += self.accel_p * speed_offset * speed_offset
        
        scale_factor /= speed
        
        return (x * scale_factor, y * scale_factor)
    
    def get_wheel_delta(self) -> float:
        """Obtener y resetear wheel accumulator"""
        delta = self.state.accumulator_wheel
        self.state.accumulator_wheel = 0.0
        return delta
