#!/usr/bin/env python3
"""
Smooth Scrolling Daemon for Linux/Wayland - FIXED CURSOR FREEZE
Replica del smooth_scrolling_app.ahk en Python con evdev/uinput
"""

import sys
import os
import time
import signal
import logging
import configparser
from pathlib import Path
from typing import Optional, Dict
from threading import Thread, Event

# Importar evdev para lectura de input y envío de eventos
try:
    from evdev import InputDevice, UInput, ecodes, list_devices
except ImportError:
    print("ERROR: python3-evdev no está instalado")
    print("Instala con: sudo apt install python3-evdev")
    sys.exit(1)

# Importar nuestro módulo de lógica
from scroll_logic import SmoothScrollLogic

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/tmp/smooth_scroll.log')
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

CONFIG_PATH = Path('/etc/smooth_scroll/config.ini')
if not CONFIG_PATH.exists():
    CONFIG_PATH = Path('config.ini')

if not CONFIG_PATH.exists():
    logger.error(f"Config file not found: {CONFIG_PATH}")
    sys.exit(1)

config = configparser.ConfigParser()
config.read(CONFIG_PATH)

# Leer configuración
HOTKEY1 = config['Hotkeys']['hotkey1']
HOTKEY2 = config['Hotkeys'].get('hotkey2', '')
PANIC_BUTTON = config['Hotkeys'].get('panicButton', '')
MODE = config['Hotkeys']['mode']
HOLD_DURATION = int(config['Hotkeys']['holdDuration']) / 1000.0  # Convert to seconds

logger.info(f"Loaded config: MODE={MODE}, HOTKEY1={HOTKEY1}, HOTKEY2={HOTKEY2}")

# ============================================================================
# HOTKEY MAPPING
# ============================================================================

KEY_NAME_TO_CODE = {
    'F1': ecodes.KEY_F1, 'F2': ecodes.KEY_F2, 'F3': ecodes.KEY_F3,
    'F4': ecodes.KEY_F4, 'F5': ecodes.KEY_F5, 'F6': ecodes.KEY_F6,
    'F7': ecodes.KEY_F7, 'F8': ecodes.KEY_F8, 'F9': ecodes.KEY_F9,
    'F10': ecodes.KEY_F10, 'F11': ecodes.KEY_F11, 'F12': ecodes.KEY_F12,
    'm': ecodes.KEY_M, 'n': ecodes.KEY_N, 'p': ecodes.KEY_P,
    'space': ecodes.KEY_SPACE, 'esc': ecodes.KEY_ESC, 'enter': ecodes.KEY_ENTER,
}

MOUSE_BUTTON_CODES = {
    'LButton': ecodes.BTN_LEFT,
    'RButton': ecodes.BTN_RIGHT,
    'MButton': ecodes.BTN_MIDDLE,
}


# ============================================================================
# DEVICE DETECTION
# ============================================================================

def find_mouse_device() -> Optional[InputDevice]:
    """Encuentra el dispositivo de mouse"""
    devices = [InputDevice(path) for path in list_devices()]
    
    for device in devices:
        # Buscar mouse por nombre
        if 'logitech ergo m575' in device.name.lower() or 'trackpad' in device.name.lower():
            # Verificar que tenga soporte para movimiento relativo
            if ecodes.EV_REL in device.capabilities():
                if ecodes.REL_X in device.capabilities()[ecodes.EV_REL]:
                    logger.info(f"Found mouse: {device.path} ({device.name})")
                    return device
    
    logger.error("No mouse device found!")
    return None


def find_keyboard_device() -> Optional[InputDevice]:
    """Encuentra el dispositivo de teclado para detectar hotkeys"""
    devices = [InputDevice(path) for path in list_devices()]
    
    for device in devices:
        if 'keyboard' in device.name.lower():
            if ecodes.EV_KEY in device.capabilities():
                logger.info(f"Found keyboard: {device.path} ({device.name})")
                return device
    
    # Fallback: devolver cualquier dispositivo con keys
    for device in devices:
        if ecodes.EV_KEY in device.capabilities():
            logger.info(f"Using device for keys: {device.path} ({device.name})")
            return device
    
    logger.error("No keyboard device found!")
    return None


# ============================================================================
# UINPUT SETUP - COPIA CAPACIDADES COMPLETAS DEL MOUSE
# ============================================================================

def create_uinput_device(mouse_caps: dict) -> UInput:
    """Crea dispositivo virtual uinput - VERSIÓN ROBUSTA"""
    try:
        # CAPACIDADES BÁSICAS + ESENCIALES (funciona con cualquier mouse)
        capabilities = {
            ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE],
            ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL, ecodes.REL_HWHEEL],
            ecodes.EV_SYN: [],
        }
        
        # Agregar capacidades ADICIONALES del mouse SOLO si son válidas
        rel_caps = mouse_caps.get(ecodes.EV_REL, [])
        key_caps = mouse_caps.get(ecodes.EV_KEY, [])
        
        # Agregar REL_ capacidades comunes
        for code in rel_caps:
            if code not in capabilities[ecodes.EV_REL]:
                capabilities[ecodes.EV_REL].append(code)
        
        # Agregar KEY/BTN capacidades comunes (hasta 20 para no saturar)
        for code in key_caps[:20]:
            if code not in capabilities[ecodes.EV_KEY]:
                capabilities[ecodes.EV_KEY].append(code)
        
        device = UInput(capabilities, name='smooth-scroll-mouse', version=0x0101)
        logger.info(f"Created uinput with {len(capabilities[ecodes.EV_REL])} REL + {len(capabilities[ecodes.EV_KEY])} KEY capabilities")
        return device
    except Exception as e:
        logger.error(f"Failed to create uinput device: {e}")
        sys.exit(1)



def send_scroll(uinput_device: UInput, scroll_x: int, scroll_y: int) -> None:
    """Envía eventos de scroll al dispositivo uinput"""
    if scroll_x != 0:
        uinput_device.write(ecodes.EV_REL, ecodes.REL_HWHEEL, scroll_x)
    if scroll_y != 0:
        uinput_device.write(ecodes.EV_REL, ecodes.REL_WHEEL, scroll_y)
    uinput_device.syn()


def replay_event(uinput_device: UInput, event) -> None:
    """Reproduce un evento del mouse original exactamente igual"""
    uinput_device.write(event.type, event.code, event.value)
    uinput_device.syn()


# ============================================================================
# SMOOTH SCROLL DAEMON - FIXED CURSOR FREEZE
# ============================================================================

class SmoothScrollDaemon:
    """Daemon principal del smooth scrolling - CON FREEZE DEL CURSOR"""
    
    def __init__(self):
            
        self.mouse_device = find_mouse_device()
        self.keyboard_device = find_keyboard_device()
        
        if not self.mouse_device:
            sys.exit(1)
            
        # CREAR uinput COPIANDO CAPACIDADES COMPLETAS del mouse
        self.uinput_device = create_uinput_device(self.mouse_device.capabilities())
        self.logic = SmoothScrollLogic(config)
        
        self.stop_event = Event()
        self.running = False
        
        # Estado de hotkeys
        self.hotkey1_pressed = False
        self.hotkey2_pressed = False

        self.button_press_time = 0
        self.is_holding = False
        
        # GRAB el mouse para bloquear eventos originales
        try:
            self.mouse_device.grab()
            logger.info("*** MOUSE GRABBED - Cursor freeze ready ***")
        except Exception as e:
            logger.error(f"Failed to grab mouse: {e}")
            sys.exit(1)
    
    def signal_handler(self, signum, frame):
        """Manejador para Ctrl+C - RELEASE grab"""
        logger.info("Received signal, shutting down...")
        try:
            self.mouse_device.ungrab()
        except:
            pass
        self.stop()
    
    def start(self) -> None:
        """Iniciar el daemon"""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        logger.info("*** Starting Smooth Scroll Daemon WITH CURSOR FREEZE ***")
        self.running = True
        
        # Thread para leer mouse events (CRUCIAL: GRABBED + REPLAY)
        mouse_supervisor = Thread(
            target=self._mouse_supervisor_thread,
            daemon=True
        )
        mouse_supervisor.start()
        
        # Thread para leer keyboard events
        keyboard_thread = Thread(target=self._keyboard_reader_thread, daemon=True)
        keyboard_thread.start()
        
        # Thread principal para procesar scroll
        self._process_scroll_thread()
    
    def stop(self) -> None:
        """Detener el daemon"""
        try:
            self.mouse_device.ungrab()
        except:
            pass
        self.running = False
        self.stop_event.set()
        self.uinput_device.close()
        logger.info("Smooth Scroll Daemon stopped")

    def _mouse_reader_loop(self) -> None:
            target_hotkey_code = MOUSE_BUTTON_CODES.get(HOTKEY1) or KEY_NAME_TO_CODE.get(HOTKEY1)
            logger.info(f"Mouse reader activo (Tap vs Hold + Instant Drag) en código: {target_hotkey_code}")
            
            try:
                for event in self.mouse_device.read_loop():
                    if not self.running:
                        return
                    
                    # 1. --- LÓGICA DE BOTONES (EV_KEY) ---
                    if event.type == ecodes.EV_KEY and event.code == target_hotkey_code:
                        if event.value == 1:  # Al presionar (Press)
                            self.button_press_time = time.time()
                            self.is_holding = True
                        elif event.value == 0:  # Al soltar (Release)
                            duration = time.time() - self.button_press_time
                            self.is_holding = False
                            
                            if self.logic.is_active():
                                self.logic.deactivate()
                                logger.info("🔴 Scroll desactivado")
                            elif duration < HOLD_DURATION:
                                logger.info(f"🖱️ Tap detectado ({duration:.2f}s) - Enviando clic original")
                                self.uinput_device.write(ecodes.EV_KEY, target_hotkey_code, 1)
                                self.uinput_device.syn()
                                self.uinput_device.write(ecodes.EV_KEY, target_hotkey_code, 0)
                                self.uinput_device.syn()
                        continue

                    # 2. --- LÓGICA DE MOVIMIENTO / CONGELAMIENTO (MODIFICADA) ---
                    if event.type == ecodes.EV_REL:
                        # NUEVO: Si estoy sosteniendo la hotkey y muevo el mouse, activo el scroll YA
                        if self.is_holding and not self.logic.is_active():
                            self.logic.activate(0, 0)
                            logger.info("⚡ Drag detectado - Activación instantánea de scroll")

                        # Si el scroll ya está activo, procesamos el movimiento y NO dejamos que pase al sistema
                        if self.logic.is_active():
                            if event.code == ecodes.REL_X:
                                self.logic.add_mouse_movement(event.value, 0)
                            elif event.code == ecodes.REL_Y:
                                self.logic.add_mouse_movement(0, event.value)
                            continue # Congela el cursor

                    # 3. --- LÓGICA DE ACTIVACIÓN POR TIEMPO (STILL HERE) ---
                    # Esto sirve por si dejas el dedo quieto: a los 200ms el cursor se congela solo
                    if self.is_holding and not self.logic.is_active():
                        if (time.time() - self.button_press_time) > HOLD_DURATION:
                            self.logic.activate(0, 0)
                            logger.info("🟢 Hold detectado - Activando FREEZE por tiempo")

                    # 4. --- REPRODUCCIÓN NORMAL ---
                    replay_event(self.uinput_device, event)

            except Exception as e:
                logger.error(f"Error crítico en mouse_reader_thread: {e}", exc_info=True)
            finally:
                self.is_holding = False
                logger.info("Hilo mouse_reader finalizado.")

    def _keyboard_reader_thread(self) -> None:
        """Lee eventos del teclado para detectar hotkeys"""
        if not self.keyboard_device:
            return
        
        try:
            for event in self.keyboard_device.read_loop():
                if not self.running:
                    break
                
                if event.type != ecodes.EV_KEY:
                    continue
                
                # Detectar hotkeys
                self._handle_key_event(event.code, event.value)
        
        except Exception as e:
            logger.error(f"Error in keyboard reader thread: {e}")
    
    def _handle_key_event(self, key_code: int, key_value: int) -> None:
        """Maneja eventos de tecla para hotkeys"""
        is_press = key_value == 1
        is_release = key_value == 0
        
        # Comparar con hotkeys configurados
        hotkey1_code = KEY_NAME_TO_CODE.get(HOTKEY1)
        hotkey2_code = KEY_NAME_TO_CODE.get(HOTKEY2) if HOTKEY2 else None
        panic_code = KEY_NAME_TO_CODE.get(PANIC_BUTTON) if PANIC_BUTTON else None
        
        # Panic button
        if panic_code and key_code == panic_code and is_press:
            logger.warning("Panic button pressed, exiting...")
            self.stop()
            sys.exit(0)
        
        # Procesar según el modo
        if MODE == 'ONE_KEY_TOGGLE':
            self._handle_one_key_toggle(key_code, hotkey1_code, is_press)
        elif MODE == 'ONE_KEY_MOMENTARY':
            self._handle_one_key_momentary(key_code, hotkey1_code, is_press, is_release)
        elif MODE == 'ON_OFF':
            self._handle_on_off(key_code, hotkey1_code, hotkey2_code, is_press)
    
    def _handle_one_key_toggle(self, key_code: int, hotkey1_code: int, is_press: bool) -> None:
        """Modo ONE_KEY_TOGGLE: presionar alterna el estado"""
        if key_code == hotkey1_code and is_press and not self.hotkey1_pressed:
            self.hotkey1_pressed = True
            
            if self.logic.is_active():
                self.logic.deactivate()
                logger.info("🔴 Toggle OFF - Cursor libre")
            else:
                self.logic.activate(0, 0)  # Posición no usada en evdev
                logger.info("🟢 Toggle ON - Cursor FREEZED")
        
        elif key_code == hotkey1_code and not is_press:
            self.hotkey1_pressed = False
    
    def _handle_one_key_momentary(self, key_code: int, hotkey1_code: int, 
                                  is_press: bool, is_release: bool) -> None:
        """Modo ONE_KEY_MOMENTARY: mantener presionado activa"""
        if key_code == hotkey1_code:
            if is_press and not self.hotkey1_pressed:
                self.hotkey1_pressed = True
                self.logic.activate(0, 0)
                logger.info("🟢 Momentary ON - Cursor FREEZED")
            elif is_release and self.hotkey1_pressed:
                self.hotkey1_pressed = False
                self.logic.deactivate()
                logger.info("🔴 Momentary OFF - Cursor libre")
    
    def _handle_on_off(self, key_code: int, hotkey1_code: int, hotkey2_code: Optional[int], 
                       is_press: bool) -> None:
        """Modo ON_OFF: hotkey1 activa, hotkey2 desactiva"""
        if key_code == hotkey1_code and is_press and not self.hotkey1_pressed:
            self.hotkey1_pressed = True
            self.logic.activate(0, 0)
            logger.info("🟢 ON_OFF: Activated - Cursor FREEZED")
        elif key_code == hotkey1_code and not is_press:
            self.hotkey1_pressed = False
        
        if hotkey2_code and key_code == hotkey2_code and is_press and not self.hotkey2_pressed:
            self.hotkey2_pressed = True
            self.logic.deactivate()
            logger.info("🔴 ON_OFF: Deactivated - Cursor libre")
        elif hotkey2_code and key_code == hotkey2_code and not is_press:
            self.hotkey2_pressed = False
    
    def _process_scroll_thread(self) -> None:
        """Thread principal que procesa smooth scroll a intervalos regulares"""
        refresh_interval = float(config['Texture']['refreshInterval']) / 1000.0
        
        logger.info(f"Scroll processing thread started (interval: {refresh_interval}s)")
        
        while self.running:
            try:
                if self.logic.is_active():
                    # Procesar scroll
                    scroll_x, scroll_y = self.logic.process_scroll()
                    
                    # Enviar scroll (SOLO scroll, NO cursor movement)
                    if scroll_x != 0 or scroll_y != 0:
                        send_scroll(self.uinput_device, scroll_x, scroll_y)
                    
                    # Procesar wheel accumulator
                    wheel_delta = self.logic.get_wheel_delta()
                    if wheel_delta != 0:
                        send_scroll(self.uinput_device, 0, int(wheel_delta))
                
                time.sleep(refresh_interval)
            
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Error in scroll processing: {e}", exc_info=True)
                time.sleep(refresh_interval)

    def _handle_mouse_hotkey(self, button_code: int, button_value: int) -> None:
        """Procesa hotkeys del mouse según config.ini"""
        is_press = button_value == 1
        is_release = button_value == 0
        
        # Mapear botones del mouse a nombres de config
        button_map = {
            ecodes.BTN_RIGHT: 'RButton',
            ecodes.BTN_LEFT: 'LButton', 
            ecodes.BTN_MIDDLE: 'MButton',
        }
        
        button_name = button_map.get(button_code)
        if not button_name:
            return  # No es hotkey
        
        hotkey1 = config['Hotkeys']['hotkey1']
        
        # ONE_KEY_MOMENTARY: Activa al presionar, desactiva al soltar
        if MODE == 'ONE_KEY_MOMENTARY' and button_name == hotkey1:
            if is_press:
                self.logic.activate(0, 0)
                logger.info(f"🟢 {button_name}: Momentary ON - FREEZED")
            elif is_release:
                self.logic.deactivate()
                logger.info(f"🔴 {button_name}: Momentary OFF")

        # Dentro de _handle_mouse_hotkey para el modo TOGGLE
        elif MODE == 'ONE_KEY_TOGGLE' and button_name == hotkey1:
            if is_press and not self.hotkey1_pressed: # Añadimos la bandera
                self.hotkey1_pressed = True
                if self.logic.is_active():
                    self.logic.deactivate()
                    logger.info(f"🔴 {button_name}: Toggle OFF")
                else:
                    self.logic.activate(0, 0)
                    logger.info(f"🟢 {button_name}: Toggle ON - FREEZED")
            elif is_release:
                self.hotkey1_pressed = False # Resetear la bandera al soltar



    def _mouse_supervisor_thread(self):
        """Supervisa el mouse y lo reancla si se desconecta"""
        while self.running:
            try:
                logger.info("🔍 Buscando mouse...")
                self.mouse_device = find_mouse_device()

                if not self.mouse_device:
                    time.sleep(1)
                    continue

                logger.info(f"🖱️ Mouse conectado: {self.mouse_device.name}")

                # Crear uinput NUEVO
                self.uinput_device = create_uinput_device(
                    self.mouse_device.capabilities()
                )

                # Grab
                self.mouse_device.grab()
                logger.info("🔒 Mouse grabbeado")

                # Lanzar lector (bloqueante)
                self._mouse_reader_loop()

            except Exception as e:
                logger.error(f"💥 Mouse loop crashed: {e}", exc_info=True)

            finally:
                # LIMPIEZA OBLIGATORIA
                self.logic.deactivate()
                self.is_holding = False

                try:
                    self.mouse_device.ungrab()
                except:
                    pass

                try:
                    self.uinput_device.close()
                except:
                    pass

                self.mouse_device = None
                self.uinput_device = None

                logger.info("♻️ Esperando reconexión del mouse...")
                time.sleep(1)




# ============================================================================
# MAIN
# ============================================================================

def main():
    """Función principal"""
    # Verificar que se ejecuta con sudo
    if os.geteuid() != 0:
        logger.error("This script must be run with sudo (requires access to /dev/input/*)")
        print("ERROR: Ejecuta con sudo")
        sys.exit(1)
    
    # Crear y ejecutar daemon
    daemon = SmoothScrollDaemon()
    daemon.start()


if __name__ == '__main__':
    main()
