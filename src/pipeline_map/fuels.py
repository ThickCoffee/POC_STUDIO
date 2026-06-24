# ==============================================================================
# File: src/pipeline_map/fuels.py
# Purpose: Parses the Canadian National FBP GeoTIFF. 
#          Dynamically reprojects the data to match GPS coordinates and translates
#          the government integer codes into the engine's FuelType enum.
# ==============================================================================

import os
import numpy as np
import rasterio
from rasterio.vrt import WarpedVRT
from rasterio.enums import Resampling

# ---------------------------------------------------------
# GOVERNMENT TO ODIN TRANSLATION DICTIONARY
# Maps raw raster/GIS integer codes to your exact Odin FuelType enum strings
# ---------------------------------------------------------
NRCAN_FBP_DICTIONARY = {
    # --- Conifers ---
    1: "C1_Spruce_Lichen_Woodland",
    2: "C2_Boreal_Spruce",
    3: "C3_Mature_Jack_Pine",
    4: "C4_Immature_Jack_Pine",
    5: "C5_Red_and_White_Pine",
    6: "C6_Conifer_Plantation",
    7: "C7_Pon_Pine_D_Fir",
    
    # --- Deciduous & Mixed ---
    8: "D1_Leafless_Aspen",
    9: "M1_Boreal_Mixedwood_Leafless",
    10: "M2_Boreal_Mixedwood_Green",
    11: "M3_Dead_Balsam_Leafless",
    12: "M4_Dead_Balsam_Green",
    
    # --- Slash ---
    13: "S1_Jack_Pine_Slash",
    14: "S2_White_Spruce_Balsam_Slash",
    15: "S3_Coastal_Cedar_Hem_DFir_Slash",
    
    # --- Open/Grass ---
    16: "O1a_Matted_Grass",
    17: "O1b_Standing_Grass",
    
    # --- Values at Risk (Usually populated by OSM data overrides) ---
    90: "Structure_VAR",
    91: "PowerlinePole",
    92: "Farm_Field_Planted_Green",
    93: "Oil_Lease_Site",
    
    # --- Non-burnables ---
    100: "Road_Dirt",
    101: "Road_Highway",
    102: "Water_River",
    103: "Water_Lake",
    104: "Rock_Bare"
}


def generate_baseline_environment(params, fuel_map, dst_transform, status_callback):
    """
    Attempts to read spatial fuel from a local GeoTIFF.
    Falls back to a solid blanket of C7 Pine if no file is provided.
    """
    
    # 1. ESTABLISH FALLBACKS
    idx_pine = fuel_map.get("C7_Pon_Pine_D_Fir", 6)
    
    # Default everything to C7 Pine and Silt Loam (Index 1)
    fuel_grid = np.full((params['height'], params['width']), idx_pine, dtype=np.uint8)
    soil_array = np.full(params['height'] * params['width'], 1, dtype=np.uint8)

    tif_path = params.get('fbp_tif_path', '').strip()

    # 2. VALIDATION CHECK
    if not os.path.exists(tif_path) or not tif_path.endswith('.tif'):
        status_callback("   -> [WARNING] No valid FBP GeoTIFF found. Defaulting to solid C-7 Pine.")
        return fuel_grid, soil_array

    status_callback("   -> Warping and cropping Canadian FBP GeoTIFF...")

    # 3. SPATIAL EXTRACTION
    try:
        # Open the massive source file
        with rasterio.open(tif_path) as src:
            # Create a Virtual Raster that automatically bends the Canadian map to GPS Lat/Lon (EPSG:4326)
            with WarpedVRT(src, crs="EPSG:4326", resampling=Resampling.nearest) as vrt:
                
                # Read ONLY the pixels that fall within our specific map boundaries
                window = vrt.window(params['west'], params['south'], params['east'], params['north'])
                raw_fuels = vrt.read(1, window=window, out_shape=(params['height'], params['width']))

                unique_fuels = np.unique(raw_fuels)
                status_callback(f"   -> [DIAGNOSTIC] Raw raster integers found in this crop: {unique_fuels}")

                # 4. TRANSLATE DATA TO ODIN ENUM (vectorized — avoids ~1M Python iterations)
                idx_fallback = fuel_map.get("Rock_Bare", 0)
                
                max_code = max(NRCAN_FBP_DICTIONARY.keys())
                lookup = np.full(max_code + 1, idx_fallback, dtype=np.uint8)
                for gov_code, fuel_name in NRCAN_FBP_DICTIONARY.items():
                    lookup[gov_code] = fuel_map.get(fuel_name, idx_fallback)

                raw_int = raw_fuels.astype(np.int32)
                in_range = (raw_int >= 0) & (raw_int <= max_code)
                fuel_grid = np.where(
                    in_range,
                    lookup[np.clip(raw_int, 0, max_code)],
                    idx_fallback
                ).astype(np.uint8)
                        
        status_callback("   -> FBP Raster successfully applied.")
    except Exception as e:
        status_callback(f"   -> [ERROR] Failed to read Fuel GeoTIFF: {e}. Defaulting to C-7.")

    return fuel_grid, soil_array