"""DroidCommander Modules Package."""

from modules.device_info import device_info_menu
from modules.app_manager import app_manager_menu
from modules.file_manager import file_manager_menu
from modules.screen_capture import screen_capture_menu
from modules.screen_mirror import screen_mirror_menu
from modules.power_tools import power_tools_menu

__all__ = [
    "device_info_menu",
    "app_manager_menu",
    "file_manager_menu",
    "screen_capture_menu",
    "screen_mirror_menu",
    "power_tools_menu",
]


