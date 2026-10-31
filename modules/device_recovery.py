"""
modules/device_recovery.py — Device Recovery Assistant.

Helps users recover access to their own devices through official
methods: recovery mode, factory reset, pre-reset backup, and
brand-specific guides with hardware button combinations.
"""

import os
import time
import webbrowser
from datetime import datetime
from core.adb import adb
from core import ui
from core.device import ensure_device


# ─── Brand-specific recovery key combos ──────────────────────────────────────

RECOVERY_COMBOS = {
    "Samsung": {
        "keys": "Power + Volume Up + Bixby (or Home)",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Volume Up + Power + Bixby/Home",
            "Release all buttons when Samsung logo appears",
            "Wait for Android Recovery menu",
            "Use Volume buttons to navigate, Power to select",
        ],
    },
    "Google Pixel": {
        "keys": "Power + Volume Down",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Power + Volume Down together",
            "Bootloader menu appears → use Volume to select 'Recovery mode'",
            "Press Power to confirm",
            "When Android robot with exclamation appears: hold Power, tap Volume Up",
        ],
    },
    "OnePlus": {
        "keys": "Power + Volume Down",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Power + Volume Down",
            "Select 'Recovery mode' from bootloader",
            "Press Power to confirm",
        ],
    },
    "Xiaomi / Redmi / POCO": {
        "keys": "Power + Volume Up",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Power + Volume Up together",
            "Release when Mi/Redmi logo appears",
            "MI Recovery menu will load",
            "Use touch or Volume buttons to navigate",
        ],
    },
    "Huawei / Honor": {
        "keys": "Power + Volume Up",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Power + Volume Up",
            "Release Power when Huawei logo appears, keep holding Volume Up",
            "EMUI Recovery menu appears",
        ],
    },
    "Motorola": {
        "keys": "Power + Volume Down",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Power + Volume Down",
            "Bootloader appears → use Volume to select 'Recovery mode'",
            "Press Power to confirm",
            "If Android robot appears: hold Power, tap Volume Up",
        ],
    },
    "LG": {
        "keys": "Power + Volume Down",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Power + Volume Down",
            "When LG logo appears: release both, then immediately re-press both",
            "Factory Reset screen appears",
        ],
    },
    "Sony Xperia": {
        "keys": "Power + Volume Down",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Power + Volume Down",
            "Wait for LED light or vibration",
            "Release and select Recovery from bootloader",
        ],
    },
    "OPPO / Realme": {
        "keys": "Power + Volume Down",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Power + Volume Down",
            "Release when logo appears",
            "ColorOS Recovery menu will load",
            "Select language, then choose option",
        ],
    },
    "Vivo": {
        "keys": "Power + Volume Up",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Power + Volume Up together",
            "Release when Vivo logo appears",
            "Recovery menu will load",
        ],
    },
    "ASUS (ROG / ZenFone)": {
        "keys": "Power + Volume Down",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Power + Volume Down",
            "Select 'Recovery mode' from bootloader menu",
            "Press Power to confirm",
        ],
    },
    "Nokia": {
        "keys": "Power + Volume Up",
        "steps": [
            "Power OFF the device completely",
            "Press and HOLD: Power + Volume Up",
            "Release when Nokia/Android logo appears",
            "Recovery menu will load",
        ],
    },
    "Other / Generic Android": {
        "keys": "Power + Volume Up  OR  Power + Volume Down",
        "steps": [
            "Power OFF the device completely",
            "Try: Press and HOLD Power + Volume Up",
            "If that doesn't work, try: Power + Volume Down",
            "Hold for 10-15 seconds until recovery/bootloader appears",
            "Navigate with Volume keys, select with Power",
        ],
    },
}

# ─── Official recovery/unlock tool links ─────────────────────────────────────

BRAND_TOOLS = {
    "Samsung": {
        "Find My Mobile": "https://findmymobile.samsung.com",
        "Smart Switch": "https://www.samsung.com/smartswitch/",
        "Odin (firmware)": "https://odindownload.com",
    },
    "Google Pixel": {
        "Find My Device": "https://www.google.com/android/find",
        "Android Flash Tool": "https://flash.android.com",
    },
    "Xiaomi / Redmi": {
        "Mi Unlock Tool": "https://en.miui.com/unlock/",
        "Mi PC Suite": "https://xiaomipctools.com",
    },
    "Huawei / Honor": {
        "HiSuite": "https://consumer.huawei.com/en/support/hisuite/",
    },
    "OnePlus": {
        "OxygenOS Updater": "https://www.oneplus.com/support",
    },
    "Motorola": {
        "Rescue & Smart Assistant": "https://www.motorola.com/us/rescue-and-smart-assistant",
    },
    "OPPO / Realme": {
        "Flash Tool": "https://www.coloros.com/topic/flashtool",
    },
    "General": {
        "Google Find My Device": "https://www.google.com/android/find",
        "Google Account Recovery": "https://accounts.google.com/signin/recovery",
    },
}


# ─── Helper: Detect brand ────────────────────────────────────────────────────

def _detect_brand() -> str:
    """Try to detect the device brand via ADB properties."""
    brand = adb.getprop("ro.product.brand").strip().lower()
    manufacturer = adb.getprop("ro.product.manufacturer").strip().lower()

    brand_map = {
        "samsung": "Samsung",
        "google": "Google Pixel",
        "oneplus": "OnePlus",
        "xiaomi": "Xiaomi / Redmi / POCO",
        "redmi": "Xiaomi / Redmi / POCO",
        "poco": "Xiaomi / Redmi / POCO",
        "huawei": "Huawei / Honor",
        "honor": "Huawei / Honor",
        "motorola": "Motorola",
        "lge": "LG",
        "lg": "LG",
        "sony": "Sony Xperia",
        "oppo": "OPPO / Realme",
        "realme": "OPPO / Realme",
        "vivo": "Vivo",
        "asus": "ASUS (ROG / ZenFone)",
        "nokia": "Nokia",
    }

    for key, name in brand_map.items():
        if key in brand or key in manufacturer:
            return name
    return "Other / Generic Android"


# ─── Menu functions ───────────────────────────────────────────────────────────

def detect_device_state():
    """Check if a device is connected and its current state."""
    ui.print_sub_banner("Device State Detection", "🔍")

    devices = adb.list_devices()
    if not devices:
        ui.error("No device detected via USB.")
        ui.info("Make sure the device is connected with a USB cable.")
        ui.info("If the device is completely unresponsive, try a forced reboot:")
        print(f"\n    {ui.Colors.YELLOW}Hold Power + Volume Down for 10-15 seconds{ui.Colors.RESET}")
        return

    for dev in devices:
        serial = dev.get("serial", "?")
        state = dev.get("state", "unknown")
        model = dev.get("model", "—")

        state_display = state
        if state == "device":
            state_display = f"{ui.Colors.GREEN}Online (ADB active){ui.Colors.RESET}"
        elif state == "recovery":
            state_display = f"{ui.Colors.YELLOW}Recovery Mode{ui.Colors.RESET}"
        elif state == "sideload":
            state_display = f"{ui.Colors.YELLOW}Sideload Mode{ui.Colors.RESET}"
        elif state == "unauthorized":
            state_display = f"{ui.Colors.RED}Unauthorized — accept USB debugging prompt on phone{ui.Colors.RESET}"
        elif state == "offline":
            state_display = f"{ui.Colors.RED}Offline{ui.Colors.RESET}"
        elif state == "bootloader":
            state_display = f"{ui.Colors.CYAN}Bootloader / Fastboot{ui.Colors.RESET}"

        ui.print_kv({
            "Serial": serial,
            "State": state_display,
            "Model": model,
        })
        print()

    online = [d for d in devices if d["state"] == "device"]
    if online:
        adb.serial = online[0]["serial"]
        brand = _detect_brand()
        model = adb.getprop("ro.product.model")
        android_ver = adb.getprop("ro.build.version.release")
        locked = "Unknown"

        # Check if screen is locked
        ok, output = adb.run_shell("dumpsys window")
        if ok:
            if "mDreamingLockscreen=true" in output or "isStatusBarKeyguard=true" in output or "mShowingLockscreen=true" in output:
                locked = f"{ui.Colors.YELLOW}Screen is LOCKED{ui.Colors.RESET}"
            else:
                locked = f"{ui.Colors.GREEN}Screen is UNLOCKED{ui.Colors.RESET}"

        ui.print_kv({
            "Brand": brand,
            "Model": model,
            "Android": android_ver,
            "Lock Status": locked,
        })


def reboot_to_recovery_adb():
    """Boot device into recovery mode via ADB."""
    ui.print_sub_banner("Boot to Recovery Mode (ADB)", "🔄")

    if not ensure_device():
        ui.info("Device not reachable via ADB. Use the manual hardware button method instead.")
        return

    brand = _detect_brand()
    model = adb.getprop("ro.product.model")
    ui.info(f"Device: {model} ({brand})")
    print()

    ui.warning("This will reboot your device into Recovery Mode.")
    ui.info("In Recovery Mode you can:")
    print(f"    {ui.Colors.CYAN}• Factory reset (Wipe data){ui.Colors.RESET}")
    print(f"    {ui.Colors.CYAN}• Wipe cache partition{ui.Colors.RESET}")
    print(f"    {ui.Colors.CYAN}• Sideload OTA updates{ui.Colors.RESET}")
    print(f"    {ui.Colors.CYAN}• Reboot to system{ui.Colors.RESET}")
    print()

    if not ui.confirm("Reboot to Recovery Mode now?"):
        ui.info("Cancelled.")
        return

    ok, output = adb.run(["reboot", "recovery"], timeout=15)
    if ok:
        ui.success("Device is rebooting to Recovery Mode...")
        ui.info("Wait 10-15 seconds for recovery menu to appear.")
        ui.info("Use Volume buttons to navigate, Power button to select.")
    else:
        ui.error(f"Failed: {output}")
        ui.info("Try the manual hardware button method instead (Option 3).")


def manual_recovery_guide():
    """Show hardware button combinations for recovery mode by brand."""
    ui.print_sub_banner("Manual Recovery Mode Guide", "📖")

    print(f"\n  {ui.Colors.BOLD}Select your device brand:{ui.Colors.RESET}\n")

    brands = list(RECOVERY_COMBOS.keys())
    for i, brand in enumerate(brands, 1):
        combo = RECOVERY_COMBOS[brand]
        print(f"  {ui.Colors.YELLOW}[{i:>2}]{ui.Colors.RESET} {brand}  {ui.Colors.DIM}({combo['keys']}){ui.Colors.RESET}")

    print()
    choice = ui.get_choice("Select brand number")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(brands):
            brand = brands[idx]
            combo = RECOVERY_COMBOS[brand]

            ui.print_sub_banner(f"{brand} — Recovery Mode", "📱")
            print(f"\n  {ui.Colors.BOLD}Key Combination:{ui.Colors.RESET} {ui.Colors.CYAN}{combo['keys']}{ui.Colors.RESET}\n")
            print(f"  {ui.Colors.BOLD}Steps:{ui.Colors.RESET}\n")
            for j, step in enumerate(combo["steps"], 1):
                print(f"    {ui.Colors.GREEN}{j}.{ui.Colors.RESET} {step}")

            print(f"\n  {ui.Colors.BOLD}{ui.Colors.YELLOW}In Recovery Menu:{ui.Colors.RESET}")
            print(f"    • {ui.Colors.CYAN}Wipe data/factory reset{ui.Colors.RESET} → Erases all data, removes lock")
            print(f"    • {ui.Colors.CYAN}Wipe cache partition{ui.Colors.RESET} → Clears cache (keeps data)")
            print(f"    • {ui.Colors.CYAN}Reboot system now{ui.Colors.RESET} → Normal restart")
            print(f"    • {ui.Colors.CYAN}Apply update from ADB{ui.Colors.RESET} → Sideload OTA")
        else:
            ui.error("Invalid selection.")
    except ValueError:
        ui.error("Invalid input.")


def auto_detect_and_guide():
    """Auto-detect brand and show the correct recovery guide."""
    ui.print_sub_banner("Auto-Detect Recovery Guide", "🤖")

    if not ensure_device():
        ui.warning("Cannot auto-detect — device not reachable via ADB.")
        ui.info("Use Option 3 (Manual Guide) to select your brand manually.")
        return

    brand = _detect_brand()
    model = adb.getprop("ro.product.model")
    android_ver = adb.getprop("ro.build.version.release")

    ui.success(f"Detected: {brand} — {model} (Android {android_ver})")

    if brand in RECOVERY_COMBOS:
        combo = RECOVERY_COMBOS[brand]
        print(f"\n  {ui.Colors.BOLD}Recovery Key Combo:{ui.Colors.RESET} {ui.Colors.CYAN}{combo['keys']}{ui.Colors.RESET}\n")
        for j, step in enumerate(combo["steps"], 1):
            print(f"    {ui.Colors.GREEN}{j}.{ui.Colors.RESET} {step}")
    else:
        combo = RECOVERY_COMBOS["Other / Generic Android"]
        print(f"\n  {ui.Colors.BOLD}Generic Recovery:{ui.Colors.RESET} {ui.Colors.CYAN}{combo['keys']}{ui.Colors.RESET}\n")
        for j, step in enumerate(combo["steps"], 1):
            print(f"    {ui.Colors.GREEN}{j}.{ui.Colors.RESET} {step}")

    print(f"\n  {ui.Colors.DIM}Or use Option 2 to reboot via ADB directly.{ui.Colors.RESET}")


def pre_reset_backup():
    """Backup accessible data before performing a factory reset."""
    ui.print_sub_banner("Pre-Reset Data Backup", "💾")

    if not ensure_device():
        ui.error("Device not reachable via ADB. Cannot perform backup.")
        return

    model = adb.getprop("ro.product.model")
    ui.info(f"Device: {model}")
    ui.info("Attempting to pull accessible data before reset...")
    print()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = f"recovery_backup_{timestamp}"
    os.makedirs(backup_dir, exist_ok=True)

    # Folders to try backing up
    folders = [
        ("/sdcard/DCIM", "Photos & Videos (DCIM)"),
        ("/sdcard/Pictures", "Pictures"),
        ("/sdcard/Download", "Downloads"),
        ("/sdcard/Documents", "Documents"),
        ("/sdcard/WhatsApp", "WhatsApp Data"),
        ("/sdcard/Music", "Music"),
    ]

    pulled = 0
    for remote_path, label in folders:
        # Check if folder exists
        ok, output = adb.run_shell(f"ls {remote_path}")
        if not ok or "No such file" in output:
            print(f"  {ui.Colors.DIM}⏭ {label}: not found{ui.Colors.RESET}")
            continue

        local_dest = os.path.join(backup_dir, os.path.basename(remote_path))
        ui.info(f"Pulling {label}...")
        ok, output = adb.run(["pull", remote_path, local_dest], timeout=300)
        if ok:
            ui.success(f"  Saved: {local_dest}")
            pulled += 1
        else:
            print(f"  {ui.Colors.RED}✗ Failed: {output}{ui.Colors.RESET}")

    # Try to pull contacts
    ui.info("Attempting to export contacts...")
    ok, output = adb.run_shell("content query --uri content://com.android.contacts/contacts --projection display_name")
    if ok and output.strip():
        contacts_file = os.path.join(backup_dir, "contacts_dump.txt")
        with open(contacts_file, "w", encoding="utf-8") as f:
            f.write(output)
        ui.success(f"  Contacts saved: {contacts_file}")
        pulled += 1
    else:
        print(f"  {ui.Colors.DIM}⏭ Contacts: not accessible{ui.Colors.RESET}")

    # Pull installed apps list
    ui.info("Saving installed apps list...")
    ok, output = adb.run(["shell", "pm", "list", "packages", "-3"])
    if ok:
        apps_file = os.path.join(backup_dir, "installed_apps.txt")
        with open(apps_file, "w", encoding="utf-8") as f:
            f.write(output)
        ui.success(f"  App list saved: {apps_file}")
        pulled += 1

    print()
    if pulled > 0:
        ui.success(f"Backup complete! {pulled} items saved to: {backup_dir}/")
    else:
        ui.warning("No data could be pulled. Device storage may not be accessible.")
    ui.info("You can now safely proceed with factory reset.")


def guided_factory_reset():
    """Guide user through factory reset options."""
    ui.print_sub_banner("Guided Factory Reset", "🏭")

    print(f"""
  {ui.Colors.BOLD}{ui.Colors.YELLOW}⚠  WARNING: Factory reset erases ALL data!{ui.Colors.RESET}
  {ui.Colors.YELLOW}   Make sure you've backed up important data first (Option 5).{ui.Colors.RESET}

  {ui.Colors.BOLD}Choose reset method:{ui.Colors.RESET}

  {ui.Colors.YELLOW}[1]{ui.Colors.RESET} Via ADB command (device must be accessible)
  {ui.Colors.YELLOW}[2]{ui.Colors.RESET} Via Recovery Mode (works when locked out)
  {ui.Colors.YELLOW}[3]{ui.Colors.RESET} Via Google Find My Device (remote)
  {ui.Colors.YELLOW}[0]{ui.Colors.RESET} Cancel
    """)

    choice = ui.get_choice()

    if choice == "1":
        _reset_via_adb()
    elif choice == "2":
        _reset_via_recovery()
    elif choice == "3":
        _reset_via_find_my_device()
    elif choice == "0":
        ui.info("Cancelled.")


def _reset_via_adb():
    """Factory reset via ADB (requires device access)."""
    if not ensure_device():
        ui.error("Device not accessible via ADB.")
        return

    ui.warning("This will ERASE ALL DATA on the device!")
    if not ui.confirm("Are you absolutely sure?"):
        ui.info("Cancelled.")
        return

    if not ui.confirm("FINAL WARNING — This cannot be undone. Continue?"):
        ui.info("Cancelled.")
        return

    ui.info("Sending factory reset command...")
    ok, output = adb.run(["shell", "am", "broadcast", "-a",
                          "android.intent.action.MASTER_CLEAR"], timeout=15)
    if ok:
        ui.success("Factory reset initiated. Device will reboot and erase all data.")
        ui.info("This process takes 2-5 minutes. Do NOT disconnect the device.")
    else:
        ui.error(f"Reset command failed: {output}")
        ui.info("Try using Recovery Mode method instead (Option 2).")


def _reset_via_recovery():
    """Guide for factory reset via recovery mode."""
    print(f"""
  {ui.Colors.BOLD}{ui.Colors.CYAN}Factory Reset via Recovery Mode:{ui.Colors.RESET}

    {ui.Colors.GREEN}1.{ui.Colors.RESET} Boot into Recovery Mode (use Option 2 or 3)
    {ui.Colors.GREEN}2.{ui.Colors.RESET} In the Recovery Menu, navigate with Volume buttons
    {ui.Colors.GREEN}3.{ui.Colors.RESET} Select {ui.Colors.YELLOW}"Wipe data/factory reset"{ui.Colors.RESET}
    {ui.Colors.GREEN}4.{ui.Colors.RESET} Confirm by selecting {ui.Colors.YELLOW}"Factory data reset"{ui.Colors.RESET}
    {ui.Colors.GREEN}5.{ui.Colors.RESET} Wait for the wipe to complete
    {ui.Colors.GREEN}6.{ui.Colors.RESET} Select {ui.Colors.YELLOW}"Reboot system now"{ui.Colors.RESET}
    {ui.Colors.GREEN}7.{ui.Colors.RESET} Device will restart fresh — set up as new

  {ui.Colors.DIM}Note: You'll need your Google account to set up after reset
  (Factory Reset Protection / FRP).{ui.Colors.RESET}
    """)


def _reset_via_find_my_device():
    """Guide for remote factory reset via Google Find My Device."""
    print(f"""
  {ui.Colors.BOLD}{ui.Colors.CYAN}Remote Factory Reset via Google Find My Device:{ui.Colors.RESET}

    {ui.Colors.GREEN}1.{ui.Colors.RESET} Open {ui.Colors.CYAN}https://www.google.com/android/find{ui.Colors.RESET}
    {ui.Colors.GREEN}2.{ui.Colors.RESET} Sign in with the Google Account linked to the device
    {ui.Colors.GREEN}3.{ui.Colors.RESET} Select your device from the list
    {ui.Colors.GREEN}4.{ui.Colors.RESET} Click {ui.Colors.YELLOW}"ERASE DEVICE"{ui.Colors.RESET}
    {ui.Colors.GREEN}5.{ui.Colors.RESET} Confirm the erase

  {ui.Colors.YELLOW}Requirements:{ui.Colors.RESET}
    • Device must be powered on
    • Device must have internet connection
    • Device must be signed into a Google Account
    • Location services should be enabled

  {ui.Colors.DIM}After erase, you'll need the original Google account
  credentials to set up the device (FRP protection).{ui.Colors.RESET}
    """)

    try:
        open_browser = ui.get_choice("Open Find My Device in browser? (y/n)")
        if open_browser.lower() in ("y", "yes"):
            webbrowser.open("https://www.google.com/android/find")
            ui.success("Opened in browser.")
    except Exception:
        pass


def brand_tools_links():
    """Show official manufacturer recovery and unlock tools."""
    ui.print_sub_banner("Official Manufacturer Tools", "🔗")

    for brand, tools in BRAND_TOOLS.items():
        print(f"\n  {ui.Colors.BOLD}{ui.Colors.CYAN}{brand}{ui.Colors.RESET}")
        for name, url in tools.items():
            print(f"    {ui.Colors.GREEN}•{ui.Colors.RESET} {name}: {ui.Colors.UNDERLINE}{url}{ui.Colors.RESET}")

    print()
    ui.info("These are official tools from device manufacturers.")
    ui.info("Use them to flash firmware, unlock bootloaders, or recover devices.")


def recovery_checklist():
    """Interactive recovery checklist."""
    ui.print_sub_banner("Recovery Checklist", "📋")

    steps = [
        ("Have you tried restarting the device?",
         "Hold Power for 10-15 seconds to force restart."),
        ("Is USB Debugging enabled?",
         "If yes, you can use ADB commands. If no, try recovery mode."),
        ("Do you remember your Google Account?",
         "You'll need it after factory reset (FRP protection)."),
        ("Have you backed up important data?",
         "Use Option 5 to pull accessible files before resetting."),
        ("Have you tried Google Find My Device?",
         "Visit google.com/android/find to remotely erase."),
        ("Have you tried the manufacturer's tool?",
         "Samsung Smart Switch, Xiaomi Mi Flash, etc. (Option 7)"),
        ("Ready to factory reset via Recovery Mode?",
         "Use Option 2 (ADB) or Option 3 (manual buttons)."),
    ]

    print()
    for i, (question, hint) in enumerate(steps, 1):
        print(f"  {ui.Colors.BOLD}{ui.Colors.YELLOW}Step {i}:{ui.Colors.RESET} {question}")
        print(f"         {ui.Colors.DIM}{hint}{ui.Colors.RESET}")
        answer = ui.get_choice("Done? (y/n/skip)")
        if answer.lower() == "y":
            print(f"         {ui.Colors.GREEN}✓ Done{ui.Colors.RESET}\n")
        elif answer.lower() == "skip":
            print(f"         {ui.Colors.YELLOW}⏭ Skipped{ui.Colors.RESET}\n")
        else:
            print(f"         {ui.Colors.CYAN}→ Try this step before continuing{ui.Colors.RESET}\n")

    ui.success("Checklist complete! Use the other options in this menu to proceed.")


def post_reset_guide():
    """Guide for setting up device after factory reset."""
    ui.print_sub_banner("Post-Reset Setup Guide", "🔄")

    print(f"""
  {ui.Colors.BOLD}{ui.Colors.CYAN}After Factory Reset — Setup Guide:{ui.Colors.RESET}

  {ui.Colors.BOLD}Step 1: Initial Setup{ui.Colors.RESET}
    • Select language and region
    • Connect to WiFi
    • Sign in with your Google Account
      {ui.Colors.DIM}(Must be the same account that was on the device — FRP){ui.Colors.RESET}

  {ui.Colors.BOLD}Step 2: Restore Data{ui.Colors.RESET}
    • When prompted, choose {ui.Colors.YELLOW}"Restore from Google Backup"{ui.Colors.RESET}
    • Select your most recent backup
    • This restores: apps, contacts, settings, WiFi passwords

  {ui.Colors.BOLD}Step 3: Restore Local Files{ui.Colors.RESET}
    • If you used Option 5 (Pre-Reset Backup):
      {ui.Colors.CYAN}adb push recovery_backup_XXXXXX/DCIM /sdcard/DCIM{ui.Colors.RESET}
      {ui.Colors.CYAN}adb push recovery_backup_XXXXXX/Pictures /sdcard/Pictures{ui.Colors.RESET}
      {ui.Colors.CYAN}adb push recovery_backup_XXXXXX/Download /sdcard/Download{ui.Colors.RESET}

  {ui.Colors.BOLD}Step 4: Re-install Apps{ui.Colors.RESET}
    • Check {ui.Colors.CYAN}recovery_backup_XXXXXX/installed_apps.txt{ui.Colors.RESET}
      for your previous app list
    • Install from Play Store or use PhoneSurgeon's App Manager

  {ui.Colors.BOLD}Step 5: Security{ui.Colors.RESET}
    • Set up a new screen lock (PIN/pattern/password)
    • Enable biometric unlock (fingerprint/face)
    • Enable Find My Device
    • Review app permissions
    """)


def wipe_cache_via_adb():
    """Wipe cache partition via ADB (doesn't erase user data)."""
    ui.print_sub_banner("Wipe Cache Partition", "🧹")

    if not ensure_device():
        ui.info("Device not accessible. Boot into recovery mode manually to wipe cache.")
        return

    ui.info("Wiping cache does NOT erase your data.")
    ui.info("It clears temporary system files and can fix boot issues.")
    print()

    if not ui.confirm("Wipe cache partition?"):
        ui.info("Cancelled.")
        return

    # Try clearing package cache
    ui.info("Clearing system cache...")

    ok1, _ = adb.run_shell("rm -rf /data/dalvik-cache/*")
    ok2, _ = adb.run_shell("pm trim-caches 999999999999")

    if ok1 or ok2:
        ui.success("Cache cleared!")
        ui.info("Reboot the device for changes to take effect.")
        reboot = ui.get_choice("Reboot now? (y/n)")
        if reboot.lower() in ("y", "yes"):
            adb.run(["reboot"])
            ui.success("Rebooting...")
    else:
        ui.warning("Could not clear cache via ADB (may need root).")
        ui.info("Boot into Recovery Mode and select 'Wipe cache partition' instead.")


# ─── Main Menu ────────────────────────────────────────────────────────────────

def device_recovery_menu():
    """Device Recovery Assistant main menu."""
    while True:
        ui.clear()
        ui.print_banner()
        ui.print_menu("🏥 Device Recovery Assistant", [
            "🔍  Detect device state",
            "🔄  Boot to Recovery Mode (via ADB)",
            "📖  Manual Recovery Mode guide (hardware buttons)",
            "🤖  Auto-detect brand & show guide",
            "💾  Pre-reset data backup",
            "🏭  Guided factory reset",
            "🔗  Official manufacturer tools & links",
            "📋  Recovery checklist (step-by-step)",
            "🔄  Post-reset setup guide",
            "🧹  Wipe cache partition",
        ])
        choice = ui.get_choice()

        if choice == "0":
            break
        elif choice == "1":
            detect_device_state()
        elif choice == "2":
            reboot_to_recovery_adb()
        elif choice == "3":
            manual_recovery_guide()
        elif choice == "4":
            auto_detect_and_guide()
        elif choice == "5":
            pre_reset_backup()
        elif choice == "6":
            guided_factory_reset()
        elif choice == "7":
            brand_tools_links()
        elif choice == "8":
            recovery_checklist()
        elif choice == "9":
            post_reset_guide()
        elif choice == "10":
            wipe_cache_via_adb()
        else:
            ui.error("Invalid option.")

        ui.pause()
