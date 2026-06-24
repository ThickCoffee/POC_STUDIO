# ==============================================================================
# File: src/pipeline/osm.py
# Purpose: Downloads and rasterizes OpenStreetMap water and roads.
# ==============================================================================
import os
import osmnx as ox
from rasterio.features import rasterize

""" Neatly puts the JSON files from OSM into 'osmnx' folder to keep cache folder clean """
os.makedirs("cache/osmnx", exist_ok=True)
ox.settings.cache_folder = "cache/osmnx"

def rasterize_infrastructure(bounds_poly, transform, fuel_grid, fuel_map, status_callback):
    
    IDX_HIGHWAY   = fuel_map.get("Road_Highway", 22)
    IDX_DIRT_ROAD = fuel_map.get("Road_Dirt", 21)
    IDX_RIVER     = fuel_map.get("Water_River", 23)
    IDX_LAKE      = fuel_map.get("Water_Lake", 27)

    def meters_to_degrees(meters):
        return meters / 111320.0

    # 1. WATER BODIES
    try:
        water = ox.features_from_polygon(bounds_poly, tags={"natural": ["water", "lake"]})
        if not water.empty:
            # ADDED: all_touched=True
            rasterize([(geom, IDX_LAKE) for geom in water.geometry], out=fuel_grid, transform=transform, all_touched=True)
            status_callback(f" -> Mapped {len(water)} lakes/ponds.")
        
        rivers = ox.features_from_polygon(bounds_poly, tags={"waterway": ["river", "stream"]})
        if not rivers.empty:
            river_shapes = [(geom.buffer(meters_to_degrees(10.0)), IDX_RIVER) for geom in rivers.geometry]
            rasterize(river_shapes, out=fuel_grid, transform=transform, all_touched=True)
            status_callback(f" -> Mapped {len(rivers)} rivers.")
    except Exception as e:
        status_callback(f" -> Water mapping skipped: {e}")

    # 2. ROADS & HIGHWAYS
    try:
        hwys = ox.features_from_polygon(bounds_poly, tags={"highway": ["motorway", "trunk", "primary", "secondary"]})
        if not hwys.empty:
            road_shapes = [(geom.buffer(meters_to_degrees(10.0)), IDX_HIGHWAY) for geom in hwys.geometry]
            rasterize(road_shapes, out=fuel_grid, transform=transform, all_touched=True)
            status_callback(f" -> Mapped {len(hwys)} highways.")
            
        dirt = ox.features_from_polygon(bounds_poly, tags={"highway": ["tertiary", "unclassified", "track"]})
        if not dirt.empty:
            dirt_shapes = [(geom.buffer(meters_to_degrees(5.0)), IDX_DIRT_ROAD) for geom in dirt.geometry]
            rasterize(dirt_shapes, out=fuel_grid, transform=transform, all_touched=True)
            status_callback(f" -> Mapped {len(dirt)} dirt roads.")
    except Exception as e:
        status_callback(f" -> Road mapping skipped: {e}")

    return fuel_grid