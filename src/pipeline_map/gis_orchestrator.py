import os
import re
from shapely.geometry import box
from rasterio.transform import from_bounds
from pipeline_map import topo, fuels, osm, baker

def extract_odin_enums(odin_filepath: str, log_callback) -> dict:
    """Scans the Odin enum file to find the FuelType order and maps Strings to Ints."""
    fuel_map = {}
    try:
        with open(odin_filepath, 'r') as f:
            content = f.read()
            
        match = re.search(r'FuelType\s*::\s*enum.*?\{(.*?)\}', content, re.DOTALL)
        if match:
            enum_block = match.group(1)
            clean_lines = [line.split('//')[0].strip() for line in enum_block.split('\n')]
            enum_names = [word.strip(',') for line in clean_lines for word in line.split() if word]
            
            for index, name in enumerate(enum_names):
                fuel_map[name] = index
                
        log_callback(f"Successfully mapped {len(fuel_map)} FuelType enums from Odin.", "SYS")
    except Exception as e:
        log_callback(f"Error parsing Odin enums: {e}", "ERROR")
        
    return fuel_map

def run_gis_pipeline(lat: float, lon: float, country: str, province: str, region: str, map_name: str, 
                     api_key: str, fuel_tif: str, odin_path: str, log_callback):
    """Orchestrates the entire map baking process directly into the IGNIS engine."""
    
    # 1. BOUNDING BOX MATH
    METERS_PER_DEGREE_LAT = 111320.0
    METERS_PER_DEGREE_LON = 63850.0  
    
    size = 1024
    res = 30.0
    
    map_meters = size * res
    half_meters = map_meters / 2.0
    
    north = lat + (half_meters / METERS_PER_DEGREE_LAT)
    south = lat - (half_meters / METERS_PER_DEGREE_LAT)
    east = lon + (half_meters / METERS_PER_DEGREE_LON)
    west = lon - (half_meters / METERS_PER_DEGREE_LON)
    
    params = {
        'width': size,
        'height': size,
        'resolution': res,
        'north': north,
        'south': south,
        'east': east,
        'west': west,
        'fbp_tif_path': fuel_tif
    }
    
    log_callback(f"Calculated Bounding Box: N:{north:.4f}, S:{south:.4f}, E:{east:.4f}, W:{west:.4f}", "SYS")

    # 2. DYNAMIC ODIN PARSING
    fuel_map = extract_odin_enums(odin_path, log_callback)
    if not fuel_map:
        log_callback("CRITICAL: Could not load FuelTypes from Odin. Aborting.", "ERROR")
        return None

    # 3. DIRECTORY & NAMING STRUCTURE
    safe_region = region.replace(" ", "_").lower()
    safe_name = map_name.replace(" ", "_").lower()
    
    # Target: IGNIS/assets/maps/Canada/Yukon/klondike/
    ignis_base = r"C:\Users\cread\VSCode_Projects\IGNIS\assets\maps"
    target_dir = os.path.join(ignis_base, country, province, safe_region)
    os.makedirs(target_dir, exist_ok=True)
    
    final_filepath = os.path.join(target_dir, f"{safe_name}.pocmap")
    display_name = f"{province}: {region} - {map_name}"

    try:
        # 4. TOPOGRAPHY
        def topo_log(msg): log_callback(msg, "TOPO")
        elev, slope, aspect = topo.get_topography(api_key, south, north, west, east, size, size, res, safe_name, topo_log)
        
        # 5. FUELS 
        def fuel_log(msg): log_callback(msg, "FUEL")
        transform = from_bounds(west, south, east, north, size, size)
        fuel_grid, soil_array = fuels.generate_baseline_environment(params, fuel_map, transform, fuel_log)
        
        # 6. OPEN STREET MAPS (Infrastructure & Water)
        def osm_log(msg): log_callback(msg, "OSM")
        bounds_poly = box(west, south, east, north)
        fuel_grid = osm.rasterize_infrastructure(bounds_poly, transform, fuel_grid, fuel_map, osm_log)
        
        # 7. PACK BINARY
        final_path = baker.export_pocmap(
            output_filepath=final_filepath, 
            display_name=display_name,      
            width=size, height=size, resolution=res,
            center_lat=lat, center_lon=lon,
            elev=elev, slope=slope, aspect=aspect,
            fuel_grid=fuel_grid, soil_array=soil_array,
            log_callback=log_callback
        )
        
        return final_path
        
    except Exception as e:
        log_callback(f"Pipeline Failed: {str(e)}", "ERROR")
        return None