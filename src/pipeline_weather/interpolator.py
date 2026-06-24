import numpy as np
import pandas as pd
from datetime import datetime, timedelta

class SyntheticSeasonGenerator:
    def __init__(self, year: int):
        self.year = year

    def _cosine_interpolate(self, y1, y2, mu):
        """Smoothly interpolates between two values."""
        mu2 = (1 - np.cos(mu * np.pi)) / 2
        return y1 * (1 - mu2) + y2 * mu2

    def generate_smooth_season(self, anchors: list) -> pd.DataFrame:
        """
        Generates a perfectly smooth 365-day weather dataset.
        anchors: List of dicts {'day': int, 'temp': float, 'rh': float, 'wind': float, 'rain': float}
        """
        # Sort anchors sequentially by day of the year
        anchors = sorted(anchors, key=lambda x: x['day'])
        
        # We need data for all 365 days
        days = np.arange(1, 366)
        season_data = []

        # Start date object to construct actual Pandas dates
        start_date = datetime(self.year, 1, 1)

        for day in days:
            # 1. Find which two anchors this day falls between
            start_anchor = anchors[0]
            end_anchor = anchors[-1]
            
            for i in range(len(anchors) - 1):
                if anchors[i]['day'] <= day <= anchors[i+1]['day']:
                    start_anchor = anchors[i]
                    end_anchor = anchors[i+1]
                    break
            
            # 2. Handle days before the first anchor or after the last anchor (Flatline)
            if day <= anchors[0]['day']:
                temp, rh = anchors[0]['temp'], anchors[0]['rh']
                wind, rain = anchors[0]['wind'], anchors[0]['rain']
            elif day >= anchors[-1]['day']:
                temp, rh = anchors[-1]['temp'], anchors[-1]['rh']
                wind, rain = anchors[-1]['wind'], anchors[-1]['rain']
            else:
                # 3. Apply your Cosine Math for days between anchors
                duration = end_anchor['day'] - start_anchor['day']
                mu = (day - start_anchor['day']) / duration
                
                temp = self._cosine_interpolate(start_anchor['temp'], end_anchor['temp'], mu)
                rh = self._cosine_interpolate(start_anchor['rh'], end_anchor['rh'], mu)
                wind = self._cosine_interpolate(start_anchor['wind'], end_anchor['wind'], mu)
                
                # Rain shouldn't be interpolated (it doesn't normally gradually ramp up over a month)
                # but we will hold the start anchor's rain value for the duration
                rain = start_anchor['rain'] 

            # 4. Append to data list matching the exact OpenMeteo column format
            current_date = start_date + timedelta(days=int(day - 1))
            season_data.append({
                'date': current_date.date(),
                'temperature_c': round(temp, 2),
                'relative_humidity': round(rh, 2),
                'wind_speed_kmh': round(wind, 2),
                'rain_24h_mm': round(rain, 2)
            })

        # 5. Return the exact same DataFrame structure as the real-world fetcher!
        return pd.DataFrame(season_data)