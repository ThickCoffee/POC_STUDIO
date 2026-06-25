import struct
import numpy as np
import os

class WeatherBaker:
    def __init__(self, year_length=365):
        self.year_length = year_length
        # 8 parameters per day:
        # [0] temp_c, [1] rh, [2] wind_spd, [3] wind_dir,
        # [4] rain_24h_mm (daily total), [5] ffmc, [6] dmc, [7] dc
        self.season_data = np.zeros((self.year_length, 8), dtype=np.float32)
        
    def set_day(self, day_index: int, temp: float, rh: float, wind_spd: float, 
                wind_dir: float, rain: float, ffmc: float, dmc: float, dc: float):
        """Populates the specific day's data matrix."""
        if 0 <= day_index < self.year_length:
            self.season_data[day_index] = [temp, rh, wind_spd, wind_dir, rain, ffmc, dmc, dc]
        else:
            raise IndexError(f"Day index {day_index} out of bounds.")
        
    def bake(self, output_filepath: str, lat: float, lon: float, year: int):
        """Packs the header + 2D numpy array into a flat binary file (.pocwea)"""
        print(f"[BAKER] Assembling binary for {output_filepath}...")
        
        dir_part = os.path.dirname(output_filepath)
        if dir_part:
            os.makedirs(dir_part, exist_ok=True)
        
        try:
            with open(output_filepath, 'wb') as file:
                # 1. WRITE THE 24-BYTE HEADER
                # <4sIIfff: 4-byte string, 2 uint32s, 3 float32s (Little Endian)
                header_bytes = struct.pack('<4sIIfff', b'POCW', int(year), int(self.year_length), 0.0, float(lat), float(lon))
                file.write(header_bytes)
                
                # 2. WRITE THE CONTINUOUS WEATHER ARRAY
                # We bypass the slow 'for' loop and dump the numpy memory directly.
                # .astype('<f4') guarantees Little-Endian 32-bit floats for Odin.
                file.write(self.season_data.astype('<f4').tobytes())
                
            actual_size = os.path.getsize(output_filepath)
            expected_size = 24 + self.year_length * 8 * 4
            print(f"[BAKER] Success! Wrote Header (24 bytes) + {self.year_length} days ({actual_size} bytes). Expected: {expected_size}.")
            return actual_size == expected_size
            
        except Exception as e:
            print(f"[BAKER] CRITICAL ERROR during bake: {e}")
            return False