"""
core/ui.py — Premium Terminal UI: colors, menus, banners, prompts, animations.
"""

import os
import sys
import time
import shutil


# ─── ANSI Colors ──────────────────────────────────────────────────────────────

class Colors:
    """ANSI escape codes for terminal styling."""
    # Standard
    HEADER  = "\033[95m"
    BLUE    = "\033[94m"
    CYAN    = "\033[96m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    MAGENTA = "\033[35m"
    WHITE   = "\033[97m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    UNDERLINE = "\033[4m"
    ITALIC  = "\033[3m"
    RESET   = "\033[0m"
    # Backgrounds
    BG_BLUE  = "\033[44m"
    BG_GREEN = "\033[42m"
    BG_RED   = "\033[41m"
    BG_CYAN  = "\033[46m"
    BG_YELLOW = "\033[43m"
    # 256-color accents
    ORANGE  = "\033[38;5;208m"
    PINK    = "\033[38;5;205m"
    GOLD    = "\033[38;5;220m"
    LIME    = "\033[38;5;118m"
    TEAL    = "\033[38;5;37m"
    PURPLE  = "\033[38;5;141m"


# ─── Screen ───────────────────────────────────────────────────────────────────

def clear():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def get_terminal_width() -> int:
    """Get terminal width, defaulting to 80."""
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


# ─── Animated text ────────────────────────────────────────────────────────────

def type_text(text: str, delay: float = 0.01):
    """Print text with a typewriter effect."""
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def loading_animation(msg: str = "Loading", duration: float = 1.0):
    """Show a brief loading spinner."""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    end_time = time.time() + duration
    i = 0
    while time.time() < end_time:
        print(f"\r  {Colors.CYAN}{frames[i % len(frames)]}{Colors.RESET} {msg}...", end="", flush=True)
        time.sleep(0.08)
        i += 1
    print(f"\r  {Colors.GREEN}✓{Colors.RESET} {msg}     ")


# ─── Banner ───────────────────────────────────────────────────────────────────

BANNER = f"""
{Colors.BOLD}
    {Colors.TEAL}╔══════════════════════════════════════════════════════════╗
    ║                                                          ║
    ║  {Colors.CYAN}  ██████╗ ██╗  ██╗ ██████╗ ███╗   ██╗███████╗         {Colors.TEAL}║
    ║  {Colors.CYAN}  ██╔══██╗██║  ██║██╔═══██╗████╗  ██║██╔════╝         {Colors.TEAL}║
    ║  {Colors.CYAN}  ██████╔╝███████║██║   ██║██╔██╗ ██║█████╗           {Colors.TEAL}║
    ║  {Colors.CYAN}  ██╔═══╝ ██╔══██║██║   ██║██║╚██╗██║██╔══╝           {Colors.TEAL}║
    ║  {Colors.CYAN}  ██║     ██║  ██║╚██████╔╝██║ ╚████║███████╗         {Colors.TEAL}║
    ║  {Colors.CYAN}  ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝         {Colors.TEAL}║
    ║                                                          ║
    ║  {Colors.GOLD}  ███████╗██╗   ██╗██████╗  ██████╗ ███████╗ ██████╗ ███╗   ██╗{Colors.TEAL} ║
    ║  {Colors.GOLD}  ██╔════╝██║   ██║██╔══██╗██╔════╝ ██╔════╝██╔═══██╗████╗  ██║{Colors.TEAL} ║
    ║  {Colors.GOLD}  ███████╗██║   ██║██████╔╝██║  ███╗█████╗  ██║   ██║██╔██╗ ██║{Colors.TEAL} ║
    ║  {Colors.GOLD}  ╚════██║██║   ██║██╔══██╗██║   ██║██╔══╝  ██║   ██║██║╚██╗██║{Colors.TEAL} ║
    ║  {Colors.GOLD}  ███████║╚██████╔╝██║  ██║╚██████╔╝███████╗╚██████╔╝██║ ╚████║{Colors.TEAL} ║
    ║  {Colors.GOLD}  ╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝{Colors.TEAL} ║
    ║                                                          ║
    ║  {Colors.WHITE}🏥 Advanced ADB Toolkit  •  v3.0  •  20 Modules{Colors.TEAL}        ║
    ║  {Colors.DIM}{Colors.WHITE}   250+ Commands  •  Zero Dependencies  •  Auto-Setup{Colors.TEAL}   {Colors.BOLD}║
    ╚══════════════════════════════════════════════════════════╝
{Colors.RESET}"""


def print_banner():
    """Display the premium application banner."""
    print(BANNER)


def print_sub_banner(title: str, icon: str = ""):
    """Display a section sub-banner with premium styling."""
    title_text = f"{icon}  {title}" if icon else title
    width = max(len(title_text) + 6, 48)
    print(f"\n{Colors.BOLD}{Colors.TEAL}")
    print(f"    ╔{'═' * width}╗")
    print(f"    ║  {title_text:^{width - 4}}  ║")
    print(f"    ╚{'═' * width}╝")
    print(Colors.RESET)


# ─── Menu ─────────────────────────────────────────────────────────────────────

def print_menu(title: str, options: list[str], columns: int = 1):
    """
    Display a premium formatted menu.

    Parameters
    ----------
    title : str
        Menu section title.
    options : list[str]
        List of option labels.
    columns : int
        Number of columns for layout (1 or 2).
    """
    print(f"\n  {Colors.BOLD}{Colors.TEAL}┌─ {title} ─{'─' * max(0, 40 - len(title))}┐{Colors.RESET}\n")

    if columns == 2 and len(options) > 6:
        mid = (len(options) + 1) // 2
        for i in range(mid):
            left_idx = i + 1
            left_opt = options[i]
            # Separator line
            if left_opt.startswith("──"):
                left = f"  {Colors.DIM}{'─' * 38}{Colors.RESET}"
            else:
                left = f"  {Colors.GOLD}[{left_idx:>2}]{Colors.RESET} {left_opt}"
            if i + mid < len(options):
                right_idx = i + mid + 1
                right_opt = options[i + mid]
                if right_opt.startswith("──"):
                    right = f"  {Colors.DIM}{'─' * 38}{Colors.RESET}"
                else:
                    right = f"  {Colors.GOLD}[{right_idx:>2}]{Colors.RESET} {right_opt}"
            else:
                right = ""
            print(f"{left:<48}{right}")
    else:
        for i, option in enumerate(options, 1):
            if option.startswith("──"):
                print(f"  {Colors.DIM}{'─' * 42}{Colors.RESET}")
            else:
                print(f"  {Colors.GOLD}[{i:>2}]{Colors.RESET} {option}")

    print(f"\n  {Colors.GOLD}[ 0]{Colors.RESET} ← Back / Exit")
    print(f"\n  {Colors.BOLD}{Colors.TEAL}└{'─' * 44}┘{Colors.RESET}\n")


# ─── Prompts ──────────────────────────────────────────────────────────────────

def get_choice(prompt: str = "Select option") -> str:
    """Prompt user for input with premium styled prompt."""
    try:
        return input(f"  {Colors.LIME}❯{Colors.RESET} {Colors.BOLD}{prompt}:{Colors.RESET} ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return "0"


def confirm(prompt: str = "Are you sure?") -> bool:
    """Ask for yes/no confirmation."""
    answer = get_choice(f"{prompt} (y/n)")
    return answer.lower() in ("y", "yes")


def pause():
    """Wait for the user to press Enter."""
    input(f"\n  {Colors.DIM}Press Enter to continue...{Colors.RESET}")


# ─── Messages ─────────────────────────────────────────────────────────────────

def success(msg: str):
    """Print a green success message."""
    print(f"\n  {Colors.GREEN}✓ {msg}{Colors.RESET}")


def error(msg: str):
    """Print a red error message."""
    print(f"\n  {Colors.RED}✗ {msg}{Colors.RESET}")


def info(msg: str):
    """Print a cyan info message."""
    print(f"\n  {Colors.CYAN}ℹ {msg}{Colors.RESET}")


def warning(msg: str):
    """Print a yellow warning message."""
    print(f"\n  {Colors.YELLOW}⚠ {msg}{Colors.RESET}")


def header(msg: str):
    """Print a bold header line."""
    print(f"\n  {Colors.BOLD}{msg}{Colors.RESET}")


def divider(char: str = "─", width: int = 50):
    """Print a divider line."""
    print(f"\n  {Colors.DIM}{char * width}{Colors.RESET}")


# ─── Tables ───────────────────────────────────────────────────────────────────

def print_table(rows: list[tuple], headers: tuple | None = None, indent: int = 4):
    """Print a premium styled ASCII table."""
    if not rows and not headers:
        return

    all_rows = ([headers] if headers else []) + rows
    col_widths = [
        max(len(str(row[i])) for row in all_rows)
        for i in range(len(all_rows[0]))
    ]

    pad = " " * indent
    sep_top = pad + f"{Colors.TEAL}┌" + "┬".join("─" * (w + 2) for w in col_widths) + f"┐{Colors.RESET}"
    sep_mid = pad + f"{Colors.TEAL}├" + "┼".join("─" * (w + 2) for w in col_widths) + f"┤{Colors.RESET}"
    sep_bot = pad + f"{Colors.TEAL}└" + "┴".join("─" * (w + 2) for w in col_widths) + f"┘{Colors.RESET}"

    if headers:
        print(sep_top)
        hdr = pad + f"{Colors.TEAL}│{Colors.RESET}" + f"{Colors.TEAL}│{Colors.RESET}".join(
            f" {Colors.BOLD}{Colors.GOLD}{str(h).ljust(w)}{Colors.RESET} "
            for h, w in zip(headers, col_widths)
        ) + f"{Colors.TEAL}│{Colors.RESET}"
        print(hdr)
        print(sep_mid)
    else:
        print(sep_top)

    for row in rows:
        line = pad + f"{Colors.TEAL}│{Colors.RESET}" + f"{Colors.TEAL}│{Colors.RESET}".join(
            f" {str(c).ljust(w)} " for c, w in zip(row, col_widths)
        ) + f"{Colors.TEAL}│{Colors.RESET}"
        print(line)
    print(sep_bot)


def print_kv(data: dict, indent: int = 4):
    """Print a key-value list with aligned values and premium styling."""
    if not data:
        return
    max_key = max(len(str(k)) for k in data)
    pad = " " * indent
    for k, v in data.items():
        print(f"{pad}{Colors.TEAL}{str(k).ljust(max_key)}{Colors.RESET}  {Colors.WHITE}{v}{Colors.RESET}")


# ─── Progress ─────────────────────────────────────────────────────────────────

def progress_bar(current: int, total: int, width: int = 30, label: str = ""):
    """Print a premium progress bar."""
    pct = current / total if total > 0 else 0
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    pct_str = f"{pct * 100:5.1f}%"

    if pct < 0.5:
        color = Colors.YELLOW
    elif pct < 1.0:
        color = Colors.CYAN
    else:
        color = Colors.GREEN

    text = f"  {label} [{color}{bar}{Colors.RESET}] {pct_str}"
    print(f"\r{text}", end="", flush=True)
    if current >= total:
        print()


# ─── Device status line ──────────────────────────────────────────────────────

def print_device_status(serial: str | None, model: str = ""):
    """Show the currently active device with premium badge styling."""
    if serial:
        dev = f"{serial}"
        if model:
            dev += f" ({model})"
        print(f"  {Colors.BOLD}{Colors.TEAL}┌─ Device ─────────────────────────────────┐{Colors.RESET}")
        print(f"  {Colors.TEAL}│{Colors.RESET}  🔌 {Colors.GREEN}{Colors.BOLD}{dev}{Colors.RESET}  {Colors.TEAL}│{Colors.RESET}")
        print(f"  {Colors.BOLD}{Colors.TEAL}└──────────────────────────────────────────┘{Colors.RESET}")
    else:
        print(f"  {Colors.DIM}🔌 No device selected — connect via USB or WiFi{Colors.RESET}")
