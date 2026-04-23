"""Uninstall+ - Clean uninstaller that hunts leftovers."""

import os
import sys
import winreg
import shutil
import subprocess
import threading
import json
from pathlib import Path
from typing import Optional
from datetime import datetime
import customtkinter as ctk
import ctypes


def run_as_admin():
    """Re-launch the script with admin privileges."""
    if is_admin():
        return True

    try:
        # Re-run with elevation
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join([f'"{arg}"' for arg in sys.argv]), None, 1
        )
        sys.exit(0)
    except Exception as e:
        print(f"Failed to elevate: {e}")
        return False


def delete_registry_key_recursive(hive, key_path):
    """Recursively delete a registry key and all its subkeys."""
    try:
        key = winreg.OpenKey(hive, key_path, 0, winreg.KEY_ALL_ACCESS)

        # First, delete all subkeys recursively
        while True:
            try:
                subkey_name = winreg.EnumKey(key, 0)
                subkey_path = f"{key_path}\\{subkey_name}"
                delete_registry_key_recursive(hive, subkey_path)
            except OSError:
                break

        winreg.CloseKey(key)

        # Now delete the key itself
        winreg.DeleteKey(hive, key_path)
        return True
    except PermissionError:
        return False
    except FileNotFoundError:
        return True  # Already deleted
    except Exception as e:
        print(f"Registry delete error: {e}")
        return False


def force_delete_folder(path: Path):
    """Force delete a folder, handling permission issues."""
    if not path.exists():
        return True

    try:
        # Try normal delete first
        shutil.rmtree(path, ignore_errors=False)
        return True
    except PermissionError:
        # Try to take ownership and delete
        try:
            # Use icacls to grant full control
            subprocess.run(
                ['icacls', str(path), '/grant', f'{os.environ.get("USERNAME", "Everyone")}:F', '/T', '/Q'],
                capture_output=True, timeout=30
            )
            # Try again
            shutil.rmtree(path, ignore_errors=True)
            return not path.exists()
        except:
            pass
    except Exception as e:
        print(f"Delete error for {path}: {e}")

    return not path.exists()

# === Theme: Cyan on Dark (our look) ===
COLORS = {
    "bg": "#0a0a0a",
    "surface": "#141414",
    "surface_hover": "#1f1f1f",
    "accent": "#00d4ff",
    "accent_hover": "#00a8cc",
    "accent_dim": "#007a99",
    "text": "#fafafa",
    "text_dim": "#888888",
    "border": "#2a2a2a",
    "danger": "#ff4757",
    "danger_hover": "#cc3945",
    "warning": "#ffa502",
    "success": "#2ed573",
}

# Generic words to exclude from search terms (cause false positives)
GENERIC_WORDS = {
    "software", "program", "programs", "application", "applications", "app",
    "tools", "tool", "utility", "utilities", "system", "systems",
    "windows", "microsoft", "update", "updates", "service", "services",
    "driver", "drivers", "runtime", "framework", "library", "libraries",
    "setup", "install", "installer", "uninstall", "edition", "version",
    "free", "pro", "premium", "plus", "lite", "trial", "demo",
    "x64", "x86", "64-bit", "32-bit", "portable",
    "recovery", "backup", "data", "file", "files", "folder", "folders",
}

# Registry paths for installed programs
UNINSTALL_PATHS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]

# Common leftover locations
LEFTOVER_LOCATIONS = [
    Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")),
    Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")),
    Path(os.environ.get("LOCALAPPDATA", "")),
    Path(os.environ.get("APPDATA", "")),
    Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")),
    Path.home() / "AppData" / "LocalLow",
]

# Registry locations to check for leftovers
REGISTRY_LEFTOVER_PATHS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE"),
]


def get_folder_size(path: Path) -> int:
    """Get total size of a folder in bytes."""
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return total


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def is_admin() -> bool:
    """Check if running as administrator."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def get_folder_mtime(path: str) -> float:
    """Get the most recent modification time in a folder."""
    if not path:
        return 0
    folder = Path(path)
    if not folder.exists():
        return 0
    try:
        # Get folder's own mtime as baseline
        latest = folder.stat().st_mtime
        # Check a few files inside (don't scan everything - too slow)
        count = 0
        for entry in folder.iterdir():
            try:
                mtime = entry.stat().st_mtime
                if mtime > latest:
                    latest = mtime
                count += 1
                if count >= 20:  # Sample first 20 items
                    break
            except:
                pass
        return latest
    except:
        return 0


def parse_install_date(date_str: str) -> int:
    """Parse install date string (YYYYMMDD) to sortable int."""
    if not date_str:
        return 0
    try:
        # Most common format: YYYYMMDD
        if len(date_str) == 8 and date_str.isdigit():
            return int(date_str)
        return 0
    except:
        return 0


class InstalledProgram:
    """Represents an installed program."""

    def __init__(self, name: str, publisher: str, version: str,
                 install_location: str, uninstall_string: str,
                 install_date: str, estimated_size: int,
                 registry_key: str, registry_hive: int, registry_path: str):
        self.name = name
        self.publisher = publisher
        self.version = version
        self.install_location = install_location
        self.uninstall_string = uninstall_string
        self.install_date = install_date
        self.estimated_size = estimated_size
        self.registry_key = registry_key
        self.registry_hive = registry_hive
        self.registry_path = registry_path

        # Computed on demand
        self._last_modified: Optional[float] = None

    @property
    def search_text(self) -> str:
        return f"{self.name} {self.publisher}".lower()

    @property
    def install_date_sortable(self) -> int:
        return parse_install_date(self.install_date)

    @property
    def last_modified(self) -> float:
        if self._last_modified is None:
            self._last_modified = get_folder_mtime(self.install_location)
        return self._last_modified


class LeftoverItem:
    """Represents a leftover file/folder/registry key."""

    def __init__(self, path: str, item_type: str, size: int = 0):
        self.path = path
        self.item_type = item_type  # "folder", "file", "registry"
        self.size = size
        self.selected = True


class ProgramCard(ctk.CTkFrame):
    """Card displaying a single program."""

    def __init__(self, parent, program: InstalledProgram, on_select):
        super().__init__(parent, fg_color=COLORS["surface"], corner_radius=8, height=70)
        self.pack_propagate(False)

        self.program = program
        self.on_select = on_select
        self.selected = False

        # Make clickable
        self.bind("<Button-1>", self._click)
        self.configure(cursor="hand2")

        # Content
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=15, pady=10)
        content.bind("<Button-1>", self._click)

        # Detect Steam games
        display_name = program.name
        self.is_steam = "steam" in program.uninstall_string.lower() if program.uninstall_string else False
        if self.is_steam:
            display_name = f"{program.name} (Steam)"

        # Default color based on type
        self.default_color = COLORS["accent_dim"] if self.is_steam else COLORS["text"]

        # Name
        self.name_label = ctk.CTkLabel(
            content, text=display_name,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.default_color,
            anchor="w"
        )
        self.name_label.pack(anchor="w")
        self.name_label.bind("<Button-1>", self._click)

        # Info row
        info_parts = []
        if program.publisher:
            info_parts.append(program.publisher)
        if program.version:
            info_parts.append(f"v{program.version}")
        if program.estimated_size > 0:
            info_parts.append(format_size(program.estimated_size * 1024))  # Size is in KB

        info_text = " • ".join(info_parts) if info_parts else "Unknown"

        self.info_label = ctk.CTkLabel(
            content, text=info_text,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_dim"],
            anchor="w"
        )
        self.info_label.pack(anchor="w")
        self.info_label.bind("<Button-1>", self._click)

    def _click(self, event=None):
        self.on_select(self)

    def set_selected(self, selected: bool):
        self.selected = selected
        if selected:
            self.configure(border_width=2, border_color=COLORS["accent"])
            self.name_label.configure(text_color=COLORS["accent"])
        else:
            self.configure(border_width=0)
            self.name_label.configure(text_color=self.default_color)


class LeftoverCard(ctk.CTkFrame):
    """Card displaying a leftover item."""

    def __init__(self, parent, item: LeftoverItem, on_toggle):
        super().__init__(parent, fg_color=COLORS["surface"], corner_radius=6)

        self.item = item
        self.on_toggle = on_toggle

        # Checkbox
        self.checkbox = ctk.CTkCheckBox(
            self, text="",
            width=24, height=24,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            border_color=COLORS["border"],
            command=self._toggle
        )
        self.checkbox.pack(side="left", padx=(10, 5), pady=8)
        if item.selected:
            self.checkbox.select()

        # Icon based on type
        icon_text = {"folder": "📁", "file": "📄", "registry": "🔑"}.get(item.item_type, "❓")
        icon_label = ctk.CTkLabel(self, text=icon_text, font=ctk.CTkFont(size=14))
        icon_label.pack(side="left", padx=(0, 8))

        # Path (truncated)
        display_path = item.path
        if len(display_path) > 60:
            display_path = "..." + display_path[-57:]

        path_label = ctk.CTkLabel(
            self, text=display_path,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text"],
            anchor="w"
        )
        path_label.pack(side="left", fill="x", expand=True)

        # Size
        if item.size > 0:
            size_label = ctk.CTkLabel(
                self, text=format_size(item.size),
                font=ctk.CTkFont(size=12),
                text_color=COLORS["warning"]
            )
            size_label.pack(side="right", padx=10)

    def _toggle(self):
        self.item.selected = self.checkbox.get() == 1
        self.on_toggle()


class UninstallPlusApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Uninstall+")
        self.geometry("900x700")
        self.configure(fg_color=COLORS["bg"])
        self.minsize(700, 500)

        self.programs: list[InstalledProgram] = []
        self.filtered_programs: list[InstalledProgram] = []
        self.program_cards: list[ProgramCard] = []
        self.selected_program: Optional[InstalledProgram] = None
        self.current_sort = "name_asc"

        self.leftovers: list[LeftoverItem] = []
        self.leftover_cards: list[LeftoverCard] = []

        # Uninstall process tracking
        self.uninstall_process = None
        self.uninstall_cancelled = False

        self.setup_ui()
        self.load_programs()

    def setup_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 10))

        title = ctk.CTkLabel(
            header, text="Uninstall+",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=COLORS["accent"]
        )
        title.pack(side="left")

        # Admin indicator
        if is_admin():
            admin_label = ctk.CTkLabel(
                header, text="👑 Admin",
                font=ctk.CTkFont(size=12),
                text_color=COLORS["success"]
            )
            admin_label.pack(side="left", padx=15)
        else:
            admin_label = ctk.CTkLabel(
                header, text="⚠ Run as Admin for full cleanup",
                font=ctk.CTkFont(size=12),
                text_color=COLORS["warning"]
            )
            admin_label.pack(side="left", padx=15)

        # Recent button
        recent_btn = ctk.CTkButton(
            header, text="📋 Recent",
            width=90, height=32,
            fg_color=COLORS["surface"],
            hover_color=COLORS["surface_hover"],
            text_color=COLORS["text"],
            command=self.show_history
        )
        recent_btn.pack(side="right")

        # Manual Scan button
        manual_btn = ctk.CTkButton(
            header, text="🔎 Manual Scan",
            width=120, height=32,
            fg_color=COLORS["surface"],
            hover_color=COLORS["surface_hover"],
            text_color=COLORS["text"],
            command=self.show_manual_scan
        )
        manual_btn.pack(side="right", padx=(0, 10))

        # Main layout: left panel (programs) + right panel (actions)
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=10)

        # Left panel - Program list
        left_panel = ctk.CTkFrame(main, fg_color=COLORS["surface"], corner_radius=12)
        left_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # Search
        search_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        search_frame.pack(fill="x", padx=15, pady=15)

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.debounced_search())
        self.search_after_id = None  # For debounce

        self.search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="Search programs...",
            textvariable=self.search_var,
            height=40,
            fg_color=COLORS["bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"]
        )
        self.search_entry.pack(fill="x")

        # Sort options
        sort_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        sort_frame.pack(fill="x", padx=15, pady=(0, 10))

        sort_label = ctk.CTkLabel(
            sort_frame, text="Sort:",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_dim"]
        )
        sort_label.pack(side="left")

        self.sort_options = {
            "Name (A-Z)": "name_asc",
            "Name (Z-A)": "name_desc",
            "Installed (Newest)": "date_desc",
            "Installed (Oldest)": "date_asc",
            "Last Modified": "modified_desc",
            "Size (Largest)": "size_desc",
            "Size (Smallest)": "size_asc",
        }

        self.sort_dropdown = ctk.CTkOptionMenu(
            sort_frame,
            values=list(self.sort_options.keys()),
            command=self.on_sort_change,
            width=160,
            height=32,
            fg_color=COLORS["bg"],
            button_color=COLORS["accent_dim"],
            button_hover_color=COLORS["accent"],
            dropdown_fg_color=COLORS["surface"],
            dropdown_hover_color=COLORS["surface_hover"],
            text_color=COLORS["text"]
        )
        self.sort_dropdown.set("Name (A-Z)")
        self.sort_dropdown.pack(side="left", padx=(10, 0))

        # Program count
        self.count_label = ctk.CTkLabel(
            sort_frame, text="Loading...",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_dim"]
        )
        self.count_label.pack(side="right")

        # Program list
        self.program_scroll = ctk.CTkScrollableFrame(
            left_panel, fg_color="transparent",
            scrollbar_button_color=COLORS["accent_dim"],
            scrollbar_button_hover_color=COLORS["accent"]
        )
        self.program_scroll.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        # Right panel - Actions
        self.right_panel = ctk.CTkFrame(main, fg_color=COLORS["surface"], corner_radius=12, width=320)
        self.right_panel.pack(side="right", fill="y", padx=(10, 0))
        self.right_panel.pack_propagate(False)

        self.setup_action_panel()

    def check_uninstaller_exists(self, uninstall_string: str) -> bool:
        """Check if the uninstaller executable exists."""
        if not uninstall_string:
            return False

        # Try to extract the executable path
        cmd = uninstall_string.strip()

        # Handle quoted paths
        if cmd.startswith('"'):
            end_quote = cmd.find('"', 1)
            if end_quote > 0:
                exe_path = cmd[1:end_quote]
            else:
                exe_path = cmd[1:]
        else:
            # Take first part before space
            space_idx = cmd.find(' ')
            if space_idx > 0:
                exe_path = cmd[:space_idx]
            else:
                exe_path = cmd

        # MsiExec is always available
        if "msiexec" in exe_path.lower():
            return True

        # Check if file exists
        return Path(exe_path).exists()

    def setup_action_panel(self):
        """Setup the right action panel."""
        # Clear existing
        for widget in self.right_panel.winfo_children():
            widget.destroy()

        if not self.selected_program:
            # No selection state
            no_select = ctk.CTkLabel(
                self.right_panel,
                text="Select a program\nto uninstall",
                font=ctk.CTkFont(size=16),
                text_color=COLORS["text_dim"],
                justify="center"
            )
            no_select.pack(expand=True)
            return

        prog = self.selected_program

        # Program info
        info_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        info_frame.pack(fill="x", padx=20, pady=20)

        name_label = ctk.CTkLabel(
            info_frame, text=prog.name,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["accent"],
            wraplength=280
        )
        name_label.pack(anchor="w")

        if prog.publisher:
            pub_label = ctk.CTkLabel(
                info_frame, text=prog.publisher,
                font=ctk.CTkFont(size=13),
                text_color=COLORS["text_dim"]
            )
            pub_label.pack(anchor="w", pady=(5, 0))

        if prog.version:
            ver_label = ctk.CTkLabel(
                info_frame, text=f"Version {prog.version}",
                font=ctk.CTkFont(size=12),
                text_color=COLORS["text_dim"]
            )
            ver_label.pack(anchor="w")

        # Program size
        if prog.estimated_size > 0:
            size_label = ctk.CTkLabel(
                info_frame, text=f"💾 {format_size(prog.estimated_size * 1024)}",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=COLORS["warning"]
            )
            size_label.pack(anchor="w", pady=(8, 0))

        if prog.install_location:
            loc_label = ctk.CTkLabel(
                info_frame, text=f"📁 {prog.install_location}",
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_dim"],
                wraplength=280
            )
            loc_label.pack(anchor="w", pady=(10, 0))

        # Divider
        divider = ctk.CTkFrame(self.right_panel, fg_color=COLORS["border"], height=1)
        divider.pack(fill="x", padx=20, pady=10)

        # Check if uninstaller exists
        uninstaller_exists = self.check_uninstaller_exists(prog.uninstall_string)

        # Action buttons
        actions_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        actions_frame.pack(fill="x", padx=20)

        if not uninstaller_exists:
            # Warning for broken uninstaller
            warning_label = ctk.CTkLabel(
                actions_frame,
                text="⚠️ Uninstaller not found\nScan for leftovers instead",
                font=ctk.CTkFont(size=12),
                text_color=COLORS["warning"],
                justify="center"
            )
            warning_label.pack(fill="x", pady=(0, 10))

        # Uninstall button
        self.uninstall_btn = ctk.CTkButton(
            actions_frame, text="🗑 Uninstall",
            height=45,
            fg_color=COLORS["danger"] if uninstaller_exists else COLORS["border"],
            hover_color=COLORS["danger_hover"] if uninstaller_exists else COLORS["border"],
            text_color="#ffffff" if uninstaller_exists else COLORS["text_dim"],
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.run_uninstall,
            state="normal" if uninstaller_exists else "disabled"
        )
        self.uninstall_btn.pack(fill="x", pady=(0, 10))

        # Scan leftovers button
        self.scan_btn = ctk.CTkButton(
            actions_frame, text="🔍 Scan for Leftovers",
            height=40,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#000000",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.scan_leftovers
        )
        self.scan_btn.pack(fill="x")

        # Leftovers area
        self.leftovers_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent")
        self.leftovers_frame.pack(fill="both", expand=True, padx=10, pady=10)

    def load_programs(self):
        """Load installed programs from registry."""
        def load():
            programs = []

            for hive, path in UNINSTALL_PATHS:
                try:
                    key = winreg.OpenKey(hive, path)
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            i += 1

                            try:
                                subkey = winreg.OpenKey(key, subkey_name)

                                # Get display name
                                try:
                                    name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                                except:
                                    continue  # Skip entries without names

                                # Skip system components
                                try:
                                    system_component = winreg.QueryValueEx(subkey, "SystemComponent")[0]
                                    if system_component == 1:
                                        continue
                                except:
                                    pass

                                # Get other info
                                def get_val(key_name, default=""):
                                    try:
                                        return winreg.QueryValueEx(subkey, key_name)[0]
                                    except:
                                        return default

                                prog = InstalledProgram(
                                    name=name,
                                    publisher=get_val("Publisher"),
                                    version=get_val("DisplayVersion"),
                                    install_location=get_val("InstallLocation"),
                                    uninstall_string=get_val("UninstallString"),
                                    install_date=get_val("InstallDate"),
                                    estimated_size=get_val("EstimatedSize", 0),
                                    registry_key=subkey_name,
                                    registry_hive=hive,
                                    registry_path=path
                                )

                                # Only add if has uninstall string
                                if prog.uninstall_string:
                                    programs.append(prog)

                                winreg.CloseKey(subkey)
                            except Exception as e:
                                pass
                        except OSError:
                            break
                    winreg.CloseKey(key)
                except Exception as e:
                    pass

            # Sort by name
            programs.sort(key=lambda p: p.name.lower())

            # Remove duplicates by name
            seen = set()
            unique = []
            for p in programs:
                if p.name.lower() not in seen:
                    seen.add(p.name.lower())
                    unique.append(p)

            self.after(0, lambda: self.display_programs(unique))

        threading.Thread(target=load, daemon=True).start()

    def display_programs(self, programs: list[InstalledProgram]):
        """Display loaded programs."""
        self.programs = programs
        self.filter_programs()

    def on_sort_change(self, choice: str):
        """Handle sort dropdown change."""
        self.current_sort = self.sort_options.get(choice, "name_asc")
        self.filter_programs()

    def sort_programs(self, programs: list[InstalledProgram]) -> list[InstalledProgram]:
        """Sort programs based on current sort setting."""
        if self.current_sort == "name_asc":
            return sorted(programs, key=lambda p: p.name.lower())
        elif self.current_sort == "name_desc":
            return sorted(programs, key=lambda p: p.name.lower(), reverse=True)
        elif self.current_sort == "date_desc":
            return sorted(programs, key=lambda p: p.install_date_sortable, reverse=True)
        elif self.current_sort == "date_asc":
            return sorted(programs, key=lambda p: p.install_date_sortable)
        elif self.current_sort == "modified_desc":
            return sorted(programs, key=lambda p: p.last_modified, reverse=True)
        elif self.current_sort == "size_desc":
            return sorted(programs, key=lambda p: p.estimated_size, reverse=True)
        elif self.current_sort == "size_asc":
            return sorted(programs, key=lambda p: p.estimated_size)
        return programs

    def debounced_search(self):
        """Debounce search input - wait 500ms after typing stops."""
        # Cancel previous scheduled search
        if self.search_after_id:
            self.after_cancel(self.search_after_id)

        # Schedule new search after 500ms
        self.search_after_id = self.after(500, self.filter_programs)

    def filter_programs(self):
        """Filter and sort programs based on search and sort settings."""
        search = self.search_var.get().lower().strip()

        if search:
            self.filtered_programs = [p for p in self.programs if search in p.search_text]
        else:
            self.filtered_programs = self.programs[:]

        # Apply sorting
        self.filtered_programs = self.sort_programs(self.filtered_programs)

        self.count_label.configure(text=f"{len(self.filtered_programs)} programs")

        # Clear existing cards
        for card in self.program_cards:
            card.destroy()
        self.program_cards.clear()

        # Create new cards
        for prog in self.filtered_programs:
            card = ProgramCard(self.program_scroll, prog, self.select_program)
            card.pack(fill="x", pady=3)
            self.program_cards.append(card)

    def select_program(self, card: ProgramCard):
        """Handle program selection."""
        # Deselect all
        for c in self.program_cards:
            c.set_selected(False)

        # Select this one
        card.set_selected(True)
        self.selected_program = card.program

        # Clear leftovers
        self.leftovers.clear()

        # Update action panel
        self.setup_action_panel()

    def run_uninstall(self):
        """Run the native uninstaller."""
        if not self.selected_program:
            return

        prog = self.selected_program
        uninstall_cmd = prog.uninstall_string

        if not uninstall_cmd:
            return

        self.uninstall_process = None
        self.uninstall_cancelled = False

        # Change button to cancel
        self.uninstall_btn.configure(
            text="⏹ Cancel",
            fg_color=COLORS["warning"],
            hover_color="#cc8400",
            command=self.cancel_uninstall
        )

        def run():
            try:
                # Handle MsiExec
                if "msiexec" in uninstall_cmd.lower():
                    self.uninstall_process = subprocess.Popen(uninstall_cmd, shell=True)
                else:
                    self.uninstall_process = subprocess.Popen(uninstall_cmd, shell=True)

                # Wait for process
                self.uninstall_process.wait()

            except Exception as e:
                print(f"Uninstall error: {e}")

            if not self.uninstall_cancelled:
                self.after(0, self.uninstall_complete)
            else:
                self.after(0, self.uninstall_reset)

        threading.Thread(target=run, daemon=True).start()

    def cancel_uninstall(self):
        """Cancel running uninstall."""
        self.uninstall_cancelled = True
        if self.uninstall_process:
            try:
                self.uninstall_process.terminate()
                # Also try to kill child processes
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.uninstall_process.pid)],
                               capture_output=True)
            except:
                pass
        self.uninstall_reset()

    def uninstall_reset(self):
        """Reset uninstall button to normal state."""
        self.uninstall_btn.configure(
            text="🗑 Uninstall",
            fg_color=COLORS["danger"],
            hover_color=COLORS["danger_hover"],
            command=self.run_uninstall
        )

    def uninstall_complete(self):
        """Called when uninstall finishes."""
        # Change button to show uninstalled state (greyed out)
        self.uninstall_btn.configure(
            text="✓ Uninstalled",
            fg_color=COLORS["border"],
            hover_color=COLORS["border"],
            text_color=COLORS["text_dim"],
            state="disabled",
            command=self.run_uninstall
        )

        # Auto-scan for leftovers
        self.scan_leftovers()

    def scan_leftovers(self):
        """Scan for leftover files and registry entries."""
        if not self.selected_program:
            return

        prog = self.selected_program
        self.scan_btn.configure(text="Scanning...", state="disabled")

        def scan():
            leftovers = []

            # Generate search terms from program name (filter generic words)
            name = prog.name
            search_terms = [name.lower()]

            # Add variations
            search_terms.append(name.lower().replace(" ", ""))
            search_terms.append(name.lower().replace(" ", "-"))
            search_terms.append(name.lower().replace(" ", "_"))

            # Add publisher-based terms (if not generic)
            if prog.publisher:
                pub_lower = prog.publisher.lower()
                if pub_lower not in GENERIC_WORDS:
                    search_terms.append(pub_lower)

            # Extract key words (longer than 3 chars, not generic)
            for word in name.split():
                word_lower = word.lower()
                if len(word) > 3 and word_lower not in GENERIC_WORDS:
                    search_terms.append(word_lower)

            search_terms = list(set(search_terms))  # Dedupe

            # Check install location if it still exists
            if prog.install_location:
                install_path = Path(prog.install_location)
                if install_path.exists():
                    size = get_folder_size(install_path)
                    leftovers.append(LeftoverItem(
                        str(install_path), "folder", size
                    ))

            # Scan common locations
            for base_path in LEFTOVER_LOCATIONS:
                if not base_path or not base_path.exists():
                    continue

                try:
                    for entry in base_path.iterdir():
                        if not entry.is_dir():
                            continue

                        entry_lower = entry.name.lower()

                        for term in search_terms:
                            if term in entry_lower and len(term) > 3:
                                # Found a match
                                size = get_folder_size(entry)
                                leftovers.append(LeftoverItem(
                                    str(entry), "folder", size
                                ))
                                break
                except (PermissionError, OSError):
                    pass

            # Scan registry for leftovers
            for hive, base_path in REGISTRY_LEFTOVER_PATHS:
                try:
                    key = winreg.OpenKey(hive, base_path)
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            i += 1

                            subkey_lower = subkey_name.lower()
                            for term in search_terms:
                                if term in subkey_lower and len(term) > 3:
                                    hive_name = "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU"
                                    reg_path = f"{hive_name}\\{base_path}\\{subkey_name}"
                                    leftovers.append(LeftoverItem(reg_path, "registry", 0))
                                    break
                        except OSError:
                            break
                    winreg.CloseKey(key)
                except:
                    pass

            # Check Start Menu
            start_menu_paths = [
                Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
                Path("C:/ProgramData/Microsoft/Windows/Start Menu/Programs"),
            ]

            for sm_path in start_menu_paths:
                if not sm_path.exists():
                    continue
                try:
                    for entry in sm_path.rglob("*"):
                        if entry.is_file():
                            entry_lower = entry.stem.lower()
                            for term in search_terms:
                                if term in entry_lower and len(term) > 3:
                                    leftovers.append(LeftoverItem(str(entry), "file", entry.stat().st_size))
                                    break
                except (PermissionError, OSError):
                    pass

            # Check Desktop
            desktop_paths = [
                Path.home() / "Desktop",
                Path("C:/Users/Public/Desktop"),
            ]

            for desk_path in desktop_paths:
                if not desk_path.exists():
                    continue
                try:
                    for entry in desk_path.iterdir():
                        if entry.is_file():
                            entry_lower = entry.stem.lower()
                            for term in search_terms:
                                if term in entry_lower and len(term) > 3:
                                    leftovers.append(LeftoverItem(str(entry), "file", entry.stat().st_size))
                                    break
                except (PermissionError, OSError):
                    pass

            # Dedupe by path
            seen_paths = set()
            unique_leftovers = []
            for item in leftovers:
                if item.path not in seen_paths:
                    seen_paths.add(item.path)
                    unique_leftovers.append(item)

            self.after(0, lambda: self.display_leftovers(unique_leftovers))

        threading.Thread(target=scan, daemon=True).start()

    def display_leftovers(self, leftovers: list[LeftoverItem]):
        """Display found leftovers."""
        self.leftovers = leftovers
        self.scan_btn.configure(text="🔍 Scan for Leftovers", state="normal")

        # Clear existing
        for card in self.leftover_cards:
            card.destroy()
        self.leftover_cards.clear()

        for widget in self.leftovers_frame.winfo_children():
            widget.destroy()

        if not leftovers:
            no_leftovers = ctk.CTkLabel(
                self.leftovers_frame,
                text="✓ No leftovers found!",
                font=ctk.CTkFont(size=14),
                text_color=COLORS["success"]
            )
            no_leftovers.pack(pady=20)
            return

        # Header
        total_size = sum(l.size for l in leftovers)
        header = ctk.CTkLabel(
            self.leftovers_frame,
            text=f"Found {len(leftovers)} leftover(s) ({format_size(total_size)})",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["warning"]
        )
        header.pack(anchor="w", pady=(0, 10))

        # Tip at bottom
        tip_label = ctk.CTkLabel(
            self.leftovers_frame,
            text="💡 Close the program first if files won't delete",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_dim"]
        )
        tip_label.pack(side="bottom", pady=(5, 0))

        # Cleanup button (at bottom)
        self.cleanup_btn = ctk.CTkButton(
            self.leftovers_frame, text="🧹 Clean Selected",
            height=40,
            fg_color=COLORS["danger"],
            hover_color=COLORS["danger_hover"],
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.cleanup_leftovers
        )
        self.cleanup_btn.pack(side="bottom", fill="x", pady=(10, 0))

        # Scrollable list (fills remaining space)
        scroll = ctk.CTkScrollableFrame(
            self.leftovers_frame, fg_color="transparent",
            scrollbar_button_color=COLORS["accent_dim"],
            scrollbar_button_hover_color=COLORS["accent"]
        )
        scroll.pack(fill="both", expand=True)

        for item in leftovers:
            card = LeftoverCard(scroll, item, self.update_cleanup_button)
            card.pack(fill="x", pady=2)
            self.leftover_cards.append(card)

        self.update_cleanup_button()

    def update_cleanup_button(self):
        """Update cleanup button state."""
        selected = [l for l in self.leftovers if l.selected]
        if hasattr(self, 'cleanup_btn'):
            total_size = sum(l.size for l in selected)
            self.cleanup_btn.configure(
                text=f"🧹 Clean {len(selected)} item(s) ({format_size(total_size)})",
                state="normal" if selected else "disabled"
            )

    def cleanup_leftovers(self):
        """Remove selected leftovers."""
        selected = [l for l in self.leftovers if l.selected]
        if not selected:
            return

        self.cleanup_btn.configure(text="Cleaning...", state="disabled")

        def clean():
            for item in selected:
                try:
                    if item.item_type == "folder":
                        force_delete_folder(Path(item.path))
                    elif item.item_type == "file":
                        try:
                            Path(item.path).unlink(missing_ok=True)
                        except PermissionError:
                            # Try with elevated permissions
                            subprocess.run(['del', '/f', '/q', item.path], shell=True, capture_output=True)
                    elif item.item_type == "registry":
                        # Parse registry path: HKCU\SOFTWARE\CleverFiles
                        parts = item.path.split("\\", 2)
                        if len(parts) >= 3:
                            hive_name = parts[0]
                            full_subkey = "\\".join(parts[1:])
                            hive = winreg.HKEY_LOCAL_MACHINE if hive_name == "HKLM" else winreg.HKEY_CURRENT_USER
                            delete_registry_key_recursive(hive, full_subkey)
                except Exception as e:
                    print(f"Failed to remove {item.path}: {e}")

            self.after(0, self.cleanup_complete)

        threading.Thread(target=clean, daemon=True).start()

    def cleanup_complete(self):
        """Called when cleanup finishes."""
        # Save to history
        if self.selected_program:
            self.save_to_history(self.selected_program, self.leftovers)

        # Re-scan to show what's left
        self.scan_leftovers()

        # Refresh program list (the uninstalled program might be gone now)
        self.load_programs()

    def get_history_path(self) -> Path:
        """Get path to history file."""
        return Path.home() / ".uninstallplus_history.json"

    def save_to_history(self, program: InstalledProgram, leftovers: list[LeftoverItem]):
        """Save uninstall to history."""
        history = self.load_history()

        # Generate search terms for re-scanning (filter out generic words)
        search_terms = [program.name.lower()]
        if program.publisher:
            pub_lower = program.publisher.lower()
            if pub_lower not in GENERIC_WORDS:
                search_terms.append(pub_lower)
        for word in program.name.split():
            word_lower = word.lower()
            if len(word) > 3 and word_lower not in GENERIC_WORDS:
                search_terms.append(word_lower)

        entry = {
            "name": program.name,
            "publisher": program.publisher,
            "version": program.version,
            "uninstalled_at": datetime.now().isoformat(),
            "leftovers_cleaned": [l.path for l in leftovers if l.selected],
            "search_terms": list(set(search_terms))
        }

        history.insert(0, entry)
        history = history[:20]  # Keep last 20

        try:
            with open(self.get_history_path(), "w") as f:
                json.dump(history, f, indent=2)
        except:
            pass

    def load_history(self) -> list:
        """Load history from file."""
        try:
            with open(self.get_history_path(), "r") as f:
                return json.load(f)
        except:
            return []

    def clear_history(self, popup=None):
        """Clear all history."""
        try:
            self.get_history_path().unlink(missing_ok=True)
        except:
            pass

        if popup:
            popup.destroy()
            # Reopen to show empty state
            self.show_history()

    def show_history(self):
        """Show popup with recently uninstalled programs."""
        history = self.load_history()

        # Create popup window
        popup = ctk.CTkToplevel(self)
        popup.title("Recently Uninstalled")
        popup.geometry("500x400")
        popup.configure(fg_color=COLORS["bg"])
        popup.transient(self)
        popup.grab_set()

        # Center on parent
        popup.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 500) // 2
        y = self.winfo_y() + (self.winfo_height() - 400) // 2
        popup.geometry(f"+{x}+{y}")

        # Header
        header = ctk.CTkLabel(
            popup, text="📋 Recently Uninstalled",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS["accent"]
        )
        header.pack(pady=(20, 10))

        if not history:
            empty = ctk.CTkLabel(
                popup, text="No recent uninstalls",
                font=ctk.CTkFont(size=14),
                text_color=COLORS["text_dim"]
            )
            empty.pack(expand=True)
        else:
            # Scrollable list
            scroll = ctk.CTkScrollableFrame(
                popup, fg_color="transparent",
                scrollbar_button_color=COLORS["accent_dim"],
                scrollbar_button_hover_color=COLORS["accent"]
            )
            scroll.pack(fill="both", expand=True, padx=20, pady=10)

            for entry in history:
                item_frame = ctk.CTkFrame(scroll, fg_color=COLORS["surface"], corner_radius=8)
                item_frame.pack(fill="x", pady=4)

                # Row layout
                row = ctk.CTkFrame(item_frame, fg_color="transparent")
                row.pack(fill="x", padx=15, pady=10)

                # Info section (left)
                info = ctk.CTkFrame(row, fg_color="transparent")
                info.pack(side="left", fill="x", expand=True)

                name = ctk.CTkLabel(
                    info, text=entry.get("name", "Unknown"),
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=COLORS["text"]
                )
                name.pack(anchor="w")

                # Parse date
                try:
                    dt = datetime.fromisoformat(entry.get("uninstalled_at", ""))
                    date_str = dt.strftime("%b %d, %Y at %I:%M %p")
                except:
                    date_str = "Unknown date"

                date_label = ctk.CTkLabel(
                    info, text=date_str,
                    font=ctk.CTkFont(size=12),
                    text_color=COLORS["text_dim"]
                )
                date_label.pack(anchor="w")

                # Leftovers cleaned count
                leftovers_list = entry.get("leftovers_cleaned", [])
                if leftovers_list:
                    leftover_label = ctk.CTkLabel(
                        info, text=f"🧹 {len(leftovers_list)} leftover(s) cleaned",
                        font=ctk.CTkFont(size=11),
                        text_color=COLORS["success"]
                    )
                    leftover_label.pack(anchor="w", pady=(5, 0))

                # Re-scan button (right)
                search_terms = entry.get("search_terms", [entry.get("name", "").lower()])
                rescan_btn = ctk.CTkButton(
                    row, text="🔍 Re-scan",
                    width=80, height=28,
                    fg_color=COLORS["accent"],
                    hover_color=COLORS["accent_hover"],
                    text_color="#000000",
                    font=ctk.CTkFont(size=11),
                    command=lambda terms=search_terms, name=entry.get("name", "Unknown"), p=popup: self.rescan_from_history(terms, name, p)
                )
                rescan_btn.pack(side="right")

        # Button row
        btn_row = ctk.CTkFrame(popup, fg_color="transparent")
        btn_row.pack(pady=15)

        if history:
            clear_btn = ctk.CTkButton(
                btn_row, text="🗑 Clear History",
                width=120, height=36,
                fg_color=COLORS["danger"],
                hover_color=COLORS["danger_hover"],
                text_color="#ffffff",
                command=lambda: self.clear_history(popup)
            )
            clear_btn.pack(side="left", padx=(0, 10))

        close_btn = ctk.CTkButton(
            btn_row, text="Close",
            width=100, height=36,
            fg_color=COLORS["surface"],
            hover_color=COLORS["surface_hover"],
            text_color=COLORS["text"],
            command=popup.destroy
        )
        close_btn.pack(side="left")

    def rescan_from_history(self, search_terms: list, program_name: str, popup):
        """Re-scan for leftovers from a previously uninstalled program."""
        popup.destroy()

        # Show scanning popup
        scan_popup = ctk.CTkToplevel(self)
        scan_popup.title(f"Re-scanning: {program_name}")
        scan_popup.geometry("550x450")
        scan_popup.configure(fg_color=COLORS["bg"])
        scan_popup.transient(self)
        scan_popup.grab_set()

        # Center
        scan_popup.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 550) // 2
        y = self.winfo_y() + (self.winfo_height() - 450) // 2
        scan_popup.geometry(f"+{x}+{y}")

        header = ctk.CTkLabel(
            scan_popup, text=f"🔍 Re-scanning for {program_name}",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["accent"]
        )
        header.pack(pady=(20, 5))

        status_label = ctk.CTkLabel(
            scan_popup, text="Scanning...",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_dim"]
        )
        status_label.pack(pady=(0, 15))

        results_frame = ctk.CTkScrollableFrame(
            scan_popup, fg_color="transparent",
            scrollbar_button_color=COLORS["accent_dim"],
            scrollbar_button_hover_color=COLORS["accent"]
        )
        results_frame.pack(fill="both", expand=True, padx=20, pady=10)

        rescan_leftovers = []
        rescan_cards = []

        def scan():
            leftovers = []

            # Scan common locations
            for base_path in LEFTOVER_LOCATIONS:
                if not base_path or not base_path.exists():
                    continue
                try:
                    for entry in base_path.iterdir():
                        if not entry.is_dir():
                            continue
                        entry_lower = entry.name.lower()
                        for term in search_terms:
                            if term in entry_lower and len(term) > 3:
                                size = get_folder_size(entry)
                                leftovers.append(LeftoverItem(str(entry), "folder", size))
                                break
                except (PermissionError, OSError):
                    pass

            # Scan registry
            for hive, base_path in REGISTRY_LEFTOVER_PATHS:
                try:
                    key = winreg.OpenKey(hive, base_path)
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            i += 1
                            subkey_lower = subkey_name.lower()
                            for term in search_terms:
                                if term in subkey_lower and len(term) > 3:
                                    hive_name = "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU"
                                    reg_path = f"{hive_name}\\{base_path}\\{subkey_name}"
                                    leftovers.append(LeftoverItem(reg_path, "registry", 0))
                                    break
                        except OSError:
                            break
                    winreg.CloseKey(key)
                except:
                    pass

            # Dedupe
            seen = set()
            unique = []
            for item in leftovers:
                if item.path not in seen:
                    seen.add(item.path)
                    unique.append(item)

            scan_popup.after(0, lambda: show_results(unique))

        def show_results(leftovers):
            nonlocal rescan_leftovers, rescan_cards
            rescan_leftovers = leftovers

            if not leftovers:
                status_label.configure(text="✓ No leftovers found!", text_color=COLORS["success"])

                # Back button to return to history
                back_btn = ctk.CTkButton(
                    scan_popup, text="← Back to Recent",
                    width=140, height=36,
                    fg_color=COLORS["surface"],
                    hover_color=COLORS["surface_hover"],
                    text_color=COLORS["text"],
                    command=lambda: (scan_popup.destroy(), self.show_history())
                )
                back_btn.pack(pady=20)
            else:
                total_size = sum(l.size for l in leftovers)
                status_label.configure(
                    text=f"Found {len(leftovers)} leftover(s) ({format_size(total_size)})",
                    text_color=COLORS["warning"]
                )

                for item in leftovers:
                    card = LeftoverCard(results_frame, item, lambda: update_clean_btn())
                    card.pack(fill="x", pady=2)
                    rescan_cards.append(card)

                # Clean button
                clean_btn = ctk.CTkButton(
                    scan_popup, text="🧹 Clean Selected",
                    height=40,
                    fg_color=COLORS["danger"],
                    hover_color=COLORS["danger_hover"],
                    text_color="#ffffff",
                    font=ctk.CTkFont(size=13, weight="bold"),
                    command=lambda: clean_rescan_leftovers(clean_btn)
                )
                clean_btn.pack(fill="x", padx=20, pady=(5, 15))

                def update_clean_btn():
                    selected = [l for l in rescan_leftovers if l.selected]
                    total = sum(l.size for l in selected)
                    clean_btn.configure(
                        text=f"🧹 Clean {len(selected)} item(s) ({format_size(total)})",
                        state="normal" if selected else "disabled"
                    )

                update_clean_btn()

        def clean_rescan_leftovers(btn):
            selected = [l for l in rescan_leftovers if l.selected]
            if not selected:
                return

            btn.configure(text="Cleaning...", state="disabled")

            def do_clean():
                for item in selected:
                    try:
                        if item.item_type == "folder":
                            force_delete_folder(Path(item.path))
                        elif item.item_type == "file":
                            Path(item.path).unlink(missing_ok=True)
                        elif item.item_type == "registry":
                            parts = item.path.split("\\", 2)
                            if len(parts) >= 3:
                                hive_name = parts[0]
                                full_subkey = "\\".join(parts[1:])
                                hive = winreg.HKEY_LOCAL_MACHINE if hive_name == "HKLM" else winreg.HKEY_CURRENT_USER
                                delete_registry_key_recursive(hive, full_subkey)
                    except Exception as e:
                        print(f"Failed: {e}")

                scan_popup.after(0, lambda: scan_popup.destroy())

            threading.Thread(target=do_clean, daemon=True).start()

        threading.Thread(target=scan, daemon=True).start()

    def show_manual_scan(self):
        """Show dialog to manually scan for any program's leftovers."""
        # Create popup
        popup = ctk.CTkToplevel(self)
        popup.title("Manual Scan")
        popup.geometry("550x500")
        popup.configure(fg_color=COLORS["bg"])
        popup.transient(self)
        popup.grab_set()

        # Center on parent
        popup.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 550) // 2
        y = self.winfo_y() + (self.winfo_height() - 500) // 2
        popup.geometry(f"+{x}+{y}")

        # Header
        header = ctk.CTkLabel(
            popup, text="🔎 Manual Leftover Scan",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS["accent"]
        )
        header.pack(pady=(20, 5))

        desc = ctk.CTkLabel(
            popup, text="Search for leftovers from any program, even if already uninstalled",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_dim"]
        )
        desc.pack(pady=(0, 15))

        # Search input
        input_frame = ctk.CTkFrame(popup, fg_color="transparent")
        input_frame.pack(fill="x", padx=20)

        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="Enter program name (e.g., Discord, Spotify...)",
            textvariable=search_var,
            height=45,
            fg_color=COLORS["surface"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=14)
        )
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        search_entry.focus()

        # Results area
        results_frame = ctk.CTkFrame(popup, fg_color="transparent")
        results_frame.pack(fill="both", expand=True, padx=20, pady=15)

        status_label = ctk.CTkLabel(
            results_frame, text="",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_dim"]
        )
        status_label.pack(anchor="w")

        scroll = ctk.CTkScrollableFrame(
            results_frame, fg_color="transparent",
            scrollbar_button_color=COLORS["accent_dim"],
            scrollbar_button_hover_color=COLORS["accent"]
        )
        scroll.pack(fill="both", expand=True, pady=(10, 0))

        manual_leftovers = []
        manual_cards = []

        def do_scan():
            query = search_var.get().strip()
            if not query or len(query) < 2:
                status_label.configure(text="Enter at least 2 characters", text_color=COLORS["warning"])
                return

            # Clear previous results
            for card in manual_cards:
                card.destroy()
            manual_cards.clear()
            manual_leftovers.clear()

            status_label.configure(text="Scanning...", text_color=COLORS["text_dim"])
            popup.update()

            # Generate search terms (filter generic words)
            search_terms = [query.lower()]
            search_terms.append(query.lower().replace(" ", ""))
            for word in query.split():
                word_lower = word.lower()
                if len(word) > 3 and word_lower not in GENERIC_WORDS:
                    search_terms.append(word_lower)
            search_terms = list(set(search_terms))

            leftovers = []

            # Scan common locations
            for base_path in LEFTOVER_LOCATIONS:
                if not base_path or not base_path.exists():
                    continue
                try:
                    for entry in base_path.iterdir():
                        if not entry.is_dir():
                            continue
                        entry_lower = entry.name.lower()
                        for term in search_terms:
                            if term in entry_lower and len(term) > 2:
                                size = get_folder_size(entry)
                                leftovers.append(LeftoverItem(str(entry), "folder", size))
                                break
                except (PermissionError, OSError):
                    pass

            # Scan registry
            for hive, base_path in REGISTRY_LEFTOVER_PATHS:
                try:
                    key = winreg.OpenKey(hive, base_path)
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            i += 1
                            subkey_lower = subkey_name.lower()
                            for term in search_terms:
                                if term in subkey_lower and len(term) > 2:
                                    hive_name = "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU"
                                    reg_path = f"{hive_name}\\{base_path}\\{subkey_name}"
                                    leftovers.append(LeftoverItem(reg_path, "registry", 0))
                                    break
                        except OSError:
                            break
                    winreg.CloseKey(key)
                except:
                    pass

            # Dedupe
            seen = set()
            unique = []
            for item in leftovers:
                if item.path not in seen:
                    seen.add(item.path)
                    unique.append(item)

            manual_leftovers.extend(unique)

            if not unique:
                status_label.configure(text=f"✓ No leftovers found for '{query}'", text_color=COLORS["success"])
            else:
                total_size = sum(l.size for l in unique)
                status_label.configure(
                    text=f"Found {len(unique)} leftover(s) ({format_size(total_size)})",
                    text_color=COLORS["warning"]
                )

                for item in unique:
                    card = LeftoverCard(scroll, item, update_clean_btn)
                    card.pack(fill="x", pady=2)
                    manual_cards.append(card)

                update_clean_btn()

        def update_clean_btn():
            selected = [l for l in manual_leftovers if l.selected]
            total = sum(l.size for l in selected)
            clean_btn.configure(
                text=f"🧹 Clean {len(selected)} item(s) ({format_size(total)})",
                state="normal" if selected else "disabled"
            )

        def do_clean():
            selected = [l for l in manual_leftovers if l.selected]
            if not selected:
                return

            clean_btn.configure(text="Cleaning...", state="disabled")

            def clean_thread():
                for item in selected:
                    try:
                        if item.item_type == "folder":
                            force_delete_folder(Path(item.path))
                        elif item.item_type == "file":
                            Path(item.path).unlink(missing_ok=True)
                        elif item.item_type == "registry":
                            parts = item.path.split("\\", 2)
                            if len(parts) >= 3:
                                hive_name = parts[0]
                                full_subkey = "\\".join(parts[1:])
                                hive = winreg.HKEY_LOCAL_MACHINE if hive_name == "HKLM" else winreg.HKEY_CURRENT_USER
                                delete_registry_key_recursive(hive, full_subkey)
                    except Exception as e:
                        print(f"Failed: {e}")

                popup.after(0, do_scan)  # Re-scan to show what's left

            threading.Thread(target=clean_thread, daemon=True).start()

        # Scan button
        scan_btn = ctk.CTkButton(
            input_frame, text="Scan",
            width=80, height=45,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#000000",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=do_scan
        )
        scan_btn.pack(side="right")

        # Bind Enter key
        search_entry.bind("<Return>", lambda e: do_scan())

        # Bottom buttons
        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 15))

        clean_btn = ctk.CTkButton(
            btn_frame, text="🧹 Clean Selected",
            height=40,
            fg_color=COLORS["danger"],
            hover_color=COLORS["danger_hover"],
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=do_clean,
            state="disabled"
        )
        clean_btn.pack(side="left", fill="x", expand=True, padx=(0, 10))

        close_btn = ctk.CTkButton(
            btn_frame, text="Close",
            width=80, height=40,
            fg_color=COLORS["surface"],
            hover_color=COLORS["surface_hover"],
            text_color=COLORS["text"],
            command=popup.destroy
        )
        close_btn.pack(side="right")


def main():
    # Request admin if not already elevated
    if not is_admin():
        run_as_admin()
        return

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    app = UninstallPlusApp()
    app.mainloop()


if __name__ == "__main__":
    main()
