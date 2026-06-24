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
from pipeline_map.gis_orchestrator import run_gis_pipeline
from pipeline_weather.weather_api import fetch_live_telemetry
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
        self.fuel_tif_path.insert(0, r"C:\Users\cread\VSCode_Projects\POC_STUDIO\assets\nrcan_fbp_fuels.tif")
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
        
        # 6. Weather & Output
        ctk.CTkLabel(pg_ctrls, text="Weather Target:", font=ctk.CTkFont(weight="bold"), text_color=Palette.TEXT_LIGHT).grid(row=8, column=0, sticky="e", pady=(20,0), padx=(0,15))
        self.pg_weather = ctk.CTkOptionMenu(pg_ctrls, values=["Moderate (Blue) - NO Wind", "Very High (Orange)", "Extreme (Red) - High Wind", "Extreme Drought (High BUI)"], fg_color=Palette.DARK_WIDGET, button_color=Palette.DARK_WIDGET_HOVER)
        self.pg_weather.grid(row=8, column=1, sticky="ew", pady=(20,0))
        
        ctk.CTkLabel(pg_ctrls, text="Test Name:", font=ctk.CTkFont(weight="bold"), text_color=Palette.TEXT_LIGHT).grid(row=9, column=0, sticky="e", pady=(10,0), padx=(0,15))
        self.pg_name = ctk.CTkEntry(pg_ctrls, placeholder_text="e.g. Test1_ExpCurve", fg_color=Palette.DARK_PANEL, text_color="white")
        self.pg_name.grid(row=9, column=1, sticky="ew", pady=(10,0))

        self.bake_pg_btn = ctk.CTkButton(pg_ctrls, text="BAKE TEST LAB (.pocmap & .pocwea)", font=ctk.CTkFont(weight="bold"), fg_color=Palette.DARK_ACCENT, hover_color=Palette.DARK_ACCENT_HOVER, text_color="white", command=self.execute_pg_bake)
        self.bake_pg_btn.grid(row=10, column=0, columnspan=2, sticky="w", pady=(30, 20))

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

    def _update_pg_preview(self, *args):
        self.ax.clear()
        self.ax.set_axis_off()
        self.ax.set_facecolor(Palette.DARK_PANEL)
        
        # 1. Parse Parameters safely
        try: size = int(self.pg_size.get() or 512)
        except: size = 512
        try: res = float(self.pg_res.get() or 10.0)
        except: res = 10.0
        try: slope_val = float(self.pg_slope.get() or 0.0)
        except: slope_val = 0.0

        map_meters = size * res
        slope_rad = np.radians(slope_val)

        # 2. Build Physical Meshgrid
        x = np.linspace(-map_meters/2, map_meters/2, 40)
        y = np.linspace(-map_meters/2, map_meters/2, 40)
        X, Y = np.meshgrid(x, y)
        
        shape = self.pg_shape.get()
        Z = np.zeros_like(X)

        # 3. Apply Geometry
        if shape == "Ramp":
            Z = (Y - np.min(Y)) * np.tan(slope_rad)
        elif shape == "Ridge":
            max_z = (map_meters/2) * np.tan(slope_rad)
            Z = max_z - (np.abs(X) * np.tan(slope_rad))
        elif shape == "Saddle":
            Z = (X**2 - Y**2) * (np.tan(slope_rad) / map_meters)
        elif shape == "Bowl":
            Z = (X**2 + Y**2) * (np.tan(slope_rad) / map_meters)

        # 4. Lock Aspect Ratio to 1:1:1 Reality
        z_range = np.ptp(Z) if np.ptp(Z) > 0 else 1.0
        self.ax.set_box_aspect((1, 1, z_range / map_meters))
        
        self.ax.plot_surface(X, Y, Z, cmap='magma', edgecolor='none')
        self.ax.set_title(f"{shape} Geometry\n{map_meters}m Wide | Slope: {slope_val}°", fontsize=10, color="#94A3B8")
        
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
            self.log_event("Fetching meteorological telemetry...", "SYS")
            weather_data = fetch_live_telemetry(self.active_lat, self.active_lon, self.log_event)
            
            if weather_data:
                safe_region = region.replace(" ", "_").lower()
                safe_name = name.replace(" ", "_").lower()
                
                ignis_base = r"C:\Users\cread\VSCode_Projects\IGNIS\assets\maps"
                target_dir = os.path.join(ignis_base, country, province, safe_region)
                os.makedirs(target_dir, exist_ok=True)
                
                final_filepath = os.path.join(target_dir, f"{safe_name}.pocwea")
                
                baker = WeatherBaker(year_length=365)
                
                # Broadcast the live conditions across the array
                for day in range(365):
                    baker.set_day(
                        day_index=day,
                        temp=weather_data['temp'],
                        rh=weather_data['rh'],
                        wind_spd=weather_data['wind_spd'],
                        wind_dir=weather_data['wind_dir'],
                        rain=weather_data['rain'],
                        ffmc=85.0,  
                        dmc=6.0,    
                        dc=15.0     
                    )
                
                current_year = datetime.datetime.now().year
                success = baker.bake(final_filepath, self.active_lat, self.active_lon, current_year)
                
                if success:
                    self.weather_status.configure(text=f"[x] Weather Baked (.pocwea)", text_color=Palette.SUCCESS)
                    self.log_event("Master Pipeline Complete!", "SUCCESS")
            else:
                self.log_event("Weather fetch failed. Try again later.", "WARN")

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
            
            size = 1024
            res = 30.0
            map_meters = size * res
            
            # 1. Parse Fuel Enums directly from Odin
            odin_file = self.odin_path.get().strip()
            fuel_dict = {}
            with open(odin_file, 'r') as f:
                content = f.read()
                match = re.search(r'FuelType\s*::\s*enum\s*u8\s*\{([^}]+)\}', content)
                if match:
                    idx = 0
                    for line in match.group(1).split('\n'):
                        line = line.split('//')[0].strip()
                        if not line: continue
                        parts = line.split('=')
                        name = parts[0].strip().strip(',')
                        if len(parts) > 1:
                            idx = int(parts[1].strip().strip(','))
                        fuel_dict[name] = idx
                        idx += 1
            
            # 2. Build Base Geometry
            try: slope_val = float(self.pg_slope.get() or 0.0)
            except: slope_val = 0.0
            slope_rad = np.radians(slope_val)
            
            x = np.linspace(-map_meters/2, map_meters/2, size)
            y = np.linspace(-map_meters/2, map_meters/2, size)
            X, Y = np.meshgrid(x, y)
            Z = np.zeros((size, size), dtype=np.float32)

            shape = self.pg_shape.get()
            if shape == "Ramp":
                Z = (Y - np.min(Y)) * np.tan(slope_rad)
            elif shape == "Undulations":
                freq = map_meters / 4.0 
                max_z = (map_meters/8) * np.tan(slope_rad)
                Z = np.sin(X / freq * 2 * np.pi) * np.cos(Y / freq * 2 * np.pi) * max_z
                Z -= np.min(Z)
            
            # Calculate physical slope & aspect
            dy, dx = np.gradient(Z, res, res)
            slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2))).astype(np.float32)
            aspect = np.degrees(np.arctan2(dx, -dy)).astype(np.float32)
            aspect[aspect < 0] += 360.0

            # 3. Apply Fuel Layout
            base_int = fuel_dict.get(self.pg_fuel.get(), 0)
            sec_int = fuel_dict.get(self.pg_sec_fuel.get(), 0)
            
            fuel_grid = np.full((size, size), base_int, dtype=np.uint8)
            pattern = self.pg_fuel_pattern.get()
            
            if pattern == "Half-and-Half (Left/Right)":
                fuel_grid[:, int(size/2):] = sec_int
            elif pattern == "Checkerboard":
                chk = 64
                for i in range(0, size, chk):
                    for j in range(0, size, chk):
                        if (i//chk + j//chk) % 2 == 1:
                            fuel_grid[i:i+chk, j:j+chk] = sec_int
            elif pattern == "Center VAR Block":
                c = int(size/2)
                # 9x9 block of Oil Lease
                oil_int = fuel_dict.get("Oil_Lease_Site", 0)
                fuel_grid[c-4:c+5, c-4:c+5] = oil_int
                # 3x3 block of Structure inside it
                struct_int = fuel_dict.get("Structure_VAR", 0)
                fuel_grid[c-1:c+2, c-1:c+2] = struct_int

            soil_grid = np.full((size, size), 1, dtype=np.uint8) # Silt Loam

            # 4. Save Paths
            safe_name = test_name.replace(" ", "_").lower()
            target_dir = os.path.join(r"C:\Users\cread\VSCode_Projects\IGNIS\assets\maps", "Proving_Grounds")
            os.makedirs(target_dir, exist_ok=True)
            
            map_path = os.path.join(target_dir, f"{safe_name}.pocmap")
            wea_path = os.path.join(target_dir, f"{safe_name}.pocwea")

            # 5. Pack Map Binary
            export_pocmap(map_path, f"Lab: {test_name}", size, size, res, 0.0, 0.0, Z, slope, aspect, fuel_grid, soil_grid, self.log_event)

            # 6. Pack Weather Binary
            weather_target = self.pg_weather.get()
            w_temp, w_rh, w_wind = 15.0, 50.0, 0.0
            
            if weather_target == "Extreme (Red) - High Wind":
                w_temp, w_rh, w_wind = 30.0, 20.0, 45.0
            elif weather_target == "Very High (Orange)":
                w_temp, w_rh, w_wind = 25.0, 30.0, 20.0
            elif weather_target == "Extreme Drought (High BUI)":
                w_temp, w_rh, w_wind = 35.0, 15.0, 10.0

            baker = WeatherBaker(year_length=365)
            for day in range(365):
                baker.set_day(day, temp=w_temp, rh=w_rh, wind_spd=w_wind, wind_dir=270.0, rain=0.0, ffmc=90.0, dmc=150.0, dc=500.0)
            baker.bake(wea_path, 0.0, 0.0, 2024)

            self.log_event("Proving Grounds lab ready for launch!", "SUCCESS")
            self.bake_pg_btn.configure(state="normal", text="BAKE TEST LAB (.pocmap & .pocwea)")

        except Exception as e:
            self.log_event(f"Lab Error: {str(e)}", "ERROR")
            self.bake_pg_btn.configure(state="normal", text="BAKE TEST LAB (.pocmap & .pocwea)")

if __name__ == "__main__":
    app = POC_Studio()
    app.mainloop()