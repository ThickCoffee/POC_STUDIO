# ==============================================================================
# File: src/pipeline_map/baker.py
# Purpose: Packs the raw numpy arrays into the strict C-style binary struct 
#          required by the Odin engine.
# ==============================================================================
import os
import struct
import numpy as np

def export_pocmap(output_filepath: str, display_name: str, width: int, height: int, resolution: float, 
                  center_lat: float, center_lon: float,
                  elev: np.ndarray, slope: np.ndarray, aspect: np.ndarray, 
                  fuel_grid: np.ndarray, soil_array: np.ndarray, 
                  log_callback):
    """
    Packs 5 geographic arrays into a single, contiguous .pocmap binary file.
    """
    
    log_callback(f"Baking binary map to {output_filepath}...", "BAKER")
    
    # Encode string to bytes, truncate to 63, pad to 64.
    name_bytes = display_name.encode('utf-8')[:63] 
    padded_name = name_bytes.ljust(64, b'\x00')
    
    try:
        # Notice we use output_filepath directly to IGNIS
        with open(output_filepath, 'wb') as f:
            
            header_format = '<64s 4s I I f f f'
            f.write(struct.pack(header_format, 
                                padded_name, 
                                b'POCM', 
                                int(width), 
                                int(height), 
                                float(resolution), 
                                float(center_lat), 
                                float(center_lon)))
            
            f.write(elev.astype(np.float32).flatten().tobytes())
            f.write(slope.astype(np.float32).flatten().tobytes())
            f.write(aspect.astype(np.float32).flatten().tobytes())
            f.write(fuel_grid.astype(np.uint8).flatten().tobytes())
            f.write(soil_array.astype(np.uint8).flatten().tobytes())
            
        total_cells = width * height
        expected_size = 88 + (total_cells * 14)
        actual_size = os.path.getsize(output_filepath)
        
        if expected_size == actual_size:
            log_callback(f"SUCCESS! Map baked perfectly ({actual_size / 1024 / 1024:.2f} MB).", "OK")
            return output_filepath
        else:
            log_callback(f"SIZE MISMATCH! Expected {expected_size} bytes, got {actual_size}.", "ERROR")
            return None
            
    except Exception as e:
        log_callback(f"Failed to write binary: {str(e)}", "ERROR")
        return None