# ==============================================================================
# File: src/pipeline/topo.py
# Purpose: Manages DEM downloads, caching, and 3D calculus (Slope/Aspect).
# ==============================================================================
import os
import requests
import rasterio
from rasterio.enums import Resampling
import numpy as np

def compute_aspect_from_gradient(dy, dx):
    """Cardinal aspect in degrees (0=N, 90=E) matching IGNIS FBP conventions."""
    return ((90.0 - np.degrees(np.arctan2(-dy, dx))) % 360.0).astype(np.float32)

def compute_slope_aspect(elev_2d, cell_size):
    dy, dx = np.gradient(elev_2d, cell_size, cell_size)
    slope = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2))).astype(np.float32)
    aspect = compute_aspect_from_gradient(dy, dx)
    return slope, aspect

def get_topography(api_key, south, north, west, east, map_width, map_height, cell_size, map_name, status_callback):
    """Returns flat numpy arrays for elevation, slope, and aspect."""
    
    # Define our local cache path
    cache_dir = "cache"
    os.makedirs(cache_dir, exist_ok=True)
    cached_tif = os.path.join(cache_dir, f"{map_name}_dem.tif")

    # 1. Check Cache OR Download
    if os.path.exists(cached_tif):
        status_callback(f">>> Found cached topography: {cached_tif}. Skipping API download!")
    else:
        status_callback(">>> DOWNLOADING SATELLITE DEM (Costs 1 API Pull)...")
        url = f"https://portal.opentopography.org/API/globaldem?demtype=COP30&south={south}&north={north}&west={west}&east={east}&outputFormat=GTiff&API_Key={api_key}"
        
        response = requests.get(url)
        if response.status_code != 200:
            raise ConnectionError(f"OpenTopography API Failed (Code {response.status_code}). Check API Key.")
            
        with open(cached_tif, "wb") as f:
            f.write(response.content)

    # 2. Process the GeoTIFF
    status_callback(">>> CALCULATING 3D TOPOGRAPHY...")
    with rasterio.open(cached_tif) as dataset:
        elev = dataset.read(1, out_shape=(map_height, map_width), resampling=Resampling.bilinear)
    
    # 3. Calculus for Slope & Aspect
    slope, aspect = compute_slope_aspect(elev, cell_size)

    return (
        elev.astype(np.float32).flatten(),
        slope.flatten(),
        aspect.flatten()
    )