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

# ==============================================================================
# SOIL TEXTURE DERIVATION
# ==============================================================================
# Indices match Odin's Soil_Texture enum order exactly:
#   0 = Coarse_Sand | 1 = Silt_Loam | 2 = Clay_Loam | 3 = Bedrock
SOIL_COARSE_SAND = 0
SOIL_SILT_LOAM   = 1
SOIL_CLAY_LOAM   = 2
SOIL_BEDROCK     = 3

# Base soil texture for each Canadian FBP fuel type, derived from the ecological
# substrate associations documented in the Soil Landscapes of Canada v3.2 and CFS
# fire ecology literature. This is the primary signal for soil classification.
FUEL_TO_SOIL_BASE = {
    # Conifer — characteristically well-drained, coarse-textured substrates
    "C1_Spruce_Lichen_Woodland":       SOIL_COARSE_SAND,  # Lichen grows on thin coarse-over-rock substrate
    "C2_Boreal_Spruce":                SOIL_SILT_LOAM,    # Typical boreal mineral/loamy moraine soil
    "C3_Mature_Jack_Pine":             SOIL_COARSE_SAND,  # Jack Pine is an obligate sand-barren species
    "C4_Immature_Jack_Pine":           SOIL_COARSE_SAND,  # Same substrate as C3
    "C5_Red_and_White_Pine":           SOIL_COARSE_SAND,  # Eastern pine — sandy/glaciofluvial outwash
    "C6_Conifer_Plantation":           SOIL_SILT_LOAM,    # Planted on prepared loamy mineral soil
    "C7_Pon_Pine_D_Fir":               SOIL_SILT_LOAM,    # IDF zone — well-drained but deeper mineral soils
    # Deciduous / Mixed
    "D1_Leafless_Aspen":               SOIL_SILT_LOAM,    # Aspen grows on good loamy mineral soil
    "M1_Boreal_Mixedwood_Leafless":    SOIL_SILT_LOAM,
    "M2_Boreal_Mixedwood_Green":       SOIL_SILT_LOAM,
    "M3_Dead_Balsam_Leafless":         SOIL_CLAY_LOAM,    # Balsam fir thrives in wet, impeded-drainage sites
    "M4_Dead_Balsam_Green":            SOIL_CLAY_LOAM,
    # Slash
    "S1_Jack_Pine_Slash":              SOIL_COARSE_SAND,  # Logged from C3/C4 sandy substrate
    "S2_White_Spruce_Balsam_Slash":    SOIL_SILT_LOAM,
    "S3_Coastal_Cedar_Hem_DFir_Slash": SOIL_CLAY_LOAM,    # Coastal — organic-rich, wet soils
    # Open / Grass
    "O1a_Matted_Grass":                SOIL_CLAY_LOAM,    # Matted grass signals wet, poorly drained flats
    "O1b_Standing_Grass":              SOIL_SILT_LOAM,    # Upland meadow — well-drained mineral
    # Values at Risk
    "Structure_VAR":                   SOIL_SILT_LOAM,
    "PowerlinePole":                   SOIL_SILT_LOAM,
    "Farm_Field_Planted_Green":        SOIL_SILT_LOAM,
    "Oil_Lease_Site":                  SOIL_SILT_LOAM,
    # Non-burnables
    "Road_Dirt":                       SOIL_SILT_LOAM,
    "Road_Highway":                    SOIL_BEDROCK,      # Impermeable pavement = effectively bedrock
    "Water_River":                     SOIL_CLAY_LOAM,    # Fluvial terraces — fine sediment deposition
    "Water_Stream":                    SOIL_CLAY_LOAM,
    "Water_Creek":                     SOIL_CLAY_LOAM,
    "Water_Pond":                      SOIL_CLAY_LOAM,
    "Water_Lake":                      SOIL_CLAY_LOAM,
    "Rock_Bare":                       SOIL_BEDROCK,
}

_WATER_FUEL_NAMES = (
    "Water_River", "Water_Stream", "Water_Creek", "Water_Pond", "Water_Lake"
)


def _dilate_bool_2d(mask: np.ndarray, radius: int) -> np.ndarray:
    """Expand a 2D boolean mask by `radius` cells (circular footprint, pure numpy)."""
    result = mask.copy()
    h, w = mask.shape
    padded = np.pad(mask, radius, mode='constant', constant_values=False)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dy * dy + dx * dx <= radius * radius:
                result |= padded[radius + dy: radius + dy + h,
                                 radius + dx: radius + dx + w]
    return result


def derive_soil_array(
    fuel_grid_2d: np.ndarray,
    elev_flat: np.ndarray,
    fuel_map: dict,
    status_callback,
) -> np.ndarray:
    """
    Derives a per-cell Soil_Texture index (uint8) from three signals:

    1. Fuel-type ecological association (primary)
       Each FBP fuel type implies a characteristic substrate — Jack Pine grows on
       coarse sand barrens; matted grass (O1a) signals wet impeded drainage; balsam
       fir favours clay-rich lowland soils; lichen woodland sits on thin rocky substrate.

    2. Proximity to permanent water bodies (secondary correction)
       Cells within ~90 m (3 cells at 30 m) of any water body → Clay_Loam.
       These are riparian terraces with fine sediment deposition and high water table.
       This correction runs AFTER OSM water features are in the fuel grid, so
       OSM-sourced creeks and lakes are included, not just NRCan raster water codes.

    3. Elevation (tertiary correction)
       Above 2 000 m: thin alpine mineral soils → Silt_Loam cells → Coarse_Sand.
       Above 2 500 m: exposed subalpine/alpine rock → non-Clay_Loam → Bedrock.
       Clay_Loam is protected in both tiers (wet basins occur at any elevation).

    Returns a flat uint8 array (length = h × w) matching Odin's Soil_Texture enum.
    """
    h, w = fuel_grid_2d.shape

    # ── Step 1: Fuel-type base mapping ────────────────────────────────────────
    max_ordinal = max(fuel_map.values(), default=30)
    lookup = np.full(max_ordinal + 2, SOIL_SILT_LOAM, dtype=np.uint8)
    for fuel_name, soil_idx in FUEL_TO_SOIL_BASE.items():
        ordinal = fuel_map.get(fuel_name)
        if ordinal is not None and ordinal <= max_ordinal:
            lookup[ordinal] = soil_idx

    flat_fuel = fuel_grid_2d.flatten().astype(np.int32)
    soil_2d = lookup[np.clip(flat_fuel, 0, max_ordinal)].reshape(h, w)

    # ── Step 2: Water proximity correction ────────────────────────────────────
    water_ordinals = [
        fuel_map[n] for n in _WATER_FUEL_NAMES if n in fuel_map
    ]
    if water_ordinals:
        water_mask = np.isin(fuel_grid_2d, water_ordinals)
        if np.any(water_mask):
            near_water = _dilate_bool_2d(water_mask, radius=3)
            apply_mask = near_water & ~water_mask & (soil_2d != SOIL_BEDROCK)
            soil_2d[apply_mask] = SOIL_CLAY_LOAM

    # ── Step 3: Elevation correction ──────────────────────────────────────────
    if elev_flat is not None and len(elev_flat) == h * w:
        elev_2d = elev_flat.reshape(h, w)
        # Mid-alpine: thin soils — only upgrade Silt_Loam (don't touch Clay or Sand)
        soil_2d[(elev_2d > 2000.0) & (elev_2d <= 2500.0) & (soil_2d == SOIL_SILT_LOAM)] = SOIL_COARSE_SAND
        # High alpine: bedrock — protect Clay_Loam (wet alpine basins still exist)
        soil_2d[(elev_2d > 2500.0) & (soil_2d != SOIL_CLAY_LOAM)] = SOIL_BEDROCK

    # ── Diagnostic summary (appears in POC Studio console) ────────────────────
    soil_names = {
        SOIL_COARSE_SAND: "Coarse_Sand",
        SOIL_SILT_LOAM:   "Silt_Loam",
        SOIL_CLAY_LOAM:   "Clay_Loam",
        SOIL_BEDROCK:     "Bedrock",
    }
    total = h * w
    unique, counts = np.unique(soil_2d, return_counts=True)
    status_callback("   -> Soil texture distribution:")
    for u, c in zip(unique, counts):
        status_callback(f"      {soil_names.get(int(u), '?')}: {c:,} cells ({100 * c / total:.1f}%)")

    return soil_2d.flatten().astype(np.uint8)

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
    
    # Default fuel to C7 Pine. Soil is a placeholder — derive_soil_array() in
    # gis_orchestrator replaces it once OSM water features are also in fuel_grid.
    fuel_grid = np.full((params['height'], params['width']), idx_pine, dtype=np.uint8)
    soil_array = np.full(params['height'] * params['width'], SOIL_SILT_LOAM, dtype=np.uint8)

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