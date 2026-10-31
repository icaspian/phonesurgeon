"""
modules/screen_mirror.py — Screen Mirroring & scrcpy Integration for DroidCommander.

Provides a comprehensive screen mirroring, remote control, and recording toolkit using scrcpy:
- scrcpy availability detection and cross-platform installation instructions
- Default screen mirroring with automatic device serial targeting
- Custom resolution scaling / downscaling presets (--max-size)
- Video bitrate configuration (-b / --bit-rate) for low-latency or high-quality streams
- Host-side screen recording directly to MP4/MKV video files (--record)
- Audio routing control (--no-audio) for older devices or latency reduction
- Custom window title naming (--window-title)
- Fullscreen mode launch (--fullscreen)
- Wireless screen mirroring over Wi-Fi ADB (auto TCP/IP setup & IP discovery)
- Complete scrcpy keyboard shortcuts & gestures quick reference
- Read-only / view-only presentation mode (--no-control)
- Direct link to official scrcpy releases & documentation in web browser
- Device physical screen-off mirroring (--turn-screen-off) to save battery and reduce heat
- Show physical touch visualizer (--show-touches) for tutorials & presentations
- Keep device awake (--stay-awake) during mirroring sessions
- Always-on-top window pin (--always-on-top)
- Advanced interactive launcher wizard (custom multi-flag builder)
- Active scrcpy process management & background session monitoring
"""

import os
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Any

from core.adb import adb
from core import ui
from core.device import ensure_device


# ─── URLs & Constants ────────────────────────────────────────────────────────

SCRCPY_DOWNLOAD_URL = "https://github.com/Genymobile/scrcpy/releases"
SCRCPY_GITHUB_URL = "https://github.com/Genymobile/scrcpy"
SCRCPY_DOCS_URL = "https://github.com/Genymobile/scrcpy#readme"

# Track background scrcpy sessions spawned during the current program run
_ACTIVE_SESSIONS: List[Dict[str, Any]] = []


# ─── Directory & File Helpers ────────────────────────────────────────────────

def _get_recordings_dir() -> str:
    """
    Get the absolute path to the local recordings directory.

    Creates the directory if it does not already exist.
    """
    target_dir = os.path.join(os.getcwd(), "captures", "recordings")
    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def _get_logs_dir() -> str:
    """
    Get the absolute path to the scrcpy session logs directory.

    Creates the directory if it does not already exist.
    """
    target_dir = os.path.join(os.getcwd(), "captures", "logs")
    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def _human_size(num_bytes: int) -> str:
    """Convert integer byte count to human-readable string."""
    if num_bytes < 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    unit_idx = 0
    while size >= 1024.0 and unit_idx < len(units) - 1:
        size /= 1024.0
        unit_idx += 1
    return f"{size:.2f} {units[unit_idx]}" if unit_idx > 0 else f"{int(size)} B"


def _open_folder(directory_path: str):
    """Open the specified folder in the operating system default file manager."""
    try:
        abs_path = os.path.abspath(directory_path)
        if sys.platform.startswith("win"):
            os.startfile(abs_path)
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", abs_path])
        else:
            subprocess.Popen(["xdg-open", abs_path])
        ui.success(f"Opened folder: {abs_path}")
    except Exception as exc:
        ui.error(f"Failed to open folder: {exc}")


def _open_file(file_path: str):
    """Open a media file in the operating system default viewer."""
    try:
        abs_path = os.path.abspath(file_path)
        if sys.platform.startswith("win"):
            os.startfile(abs_path)
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", abs_path])
        else:
            subprocess.Popen(["xdg-open", abs_path])
    except Exception as exc:
        ui.warning(f"Could not open file automatically: {exc}")


# ─── Scrcpy Detection & Diagnostics ──────────────────────────────────────────

def is_scrcpy_installed() -> bool:
    """
    Check whether scrcpy is available in the system PATH or common directories.

    Returns True if found, False otherwise.
    """
    # Check standard PATH
    if shutil.which("scrcpy") is not None:
        return True

    # Check common fallback locations on Windows
    if sys.platform.startswith("win"):
        common_paths = [
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "scrcpy", "scrcpy.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "scrcpy", "scrcpy.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "scrcpy", "scrcpy.exe"),
            os.path.join(os.environ.get("USERPROFILE", ""), "scrcpy", "scrcpy.exe"),
            os.path.join(os.getcwd(), "scrcpy.exe"),
            os.path.join(os.getcwd(), "scrcpy", "scrcpy.exe"),
        ]
        for p in common_paths:
            if os.path.isfile(p):
                return True

    return False


def get_scrcpy_binary() -> str:
    """
    Return the resolved executable command or path for scrcpy.

    Defaults to 'scrcpy' if found in PATH or as fallback.
    """
    which_path = shutil.which("scrcpy")
    if which_path:
        return which_path

    if sys.platform.startswith("win"):
        common_paths = [
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "scrcpy", "scrcpy.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "scrcpy", "scrcpy.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "scrcpy", "scrcpy.exe"),
            os.path.join(os.environ.get("USERPROFILE", ""), "scrcpy", "scrcpy.exe"),
            os.path.join(os.getcwd(), "scrcpy.exe"),
            os.path.join(os.getcwd(), "scrcpy", "scrcpy.exe"),
        ]
        for p in common_paths:
            if os.path.isfile(p):
                return p

    return "scrcpy"


def get_scrcpy_version() -> Optional[str]:
    """
    Query the scrcpy binary version string.

    Returns e.g. 'scrcpy 2.4' or None if undetectable.
    """
    if not is_scrcpy_installed():
        return None
    try:
        bin_path = get_scrcpy_binary()
        proc = subprocess.run(
            [bin_path, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=5,
        )
        if proc.stdout:
            for line in proc.stdout.splitlines():
                line_str = line.strip()
                if "scrcpy" in line_str.lower():
                    return line_str
    except Exception:
        pass
    return None


def show_installation_guide() -> None:
    """Display comprehensive cross-platform installation guide for scrcpy."""
    ui.header("scrcpy Installation Guide")
    print(f"""
  {ui.Colors.YELLOW}scrcpy{ui.Colors.RESET} is a free, open-source display mirroring & remote control tool
  developed by Genymobile. It provides low latency, high quality, and requires
  no root access on the Android device.

  {ui.Colors.BOLD}{ui.Colors.CYAN}── Windows Installation ──{ui.Colors.RESET}
    Option A (Windows Package Manager - Recommended):
      {ui.Colors.GREEN}winget install Genymobile.scrcpy{ui.Colors.RESET}

    Option B (Chocolatey):
      {ui.Colors.GREEN}choco install scrcpy{ui.Colors.RESET}

    Option C (Scoop):
      {ui.Colors.GREEN}scoop install scrcpy{ui.Colors.RESET}

    Option D (Manual ZIP):
      1. Download the pre-built zip from GitHub releases
      2. Extract to a folder (e.g. C:\\scrcpy)
      3. Add that folder to your Windows System PATH environment variable

  {ui.Colors.BOLD}{ui.Colors.CYAN}── macOS Installation ──{ui.Colors.RESET}
    Using Homebrew:
      {ui.Colors.GREEN}brew install scrcpy{ui.Colors.RESET}

  {ui.Colors.BOLD}{ui.Colors.CYAN}── Linux Installation ──{ui.Colors.RESET}
    Debian / Ubuntu / Mint:
      {ui.Colors.GREEN}sudo apt update && sudo apt install scrcpy{ui.Colors.RESET}
    Fedora:
      {ui.Colors.GREEN}sudo dnf copr enable zeno/scrcpy && sudo dnf install scrcpy{ui.Colors.RESET}
    Arch Linux / Manjaro:
      {ui.Colors.GREEN}sudo pacman -S scrcpy{ui.Colors.RESET}
    Snap (Universal):
      {ui.Colors.GREEN}sudo snap install scrcpy{ui.Colors.RESET}

  {ui.Colors.BOLD}{ui.Colors.CYAN}── Requirements ──{ui.Colors.RESET}
    • Android 5.0+ (Lollipop) or higher (Android 11+ for audio forwarding)
    • USB Debugging enabled on device
    • Device connected via USB or Wi-Fi ADB
""")
    if ui.confirm("Open official scrcpy download page in your web browser?"):
        webbrowser.open(SCRCPY_DOWNLOAD_URL)
        ui.success("Opened download page in browser.")


def check_scrcpy_status() -> bool:
    """
    Check if scrcpy is installed and report detailed environment status.

    Returns True if scrcpy is found and operational, False otherwise.
    """
    ui.header("scrcpy Environment & Installation Status")
    print()

    installed = is_scrcpy_installed()
    bin_path = get_scrcpy_binary() if installed else "Not found in PATH"
    version_str = get_scrcpy_version() if installed else "N/A"

    # Check ADB status alongside scrcpy
    adb_online = bool(adb.serial and adb.serial in adb.get_connected_serials())
    active_target = adb.serial if adb.serial else "None (Select from menu)"

    status_data = {
        "scrcpy Status": f"{ui.Colors.GREEN}Installed & Ready{ui.Colors.RESET}" if installed else f"{ui.Colors.RED}Not Installed{ui.Colors.RESET}",
        "Executable Path": bin_path,
        "scrcpy Version": version_str or "Unknown",
        "Target Device": active_target,
        "Device Connected": f"{ui.Colors.GREEN}Yes{ui.Colors.RESET}" if adb_online else f"{ui.Colors.YELLOW}No device connected{ui.Colors.RESET}",
        "Official Releases": SCRCPY_DOWNLOAD_URL,
    }
    ui.print_kv(status_data)
    print()

    if not installed:
        ui.warning("scrcpy was not detected on your system.")
        if ui.confirm("Would you like to view the complete installation guide now?"):
            show_installation_guide()
        return False
    else:
        ui.success("scrcpy is properly installed and ready for screen mirroring!")
        return True


# ─── Wi-Fi IP Discovery Helper ───────────────────────────────────────────────

def _get_wlan_ip() -> Optional[str]:
    """
    Detect and return the Wi-Fi IPv4 address (wlan0) of the target device.

    Queries multiple Android system mechanisms for maximum compatibility.
    """
    # Method 1: ip -f inet addr show wlan0
    ok, out = adb.run(["shell", "ip", "-f", "inet", "addr", "show", "wlan0"])
    if ok and out:
        match = re.search(r"inet\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", out)
        if match:
            return match.group(1)

    # Method 2: getprop dhcp.wlan0.ipaddress
    ip_prop = adb.getprop("dhcp.wlan0.ipaddress").strip()
    if ip_prop and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip_prop):
        return ip_prop

    # Method 3: ip route show dev wlan0
    ok, out = adb.run(["shell", "ip", "route", "show"])
    if ok and out:
        for line in out.splitlines():
            if "wlan0" in line and "src" in line:
                parts = line.split()
                if "src" in parts:
                    idx = parts.index("src")
                    if idx + 1 < len(parts):
                        return parts[idx + 1]

    # Method 4: ifconfig wlan0
    ok, out = adb.run(["shell", "ifconfig", "wlan0"])
    if ok and out:
        match = re.search(r"inet\s+addr:(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", out)
        if match:
            return match.group(1)

    # Method 5: inspect all interfaces via ip -4 addr
    ok, out = adb.run(["shell", "ip", "-4", "addr", "show"])
    if ok and out:
        for block in out.split("\n\n"):
            if "wlan" in block or "wlp" in block:
                match = re.search(r"inet\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", block)
                if match:
                    return match.group(1)

    return None


# ─── Background Session Tracking & Core Launcher ─────────────────────────────

def _clean_sessions() -> None:
    """Clean up terminated scrcpy processes from active session tracker."""
    for sess in _ACTIVE_SESSIONS:
        proc: subprocess.Popen = sess["proc"]
        if proc.poll() is not None:
            sess["status"] = f"Exited (code {proc.returncode})"
            if sess.get("log_file_handle") and not sess["log_file_handle"].closed:
                try:
                    sess["log_file_handle"].close()
                except Exception:
                    pass


def _launch_scrcpy_subprocess(extra_args: List[str], label: str = "Mirror Session") -> bool:
    """
    Central non-blocking launcher for scrcpy.

    - Verifies scrcpy is installed
    - Ensures device is selected and active
    - Targets active device serial (-s <serial>)
    - Spawns subprocess.Popen without blocking the terminal
    - Verifies process didn't crash during immediate initialization
    - Logs session output to captures/logs/
    """
    if not is_scrcpy_installed():
        ui.error("scrcpy is not installed or not found in system PATH.")
        show_installation_guide()
        return False

    if not ensure_device():
        return False

    bin_path = get_scrcpy_binary()
    cmd: List[str] = [bin_path]

    # Explicitly target active selected device
    if adb.serial:
        cmd.extend(["-s", adb.serial])

    # Append user/feature arguments
    cmd.extend(extra_args)

    ui.info(f"Launching {label}...")
    ui.info(f"Command: {ui.Colors.DIM}{' '.join(cmd)}{ui.Colors.RESET}")

    logs_dir = _get_logs_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"scrcpy_{timestamp}.log"
    log_filepath = os.path.join(logs_dir, log_filename)

    try:
        log_file_handle = open(log_filepath, "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            cmd,
            stdout=log_file_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Brief pause to verify the process didn't fail on instant startup
        time.sleep(0.4)
        exit_code = proc.poll()

        if exit_code is not None and exit_code != 0:
            log_file_handle.close()
            ui.error(f"scrcpy failed to start (Process exited with code {exit_code}).")
            if os.path.isfile(log_filepath):
                try:
                    with open(log_filepath, "r", encoding="utf-8", errors="replace") as lf:
                        err_content = lf.read().strip()
                        if err_content:
                            print(f"\n  {ui.Colors.RED}{ui.Colors.BOLD}Error Output:{ui.Colors.RESET}")
                            for eline in err_content.splitlines()[-10:]:
                                print(f"    {ui.Colors.RED}{eline}{ui.Colors.RESET}")
                except Exception:
                    pass
            ui.info(f"Full log available at: {log_filepath}")
            return False

        # Register active session
        session_info = {
            "pid": proc.pid,
            "label": label,
            "cmd": cmd,
            "start_time": datetime.now().strftime("%H:%M:%S"),
            "proc": proc,
            "status": "Running",
            "log_path": log_filepath,
            "log_file_handle": log_file_handle,
            "serial": adb.serial or "Unknown",
        }
        _ACTIVE_SESSIONS.append(session_info)

        ui.success(f"{label} launched successfully! (PID: {proc.pid})")
        ui.info("scrcpy is running in a separate window. You may continue using DroidCommander.")
        ui.info(f"Session log: {log_filepath}")
        return True

    except FileNotFoundError:
        ui.error("Failed to execute scrcpy. File not found.")
        show_installation_guide()
        return False
    except Exception as exc:
        ui.error(f"Unexpected error launching scrcpy: {exc}")
        return False


# ─── Feature 1: Default Mirror ───────────────────────────────────────────────

def launch_default_mirror() -> bool:
    """Launch scrcpy with standard default settings and device window title."""
    ui.header("Launch Screen Mirror (Default)")
    print()
    if not ensure_device():
        return False

    model = adb.getprop("ro.product.model") or adb.serial
    title = f"DroidCommander - {model} ({adb.serial})"
    args = ["--window-title", title]

    return _launch_scrcpy_subprocess(args, label=f"Screen Mirror [{model}]")


# ─── Feature 2: Custom Resolution ───────────────────────────────────────────

def launch_custom_resolution() -> bool:
    """Launch scrcpy with downscaled or restricted resolution (--max-size)."""
    ui.header("Launch Screen Mirror (Custom Resolution)")
    print("""
  Limiting screen resolution reduces video encoder load on the device,
  lowers USB/Wi-Fi bandwidth usage, and improves frame rates.
""")
    if not ensure_device():
        return False

    resolutions = [
        ("1920", "1080p Full HD limit (Crisp high-definition)"),
        ("1600", "1600px limit (Great for high-DPI tablets)"),
        ("1440", "1440px limit (Balanced 2K downscale)"),
        ("1280", "720p HD limit (Recommended for smooth responsiveness)"),
        ("1024", "1024px limit (Low latency standard)"),
        ("800",  "800px limit (Ultra-low bandwidth / slower connections)"),
        ("640",  "480p SD limit (Maximum FPS / lowest latency)"),
        ("custom", "Enter custom pixel dimension"),
    ]

    print(f"  {ui.Colors.CYAN}{ui.Colors.BOLD}Available Resolution Presets:{ui.Colors.RESET}")
    for idx, (res, desc) in enumerate(resolutions, 1):
        print(f"    {ui.Colors.YELLOW}[{idx}]{ui.Colors.RESET} {res:<7} — {desc}")
    print()

    choice = ui.get_choice("Select resolution option [4 for 1280]")
    selected_res = "1280"

    if choice == "0":
        ui.info("Operation cancelled.")
        return False
    elif choice.isdigit() and 1 <= int(choice) <= len(resolutions):
        idx = int(choice) - 1
        if resolutions[idx][0] == "custom":
            custom_input = ui.get_choice("Enter maximum resolution (e.g. 1024, 960)")
            if not custom_input.isdigit() or int(custom_input) < 100:
                ui.error("Invalid resolution value. Must be a number >= 100.")
                return False
            selected_res = custom_input.strip()
        else:
            selected_res = resolutions[idx][0]
    elif choice.strip():
        if choice.strip().isdigit() and int(choice.strip()) >= 100:
            selected_res = choice.strip()
        else:
            ui.error("Invalid choice.")
            return False

    model = adb.getprop("ro.product.model") or adb.serial
    title = f"DroidCommander - {model} [{selected_res}p]"
    args = [
        "--max-size", selected_res,
        "--window-title", title,
    ]

    return _launch_scrcpy_subprocess(args, label=f"Screen Mirror ({selected_res}px)")


# ─── Feature 3: Custom Bitrate ───────────────────────────────────────────────

def launch_custom_bitrate() -> bool:
    """Launch scrcpy with a user-selected video stream bitrate (-b / --bit-rate)."""
    ui.header("Launch Screen Mirror (Custom Bitrate)")
    print("""
  Higher bitrates increase visual sharpness for high-action games or videos,
  while lower bitrates minimize frame drops and network latency over Wi-Fi.
""")
    if not ensure_device():
        return False

    bitrate_options = [
        ("2M",  "2 Mbps (Ultra-light, best for congested Wi-Fi)"),
        ("4M",  "4 Mbps (Lightweight, responsive, low latency)"),
        ("8M",  "8 Mbps (scrcpy default, great all-round fidelity)"),
        ("12M", "12 Mbps (High fidelity, crisp text & small details)"),
        ("16M", "16 Mbps (Very high quality, ideal for video playback)"),
        ("24M", "24 Mbps (Maximum quality, high-speed USB required)"),
        ("custom", "Enter custom bitrate (e.g. 6M, 10M, 500K)"),
    ]

    print(f"  {ui.Colors.CYAN}{ui.Colors.BOLD}Available Bitrate Presets:{ui.Colors.RESET}")
    for idx, (br, desc) in enumerate(bitrate_options, 1):
        print(f"    {ui.Colors.YELLOW}[{idx}]{ui.Colors.RESET} {br:<7} — {desc}")
    print()

    choice = ui.get_choice("Select bitrate option [3 for 8M]")
    selected_br = "8M"

    if choice == "0":
        ui.info("Operation cancelled.")
        return False
    elif choice.isdigit() and 1 <= int(choice) <= len(bitrate_options):
        idx = int(choice) - 1
        if bitrate_options[idx][0] == "custom":
            custom_input = ui.get_choice("Enter bitrate with unit (e.g. 6M, 10M, 800K)").strip()
            if not custom_input:
                ui.error("Bitrate cannot be empty.")
                return False
            selected_br = custom_input
        else:
            selected_br = bitrate_options[idx][0]
    elif choice.strip():
        selected_br = choice.strip()

    model = adb.getprop("ro.product.model") or adb.serial
    title = f"DroidCommander - {model} [{selected_br}]"
    # Using '-b' for maximum backward and forward compatibility across scrcpy versions
    args = [
        "-b", selected_br,
        "--window-title", title,
    ]

    return _launch_scrcpy_subprocess(args, label=f"Screen Mirror ({selected_br} bitrate)")


# ─── Feature 4: Screen Recording ─────────────────────────────────────────────

def launch_record_mode() -> bool:
    """Launch scrcpy with screen recording directly saved to local disk (--record)."""
    ui.header("Launch Screen Mirror (Recording Mode)")
    print("""
  Record your Android device screen directly to your computer in MP4 or MKV format.
  No temporary files are created on the device.
  Recording automatically stops and finalizes when you close the scrcpy window.
""")
    if not ensure_device():
        return False

    recordings_dir = _get_recordings_dir()
    default_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_filename = f"scrcpy_rec_{default_ts}.mp4"

    name_input = ui.get_choice(f"Enter output file name [{default_filename}]").strip()
    filename = name_input if name_input else default_filename

    # Ensure valid extension
    if not (filename.endswith(".mp4") or filename.endswith(".mkv")):
        filename += ".mp4"

    full_output_path = os.path.join(recordings_dir, filename)

    print()
    ui.info(f"Target file: {full_output_path}")

    # Prompt whether to display mirrored window while recording or record silently
    show_window = ui.confirm("Display mirrored window on screen while recording?")

    model = adb.getprop("ro.product.model") or adb.serial
    title = f"DroidCommander - [RECORDING] {model}"

    args = [
        "--record", full_output_path,
        "--window-title", title,
    ]

    if not show_window:
        # Hide the video window and record headless
        args.append("--no-playback")
        ui.info("Running in background recording mode (mirror window disabled).")
        ui.info("To finish and save the recording, use 'Active Mirror Sessions Manager' to stop it.")

    ok = _launch_scrcpy_subprocess(args, label=f"Screen Recording ({filename})")
    if ok:
        print()
        ui.header("Recording In Progress:")
        ui.print_kv({
            "File": full_output_path,
            "Format": "MP4 / H.264",
            "Stop Recording": "Close the scrcpy window or terminate session",
            "Output Directory": recordings_dir,
        })
        if ui.confirm("Open output recordings folder now?"):
            _open_folder(recordings_dir)
    return ok


# ─── Feature 5: No-Audio Mode ────────────────────────────────────────────────

def launch_no_audio_mode() -> bool:
    """
    Launch scrcpy with audio forwarding explicitly disabled (--no-audio).

    Helpful for older Android devices (< Android 11), avoiding audio routing glitches,
    or minimizing CPU and bandwidth consumption.
    """
    ui.header("Launch Screen Mirror (No-Audio Mode)")
    print("""
  Disabling audio forwarding avoids audio capture latency, prevents device sound
  redirection, and is required for compatibility with Android 10 and older.
""")
    if not ensure_device():
        return False

    model = adb.getprop("ro.product.model") or adb.serial
    title = f"DroidCommander - {model} [Muted]"
    args = [
        "--no-audio",
        "--window-title", title,
    ]

    return _launch_scrcpy_subprocess(args, label=f"Screen Mirror (No Audio) [{model}]")


# ─── Feature 6: Custom Window Title ──────────────────────────────────────────

def launch_custom_title() -> bool:
    """Launch scrcpy with a user-specified desktop window title."""
    ui.header("Launch Screen Mirror (Custom Window Title)")
    print()
    if not ensure_device():
        return False

    model = adb.getprop("ro.product.model") or adb.serial
    default_title = f"DroidCommander Mirror - {model}"

    title_input = ui.get_choice(f"Enter custom window title [{default_title}]").strip()
    title = title_input if title_input else default_title

    args = ["--window-title", title]
    return _launch_scrcpy_subprocess(args, label=f"Screen Mirror ('{title}')")


# ─── Feature 7: Fullscreen Mode ──────────────────────────────────────────────

def launch_fullscreen() -> bool:
    """Launch scrcpy directly in fullscreen mode (--fullscreen / -f)."""
    ui.header("Launch Screen Mirror (Fullscreen)")
    print("""
  Launches scrcpy in borderless fullscreen mode.
  Shortcut: Press [MOD + f] or [Alt + f] at any time to toggle windowed mode.
""")
    if not ensure_device():
        return False

    model = adb.getprop("ro.product.model") or adb.serial
    title = f"DroidCommander - {model} [Fullscreen]"

    args = [
        "--fullscreen",
        "--window-title", title,
    ]

    return _launch_scrcpy_subprocess(args, label=f"Screen Mirror Fullscreen [{model}]")


# ─── Feature 8: Wireless Mirror (Wi-Fi ADB) ──────────────────────────────────

def launch_wireless_mirror() -> bool:
    """
    Configure Wi-Fi ADB and launch wireless screen mirroring without cables.

    - If device is already connected via TCP/IP, launches scrcpy directly.
    - If connected via USB, enables TCP/IP port 5555, discovers IP, connects,
      and launches scrcpy wirelessly.
    """
    ui.header("Launch Wireless Screen Mirror (Wi-Fi ADB)")
    print("""
  Mirror and control your Android device wire-free over local Wi-Fi.
  Both your computer and Android device must be on the same Wi-Fi network.
""")
    if not ensure_device():
        return False

    active_serial = adb.serial or ""

    # Check if currently connected target is already a network address (IP:Port)
    if ":" in active_serial:
        ui.info(f"Target device is already connected via Wi-Fi: {active_serial}")
        model = adb.getprop("ro.product.model") or active_serial
        title = f"DroidCommander [Wireless] - {model} ({active_serial})"
        args = ["--window-title", title]
        return _launch_scrcpy_subprocess(args, label=f"Wireless Mirror [{active_serial}]")

    # Connected via USB — perform automatic Wi-Fi setup
    ui.info(f"Current connection is via USB ({active_serial}).")
    ui.info("Setting up wireless ADB daemon (TCP/IP mode)...")

    port = "5555"
    ok_tcp, tcp_out = adb.run(["tcpip", port])
    if not ok_tcp:
        ui.error(f"Failed to switch device to TCP/IP mode: {tcp_out}")
        return False

    ui.success(f"ADB daemon switched to TCP/IP mode on port {port}.")
    time.sleep(1.0)

    # Detect device Wi-Fi IP address
    ui.info("Detecting device Wi-Fi IP address...")
    ip_addr = _get_wlan_ip()

    if not ip_addr:
        ui.warning("Could not auto-detect device Wi-Fi IP address.")
        ip_input = ui.get_choice("Enter device IP address (from Settings > About > Status)").strip()
        if not ip_input:
            ui.error("Wi-Fi IP address required to establish wireless connection.")
            return False
        ip_addr = ip_input

    endpoint = f"{ip_addr}:{port}"
    ui.info(f"Connecting to wireless endpoint: {endpoint}...")
    ok_conn, conn_out = adb.run(["connect", endpoint], timeout=15)

    if ok_conn and ("connected" in conn_out.lower() or "already connected" in conn_out.lower()):
        ui.success(f"Wireless connection established: {endpoint}")
        # Switch active serial to wireless endpoint
        adb.serial = endpoint
        ui.success(f"Active target switched to {endpoint}")
        ui.info("You may now safely unplug the USB cable if desired.")
    else:
        ui.error(f"Could not connect wirelessly to {endpoint}: {conn_out}")
        if not ui.confirm("Attempt to launch scrcpy on endpoint anyway?"):
            return False

    model = adb.getprop("ro.product.model") or endpoint
    title = f"DroidCommander [Wireless] - {model} ({endpoint})"
    args = [
        "-s", endpoint,
        "--window-title", title,
    ]

    return _launch_scrcpy_subprocess(args, label=f"Wireless Mirror [{endpoint}]")


# ─── Feature 9: Read-Only / View-Only Mode ───────────────────────────────────

def launch_read_only_mode() -> bool:
    """
    Launch scrcpy in read-only / presentation mode (--no-control).

    Disables mouse clicking, dragging, and keyboard input forwarding.
    """
    ui.header("Launch Screen Mirror (Read-Only / View-Only)")
    print("""
  In read-only mode, touch events, mouse clicks, and computer keyboard inputs
  are NOT forwarded to the Android device.
  Perfect for live streaming, demonstrations, presentations, or monitoring.
""")
    if not ensure_device():
        return False

    model = adb.getprop("ro.product.model") or adb.serial
    title = f"DroidCommander [View Only] - {model}"

    args = [
        "--no-control",
        "--window-title", title,
    ]

    return _launch_scrcpy_subprocess(args, label=f"View-Only Mirror [{model}]")


# ─── Feature 10: Screen Off on Device ────────────────────────────────────────

def launch_screen_off_mode() -> bool:
    """
    Launch scrcpy with physical device display turned off (--turn-screen-off / -S).

    Mirrors to computer while the device screen remains powered off, saving battery
    and keeping the device cool.
    """
    ui.header("Launch Screen Mirror (Device Screen Off)")
    print("""
  Powers off the physical Android screen while keeping mirroring active on PC.
  Saves battery, reduces device heat, and prevents screen burn-in.
  Shortcut: Press [MOD + Shift + o] or [Alt + Shift + o] to turn physical screen back on.
""")
    if not ensure_device():
        return False

    model = adb.getprop("ro.product.model") or adb.serial
    title = f"DroidCommander [Screen Off] - {model}"

    args = [
        "--turn-screen-off",
        "--window-title", title,
    ]

    return _launch_scrcpy_subprocess(args, label=f"Screen-Off Mirror [{model}]")


# ─── Feature 11: Show Physical Touches ───────────────────────────────────────

def launch_show_touches_mode() -> bool:
    """Launch scrcpy with touch points visualizer enabled (--show-touches / -t)."""
    ui.header("Launch Screen Mirror (Show Touches)")
    print("""
  Displays a circular visual indicator for every finger tap and swipe.
  Great for app demos, user testing, and video tutorials.
""")
    if not ensure_device():
        return False

    model = adb.getprop("ro.product.model") or adb.serial
    title = f"DroidCommander [Touches] - {model}"

    args = [
        "--show-touches",
        "--window-title", title,
    ]

    return _launch_scrcpy_subprocess(args, label=f"Show-Touches Mirror [{model}]")


# ─── Feature 12: Stay Awake Mode ─────────────────────────────────────────────

def launch_stay_awake_mode() -> bool:
    """Launch scrcpy with stay-awake enabled (--stay-awake / -w)."""
    ui.header("Launch Screen Mirror (Stay Awake)")
    print("""
  Prevents the device from sleeping while connected and mirroring.
  Restores previous sleep timeout when scrcpy is closed.
""")
    if not ensure_device():
        return False

    model = adb.getprop("ro.product.model") or adb.serial
    title = f"DroidCommander [Stay Awake] - {model}"

    args = [
        "--stay-awake",
        "--window-title", title,
    ]

    return _launch_scrcpy_subprocess(args, label=f"Stay-Awake Mirror [{model}]")


# ─── Feature 13: Advanced Multi-Option Wizard ────────────────────────────────

def launch_advanced_wizard() -> bool:
    """
    Interactive multi-option launcher wizard.

    Allows custom combining of resolution, bitrate, audio, screen state, touches,
    always-on-top, fullscreen, and recording options in one customized session.
    """
    ui.header("Advanced Screen Mirroring Wizard")
    print("""
  Configure a customized scrcpy session with your exact combination of flags.
""")
    if not ensure_device():
        return False

    extra_args: List[str] = []

    # 1. Max resolution
    ui.header("Step 1: Screen Resolution Limit")
    res_choice = ui.get_choice("Limit max size in px? (e.g. 1024, 1280, 1920, or Enter for Native)").strip()
    if res_choice.isdigit() and int(res_choice) >= 100:
        extra_args.extend(["--max-size", res_choice])
        ui.info(f"Set max resolution limit: {res_choice}px")

    # 2. Bitrate
    ui.header("Step 2: Video Bitrate")
    br_choice = ui.get_choice("Bitrate? (e.g. 2M, 4M, 8M, 16M, or Enter for 8M default)").strip()
    if br_choice:
        extra_args.extend(["-b", br_choice])
        ui.info(f"Set bitrate: {br_choice}")

    # 3. Audio Forwarding
    ui.header("Step 3: Audio Forwarding")
    if not ui.confirm("Enable audio forwarding? (Yes for sound, No for muted)"):
        extra_args.append("--no-audio")
        ui.info("Audio forwarding disabled (--no-audio).")

    # 4. Turn Screen Off
    ui.header("Step 4: Device Display Power")
    if ui.confirm("Turn physical device screen OFF while mirroring? (Saves battery)"):
        extra_args.append("--turn-screen-off")
        ui.info("Turn screen off enabled (--turn-screen-off).")

    # 5. Stay Awake
    ui.header("Step 5: Sleep Prevention")
    if ui.confirm("Keep device awake while mirroring?"):
        extra_args.append("--stay-awake")
        ui.info("Stay awake enabled (--stay-awake).")

    # 6. Show Touches
    ui.header("Step 6: Visual Touches")
    if ui.confirm("Show touch indicators on screen?"):
        extra_args.append("--show-touches")
        ui.info("Show touches enabled (--show-touches).")

    # 7. Window State
    ui.header("Step 7: Window Behavior")
    if ui.confirm("Keep scrcpy window ALWAYS ON TOP of other desktop windows?"):
        extra_args.append("--always-on-top")
        ui.info("Always on top enabled (--always-on-top).")

    if ui.confirm("Launch in FULLSCREEN mode?"):
        extra_args.append("--fullscreen")
        ui.info("Fullscreen enabled (--fullscreen).")

    # 8. Read-only
    ui.header("Step 8: Input Control")
    if ui.confirm("Enable READ-ONLY mode? (Disable mouse/touch inputs)"):
        extra_args.append("--no-control")
        ui.info("Read-only enabled (--no-control).")

    # 9. Recording
    ui.header("Step 9: Screen Recording")
    if ui.confirm("Record this session to a video file?"):
        recordings_dir = _get_recordings_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        rec_name = ui.get_choice(f"Recording filename [wizard_rec_{ts}.mp4]").strip() or f"wizard_rec_{ts}.mp4"
        if not (rec_name.endswith(".mp4") or rec_name.endswith(".mkv")):
            rec_name += ".mp4"
        rec_path = os.path.join(recordings_dir, rec_name)
        extra_args.extend(["--record", rec_path])
        ui.info(f"Recording to: {rec_path}")

    # 10. Title
    model = adb.getprop("ro.product.model") or adb.serial
    title_in = ui.get_choice(f"Window title [DroidCommander Custom - {model}]").strip()
    title = title_in if title_in else f"DroidCommander Custom - {model}"
    extra_args.extend(["--window-title", title])

    print()
    ui.header("Wizard Configuration Summary:")
    print(f"  Flags: {ui.Colors.CYAN}{' '.join(extra_args)}{ui.Colors.RESET}")
    print()

    if not ui.confirm("Launch customized scrcpy session now?"):
        ui.info("Launch cancelled.")
        return False

    return _launch_scrcpy_subprocess(extra_args, label=f"Custom Wizard Session [{model}]")


# ─── Feature 14: Keyboard Shortcuts & Gesture Reference ──────────────────────

def show_shortcuts_reference() -> None:
    """Display comprehensive reference card for scrcpy keyboard shortcuts and gestures."""
    ui.header("scrcpy Keyboard Shortcuts & Controls Reference")
    print(f"""
  {ui.Colors.CYAN}{ui.Colors.BOLD}Modifier Key (MOD):{ui.Colors.RESET}
    • On Windows & Linux: {ui.Colors.YELLOW}Left Alt{ui.Colors.RESET} (default)
    • On macOS:           {ui.Colors.YELLOW}Command (⌘){ui.Colors.RESET} or {ui.Colors.YELLOW}Left Alt{ui.Colors.RESET}
""")

    sections = [
        (
            "Window & Display Management",
            [
                ("MOD + f", "Toggle Fullscreen mode"),
                ("MOD + g", "Resize window to 1:1 pixel-perfect scale"),
                ("MOD + w", "Resize window to tightly fit content (remove black borders)"),
                ("MOD + Left / Right", "Rotate display counter-clockwise / clockwise (PC window)"),
            ]
        ),
        (
            "Device Navigation & Physical Buttons",
            [
                ("MOD + h  /  Middle-click", "Home button"),
                ("MOD + b  /  Right-click",  "Back button (or turns screen on if off)"),
                ("MOD + s",                 "App Switcher / Recent Apps overview"),
                ("MOD + m",                 "Menu button"),
                ("MOD + p",                 "Power button (short press = sleep / wake)"),
                ("MOD + Up / Down",         "Volume Up / Volume Down"),
            ]
        ),
        (
            "Display State & Hardware Control",
            [
                ("MOD + o",                 "Turn device physical screen OFF (mirroring stays on)"),
                ("MOD + Shift + o",         "Turn device physical screen back ON"),
                ("MOD + r",                 "Rotate physical device orientation"),
            ]
        ),
        (
            "Clipboard & Text Input",
            [
                ("MOD + c",                 "Copy device clipboard to computer clipboard"),
                ("MOD + v",                 "Paste computer clipboard to device"),
                ("MOD + Shift + v",         "Inject computer clipboard as raw keyboard key events"),
            ]
        ),
        (
            "Notifications & Diagnostics",
            [
                ("MOD + n",                 "Expand notification shade"),
                ("MOD + Shift + n",         "Collapse notification shade"),
                ("MOD + i",                 "Toggle real-time FPS counter in terminal / title"),
            ]
        ),
        (
            "Mouse & Drag-and-Drop Actions",
            [
                ("Drag & drop .APK file",   "Automatically installs the APK onto the device"),
                ("Drag & drop any file",    "Pushes file directly to /sdcard/Download/ on device"),
                ("Pinch-to-zoom",           "Hold Ctrl + Left Click and drag mouse"),
            ]
        ),
    ]

    for title, rows in sections:
        headers = ("Key / Gesture", "Action / Behavior")
        table_rows = [(f"{ui.Colors.YELLOW}{k}{ui.Colors.RESET}", desc) for k, desc in rows]
        print(f"  {ui.Colors.CYAN}{ui.Colors.BOLD}── {title} ──{ui.Colors.RESET}")
        ui.print_table(table_rows, headers, indent=4)
        print()

    ui.info("All shortcuts function while the scrcpy mirrored window is focused.")


# ─── Feature 15: Active Sessions Manager ─────────────────────────────────────

def manage_active_sessions() -> None:
    """View and manage background scrcpy processes spawned by DroidCommander."""
    ui.header("Active Mirror Sessions Manager")
    print()
    _clean_sessions()

    if not _ACTIVE_SESSIONS:
        ui.info("No active or recent scrcpy sessions recorded in this program run.")
        return

    headers = ("#", "PID", "Status", "Started", "Target Device", "Session Label")
    table_rows = []
    for idx, sess in enumerate(_ACTIVE_SESSIONS, 1):
        proc: subprocess.Popen = sess["proc"]
        is_running = proc.poll() is None
        status_color = f"{ui.Colors.GREEN}Running{ui.Colors.RESET}" if is_running else f"{ui.Colors.DIM}Exited{ui.Colors.RESET}"
        table_rows.append((
            str(idx),
            str(sess["pid"]),
            status_color,
            sess["start_time"],
            sess.get("serial", "—"),
            sess["label"],
        ))

    ui.print_table(table_rows, headers, indent=4)
    print()

    print(f"  {ui.Colors.CYAN}Options:{ui.Colors.RESET}")
    print(f"    {ui.Colors.YELLOW}[1]{ui.Colors.RESET} Terminate a specific session by #")
    print(f"    {ui.Colors.YELLOW}[2]{ui.Colors.RESET} Terminate ALL running scrcpy sessions")
    print(f"    {ui.Colors.YELLOW}[3]{ui.Colors.RESET} View log of a specific session")
    print(f"    {ui.Colors.YELLOW}[4]{ui.Colors.RESET} Open captures & recordings folder")
    print(f"    {ui.Colors.YELLOW}[0]{ui.Colors.RESET} Return to menu")
    print()

    sub_choice = ui.get_choice("Select action")

    if sub_choice == "1":
        sess_num = ui.get_choice("Enter session # to terminate").strip()
        if sess_num.isdigit() and 1 <= int(sess_num) <= len(_ACTIVE_SESSIONS):
            sess = _ACTIVE_SESSIONS[int(sess_num) - 1]
            proc: subprocess.Popen = sess["proc"]
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except Exception:
                    proc.kill()
                ui.success(f"Terminated session #{sess_num} (PID: {sess['pid']}).")
            else:
                ui.info(f"Session #{sess_num} was already terminated.")
        else:
            ui.error("Invalid session number.")

    elif sub_choice == "2":
        if ui.confirm("Are you sure you want to terminate all active scrcpy sessions?"):
            killed = 0
            for sess in _ACTIVE_SESSIONS:
                proc = sess["proc"]
                if proc.poll() is None:
                    proc.terminate()
                    killed += 1
            ui.success(f"Terminated {killed} running scrcpy session(s).")

    elif sub_choice == "3":
        sess_num = ui.get_choice("Enter session # to view log").strip()
        if sess_num.isdigit() and 1 <= int(sess_num) <= len(_ACTIVE_SESSIONS):
            sess = _ACTIVE_SESSIONS[int(sess_num) - 1]
            log_path = sess.get("log_path", "")
            if log_path and os.path.isfile(log_path):
                ui.header(f"Log content for session #{sess_num}:")
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                        if lines:
                            for l in lines[-30:]:
                                print(f"    {ui.Colors.DIM}{l.rstrip()}{ui.Colors.RESET}")
                        else:
                            ui.info("Log file is currently empty.")
                except Exception as exc:
                    ui.error(f"Failed to read log: {exc}")
            else:
                ui.warning("No log file found for this session.")
        else:
            ui.error("Invalid session number.")

    elif sub_choice == "4":
        _open_folder(_get_recordings_dir())


# ─── Feature 16: Open scrcpy Download & Releases Page ────────────────────────

def open_download_page() -> None:
    """Open the official scrcpy GitHub releases page in the default web browser."""
    ui.header("Open scrcpy Releases & Downloads")
    print(f"""
  Official GitHub Repository: {ui.Colors.CYAN}{SCRCPY_GITHUB_URL}{ui.Colors.RESET}
  Releases & Binaries:       {ui.Colors.CYAN}{SCRCPY_DOWNLOAD_URL}{ui.Colors.RESET}
  Full Documentation:        {ui.Colors.CYAN}{SCRCPY_DOCS_URL}{ui.Colors.RESET}
""")
    try:
        webbrowser.open(SCRCPY_DOWNLOAD_URL)
        ui.success("Opened scrcpy download page in your default browser.")
    except Exception as exc:
        ui.error(f"Could not launch web browser: {exc}")
        ui.info(f"Please visit the URL manually: {SCRCPY_DOWNLOAD_URL}")


# ─── Main Menu Entry Point ───────────────────────────────────────────────────

def screen_mirror_menu() -> None:
    """Public entry function and interactive loop for the Screen Mirroring module."""
    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Screen Mirroring & scrcpy", icon="🖥️")

        # Show device and scrcpy status
        scrcpy_ready = is_scrcpy_installed()
        status_tag = f"{ui.Colors.GREEN}Ready{ui.Colors.RESET}" if scrcpy_ready else f"{ui.Colors.RED}scrcpy Missing{ui.Colors.RESET}"
        dev_tag = f"{ui.Colors.GREEN}{adb.serial}{ui.Colors.RESET}" if adb.serial else f"{ui.Colors.YELLOW}No device selected{ui.Colors.RESET}"

        print(f"  {ui.Colors.DIM}Target Device:{ui.Colors.RESET} {dev_tag}  │  {ui.Colors.DIM}scrcpy Engine:{ui.Colors.RESET} {status_tag}")

        options = [
            "Check scrcpy Installation & Status",
            "Launch Screen Mirror (Default)",
            "Launch with Custom Resolution",
            "Launch with Custom Bitrate",
            "Launch in Record Mode (Save to MP4)",
            "Launch No-Audio Mode (Muted)",
            "Launch with Custom Window Title",
            "Launch in Fullscreen Mode",
            "Launch Wireless Mirror (Wi-Fi ADB)",
            "Launch Read-Only / View-Only Mode",
            "Launch with Device Screen Off",
            "Launch with Show Touches Enabled",
            "Launch with Stay Awake Enabled",
            "Advanced Mirroring Wizard (Custom Flags)",
            "Keyboard Shortcuts & Gesture Reference",
            "Active Mirror Sessions Manager",
            "Open scrcpy Download & Releases Page",
        ]

        ui.print_menu("Screen Mirroring Operations", options, columns=2)
        choice = ui.get_choice()

        if choice == "0":
            break
        elif choice == "1":
            check_scrcpy_status()
        elif choice == "2":
            launch_default_mirror()
        elif choice == "3":
            launch_custom_resolution()
        elif choice == "4":
            launch_custom_bitrate()
        elif choice == "5":
            launch_record_mode()
        elif choice == "6":
            launch_no_audio_mode()
        elif choice == "7":
            launch_custom_title()
        elif choice == "8":
            launch_fullscreen()
        elif choice == "9":
            launch_wireless_mirror()
        elif choice == "10":
            launch_read_only_mode()
        elif choice == "11":
            launch_screen_off_mode()
        elif choice == "12":
            launch_show_touches_mode()
        elif choice == "13":
            launch_stay_awake_mode()
        elif choice == "14":
            launch_advanced_wizard()
        elif choice == "15":
            show_shortcuts_reference()
        elif choice == "16":
            manage_active_sessions()
        elif choice == "17":
            open_download_page()
        else:
            ui.error("Invalid option. Please choose a valid number from the menu.")

        ui.pause()
