import sys
import os
import threading
import datetime
from pathlib import Path
import shutil

# Force Python to recognize the 'src' folder as the root directory
sys.path.append(str(Path(__file__).parent.absolute()))

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
import numpy as np
import re
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from core.utils import to_decimal_degrees
from pipeline_map.baker import export_pocmap
from pipeline_map.gis_orchestrator import run_gis_pipeline, extract_odin_enums
from pipeline_map.topo import compute_slope_aspect
from pipeline_weather.weather_api import fetch_live_telemetry, OpenMeteoFetcher
from pipeline_weather.fwi_math import FWICalculator
from pipeline_weather.baker import WeatherBaker

ctk.set_appearance_mode("Light")

# =========================================================================
# UI THEME & COLOR PALETTE
# =========================================================================
class Palette:
    """Centralized color definitions for a clean, consistent UI."""
    # Base UI
    BG_MAIN = "#F0F4F8"
    BG_SIDEBAR = "#E1E8ED"
    BG_TAB = "#FFFFFF"

    # Text & Fonts
    TEXT_MAIN = "#2C3E50"
    TEXT_SUB = "#546E7A"
    TEXT_MUTED = "#78909C"
    TEXT_LIGHT = "#F8FAFC"

    # Status & Actions
    SUCCESS = "#388E3C"
    SUCCESS_HOVER = "#2E7D32"
    ERROR = "#D32F2F"
    WARNING = "#F57F17"
    INFO = "#1976D2"
    INFO_HOVER = "#0D47A1"

    # Dark Mode (Proving Grounds)
    DARK_BG = "#1E293B"
    DARK_PANEL = "#0F172A"
    DARK_WIDGET = "#334155"
    DARK_WIDGET_HOVER = "#475569"
    DARK_ACCENT = "#EA580C"
    DARK_ACCENT_HOVER = "#C2410C"

# =========================================================================
# MASTER STUDIO APPLICATION
# =========================================================================
class POC_Studio(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- Shared Pipeline State ---
        self.active_lat = 0.0
        self.active_lon = 0.0
        self.active_map_name = ""

        # --- Window Setup & Centering ---
        self.title("POC Studio - Asset Conditioning Pipeline")
        self._center_window(width=1100, height=800)
        self.configure(fg_color=Palette.BG_MAIN) 
        
        # Grid layout for Sidebar (Col 0) and Main Content (Col 1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_frame()

    def _center_window(self, width: int, height: int):
        self.update_idletasks() # Force UI to initialize before measuring
        
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        x = int((screen_width / 2) - (width / 2))
        y = int((screen_height / 2) - (height / 2))
        
        # Shifted slightly up (-40) so the Windows taskbar doesn't clip the bottom
        self.geometry(f"{width}x{height}+{x}+{max(0, y - 40)}")
        self.minsize(900, 700) # prevents from being able to minimize too small it breaks

    # =========================================================================
    # UI: SIDEBAR & MAIN TABS
    # =========================================================================
    def _build_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=Palette.BG_SIDEBAR)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(5, weight=1) # Pushes terminal to bottom
        
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="POC STUDIO", font=ctk.CTkFont(size=20, weight="bold"), text_color=Palette.TEXT_MAIN)
        self.logo_label.pack(pady=(20, 10), padx=20)

        ctk.CTkLabel(self.sidebar_frame, text="Pipeline Status:", font=ctk.CTkFont(weight="bold"), text_color=Palette.TEXT_MAIN).pack(pady=(20,5), anchor="w", padx=20)
        
        self.map_status = ctk.CTkLabel(self.sidebar_frame, text="[ ] Terrain Missing", text_color=Palette.ERROR)
        self.map_status.pack(pady=5, anchor="w", padx=20)
        
        self.weather_status = ctk.CTkLabel(self.sidebar_frame, text="[ ] Weather Missing", text_color=Palette.ERROR)
        self.weather_status.pack(pady=5, anchor="w", padx=20)

    def _build_main_frame(self):
        # Top Section: Tabs
        self.tabview = ctk.CTkTabview(self, fg_color=Palette.BG_TAB)
        self.tabview.grid(row=0, column=1, padx=20, pady=(20, 10), sticky="nsew")

        self.tab_gis = self.tabview.add("1. Real-World GIS")
        self.tab_science = self.tabview.add("2. Proving Grounds")
        
        self._setup_gis_tab()
        self._setup_science_tab()
        
        # Bottom Section: Sleek System Console
        self._build_system_console()

    def _build_system_console(self):
        """A minimal, classy read-only viewport for background processes."""
        # Fixed height frame so it doesn't take over the screen
        console_container = ctk.CTkFrame(self, height=120, fg_color=Palette.DARK_PANEL, corner_radius=8)
        console_container.grid(row=1, column=1, padx=20, pady=(0, 20), sticky="ew")
        console_container.grid_propagate(False) # Locks the height

        # Small header
        ctk.CTkLabel(console_container, text="SYSTEM LOG", font=ctk.CTkFont(size=10, weight="bold"), text_color=Palette.TEXT_MUTED).pack(anchor="w", padx=10, pady=(5, 0))

        self.console_textbox = ctk.CTkTextbox(console_container, fg_color="transparent", text_color="#10B981", font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
        self.console_textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.console_textbox.configure(state="disabled")

    def log_event(self, message: str, status: str = "INFO"):
        """Classy formatter: [14:22:05] INFO: Message..."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {status}: {message}\n"
        
        self.console_textbox.configure(state="normal")
        self.console_textbox.insert("end", formatted_message)
        self.console_textbox.see("end")
        self.console_textbox.configure(state="disabled")
        self.update_idletasks() 

    # =========================================================================
    # TAB 1: REAL-WORLD GIS
    # =========================================================================
    def _setup_gis_tab(self):
        tab = self.tab_gis
        ctk.CTkLabel(tab, text="Map & Topography Baker", font=ctk.CTkFont(size=18, weight="bold"), text_color=Palette.TEXT_MAIN).pack(pady=(10, 5), anchor="w", padx=20)

        # --- THE FIX: Changed to CTkScrollableFrame to prevent bottom cutoff ---
        form = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=10, pady=5)
        form.grid_columnconfigure(1, weight=1) 

        # 1. API Key
        ctk.CTkLabel(form, text="OpenTopography API Key:", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="e", pady=10, padx=(0,15))
        self.api_entry = ctk.CTkEntry(form, placeholder_text="Required for 30m high-res elevation data")
        self.api_entry.grid(row=0, column=1, sticky="ew", pady=10)

        # 2. Coordinates
        ctk.CTkLabel(form, text="Map Center Coordinates:", font=ctk.CTkFont(weight="bold")).grid(row=1, column=0, sticky="e", pady=(10,0), padx=(0,15))
        self.coord_entry = ctk.CTkEntry(form, placeholder_text="e.g. 55.0, -115.0  OR  55°00'N 115°00'W")
        self.coord_entry.grid(row=1, column=1, sticky="ew", pady=(10,0))
        ctk.CTkLabel(form, text="Center point for your GPS bounding box.", text_color=Palette.TEXT_MUTED, font=ctk.CTkFont(size=10)).grid(row=2, column=1, sticky="w", pady=(0,10))

        # 3. Odin Enum Dictionary
        ctk.CTkLabel(form, text="Odin Enums (.odin):", font=ctk.CTkFont(weight="bold")).grid(row=3, column=0, sticky="e", pady=(10,0), padx=(0,15))
        file_frame0 = ctk.CTkFrame(form, fg_color="transparent")
        file_frame0.grid(row=3, column=1, sticky="ew", pady=(10,0))
        file_frame0.grid_columnconfigure(0, weight=1)
        self.odin_path = ctk.CTkEntry(file_frame0, placeholder_text="Path to ignis_types.odin")
        self.odin_path.insert(0, r"C:\Users\cread\VSCode_Projects\IGNIS\src\ignis_types.odin") 
        self.odin_path.grid(row=0, column=0, sticky="ew", padx=(0,5))
        ctk.CTkButton(file_frame0, text="Browse", width=80, fg_color=Palette.TEXT_MUTED, hover_color=Palette.TEXT_SUB, command=lambda: self._browse_file(self.odin_path)).grid(row=0, column=1)
        ctk.CTkLabel(form, text="Required to sync Python fuel integers with the C-struct.", text_color=Palette.TEXT_MUTED, font=ctk.CTkFont(size=10)).grid(row=4, column=1, sticky="w", pady=(0,10))

        # 4. Size & Resolution (LOCKED FOR STABILITY)
        ctk.CTkLabel(form, text="Grid Size (NxN):", font=ctk.CTkFont(weight="bold")).grid(row=5, column=0, sticky="e", pady=(10,0), padx=(0,15))
        self.gis_size = ctk.CTkEntry(form, fg_color=Palette.BG_SIDEBAR, text_color=Palette.TEXT_MUTED)
        self.gis_size.insert(0, "1024")
        self.gis_size.configure(state="disabled") 
        self.gis_size.grid(row=5, column=1, sticky="ew", pady=(10,0))
        
        ctk.CTkLabel(form, text="Cell Resolution (m):", font=ctk.CTkFont(weight="bold")).grid(row=6, column=0, sticky="e", pady=(10,0), padx=(0,15))
        self.gis_res = ctk.CTkEntry(form, fg_color=Palette.BG_SIDEBAR, text_color=Palette.TEXT_MUTED)
        self.gis_res.insert(0, "30.0")
        self.gis_res.configure(state="disabled") 
        self.gis_res.grid(row=6, column=1, sticky="ew", pady=(10,0))
        ctk.CTkLabel(form, text="Locked to 1024x1024 at 30m to ensure engine stability during tuning.", text_color=Palette.TEXT_MUTED, font=ctk.CTkFont(size=10)).grid(row=7, column=1, sticky="w", pady=(0,10))

        # 5. Data Sources
        ctk.CTkLabel(form, text="Fuel Raster (.tif):", font=ctk.CTkFont(weight="bold")).grid(row=8, column=0, sticky="e", pady=10, padx=(0,15))
        file_frame1 = ctk.CTkFrame(form, fg_color="transparent")
        file_frame1.grid(row=8, column=1, sticky="ew", pady=10)
        file_frame1.grid_columnconfigure(0, weight=1)
        self.fuel_tif_path = ctk.CTkEntry(file_frame1, placeholder_text="Path to NRCan regional fuel .tif")
        self.fuel_tif_path.insert(0, r"C:\Users\cread\VSCode_Projects\nrcan_fbp_fuels.tif")
        self.fuel_tif_path.grid(row=0, column=0, sticky="ew", padx=(0,5))
        ctk.CTkButton(file_frame1, text="Browse", width=80, fg_color=Palette.TEXT_MUTED, hover_color=Palette.TEXT_SUB, command=lambda: self._browse_file(self.fuel_tif_path)).grid(row=0, column=1)

        # 6. Map Classification & Hierarchy (STRICT NAMING)
        ctk.CTkLabel(form, text="Map Classification:", font=ctk.CTkFont(weight="bold")).grid(row=9, column=0, sticky="e", pady=(10,0), padx=(0,15))
        
        class_frame = ctk.CTkFrame(form, fg_color="transparent")
        class_frame.grid(row=9, column=1, sticky="ew", pady=(10,0))
        class_frame.grid_columnconfigure((0,1), weight=1)

        self.gis_country = ctk.CTkOptionMenu(class_frame, values=["Canada", "USA"])
        self.gis_country.grid(row=0, column=0, sticky="ew", padx=(0,5), pady=5)
        
        self.gis_province = ctk.CTkOptionMenu(class_frame, values=[
            "Alberta", "British Columbia", "Manitoba", "New Brunswick", 
            "Newfoundland", "Northwest Territories", "Nova Scotia", "Nunavut", 
            "Ontario", "Prince Edward Island", "Quebec", "Saskatchewan", "Yukon"
        ])
        self.gis_province.grid(row=0, column=1, sticky="ew", padx=(5,0), pady=5)

        self.gis_region = ctk.CTkEntry(class_frame, placeholder_text="Region (e.g. Klondike)")
        self.gis_region.grid(row=1, column=0, sticky="ew", padx=(0,5), pady=5)

        self.gis_name = ctk.CTkEntry(class_frame, placeholder_text="Map Name (e.g. Dawson City)")
        self.gis_name.grid(row=1, column=1, sticky="ew", padx=(5,0), pady=5)

        ctk.CTkLabel(form, text="Generates strict folder tree in IGNIS engine for UI filtering.", text_color=Palette.TEXT_MUTED, font=ctk.CTkFont(size=10)).grid(row=10, column=1, sticky="w", pady=(0,10))

        # --- Integrated Weather Notification ---
        ctk.CTkLabel(form, text="Climatology Data:", font=ctk.CTkFont(weight="bold")).grid(row=11, column=0, sticky="e", pady=(20,0), padx=(0,15))
        ctk.CTkLabel(form, text="Live telemetry is automatically fetched for the coordinates above.", text_color=Palette.INFO, font=ctk.CTkFont(weight="bold")).grid(row=11, column=1, sticky="w", pady=(20,0))

        # --- Integrated Master Button ---
        self.bake_master_btn = ctk.CTkButton(form, text="EXECUTE MASTER PIPELINE (MAP + WEATHER)", font=ctk.CTkFont(weight="bold"), fg_color=Palette.SUCCESS, hover_color=Palette.SUCCESS_HOVER, command=self.execute_master_pipeline)
        self.bake_master_btn.grid(row=12, column=0, columnspan=2, sticky="w", pady=(20, 10), padx=(0, 15))

        # --- Loading Bar ---
        self.gis_progress = ctk.CTkProgressBar(form, mode="indeterminate", fg_color=Palette.DARK_PANEL, progress_color=Palette.INFO)
        self.gis_progress.grid(row=13, column=0, columnspan=2, sticky="ew", padx=(0, 15), pady=(0, 40))
        self.gis_progress.set(0)
        
    # =========================================================================
    # TAB 2: PROVING GROUNDS (Dark Mode Science Lab)
    # =========================================================================
    def _setup_science_tab(self):
        tab = self.tab_science
        tab.configure(fg_color=Palette.DARK_BG) 
        
        ctk.CTkLabel(tab, text="Ignis Proving Grounds", font=ctk.CTkFont(size=18, weight="bold"), text_color=Palette.TEXT_LIGHT).pack(pady=(10, 0), anchor="w", padx=20)
        ctk.CTkLabel(tab, text="Generate sterile, mathematically perfect terrain for engine tuning and physics diagnostics.", text_color=Palette.TEXT_MUTED).pack(pady=(0, 20), anchor="w", padx=20)

        self.pg_form = ctk.CTkFrame(tab, fg_color="transparent")
        self.pg_form.pack(fill="both", expand=True, padx=20)
        self.pg_form.grid_columnconfigure(0, weight=1) 
        self.pg_form.grid_columnconfigure(1, weight=1) 

        # --- Left Column: Controls (Scrollable) ---
        pg_ctrls = ctk.CTkScrollableFrame(self.pg_form, fg_color="transparent")
        pg_ctrls.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        pg_ctrls.grid_columnconfigure(1, weight=1)

        ALL_FUEL_TYPES = [
            "C1_Spruce_Lichen_Woodland", "C2_Boreal_Spruce", "C3_Mature_Jack_Pine", 
            "C4_Immature_Jack_Pine", "C5_Red_and_White_Pine", "C6_Conifer_Plantation", 
            "C7_Pon_Pine_D_Fir", "D1_Leafless_Aspen", "M1_Boreal_Mixedwood_Leafless", 
            "M2_Boreal_Mixedwood_Green", "M3_Dead_Balsam_Leafless", "M4_Dead_Balsam_Green",
            "S1_Jack_Pine_Slash", "S2_White_Spruce_Balsam_Slash", "S3_Coastal_Cedar_Hem_DFir_Slash",
            "O1a_Matted_Grass", "O1b_Standing_Grass", "Structure_VAR", "PowerlinePole", 
            "Farm_Field_Planted_Green", "Oil_Lease_Site"
        ]

        # 1. Fuels
        ctk.CTkLabel(pg_ctrls, text="Base Fuel Ecology:", font=ctk.CTkFont(weight="bold"), text_color=Palette.TEXT_LIGHT).grid(row=0, column=0, sticky="e", pady=(10,0), padx=(0,15))
        self.pg_fuel = ctk.CTkOptionMenu(pg_ctrls, values=ALL_FUEL_TYPES, fg_color=Palette.DARK_WIDGET, button_color=Palette.DARK_WIDGET_HOVER)
        self.pg_fuel.set("O1b_Standing_Grass")
        self.pg_fuel.grid(row=0, column=1, sticky="ew", pady=(10,0))
        
        ctk.CTkLabel(pg_ctrls, text="Secondary Fuel (For Splits):", font=ctk.CTkFont(weight="bold"), text_color=Palette.TEXT_LIGHT).grid(row=1, column=0, sticky="e", pady=(10,0), padx=(0,15))
        self.pg_sec_fuel = ctk.CTkOptionMenu(pg_ctrls, values=ALL_FUEL_TYPES, fg_color=Palette.DARK_WIDGET, button_color=Palette.DARK_WIDGET_HOVER)
        self.pg_sec_fuel.set("Farm_Field_Planted_Green")
        self.pg_sec_fuel.grid(row=1, column=1, sticky="ew", pady=(10,0))

        # 2. Fuel Layout
        ctk.CTkLabel(pg_ctrls, text="Fuel Layout Pattern:", font=ctk.CTkFont(weight="bold"), text_color=Palette.TEXT_LIGHT).grid(row=2, column=0, sticky="e", pady=(10,0), padx=(0,15))
        self.pg_fuel_pattern = ctk.CTkOptionMenu(pg_ctrls, values=["Solid", "Half-and-Half (Left/Right)", "Checkerboard", "Center VAR Block"], fg_color=Palette.DARK_WIDGET, button_color=Palette.DARK_WIDGET_HOVER)
        self.pg_fuel_pattern.grid(row=2, column=1, sticky="ew", pady=(10,0))

        # 3. Geometry Shape
        ctk.CTkLabel(pg_ctrls, text="Topographic Shape:", font=ctk.CTkFont(weight="bold"), text_color=Palette.TEXT_LIGHT).grid(row=4, column=0, sticky="e", pady=(10,0), padx=(0,15))
        self.pg_shape = ctk.CTkOptionMenu(pg_ctrls, values=["Flat", "Ramp", "Ridge", "Bowl", "Saddle", "Cone", "Undulations"], fg_color=Palette.DARK_WIDGET, button_color=Palette.DARK_WIDGET_HOVER, command=self._update_pg_preview)
        self.pg_shape.set("Flat")
        self.pg_shape.grid(row=4, column=1, sticky="ew", pady=(10,0))

        # 4. Slope & Units
        ctk.CTkLabel(pg_ctrls, text="Max Slope Gradient:", font=ctk.CTkFont(weight="bold"), text_color=Palette.TEXT_LIGHT).grid(row=6, column=0, sticky="e", pady=10, padx=(0,15))
        slope_frame = ctk.CTkFrame(pg_ctrls, fg_color="transparent")
        slope_frame.grid(row=6, column=1, sticky="ew", pady=10)
        self.pg_slope = ctk.CTkEntry(slope_frame, width=80, placeholder_text="e.g. 15", fg_color=Palette.DARK_PANEL, text_color="white")
        self.pg_slope.pack(side="left", padx=(0,10))
        self.pg_slope.bind("<KeyRelease>", self._update_pg_preview)
        
        self.pg_slope_unit = ctk.CTkSegmentedButton(slope_frame, values=["Deg", "%"], selected_color=Palette.DARK_ACCENT, selected_hover_color=Palette.DARK_ACCENT_HOVER, command=self._update_pg_preview)
        self.pg_slope_unit.set("Deg")
        self.pg_slope_unit.pack(side="left")

        # 5. Locked Dimensions
        ctk.CTkLabel(pg_ctrls, text="Scale (Locked to Reality):", font=ctk.CTkFont(weight="bold"), text_color=Palette.TEXT_LIGHT).grid(row=7, column=0, sticky="e", pady=(10,0), padx=(0,15))
        ctk.CTkLabel(pg_ctrls, text="1024 x 1024 cells @ 30.0m resolution", text_color=Palette.SUCCESS).grid(row=7, column=1, sticky="w", pady=(10,0))
        
        # 6. Weather — Fire Danger Preset + fully tunable parameter fields
        ctk.CTkLabel(pg_ctrls, text="Fire Danger Preset:", font=ctk.CTkFont(weight="bold"), text_color=Palette.TEXT_LIGHT).grid(row=8, column=0, sticky="e", pady=(20,0), padx=(0,15))
        self.pg_weather = ctk.CTkOptionMenu(
            pg_ctrls,
            values=["Low", "Medium", "High", "Very High", "Extreme"],
            fg_color=Palette.DARK_WIDGET, button_color=Palette.DARK_WIDGET_HOVER,
            command=self._apply_pg_preset
        )
        self.pg_weather.set("High")
        self.pg_weather.grid(row=8, column=1, sticky="ew", pady=(20,0))

        ctk.CTkLabel(pg_ctrls, text="── Weather Parameters ──", text_color=Palette.TEXT_MUTED,
                     font=ctk.CTkFont(size=10)).grid(row=9, column=0, columnspan=2, pady=(12,4))

        def _wfield(label, row, attr):
            ctk.CTkLabel(pg_ctrls, text=label, font=ctk.CTkFont(size=11),
                         text_color=Palette.TEXT_LIGHT).grid(row=row, column=0, sticky="e", pady=3, padx=(0,10))
            e = ctk.CTkEntry(pg_ctrls, fg_color=Palette.DARK_PANEL, text_color="white", width=110)
            e.grid(row=row, column=1, sticky="w", pady=3)
            setattr(self, attr, e)

        _wfield("Temp (°C):",         10, "pg_w_temp")
        _wfield("Rel. Humidity %:",   11, "pg_w_rh")
        _wfield("Wind Speed km/h:",   12, "pg_w_wind_spd")
        _wfield("Wind Direction °:",  13, "pg_w_wind_dir")
        _wfield("Rain mm/24h:",       14, "pg_w_rain")

        ctk.CTkLabel(pg_ctrls, text="── FWI Moisture Codes ──", text_color=Palette.TEXT_MUTED,
                     font=ctk.CTkFont(size=10)).grid(row=15, column=0, columnspan=2, pady=(8,4))

        _wfield("FFMC:",  16, "pg_w_ffmc")
        _wfield("DMC:",   17, "pg_w_dmc")
        _wfield("DC:",    18, "pg_w_dc")

        # Populate field defaults via the "High" preset
        self._apply_pg_preset("High")

        ctk.CTkLabel(pg_ctrls, text="Test Name:", font=ctk.CTkFont(weight="bold"), text_color=Palette.TEXT_LIGHT).grid(row=19, column=0, sticky="e", pady=(20,0), padx=(0,15))
        self.pg_name = ctk.CTkEntry(pg_ctrls, placeholder_text="e.g. Test1_ExpCurve", fg_color=Palette.DARK_PANEL, text_color="white")
        self.pg_name.grid(row=19, column=1, sticky="ew", pady=(20,0))

        self.bake_pg_btn = ctk.CTkButton(pg_ctrls, text="BAKE TEST LAB (.pocmap & .pocwea)", font=ctk.CTkFont(weight="bold"), fg_color=Palette.DARK_ACCENT, hover_color=Palette.DARK_ACCENT_HOVER, text_color="white", command=self.execute_pg_bake)
        self.bake_pg_btn.grid(row=20, column=0, columnspan=2, sticky="w", pady=(20, 20))

        # --- Right Column: Live 3D Plot ---
        self.pg_plot_frame = ctk.CTkFrame(self.pg_form, fg_color=Palette.DARK_PANEL, corner_radius=10)
        self.pg_plot_frame.grid(row=0, column=1, sticky="nsew")
        
        self.fig = Figure(figsize=(4, 4), dpi=100)
        self.fig.patch.set_facecolor(Palette.DARK_PANEL) 
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.ax.set_facecolor(Palette.DARK_PANEL)
        self.ax.set_axis_off() 
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.pg_plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=5, pady=5)

        # Draw initial state
        self._update_pg_preview()

    # fmt: off
    _PG_PRESETS = {
        # Preset        Temp   RH  Wind  Dir  Rain  FFMC   DMC    DC
        "Low":         (12.0, 70.0,  5.0, 270.0, 0.0,  65.0,   8.0,  40.0),
        "Medium":      (18.0, 50.0, 10.0, 270.0, 0.0,  78.0,  25.0, 120.0),
        "High":        (25.0, 35.0, 20.0, 270.0, 0.0,  86.0,  55.0, 220.0),
        "Very High":   (30.0, 25.0, 30.0, 270.0, 0.0,  91.0,  90.0, 350.0),
        "Extreme":     (35.0, 15.0, 50.0, 270.0, 0.0,  95.0, 130.0, 600.0),
    }
    # fmt: on

    def _apply_pg_preset(self, preset_name: str):
        """Populate all 8 editable weather fields from the selected fire-danger preset."""
        vals = self._PG_PRESETS.get(preset_name)
        if vals is None:
            return
        temp, rh, wind_spd, wind_dir, rain, ffmc, dmc, dc = vals
        for entry, val in (
            (self.pg_w_temp,     temp),
            (self.pg_w_rh,       rh),
            (self.pg_w_wind_spd, wind_spd),
            (self.pg_w_wind_dir, wind_dir),
            (self.pg_w_rain,     rain),
            (self.pg_w_ffmc,     ffmc),
            (self.pg_w_dmc,      dmc),
            (self.pg_w_dc,       dc),
        ):
            entry.delete(0, 'end')
            entry.insert(0, str(val))

    def _update_pg_preview(self, *args):
        self.ax.clear()
        self.ax.set_axis_off()
        self.ax.set_facecolor(Palette.DARK_PANEL)
        
        # Grid is locked to 1024 × 1024 @ 30 m (pg_size/pg_res removed as editable fields)
        size      = 1024
        res       = 30.0
        map_meters = size * res

        try: slope_val = float(self.pg_slope.get() or 0.0)
        except: slope_val = 0.0

        try: unit = self.pg_slope_unit.get()
        except: unit = "Deg"

        slope_rad = np.arctan(slope_val / 100.0) if unit == "%" else np.radians(slope_val)

        # Low-res meshgrid for display performance
        x = np.linspace(-map_meters/2, map_meters/2, 40)
        y = np.linspace(-map_meters/2, map_meters/2, 40)
        X, Y = np.meshgrid(x, y)
        
        shape = self.pg_shape.get()
        Z = np.zeros_like(X)

        if shape == "Ramp":
            Z = (Y - np.min(Y)) * np.tan(slope_rad)
        elif shape == "Ridge":
            max_z = (map_meters / 2) * np.tan(slope_rad)
            Z = np.maximum(0.0, max_z - np.abs(X) * np.tan(slope_rad))
        elif shape == "Bowl":
            Z = (X**2 + Y**2) * (np.tan(slope_rad) / map_meters)
        elif shape == "Saddle":
            Z = (X**2 - Y**2) * (np.tan(slope_rad) / map_meters)
            Z -= np.min(Z)
        elif shape == "Cone":
            r = np.sqrt(X**2 + Y**2)
            Z = np.maximum(0.0, (map_meters / 2 - r) * np.tan(slope_rad))
        elif shape == "Undulations":
            freq  = map_meters / 4.0
            max_z = (map_meters / 8) * np.tan(slope_rad)
            Z = np.sin(X / freq * 2 * np.pi) * np.cos(Y / freq * 2 * np.pi) * max_z
            Z -= np.min(Z)

        z_range = np.ptp(Z) if np.ptp(Z) > 0 else 1.0
        self.ax.set_box_aspect((1, 1, z_range / map_meters))
        self.ax.plot_surface(X, Y, Z, cmap='magma', edgecolor='none')
        slope_label = f"{slope_val}{unit}"
        self.ax.set_title(f"{shape} | {map_meters/1000:.1f} km² | Slope: {slope_label}", fontsize=10, color="#94A3B8")
        self.canvas.draw()

    # =========================================================================
    # ACTIONS & THREADING
    # =========================================================================
    def _browse_file(self, entry_widget):
        f = filedialog.askopenfilename()
        if f:
            entry_widget.delete(0, 'end')
            entry_widget.insert(0, f)

    def execute_master_pipeline(self):
        raw_coords = self.coord_entry.get()

        if not raw_coords:
            self.log_event("Missing Coordinates.", "WARN")
            return

        self.bake_master_btn.configure(state="disabled", text="BUILDING SCENARIO...")
        self.gis_progress.start()
        self.update_idletasks()
        
        threading.Thread(target=self._threaded_master_pipeline, args=(raw_coords,), daemon=True).start()

    def _threaded_master_pipeline(self, raw_coords):
        try:
            # ==========================================
            # PHASE 1: TERRAIN & GIS BAKE
            # ==========================================
            lat, lon = to_decimal_degrees(raw_coords)
            self.active_lat = lat
            self.active_lon = lon
            
            api_key = self.api_entry.get().strip()
            fuel_tif = self.fuel_tif_path.get().strip()
            odin_path = self.odin_path.get().strip()
            
            country = self.gis_country.get()
            province = self.gis_province.get()
            region = self.gis_region.get().strip()
            name = self.gis_name.get().strip()

            if not region or not name:
                self.log_event("Missing Region or Map Name.", "ERROR")
                self.bake_master_btn.configure(state="normal", text="EXECUTE MASTER PIPELINE (MAP + WEATHER)")
                self.gis_progress.stop()
                return

            self.log_event(f"Starting Master Pipeline for {name}...", "SYS")
            
            success_path = run_gis_pipeline(
                lat=lat, lon=lon, 
                country=country, province=province, region=region, map_name=name,
                api_key=api_key, fuel_tif=fuel_tif, odin_path=odin_path, 
                log_callback=self.log_event
            )
            
            if not success_path:
                self.log_event("Terrain Bake Failed. Aborting Weather Fetch.", "ERROR")
                self.bake_master_btn.configure(state="normal", text="EXECUTE MASTER PIPELINE (MAP + WEATHER)")
                self.gis_progress.stop()
                return

            self.map_status.configure(text=f"[x] Terrain Baked ({name})", text_color=Palette.SUCCESS)

            # ==========================================
            # PHASE 2: METEOROLOGY & WEATHER BAKE
            # ==========================================
            safe_region = region.replace(" ", "_").lower()
            safe_name   = name.replace(" ", "_").lower()
            ignis_base  = r"C:\Users\cread\VSCode_Projects\IGNIS\assets\maps"
            target_dir  = os.path.join(ignis_base, country, province, safe_region)
            os.makedirs(target_dir, exist_ok=True)
            final_filepath = os.path.join(target_dir, f"{safe_name}.pocwea")

            bake_year       = datetime.datetime.now().year - 1  # last complete calendar year
            weather_baker   = WeatherBaker(year_length=365)
            historical_ok   = False

            # --- Attempt 1: real historical climatology + FWI calculation ---
            try:
                self.log_event(f"Fetching {bake_year} historical climate archive (Open-Meteo)...", "METEO")
                fetcher = OpenMeteoFetcher()
                df = fetcher.fetch_historical_years(
                    lat=self.active_lat, lon=self.active_lon,
                    end_year=bake_year, years_back=1
                )
                self.log_event(f"Computing CFFDRS FWI codes for {len(df)} days...", "METEO")
                calc = FWICalculator(start_ffmc=85.0, start_dmc=6.0, start_dc=15.0)
                df   = calc.process_season(df)

                n = min(len(df), 365)
                for i in range(n):
                    row = df.iloc[i]
                    weather_baker.set_day(
                        day_index=i,
                        temp=float(row['temperature_c']),
                        rh=float(row['relative_humidity']),
                        wind_spd=float(row['wind_speed_kmh']),
                        wind_dir=float(row.get('wind_direction_deg', 270.0)),
                        rain=float(row['rain_24h_mm']),
                        ffmc=float(row['ffmc']),
                        dmc=float(row['dmc']),
                        dc=float(row['dc'])
                    )
                # Pad with last-day values if API returned fewer than 365 days
                if n < 365:
                    last = df.iloc[-1]
                    self.log_event(f"[WARN] Only {n} days in archive — padding remaining {365-n} days.", "WARN")
                    for i in range(n, 365):
                        weather_baker.set_day(
                            day_index=i,
                            temp=float(last['temperature_c']), rh=float(last['relative_humidity']),
                            wind_spd=float(last['wind_speed_kmh']), wind_dir=float(last.get('wind_direction_deg', 270.0)),
                            rain=float(last['rain_24h_mm']),
                            ffmc=float(last['ffmc']), dmc=float(last['dmc']), dc=float(last['dc'])
                        )
                historical_ok = True
                self.log_event(f"Real CFFDRS FWI seasonal data computed from {bake_year} archive.", "OK")

            except Exception as hist_err:
                self.log_event(f"Historical fetch failed ({hist_err}). Falling back to live telemetry.", "WARN")

            # --- Attempt 2: live snapshot broadcast (fallback) ---
            if not historical_ok:
                weather_data = fetch_live_telemetry(self.active_lat, self.active_lon, self.log_event)
                if weather_data:
                    for day in range(365):
                        weather_baker.set_day(
                            day_index=day,
                            temp=weather_data['temp'],  rh=weather_data['rh'],
                            wind_spd=weather_data['wind_spd'], wind_dir=weather_data['wind_dir'],
                            rain=weather_data['rain'],
                            ffmc=85.0, dmc=6.0, dc=15.0
                        )
                else:
                    self.log_event("All weather sources failed. Skipping .pocwea.", "ERROR")
                    self.bake_master_btn.configure(state="normal", text="EXECUTE MASTER PIPELINE (MAP + WEATHER)")
                    self.gis_progress.stop()
                    return

            success = weather_baker.bake(final_filepath, self.active_lat, self.active_lon, bake_year)
            if success:
                self.weather_status.configure(text="[x] Weather Baked (.pocwea)", text_color=Palette.SUCCESS)
                self.log_event("Master Pipeline Complete!", "SUCCESS")
            else:
                self.log_event("Weather bake failed.", "ERROR")

            # Clean up UI State
            self.bake_master_btn.configure(state="normal", text="EXECUTE MASTER PIPELINE (MAP + WEATHER)")
            self.gis_progress.stop()

        except Exception as e:
            self.log_event(f"Pipeline Error: {str(e)}", "ERROR")
            self.bake_master_btn.configure(state="normal", text="EXECUTE MASTER PIPELINE (MAP + WEATHER)")
            self.gis_progress.stop()

    def execute_pg_bake(self):
        test_name = self.pg_name.get().strip()
        if not test_name:
            self.log_event("Missing Test Name for Proving Grounds.", "WARN")
            return
            
        self.bake_pg_btn.configure(state="disabled", text="GENERATING LAB...")
        threading.Thread(target=self._threaded_pg_bake, args=(test_name,), daemon=True).start()

    def _threaded_pg_bake(self, test_name):
        try:
            self.log_event(f"Building Proving Grounds: {test_name}...", "SYS")
            
            size      = 1024
            res       = 30.0
            map_meters = size * res

            # 1. Parse Fuel Enums from Odin (shared parser with GIS pipeline)
            odin_file = self.odin_path.get().strip()
            fuel_dict = extract_odin_enums(odin_file, self.log_event)
            if not fuel_dict:
                self.log_event("CRITICAL: Could not parse FuelType enum from Odin.", "ERROR")
                return

            # 2. Build Terrain Geometry
            try: slope_val = float(self.pg_slope.get() or 0.0)
            except: slope_val = 0.0

            # Respect the slope unit selector — convert % grade to radians directly
            if self.pg_slope_unit.get() == "%":
                slope_rad = np.arctan(slope_val / 100.0)
            else:
                slope_rad = np.radians(slope_val)

            x = np.linspace(-map_meters/2, map_meters/2, size)
            y = np.linspace(-map_meters/2, map_meters/2, size)
            X, Y = np.meshgrid(x, y)
            Z = np.zeros((size, size), dtype=np.float32)

            shape = self.pg_shape.get()
            if shape == "Ramp":
                Z = ((Y - np.min(Y)) * np.tan(slope_rad)).astype(np.float32)
            elif shape == "Ridge":
                max_z = (map_meters / 2) * np.tan(slope_rad)
                Z = np.maximum(0.0, max_z - np.abs(X) * np.tan(slope_rad)).astype(np.float32)
            elif shape == "Bowl":
                Z = ((X**2 + Y**2) * (np.tan(slope_rad) / map_meters)).astype(np.float32)
            elif shape == "Saddle":
                Z = ((X**2 - Y**2) * (np.tan(slope_rad) / map_meters)).astype(np.float32)
                Z -= np.min(Z)
            elif shape == "Cone":
                r = np.sqrt(X**2 + Y**2)
                Z = np.maximum(0.0, (map_meters / 2 - r) * np.tan(slope_rad)).astype(np.float32)
            elif shape == "Undulations":
                freq  = map_meters / 4.0
                max_z = (map_meters / 8) * np.tan(slope_rad)
                Z = (np.sin(X / freq * 2 * np.pi) * np.cos(Y / freq * 2 * np.pi) * max_z).astype(np.float32)
                Z -= np.min(Z)
            # "Flat" → Z stays zeros

            dy, dx = np.gradient(Z, res, res)
            slope_grid, aspect_grid = compute_slope_aspect(Z, res)

            # 3. Fuel Layout
            base_int = fuel_dict.get(self.pg_fuel.get(), 0)
            sec_int  = fuel_dict.get(self.pg_sec_fuel.get(), 0)
            fuel_grid = np.full((size, size), base_int, dtype=np.uint8)
            pattern = self.pg_fuel_pattern.get()

            if pattern == "Half-and-Half (Left/Right)":
                fuel_grid[:, size//2:] = sec_int
            elif pattern == "Checkerboard":
                chk = 64
                for i in range(0, size, chk):
                    for j in range(0, size, chk):
                        if (i//chk + j//chk) % 2 == 1:
                            fuel_grid[i:i+chk, j:j+chk] = sec_int
            elif pattern == "Center VAR Block":
                c = size // 2
                fuel_grid[c-4:c+5, c-4:c+5] = fuel_dict.get("Oil_Lease_Site", 0)
                fuel_grid[c-1:c+2, c-1:c+2] = fuel_dict.get("Structure_VAR", 0)

            soil_grid = np.full((size, size), 1, dtype=np.uint8)  # Silt Loam

            # 4. Output paths
            safe_name  = test_name.replace(" ", "_").lower()
            target_dir = os.path.join(r"C:\Users\cread\VSCode_Projects\IGNIS\assets\maps", "Proving_Grounds")
            os.makedirs(target_dir, exist_ok=True)
            map_path = os.path.join(target_dir, f"{safe_name}.pocmap")
            wea_path = os.path.join(target_dir, f"{safe_name}.pocwea")

            # 5. Pack Map Binary
            export_pocmap(map_path, f"Lab: {test_name}", size, size, res, 0.0, 0.0,
                          Z, slope_grid, aspect_grid, fuel_grid, soil_grid, self.log_event)

            # 6. Pack Weather Binary — read directly from tunable UI fields
            def _sf(entry, default):
                try: return float(entry.get() or default)
                except: return float(default)

            w_temp     = _sf(self.pg_w_temp,     25.0)
            w_rh       = _sf(self.pg_w_rh,       35.0)
            w_wind_spd = _sf(self.pg_w_wind_spd, 20.0)
            w_wind_dir = _sf(self.pg_w_wind_dir, 270.0)
            w_rain     = _sf(self.pg_w_rain,      0.0)
            w_ffmc     = _sf(self.pg_w_ffmc,     86.0)
            w_dmc      = _sf(self.pg_w_dmc,      55.0)
            w_dc       = _sf(self.pg_w_dc,      220.0)

            pg_baker = WeatherBaker(year_length=365)
            for day in range(365):
                pg_baker.set_day(day, temp=w_temp, rh=w_rh, wind_spd=w_wind_spd,
                                 wind_dir=w_wind_dir, rain=w_rain,
                                 ffmc=w_ffmc, dmc=w_dmc, dc=w_dc)
            pg_baker.bake(wea_path, 0.0, 0.0, 2024)

            self.log_event("Proving Grounds lab ready for launch!", "SUCCESS")
            self.bake_pg_btn.configure(state="normal", text="BAKE TEST LAB (.pocmap & .pocwea)")

        except Exception as e:
            self.log_event(f"Lab Error: {str(e)}", "ERROR")
            self.bake_pg_btn.configure(state="normal", text="BAKE TEST LAB (.pocmap & .pocwea)")

if __name__ == "__main__":
    app = POC_Studio()
    app.mainloop()