"""
modules/app_testing.py — App Testing & Debugging Tools Module for DroidCommander.

Provides a comprehensive suite for Android application testing and quality assurance:
UI monkey testing, high-volume endurance stress testing, intent injection, broadcast dispatch,
service lifecycle control, deep link & App Link verification, content provider inspection,
heap dump extraction (.hprof), method execution tracing, debugger attachment control,
data clearing & cold launch benchmarking, low memory pressure simulation,
crash & ANR analysis from Dropbox, ART/Dalvik garbage collection triggering,
App Standby & Doze mode testing, and runtime permission matrix manipulation.
"""

from datetime import datetime
import os
import re
import shutil
import time
from typing import Dict, List, Optional, Tuple, Any

from core.adb import adb
from core import ui
from core.device import ensure_device


# ─── File & Path Helpers ──────────────────────────────────────────────────────

def _ensure_output_dir(dirname: str) -> str:
    """Ensure a local directory exists for storing test artifacts and reports."""
    os.makedirs(dirname, exist_ok=True)
    return dirname


def _clean_path(path_str: str) -> str:
    """Clean quoted or whitespace-padded local paths."""
    return os.path.expanduser(path_str.strip().strip('"').strip("'"))


def _format_bytes(num_bytes: int) -> str:
    """Format an integer byte count into a human-readable representation."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.2f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


# ─── Package & Process Discovery Helpers ──────────────────────────────────────

def _get_installed_packages(filter_flag: str = "") -> List[str]:
    """
    Fetch a sorted list of installed package names from the connected device.

    Parameters
    ----------
    filter_flag : str
        Optional filter flag for `pm list packages` ('-3' for third-party, '-s' for system).
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


def _get_focused_package() -> Optional[str]:
    """Return the package name of the currently focused foreground application."""
    ok, out = adb.run(["shell", "dumpsys", "window"], timeout=8)
    if ok and out:
        for line in out.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                match = re.search(r"([a-zA-Z0-9_\.]+\/[a-zA-Z0-9_\.\$]+)", line)
                if match:
                    pkg = match.group(1).split("/")[0]
                    if pkg and pkg not in ("StatusBar", "Keyguard", "com.android.systemui"):
                        return pkg

    # Fallback to activity stack inspection
    ok_act, out_act = adb.run(["shell", "dumpsys", "activity", "activities"], timeout=8)
    if ok_act and out_act:
        for line in out_act.splitlines():
            if "ResumedActivity" in line or "mResumedActivity" in line:
                match = re.search(r"([a-zA-Z0-9_\.]+\/[a-zA-Z0-9_\.\$]+)", line)
                if match:
                    return match.group(1).split("/")[0]

    return None


def _select_or_search_package(
    prompt: str = "Enter package name",
    allow_focused_default: bool = True
) -> Optional[str]:
    """
    Prompt user for a package name with interactive search and foreground app auto-detection.

    Entering '?' initiates a substring search across installed packages.
    Pressing Enter with no text adopts the currently focused foreground app if available.
    """
    focused = _get_focused_package() if allow_focused_default else None
    hints = []
    if focused:
        hints.append(f"Enter for '{focused}'")
    hints.append("or '?' to search")
    hint_text = f" ({', '.join(hints)})"

    ui.info(f"{prompt}{hint_text}:")
    val = ui.get_choice(prompt)

    if not val and focused:
        ui.info(f"Targeting active foreground application: {focused}")
        return focused

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

        ui.header(f"Matching Packages ({len(matches)} found):")
        print()
        for idx, pkg in enumerate(matches[:30], 1):
            print(f"  {ui.Colors.YELLOW}[{idx:>2}]{ui.Colors.RESET} {pkg}")
        if len(matches) > 30:
            print(f"  {ui.Colors.DIM}... and {len(matches) - 30} more (refine query to filter){ui.Colors.RESET}")
        print()

        sel = ui.get_choice("Select package number (or 0 to cancel)")
        try:
            sel_idx = int(sel) - 1
            if 0 <= sel_idx < len(matches):
                chosen = matches[sel_idx]
                ui.success(f"Selected: {chosen}")
                return chosen
        except ValueError:
            pass

        ui.error("Invalid selection.")
        return None

    return val


def _get_pid_for_package(pkg: str) -> Optional[int]:
    """Resolve the Linux process ID (PID) for a package name."""
    ok, out = adb.run(["shell", "pidof", "-s", pkg], timeout=5)
    if ok and out.strip().isdigit():
        return int(out.strip())

    ok, out = adb.run(["shell", "pidof", pkg], timeout=5)
    if ok and out.strip():
        parts = out.strip().split()
        if parts and parts[0].isdigit():
            return int(parts[0])

    # Fallback to ps listing
    ok_ps, out_ps = adb.run(["shell", "ps", "-A"], timeout=8)
    if not ok_ps or not out_ps:
        ok_ps, out_ps = adb.run(["shell", "ps"], timeout=8)

    if ok_ps and out_ps:
        for line in out_ps.splitlines():
            parts = line.split()
            if len(parts) >= 9 and parts[-1] == pkg:
                if parts[1].isdigit():
                    return int(parts[1])
            elif len(parts) >= 2 and line.strip().endswith(pkg):
                if parts[1].isdigit():
                    return int(parts[1])

    return None


def _get_package_launcher_activity(pkg: str) -> Optional[str]:
    """Retrieve the main launcher activity component string for a package."""
    ok, out = adb.run(["shell", "cmd", "package", "resolve-activity", "--brief", pkg], timeout=6)
    if ok and out:
        for line in out.splitlines():
            line = line.strip()
            if "/" in line and not line.startswith("priority="):
                return line

    # Fallback via package dumpsys
    ok_dump, out_dump = adb.run(["shell", "dumpsys", "package", pkg], timeout=10)
    if ok_dump and out_dump:
        in_activities = False
        for line in out_dump.splitlines():
            if "Activity Resolver Table:" in line:
                in_activities = True
                continue
            elif in_activities and ("Receiver Resolver Table:" in line or "Service Resolver Table:" in line):
                break
            if in_activities and "/" in line and pkg in line:
                match = re.search(rf"({re.escape(pkg)}\/[a-zA-Z0-9_\.\$]+)", line)
                if match:
                    return match.group(1)

    return None


def _get_package_services(pkg: str) -> List[str]:
    """Extract list of declared service components from package manifest."""
    ok, out = adb.run(["shell", "dumpsys", "package", pkg], timeout=10)
    if not ok or not out:
        return []

    services: List[str] = []
    in_services = False
    for line in out.splitlines():
        stripped = line.strip()
        if "Service Resolver Table:" in stripped or "Services:" in stripped:
            in_services = True
            continue
        elif in_services and ("Permissions:" in stripped or "Providers:" in stripped or "Key Set Manager:" in stripped):
            in_services = False
            break

        if in_services and "/" in stripped and pkg in stripped:
            match = re.search(rf"({re.escape(pkg)}\/[a-zA-Z0-9_\.\$]+)", stripped)
            if match:
                srv = match.group(1)
                if srv not in services:
                    services.append(srv)

    return services


def _get_meminfo_summary(pkg_or_pid: str) -> Dict[str, str]:
    """Extract critical memory metrics (PSS, RSS, Heaps) from dumpsys meminfo."""
    ok, out = adb.run(["shell", "dumpsys", "meminfo", str(pkg_or_pid)], timeout=10)
    stats: Dict[str, str] = {
        "Total PSS": "N/A",
        "Total RSS": "N/A",
        "Native Heap": "N/A",
        "Dalvik Heap": "N/A",
        "Private Dirty": "N/A",
    }
    if not ok or not out:
        return stats

    for line in out.splitlines():
        line_clean = line.strip()
        if line_clean.startswith("TOTAL PSS:") or line_clean.startswith("TOTAL:"):
            parts = line_clean.split()
            if len(parts) >= 2 and parts[1].isdigit():
                stats["Total PSS"] = _format_bytes(int(parts[1]) * 1024)
            elif len(parts) >= 3 and parts[2].isdigit():
                stats["Total PSS"] = _format_bytes(int(parts[2]) * 1024)
        elif line_clean.startswith("TOTAL RSS:"):
            parts = line_clean.split()
            if len(parts) >= 3 and parts[2].isdigit():
                stats["Total RSS"] = _format_bytes(int(parts[2]) * 1024)
        elif "Native Heap" in line:
            parts = line.split()
            if len(parts) >= 3 and parts[2].isdigit():
                stats["Native Heap"] = _format_bytes(int(parts[2]) * 1024)
        elif "Dalvik Heap" in line:
            parts = line.split()
            if len(parts) >= 3 and parts[2].isdigit():
                stats["Dalvik Heap"] = _format_bytes(int(parts[2]) * 1024)
        elif "Private Dirty" in line and "TOTAL" in line:
            parts = line.split()
            if len(parts) >= 4 and parts[3].isdigit():
                stats["Private Dirty"] = _format_bytes(int(parts[3]) * 1024)

    return stats


# ─── 1. Monkey Test ───────────────────────────────────────────────────────────

def run_monkey_test():
    """Run random UI fuzzing events on a target app with customizable throttling and seed."""
    if not ensure_device():
        return

    ui.header("UI Monkey Test (Random Event Fuzzing)")
    pkg = _select_or_search_package("Target package name for Monkey Test")
    if not pkg:
        ui.error("No target package specified.")
        return

    # Event count
    count_str = ui.get_choice("Event count [Default: 1000]")
    event_count = 1000
    if count_str:
        try:
            event_count = max(10, int(count_str))
        except ValueError:
            ui.warning("Invalid number. Falling back to default: 1000.")

    # Throttle delay
    throttle_str = ui.get_choice("Throttle delay between events in ms [Default: 100]")
    throttle = 100
    if throttle_str:
        try:
            throttle = max(0, int(throttle_str))
        except ValueError:
            ui.warning("Invalid throttle. Falling back to default: 100ms.")

    # Seed
    seed_str = ui.get_choice("Random seed (0 for random / non-repeatable) [Default: 0]")
    seed = 0
    if seed_str:
        try:
            seed = int(seed_str)
        except ValueError:
            seed = 0

    # Advanced options
    cmd = ["shell", "monkey", "-p", pkg]
    if throttle > 0:
        cmd += ["--throttle", str(throttle)]
    if seed > 0:
        cmd += ["-s", str(seed)]

    if ui.confirm("Configure error handling flags (ignore crashes / ANRs)?"):
        if ui.confirm("Ignore application crashes?"):
            cmd.append("--ignore-crashes")
        if ui.confirm("Ignore timeouts / ANR dialogs?"):
            cmd.append("--ignore-timeouts")
        if ui.confirm("Ignore security exceptions (permissions)?"):
            cmd.append("--ignore-security-exceptions")
        if ui.confirm("Kill process immediately upon error?"):
            cmd.append("--kill-process-after-error")

    cmd += ["-v", "-v", str(event_count)]

    est_duration = int((event_count * throttle) / 1000) + 30
    timeout = max(60, min(est_duration, 1800))

    ui.info(f"Launching Monkey test on '{pkg}' with {event_count:,} events (throttle: {throttle}ms)...")
    ui.info(f"Estimated runtime: ~{est_duration} seconds. Command timeout set to {timeout}s.")
    print()

    start_time = time.time()
    ok, output = adb.run(cmd, timeout=timeout)
    elapsed = time.time() - start_time

    # Output analysis
    injected = 0
    match_inj = re.search(r"Events injected:\s*(\d+)", output)
    if match_inj:
        injected = int(match_inj.group(1))

    crashes = len(re.findall(r"(// CRASH:|FATAL EXCEPTION|Native crash)", output))
    anrs = len(re.findall(r"(// NOT RESPONDING|ANR in)", output))
    aborted = "** Monkey aborted" in output or "System appears to have crashed" in output

    ui.header("Monkey Test Execution Summary")
    print()
    ui.print_kv({
        "Target Package": pkg,
        "Requested Events": f"{event_count:,}",
        "Injected Events": f"{injected:,}",
        "Elapsed Time": f"{elapsed:.2f} seconds",
        "Average Speed": f"{injected / elapsed:.1f} events/sec" if elapsed > 0 else "N/A",
        "Crashes Encountered": f"{ui.Colors.RED if crashes > 0 else ui.Colors.GREEN}{crashes}{ui.Colors.RESET}",
        "ANRs Encountered": f"{ui.Colors.RED if anrs > 0 else ui.Colors.GREEN}{anrs}{ui.Colors.RESET}",
        "Test Completion": f"{ui.Colors.RED}ABORTED{ui.Colors.RESET}" if aborted else f"{ui.Colors.GREEN}COMPLETED{ui.Colors.RESET}",
    })
    print()

    if crashes == 0 and anrs == 0 and not aborted:
        ui.success("Monkey test finished cleanly without detected crashes or ANRs.")
    else:
        ui.warning("Instabilities detected during Monkey fuzzing execution!")

    if ui.confirm("Save full Monkey log output to local file?"):
        out_dir = _ensure_output_dir("test_reports")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(out_dir, f"monkey_{pkg}_{timestamp}.log")
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"=== MONKEY TEST REPORT ===\n")
                f.write(f"Package: {pkg}\n")
                f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                f.write(f"Command: adb {' '.join(cmd)}\n")
                f.write(f"Injected: {injected} / {event_count}\n")
                f.write(f"Crashes: {crashes}, ANRs: {anrs}\n\n")
                f.write(output)
            ui.success(f"Log saved successfully to: {filename}")
        except OSError as e:
            ui.error(f"Failed to write log file: {e}")


# ─── 2. Stress Test ───────────────────────────────────────────────────────────

def run_stress_test():
    """Run high-volume endurance monkey testing (10,000+ events) with memory tracking and logging."""
    if not ensure_device():
        return

    ui.header("High-Volume Endurance Stress Test")
    pkg = _select_or_search_package("Target package for endurance stress testing")
    if not pkg:
        ui.error("No package selected.")
        return

    print()
    ui.info("Select Stress Test Volume Preset:")
    print("  [1] Standard Stress   — 10,000 events  (~3-5 minutes)")
    print("  [2] Extended Stress   — 25,000 events  (~8-12 minutes)")
    print("  [3] Endurance Run     — 50,000 events  (~15-25 minutes)")
    print("  [4] Full Torture Test — 100,000 events (~30-60 minutes)")
    print("  [5] Custom Volume     — Enter event count (>= 10,000)")
    print()

    preset_choice = ui.get_choice("Select volume preset [Default: 1]")
    event_count = 10000
    if preset_choice == "2":
        event_count = 25000
    elif preset_choice == "3":
        event_count = 50000
    elif preset_choice == "4":
        event_count = 100000
    elif preset_choice == "5":
        custom_val = ui.get_choice("Enter custom event count (>= 10,000)")
        try:
            event_count = max(10000, int(custom_val))
        except ValueError:
            ui.warning("Invalid count. Falling back to 10,000 events.")

    print()
    ui.info("Select Throttle / Injection Rate:")
    print("  [1] 0 ms   (Maximum throughput — stress race conditions & thread contention)")
    print("  [2] 25 ms  (Ultra high intensity)")
    print("  [3] 50 ms  (Fast stress testing)")
    print("  [4] 100 ms (Standard rapid user simulation)")
    throttle_choice = ui.get_choice("Select throttle [Default: 2]")
    throttle = 25
    if throttle_choice == "1":
        throttle = 0
    elif throttle_choice == "3":
        throttle = 50
    elif throttle_choice == "4":
        throttle = 100

    ignore_errors = ui.confirm("Ignore crashes & ANRs so stress run continues to completion?")

    # Memory baseline before stress run
    pid_before = _get_pid_for_package(pkg)
    mem_before = _get_meminfo_summary(pkg) if pid_before else {}

    cmd = ["shell", "monkey", "-p", pkg]
    if throttle > 0:
        cmd += ["--throttle", str(throttle)]
    if ignore_errors:
        cmd += ["--ignore-crashes", "--ignore-timeouts", "--ignore-security-exceptions", "--monitor-native-crashes"]
    cmd += ["-v", "-v", str(event_count)]

    est_sec = int((event_count * throttle) / 1000) + 60
    timeout = max(180, min(est_sec * 2, 7200))

    ui.info(f"Starting {event_count:,} event stress run on '{pkg}' (PID: {pid_before or 'Cold launch'})...")
    ui.info(f"Logging active. Test may run up to {timeout // 60} minutes. Please do not disconnect device.")
    print()

    start_time = time.time()
    ok, output = adb.run(cmd, timeout=timeout)
    elapsed = time.time() - start_time

    # Memory state after stress run
    pid_after = _get_pid_for_package(pkg)
    mem_after = _get_meminfo_summary(pkg) if pid_after else {}

    injected = 0
    match_inj = re.search(r"Events injected:\s*(\d+)", output)
    if match_inj:
        injected = int(match_inj.group(1))

    crashes = len(re.findall(r"(// CRASH:|FATAL EXCEPTION)", output))
    native_crashes = len(re.findall(r"(Native crash|SIGSEGV|SIGABRT)", output))
    anrs = len(re.findall(r"(// NOT RESPONDING|ANR in)", output))
    aborted = "** Monkey aborted" in output

    # Automatically save report
    out_dir = _ensure_output_dir("test_reports")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = os.path.join(out_dir, f"stress_{pkg}_{timestamp}.log")
    try:
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"====================================================\n")
            f.write(f"      DROIDCOMMANDER APP STRESS TEST REPORT        \n")
            f.write(f"====================================================\n")
            f.write(f"Target Package:      {pkg}\n")
            f.write(f"Timestamp:           {datetime.now().isoformat()}\n")
            f.write(f"Events Injected:     {injected:,} / {event_count:,}\n")
            f.write(f"Elapsed Time:        {elapsed:.2f} seconds\n")
            f.write(f"Average Throughput:  {injected / elapsed:.1f} events/s\n")
            f.write(f"Java Crashes:        {crashes}\n")
            f.write(f"Native Crashes:      {native_crashes}\n")
            f.write(f"ANR Events:          {anrs}\n")
            f.write(f"Initial Memory PSS:  {mem_before.get('Total PSS', 'N/A')}\n")
            f.write(f"Final Memory PSS:    {mem_after.get('Total PSS', 'N/A')}\n")
            f.write(f"Process PID:         {pid_before} -> {pid_after}\n")
            f.write(f"====================================================\n\n")
            f.write(output)
        saved_msg = f"Report saved: {report_file}"
    except OSError as e:
        saved_msg = f"Could not save report: {e}"

    ui.header("Endurance Stress Test Results")
    print()
    ui.print_kv({
        "Package Tested": pkg,
        "Target Events": f"{event_count:,}",
        "Injected Events": f"{injected:,}",
        "Duration": f"{elapsed:.1f}s ({elapsed / 60:.1f} min)",
        "Throughput": f"{injected / elapsed:.1f} events/sec" if elapsed > 0 else "N/A",
        "Java Exceptions/Crashes": f"{ui.Colors.RED if crashes > 0 else ui.Colors.GREEN}{crashes}{ui.Colors.RESET}",
        "Native Crashes": f"{ui.Colors.RED if native_crashes > 0 else ui.Colors.GREEN}{native_crashes}{ui.Colors.RESET}",
        "ANRs Detected": f"{ui.Colors.RED if anrs > 0 else ui.Colors.GREEN}{anrs}{ui.Colors.RESET}",
        "Memory (PSS) Before": mem_before.get("Total PSS", "N/A"),
        "Memory (PSS) After": mem_after.get("Total PSS", "N/A"),
        "Process Survived": f"{ui.Colors.GREEN}YES{ui.Colors.RESET}" if pid_after else f"{ui.Colors.RED}NO (Killed / Crashed){ui.Colors.RESET}",
    })
    print()
    ui.info(saved_msg)


# ─── 3. Send Intent ───────────────────────────────────────────────────────────

def send_custom_intent():
    """Construct and dispatch custom intents or trigger curated system actions."""
    if not ensure_device():
        return

    ui.header("Send Intent (am start)")
    print("  [1]  Open Web URL (android.intent.action.VIEW)")
    print("  [2]  Dial Phone Number (android.intent.action.DIAL)")
    print("  [3]  Direct Phone Call (android.intent.action.CALL)")
    print("  [4]  Compose SMS Message (android.intent.action.SENDTO)")
    print("  [5]  Send Email Draft (android.intent.action.SENDTO)")
    print("  [6]  Open Main System Settings")
    print("  [7]  Open Wi-Fi Settings")
    print("  [8]  Open App Details Settings")
    print("  [9]  Open Developer Options")
    print("  [10] Open Battery Optimization Settings")
    print("  [11] Launch Camera Viewfinder")
    print("  [12] Perform Web Search")
    print("  [13] Custom Intent Builder (Action, Data, Extras, Flags)")
    print()

    choice = ui.get_choice("Select intent preset")
    args: List[str] = ["shell", "am", "start"]

    if choice == "1":
        url = ui.get_choice("Enter URL to open [e.g. https://github.com]")
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        args += ["-a", "android.intent.action.VIEW", "-d", url]

    elif choice == "2":
        number = ui.get_choice("Enter phone number to dial")
        if not number:
            return
        args += ["-a", "android.intent.action.DIAL", "-d", f"tel:{number}"]

    elif choice == "3":
        number = ui.get_choice("Enter phone number to call")
        if not number:
            return
        args += ["-a", "android.intent.action.CALL", "-d", f"tel:{number}"]

    elif choice == "4":
        number = ui.get_choice("Recipient phone number")
        body = ui.get_choice("SMS message body text")
        args += ["-a", "android.intent.action.SENDTO", "-d", f"smsto:{number}"]
        if body:
            args += ["--es", "sms_body", body]

    elif choice == "5":
        email = ui.get_choice("Recipient email address")
        subject = ui.get_choice("Email subject line")
        args += ["-a", "android.intent.action.SENDTO", "-d", f"mailto:{email}"]
        if subject:
            args += ["--es", "android.intent.extra.SUBJECT", subject]

    elif choice == "6":
        args += ["-a", "android.settings.SETTINGS"]

    elif choice == "7":
        args += ["-a", "android.settings.WIFI_SETTINGS"]

    elif choice == "8":
        pkg = _select_or_search_package("Package to view in Application Settings")
        if not pkg:
            return
        args += ["-a", "android.settings.APPLICATION_DETAILS_SETTINGS", "-d", f"package:{pkg}"]

    elif choice == "9":
        args += ["-a", "android.settings.APPLICATION_DEVELOPMENT_SETTINGS"]

    elif choice == "10":
        args += ["-a", "android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS"]

    elif choice == "11":
        args += ["-a", "android.media.action.IMAGE_CAPTURE"]

    elif choice == "12":
        query = ui.get_choice("Enter search query")
        if not query:
            return
        args += ["-a", "android.intent.action.WEB_SEARCH", "--es", "query", query]

    elif choice == "13":
        ui.header("Custom Intent Builder Wizard")
        action = ui.get_choice("Action [e.g. android.intent.action.VIEW or android.intent.action.MAIN]")
        data_uri = ui.get_choice("Data URI [optional, e.g. content://... or https://...]")
        comp = ui.get_choice("Component [optional, e.g. com.example/.MainActivity]")
        cat = ui.get_choice("Category [optional, e.g. android.intent.category.BROWSABLE]")
        mime = ui.get_choice("MIME Type [optional, e.g. text/plain]")

        if action:
            args += ["-a", action]
        if data_uri:
            args += ["-d", data_uri]
        if comp:
            args += ["-n", comp]
        if cat:
            args += ["-c", cat]
        if mime:
            args += ["-t", mime]

        while ui.confirm("Add an extra parameter?"):
            print("  [1] String extra (--es)")
            print("  [2] Boolean extra (--ez)")
            print("  [3] Integer extra (--ei)")
            extra_type = ui.get_choice("Extra type")
            key = ui.get_choice("Extra key name")
            if not key:
                break
            val = ui.get_choice("Extra value")
            if extra_type == "2":
                args += ["--ez", key, "true" if val.lower() in ("true", "1", "yes") else "false"]
            elif extra_type == "3":
                args += ["--ei", key, val]
            else:
                args += ["--es", key, val]

        if ui.confirm("Wait for launch completion and measure timing (-W)?"):
            args.append("-W")

    else:
        ui.error("Invalid selection.")
        return

    ui.info(f"Executing: adb {' '.join(args)}")
    ok, out = adb.run(args, timeout=15)
    if ok:
        ui.success("Intent dispatched successfully:")
        print(f"\n{out}\n")
    else:
        ui.error(f"Intent dispatch failed:\n{out}")


# ─── 4. Send Broadcast ────────────────────────────────────────────────────────

def send_custom_broadcast():
    """Dispatch system broadcast signals or trigger custom application receivers."""
    if not ensure_device():
        return

    ui.header("Send Broadcast (am broadcast)")
    print("  [1]  Boot Completed (android.intent.action.BOOT_COMPLETED)")
    print("  [2]  Battery Low (android.intent.action.BATTERY_LOW)")
    print("  [3]  Battery OK (android.intent.action.BATTERY_OKAY)")
    print("  [4]  Power Connected (android.intent.action.ACTION_POWER_CONNECTED)")
    print("  [5]  Power Disconnected (android.intent.action.ACTION_POWER_DISCONNECTED)")
    print("  [6]  Screen Turned On (android.intent.action.SCREEN_ON)")
    print("  [7]  Screen Turned Off (android.intent.action.SCREEN_OFF)")
    print("  [8]  Airplane Mode Changed (android.intent.action.AIRPLANE_MODE)")
    print("  [9]  Connectivity Change (android.net.conn.CONNECTIVITY_CHANGE)")
    print("  [10] Timezone Changed (android.intent.action.TIMEZONE_CHANGED)")
    print("  [11] Package Replaced Notification (android.intent.action.MY_PACKAGE_REPLACED)")
    print("  [12] Locale Changed (android.intent.action.LOCALE_CHANGED)")
    print("  [13] Custom Broadcast Wizard (Action, Component, Extras)")
    print()

    choice = ui.get_choice("Select broadcast preset")
    args: List[str] = ["shell", "am", "broadcast"]

    if choice == "1":
        args += ["-a", "android.intent.action.BOOT_COMPLETED"]
    elif choice == "2":
        args += ["-a", "android.intent.action.BATTERY_LOW"]
    elif choice == "3":
        args += ["-a", "android.intent.action.BATTERY_OKAY"]
    elif choice == "4":
        args += ["-a", "android.intent.action.ACTION_POWER_CONNECTED"]
    elif choice == "5":
        args += ["-a", "android.intent.action.ACTION_POWER_DISCONNECTED"]
    elif choice == "6":
        args += ["-a", "android.intent.action.SCREEN_ON"]
    elif choice == "7":
        args += ["-a", "android.intent.action.SCREEN_OFF"]
    elif choice == "8":
        state = ui.confirm("Simulate Airplane Mode enabled?")
        args += ["-a", "android.intent.action.AIRPLANE_MODE", "--ez", "state", "true" if state else "false"]
    elif choice == "9":
        args += ["-a", "android.net.conn.CONNECTIVITY_CHANGE"]
    elif choice == "10":
        args += ["-a", "android.intent.action.TIMEZONE_CHANGED"]
    elif choice == "11":
        pkg = _select_or_search_package("Target package for MY_PACKAGE_REPLACED")
        if not pkg:
            return
        args += ["-a", "android.intent.action.MY_PACKAGE_REPLACED", "-p", pkg]
    elif choice == "12":
        args += ["-a", "android.intent.action.LOCALE_CHANGED"]
    elif choice == "13":
        action = ui.get_choice("Broadcast Action string")
        if not action:
            return
        args += ["-a", action]
        comp = ui.get_choice("Target component [optional, e.g. com.example/.MyReceiver]")
        if comp:
            args += ["-n", comp]
        pkg = ui.get_choice("Target package [optional]")
        if pkg:
            args += ["-p", pkg]

        while ui.confirm("Add broadcast extra parameter?"):
            print("  [1] String extra (--es)")
            print("  [2] Boolean extra (--ez)")
            print("  [3] Integer extra (--ei)")
            t = ui.get_choice("Type")
            k = ui.get_choice("Key")
            if not k:
                break
            v = ui.get_choice("Value")
            if t == "2":
                args += ["--ez", k, "true" if v.lower() in ("true", "1", "yes") else "false"]
            elif t == "3":
                args += ["--ei", k, v]
            else:
                args += ["--es", k, v]
    else:
        ui.error("Invalid selection.")
        return

    ui.info(f"Executing: adb {' '.join(args)}")
    ok, out = adb.run(args, timeout=15)
    if ok:
        ui.success("Broadcast dispatched successfully:")
        print(f"\n{out}\n")
    else:
        ui.error(f"Broadcast dispatch encountered error:\n{out}")


# ─── 5. Start / Stop Specific Service ─────────────────────────────────────────

def manage_services():
    """Start, stop, inspect, or enumerate background and foreground services."""
    if not ensure_device():
        return

    ui.header("Service Lifecycle Controller")
    print("  [1] Start Background Service (am startservice)")
    print("  [2] Start Foreground Service (am start-foreground-service)")
    print("  [3] Stop Running Service (am stopservice)")
    print("  [4] Inspect Active Services for a Package")
    print("  [5] List Declared Services in App Manifest")
    print("  [6] Search All Active Services System-Wide")
    print()

    choice = ui.get_choice("Select service action")

    if choice in ("1", "2", "3", "5"):
        pkg = _select_or_search_package("Target package name")
        if not pkg:
            return

        declared = _get_package_services(pkg)
        srv_comp = ""
        if declared:
            ui.header(f"Declared Services for {pkg} ({len(declared)} found):")
            for idx, s in enumerate(declared, 1):
                print(f"  {ui.Colors.YELLOW}[{idx:>2}]{ui.Colors.RESET} {s}")
            print(f"  {ui.Colors.YELLOW}[ 0]{ui.Colors.RESET} Enter custom component manually")
            print()
            srv_sel = ui.get_choice("Select service number")
            try:
                s_idx = int(srv_sel) - 1
                if 0 <= s_idx < len(declared):
                    srv_comp = declared[s_idx]
            except ValueError:
                pass

        if not srv_comp:
            srv_comp = ui.get_choice("Enter full service component [e.g. com.example/.MyService]")
            if not srv_comp:
                return

        if choice == "1":
            ok, out = adb.run(["shell", "am", "startservice", "-n", srv_comp], timeout=10)
            if ok:
                ui.success(f"startservice executed for {srv_comp}:\n{out}")
            else:
                ui.error(f"startservice failed:\n{out}")

        elif choice == "2":
            ok, out = adb.run(["shell", "am", "start-foreground-service", "-n", srv_comp], timeout=10)
            if ok:
                ui.success(f"start-foreground-service executed for {srv_comp}:\n{out}")
            else:
                ui.error(f"start-foreground-service failed:\n{out}")

        elif choice == "3":
            ok, out = adb.run(["shell", "am", "stopservice", "-n", srv_comp], timeout=10)
            if ok:
                ui.success(f"stopservice executed for {srv_comp}:\n{out}")
            else:
                ui.error(f"stopservice failed:\n{out}")

        elif choice == "5":
            if not declared:
                ui.warning(f"No declared services found in package manifest for '{pkg}'.")
            else:
                ui.success(f"Found {len(declared)} declared services.")

    elif choice == "4":
        pkg = _select_or_search_package("Package to query running services")
        if not pkg:
            return
        ok, out = adb.run(["shell", "dumpsys", "activity", "services", pkg], timeout=10)
        if ok and out:
            ui.header(f"Running Services for {pkg}:")
            print(out)
        else:
            ui.warning(f"No active services currently running for '{pkg}'.")

    elif choice == "6":
        query = ui.get_choice("Filter search term [or press Enter for top 25]")
        ok, out = adb.run(["shell", "dumpsys", "activity", "services"], timeout=15)
        if ok and out:
            records = [line.strip() for line in out.splitlines() if "* ServiceRecord{" in line]
            if query:
                records = [r for r in records if query.lower() in r.lower()]
            ui.header(f"Active Services in System ({len(records)} found):")
            for r in records[:30]:
                print(f"  {ui.Colors.CYAN}•{ui.Colors.RESET} {r}")
            if len(records) > 30:
                print(f"  {ui.Colors.DIM}... and {len(records) - 30} more{ui.Colors.RESET}")
        else:
            ui.error("Failed to query service records.")
    else:
        ui.error("Invalid choice.")


# ─── 6. Deep Link Tester ──────────────────────────────────────────────────────

def test_deep_links():
    """Test custom URI schemes, HTTP App Links, and query domain verification status."""
    if not ensure_device():
        return

    ui.header("Deep Link & App Link Tester")
    print("  [1] Test Custom Scheme URL (scheme://host/path?params)")
    print("  [2] Test HTTPS / HTTP Web App Link")
    print("  [3] Common Scheme Presets (Market, Geo, Tel, Mailto)")
    print("  [4] Inspect App Links Domain Verification Status")
    print("  [5] Configure User App Link Preference")
    print()

    choice = ui.get_choice("Select deep link action")

    if choice in ("1", "2", "3"):
        url = ""
        if choice == "1":
            url = ui.get_choice("Enter custom scheme URL [e.g. myapp://checkout?id=123]")
        elif choice == "2":
            url = ui.get_choice("Enter HTTPS web link [e.g. https://www.example.com/product/456]")
        elif choice == "3":
            print("    [a] Google Play / Market (market://details?id=pkg)")
            print("    [b] Geographic Coordinates (geo:37.7749,-122.4194?z=15)")
            print("    [c] Telephone Dial (tel:+18005550199)")
            print("    [d] Email Draft (mailto:support@example.com?subject=Help)")
            sub_c = ui.get_choice("Select preset")
            if sub_c == "a":
                p = ui.get_choice("Package name")
                url = f"market://details?id={p}"
            elif sub_c == "b":
                coords = ui.get_choice("Coordinates [Default: 37.7749,-122.4194]") or "37.7749,-122.4194"
                url = f"geo:{coords}?z=12"
            elif sub_c == "c":
                num = ui.get_choice("Phone number") or "+18005550199"
                url = f"tel:{num}"
            elif sub_c == "d":
                em = ui.get_choice("Email address") or "support@example.com"
                url = f"mailto:{em}"

        if not url:
            ui.error("URL cannot be empty.")
            return

        cmd: List[str] = ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url]

        target_pkg = ui.get_choice("Target specific package? (Press Enter for system default resolver)")
        if target_pkg:
            cmd += ["-p", target_pkg]

        if ui.confirm("Add BROWSABLE category constraint?"):
            cmd += ["-c", "android.intent.category.BROWSABLE"]

        cmd.append("-W")  # Measure launch performance

        ui.info(f"Firing Deep Link: {url}")
        start_t = time.time()
        ok, out = adb.run(cmd, timeout=15)
        duration = (time.time() - start_t) * 1000

        if ok:
            ui.success(f"Deep link resolved successfully (~{duration:.0f} ms):")
            print(f"\n{out}\n")
        else:
            ui.error(f"Failed to dispatch deep link:\n{out}")

    elif choice == "4":
        pkg = _select_or_search_package("Package to verify App Links domain status")
        if not pkg:
            return

        # Try modern Android 12+ pm get-app-links first
        ok, out = adb.run(["shell", "pm", "get-app-links", pkg], timeout=10)
        if ok and out:
            ui.header(f"App Link Domain Verification for {pkg}:")
            print(out)
        else:
            # Fallback for older Android releases
            ok_dump, out_dump = adb.run(["shell", "dumpsys", "package", "domain-preferred-apps"], timeout=10)
            if ok_dump and out_dump:
                ui.header(f"Domain Preferred Applications:")
                matching = [line for line in out_dump.splitlines() if pkg in line]
                if matching:
                    for line in matching:
                        print(f"  {line}")
                else:
                    print(out_dump[:800])
            else:
                ui.warning(f"Domain verification data not available on this Android build.")

    elif choice == "5":
        pkg = _select_or_search_package("Package to set link handling preference")
        if not pkg:
            return
        state = ui.confirm("Always open supported links in this application?")
        domain = ui.get_choice("Domain to configure [or press Enter for 'all']") or "all"
        state_str = "always" if state else "never"
        ok, out = adb.run(["shell", "pm", "set-app-links-user-selection", "--package", pkg, state_str, domain], timeout=10)
        if ok:
            ui.success(f"Configured app link preference for '{pkg}' ({domain} -> {state_str}).")
        else:
            ui.error(f"Failed to update preference:\n{out}")
    else:
        ui.error("Invalid choice.")


# ─── 7. Content Provider Query ────────────────────────────────────────────────

def query_content_provider():
    """Query data from Android Content Providers using URI endpoints."""
    if not ensure_device():
        return

    ui.header("Content Provider Query Tool")
    print("  [1]  Contacts Directory (content://contacts/phones)")
    print("  [2]  Contacts Raw Data (content://com.android.contacts/data)")
    print("  [3]  SMS Inbox (content://sms/inbox)")
    print("  [4]  SMS Sent (content://sms/sent)")
    print("  [5]  Call History Logs (content://call_log/calls)")
    print("  [6]  MediaStore - Images (content://media/external/images/media)")
    print("  [7]  MediaStore - Audio Tracks (content://media/external/audio/media)")
    print("  [8]  MediaStore - Video Clips (content://media/external/video/media)")
    print("  [9]  Calendar Events (content://com.android.calendar/events)")
    print("  [10] System Settings Provider (content://settings/system)")
    print("  [11] Global Settings Provider (content://settings/global)")
    print("  [12] Custom Content URI Query")
    print()

    choice = ui.get_choice("Select provider URI")
    uri_map = {
        "1": "content://contacts/phones",
        "2": "content://com.android.contacts/data",
        "3": "content://sms/inbox",
        "4": "content://sms/sent",
        "5": "content://call_log/calls",
        "6": "content://media/external/images/media",
        "7": "content://media/external/audio/media",
        "8": "content://media/external/video/media",
        "9": "content://com.android.calendar/events",
        "10": "content://settings/system",
        "11": "content://settings/global",
    }

    uri = uri_map.get(choice)
    if not uri:
        if choice == "12":
            uri = ui.get_choice("Enter full content URI [e.g. content://my.authority/items]")
        else:
            ui.error("Invalid choice.")
            return

    if not uri:
        return

    cmd = ["shell", "content", "query", "--uri", uri]

    proj = ui.get_choice("Projection columns [optional, colon-separated, e.g. name:number]")
    if proj:
        cmd += ["--projection", proj]

    where_clause = ui.get_choice("Where clause [optional, e.g. type=1]")
    if where_clause:
        cmd += ["--where", where_clause]

    sort_order = ui.get_choice("Sort order [optional, e.g. date DESC]")
    if sort_order:
        cmd += ["--sort", sort_order]

    ui.info(f"Querying: adb {' '.join(cmd)}")
    ok, out = adb.run(cmd, timeout=20)

    if not ok:
        ui.error(f"Content provider query failed:\n{out}")
        return

    if not out.strip() or "No result found" in out:
        ui.warning("Query executed successfully, but returned 0 rows.")
        return

    lines = [line.strip() for line in out.splitlines() if line.strip()]
    row_lines = [l for l in lines if l.startswith("Row:")]

    ui.header(f"Query Results ({len(row_lines)} rows returned):")
    print()

    max_display = 20
    for r in row_lines[:max_display]:
        print(f"  {ui.Colors.CYAN}{r[:120]}{ui.Colors.RESET}")
    if len(row_lines) > max_display:
        print(f"\n  {ui.Colors.DIM}... and {len(row_lines) - max_display} more rows (total: {len(row_lines)}){ui.Colors.RESET}")
    print()

    if ui.confirm("Export full query results to local text file?"):
        out_dir = _ensure_output_dir("test_reports")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_uri = re.sub(r"[^a-zA-Z0-9_]", "_", uri)
        out_file = os.path.join(out_dir, f"query_{safe_uri[:30]}_{timestamp}.txt")
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(f"URI: {uri}\n")
                f.write(f"Command: adb {' '.join(cmd)}\n")
                f.write(f"Total Rows: {len(row_lines)}\n\n")
                f.write(out)
            ui.success(f"Results exported to: {out_file}")
        except OSError as e:
            ui.error(f"Export failed: {e}")


# ─── 8. Dump App Heap ─────────────────────────────────────────────────────────

def dump_app_heap():
    """Trigger a memory heap dump (.hprof) on target app and pull to host computer."""
    if not ensure_device():
        return

    ui.header("Dump Application Heap (.hprof)")
    pkg = _select_or_search_package("Target package name for heap dump")
    if not pkg:
        ui.error("No package selected.")
        return

    pid = _get_pid_for_package(pkg)
    if not pid:
        if ui.confirm(f"App '{pkg}' is not currently running. Launch it now?"):
            launcher = _get_package_launcher_activity(pkg)
            if launcher:
                adb.run(["shell", "am", "start", "-n", launcher], timeout=10)
            else:
                adb.run(["shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"], timeout=10)
            time.sleep(2)
            pid = _get_pid_for_package(pkg)

    if not pid:
        ui.error(f"Unable to find or launch active process for '{pkg}'.")
        return

    ui.info(f"Target process: {pkg} (PID: {pid})")

    # Options
    native_heap = False
    if ui.confirm("Include native C/C++ memory heap in dump (-n flag)?"):
        native_heap = True

    device_tmp_path = f"/data/local/tmp/heap_{pkg}_{pid}.hprof"
    cmd = ["shell", "am", "dumpheap"]
    if native_heap:
        cmd.append("-n")
    cmd += [str(pid), device_tmp_path]

    ui.info(f"Generating heap snapshot on device... (Path: {device_tmp_path})")
    ok, out = adb.run(cmd, timeout=30)
    if not ok:
        ui.error(f"Failed to initiate dumpheap:\n{out}")
        return

    # Wait briefly for disk write
    ui.info("Waiting for heap dump file serialization to complete...")
    dump_ready = False
    for _ in range(15):
        time.sleep(1)
        ok_ls, out_ls = adb.run(["shell", "ls", "-l", device_tmp_path], timeout=5)
        if ok_ls and device_tmp_path in out_ls and "No such file" not in out_ls:
            dump_ready = True
            break

    if not dump_ready:
        ui.error("Heap dump file was not generated in /data/local/tmp. Process may lack permissions or already died.")
        return

    # Pull file to host
    out_dir = _ensure_output_dir("heap_dumps")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_path = os.path.join(out_dir, f"heap_{pkg}_{timestamp}.hprof")

    ui.info(f"Pulling heap file from device to: {local_path}")
    ok_pull, out_pull = adb.run(["pull", device_tmp_path, local_path], timeout=120)

    # Clean up device temp file
    adb.run(["shell", "rm", "-f", device_tmp_path], timeout=5)

    if ok_pull and os.path.exists(local_path):
        fsize = os.path.getsize(local_path)
        ui.success(f"Heap dump successfully captured! Size: {_format_bytes(fsize)}")
        ui.info(f"Local Path: {os.path.abspath(local_path)}")
        print()
        ui.header("Analysis Instructions:")
        print(f"  {ui.Colors.CYAN}1.{ui.Colors.RESET} Open directly in Android Studio via File -> Open -> select .hprof file.")
        print(f"  {ui.Colors.CYAN}2.{ui.Colors.RESET} To inspect in Eclipse Memory Analyzer (MAT), convert Dalvik HPROF first:")
        print(f"     {ui.Colors.YELLOW}hprof-conv \"{local_path}\" \"{local_path.replace('.hprof', '_mat.hprof')}\"{ui.Colors.RESET}")
    else:
        ui.error(f"Failed to pull heap file from device:\n{out_pull}")


# ─── 9. Profile Method Tracing ────────────────────────────────────────────────

def profile_method_tracing():
    """Start, stop, and retrieve method execution traces (.trace) for CPU profiling."""
    if not ensure_device():
        return

    ui.header("App Method Execution Profiling")
    print("  [1] Start Method Tracing (Detailed execution profile)")
    print("  [2] Start Sampling Method Tracing (Low overhead)")
    print("  [3] Stop Method Tracing & Pull Trace File")
    print("  [4] Inspect Profiling Status")
    print()

    choice = ui.get_choice("Select profiling action")
    if choice not in ("1", "2", "3", "4"):
        ui.error("Invalid selection.")
        return

    pkg = _select_or_search_package("Target package name")
    if not pkg:
        ui.error("No package selected.")
        return

    remote_trace = f"/data/local/tmp/trace_{pkg}.trace"

    if choice == "1":
        cmd = ["shell", "am", "profile", "start", pkg, remote_trace]
        ok, out = adb.run(cmd, timeout=10)
        if ok:
            ui.success(f"Method tracing started for '{pkg}'. Output target: {remote_trace}")
            ui.info("Perform actions in the app now, then choose option [3] to stop and pull the trace.")
        else:
            ui.error(f"Failed to start method trace:\n{out}")

    elif choice == "2":
        interval = ui.get_choice("Sampling interval in microseconds [Default: 1000]") or "1000"
        cmd = ["shell", "am", "profile", "start", "--sampling", interval, pkg, remote_trace]
        ok, out = adb.run(cmd, timeout=10)
        if ok:
            ui.success(f"Sampling tracing started for '{pkg}' ({interval} µs interval).")
        else:
            ui.error(f"Failed to start sampling trace:\n{out}")

    elif choice == "3":
        ui.info(f"Stopping method profiling for '{pkg}'...")
        adb.run(["shell", "am", "profile", "stop", pkg], timeout=10)
        time.sleep(2)  # Flush buffers

        out_dir = _ensure_output_dir("trace_profiles")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        local_path = os.path.join(out_dir, f"trace_{pkg}_{timestamp}.trace")

        ui.info("Pulling trace file to host computer...")
        ok_pull, out_pull = adb.run(["pull", remote_trace, local_path], timeout=60)
        adb.run(["shell", "rm", "-f", remote_trace], timeout=5)

        if ok_pull and os.path.exists(local_path):
            sz = os.path.getsize(local_path)
            ui.success(f"Trace captured successfully! Size: {_format_bytes(sz)}")
            ui.info(f"Local file: {os.path.abspath(local_path)}")
            ui.info("Tip: Drag and drop this file into Android Studio Profiler or Perfetto (https://ui.perfetto.dev).")
        else:
            ui.error(f"Failed to retrieve trace file. Process may not have been actively profiled.\n{out_pull}")

    elif choice == "4":
        ok, out = adb.run(["shell", "ls", "-lh", remote_trace], timeout=5)
        if ok and "No such file" not in out:
            ui.info(f"Active trace file exists on device:\n{out}")
        else:
            ui.info(f"No active trace file detected at {remote_trace}.")


# ─── 10. Set App Debug Mode ───────────────────────────────────────────────────

def configure_debug_mode():
    """Configure wait-for-debugger flags, list JDWP sockets, and forward debug ports."""
    if not ensure_device():
        return

    ui.header("Application Debug Mode & JDWP Setup")
    print("  [1] Wait for Debugger on Launch (am set-debug-app -w)")
    print("  [2] Wait for Debugger Persistently across Reboots (--persistent)")
    print("  [3] Enable Debug App without Waiting")
    print("  [4] Clear Debug App Configuration (am clear-debug-app)")
    print("  [5] List Active JDWP Debuggable Process IDs")
    print("  [6] Forward JDWP Port to Localhost (adb forward tcp:<port> jdwp:<pid>)")
    print()

    choice = ui.get_choice("Select debug mode action")

    if choice in ("1", "2", "3"):
        pkg = _select_or_search_package("Target package to configure for debugging")
        if not pkg:
            return

        cmd = ["shell", "am", "set-debug-app"]
        if choice in ("1", "2"):
            cmd.append("-w")
        if choice == "2":
            cmd.append("--persistent")
        cmd.append(pkg)

        ok, out = adb.run(cmd, timeout=10)
        if ok:
            ui.success(f"Debug mode set for '{pkg}'.")
            if "-w" in cmd:
                ui.info("When launched, the app will freeze at startup showing 'Waiting for Debugger'.")
        else:
            ui.error(f"Failed to set debug mode:\n{out}")

    elif choice == "4":
        ok, out = adb.run(["shell", "am", "clear-debug-app"], timeout=10)
        if ok:
            ui.success("Cleared all debug app settings. Apps will launch normally.")
        else:
            ui.error(f"Failed to clear debug app:\n{out}")

    elif choice == "5":
        ui.info("Scanning for debuggable processes (adb jdwp)...")
        ok, out = adb.run(["jdwp"], timeout=8)
        if ok and out.strip():
            pids = out.strip().splitlines()
            ui.header(f"Active JDWP Debuggable Processes ({len(pids)} total):")
            rows = []
            for p in pids[:25]:
                # Identify package for PID
                ok_name, p_name = adb.run(["shell", "cat", f"/proc/{p}/cmdline"], timeout=3)
                clean_name = p_name.replace("\x00", " ").strip() if ok_name else "Unknown"
                rows.append((p, clean_name))
            ui.print_table(rows, ("PID", "Process / Package Name"))
        else:
            ui.warning("No JDWP debuggable processes detected (apps must have android:debuggable='true').")

    elif choice == "6":
        pid_str = ui.get_choice("Enter target process PID for JDWP attachment")
        port_str = ui.get_choice("Local TCP port to listen on [Default: 8700]") or "8700"
        ok, out = adb.run(["forward", f"tcp:{port_str}", f"jdwp:{pid_str}"], timeout=10)
        if ok:
            ui.success(f"Forwarded localhost:{port_str} -> JDWP process PID {pid_str}.")
            ui.info("You can now connect JDB or your IDE debugger to localhost:" + port_str)
        else:
            ui.error(f"Port forwarding failed:\n{out}")
    else:
        ui.error("Invalid choice.")


# ─── 11. Clear and Restart App ────────────────────────────────────────────────

def clear_and_restart_app():
    """Clear app data, force-stop, and benchmark cold startup performance."""
    if not ensure_device():
        return

    ui.header("Clear Data & Cold Restart Benchmark")
    pkg = _select_or_search_package("Package to clear and relaunch")
    if not pkg:
        ui.error("No package selected.")
        return

    pid_before = _get_pid_for_package(pkg)
    mem_before = _get_meminfo_summary(pkg) if pid_before else {}

    ui.info(f"Force-stopping '{pkg}'...")
    adb.run(["shell", "am", "force-stop", pkg], timeout=10)

    ui.info(f"Clearing user data and application caches (pm clear)...")
    ok_clr, out_clr = adb.run(["shell", "pm", "clear", pkg], timeout=15)
    if not ok_clr or "Success" not in out_clr:
        ui.warning(f"pm clear returned: {out_clr}")
    else:
        ui.success("Application data wiped clean.")

    # Locate launcher activity
    launcher = _get_package_launcher_activity(pkg)
    launch_cmd = ["shell", "am", "start", "-W"]
    if launcher:
        launch_cmd += ["-n", launcher]
    else:
        launch_cmd += ["-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", "-p", pkg]

    ui.info(f"Cold launching '{pkg}' and measuring launch duration...")
    ok_start, out_start = adb.run(launch_cmd, timeout=25)

    # Measure new memory footprint
    time.sleep(1.5)
    pid_after = _get_pid_for_package(pkg)
    mem_after = _get_meminfo_summary(pkg) if pid_after else {}

    # Parse timing metrics
    this_time = "N/A"
    total_time = "N/A"
    wait_time = "N/A"
    status = "N/A"

    if ok_start and out_start:
        for line in out_start.splitlines():
            line_str = line.strip()
            if line_str.startswith("Status:"):
                status = line_str.split(":", 1)[1].strip()
            elif line_str.startswith("ThisTime:"):
                this_time = line_str.split(":", 1)[1].strip() + " ms"
            elif line_str.startswith("TotalTime:"):
                total_time = line_str.split(":", 1)[1].strip() + " ms"
            elif line_str.startswith("WaitTime:"):
                wait_time = line_str.split(":", 1)[1].strip() + " ms"

    ui.header("Cold Launch Benchmark Telemetry:")
    print()
    ui.print_kv({
        "Package": pkg,
        "Launcher Component": launcher or "Resolved dynamically",
        "Launch Status": status,
        "ThisTime (Activity Drawn)": this_time,
        "TotalTime (App Launch)": f"{ui.Colors.GREEN}{total_time}{ui.Colors.RESET}",
        "WaitTime (Total Windowing)": wait_time,
        "Initial PSS Memory": mem_before.get("Total PSS", "N/A"),
        "Cold Launch PSS Memory": mem_after.get("Total PSS", "N/A"),
        "New Process PID": pid_after or "Failed to start",
    })
    print()
    if ok_start:
        ui.success("Application successfully reset and launched.")
    else:
        ui.error(f"Launch encountered issues:\n{out_start}")


# ─── 12. Simulate Low Memory ──────────────────────────────────────────────────

def simulate_low_memory():
    """Trigger memory pressure callbacks on an app via send-trim-memory."""
    if not ensure_device():
        return

    ui.header("Simulate Low Memory Pressure (send-trim-memory)")
    pkg = _select_or_search_package("Target package to test memory pressure")
    if not pkg:
        ui.error("No package selected.")
        return

    pid = _get_pid_for_package(pkg)
    if not pid:
        ui.error(f"App '{pkg}' is not running. Please launch it before trimming memory.")
        return

    mem_before = _get_meminfo_summary(str(pid))
    ui.info(f"Target process: {pkg} (PID: {pid})")
    ui.info(f"Current PSS Memory: {mem_before.get('Total PSS', 'N/A')} | Private Dirty: {mem_before.get('Private Dirty', 'N/A')}")
    print()

    print("  [1] COMPLETE         — Process is in LRU list, system is near OOM")
    print("  [2] MODERATE         — Process is in LRU list, system is low on memory")
    print("  [3] BACKGROUND       — Process has entered background LRU list")
    print("  [4] UI_HIDDEN        — Process UI is no longer visible (free UI assets)")
    print("  [5] RUNNING_CRITICAL — Process is running, device is critically low on RAM")
    print("  [6] RUNNING_LOW      — Process is running, device is low on RAM")
    print("  [7] RUNNING_MODERATE — Process is running, moderate memory pressure")
    print()

    level_map = {
        "1": "COMPLETE",
        "2": "MODERATE",
        "3": "BACKGROUND",
        "4": "UI_HIDDEN",
        "5": "RUNNING_CRITICAL",
        "6": "RUNNING_LOW",
        "7": "RUNNING_MODERATE",
    }

    choice = ui.get_choice("Select memory trim level [Default: 1]")
    level = level_map.get(choice, "COMPLETE")

    ui.info(f"Dispatching send-trim-memory {level} to PID {pid}...")
    ok, out = adb.run(["shell", "am", "send-trim-memory", str(pid), level], timeout=10)

    if not ok:
        ui.error(f"Failed to send trim memory:\n{out}")
        return

    time.sleep(2)  # Allow onTrimMemory callback to execute
    mem_after = _get_meminfo_summary(str(pid))

    ui.header("Memory Trim Telemetry Comparison:")
    print()
    ui.print_kv({
        "Target PID": pid,
        "Trim Level Dispatched": level,
        "PSS Before Trim": mem_before.get("Total PSS", "N/A"),
        "PSS After Trim": mem_after.get("Total PSS", "N/A"),
        "Dalvik Heap Before": mem_before.get("Dalvik Heap", "N/A"),
        "Dalvik Heap After": mem_after.get("Dalvik Heap", "N/A"),
        "Private Dirty Before": mem_before.get("Private Dirty", "N/A"),
        "Private Dirty After": mem_after.get("Private Dirty", "N/A"),
    })
    print()
    ui.success("onTrimMemory event dispatched. Verify how your app responds to resource constraints.")


# ─── 13. View App Crash History ───────────────────────────────────────────────

def view_crash_history():
    """Inspect application crashes, ANRs, and tombstones recorded in Dropbox and Logcat."""
    if not ensure_device():
        return

    ui.header("App Crash History & ANR Diagnostics")
    print("  [1] List Recent App Crashes (dumpsys dropbox data_app_crash)")
    print("  [2] List Recent Application ANRs (dumpsys dropbox data_app_anr)")
    print("  [3] List Native Crashes & Tombstones (data_app_native_crash)")
    print("  [4] Filter Crash History by Specific Package")
    print("  [5] Dump Active Logcat Crash Buffer (logcat -b crash)")
    print("  [6] Clear Dropbox Crash History")
    print("  [7] Export All Crash Logs to Local Directory")
    print()

    choice = ui.get_choice("Select crash diagnostic action")

    if choice in ("1", "2", "3", "4"):
        tag = ""
        if choice == "1":
            tag = "data_app_crash"
        elif choice == "2":
            tag = "data_app_anr"
        elif choice == "3":
            tag = "data_app_native_crash"

        pkg_filter = ""
        if choice == "4":
            pkg_filter = ui.get_choice("Enter package name to filter crashes")
            if not pkg_filter:
                return

        ui.info("Querying system Dropbox manager for recorded crash events...")
        ok, out = adb.run(["shell", "dumpsys", "dropbox", "--print"] + ([tag] if tag else []), timeout=25)

        if not ok or not out:
            ui.warning("No crash records retrieved from Dropbox service.")
            return

        entries = out.split("========================================")
        filtered_entries = []

        for e in entries:
            clean_e = e.strip()
            if not clean_e:
                continue
            if pkg_filter and pkg_filter.lower() not in clean_e.lower():
                continue
            filtered_entries.append(clean_e)

        if not filtered_entries:
            ui.success("No matching crash or ANR entries found in Dropbox!")
            return

        ui.header(f"Found {len(filtered_entries)} Crash Records:")
        print()

        for idx, entry in enumerate(filtered_entries[:15], 1):
            lines = entry.splitlines()
            hdr = lines[0] if lines else "Entry"
            details = "\n".join(lines[1:5])
            print(f"  {ui.Colors.YELLOW}[{idx:>2}]{ui.Colors.RESET} {ui.Colors.BOLD}{hdr}{ui.Colors.RESET}")
            print(f"     {details}")
            print()

        inspect_idx = ui.get_choice("Enter entry number to view full stack trace (or 0 to skip)")
        try:
            val = int(inspect_idx) - 1
            if 0 <= val < len(filtered_entries):
                ui.header(f"Full Crash Dump Entry #{val + 1}:")
                print(f"\n{filtered_entries[val]}\n")
        except ValueError:
            pass

    elif choice == "5":
        ui.info("Reading crash buffer from logcat...")
        ok, out = adb.run(["shell", "logcat", "-b", "crash", "-d", "-v", "time"], timeout=15)
        if ok and out.strip():
            ui.header("Logcat Crash Buffer Dump:")
            lines = out.splitlines()
            for line in lines[-40:]:
                print(f"  {line}")
            if len(lines) > 40:
                ui.info(f"... showing last 40 of {len(lines)} lines from crash buffer.")
        else:
            ui.success("Logcat crash buffer is completely clean (no recent unhandled exceptions).")

    elif choice == "6":
        if ui.confirm("Clear all Dropbox crash logs from device?"):
            ok, out = adb.run(["shell", "dumpsys", "dropbox", "--empty"], timeout=10)
            if ok:
                ui.success("Dropbox crash logs emptied successfully.")
            else:
                ui.error(f"Failed to clear Dropbox:\n{out}")

    elif choice == "7":
        out_dir = _ensure_output_dir("crash_reports")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        crash_file = os.path.join(out_dir, f"all_crashes_{timestamp}.log")

        ui.info("Exporting Dropbox crash logs and logcat buffer...")
        ok_db, out_db = adb.run(["shell", "dumpsys", "dropbox", "--print"], timeout=30)
        ok_log, out_log = adb.run(["shell", "logcat", "-b", "crash", "-d"], timeout=15)

        try:
            with open(crash_file, "w", encoding="utf-8") as f:
                f.write(f"=== SYSTEM DROPBOX CRASH DUMP ===\n{out_db}\n\n")
                f.write(f"=== LOGCAT CRASH BUFFER ===\n{out_log}\n")
            ui.success(f"Crash logs exported successfully to: {crash_file}")
        except OSError as e:
            ui.error(f"Failed to write crash export: {e}")
    else:
        ui.error("Invalid choice.")


# ─── 14. Trigger Garbage Collection ───────────────────────────────────────────

def trigger_garbage_collection():
    """Force an immediate ART / Dalvik garbage collection cycle via SIGUSR1."""
    if not ensure_device():
        return

    ui.header("Force ART Garbage Collection (SIGUSR1 / Signal 10)")
    pkg = _select_or_search_package("Target package to trigger GC")
    if not pkg:
        ui.error("No package selected.")
        return

    pid = _get_pid_for_package(pkg)
    if not pid:
        ui.error(f"Application '{pkg}' is not actively running.")
        return

    ui.info(f"Target process: {pkg} (PID: {pid})")
    mem_before = _get_meminfo_summary(str(pid))

    # Signal 10 in Linux/Android is SIGUSR1 which requests ART/Dalvik to run explicit GC
    ui.info(f"Sending SIGUSR1 (Signal 10) to PID {pid} to force GC...")
    ok, out = adb.run(["shell", "kill", "-10", str(pid)], timeout=5)

    if not ok:
        # Fallback to dumpheap without file or cmd activity
        adb.run(["shell", "cmd", "activity", "dumpheap", "-n", str(pid)], timeout=5)

    time.sleep(1.5)  # Allow GC pass to finish
    mem_after = _get_meminfo_summary(str(pid))

    # Check logcat for recent GC output
    ok_gc_log, out_gc_log = adb.run(["shell", "logcat", "-d", "-s", "art:I", "dalvikvm:I", "-t", "10"], timeout=5)

    ui.header("Garbage Collection Telemetry Results:")
    print()
    ui.print_kv({
        "Process PID": pid,
        "PSS Memory Before GC": mem_before.get("Total PSS", "N/A"),
        "PSS Memory After GC": mem_after.get("Total PSS", "N/A"),
        "Dalvik Heap Before": mem_before.get("Dalvik Heap", "N/A"),
        "Dalvik Heap After": mem_after.get("Dalvik Heap", "N/A"),
        "Native Heap Before": mem_before.get("Native Heap", "N/A"),
        "Native Heap After": mem_after.get("Native Heap", "N/A"),
    })
    print()

    if ok_gc_log and out_gc_log.strip():
        ui.header("Recent ART GC Logcat Messages:")
        for line in out_gc_log.splitlines()[-4:]:
            print(f"  {ui.Colors.CYAN}{line}{ui.Colors.RESET}")
        print()

    ui.success("Garbage collection triggered on target process.")


# ─── 15. App Standby & Doze Mode Tester ────────────────────────────────────────

def test_app_standby_and_doze():
    """Inspect and configure App Standby Buckets and test Doze idle states."""
    if not ensure_device():
        return

    ui.header("App Standby Buckets & Doze Mode Simulation")
    print("  [1] Query App Standby Bucket (am get-standby-bucket)")
    print("  [2] Set App Standby Bucket (active, working_set, frequent, rare, restricted)")
    print("  [3] Force Device into Doze Mode (dumpsys deviceidle force-idle)")
    print("  [4] Exit / Unforce Doze Mode (dumpsys deviceidle unforce)")
    print("  [5] Step Through Doze State Machine (dumpsys deviceidle step)")
    print("  [6] Simulate Battery Unplugged (dumpsys battery unplug)")
    print("  [7] Reset Battery Emulation to Normal (dumpsys battery reset)")
    print("  [8] Inspect Device Idle Whitelist (dumpsys deviceidle whitelist)")
    print()

    choice = ui.get_choice("Select Standby/Doze option")

    if choice == "1":
        pkg = _select_or_search_package("Package to check Standby Bucket")
        if not pkg:
            return
        ok, out = adb.run(["shell", "am", "get-standby-bucket", pkg], timeout=8)
        if ok:
            bucket_num = out.strip()
            bucket_names = {
                "10": "ACTIVE (No restrictions)",
                "20": "WORKING_SET (Mild deferral)",
                "30": "FREQUENT (Jobs deferred up to 6 hours)",
                "40": "RARE (Strict deferral, alarms deferred up to 24 hours)",
                "45": "RESTRICTED (Extremely heavy background limits)",
                "50": "NEVER (Never used)",
            }
            desc = bucket_names.get(bucket_num, "Custom / Unknown")
            ui.success(f"Standby Bucket for '{pkg}': {bucket_num} ({desc})")
        else:
            ui.error(f"Failed to read standby bucket:\n{out}")

    elif choice == "2":
        pkg = _select_or_search_package("Package to update Standby Bucket")
        if not pkg:
            return
        print("    [1] active       (Bucket 10)")
        print("    [2] working_set  (Bucket 20)")
        print("    [3] frequent     (Bucket 30)")
        print("    [4] rare         (Bucket 40)")
        print("    [5] restricted   (Bucket 45)")
        b_c = ui.get_choice("Select bucket")
        b_map = {"1": "active", "2": "working_set", "3": "frequent", "4": "rare", "5": "restricted"}
        b_name = b_map.get(b_c, "active")

        ok, out = adb.run(["shell", "am", "set-standby-bucket", pkg, b_name], timeout=8)
        if ok:
            ui.success(f"Updated standby bucket of '{pkg}' to '{b_name}'.")
        else:
            ui.error(f"Failed to set bucket:\n{out}")

    elif choice == "3":
        ui.info("Simulating battery unplugged and forcing Doze idle state...")
        adb.run(["shell", "dumpsys", "battery", "unplug"], timeout=5)
        ok, out = adb.run(["shell", "dumpsys", "deviceidle", "force-idle"], timeout=8)
        if ok:
            ui.success(f"Device forced into Doze Mode:\n{out}")
            ui.info("Background jobs, alarms, and network access for non-whitelisted apps are now suspended.")
        else:
            ui.error(f"Failed to force Doze:\n{out}")

    elif choice == "4":
        ui.info("Restoring normal power state...")
        adb.run(["shell", "dumpsys", "deviceidle", "unforce"], timeout=5)
        adb.run(["shell", "dumpsys", "battery", "reset"], timeout=5)
        ui.success("Doze mode unforced and battery state reset to normal.")

    elif choice == "5":
        ok, out = adb.run(["shell", "dumpsys", "deviceidle", "step"], timeout=5)
        ui.info(f"Stepped device idle state: {out.strip() if ok else 'Failed'}")

    elif choice == "6":
        ok, out = adb.run(["shell", "dumpsys", "battery", "unplug"], timeout=5)
        if ok:
            ui.success("Battery simulated as UNPLUGGED.")
        else:
            ui.error("Failed to unplug battery.")

    elif choice == "7":
        ok, out = adb.run(["shell", "dumpsys", "battery", "reset"], timeout=5)
        if ok:
            ui.success("Battery simulation reset to actual physical state.")
        else:
            ui.error("Failed to reset battery.")

    elif choice == "8":
        ok, out = adb.run(["shell", "dumpsys", "deviceidle", "whitelist"], timeout=10)
        if ok:
            ui.header("Device Idle Battery Whitelist:")
            print(out)
        else:
            ui.error("Failed to query whitelist.")
    else:
        ui.error("Invalid choice.")


# ─── 16. Runtime Permissions Test Manager ─────────────────────────────────────

def manage_runtime_permissions():
    """Inspect, grant, and revoke app runtime permissions in batch for edge-case testing."""
    if not ensure_device():
        return

    ui.header("Runtime Permissions Testing Manager")
    pkg = _select_or_search_package("Target package name")
    if not pkg:
        ui.error("No package selected.")
        return

    print("  [1] Inspect All Requested & Granted Permissions")
    print("  [2] Grant All Requested Runtime Permissions")
    print("  [3] Revoke All Runtime Permissions (Test Missing Permission UX)")
    print("  [4] Toggle Specific Permission (Camera, Location, Storage, etc.)")
    print("  [5] Reset All App Permissions to Default (pm reset-permissions)")
    print()

    choice = ui.get_choice("Select permission action")

    if choice == "1":
        ok, out = adb.run(["shell", "dumpsys", "package", pkg], timeout=15)
        if not ok or not out:
            ui.error("Failed to query package dump.")
            return

        ui.header(f"Permission Matrix for {pkg}:")
        in_perm = False
        perm_lines = []
        for line in out.splitlines():
            if "runtime permissions:" in line.lower() or "requested permissions:" in line.lower():
                in_perm = True
            elif in_perm and line.strip().endswith(":") and not line.strip().startswith("android.permission"):
                if "install permissions:" not in line.lower():
                    in_perm = False
            if in_perm:
                perm_lines.append(line)

        if perm_lines:
            for l in perm_lines[:45]:
                print(f"  {l}")
            if len(perm_lines) > 45:
                print(f"  {ui.Colors.DIM}... and {len(perm_lines) - 45} more entries{ui.Colors.RESET}")
        else:
            ui.info("No runtime permissions table found in package dump.")

    elif choice == "2":
        common_perms = [
            "android.permission.CAMERA",
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.RECORD_AUDIO",
            "android.permission.READ_CONTACTS",
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.POST_NOTIFICATIONS",
        ]
        ui.info(f"Granting core runtime permissions to '{pkg}'...")
        granted = 0
        for p in common_perms:
            ok, _ = adb.run(["shell", "pm", "grant", pkg, p], timeout=5)
            if ok:
                granted += 1
        ui.success(f"Granted {granted} permissions to '{pkg}'.")

    elif choice == "3":
        common_perms = [
            "android.permission.CAMERA",
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.RECORD_AUDIO",
            "android.permission.READ_CONTACTS",
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.POST_NOTIFICATIONS",
        ]
        ui.info(f"Revoking core runtime permissions from '{pkg}'...")
        revoked = 0
        for p in common_perms:
            ok, _ = adb.run(["shell", "pm", "revoke", pkg, p], timeout=5)
            if ok:
                revoked += 1
        ui.success(f"Revoked {revoked} permissions from '{pkg}'. Test app behavior when permissions are denied.")

    elif choice == "4":
        print("    [1] Camera (android.permission.CAMERA)")
        print("    [2] Fine Location (android.permission.ACCESS_FINE_LOCATION)")
        print("    [3] Audio Recording (android.permission.RECORD_AUDIO)")
        print("    [4] Read Contacts (android.permission.READ_CONTACTS)")
        print("    [5] Notifications (android.permission.POST_NOTIFICATIONS)")
        print("    [6] Custom Permission String")
        sub_c = ui.get_choice("Select permission to toggle")
        perm_map = {
            "1": "android.permission.CAMERA",
            "2": "android.permission.ACCESS_FINE_LOCATION",
            "3": "android.permission.RECORD_AUDIO",
            "4": "android.permission.READ_CONTACTS",
            "5": "android.permission.POST_NOTIFICATIONS",
        }
        target_perm = perm_map.get(sub_c)
        if not target_perm:
            target_perm = ui.get_choice("Enter full permission string")
        if not target_perm:
            return

        grant = ui.confirm(f"Grant '{target_perm}'? (Choose 'n' to Revoke)")
        action_verb = "grant" if grant else "revoke"
        ok, out = adb.run(["shell", "pm", action_verb, pkg, target_perm], timeout=8)
        if ok:
            ui.success(f"Successfully executed pm {action_verb} for '{target_perm}'.")
        else:
            ui.error(f"Failed to {action_verb} permission:\n{out}")

    elif choice == "5":
        ok, out = adb.run(["shell", "pm", "reset-permissions"], timeout=10)
        if ok:
            ui.success("Reset all runtime permissions across system to default state.")
        else:
            ui.error(f"Failed to reset permissions:\n{out}")
    else:
        ui.error("Invalid choice.")


# ─── Main Module Menu Loop ───────────────────────────────────────────────────

def app_testing_menu():
    """Main menu dispatch loop for App Testing & Debugging Tools."""
    while True:
        ui.clear()
        ui.print_banner()
        ui.print_device_status(adb.serial, adb.getprop("ro.product.model") if adb.serial else "")
        ui.print_sub_banner("App Testing & QA Debugger", "🧪")

        options = [
            "Monkey test (random UI event fuzzing)",
            "High-volume stress test (10,000+ events & report)",
            "Send intent (presets & custom intent builder)",
            "Send broadcast (system & custom broadcast wizard)",
            "Start / stop specific service (background/foreground)",
            "Deep link & App Link tester (URI validation)",
            "Content provider query (contacts, SMS, media, custom)",
            "Dump app heap (.hprof memory snapshot)",
            "Profile method tracing (start / stop execution trace)",
            "Set app debug mode (wait-for-debugger & JDWP)",
            "Clear & cold restart benchmark (cold launch timings)",
            "Simulate low memory (dispatch send-trim-memory)",
            "View app crash history (Dropbox logs & logcat ANRs)",
            "Trigger garbage collection (ART / Dalvik GC cycle)",
            "App Standby & Doze tester (buckets & power idling)",
            "Runtime permissions test manager (grant/revoke batch)",
        ]

        ui.print_menu("App Testing & Debugging Tools", options, columns=2)
        choice = ui.get_choice()

        if choice == "0":
            break
        elif choice == "1":
            run_monkey_test()
        elif choice == "2":
            run_stress_test()
        elif choice == "3":
            send_custom_intent()
        elif choice == "4":
            send_custom_broadcast()
        elif choice == "5":
            manage_services()
        elif choice == "6":
            test_deep_links()
        elif choice == "7":
            query_content_provider()
        elif choice == "8":
            dump_app_heap()
        elif choice == "9":
            profile_method_tracing()
        elif choice == "10":
            configure_debug_mode()
        elif choice == "11":
            clear_and_restart_app()
        elif choice == "12":
            simulate_low_memory()
        elif choice == "13":
            view_crash_history()
        elif choice == "14":
            trigger_garbage_collection()
        elif choice == "15":
            test_app_standby_and_doze()
        elif choice == "16":
            manage_runtime_permissions()
        else:
            ui.error("Invalid option. Please try again.")

        ui.pause()
