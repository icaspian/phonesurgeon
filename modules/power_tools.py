"""
modules/power_tools.py — Advanced Power Tools & System Tweaks for DroidCommander.

A feature-rich power-user module providing 15 deep system diagnostics and modification tools:
1. View Saved Wi-Fi Passwords (Root required with configuration parser and export)
2. GPS Mock Location & Coordinate Spoofing (Presets, manual lat/lon, AppOps management)
3. Port Forwarding (adb forward — list, add, presets, remove)
4. Reverse Port Forwarding (adb reverse — dev server mapping, host socket probe)
5. Battery Optimization & Process Killer (Dumpsys batterystats analysis & simulation)
6. Bloatware Manager (Freeze/unfreeze, user-0 debloat, OEM bloatware database scanner)
7. OTA Sideload Guide & Package Installer (Recovery & sideload workflow)
8. App Data Backup & Restore (.ab archive extraction and packaging)
9. Grant / Revoke Runtime Permissions (Interactive viewer, batch grant, appops)
10. Change Device DPI (wm density with presets and safe restoration)
11. Change Screen Resolution (wm size with downscaling & aspect presets)
12. System Animation Overrides (Instant 0x, snappy 0.5x, slow-mo 10x)
13. Force Dark Mode & HWUI Force-Dark Override
14. Wake Lock Inspector (dumpsys power active locks & suspend blockers)
15. Doze Mode Control & Battery Optimization Whitelist
"""

from datetime import datetime
import os
import re
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import xml.etree.ElementTree as ET

from core.adb import adb
from core import ui
from core.device import ensure_device


# ─── Low-Level Shell Execution Helpers ───────────────────────────────────────

def _run_raw_shell(cmd_str: str, timeout: int = 30) -> Tuple[bool, str]:
    """
    Execute a shell command through `sh -c` to ensure quotes, pipelines,
    and redirections are preserved correctly across ADB.
    """
    return adb.run(["shell", "sh", "-c", cmd_str], timeout=timeout)


def _check_root_status() -> Tuple[bool, str]:
    """
    Determine if root access is available on the connected device.

    Returns
    -------
    Tuple[bool, str]
        (is_rooted, explanation_message)
    """
    # Test 1: Direct su command execution
    ok, out = _run_raw_shell("su -c id", timeout=6)
    if ok and "uid=0" in out.lower():
        return True, "Root access confirmed via su binary (uid=0)."

    # Test 2: Check if adbd itself runs as root (eng / userdebug build)
    ok, out = adb.run(["shell", "id"], timeout=5)
    if ok and "uid=0" in out.lower():
        return True, "Device adbd daemon is running natively as root (uid=0)."

    # Test 3: Attempt switching adbd to root mode
    ok, out = adb.run(["root"], timeout=8)
    if ok and ("restarting adbd as root" in out.lower() or "already running as root" in out.lower()):
        time.sleep(1.5)
        ok_verify, out_verify = adb.run(["shell", "id"], timeout=5)
        if ok_verify and "uid=0" in out_verify.lower():
            return True, "Root access enabled via 'adb root'."

    return False, "Device is not rooted or root access was denied by superuser manager."


def _get_installed_packages(filter_flag: str = "") -> List[str]:
    """
    Fetch sorted list of package names from device.

    Parameters
    ----------
    filter_flag : str
        Optional filter flag for `pm list packages` ('-3', '-s', '-d', '-e').
    """
    args = ["shell", "pm", "list", "packages"]
    if filter_flag:
        args.append(filter_flag)

    ok, output = adb.run(args, timeout=20)
    if not ok or not output:
        return []

    packages: List[str] = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            pkg = line.replace("package:", "").strip()
            if pkg:
                packages.append(pkg)

    return sorted(packages)


def _select_or_search_package(prompt: str = "Enter package name") -> Optional[str]:
    """
    Prompt user for a package name with interactive search fallback.
    Typing '?' or 's' triggers an interactive package search filter.
    """
    ui.info(f"{prompt} (or enter {ui.Colors.YELLOW}'?'{ui.Colors.CYAN} to search installed apps):{ui.Colors.RESET}")
    val = ui.get_choice(prompt)

    if not val:
        return None

    if val in ("?", "s", "search", "/"):
        query = ui.get_choice("Enter keyword to search installed packages")
        if not query:
            return None

        all_pkgs = _get_installed_packages()
        matches = [p for p in all_pkgs if query.lower() in p.lower()]

        if not matches:
            ui.warning(f"No packages found matching '{query}'.")
            return None

        ui.header(f"Matching Packages ({len(matches)} found, showing up to 30):")
        print()
        for idx, pkg in enumerate(matches[:30], 1):
            print(f"  {ui.Colors.YELLOW}[{idx:>2}]{ui.Colors.RESET} {pkg}")
        print()

        sel = ui.get_choice("Select package number (or 0 to cancel)")
        try:
            sel_idx = int(sel) - 1
            if 0 <= sel_idx < min(len(matches), 30):
                chosen = matches[sel_idx]
                ui.success(f"Selected: {chosen}")
                return chosen
        except ValueError:
            pass

        ui.error("Invalid selection.")
        return None

    return val


def _ensure_dir(dir_path: str) -> str:
    """Ensure directory exists and return canonical path."""
    os.makedirs(dir_path, exist_ok=True)
    return dir_path


# ─── Feature 1: View Saved Wi-Fi Passwords ───────────────────────────────────

def _parse_wifi_config_store(xml_content: str) -> List[Dict[str, str]]:
    """
    Parse Android WifiConfigStore.xml configuration and extract saved networks.
    Supports both Android 8-10 and Android 11+ APEX structures.
    """
    networks: List[Dict[str, str]] = []

    # First attempt: XML DOM parsing
    try:
        root = ET.fromstring(xml_content)
        # Traverse for Network or WifiConfiguration tags
        for net_elem in root.findall(".//Network"):
            config = net_elem.find("WifiConfiguration")
            if config is None:
                config = net_elem

            ssid = ""
            psk = ""
            key_mgmt = "WPA_PSK"
            hidden = "false"

            for s in config.findall("string"):
                name = s.attrib.get("name", "")
                val = (s.text or "").strip()
                # Remove wrapping quotes
                if val.startswith("&quot;") and val.endswith("&quot;"):
                    val = val[6:-6]
                elif val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]

                if name == "SSID":
                    ssid = val
                elif name == "PreSharedKey":
                    psk = val
                elif name == "ConfigKey":
                    if "WPA_PSK" in val:
                        key_mgmt = "WPA/WPA2-PSK"
                    elif "SAE" in val:
                        key_mgmt = "WPA3-SAE"
                    elif "NONE" in val or "open" in val.lower():
                        key_mgmt = "OPEN"
                    elif "WEP" in val:
                        key_mgmt = "WEP"
                    elif "EAP" in val:
                        key_mgmt = "802.1x EAP"

            for b in config.findall("boolean"):
                name = b.attrib.get("name", "")
                val = b.attrib.get("value", "false")
                if name == "HiddenSSID":
                    hidden = val

            if ssid:
                networks.append({
                    "ssid": ssid,
                    "psk": psk if psk else "(None / Open)",
                    "security": key_mgmt,
                    "hidden": "Yes" if hidden.lower() == "true" else "No",
                })
        if networks:
            return networks
    except Exception:
        pass

    # Fallback: Regex extraction across raw text
    net_blocks = re.findall(r"<Network>(.*?)</Network>", xml_content, re.DOTALL)
    for block in net_blocks:
        ssid_match = re.search(r'<string name="SSID">"?(.*?)"?</string>', block)
        psk_match = re.search(r'<string name="PreSharedKey">"?(.*?)"?</string>', block)
        config_key = re.search(r'<string name="ConfigKey">"?(.*?)"?</string>', block)
        hidden_match = re.search(r'<boolean name="HiddenSSID" value="([a-zA-Z]+)"', block)

        if ssid_match:
            ssid = ssid_match.group(1).replace("&quot;", '"').strip('"')
            psk = psk_match.group(1).replace("&quot;", '"').strip('"') if psk_match else "(None / Open)"
            cfg = config_key.group(1) if config_key else ""
            hidden = hidden_match.group(1) if hidden_match else "false"

            sec = "WPA/WPA2-PSK"
            if "SAE" in cfg:
                sec = "WPA3-SAE"
            elif "NONE" in cfg:
                sec = "OPEN"
            elif "WEP" in cfg:
                sec = "WEP"

            networks.append({
                "ssid": ssid,
                "psk": psk,
                "security": sec,
                "hidden": "Yes" if hidden.lower() == "true" else "No",
            })

    return networks


def _parse_wpa_supplicant(conf_content: str) -> List[Dict[str, str]]:
    """Parse legacy wpa_supplicant.conf network blocks."""
    networks: List[Dict[str, str]] = []
    blocks = re.findall(r"network=\{([^\}]+)\}", conf_content)

    for block in blocks:
        ssid_m = re.search(r'ssid="([^"]+)"', block)
        psk_m = re.search(r'psk="([^"]+)"', block)
        key_m = re.search(r"key_mgmt=([^\n]+)", block)

        if ssid_m:
            ssid = ssid_m.group(1)
            psk = psk_m.group(1) if psk_m else "(None / Open)"
            sec = key_m.group(1).strip() if key_m else "WPA-PSK"
            networks.append({
                "ssid": ssid,
                "psk": psk,
                "security": sec,
                "hidden": "No",
            })

    return networks


def view_saved_wifi_passwords():
    """
    Extract and display saved Wi-Fi network credentials from protected storage.
    Requires root access. Provides detailed diagnostic fallback if unrooted.
    """
    if not ensure_device():
        return

    ui.header("Saved Wi-Fi Passwords Viewer (Root Required)")
    ui.info("Verifying root privileges on device...")

    is_rooted, root_msg = _check_root_status()
    if not is_rooted:
        ui.error("ROOT ACCESS REQUIRED")
        print()
        ui.warning("Wi-Fi credentials (WPA/WPA2/WPA3 pre-shared keys) are stored in secure")
        ui.warning("system directories with permission 0700, readable only by UID 0 (root)")
        ui.warning("and UID 1010 (wifi). The standard ADB unprivileged shell cannot read them.")
        print()
        ui.print_kv({
            "Status": "Permission Denied (UID 2000 / shell)",
            "Reason": root_msg,
            "Target Path": "/data/misc/wifi/WifiConfigStore.xml",
            "Remedy 1": "Root device using Magisk, KernelSU, or APatch",
            "Remedy 2": "If using an Android emulator, launch with root (adb root)",
            "Remedy 3": "On Android 10+, view Wi-Fi QR Code in Settings > Wi-Fi > Share",
        })
        print()

        if ui.confirm("Show current active Wi-Fi connection info via unprivileged status?"):
            ok_wifi, wifi_out = adb.run(["shell", "dumpsys", "wifi"], timeout=10)
            if ok_wifi and wifi_out:
                ui.header("Active Wi-Fi Diagnostics (Unprivileged):")
                relevant = []
                for line in wifi_out.splitlines():
                    if any(k in line for k in ("mWifiInfo", "curState", "SSID", "BSSID", "MAC:", "link speed", "frequency")):
                        relevant.append(line.strip())
                if relevant:
                    for line in relevant[:15]:
                        print(f"    {ui.Colors.DIM}•{ui.Colors.RESET} {line}")
                else:
                    ui.info("No active Wi-Fi connection detected or dumpsys output suppressed.")
        return

    ui.success(root_msg)
    ui.info("Querying system Wi-Fi storage configuration files...")

    # Known candidate paths in order of Android version prevalence
    candidate_paths = [
        "/data/misc/apexdata/com.android.wifi/WifiConfigStore.xml",  # Android 11, 12, 13, 14
        "/data/misc/wifi/WifiConfigStore.xml",                      # Android 8, 9, 10
        "/data/misc/wifi/wpa_supplicant.conf",                      # Android 7 and legacy
        "/data/wifi/bcm_supp.conf",                                 # Broadcom legacy
    ]

    raw_data = ""
    used_path = ""
    is_xml = True

    for p in candidate_paths:
        ok, out = _run_raw_shell(f"su -c 'cat {p} 2>/dev/null'", timeout=8)
        if ok and len(out.strip()) > 30:
            raw_data = out.strip()
            used_path = p
            is_xml = p.endswith(".xml")
            break

    if not raw_data:
        ui.error("Could not read Wi-Fi configuration files. Paths may be encrypted or empty.")
        return

    ui.info(f"Loaded credentials archive from: {used_path}")

    networks = _parse_wifi_config_store(raw_data) if is_xml else _parse_wpa_supplicant(raw_data)

    if not networks:
        ui.warning("Configuration file found but contains no saved Wi-Fi networks.")
        return

    ui.success(f"Successfully retrieved {len(networks)} saved Wi-Fi network(s)!")
    print()

    headers = ("#", "SSID (Network Name)", "Password / Pre-Shared Key", "Security", "Hidden")
    rows = []
    for idx, net in enumerate(networks, 1):
        pwd_display = net["psk"]
        if pwd_display == "(None / Open)":
            pwd_styled = f"{ui.Colors.DIM}{pwd_display}{ui.Colors.RESET}"
        else:
            pwd_styled = f"{ui.Colors.GREEN}{pwd_display}{ui.Colors.RESET}"

        rows.append((
            str(idx),
            net["ssid"],
            pwd_styled,
            net["security"],
            net["hidden"],
        ))

    ui.print_table(rows, headers)
    print()

    # Offer export functionality
    if ui.confirm("Export saved Wi-Fi passwords to a text file on PC?"):
        export_dir = _ensure_dir("exports")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        serial_clean = (adb.serial or "device").replace(":", "_").replace(".", "_")
        filename = f"wifi_passwords_{serial_clean}_{ts}.txt"
        filepath = os.path.join(export_dir, filename)

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"=== DroidCommander Saved Wi-Fi Passwords Export ===\n")
                f.write(f"Device Serial: {adb.serial}\n")
                f.write(f"Source Path:   {used_path}\n")
                f.write(f"Export Date:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Total Networks: {len(networks)}\n")
                f.write("=" * 60 + "\n\n")

                for idx, net in enumerate(networks, 1):
                    f.write(f"[{idx}] SSID:     {net['ssid']}\n")
                    f.write(f"    Password: {net['psk']}\n")
                    f.write(f"    Security: {net['security']}\n")
                    f.write(f"    Hidden:   {net['hidden']}\n\n")

            ui.success(f"Credentials exported to: {filepath}")
        except Exception as e:
            ui.error(f"Failed to write export file: {e}")


# ─── Feature 2: GPS Mock Location & Spoofing ─────────────────────────────────

# Common global coordinates presets
MOCK_GPS_PRESETS = [
    ("New York City, USA", 40.712776, -74.005974, 10.0),
    ("London, UK", 51.507351, -0.127758, 15.0),
    ("Tokyo, Japan", 35.676192, 139.650311, 40.0),
    ("Paris, France", 48.856614, 2.352222, 35.0),
    ("San Francisco, USA", 37.774929, -122.419416, 16.0),
    ("Sydney, Australia", -33.868820, 151.209296, 5.0),
    ("Singapore", 1.352083, 103.819836, 15.0),
    ("Dubai, UAE", 25.204849, 55.270783, 5.0),
    ("Berlin, Germany", 52.520008, 13.404954, 34.0),
    ("Rio de Janeiro, Brazil", -22.906847, -43.172896, 2.0),
    ("Cairo, Egypt", 30.044420, 31.235712, 23.0),
    ("Bermuda Triangle", 25.000000, -71.000000, 0.0),
]


def _set_mock_location_coordinates(lat: float, lon: float, alt: float = 10.0):
    """
    Inject mock GPS coordinates into system location provider.
    Enables secure settings mock_location flag and sends test provider updates.
    """
    ui.info(f"Injecting Coordinates: Lat={lat}, Lon={lon}, Alt={alt}m...")

    # Enable mock location setting flag
    adb.run(["shell", "settings", "put", "secure", "mock_location", "1"])

    # Modern Android 10+ command location set-test-provider
    adb.run(["shell", "cmd", "location", "set-test-provider-enabled", "gps", "true"])
    adb.run(["shell", "cmd", "location", "set-test-provider-location", "gps",
             "--location", f"{lat},{lon}", "--accuracy", "3.0", "--altitude", f"{alt}"])

    # Fallback to network provider mock injection as well
    adb.run(["shell", "cmd", "location", "set-test-provider-enabled", "network", "true"])
    adb.run(["shell", "cmd", "location", "set-test-provider-location", "network",
             "--location", f"{lat},{lon}", "--accuracy", "5.0"])

    # Broadcast location intent for compatible mock receiver apps
    adb.run(["shell", "am", "broadcast", "-a", "com.android.location.MOCK_LOCATION",
             "--ef", "lat", str(lat), "--ef", "lon", str(lon), "--ef", "alt", str(alt)])

    ui.success(f"GPS Mock Location broadcast complete: {lat:.6f}, {lon:.6f}")
    ui.info("Note: Location-dependent apps and maps will observe this mock position.")


def gps_mock_location_tool():
    """Manage mock location permissions, presets, and coordinate injection."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("GPS Mock Location & Coordinate Spoofing", "📍")
        ui.print_device_status(adb.serial)

        # Check current mock location settings
        ok_mock, mock_val = adb.run(["shell", "settings", "get", "secure", "mock_location"])
        current_status = "Enabled (1)" if (ok_mock and mock_val.strip() == "1") else "Disabled (0)"
        ui.info(f"Mock Location Setting: {current_status}")

        options = [
            "Select Global City Location Preset",
            "Enter Custom Coordinates (Latitude / Longitude)",
            "Grant Mock Location AppOp to an App",
            "Revoke Mock Location AppOp from an App",
            "Check Current Mock Location App Assignment",
            "Inspect Live Location Provider Status (dumpsys)",
            "Disable & Reset Mock Location Mode",
        ]

        ui.print_menu("GPS Mock Location Menu", options)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            ui.header("Select Geographic Preset:")
            print()
            headers = ("#", "Location Name", "Latitude", "Longitude", "Altitude")
            rows = []
            for i, (name, lat, lon, alt) in enumerate(MOCK_GPS_PRESETS, 1):
                rows.append((str(i), name, f"{lat:.6f}", f"{lon:.6f}", f"{alt:.1f}m"))
            ui.print_table(rows, headers)
            print()

            sel = ui.get_choice("Select preset number (or 0 to cancel)")
            try:
                idx = int(sel) - 1
                if 0 <= idx < len(MOCK_GPS_PRESETS):
                    name, lat, lon, alt = MOCK_GPS_PRESETS[idx]
                    ui.info(f"Targeting: {name}")
                    _set_mock_location_coordinates(lat, lon, alt)
                else:
                    ui.error("Invalid preset number.")
            except ValueError:
                ui.error("Invalid input.")
            ui.pause()

        elif choice == "2":
            ui.header("Custom GPS Coordinate Input")
            lat_str = ui.get_choice("Enter Latitude (-90.0 to 90.0)")
            lon_str = ui.get_choice("Enter Longitude (-180.0 to 180.0)")
            alt_str = ui.get_choice("Enter Altitude in meters (default 10.0)") or "10.0"

            try:
                lat = float(lat_str)
                lon = float(lon_str)
                alt = float(alt_str)

                if not (-90.0 <= lat <= 90.0):
                    ui.error("Latitude out of range [-90, 90].")
                elif not (-180.0 <= lon <= 180.0):
                    ui.error("Longitude out of range [-180, 180].")
                else:
                    _set_mock_location_coordinates(lat, lon, alt)
            except ValueError:
                ui.error("Latitude and Longitude must be valid numbers.")
            ui.pause()

        elif choice == "3":
            ui.header("Grant Mock Location AppOp (android:mock_location allow)")
            pkg = _select_or_search_package("Enter package to grant mock location permission")
            if pkg:
                ok, out = adb.run(["shell", "appops", "set", pkg, "android:mock_location", "allow"])
                if ok:
                    ui.success(f"AppOp 'android:mock_location allow' granted to: {pkg}")
                    ui.info("You can now designate this application as the Mock Location app in Developer Options.")
                else:
                    ui.error(f"Failed to grant AppOp: {out}")
            ui.pause()

        elif choice == "4":
            ui.header("Revoke Mock Location AppOp (android:mock_location deny)")
            pkg = _select_or_search_package("Enter package to revoke mock location permission")
            if pkg:
                ok, out = adb.run(["shell", "appops", "set", pkg, "android:mock_location", "deny"])
                if ok:
                    ui.success(f"AppOp 'android:mock_location deny' applied to: {pkg}")
                else:
                    ui.error(f"Failed to revoke AppOp: {out}")
            ui.pause()

        elif choice == "5":
            ui.header("Current Mock Location Setting & AppOps Query")
            ok, out = adb.run(["shell", "appops", "query-op", "android:mock_location", "allow"])
            if ok and out:
                ui.info("Apps with active android:mock_location permission:")
                print(f"\n{out}\n")
            else:
                ui.info("No applications currently holding explicit 'allow' for android:mock_location.")
            ui.pause()

        elif choice == "6":
            ui.header("Dumpsys Location Status (Summary):")
            ok, out = adb.run(["shell", "dumpsys", "location"], timeout=10)
            if ok and out:
                lines = [l.strip() for l in out.splitlines() if any(k in l for k in ("Last Known Locations:", "Geofences:", "mLocation", "gps provider", "test provider"))]
                for l in lines[:20]:
                    print(f"    {ui.Colors.CYAN}•{ui.Colors.RESET} {l}")
            else:
                ui.warning("Location service dumpsys not available.")
            ui.pause()

        elif choice == "7":
            ui.header("Reset Mock Location Settings")
            adb.run(["shell", "cmd", "location", "set-test-provider-enabled", "gps", "false"])
            adb.run(["shell", "cmd", "location", "set-test-provider-enabled", "network", "false"])
            adb.run(["shell", "settings", "put", "secure", "mock_location", "0"])
            ui.success("Mock location test providers disabled and secure setting reset to 0.")
            ui.pause()


# ─── Feature 3: Port Forwarding (adb forward) ────────────────────────────────

def _list_port_forwards() -> List[Tuple[str, str, str]]:
    """Query `adb forward --list` and return list of (serial, local_spec, remote_spec)."""
    ok, out = adb.run(["forward", "--list"], timeout=10)
    if not ok or not out:
        return []

    results = []
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3:
            results.append((parts[0], parts[1], parts[2]))
    return results


def port_forwarding_manager():
    """Manage ADB port forwards (forwarding host ports to device sockets)."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Port Forwarding (ADB Forward: PC -> Device)", "🔀")
        ui.print_device_status(adb.serial)

        forwards = _list_port_forwards()
        ui.header(f"Active Port Forwards ({len(forwards)} active):")
        print()

        if forwards:
            headers = ("#", "Device Serial", "Host Local Port", "Device Remote Port / Socket")
            rows = [(str(i), f[0], f[1], f[2]) for i, f in enumerate(forwards, 1)]
            ui.print_table(rows, headers)
        else:
            ui.info("No active port forwards.")
        print()

        options = [
            "Add Custom Port Forward (tcp:local -> tcp:remote)",
            "Preset: Chrome DevTools Web Inspection (tcp:9222 -> tcp:9222)",
            "Preset: Web Development Server (tcp:8080 -> tcp:8080)",
            "Preset: Node / Vite Dev Server (tcp:3000 -> tcp:3000)",
            "Preset: Wireless ADB Daemon (tcp:5555 -> tcp:5555)",
            "Forward Host TCP to Device Local Abstract Socket",
            "Remove a Specific Port Forward",
            "Remove ALL Active Port Forwards",
        ]

        ui.print_menu("Port Forwarding Actions", options)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            local_p = ui.get_choice("Enter Host PC Local Port (e.g. 8080)")
            remote_p = ui.get_choice("Enter Device Remote Port (e.g. 8080)")
            if local_p.isdigit() and remote_p.isdigit():
                ok, out = adb.run(["forward", f"tcp:{local_p}", f"tcp:{remote_p}"])
                if ok:
                    ui.success(f"Port forward created: 127.0.0.1:{local_p} -> device port {remote_p}")
                else:
                    ui.error(f"Forward failed: {out}")
            else:
                ui.error("Ports must be numeric values.")
            ui.pause()

        elif choice == "2":
            ok, out = adb.run(["forward", "tcp:9222", "tcp:9222"])
            if ok:
                ui.success("Chrome DevTools forward established on tcp:9222.")
                ui.info("Open 'chrome://inspect' on your desktop browser to inspect remote WebView/Tabs.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "3":
            ok, out = adb.run(["forward", "tcp:8080", "tcp:8080"])
            if ok:
                ui.success("Forward created: tcp:8080 -> tcp:8080.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "4":
            ok, out = adb.run(["forward", "tcp:3000", "tcp:3000"])
            if ok:
                ui.success("Forward created: tcp:3000 -> tcp:3000.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "5":
            ok, out = adb.run(["forward", "tcp:5555", "tcp:5555"])
            if ok:
                ui.success("Forward created: tcp:5555 -> tcp:5555.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "6":
            local_p = ui.get_choice("Enter Host Local TCP Port (e.g. 9999)")
            socket_name = ui.get_choice("Enter Device Local Abstract Socket name (e.g. chrome_devtools_remote)")
            if local_p.isdigit() and socket_name:
                ok, out = adb.run(["forward", f"tcp:{local_p}", f"localabstract:{socket_name}"])
                if ok:
                    ui.success(f"Forward created: tcp:{local_p} -> localabstract:{socket_name}")
                else:
                    ui.error(f"Failed: {out}")
            else:
                ui.error("Invalid port or socket name.")
            ui.pause()

        elif choice == "7":
            if not forwards:
                ui.warning("No port forwards to remove.")
                ui.pause()
                continue
            port_to_rem = ui.get_choice("Enter Host Port to remove (e.g. 8080)")
            clean_port = port_to_rem.replace("tcp:", "").strip()
            ok, out = adb.run(["forward", "--remove", f"tcp:{clean_port}"])
            if ok:
                ui.success(f"Removed port forward tcp:{clean_port}.")
            else:
                ui.error(f"Failed to remove: {out}")
            ui.pause()

        elif choice == "8":
            if ui.confirm("Remove ALL active port forwards?"):
                ok, out = adb.run(["forward", "--remove-all"])
                if ok:
                    ui.success("All port forwards cleared.")
                else:
                    ui.error(f"Failed: {out}")
            ui.pause()


# ─── Feature 4: Reverse Port Forwarding (adb reverse) ────────────────────────

def _list_reverse_forwards() -> List[Tuple[str, str, str]]:
    """Query `adb reverse --list` and return list of (serial, remote_spec, local_spec)."""
    ok, out = adb.run(["reverse", "--list"], timeout=10)
    if not ok or not out:
        return []

    results = []
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3:
            results.append((parts[0], parts[1], parts[2]))
    return results


def _is_host_port_listening(port: int) -> bool:
    """Test if a TCP port is currently open and listening on the host PC (127.0.0.1)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def reverse_port_forwarding_manager():
    """Manage reverse port forwards (enables device to access dev servers on PC)."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Reverse Port Forwarding (ADB Reverse: Device -> PC)", "🔁")
        ui.print_device_status(adb.serial)

        reverses = _list_reverse_forwards()
        ui.header(f"Active Reverse Forwards ({len(reverses)} active):")
        print()

        if reverses:
            headers = ("#", "Device Serial", "Device Remote Port", "Host PC Local Port", "PC Status")
            rows = []
            for i, r in enumerate(reverses, 1):
                try:
                    port_num = int(r[2].replace("tcp:", ""))
                    listening = _is_host_port_listening(port_num)
                    status_str = f"{ui.Colors.GREEN}Listening{ui.Colors.RESET}" if listening else f"{ui.Colors.YELLOW}Not Listening{ui.Colors.RESET}"
                except ValueError:
                    status_str = "—"
                rows.append((str(i), r[0], r[1], r[2], status_str))
            ui.print_table(rows, headers)
        else:
            ui.info("No active reverse forwards.")
        print()

        options = [
            "Add Custom Reverse Forward (tcp:remote -> tcp:local)",
            "Preset: React Native Metro Bundler (tcp:8081 -> tcp:8081)",
            "Preset: Web Dev Server / React / Vite (tcp:3000 -> tcp:3000)",
            "Preset: Web Dev Server / Vue / Spring (tcp:8080 -> tcp:8080)",
            "Preset: Python Flask / .NET API (tcp:5000 -> tcp:5000)",
            "Preset: Python Django / FastAPI (tcp:8000 -> tcp:8000)",
            "Test Host PC Port Connectivity",
            "Remove a Specific Reverse Forward",
            "Remove ALL Active Reverse Forwards",
        ]

        ui.print_menu("Reverse Forwarding Actions", options)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            remote_p = ui.get_choice("Enter Device Port (e.g. 3000)")
            local_p = ui.get_choice("Enter Host PC Port (e.g. 3000)")
            if remote_p.isdigit() and local_p.isdigit():
                ok, out = adb.run(["reverse", f"tcp:{remote_p}", f"tcp:{local_p}"])
                if ok:
                    ui.success(f"Reverse forward established: Device 'localhost:{remote_p}' -> Host PC '127.0.0.1:{local_p}'")
                else:
                    ui.error(f"Reverse forward failed: {out}")
            else:
                ui.error("Ports must be numeric values.")
            ui.pause()

        elif choice == "2":
            ok, out = adb.run(["reverse", "tcp:8081", "tcp:8081"])
            if ok:
                ui.success("React Native Metro forward created on tcp:8081.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "3":
            ok, out = adb.run(["reverse", "tcp:3000", "tcp:3000"])
            if ok:
                ui.success("Web Server reverse forward created on tcp:3000.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "4":
            ok, out = adb.run(["reverse", "tcp:8080", "tcp:8080"])
            if ok:
                ui.success("Web Server reverse forward created on tcp:8080.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "5":
            ok, out = adb.run(["reverse", "tcp:5000", "tcp:5000"])
            if ok:
                ui.success("API Server reverse forward created on tcp:5000.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "6":
            ok, out = adb.run(["reverse", "tcp:8000", "tcp:8000"])
            if ok:
                ui.success("FastAPI / Django reverse forward created on tcp:8000.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "7":
            port_test = ui.get_choice("Enter Host Port to test (e.g. 3000, 8080)")
            if port_test.isdigit():
                p = int(port_test)
                if _is_host_port_listening(p):
                    ui.success(f"Host PC Port {p} is ACTIVE and LISTENING!")
                else:
                    ui.warning(f"Host PC Port {p} is NOT reachable. Ensure your local dev server is running.")
            else:
                ui.error("Invalid port.")
            ui.pause()

        elif choice == "8":
            if not reverses:
                ui.warning("No reverse forwards to remove.")
                ui.pause()
                continue
            port_to_rem = ui.get_choice("Enter Device Port to remove (e.g. 3000)")
            clean_port = port_to_rem.replace("tcp:", "").strip()
            ok, out = adb.run(["reverse", "--remove", f"tcp:{clean_port}"])
            if ok:
                ui.success(f"Removed reverse forward tcp:{clean_port}.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "9":
            if ui.confirm("Remove ALL active reverse forwards?"):
                ok, out = adb.run(["reverse", "--remove-all"])
                if ok:
                    ui.success("All reverse forwards removed.")
                else:
                    ui.error(f"Failed: {out}")
            ui.pause()


# ─── Feature 5: Battery Optimization & Process Killer ────────────────────────

def _get_uid_package_map() -> Dict[str, str]:
    """Map system UIDs to human-readable package names."""
    uid_map: Dict[str, str] = {}
    ok, out = adb.run(["shell", "pm", "list", "packages", "-U"], timeout=12)
    if ok and out:
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                # Format: package:com.example.app uid:10156
                parts = line.split()
                if len(parts) >= 2:
                    pkg = parts[0].replace("package:", "").strip()
                    uid_str = parts[1].replace("uid:", "").strip()
                    uid_map[uid_str] = pkg
    return uid_map


def _parse_batterystats_drain() -> List[Dict[str, Any]]:
    """Parse `dumpsys batterystats` to extract estimated mAh consumption per application."""
    ok, out = adb.run(["shell", "dumpsys", "batterystats"], timeout=20)
    if not ok or not out:
        return []

    uid_map = _get_uid_package_map()
    results: List[Dict[str, Any]] = []

    # Find Estimated power use section
    in_power_section = False
    for line in out.splitlines():
        line_clean = line.strip()
        if "Estimated power use (mAh):" in line:
            in_power_section = True
            continue
        if in_power_section:
            if not line_clean or line_clean.startswith("Total "):
                break

            # Match Uid line: Uid u0a145: 142 ( cpu=120 wake=22 )
            uid_match = re.match(r"Uid\s+([a-zA-Z0-9_]+):\s+([0-9.]+)", line_clean)
            if uid_match:
                uid_raw = uid_match.group(1)
                mah = float(uid_match.group(2))

                # Extract numeric portion of UID if formatted as u0a123
                num_match = re.search(r"a(\d+)", uid_raw)
                target_pkg = ""
                if num_match:
                    full_uid = str(10000 + int(num_match.group(1)))
                    target_pkg = uid_map.get(full_uid, "")

                results.append({
                    "uid": uid_raw,
                    "package": target_pkg if target_pkg else f"UID {uid_raw}",
                    "mah": mah,
                })
            else:
                # Top-level item like Screen, Cell standby, Wi-Fi
                other_match = re.match(r"([a-zA-Z0-9_\s]+):\s+([0-9.]+)", line_clean)
                if other_match:
                    name = other_match.group(1).strip()
                    mah = float(other_match.group(2))
                    results.append({
                        "uid": "System",
                        "package": name,
                        "mah": mah,
                    })

    # Sort descending by mAh consumed
    results.sort(key=lambda x: x["mah"], reverse=True)
    return results


def battery_optimization_manager():
    """Inspect battery drain, kill rogue background processes, and simulate power."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Battery Optimization & Process Killer", "🔋")
        ui.print_device_status(adb.serial)

        # Quick battery overview
        ok, bat_out = adb.run(["shell", "dumpsys", "battery"])
        level = "—"
        voltage = "—"
        temp = "—"
        status = "—"
        ac = "—"
        if ok and bat_out:
            for line in bat_out.splitlines():
                if "level:" in line:
                    level = line.split(":")[-1].strip() + "%"
                elif "voltage:" in line:
                    v_raw = line.split(":")[-1].strip()
                    voltage = f"{int(v_raw) / 1000:.2f}V" if v_raw.isdigit() else v_raw
                elif "temperature:" in line:
                    t_raw = line.split(":")[-1].strip()
                    temp = f"{int(t_raw) / 10:.1f}°C" if t_raw.isdigit() else t_raw
                elif "status:" in line:
                    status = line.split(":")[-1].strip()
                elif "AC powered:" in line:
                    ac = line.split(":")[-1].strip()

        ui.header("Battery Status Card:")
        ui.print_kv({
            "Battery Level": level,
            "Battery Voltage": voltage,
            "Temperature": temp,
            "Charger Connected": ac,
            "Battery Status": status,
        })
        print()

        options = [
            "Show Top Battery-Draining Apps (dumpsys batterystats)",
            "Force-Stop a Single Background App",
            "Kill All Non-System Background Apps (am kill-all)",
            "Reset Battery Statistics & Dumpsys History",
            "Simulate Low Battery Level (QA Testing, e.g. 5%)",
            "Simulate Charger Disconnected (unplug mode)",
            "Reset Battery Simulation to Real Hardware",
        ]

        ui.print_menu("Battery Tools Menu", options)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            ui.header("Top Battery-Draining Components (batterystats):")
            drainers = _parse_batterystats_drain()
            if not drainers:
                ui.warning("No power consumption statistics recorded since last full charge.")
            else:
                total_mah = sum(d["mah"] for d in drainers) or 1.0
                headers = ("#", "Component / Application", "Estimated Drain (mAh)", "Share (%)")
                rows = []
                for idx, d in enumerate(drainers[:20], 1):
                    pct = (d["mah"] / total_mah) * 100
                    rows.append((
                        str(idx),
                        d["package"],
                        f"{d['mah']:.2f} mAh",
                        f"{pct:.1f}%",
                    ))
                ui.print_table(rows, headers)
            ui.pause()

        elif choice == "2":
            ui.header("Kill Background Application Process")
            pkg = _select_or_search_package("Enter package name to force stop")
            if pkg:
                ok, out = adb.run(["shell", "am", "force-stop", pkg])
                if ok:
                    ui.success(f"Application '{pkg}' forcibly terminated.")
                else:
                    ui.error(f"Failed to terminate app: {out}")
            ui.pause()

        elif choice == "3":
            ui.header("Terminate All Non-System Background Apps")
            ui.warning("This will force-stop non-essential running 3rd-party user applications.")
            if ui.confirm("Proceed with terminating background apps?"):
                third_party = _get_installed_packages("-3")
                killed_count = 0
                adb.run(["shell", "am", "kill-all"])
                for pkg in third_party:
                    ok, _ = adb.run(["shell", "am", "force-stop", pkg], timeout=2)
                    if ok:
                        killed_count += 1
                ui.success(f"Terminated background processes across {killed_count} installed 3rd-party apps.")
            ui.pause()

        elif choice == "4":
            if ui.confirm("Reset battery usage statistics counter?"):
                ok, out = adb.run(["shell", "dumpsys", "batterystats", "--reset"])
                if ok:
                    ui.success("Battery statistics history reset to 0.")
                else:
                    ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "5":
            target_lvl = ui.get_choice("Enter mock battery level (0 - 100)")
            if target_lvl.isdigit() and 0 <= int(target_lvl) <= 100:
                adb.run(["shell", "dumpsys", "battery", "unplug"])
                adb.run(["shell", "dumpsys", "battery", "set", "level", target_lvl])
                ui.success(f"Battery level spoofed to {target_lvl}%. Watch UI low battery alert.")
            else:
                ui.error("Must be an integer between 0 and 100.")
            ui.pause()

        elif choice == "6":
            adb.run(["shell", "dumpsys", "battery", "unplug"])
            ui.success("Battery service set to 'unplugged' state.")
            ui.pause()

        elif choice == "7":
            adb.run(["shell", "dumpsys", "battery", "reset"])
            ui.success("Battery service returned to physical hardware monitoring.")
            ui.pause()


# ─── Feature 6: Bloatware Manager (Freeze / Debloat) ─────────────────────────

KNOWN_OEM_BLOATWARE = [
    # Samsung
    {"pkg": "com.samsung.android.bixby.agent", "vendor": "Samsung", "name": "Bixby Voice Agent", "safe": True},
    {"pkg": "com.samsung.android.bixby.wakeup", "vendor": "Samsung", "name": "Bixby Wakeup Service", "safe": True},
    {"pkg": "com.samsung.android.app.spage", "vendor": "Samsung", "name": "Bixby Home / Samsung Free", "safe": True},
    {"pkg": "com.samsung.android.aremoji", "vendor": "Samsung", "name": "AR Emoji Studio", "safe": True},
    {"pkg": "com.samsung.android.game.gamehome", "vendor": "Samsung", "name": "Game Launcher", "safe": True},
    {"pkg": "com.samsung.android.voc", "vendor": "Samsung", "name": "Samsung Members Diagnostic", "safe": True},
    {"pkg": "com.sec.android.app.sbrowser", "vendor": "Samsung", "name": "Samsung Internet Browser", "safe": True},
    # Xiaomi / MIUI / HyperOS
    {"pkg": "com.miui.analytics", "vendor": "Xiaomi", "name": "MIUI Telemetry Analytics", "safe": True},
    {"pkg": "com.miui.msa.global", "vendor": "Xiaomi", "name": "MIUI System Ads (MSA Daemon)", "safe": True},
    {"pkg": "com.miui.videoplayer", "vendor": "Xiaomi", "name": "Mi Video Player", "safe": True},
    {"pkg": "com.mi.globalbrowser", "vendor": "Xiaomi", "name": "Mi Browser Pro", "safe": True},
    {"pkg": "com.miui.yellowpage", "vendor": "Xiaomi", "name": "MIUI YellowPages Caller ID", "safe": True},
    {"pkg": "com.miui.hybrid", "vendor": "Xiaomi", "name": "Quick Apps Service", "safe": True},
    # Meta / Facebook Preloads
    {"pkg": "com.facebook.katana", "vendor": "Meta", "name": "Facebook Preloaded App", "safe": True},
    {"pkg": "com.facebook.system", "vendor": "Meta", "name": "Facebook App Installer", "safe": True},
    {"pkg": "com.facebook.appmanager", "vendor": "Meta", "name": "Facebook App Manager Daemon", "safe": True},
    {"pkg": "com.facebook.services", "vendor": "Meta", "name": "Facebook Services Sync", "safe": True},
    # Microsoft Preloads
    {"pkg": "com.microsoft.skydrive", "vendor": "Microsoft", "name": "OneDrive Sync Preload", "safe": True},
    {"pkg": "com.linkedin.android", "vendor": "Microsoft", "name": "LinkedIn Preloaded Client", "safe": True},
    # Google Non-Essential
    {"pkg": "com.google.android.apps.books", "vendor": "Google", "name": "Google Play Books", "safe": True},
    {"pkg": "com.google.android.videos", "vendor": "Google", "name": "Google TV (Play Movies)", "safe": True},
    {"pkg": "com.google.android.apps.magazines", "vendor": "Google", "name": "Google News", "safe": True},
    {"pkg": "com.google.android.apps.podcasts", "vendor": "Google", "name": "Google Podcasts", "safe": True},
    {"pkg": "com.google.android.apps.subscriptions.red", "vendor": "Google", "name": "Google One", "safe": True},
    # Carrier Bloat
    {"pkg": "com.vzw.hss.myverizon", "vendor": "Carrier", "name": "My Verizon Stub", "safe": True},
    {"pkg": "com.aura.oobe.verizon", "vendor": "Carrier", "name": "Verizon App Selector (Aura)", "safe": True},
    {"pkg": "com.att.myWireless", "vendor": "Carrier", "name": "myAT&T Stub", "safe": True},
    {"pkg": "com.aura.oobe.att", "vendor": "Carrier", "name": "AT&T App Select (Aura)", "safe": True},
]


def bloatware_manager():
    """Freeze, unfreeze, debloat, and scan preloaded system bloatware safely."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Bloatware Manager (Freeze & Debloat)", "🗑️")
        ui.print_device_status(adb.serial)

        # Count disabled packages
        disabled_pkgs = _get_installed_packages("-d")
        ui.info(f"Currently Frozen/Disabled Apps on Device: {len(disabled_pkgs)}")

        options = [
            "Scan for Known OEM & Carrier Bloatware (One-Click Inspector)",
            "List All Currently Disabled / Frozen Apps",
            "Freeze / Disable an App (pm disable-user --user 0)",
            "Unfreeze / Re-enable an App (pm enable)",
            "Safe Debloat: Uninstall System App for User 0 (pm uninstall -k --user 0)",
            "Restore / Reinstall Uninstalled System App (cmd package install-existing)",
            "Filter & Browse System Packages (pm list packages -s)",
        ]

        ui.print_menu("Bloatware Actions", options)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            ui.header("Scanning Installed Packages for Known Bloatware...")
            all_installed = set(_get_installed_packages())
            detected = [b for b in KNOWN_OEM_BLOATWARE if b["pkg"] in all_installed]

            if not detected:
                ui.success("No known OEM/Carrier bloatware packages from our database found on this device!")
            else:
                ui.warning(f"Detected {len(detected)} known bloatware package(s) on device:")
                print()
                headers = ("#", "Vendor", "Package Name", "Description", "Status")
                rows = []
                for i, d in enumerate(detected, 1):
                    is_frozen = d["pkg"] in disabled_pkgs
                    status = f"{ui.Colors.DIM}FROZEN{ui.Colors.RESET}" if is_frozen else f"{ui.Colors.RED}ACTIVE{ui.Colors.RESET}"
                    rows.append((str(i), d["vendor"], d["pkg"], d["name"], status))
                ui.print_table(rows, headers)
                print()

                if ui.confirm("Would you like to freeze (disable) any of these packages now?"):
                    pick = ui.get_choice("Enter package number to freeze (or 'all' to freeze all active)")
                    if pick.lower() == "all":
                        frozen_count = 0
                        for d in detected:
                            if d["pkg"] not in disabled_pkgs:
                                ok, _ = adb.run(["shell", "pm", "disable-user", "--user", "0", d["pkg"]])
                                if ok:
                                    frozen_count += 1
                        ui.success(f"Batch-froze {frozen_count} bloatware packages.")
                    else:
                        try:
                            idx = int(pick) - 1
                            if 0 <= idx < len(detected):
                                chosen_pkg = detected[idx]["pkg"]
                                ok, out = adb.run(["shell", "pm", "disable-user", "--user", "0", chosen_pkg])
                                if ok:
                                    ui.success(f"Froze {chosen_pkg}.")
                                else:
                                    ui.error(f"Failed to freeze: {out}")
                        except ValueError:
                            ui.error("Invalid selection.")
            ui.pause()

        elif choice == "2":
            ui.header("Currently Disabled / Frozen Applications:")
            if not disabled_pkgs:
                ui.info("No applications are currently disabled.")
            else:
                for idx, p in enumerate(disabled_pkgs, 1):
                    print(f"  {ui.Colors.YELLOW}[{idx:>2}]{ui.Colors.RESET} {p}")
            ui.pause()

        elif choice == "3":
            ui.header("Freeze / Disable System App")
            pkg = _select_or_search_package("Enter package name to freeze")
            if pkg:
                ok, out = adb.run(["shell", "pm", "disable-user", "--user", "0", pkg])
                if ok and "disabled" in out.lower() or "state" in out.lower():
                    ui.success(f"Package '{pkg}' is now FROZEN (disabled for User 0).")
                else:
                    ui.error(f"Operation failed: {out}")
            ui.pause()

        elif choice == "4":
            ui.header("Unfreeze / Re-enable Disabled App")
            if disabled_pkgs:
                ui.header("Choose from currently disabled packages:")
                for i, p in enumerate(disabled_pkgs[:20], 1):
                    print(f"  {ui.Colors.YELLOW}[{i:>2}]{ui.Colors.RESET} {p}")
                print()
            pkg = _select_or_search_package("Enter package name to unfreeze")
            if pkg:
                ok, out = adb.run(["shell", "pm", "enable", pkg])
                if ok and "enabled" in out.lower():
                    ui.success(f"Package '{pkg}' is now ACTIVE (enabled).")
                else:
                    ui.error(f"Operation failed: {out}")
            ui.pause()

        elif choice == "5":
            ui.header("Safe Debloat: Uninstall for User 0")
            ui.warning("This uninstalls the app for primary user (User 0). The APK remains on /system")
            ui.warning("so it can be restored anytime, but it will consume 0 RAM and not run.")
            pkg = _select_or_search_package("Enter package name to uninstall for User 0")
            if pkg:
                if ui.confirm(f"Uninstall '{pkg}' for User 0?"):
                    ok, out = adb.run(["shell", "pm", "uninstall", "-k", "--user", "0", pkg])
                    if ok and "success" in out.lower():
                        ui.success(f"Successfully uninstalled '{pkg}' for User 0.")
                    else:
                        ui.error(f"Debloat failed: {out}")
            ui.pause()

        elif choice == "6":
            ui.header("Restore / Reinstall Uninstalled System App")
            pkg = _select_or_search_package("Enter package name to restore for User 0")
            if pkg:
                ok, out = adb.run(["shell", "cmd", "package", "install-existing", pkg])
                if ok and "installed" in out.lower():
                    ui.success(f"Successfully restored system package '{pkg}' for User 0.")
                else:
                    ui.error(f"Restoration failed: {out}")
            ui.pause()

        elif choice == "7":
            query = ui.get_choice("Enter keyword to filter system apps (leave empty for all)")
            system_pkgs = _get_installed_packages("-s")
            filtered = [p for p in system_pkgs if query.lower() in p.lower()] if query else system_pkgs
            ui.header(f"System Apps ({len(filtered)} matching):")
            for i, p in enumerate(filtered[:50], 1):
                print(f"  {ui.Colors.DIM}{i:>3}.{ui.Colors.RESET} {p}")
            if len(filtered) > 50:
                ui.info(f"... and {len(filtered) - 50} more system packages.")
            ui.pause()


# ─── Feature 7: OTA Sideload Guide & Runner ──────────────────────────────────

def ota_sideload_wizard():
    """Step-by-step assistant and execution tool for flashing OTA update ZIPs."""
    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("OTA Sideload Assistant & Runner", "📦")

        # Detect current device state
        devices = adb.list_devices()
        current_state = "none"
        if devices:
            for d in devices:
                if d.get("serial") == adb.serial:
                    current_state = d.get("state", "unknown")
                    break
            if current_state == "none":
                current_state = devices[0].get("state", "unknown")

        ui.print_kv({
            "Active Serial": adb.serial or "None",
            "Current State": current_state.upper(),
        })
        print()

        options = [
            "OTA Sideload Educational Guide & Instructions",
            "Reboot Device to Recovery Mode (adb reboot recovery)",
            "Reboot Device directly to Sideload Mode (adb reboot sideload)",
            "Select & Flash OTA Update Package (adb sideload update.zip)",
            "Reboot Device back to System (adb reboot)",
            "Refresh Device Connection State",
        ]

        ui.print_menu("OTA Sideload Workflow", options)
        choice = ui.get_choice("Select step")

        if choice == "0":
            break
        elif choice == "1":
            ui.header("OTA Sideloading Overview & Protocol:")
            print(f"""
  {ui.Colors.BOLD}What is ADB Sideloading?{ui.Colors.RESET}
    ADB Sideload allows flashing official manufacturer OTA updates, security patches,
    or recovery-flashable ZIPs without needing an unlocked bootloader (for official signed packages).

  {ui.Colors.BOLD}Step-by-step Process:{ui.Colors.RESET}
    1. Connect device with USB Debugging enabled.
    2. Reboot into Recovery: Choose Option 2 or 3.
    3. In Stock Recovery:
       • If "No command" screen appears, press and hold Power, then press Volume Up once.
       • Navigate using Volume buttons to {ui.Colors.CYAN}"Apply update from ADB"{ui.Colors.RESET}.
       • Press Power button to select.
    4. In Custom Recovery (TWRP / OrangeFox / Lineage Recovery):
       • Navigate to {ui.Colors.CYAN}Advanced > ADB Sideload{ui.Colors.RESET} and swipe/confirm.
    5. The device state in 'adb devices' will change to {ui.Colors.GREEN}"sideload"{ui.Colors.RESET}.
    6. Choose Option 4 in this menu and provide the path to your OTA .zip archive.
            """)
            ui.pause()

        elif choice == "2":
            if not ensure_device():
                continue
            if ui.confirm("Reboot device into Recovery Mode now?"):
                ok, out = adb.run(["reboot", "recovery"])
                if ok:
                    ui.success("Reboot recovery command issued. Device is entering recovery...")
                else:
                    ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "3":
            if not ensure_device():
                continue
            if ui.confirm("Reboot device into Sideload Mode now?"):
                ok, out = adb.run(["reboot", "sideload"])
                if ok:
                    ui.success("Reboot sideload command issued.")
                else:
                    ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "4":
            # Check if device is in sideload mode
            dev_list = adb.list_devices()
            sideload_devs = [d for d in dev_list if d.get("state") == "sideload"]

            if not sideload_devs and current_state != "sideload":
                ui.warning(f"Device is currently in state '{current_state.upper()}', NOT in 'sideload' mode.")
                ui.info("Please reboot into Recovery and select 'Apply update from ADB' first.")
                if not ui.confirm("Do you want to proceed with sideload anyway?"):
                    continue

            zip_path = ui.get_choice("Enter full local path to OTA update ZIP file").strip('"').strip("'")
            if not os.path.isfile(zip_path):
                ui.error(f"File not found: {zip_path}")
                ui.pause()
                continue

            if not zip_path.lower().endswith(".zip"):
                ui.warning("Selected file does not have a .zip extension. OTA updates are usually .zip files.")
                if not ui.confirm("Continue with this file?"):
                    continue

            file_size_mb = os.path.getsize(zip_path) / (1024 * 1024)
            ui.header("Flashing OTA Sideload Package:")
            ui.print_kv({
                "File Path": zip_path,
                "File Size": f"{file_size_mb:.2f} MB",
                "Target Device": adb.serial or "Auto",
            })
            print()

            if ui.confirm("Begin sideloading to device?"):
                ui.info("Transferring and verifying OTA payload. Do NOT disconnect the USB cable...")
                # Run with timeout=1200 (20 minutes)
                ok, out = adb.run(["sideload", zip_path], timeout=1200)
                if ok:
                    ui.success("Sideload completed successfully! Check device screen for reboot option.")
                else:
                    ui.error(f"Sideload failed or interrupted: {out}")
            ui.pause()

        elif choice == "5":
            ok, out = adb.run(["reboot"])
            if ok:
                ui.success("Reboot command accepted. Device is returning to normal system.")
            else:
                ui.error(f"Reboot failed: {out}")
            ui.pause()

        elif choice == "6":
            adb.list_devices()
            ui.info("Device state refreshed.")
            time.sleep(0.5)


# ─── Feature 8: App Data Backup to PC (.ab) ──────────────────────────────────

def app_data_backup_manager():
    """Create and restore Android application backups (.ab format) with PC export."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("App Data Backup & Restore (.ab to PC)", "💾")
        ui.print_device_status(adb.serial)

        options = [
            "Backup Specific App with APK (adb backup -apk <pkg>)",
            "Backup Specific App Data Only (adb backup -noapk <pkg>)",
            "Full System & All Apps Backup (adb backup -all)",
            "Restore an Existing .ab Backup to Device (adb restore <file>)",
            "Inspect .ab Archive Header Metadata",
            "Browse Local Backups Storage Folder",
        ]

        ui.print_menu("Backup & Restore Options", options)
        choice = ui.get_choice("Select option")

        backup_dir = _ensure_dir("backups")

        if choice == "0":
            break
        elif choice == "1" or choice == "2":
            include_apk = choice == "1"
            mode_label = "APK + Data" if include_apk else "Data Only"
            ui.header(f"App Backup ({mode_label})")

            pkg = _select_or_search_package("Enter package name to back up")
            if not pkg:
                continue

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"backup_{pkg}_{ts}.ab"
            dest_file = os.path.join(backup_dir, filename)

            ui.warning("IMPORTANT INSTRUCTION:")
            ui.info("A prompt will now appear on your phone screen.")
            ui.info("Please unlock the device and tap 'Back up my data'.")
            ui.info("If you configured a desktop backup password in Developer Options, enter it.")
            print()

            if ui.confirm(f"Start backup for '{pkg}' to '{filename}'?"):
                args = ["backup", "-f", dest_file]
                args.append("-apk" if include_apk else "-noapk")
                args.append(pkg)

                ui.info("Waiting for device confirmation...")
                ok, out = adb.run(args, timeout=300)

                if os.path.isfile(dest_file) and os.path.getsize(dest_file) > 0:
                    sz_kb = os.path.getsize(dest_file) / 1024
                    ui.success(f"Backup complete! File saved: {dest_file} ({sz_kb:.1f} KB)")
                else:
                    ui.error("Backup failed or was declined on device.")
            ui.pause()

        elif choice == "3":
            ui.header("Full System & App Data Backup")
            ui.warning("This archives all user applications and shared storage. May take several minutes.")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_file = os.path.join(backup_dir, f"full_backup_{ts}.ab")

            if ui.confirm("Initiate full device backup?"):
                ui.info("Please accept the backup prompt on your device screen...")
                ok, out = adb.run(["backup", "-f", dest_file, "-apk", "-shared", "-all", "-system"], timeout=1800)
                if os.path.isfile(dest_file) and os.path.getsize(dest_file) > 0:
                    sz_mb = os.path.getsize(dest_file) / (1024 * 1024)
                    ui.success(f"Full backup completed: {dest_file} ({sz_mb:.2f} MB)")
                else:
                    ui.error("Full backup failed or was declined on device.")
            ui.pause()

        elif choice == "4":
            ui.header("Restore .ab Archive to Device")
            file_path = ui.get_choice("Enter local path to .ab backup file").strip('"').strip("'")
            if not os.path.isfile(file_path):
                ui.error(f"File not found: {file_path}")
                ui.pause()
                continue

            ui.warning("Please unlock your phone and tap 'Restore my data' when prompted.")
            if ui.confirm(f"Restore '{os.path.basename(file_path)}' to device now?"):
                ok, out = adb.run(["restore", file_path], timeout=600)
                if ok:
                    ui.success("Restore process sent to device. Observe on-screen progress.")
                else:
                    ui.error(f"Restore failed: {out}")
            ui.pause()

        elif choice == "5":
            ui.header("Inspect Android Backup (.ab) Header")
            file_path = ui.get_choice("Enter path to .ab file to inspect").strip('"').strip("'")
            if not os.path.isfile(file_path):
                ui.error(f"File not found: {file_path}")
                ui.pause()
                continue

            try:
                with open(file_path, "rb") as f:
                    header_bytes = f.read(128)
                lines = header_bytes.split(b"\n")
                magic = lines[0].decode("latin-1", errors="ignore")
                if "ANDROID BACKUP" in magic:
                    version = lines[1].decode("latin-1") if len(lines) > 1 else "?"
                    compressed = lines[2].decode("latin-1") if len(lines) > 2 else "?"
                    encryption = lines[3].decode("latin-1") if len(lines) > 3 else "?"
                    ui.print_kv({
                        "Magic Marker": magic,
                        "Backup Version": version,
                        "Compressed": "Yes (deflate)" if compressed == "1" else "No",
                        "Encryption": "None (unencrypted)" if encryption.lower() == "none" else f"Encrypted ({encryption})",
                        "File Size": f"{os.path.getsize(file_path) / 1024:.1f} KB",
                    })
                else:
                    ui.warning("File does not start with standard 'ANDROID BACKUP' magic identifier.")
            except Exception as e:
                ui.error(f"Could not read file header: {e}")
            ui.pause()

        elif choice == "6":
            ui.header(f"Local Backups Storage Directory ('{backup_dir}'):")
            if os.path.isdir(backup_dir):
                files = [f for f in os.listdir(backup_dir) if f.endswith(".ab")]
                if files:
                    for idx, f in enumerate(files, 1):
                        f_sz = os.path.getsize(os.path.join(backup_dir, f)) / 1024
                        print(f"  {ui.Colors.YELLOW}[{idx:>2}]{ui.Colors.RESET} {f} ({f_sz:.1f} KB)")
                else:
                    ui.info("No .ab backups stored yet.")
            ui.pause()


# ─── Feature 9: Grant / Revoke Runtime Permissions ───────────────────────────

COMMON_RUNTIME_PERMISSIONS = [
    ("Camera", "android.permission.CAMERA"),
    ("Microphone (Audio)", "android.permission.RECORD_AUDIO"),
    ("Fine Location (GPS)", "android.permission.ACCESS_FINE_LOCATION"),
    ("Coarse Location (Network)", "android.permission.ACCESS_COARSE_LOCATION"),
    ("Background Location", "android.permission.ACCESS_BACKGROUND_LOCATION"),
    ("Read External Storage", "android.permission.READ_EXTERNAL_STORAGE"),
    ("Write External Storage", "android.permission.WRITE_EXTERNAL_STORAGE"),
    ("Read Images / Photos", "android.permission.READ_MEDIA_IMAGES"),
    ("Read Video", "android.permission.READ_MEDIA_VIDEO"),
    ("Read Audio / Music", "android.permission.READ_MEDIA_AUDIO"),
    ("Read Contacts", "android.permission.READ_CONTACTS"),
    ("Write Contacts", "android.permission.WRITE_CONTACTS"),
    ("Read Call Log", "android.permission.READ_CALL_LOG"),
    ("Read Phone State", "android.permission.READ_PHONE_STATE"),
    ("Post Notifications", "android.permission.POST_NOTIFICATIONS"),
]


def _get_app_permissions(pkg: str) -> List[Dict[str, Any]]:
    """Parse `dumpsys package <pkg>` to extract requested permissions and their granted state."""
    ok, out = adb.run(["shell", "dumpsys", "package", pkg], timeout=15)
    if not ok or not out:
        return []

    permissions: List[Dict[str, Any]] = []
    in_requested = False
    in_runtime = False
    runtime_granted_map: Dict[str, bool] = {}

    for line in out.splitlines():
        line_s = line.strip()
        if "requested permissions:" in line_s:
            in_requested = True
            in_runtime = False
            continue
        if "install permissions:" in line_s or "runtime permissions:" in line_s:
            in_requested = False
            in_runtime = True
            continue

        if in_runtime and ":" in line_s and "granted=" in line_s:
            perm_name = line_s.split(":")[0].strip()
            is_granted = "granted=true" in line_s
            runtime_granted_map[perm_name] = is_granted

        if in_requested and line_s.startswith("android.permission."):
            perm = line_s.split(":")[0].strip()
            permissions.append({
                "permission": perm,
                "granted": runtime_granted_map.get(perm, None),
            })

    # Update granted status from runtime map
    for p in permissions:
        if p["permission"] in runtime_granted_map:
            p["granted"] = runtime_granted_map[p["permission"]]

    return permissions


def runtime_permissions_manager():
    """Inspect and modify application runtime and AppOps permissions."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Grant / Revoke Runtime Permissions", "🛡️")
        ui.print_device_status(adb.serial)

        options = [
            "Inspect All Permissions for an App",
            "Grant Common Permission (Camera, Mic, Location, Storage, etc.)",
            "Grant Custom Permission (pm grant <pkg> <permission>)",
            "Revoke Permission (pm revoke <pkg> <permission>)",
            "Grant ALL Requested Runtime Permissions (One-Click)",
            "Reset All Permissions to Default (pm reset-permissions)",
            "Manage Special AppOps (Overlay, Write Settings, Usage Stats)",
        ]

        ui.print_menu("Permissions Menu", options)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            ui.header("Inspect Application Permissions")
            pkg = _select_or_search_package("Select package to inspect")
            if pkg:
                perms = _get_app_permissions(pkg)
                if not perms:
                    ui.warning(f"No permissions found or application '{pkg}' not installed.")
                else:
                    ui.header(f"Permissions for '{pkg}' ({len(perms)} total):")
                    headers = ("#", "Permission Name", "Status")
                    rows = []
                    for i, p in enumerate(perms, 1):
                        g = p["granted"]
                        if g is True:
                            status = f"{ui.Colors.GREEN}GRANTED{ui.Colors.RESET}"
                        elif g is False:
                            status = f"{ui.Colors.RED}DENIED{ui.Colors.RESET}"
                        else:
                            status = f"{ui.Colors.DIM}INSTALL/NORMAL{ui.Colors.RESET}"
                        rows.append((str(i), p["permission"], status))
                    ui.print_table(rows, headers)
            ui.pause()

        elif choice == "2":
            ui.header("Grant Common Runtime Permission")
            pkg = _select_or_search_package("Select target package")
            if not pkg:
                continue

            ui.header("Select Permission to Grant:")
            for idx, (label, perm) in enumerate(COMMON_RUNTIME_PERMISSIONS, 1):
                print(f"  {ui.Colors.YELLOW}[{idx:>2}]{ui.Colors.RESET} {label} ({perm})")
            print()

            sel = ui.get_choice("Select permission number")
            try:
                idx = int(sel) - 1
                if 0 <= idx < len(COMMON_RUNTIME_PERMISSIONS):
                    perm_target = COMMON_RUNTIME_PERMISSIONS[idx][1]
                    ok, out = adb.run(["shell", "pm", "grant", pkg, perm_target])
                    if ok:
                        ui.success(f"Granted '{perm_target}' to '{pkg}'.")
                    else:
                        ui.error(f"Failed to grant: {out}")
                else:
                    ui.error("Invalid choice.")
            except ValueError:
                ui.error("Invalid input.")
            ui.pause()

        elif choice == "3":
            ui.header("Grant Custom Permission")
            pkg = _select_or_search_package("Select target package")
            if pkg:
                perm_name = ui.get_choice("Enter full permission name (e.g. android.permission.RECORD_AUDIO)")
                if perm_name:
                    ok, out = adb.run(["shell", "pm", "grant", pkg, perm_name])
                    if ok:
                        ui.success(f"Granted '{perm_name}' to '{pkg}'.")
                    else:
                        ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "4":
            ui.header("Revoke Runtime Permission")
            pkg = _select_or_search_package("Select target package")
            if pkg:
                perm_name = ui.get_choice("Enter full permission name to revoke")
                if perm_name:
                    ok, out = adb.run(["shell", "pm", "revoke", pkg, perm_name])
                    if ok:
                        ui.success(f"Revoked '{perm_name}' from '{pkg}'.")
                    else:
                        ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "5":
            ui.header("Batch Grant All Runtime Permissions")
            pkg = _select_or_search_package("Select target package")
            if pkg:
                perms = _get_app_permissions(pkg)
                granted_count = 0
                for p in perms:
                    perm_name = p["permission"]
                    ok, _ = adb.run(["shell", "pm", "grant", pkg, perm_name], timeout=3)
                    if ok:
                        granted_count += 1
                ui.success(f"Batch granted {granted_count} permissions for '{pkg}'.")
            ui.pause()

        elif choice == "6":
            ui.header("Reset App Permissions to Default")
            pkg = _select_or_search_package("Select target package")
            if pkg:
                ok, out = adb.run(["shell", "pm", "reset-permissions", pkg])
                if ok:
                    ui.success(f"All runtime permissions reset to default for '{pkg}'.")
                else:
                    ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "7":
            ui.header("Special AppOps Management (Draw Over Other Apps / Settings / Usage)")
            pkg = _select_or_search_package("Select target package")
            if not pkg:
                continue

            print()
            print(f"  {ui.Colors.YELLOW}[1]{ui.Colors.RESET} SYSTEM_ALERT_WINDOW (Draw Over Other Apps / Overlay) -> ALLOW")
            print(f"  {ui.Colors.YELLOW}[2]{ui.Colors.RESET} WRITE_SETTINGS (Modify System Settings) -> ALLOW")
            print(f"  {ui.Colors.YELLOW}[3]{ui.Colors.RESET} GET_USAGE_STATS (Usage Access Tracking) -> ALLOW")
            print(f"  {ui.Colors.YELLOW}[4]{ui.Colors.RESET} MANAGE_EXTERNAL_STORAGE (All Files Access) -> ALLOW")
            print(f"  {ui.Colors.YELLOW}[5]{ui.Colors.RESET} SYSTEM_ALERT_WINDOW -> IGNORE / DENY")
            print()

            op_choice = ui.get_choice("Select AppOp configuration")
            op_map = {
                "1": ("SYSTEM_ALERT_WINDOW", "allow"),
                "2": ("WRITE_SETTINGS", "allow"),
                "3": ("GET_USAGE_STATS", "allow"),
                "4": ("MANAGE_EXTERNAL_STORAGE", "allow"),
                "5": ("SYSTEM_ALERT_WINDOW", "ignore"),
            }
            if op_choice in op_map:
                op_name, op_val = op_map[op_choice]
                ok, out = adb.run(["shell", "appops", "set", pkg, op_name, op_val])
                if ok:
                    ui.success(f"AppOp '{op_name}' set to '{op_val}' for '{pkg}'.")
                else:
                    ui.error(f"Failed: {out}")
            else:
                ui.error("Invalid choice.")
            ui.pause()


# ─── Feature 10: Change Device DPI (wm density) ──────────────────────────────

DPI_PRESETS = [
    ("Ultra-Compact (High Information Density)", 320),
    ("Compact UI (Small Elements & Fonts)", 360),
    ("Balanced Everyday UI", 400),
    ("Standard Density", 440),
    ("Comfortable / Large UI", 480),
    ("Extra Large (Accessibility)", 560),
    ("Tablet Mode (Triggers Tablet UI on Large Phones)", 280),
]


def _get_current_density() -> Tuple[str, str]:
    """Return (physical_density, override_density) from `wm density`."""
    ok, out = adb.run(["shell", "wm", "density"], timeout=5)
    phys = "Unknown"
    over = "None (Using Physical)"
    if ok and out:
        for line in out.splitlines():
            line_s = line.strip()
            if "Physical density:" in line_s:
                phys = line_s.split(":")[-1].strip()
            elif "Override density:" in line_s:
                over = line_s.split(":")[-1].strip()
    return phys, over


def change_device_dpi():
    """Adjust display pixel density (DPI) with safety validation and restoration."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Device Display Density (DPI / wm density)", "📐")
        ui.print_device_status(adb.serial)

        phys, current_over = _get_current_density()
        ui.header("Current Density Status:")
        ui.print_kv({
            "Hardware Physical DPI": f"{phys} dpi",
            "Active Override DPI": f"{current_over} dpi",
        })
        print()

        options = [
            "Select DPI from Curated Presets",
            "Scale Density by -15% (Make Elements Smaller / More Screen Space)",
            "Scale Density by +15% (Make Elements Larger / Easier Reading)",
            "Enter Custom DPI Value (120 - 720)",
            "Reset DPI to Factory Hardware Default (wm density reset)",
        ]

        ui.print_menu("DPI Actions", options)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            ui.header("Curated Display Density Presets:")
            for idx, (label, dpi_val) in enumerate(DPI_PRESETS, 1):
                print(f"  {ui.Colors.YELLOW}[{idx:>2}]{ui.Colors.RESET} {dpi_val} dpi — {label}")
            print()

            sel = ui.get_choice("Select preset")
            try:
                idx = int(sel) - 1
                if 0 <= idx < len(DPI_PRESETS):
                    target_dpi = DPI_PRESETS[idx][1]
                    ok, out = adb.run(["shell", "wm", "density", str(target_dpi)])
                    if ok:
                        ui.success(f"Density updated to {target_dpi} dpi.")
                    else:
                        ui.error(f"Failed: {out}")
                else:
                    ui.error("Invalid preset.")
            except ValueError:
                ui.error("Invalid input.")
            ui.pause()

        elif choice == "2" or choice == "3":
            try:
                base = int(phys) if phys.isdigit() else 420
                factor = 0.85 if choice == "2" else 1.15
                target = int(base * factor)
                ok, out = adb.run(["shell", "wm", "density", str(target)])
                if ok:
                    ui.success(f"Scaled density set to {target} dpi.")
                else:
                    ui.error(f"Failed: {out}")
            except Exception as e:
                ui.error(f"Error calculating scaled density: {e}")
            ui.pause()

        elif choice == "4":
            dpi_input = ui.get_choice("Enter target DPI value (120 to 720)")
            if dpi_input.isdigit():
                val = int(dpi_input)
                if 120 <= val <= 720:
                    ok, out = adb.run(["shell", "wm", "density", str(val)])
                    if ok:
                        ui.success(f"DPI successfully configured to {val}.")
                    else:
                        ui.error(f"Failed: {out}")
                else:
                    ui.error("Value must be between 120 and 720 dpi for display safety.")
            else:
                ui.error("Must be a positive integer.")
            ui.pause()

        elif choice == "5":
            ok, out = adb.run(["shell", "wm", "density", "reset"])
            if ok:
                ui.success("Density reset to hardware default.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()


# ─── Feature 11: Change Screen Resolution (wm size) ──────────────────────────

RESOLUTION_PRESETS = [
    ("HD+ (720x1600) — Low Power / High Gaming FPS", "720x1600"),
    ("FHD+ (1080x2400) — Standard Modern Aspect Ratio", "1080x2400"),
    ("QHD+ (1440x3200) — Ultra Clarity", "1440x3200"),
    ("Standard 720p 16:9 (720x1280)", "720x1280"),
    ("Standard 1080p 16:9 (1080x1920)", "1080x1920"),
    ("Standard 1440p 16:9 (1440x2560)", "1440x2560"),
]


def _get_current_resolution() -> Tuple[str, str]:
    """Return (physical_size, override_size) from `wm size`."""
    ok, out = adb.run(["shell", "wm", "size"], timeout=5)
    phys = "Unknown"
    over = "None (Using Physical)"
    if ok and out:
        for line in out.splitlines():
            line_s = line.strip()
            if "Physical size:" in line_s:
                phys = line_s.split(":")[-1].strip()
            elif "Override size:" in line_s:
                over = line_s.split(":")[-1].strip()
    return phys, over


def change_screen_resolution():
    """Adjust virtual screen resolution with downscaling presets and reset."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Screen Resolution Controls (wm size)", "🖥️")
        ui.print_device_status(adb.serial)

        phys, current_over = _get_current_resolution()
        ui.header("Display Resolution Status:")
        ui.print_kv({
            "Physical Native Resolution": phys,
            "Active Override Resolution": current_over,
        })
        print()

        options = [
            "Select Resolution from Presets",
            "Downscale to 75% of Native Resolution",
            "Downscale to 50% of Native Resolution (Half-Res Benchmark)",
            "Enter Custom Resolution (Width x Height)",
            "Reset Resolution to Factory Physical Default (wm size reset)",
        ]

        ui.print_menu("Resolution Actions", options)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            ui.header("Resolution Presets:")
            for idx, (label, res_str) in enumerate(RESOLUTION_PRESETS, 1):
                print(f"  {ui.Colors.YELLOW}[{idx:>2}]{ui.Colors.RESET} {res_str} — {label}")
            print()

            sel = ui.get_choice("Select preset")
            try:
                idx = int(sel) - 1
                if 0 <= idx < len(RESOLUTION_PRESETS):
                    target_res = RESOLUTION_PRESETS[idx][1]
                    ui.warning(f"Changing resolution to {target_res}...")
                    ok, out = adb.run(["shell", "wm", "size", target_res])
                    if ok:
                        ui.success(f"Resolution applied: {target_res}")
                    else:
                        ui.error(f"Failed: {out}")
                else:
                    ui.error("Invalid preset.")
            except ValueError:
                ui.error("Invalid input.")
            ui.pause()

        elif choice == "2" or choice == "3":
            if "x" in phys:
                try:
                    w, h = map(int, phys.split("x"))
                    factor = 0.75 if choice == "2" else 0.50
                    new_w = int(w * factor)
                    new_h = int(h * factor)
                    # Must be even dimensions
                    new_w += new_w % 2
                    new_h += new_h % 2
                    target = f"{new_w}x{new_h}"
                    ok, out = adb.run(["shell", "wm", "size", target])
                    if ok:
                        ui.success(f"Downscaled resolution set to {target}.")
                    else:
                        ui.error(f"Failed: {out}")
                except Exception as e:
                    ui.error(f"Error computing resolution: {e}")
            else:
                ui.error("Could not parse physical resolution.")
            ui.pause()

        elif choice == "4":
            res_input = ui.get_choice("Enter resolution as WIDTHxHEIGHT (e.g. 1080x2400)")
            if re.match(r"^\d{3,4}x\d{3,4}$", res_input):
                ok, out = adb.run(["shell", "wm", "size", res_input])
                if ok:
                    ui.success(f"Resolution set to {res_input}.")
                else:
                    ui.error(f"Failed: {out}")
            else:
                ui.error("Invalid format. Format must be WIDTHxHEIGHT (e.g. 720x1600).")
            ui.pause()

        elif choice == "5":
            ok, out = adb.run(["shell", "wm", "size", "reset"])
            if ok:
                ui.success("Resolution reset to hardware physical default.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()


# ─── Feature 12: Enable / Disable System Animations ──────────────────────────

def _get_animation_scales() -> Dict[str, str]:
    """Read current window, transition, and animator scales."""
    w_ok, w = adb.run(["shell", "settings", "get", "global", "window_animation_scale"])
    t_ok, t = adb.run(["shell", "settings", "get", "global", "transition_animation_scale"])
    a_ok, a = adb.run(["shell", "settings", "get", "global", "animator_duration_scale"])
    return {
        "Window Scale": w.strip() if w_ok and w.strip() else "1.0",
        "Transition Scale": t.strip() if t_ok and t.strip() else "1.0",
        "Animator Scale": a.strip() if a_ok and a.strip() else "1.0",
    }


def _set_all_animation_scales(scale: float):
    """Set all 3 animation scales simultaneously."""
    s_val = str(scale)
    adb.run(["shell", "settings", "put", "global", "window_animation_scale", s_val])
    adb.run(["shell", "settings", "put", "global", "transition_animation_scale", s_val])
    adb.run(["shell", "settings", "put", "global", "animator_duration_scale", s_val])


def system_animations_manager():
    """Toggle and adjust Android system animation speeds."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("System Animation Speeds & Scale", "⚡")
        ui.print_device_status(adb.serial)

        scales = _get_animation_scales()
        ui.header("Current System Animation Scales:")
        ui.print_kv(scales)
        print()

        options = [
            "Disable All Animations (Scale = 0.0x — Instant / Blazing Fast UI)",
            "Enable Snappy Animations (Scale = 0.5x — Developer Favorite)",
            "Enable Stock Standard Animations (Scale = 1.0x — Android Default)",
            "Enable Relaxed Animations (Scale = 1.5x)",
            "Slow Motion Mode (Scale = 2.0x — UI Testing & Review)",
            "Ultra Slow-Mo Mode (Scale = 5.0x / 10.0x — Micro-Interaction Debugging)",
            "Custom Scale Value for Specific Animation Type",
        ]

        ui.print_menu("Animation Profiles", options)
        choice = ui.get_choice("Select profile")

        if choice == "0":
            break
        elif choice == "1":
            _set_all_animation_scales(0.0)
            ui.success("All animation scales set to 0.0x! System UI will now respond instantly without transitions.")
            ui.pause()
        elif choice == "2":
            _set_all_animation_scales(0.5)
            ui.success("All animation scales set to 0.5x. Enjoy responsive, high-speed animations!")
            ui.pause()
        elif choice == "3":
            _set_all_animation_scales(1.0)
            ui.success("All animation scales reset to 1.0x (Android factory default).")
            ui.pause()
        elif choice == "4":
            _set_all_animation_scales(1.5)
            ui.success("All animation scales set to 1.5x.")
            ui.pause()
        elif choice == "5":
            _set_all_animation_scales(2.0)
            ui.success("All animation scales set to 2.0x.")
            ui.pause()
        elif choice == "6":
            slow_choice = ui.get_choice("Enter 5 or 10 for slow motion multiplier")
            val = 10.0 if slow_choice == "10" else 5.0
            _set_all_animation_scales(val)
            ui.success(f"Animation scales set to {val}x.")
            ui.pause()
        elif choice == "7":
            ui.header("Custom Scale Configuration:")
            print("  [1] Window Animation Scale")
            print("  [2] Transition Animation Scale")
            print("  [3] Animator Duration Scale")
            sel = ui.get_choice("Select animation type")
            key_map = {
                "1": "window_animation_scale",
                "2": "transition_animation_scale",
                "3": "animator_duration_scale",
            }
            if sel in key_map:
                scale_val = ui.get_choice("Enter numeric scale (e.g. 0.25, 0.75, 1.25)")
                try:
                    f_val = float(scale_val)
                    adb.run(["shell", "settings", "put", "global", key_map[sel], str(f_val)])
                    ui.success(f"Updated {key_map[sel]} to {f_val}x.")
                except ValueError:
                    ui.error("Must be a valid decimal number.")
            else:
                ui.error("Invalid choice.")
            ui.pause()


# ─── Feature 13: Force Dark Mode & UI Night Mode ─────────────────────────────

def _get_current_night_mode() -> str:
    """Detect current UI dark mode state."""
    ok, out = adb.run(["shell", "cmd", "uimode", "night"], timeout=5)
    if ok and out:
        return out.strip()

    ok2, out2 = adb.run(["shell", "settings", "get", "secure", "ui_night_mode"], timeout=5)
    if ok2 and out2:
        val = out2.strip()
        if val == "2":
            return "Night mode: yes (Dark)"
        elif val == "1":
            return "Night mode: no (Light)"
        elif val == "0":
            return "Night mode: auto (Schedule)"
    return "Unknown"


def force_dark_mode_manager():
    """Toggle system dark mode, scheduled night mode, and HWUI force dark."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Force Dark Mode & UI Night Mode", "🌙")
        ui.print_device_status(adb.serial)

        status = _get_current_night_mode()
        force_dark_prop = adb.getprop("debug.hwui.force_dark") or "false"

        ui.header("Current Dark Mode State:")
        ui.print_kv({
            "System UI Night Mode": status,
            "HWUI Force Dark (Prop)": "Enabled" if force_dark_prop.lower() == "true" else "Disabled",
        })
        print()

        options = [
            "Force Dark Mode ON (cmd uimode night yes)",
            "Force Light Mode ON (cmd uimode night no)",
            "Set Dark Mode to Automatic / Sunset Schedule (cmd uimode night auto)",
            "Toggle HWUI Force-Dark for Unsupported Apps (debug.hwui.force_dark)",
        ]

        ui.print_menu("Dark Mode Controls", options)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            ok, out = adb.run(["shell", "cmd", "uimode", "night", "yes"])
            adb.run(["shell", "settings", "put", "secure", "ui_night_mode", "2"])
            if ok:
                ui.success("Dark Mode FORCED ON across system UI and compatible applications.")
            else:
                ui.error(f"Command failed: {out}")
            ui.pause()

        elif choice == "2":
            ok, out = adb.run(["shell", "cmd", "uimode", "night", "no"])
            adb.run(["shell", "settings", "put", "secure", "ui_night_mode", "1"])
            if ok:
                ui.success("Light Mode FORCED ON.")
            else:
                ui.error(f"Command failed: {out}")
            ui.pause()

        elif choice == "3":
            ok, out = adb.run(["shell", "cmd", "uimode", "night", "auto"])
            adb.run(["shell", "settings", "put", "secure", "ui_night_mode", "0"])
            if ok:
                ui.success("Dark Mode set to AUTO (follows sunset / system schedule).")
            else:
                ui.error(f"Command failed: {out}")
            ui.pause()

        elif choice == "4":
            current_state = force_dark_prop.lower() == "true"
            new_state = "false" if current_state else "true"
            ok, out = adb.run(["shell", "setprop", "debug.hwui.force_dark", new_state])
            if ok:
                status_text = "ENABLED" if new_state == "true" else "DISABLED"
                ui.success(f"HWUI Force-Dark property {status_text}.")
                ui.info("Renders dark themes even on apps that do not natively provide dark mode.")
            else:
                ui.error(f"Failed to set property: {out}")
            ui.pause()


# ─── Feature 14: Wake Lock Inspector (dumpsys power) ─────────────────────────

def _parse_wake_locks() -> List[Dict[str, str]]:
    """Parse active wake locks from `dumpsys power`."""
    ok, out = adb.run(["shell", "dumpsys", "power"], timeout=15)
    if not ok or not out:
        return []

    wake_locks: List[Dict[str, str]] = []
    in_wake_locks = False

    for line in out.splitlines():
        line_clean = line.strip()
        if "Wake Locks: size=" in line_clean:
            in_wake_locks = True
            continue
        if in_wake_locks:
            if "Suspend Blockers:" in line_clean or line_clean.startswith("Device"):
                break
            if not line_clean:
                continue

            # e.g.: PARTIAL_WAKE_LOCK 'AudioMix' ACQ=-1s152ms (uid=1041 pid=2490 ws=WorkSource{10098})
            # or: SCREEN_BRIGHT_WAKE_LOCK 'WindowManager' ACQ=-3m12s (uid=1000 pid=1820)
            parts = line_clean.split(maxsplit=2)
            if len(parts) >= 2:
                lock_type = parts[0]
                tag = parts[1].strip("'").strip('"')
                details = parts[2] if len(parts) > 2 else ""

                # Extract UID if present
                uid_m = re.search(r"uid=(\d+)", details)
                uid_val = uid_m.group(1) if uid_m else "—"

                # Extract ACQ duration
                acq_m = re.search(r"ACQ=([^ ]+)", details)
                duration = acq_m.group(1) if acq_m else "Active"

                wake_locks.append({
                    "type": lock_type,
                    "tag": tag,
                    "uid": uid_val,
                    "duration": duration,
                })

    return wake_locks


def wake_lock_inspector():
    """Inspect applications currently holding active wake locks preventing CPU deep sleep."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Wake Lock Inspector (dumpsys power)", "⏱️")
        ui.print_device_status(adb.serial)

        locks = _parse_wake_locks()
        ui.header(f"Currently Active Wake Locks ({len(locks)} active):")
        print()

        if locks:
            headers = ("#", "Lock Type", "Tag / Process Name", "UID", "Held Duration")
            rows = [(str(i), l["type"], l["tag"], l["uid"], l["duration"]) for i, l in enumerate(locks, 1)]
            ui.print_table(rows, headers)
            print()
            ui.info("Applications holding continuous PARTIAL_WAKE_LOCK prevent deep sleep and drain battery.")
        else:
            ui.success("No active wake locks detected! Device is eligible to enter deep sleep.")
        print()

        options = [
            "Refresh Wake Locks Display",
            "Force Stop an Offending App Holding Wake Locks",
            "View PowerManager Suspend Blockers",
        ]

        ui.print_menu("Wake Lock Actions", options)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            continue
        elif choice == "2":
            pkg = _select_or_search_package("Enter package name to terminate")
            if pkg:
                ok, out = adb.run(["shell", "am", "force-stop", pkg])
                if ok:
                    ui.success(f"Terminated '{pkg}'. Wake lock released.")
                else:
                    ui.error(f"Failed: {out}")
            ui.pause()
        elif choice == "3":
            ui.header("PowerManager Suspend Blockers:")
            ok, out = adb.run(["shell", "dumpsys", "power"], timeout=10)
            if ok and out:
                lines = []
                capture = False
                for l in out.splitlines():
                    if "Suspend Blockers:" in l:
                        capture = True
                        continue
                    if capture:
                        if not l.strip() or "Screen" in l:
                            break
                        lines.append(l.strip())
                for l in lines:
                    print(f"    {ui.Colors.CYAN}•{ui.Colors.RESET} {l}")
            ui.pause()


# ─── Feature 15: Doze Mode Control & Whitelist ───────────────────────────────

def _get_doze_state() -> Dict[str, str]:
    """Inspect deviceidle dumpsys for deep and light Doze state."""
    ok, out = adb.run(["shell", "dumpsys", "deviceidle"], timeout=10)
    info_map = {
        "Deep Doze State": "Unknown",
        "Light Doze State": "Unknown",
        "Deep Doze Enabled": "Unknown",
        "Light Doze Enabled": "Unknown",
    }
    if ok and out:
        for line in out.splitlines():
            line_s = line.strip()
            if line_s.startswith("mState="):
                info_map["Deep Doze State"] = line_s.split("=")[-1]
            elif line_s.startswith("mLightState="):
                info_map["Light Doze State"] = line_s.split("=")[-1]
            elif line_s.startswith("mDeepEnabled="):
                info_map["Deep Doze Enabled"] = line_s.split("=")[-1]
            elif line_s.startswith("mLightEnabled="):
                info_map["Light Doze Enabled"] = line_s.split("=")[-1]
    return info_map


def _get_doze_whitelist() -> Tuple[List[str], List[str]]:
    """Return (system_whitelist, user_whitelist) from dumpsys deviceidle."""
    ok, out = adb.run(["shell", "dumpsys", "deviceidle", "whitelist"], timeout=10)
    sys_list: List[str] = []
    usr_list: List[str] = []

    if ok and out:
        for line in out.splitlines():
            line_s = line.strip()
            if line_s.startswith("system,"):
                sys_list.append(line_s.replace("system,", "").strip())
            elif line_s.startswith("user,"):
                usr_list.append(line_s.replace("user,", "").strip())

    return sys_list, usr_list


def doze_mode_controller():
    """Force Doze idle states, test background push notifications, and manage whitelist."""
    if not ensure_device():
        return

    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Doze Mode Control & Battery Optimization Whitelist", "💤")
        ui.print_device_status(adb.serial)

        state_info = _get_doze_state()
        ui.header("Current Doze (deviceidle) Status:")
        ui.print_kv(state_info)
        print()

        options = [
            "Force Device into Deep Doze (force-idle)",
            "Step to Next Doze State (dumpsys deviceidle step)",
            "Exit Doze / Wake Device (unforce)",
            "View Battery Optimization Whitelist Apps",
            "Add App to Doze Whitelist (Exempt from battery restrictions)",
            "Remove App from Doze Whitelist",
            "Enable Battery Saver Mode (Low Power Mode)",
            "Disable Battery Saver Mode",
        ]

        ui.print_menu("Doze Mode Controls", options)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            ui.info("Simulating screen off and forcing Deep Doze...")
            adb.run(["shell", "dumpsys", "battery", "unplug"])
            ok, out = adb.run(["shell", "dumpsys", "deviceidle", "force-idle"])
            if ok:
                ui.success("Device FORCED into IDLE (Deep Doze).")
                ui.info("Background jobs, alarms, and network sync are now throttled.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "2":
            ok, out = adb.run(["shell", "dumpsys", "deviceidle", "step"])
            if ok:
                ui.success(f"Stepped to next state: {out.strip()}")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "3":
            ok, out = adb.run(["shell", "dumpsys", "deviceidle", "unforce"])
            adb.run(["shell", "dumpsys", "battery", "reset"])
            if ok:
                ui.success("Device awakened from forced Doze. Normal power state resumed.")
            else:
                ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "4":
            sys_wl, usr_wl = _get_doze_whitelist()
            ui.header(f"User-Whitelisted Apps ({len(usr_wl)}):")
            if usr_wl:
                for i, p in enumerate(usr_wl, 1):
                    print(f"  {ui.Colors.GREEN}[{i:>2}]{ui.Colors.RESET} {p}")
            else:
                ui.info("No apps explicitly whitelisted by user.")
            print()
            ui.header(f"System Whitelist Sample ({len(sys_wl)} apps total):")
            for p in sys_wl[:15]:
                print(f"  {ui.Colors.DIM}•{ui.Colors.RESET} {p}")
            if len(sys_wl) > 15:
                ui.info(f"... and {len(sys_wl) - 15} more system packages.")
            ui.pause()

        elif choice == "5":
            ui.header("Whitelist App from Battery Optimizations")
            pkg = _select_or_search_package("Enter package to whitelist")
            if pkg:
                ok, out = adb.run(["shell", "dumpsys", "deviceidle", "whitelist", f"+{pkg}"])
                if ok:
                    ui.success(f"Added '{pkg}' to Doze battery optimization whitelist.")
                else:
                    ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "6":
            ui.header("Remove App from Battery Optimization Whitelist")
            pkg = _select_or_search_package("Enter package to remove from whitelist")
            if pkg:
                ok, out = adb.run(["shell", "dumpsys", "deviceidle", "whitelist", f"-{pkg}"])
                if ok:
                    ui.success(f"Removed '{pkg}' from Doze whitelist.")
                else:
                    ui.error(f"Failed: {out}")
            ui.pause()

        elif choice == "7":
            ok, out = adb.run(["shell", "cmd", "battery-saver", "enable"])
            if not ok:
                adb.run(["shell", "settings", "put", "global", "low_power", "1"])
            ui.success("Battery Saver Mode ENABLED.")
            ui.pause()

        elif choice == "8":
            ok, out = adb.run(["shell", "cmd", "battery-saver", "disable"])
            if not ok:
                adb.run(["shell", "settings", "put", "global", "low_power", "0"])
            ui.success("Battery Saver Mode DISABLED.")
            ui.pause()


# ─── Public Entry Menu ────────────────────────────────────────────────────────

def power_tools_menu():
    """Main menu loop for the Advanced Power Tools module."""
    while True:
        ui.clear()
        ui.print_banner()
        ui.print_sub_banner("Advanced Power Tools & System Tweaks", "⚡")
        ui.print_device_status(adb.serial)

        options = [
            "View Saved Wi-Fi Passwords (Root Required)",
            "GPS Mock Location & Coordinate Spoofing",
            "Port Forwarding (ADB Forward: PC -> Device)",
            "Reverse Port Forwarding (ADB Reverse: Device -> PC)",
            "Battery Optimization & Process Killer",
            "Bloatware Manager (Freeze / Debloat Apps)",
            "OTA Sideload Assistant & Runner",
            "App Data Backup & Restore (.ab to PC)",
            "Grant / Revoke Runtime Permissions",
            "Change Device Display Density (DPI)",
            "Change Screen Resolution (wm size)",
            "System Animation Speeds & Scale Overrides",
            "Force Dark Mode & UI Night Mode",
            "Wake Lock Inspector (dumpsys power)",
            "Doze Mode Control & Optimization Whitelist",
        ]

        ui.print_menu("Power Tools Menu", options, columns=2)
        choice = ui.get_choice("Select option")

        if choice == "0":
            break
        elif choice == "1":
            view_saved_wifi_passwords()
            ui.pause()
        elif choice == "2":
            gps_mock_location_tool()
        elif choice == "3":
            port_forwarding_manager()
        elif choice == "4":
            reverse_port_forwarding_manager()
        elif choice == "5":
            battery_optimization_manager()
        elif choice == "6":
            bloatware_manager()
        elif choice == "7":
            ota_sideload_wizard()
        elif choice == "8":
            app_data_backup_manager()
        elif choice == "9":
            runtime_permissions_manager()
        elif choice == "10":
            change_device_dpi()
        elif choice == "11":
            change_screen_resolution()
        elif choice == "12":
            system_animations_manager()
        elif choice == "13":
            force_dark_mode_manager()
        elif choice == "14":
            wake_lock_inspector()
        elif choice == "15":
            doze_mode_controller()
        else:
            ui.error("Invalid option. Please select a valid number.")
            ui.pause()
