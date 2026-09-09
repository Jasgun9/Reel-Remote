#!/usr/bin/env python3
"""
Reel Remote - Windows controller.

Sends NEXT / PREVIOUS / PLAY_PAUSE to the Reel Remote Android app over the local
network. It never touches Instagram, never logs in anywhere, and only ever speaks
to the single IP address you type in.

Protocol (must match the Android app exactly):
    GET  http://<phone-ip>:<port>/ping
         header X-Auth-Token: <token>
         -> 200 {"ok":true,"app":"reelremote","protocol":1,"accessibility":true,...}

    POST http://<phone-ip>:<port>/command
         header Content-Type: application/json
         body   {"token":"<token>","command":"NEXT"|"PREVIOUS"|"PLAY_PAUSE"}
         -> 200 {"ok":true,"command":"NEXT"}
         -> 4xx {"ok":false,"error":"...","message":"..."}

Keyboard, while this window is focused:
    Up     -> NEXT
    Down   -> PREVIOUS
    Space  -> PLAY_PAUSE
    Esc    -> disconnect

Keyboard, system-wide (the "Global hotkeys" tickbox, ON by default):
    Ctrl+Alt+Up     -> NEXT
    Ctrl+Alt+Down   -> PREVIOUS
    Ctrl+Alt+Space  -> PLAY_PAUSE
    Ctrl+Alt+Q      -> disconnect

Mouse, system-wide (the "Mouse wheel" tickbox, ON by default):
    Alt+Shift+wheel down   -> NEXT
    Alt+Shift+wheel up     -> PREVIOUS
    Alt+Shift+middle click -> PLAY_PAUSE

Or just click the three buttons. "Always on top" pins the main window; "Mini
remote" pops out a small always-on-top pad with only the buttons on it.

The global combos use modifiers on purpose, so they need no key suppression and
therefore never steal a keystroke from whatever app you are really using. The
wheel is only intercepted while its modifiers are held, so ordinary scrolling is
untouched. Everything is rebindable: Hotkeys dropdown -> Custom... -> Edit...
"""

from __future__ import annotations

import ctypes
import ipaddress
import json
import os
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from tkinter import ttk

try:
    import requests
except ImportError:  # pragma: no cover - dependency check
    print("Missing dependency. Run:  pip install -r requirements.txt")
    sys.exit(1)

# `keyboard` is optional: without it the controller still works, but only while
# its window has focus.
try:
    import keyboard as kb

    HAVE_KEYBOARD = True
except Exception:  # ImportError, or an OS that refuses the low-level hook
    kb = None
    HAVE_KEYBOARD = False


APP_TITLE = "Reel Remote Controller"
PROTOCOL_VERSION = 1
DEFAULT_PORT = 8787

# Anti-flood: the phone rejects anything faster than ~150 ms, so stay above that.
# This also swallows the OS key-repeat storm when a key is held down.
MIN_COMMAND_INTERVAL = 0.20

REQUEST_TIMEOUT = 1.5
HEARTBEAT_SECONDS = 3.0
HEARTBEAT_FAILURES_BEFORE_DROP = 2
SCAN_TIMEOUT = 0.4
SCAN_WORKERS = 64

CONFIG_DIR = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), "ReelRemote"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "controller.json")

# PyInstaller unpacks bundled data to _MEIPASS; running from source it is just
# the directory this file lives in.
ASSET_DIR = os.path.join(
    getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "assets"
)

# Global hotkey presets.
#
# Modifier combos are the default because they need no key suppression: nobody
# types Ctrl+Alt+Space by accident, so the hooks can stay armed without stealing
# keys from whatever app you are actually using.
#
# "Plain keys" is the old behaviour, kept for pure watching sessions. A bare key
# MUST be suppressed - otherwise every space you type would also pause the Reel -
# and that suppression is exactly why it hijacks the arrows system-wide. That
# rule is derived, not configured: see needs_suppression() below.
HOTKEY_PRESETS = {
    "Ctrl+Alt": {
        "NEXT": "ctrl+alt+up",
        "PREVIOUS": "ctrl+alt+down",
        "PLAY_PAUSE": "ctrl+alt+space",
        "DISCONNECT": "ctrl+alt+q",
    },
    "Ctrl+Shift": {
        "NEXT": "ctrl+shift+up",
        "PREVIOUS": "ctrl+shift+down",
        "PLAY_PAUSE": "ctrl+shift+space",
        "DISCONNECT": "ctrl+shift+q",
    },
    "Win+Alt": {
        "NEXT": "windows+alt+up",
        "PREVIOUS": "windows+alt+down",
        "PLAY_PAUSE": "windows+alt+space",
        "DISCONNECT": "windows+alt+q",
    },
    "Plain keys (steals Up/Down/Space)": {
        "NEXT": "up",
        "PREVIOUS": "down",
        "PLAY_PAUSE": "space",
        "DISCONNECT": "esc",
    },
}

DEFAULT_PRESET = "Ctrl+Alt"
CUSTOM_PRESET = "Custom..."
COMMAND_ORDER = ("NEXT", "PREVIOUS", "PLAY_PAUSE")
BINDABLE = COMMAND_ORDER + ("DISCONNECT",)

DEFAULT_CUSTOM = dict(HOTKEY_PRESETS[DEFAULT_PRESET])

# Mouse wheel. Holding these modifiers turns the wheel into Reel navigation;
# without them the wheel behaves completely normally.
DEFAULT_WHEEL_MODIFIERS = "alt+shift"
WHEEL_MODIFIER_NAMES = ("ctrl", "alt", "shift", "windows")


def needs_suppression(combo: str) -> bool:
    """
    A bare key has to be swallowed or it would still reach the focused app.
    A modifier combo does not, because nothing else uses it.
    """
    return "+" not in combo


# --------------------------------------------------------------------------- #
# Networking
# --------------------------------------------------------------------------- #


class PhoneClient:
    """Thin HTTP client for one phone. All calls are blocking; run off the UI thread."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.host = ""
        self.port = DEFAULT_PORT
        self.token = ""

    def configure(self, host: str, port: int, token: str) -> None:
        self.host = host
        self.port = port
        self.token = token

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def ping(self, host: str | None = None, port: int | None = None,
             timeout: float = REQUEST_TIMEOUT) -> dict:
        host = host or self.host
        port = port or self.port
        response = self.session.get(
            f"http://{host}:{port}/ping",
            headers={"X-Auth-Token": self.token},
            timeout=timeout,
        )
        return self._decode(response)

    def send(self, command: str) -> dict:
        response = self.session.post(
            f"{self.base_url}/command",
            json={"token": self.token, "command": command},
            timeout=REQUEST_TIMEOUT,
        )
        return self._decode(response)

    @staticmethod
    def _decode(response: "requests.Response") -> dict:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("ok", response.status_code == 200)
        payload["_status"] = response.status_code
        return payload


def local_ipv4() -> str | None:
    """This machine's LAN address. The UDP socket is never actually sent to."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None
    finally:
        probe.close()


def scan_subnet(port: int, token: str, on_progress=None) -> str | None:
    """Probe every host on our /24 for a Reel Remote that accepts this token."""
    base = local_ipv4()
    if not base:
        return None
    try:
        network = ipaddress.ip_network(f"{base}/24", strict=False)
    except ValueError:
        return None

    found: list[str] = []
    headers = {"X-Auth-Token": token}

    def probe(host: str) -> None:
        if found:
            return
        try:
            response = requests.get(
                f"http://{host}:{port}/ping", headers=headers, timeout=SCAN_TIMEOUT
            )
            if response.status_code == 200 and response.json().get("app") == "reelremote":
                found.append(host)
        except Exception:
            pass

    hosts = [str(h) for h in network.hosts() if str(h) != base]
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        for index, _ in enumerate(pool.map(probe, hosts), start=1):
            if on_progress and index % 32 == 0:
                on_progress(index, len(hosts))
            if found:
                break
    return found[0] if found else None


# --------------------------------------------------------------------------- #
# Mouse wheel hook (Windows only)
# --------------------------------------------------------------------------- #

IS_WINDOWS = sys.platform == "win32"

WH_MOUSE_LL = 14
HC_ACTION = 0
WM_QUIT = 0x0012
WM_MOUSEWHEEL = 0x020A
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208

_VK = {"ctrl": (0x11,), "alt": (0x12,), "shift": (0x10,), "windows": (0x5B, 0x5C)}

if IS_WINDOWS:
    _LRESULT = ctypes.c_ssize_t
    _HOOKPROC = ctypes.WINFUNCTYPE(
        _LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    )

    class _MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", wintypes.POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # Explicit signatures matter on 64-bit: without them ctypes truncates
    # handles and LPARAM pointers to 32 bits and the hook silently misbehaves.
    _user32.SetWindowsHookExW.argtypes = (
        ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    _user32.CallNextHookEx.argtypes = (
        wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    _user32.CallNextHookEx.restype = _LRESULT
    _user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _user32.GetMessageW.argtypes = (
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint)
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.PostThreadMessageW.argtypes = (
        wintypes.DWORD, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
    _user32.PostThreadMessageW.restype = wintypes.BOOL
    _user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def parse_modifiers(text: str) -> list[str]:
    """'alt+shift' -> ['alt', 'shift']. Unknown names are dropped."""
    out = []
    for part in str(text).lower().replace(" ", "").split("+"):
        part = {"win": "windows", "control": "ctrl"}.get(part, part)
        if part in WHEEL_MODIFIER_NAMES and part not in out:
            out.append(part)
    return out


class MouseWheelHook:
    """
    Low-level mouse hook that turns <modifiers>+wheel into commands.

    A raw WH_MOUSE_LL hook is used rather than a third-party mouse library
    because only a real hook can *suppress* the event. Without suppression the
    page under the cursor would scroll at the same time as the Reel advances.

    The hook is only consulted while the exact modifier set is held, so ordinary
    scrolling and ordinary middle-clicks are never touched.
    """

    def __init__(self, on_wheel, on_middle_click) -> None:
        self._on_wheel = on_wheel
        self._on_middle_click = on_middle_click
        self._modifiers: list[str] = []
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._hook = None
        self._proc = None  # must stay referenced or the callback is garbage-collected
        self._ready = threading.Event()
        self._error: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, modifiers: list[str]) -> str | None:
        """Returns None on success, or an error message."""
        if not IS_WINDOWS:
            return "Mouse wheel control is Windows-only."
        if not modifiers:
            return "Set at least one modifier for the wheel."
        if self.running:
            self.stop()
        self._modifiers = list(modifiers)
        self._error = None
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)
        return self._error

    def stop(self) -> None:
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = 0

    # -- hook thread -------------------------------------------------------- #

    def _held(self) -> bool:
        """True only when exactly the configured modifier set is down."""
        for name, vks in _VK.items():
            down = any(_user32.GetAsyncKeyState(vk) & 0x8000 for vk in vks)
            if (name in self._modifiers) != bool(down):
                return False
        return True

    def _callback(self, n_code, w_param, l_param):
        # Low-level hooks have a ~300 ms budget; do the cheapest possible work
        # here and hand off to the sender thread.
        if n_code == HC_ACTION:
            try:
                if w_param == WM_MOUSEWHEEL and self._held():
                    info = ctypes.cast(
                        l_param, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                    delta = ctypes.c_short((info.mouseData >> 16) & 0xFFFF).value
                    if delta:
                        self._on_wheel(delta)
                        return 1  # swallow it: the page must not scroll too
                elif w_param in (WM_MBUTTONDOWN, WM_MBUTTONUP) and self._held():
                    if w_param == WM_MBUTTONDOWN:
                        self._on_middle_click()
                    return 1  # suppress both halves or apps see a dangling press
            except Exception:
                pass  # never let an exception escape into the Windows hook chain
        return _user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        self._proc = _HOOKPROC(self._callback)
        self._hook = _user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        if not self._hook:
            self._error = (
                f"SetWindowsHookEx failed (error {ctypes.get_last_error()})")
            self._ready.set()
            return
        self._ready.set()
        try:
            msg = wintypes.MSG()
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            _user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
            self._proc = None


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #


class ControllerApp(tk.Tk):

    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.resizable(False, False)
        self._apply_icon()

        self.client = PhoneClient()
        self.connected = False

        self.ui_queue: queue.Queue = queue.Queue()
        self.command_queue: queue.Queue = queue.Queue(maxsize=6)

        self._last_trigger = 0.0
        self._stop_event = threading.Event()
        self._hooks: list = []
        self._heartbeat_thread: threading.Thread | None = None

        config = self._load_config()
        preset = config.get("preset", DEFAULT_PRESET)
        if preset not in HOTKEY_PRESETS and preset != CUSTOM_PRESET:
            preset = DEFAULT_PRESET

        # Custom bindings, sanitised against the defaults so a hand-edited or
        # partial config file can never leave a command unbound.
        saved_custom = config.get("custom") or {}
        self.custom_bindings = {
            name: str(saved_custom.get(name) or DEFAULT_CUSTOM[name]).lower()
            for name in BINDABLE
        }

        self.var_ip = tk.StringVar(value=config.get("ip", ""))
        self.var_port = tk.StringVar(value=str(config.get("port", DEFAULT_PORT)))
        self.var_token = tk.StringVar(value=config.get("token", ""))
        self.var_preset = tk.StringVar(value=preset)
        self.var_rediscover = tk.BooleanVar(value=bool(config.get("rediscover", True)))
        self.var_shortcuts = tk.StringVar()
        self.var_wheel_mods = tk.StringVar(
            value=config.get("wheel_modifiers", DEFAULT_WHEEL_MODIFIERS)
        )
        self.var_wheel_invert = tk.BooleanVar(value=bool(config.get("wheel_invert", False)))

        self.wheel_hook = MouseWheelHook(self._on_wheel, self._on_middle_click)
        self.var_wheel = tk.BooleanVar(
            value=bool(config.get("wheel", True)) and IS_WINDOWS
        )

        self.var_topmost = tk.BooleanVar(value=bool(config.get("always_on_top", False)))
        self._wanted_mini = bool(config.get("mini", False))
        self.mini: tk.Toplevel | None = None
        # Every clickable command button, main window and mini remote alike, so
        # they can be enabled/disabled together with the connection.
        self._command_buttons: list[ttk.Button] = []

        # A preset with no bare keys is safe to arm immediately, so it defaults ON.
        # One that steals real keys never auto-arms.
        wants_global = bool(config.get("global", True))
        safe_default = HAVE_KEYBOARD and not self._suppressing()
        self.var_global = tk.BooleanVar(value=wants_global and safe_default)

        self._build_ui()
        self._install_local_bindings()
        self._refresh_shortcut_label()

        self._sender_thread = threading.Thread(target=self._sender_loop, daemon=True)
        self._sender_thread.start()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._drain_ui_queue)
        self.log("Ready. Enter the IP, port and token shown in the phone app.")
        if not HAVE_KEYBOARD:
            self.log("`keyboard` not installed - hotkeys work only when this window is focused.")
        elif self.var_global.get():
            self.on_global_toggled()
        if self.var_wheel.get():
            self.on_wheel_toggled()
        if self.var_topmost.get():
            self.on_topmost_toggled()
        if self._wanted_mini:
            self.open_mini_remote()

    def _apply_icon(self) -> None:
        """
        Window and taskbar icon, the same mark as the Android launcher.

        iconbitmap(default=...) applies to every toplevel this app opens, so the
        mini remote picks it up too. Missing or unreadable assets are ignored —
        an icon is never worth failing to start over.
        """
        ico = os.path.join(ASSET_DIR, "reelremote.ico")
        png = os.path.join(ASSET_DIR, "reelremote.png")
        try:
            if IS_WINDOWS and os.path.exists(ico):
                self.iconbitmap(default=ico)
                return
            if os.path.exists(png):
                # Tk drops the image unless a reference outlives this call.
                self._icon = tk.PhotoImage(file=png)
                self.iconphoto(True, self._icon)
        except tk.TclError:
            pass

    # --- layout ------------------------------------------------------------- #

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        root = ttk.Frame(self, padding=12)
        root.grid(row=0, column=0, sticky="nsew")

        style = ttk.Style(self)
        style.configure("Remote.TButton", font=("Segoe UI", 11, "bold"), padding=(4, 10))

        ttk.Label(root, text="Phone IP").grid(row=0, column=0, sticky="w", **pad)
        self.entry_ip = ttk.Entry(root, textvariable=self.var_ip, width=18)
        self.entry_ip.grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(root, text="Port").grid(row=0, column=2, sticky="w", **pad)
        self.entry_port = ttk.Entry(root, textvariable=self.var_port, width=7)
        self.entry_port.grid(row=0, column=3, sticky="w", **pad)

        ttk.Label(root, text="Token").grid(row=1, column=0, sticky="w", **pad)
        self.entry_token = ttk.Entry(root, textvariable=self.var_token, width=30)
        self.entry_token.grid(row=1, column=1, columnspan=3, sticky="we", **pad)

        buttons = ttk.Frame(root)
        buttons.grid(row=2, column=0, columnspan=4, sticky="we", **pad)

        # takefocus=False everywhere: otherwise a focused button would eat the
        # Space key before the window-focused PLAY_PAUSE binding sees it.
        self.btn_connect = ttk.Button(
            buttons, text="Connect", command=self.on_connect_clicked, takefocus=False
        )
        self.btn_connect.grid(row=0, column=0, padx=(0, 6))

        self.btn_scan = ttk.Button(
            buttons, text="Find phone", command=self.on_scan_clicked, takefocus=False
        )
        self.btn_scan.grid(row=0, column=1, padx=6)

        self.chk_global = ttk.Checkbutton(
            buttons,
            text="Global hotkeys",
            variable=self.var_global,
            command=self.on_global_toggled,
            takefocus=False,
        )
        self.chk_global.grid(row=0, column=2, padx=6)

        ttk.Checkbutton(
            buttons,
            text="Auto re-find on drop",
            variable=self.var_rediscover,
            takefocus=False,
        ).grid(row=0, column=3, padx=6)

        hotkeys = ttk.Frame(root)
        hotkeys.grid(row=3, column=0, columnspan=4, sticky="we", **pad)
        ttk.Label(hotkeys, text="Hotkeys").grid(row=0, column=0, sticky="w")
        self.combo_preset = ttk.Combobox(
            hotkeys,
            textvariable=self.var_preset,
            values=list(HOTKEY_PRESETS.keys()) + [CUSTOM_PRESET],
            state="readonly",
            width=28,
            takefocus=False,
        )
        self.combo_preset.grid(row=0, column=1, sticky="w", padx=8)
        self.combo_preset.bind("<<ComboboxSelected>>", self.on_preset_changed)

        ttk.Button(
            hotkeys, text="Edit...", width=8, takefocus=False,
            command=self.open_binding_editor,
        ).grid(row=0, column=2, padx=6)

        self.chk_wheel = ttk.Checkbutton(
            hotkeys,
            text="Mouse wheel",
            variable=self.var_wheel,
            command=self.on_wheel_toggled,
            takefocus=False,
        )
        self.chk_wheel.grid(row=0, column=3, padx=6)
        if not IS_WINDOWS:
            self.chk_wheel.configure(state="disabled")

        status = ttk.Frame(root)
        status.grid(row=4, column=0, columnspan=4, sticky="we", **pad)
        self.canvas_led = tk.Canvas(status, width=14, height=14, highlightthickness=0)
        self.led = self.canvas_led.create_oval(2, 2, 12, 12, fill="#c62828", outline="")
        self.canvas_led.grid(row=0, column=0, padx=(0, 6))
        self.lbl_status = ttk.Label(status, text="Disconnected")
        self.lbl_status.grid(row=0, column=1, sticky="w")

        remote = ttk.Frame(root)
        remote.grid(row=5, column=0, columnspan=4, sticky="we", **pad)
        for column in range(3):
            remote.columnconfigure(column, weight=1)

        for column, (label, command) in enumerate((
            ("▲  NEXT", "NEXT"),
            ("PLAY / PAUSE", "PLAY_PAUSE"),
            ("▼  PREVIOUS", "PREVIOUS"),
        )):
            button = ttk.Button(
                remote,
                text=label,
                style="Remote.TButton",
                takefocus=False,
                command=lambda c=command: self.trigger(c),
            )
            button.grid(row=0, column=column, sticky="we", padx=3)
            self._command_buttons.append(button)

        extras = ttk.Frame(remote)
        extras.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Checkbutton(
            extras,
            text="Always on top",
            variable=self.var_topmost,
            command=self.on_topmost_toggled,
            takefocus=False,
        ).grid(row=0, column=0, padx=(3, 10))
        ttk.Button(
            extras, text="Mini remote", takefocus=False, command=self.open_mini_remote
        ).grid(row=0, column=1)

        ttk.Label(
            root,
            textvariable=self.var_shortcuts,
            font=("Segoe UI", 9, "bold"),
            justify="left",
        ).grid(row=6, column=0, columnspan=4, sticky="w", **pad)

        self.text_log = tk.Text(root, width=64, height=14, state="disabled",
                                font=("Consolas", 9), wrap="none")
        self.text_log.grid(row=7, column=0, columnspan=4, sticky="nsew", **pad)
        self._set_command_buttons_state()

    # --- config ------------------------------------------------------------- #

    def _load_config(self) -> dict:
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_config(self) -> None:
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "ip": self.var_ip.get().strip(),
                        "port": self._port_or_default(),
                        "token": self.var_token.get().strip(),
                        "rediscover": bool(self.var_rediscover.get()),
                        "preset": self.var_preset.get(),
                        "global": bool(self.var_global.get()),
                        "custom": dict(self.custom_bindings),
                        "wheel": bool(self.var_wheel.get()),
                        "wheel_modifiers": self.var_wheel_mods.get(),
                        "wheel_invert": bool(self.var_wheel_invert.get()),
                        "always_on_top": bool(self.var_topmost.get()),
                        "mini": self.mini is not None and bool(self.mini.winfo_exists()),
                    },
                    handle,
                )
        except OSError:
            pass

    def _port_or_default(self) -> int:
        try:
            port = int(self.var_port.get().strip())
            return port if 1 <= port <= 65535 else DEFAULT_PORT
        except ValueError:
            return DEFAULT_PORT

    # --- UI-thread plumbing -------------------------------------------------- #

    def log(self, line: str) -> None:
        """Thread-safe: queues the line for the Tk thread to render."""
        self.ui_queue.put(("log", time.strftime("%H:%M:%S") + "  " + line))

    def set_status(self, connected: bool, text: str) -> None:
        self.ui_queue.put(("status", (connected, text)))

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "log":
                    self.text_log.configure(state="normal")
                    self.text_log.insert("end", payload + "\n")
                    # Keep the widget from growing without bound.
                    if int(self.text_log.index("end-1c").split(".")[0]) > 300:
                        self.text_log.delete("1.0", "100.0")
                    self.text_log.see("end")
                    self.text_log.configure(state="disabled")
                elif kind == "status":
                    connected, text = payload
                    self.connected = connected
                    self.canvas_led.itemconfig(
                        self.led, fill="#2e7d32" if connected else "#c62828"
                    )
                    self.lbl_status.configure(text=text)
                    self.btn_connect.configure(
                        text="Disconnect" if connected else "Connect"
                    )
                    self._set_command_buttons_state()
                    self._refresh_mini_status()
                elif kind == "ip":
                    self.var_ip.set(payload)
                elif kind == "scan_done":
                    self.btn_scan.configure(state="normal")
                elif kind == "record":
                    var, combo = payload
                    var.set(combo if combo else "")
                elif kind == "disconnect":
                    self._do_disconnect(payload)
        except queue.Empty:
            pass
        self.after(80, self._drain_ui_queue)

    # --- connection ---------------------------------------------------------- #

    def on_connect_clicked(self) -> None:
        if self.connected:
            self._do_disconnect("disconnected by user")
        else:
            threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self) -> None:
        host = self.var_ip.get().strip()
        token = self.var_token.get().strip()
        port = self._port_or_default()

        if not host or not token:
            self.log("Enter the phone IP and the pairing token first.")
            return

        self.client.configure(host, port, token)
        self.set_status(False, f"Connecting to {host}:{port} ...")

        try:
            payload = self.client.ping()
        except requests.RequestException as exc:
            self.set_status(False, "Disconnected")
            self.log(f"Cannot reach {host}:{port} - {type(exc).__name__}")
            self.log("Check: same Wi-Fi, server started in the app, correct IP.")
            return

        if payload.get("_status") == 401:
            self.set_status(False, "Disconnected")
            self.log("Rejected: wrong pairing token.")
            return
        if not payload.get("ok"):
            self.set_status(False, "Disconnected")
            self.log(f"Phone refused the connection: {payload.get('error', 'unknown')}")
            return
        if payload.get("protocol") != PROTOCOL_VERSION:
            self.log(
                f"Warning: phone speaks protocol {payload.get('protocol')}, "
                f"controller speaks {PROTOCOL_VERSION}."
            )

        self.set_status(True, f"Connected to {host}:{port}")
        self.log("Connected")
        self._report_device_state(payload)
        self._save_config()
        self._start_heartbeat()

    def _report_device_state(self, payload: dict) -> None:
        if payload.get("locked"):
            self.log("Note: phone is locked - unlock it before sending commands.")
        elif not payload.get("screen_on", True):
            self.log("Note: phone screen is off.")
        elif payload.get("require_target_foreground") and not payload.get("target_foreground"):
            current = payload.get("foreground_package") or "unknown"
            self.log(f"Note: foreground app is {current}; open Instagram Reels.")

    def request_disconnect(self, reason: str) -> None:
        """Safe to call from any thread; the teardown happens on the Tk thread."""
        self.ui_queue.put(("disconnect", reason))

    def _do_disconnect(self, reason: str) -> None:
        """Tk thread only - it touches Tk variables and widgets."""
        if not self.connected and not self._hooks:
            return
        self._stop_heartbeat()
        # Only a suppressing preset must be torn down on disconnect - it is holding
        # the user's arrow keys hostage. Modifier combos are harmless when idle.
        if self.var_global.get() and self._suppressing():
            self.var_global.set(False)
            self._remove_global_hotkeys()
            self._refresh_shortcut_label()
            self.log("Global hotkeys released.")
        self.connected = False
        self.canvas_led.itemconfig(self.led, fill="#c62828")
        self.lbl_status.configure(text="Disconnected")
        self.btn_connect.configure(text="Connect")
        self._set_command_buttons_state()
        self._refresh_mini_status()
        self.log(f"Disconnected ({reason})")

    # --- heartbeat ----------------------------------------------------------- #

    def _start_heartbeat(self) -> None:
        self._stop_heartbeat()
        self._stop_event = threading.Event()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, args=(self._stop_event,), daemon=True
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._stop_event.set()
        self._heartbeat_thread = None

    def _heartbeat_loop(self, stop_event: threading.Event) -> None:
        failures = 0
        while not stop_event.wait(HEARTBEAT_SECONDS):
            try:
                payload = self.client.ping(timeout=1.0)
                if payload.get("ok"):
                    failures = 0
                    continue
                failures += 1
            except requests.RequestException:
                failures += 1

            if failures >= HEARTBEAT_FAILURES_BEFORE_DROP:
                self.log("Lost contact with the phone.")
                if self.var_rediscover.get() and self._try_rediscover(stop_event):
                    failures = 0
                    continue
                self.request_disconnect("connection lost")
                return

    def _try_rediscover(self, stop_event: threading.Event) -> bool:
        """The phone's DHCP lease may have moved it to a new address."""
        self.log("Searching the local network for the phone ...")
        host = scan_subnet(self.client.port, self.client.token)
        if stop_event.is_set():
            return False
        if not host:
            self.log("Not found on this subnet.")
            return False
        self.client.host = host
        self.ui_queue.put(("ip", host))
        self.ui_queue.put(("status", (True, f"Connected to {host}:{self.client.port}")))
        self.log(f"Phone moved to {host} - reconnected.")
        self._save_config()
        return True

    def on_scan_clicked(self) -> None:
        token = self.var_token.get().strip()
        if not token:
            self.log("Enter the pairing token before scanning.")
            return
        self.client.token = token
        self.btn_scan.configure(state="disabled")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self) -> None:
        port = self._port_or_default()
        self.log(f"Scanning the local /24 on port {port} ...")
        try:
            host = scan_subnet(port, self.client.token)
            if host:
                self.ui_queue.put(("ip", host))
                self.log(f"Found phone at {host}. Press Connect.")
            else:
                self.log("No phone found. Is the server started and the token correct?")
        except Exception as exc:
            self.log(f"Scan failed: {exc}")
        finally:
            self.ui_queue.put(("scan_done", None))

    # --- command dispatch ---------------------------------------------------- #

    def trigger(self, command: str) -> None:
        """Called from Tk bindings and from the global hook thread."""
        if not self.connected:
            return
        now = time.monotonic()
        if now - self._last_trigger < MIN_COMMAND_INTERVAL:
            return  # swallow key-repeat and double taps
        self._last_trigger = now
        try:
            self.command_queue.put_nowait(command)
        except queue.Full:
            pass  # already saturated; dropping is the correct behaviour here

    def _sender_loop(self) -> None:
        while True:
            command = self.command_queue.get()
            if command is None:
                return
            if not self.connected:
                continue
            try:
                payload = self.client.send(command)
            except requests.RequestException as exc:
                self.log(f"{command} failed - {type(exc).__name__}")
                continue

            if payload.get("ok"):
                self.log(f"{command} sent")
            else:
                error = payload.get("error", "ERROR")
                message = payload.get("message", "")
                self.log(f"{command} refused: {error} {message}".rstrip())

    # --- keyboard ------------------------------------------------------------ #

    def _install_local_bindings(self) -> None:
        """Window-focused fallback. Ignored while typing in a text field."""
        for key, command in (("<Up>", "NEXT"), ("<Down>", "PREVIOUS"), ("<space>", "PLAY_PAUSE")):
            self.bind_all(key, lambda event, c=command: self._local_key(event, c))
        self.bind_all("<Escape>", lambda event: self._local_escape(event))

    def _typing_in_entry(self) -> bool:
        try:
            widget = self.focus_get()
        except KeyError:
            return False
        return isinstance(widget, (tk.Entry, tk.Text))

    def _local_key(self, event, command: str):
        if self.var_global.get() and self._suppressing():
            return  # the global hook binds these same bare keys and already fired
        if self._typing_in_entry():
            return
        self.trigger(command)
        return "break"

    def _local_escape(self, event):
        if self.connected:
            self._do_disconnect("Esc pressed")
        return "break"

    # --- global hotkeys ------------------------------------------------------ #

    def _preset(self) -> dict:
        if self.var_preset.get() == CUSTOM_PRESET:
            return dict(self.custom_bindings)
        return HOTKEY_PRESETS.get(self.var_preset.get(), HOTKEY_PRESETS[DEFAULT_PRESET])

    def _suppressing(self) -> bool:
        """True when the active bindings steal real keys from other apps."""
        preset = self._preset()
        return any(needs_suppression(preset[c]) for c in COMMAND_ORDER)

    def _refresh_shortcut_label(self) -> None:
        preset = self._preset()
        scope = "global" if self.var_global.get() else "this window only"
        line = "     ".join(
            f"{preset[command]} = {command}" for command in COMMAND_ORDER
        )
        text = f"{line}     {preset['DISCONNECT']} = disconnect      [{scope}]"
        if self.var_wheel.get() and self.wheel_hook.running:
            mods = "+".join(parse_modifiers(self.var_wheel_mods.get()))
            forward, back = ("wheel up", "wheel down") if self.var_wheel_invert.get() \
                else ("wheel down", "wheel up")
            text += (f"\n{mods}+{forward} = NEXT     {mods}+{back} = PREVIOUS"
                     f"     {mods}+middle click = PLAY_PAUSE")
        self.var_shortcuts.set(text)

    def on_preset_changed(self, event=None) -> None:
        was_on = self.var_global.get()
        if was_on:
            self._remove_global_hotkeys()
        if was_on and self._suppressing():
            # Never silently arm bindings that eat the user's keyboard.
            self.var_global.set(False)
            self.log("These bindings steal real keys - re-tick 'Global hotkeys' to confirm.")
        elif was_on:
            self._install_global_hotkeys()
        self._refresh_shortcut_label()
        self._save_config()

    def on_global_toggled(self) -> None:
        if self.var_global.get():
            if not HAVE_KEYBOARD:
                self.var_global.set(False)
                self.log("Install the `keyboard` package to use global hotkeys.")
                self._refresh_shortcut_label()
                return
            if self._install_global_hotkeys():
                preset = self._preset()
                combos = ", ".join(preset[c] for c in COMMAND_ORDER)
                self.log(f"Global hotkeys ON - {combos}")
                if self._suppressing():
                    self.log("WARNING: bare keys are swallowed in every app while armed.")
            else:
                self.var_global.set(False)
        else:
            self._remove_global_hotkeys()
            self.log("Global hotkeys OFF - keys work only when this window is focused.")
        self._refresh_shortcut_label()

    def _install_global_hotkeys(self) -> bool:
        preset = self._preset()
        try:
            for command in COMMAND_ORDER:
                combo = preset[command]
                self._hooks.append(
                    self._register_hotkey(combo, needs_suppression(combo),
                                          lambda c=command: self.trigger(c))
                )
            # The disconnect key is never suppressed - other apps still need Esc.
            self._hooks.append(
                self._register_hotkey(preset["DISCONNECT"], False, self._global_disconnect)
            )
            return True
        except Exception as exc:
            self.log(f"Could not install global hooks: {exc}")
            self.log("The combo may be taken by another app; try a different preset,")
            self.log("or run the controller as Administrator.")
            self._remove_global_hotkeys()
            return False

    @staticmethod
    def _register_hotkey(combo: str, suppress: bool, callback):
        """
        Single keys go through on_press_key (reliable with suppression); real
        combos go through add_hotkey, which understands the '+' syntax.

        NB: do not name this `_register` - that is an internal Tkinter method on
        Misc, and shadowing it breaks Tk.__init__.
        """
        if "+" in combo:
            return kb.add_hotkey(combo, callback, suppress=suppress,
                                 trigger_on_release=False)
        return kb.on_press_key(combo, lambda event: callback(), suppress=suppress)

    def _global_disconnect(self) -> None:
        if self.connected:
            self.request_disconnect("disconnect hotkey pressed")

    # --- mouse wheel --------------------------------------------------------- #

    def on_wheel_toggled(self) -> None:
        if self.var_wheel.get():
            mods = parse_modifiers(self.var_wheel_mods.get())
            error = self.wheel_hook.start(mods)
            if error:
                self.var_wheel.set(False)
                self.log(f"Mouse wheel control unavailable: {error}")
            else:
                self.log(f"Mouse wheel ON - hold {'+'.join(mods)} and scroll.")
        else:
            self.wheel_hook.stop()
            self.log("Mouse wheel OFF.")
        self._refresh_shortcut_label()
        self._save_config()

    def _on_wheel(self, delta: int) -> None:
        """Hook-thread callback. delta > 0 is a scroll away from the user."""
        forward = delta < 0  # scrolling down advances a feed, as on the web
        if self.var_wheel_invert.get():
            forward = not forward
        self.trigger("NEXT" if forward else "PREVIOUS")

    def _on_middle_click(self) -> None:
        self.trigger("PLAY_PAUSE")

    # --- on-screen buttons --------------------------------------------------- #

    def _set_command_buttons_state(self) -> None:
        """Grey the buttons out while disconnected so the state is obvious."""
        state = "normal" if self.connected else "disabled"
        for button in list(self._command_buttons):
            try:
                button.configure(state=state)
            except tk.TclError:
                self._command_buttons.remove(button)  # its window was destroyed

    def on_topmost_toggled(self) -> None:
        pinned = bool(self.var_topmost.get())
        self.attributes("-topmost", pinned)
        self.log(f"Main window {'pinned on top' if pinned else 'unpinned'}.")
        self._save_config()

    def open_mini_remote(self) -> None:
        """
        A small always-on-top pad with just the three buttons, for clicking while
        the browser or anything else has focus.
        """
        if self.mini is not None and self.mini.winfo_exists():
            self.mini.lift()
            self.mini.focus_force()
            return

        win = tk.Toplevel(self)
        win.title("Reel Remote")
        win.resizable(False, False)
        win.attributes("-topmost", True)  # the entire point of this window
        self.mini = win

        frame = ttk.Frame(win, padding=8)
        frame.grid(row=0, column=0, sticky="nsew")

        created: list[ttk.Button] = []
        for row, (label, command) in enumerate((
            ("▲  NEXT", "NEXT"),
            ("PLAY / PAUSE", "PLAY_PAUSE"),
            ("▼  PREVIOUS", "PREVIOUS"),
        )):
            button = ttk.Button(
                frame,
                text=label,
                width=16,
                style="Remote.TButton",
                takefocus=False,
                command=lambda c=command: self.trigger(c),
            )
            button.grid(row=row, column=0, sticky="we", pady=2)
            created.append(button)
            self._command_buttons.append(button)

        self.mini_status = ttk.Label(frame, text="", font=("Segoe UI", 8))
        self.mini_status.grid(row=3, column=0, pady=(6, 0))

        def close() -> None:
            for button in created:
                if button in self._command_buttons:
                    self._command_buttons.remove(button)
            self.mini = None
            self.mini_status = None
            win.destroy()
            self._save_config()

        win.protocol("WM_DELETE_WINDOW", close)

        # Park it just right of the main window rather than on top of it.
        self.update_idletasks()
        win.geometry(f"+{self.winfo_x() + self.winfo_width() + 12}+{self.winfo_y()}")

        self._set_command_buttons_state()
        self._refresh_mini_status()
        self._save_config()

    def _refresh_mini_status(self) -> None:
        status = getattr(self, "mini_status", None)
        if status is None:
            return
        try:
            status.configure(
                text="Connected" if self.connected else "Disconnected",
                foreground="#2e7d32" if self.connected else "#c62828",
            )
        except tk.TclError:
            self.mini_status = None

    # --- custom binding editor ----------------------------------------------- #

    def open_binding_editor(self) -> None:
        """Edit the Custom bindings. Opening it switches the preset to Custom."""
        if self.var_preset.get() != CUSTOM_PRESET:
            # Seed the custom set from whatever preset is showing, so the editor
            # starts from something familiar rather than from stale values.
            self.custom_bindings = dict(self._preset())
            self.var_preset.set(CUSTOM_PRESET)
            self.on_preset_changed()

        win = tk.Toplevel(self)
        win.title("Custom shortcuts")
        win.resizable(False, False)
        win.transient(self)
        frame = ttk.Frame(win, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            frame,
            text="Click Record and press the combination you want,\n"
                 "or type it directly (e.g. ctrl+alt+j).",
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        entries: dict[str, tk.StringVar] = {}
        for index, name in enumerate(BINDABLE, start=1):
            ttk.Label(frame, text=name).grid(row=index, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=self.custom_bindings[name])
            entries[name] = var
            ttk.Entry(frame, textvariable=var, width=26).grid(
                row=index, column=1, sticky="we", padx=8, pady=3)
            ttk.Button(
                frame, text="Record", width=9, takefocus=False,
                command=lambda v=var: self._record_hotkey(v),
            ).grid(row=index, column=2, pady=3)

        wheel_row = len(BINDABLE) + 1
        ttk.Separator(frame, orient="horizontal").grid(
            row=wheel_row, column=0, columnspan=3, sticky="we", pady=10)
        ttk.Label(frame, text="Wheel modifiers").grid(
            row=wheel_row + 1, column=0, sticky="w")
        wheel_var = tk.StringVar(value=self.var_wheel_mods.get())
        ttk.Entry(frame, textvariable=wheel_var, width=26).grid(
            row=wheel_row + 1, column=1, sticky="we", padx=8)
        invert_var = tk.BooleanVar(value=self.var_wheel_invert.get())
        ttk.Checkbutton(
            frame, text="Invert wheel direction", variable=invert_var, takefocus=False
        ).grid(row=wheel_row + 2, column=1, sticky="w", padx=8, pady=(6, 0))

        message = ttk.Label(frame, text="", foreground="#c62828")
        message.grid(row=wheel_row + 3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        def save() -> None:
            chosen = {}
            for name, var in entries.items():
                combo = var.get().strip().lower()
                if not combo:
                    message.configure(text=f"{name} cannot be empty.")
                    return
                if HAVE_KEYBOARD:
                    try:
                        kb.parse_hotkey(combo)
                    except Exception:
                        message.configure(text=f"{name}: '{combo}' is not a valid combo.")
                        return
                chosen[name] = combo

            duplicates = [c for c in chosen.values() if list(chosen.values()).count(c) > 1]
            if duplicates:
                message.configure(text=f"'{duplicates[0]}' is bound twice.")
                return

            mods = parse_modifiers(wheel_var.get())
            if self.var_wheel.get() and not mods:
                message.configure(text="Wheel needs at least one modifier.")
                return

            self.custom_bindings = chosen
            self.var_wheel_mods.set("+".join(mods) if mods else DEFAULT_WHEEL_MODIFIERS)
            self.var_wheel_invert.set(invert_var.get())
            win.destroy()

            self.on_preset_changed()          # re-arms the keyboard hooks
            if self.var_wheel.get():          # re-arm the wheel with new modifiers
                self.wheel_hook.stop()
                self.on_wheel_toggled()
            self.log("Custom shortcuts saved.")

        buttons = ttk.Frame(frame)
        buttons.grid(row=wheel_row + 4, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Save", command=save, takefocus=False).grid(
            row=0, column=0, padx=4)
        ttk.Button(buttons, text="Cancel", command=win.destroy, takefocus=False).grid(
            row=0, column=1, padx=4)
        ttk.Button(
            buttons, text="Reset",
            takefocus=False,
            command=lambda: [entries[n].set(DEFAULT_CUSTOM[n]) for n in BINDABLE],
        ).grid(row=0, column=2, padx=4)

        win.grab_set()

    def _record_hotkey(self, var: tk.StringVar) -> None:
        """
        Capture the next combination the user presses.

        keyboard.read_hotkey() blocks until the keys are released and returns the
        exact same string format we feed back to add_hotkey(), so a recorded combo
        is guaranteed to be registrable. It runs on a worker thread and reports
        back through the Tk queue.
        """
        if not HAVE_KEYBOARD:
            self.log("Install `keyboard` to record combos, or type one manually.")
            return
        var.set("press keys...")

        def worker() -> None:
            try:
                combo = kb.read_hotkey(suppress=False)
            except Exception as exc:
                self.ui_queue.put(("log", f"Recording failed: {exc}"))
                combo = None
            self.ui_queue.put(("record", (var, combo)))

        threading.Thread(target=worker, daemon=True).start()

    def _remove_global_hotkeys(self) -> None:
        if not HAVE_KEYBOARD:
            return
        for hook in self._hooks:
            # add_hotkey handles come off via remove_hotkey, on_press_key handles
            # via unhook. Which one a handle is depends on the preset, so try both.
            for remover in (kb.remove_hotkey, kb.unhook):
                try:
                    remover(hook)
                    break
                except Exception:
                    continue
        self._hooks.clear()

    # --- shutdown ------------------------------------------------------------ #

    def _on_close(self) -> None:
        self._stop_heartbeat()
        self._remove_global_hotkeys()
        self.wheel_hook.stop()
        self._save_config()
        try:
            self.command_queue.put_nowait(None)
        except queue.Full:
            pass
        self.destroy()


def main() -> None:
    app = ControllerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
