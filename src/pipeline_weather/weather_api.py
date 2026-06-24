import os
import requests
import pandas as pd
from datetime import datetime

# ==============================================================================
# 1. LIVE TELEMETRY (For instant deployment / single-day ops)
# ==============================================================================
def fetch_live_telemetry(lat: float, lon: float, log_callback) -> dict:
    """Fetches real-world current weather data from Open-Meteo."""
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,cloud_cover,rain,wind_speed_10m,wind_direction_10m"
    
    log_callback(f"Requesting atmospheric telemetry for [{lat:.4f}, {lon:.4f}]...", "METEO")
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()['current']
        
        weather_data = {
            'temp': float(data['temperature_2m']),
            'rh': float(data['relative_humidity_2m']),
            'wind_spd': float(data['wind_speed_10m']),
            'wind_dir': float(data['wind_direction_10m']),
            'cloud': float(data['cloud_cover']) / 100.0, 
            'rain': float(data['rain'])
        }
        
        log_callback(f"Acquired: {weather_data['temp']}C, RH: {weather_data['rh']}%, Wind: {weather_data['wind_spd']}km/h @ {weather_data['wind_dir']}°", "OK")
        return weather_data
        
    except Exception as e:
        log_callback(f"Satellite telemetry failed: {e}", "ERROR")
        return None

# ==============================================================================
# 2. HISTORICAL CLIMATOLOGY (For seasonal baselines and FWI tuning)
# ==============================================================================
class OpenMeteoFetcher:
    def __init__(self):
        self.base_url = "https://archive-api.open-meteo.com/v1/archive"
        
    def fetch_historical_years(self, lat: float, lon: float, end_year: int, years_back: int) -> pd.DataFrame:
        """
        Fetches daily noon-time (12:00 LST approximation) weather data.
        Returns a Pandas DataFrame containing the required FWI inputs.
        """
        start_year = end_year - years_back + 1
        start_date = f"{start_year}-01-01"
        end_date = f"{end_year}-12-31"
        
        print(f"[API] Requesting data for {lat}, {lon} from {start_date} to {end_date}...")

        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
            "hourly": ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "wind_direction_10m", "precipitation"],
            "timezone": "auto" 
        }

        response = requests.get(self.base_url, params=params)
        response.raise_for_status()

        data = response.json()
        
        df = pd.DataFrame({
            "time": pd.to_datetime(data["hourly"]["time"]),
            "temperature_c": data["hourly"]["temperature_2m"],
            "relative_humidity": data["hourly"]["relative_humidity_2m"],
            "wind_speed_kmh": data["hourly"]["wind_speed_10m"],
            "wind_direction_deg": data["hourly"]["wind_direction_10m"],
            "precipitation_mm": data["hourly"]["precipitation"]
        })

        # Canadian FWI system requirements: NOON LST readings and 24-hour total precipitation.
        noon_data = df[df['time'].dt.hour == 12].copy()
        noon_data['date'] = noon_data['time'].dt.date
        
        df['date'] = df['time'].dt.date
        daily_rain = df.groupby('date')['precipitation_mm'].sum().reset_index()
        daily_rain = daily_rain.rename(columns={'precipitation_mm': 'rain_24h_mm'})

        final_daily_df = pd.merge(noon_data, daily_rain, on='date')
        final_daily_df = final_daily_df.drop(columns=['time'])
        final_daily_df = final_daily_df.reset_index(drop=True)
        
        return final_daily_df

    def save_to_cache(self, df: pd.DataFrame, lat: float, lon: float, start_year: int, end_year: int):
        """Saves the raw downloaded data to a CSV in the official cache folder."""
        # Updated to match your project_structure.txt
        cache_dir = os.path.join("assets", "cache", "weather_data")
        os.makedirs(cache_dir, exist_ok=True)
        
        filename = os.path.join(cache_dir, f"hist_{lat}_{lon}_{start_year}_to_{end_year}.csv")
        df.to_csv(filename, index=False)
        print(f"[API] Saved raw historical data to {filename}")
        return filename