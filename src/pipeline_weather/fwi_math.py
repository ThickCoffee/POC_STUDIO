import math
import pandas as pd

class FWICalculator:
    def __init__(self, start_ffmc=85.0, start_dmc=6.0, start_dc=15.0):
        # Standard Canadian spring startup values
        self.ffmc = start_ffmc
        self.dmc = start_dmc
        self.dc = start_dc
        
        # Standard Day-Length factors for the Northern Hemisphere (Months 1-12)
        # Required for Duff and Drought drying rates based on hours of sunlight
        self.day_length_dmc = [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0]
        self.day_length_dc  = [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6]

    def calculate_ffmc(self, temp, rh, wind, rain):
        """Calculates the Fine Fuel Moisture Code (Litter and fine surface fuels)."""
        mo = 147.2 * (101.0 - self.ffmc) / (59.5 + self.ffmc)
        
        if rain > 0.5:
            rf = rain - 0.5
            if mo <= 150.0:
                mo += 42.5 * rf * math.exp(-100.0 / (251.0 - mo)) * (1.0 - math.exp(-6.93 / rf))
            else:
                mo += 42.5 * rf * math.exp(-100.0 / (251.0 - mo)) * (1.0 - math.exp(-6.93 / rf)) + 0.0015 * ((mo - 150.0) ** 2) * math.sqrt(rf)
            mo = min(mo, 250.0)

        ed = 0.942 * (rh ** 0.679) + 11.0 * math.exp((rh - 100.0) / 10.0) + 0.18 * (21.1 - temp) * (1.0 - math.exp(-0.115 * rh))
        ew = 0.618 * (rh ** 0.753) + 10.0 * math.exp((rh - 100.0) / 10.0) + 0.18 * (21.1 - temp) * (1.0 - math.exp(-0.115 * rh))

        if mo > ed:
            ko = 0.424 * (1.0 - (rh / 100.0) ** 1.7) + 0.0694 * math.sqrt(wind) * (1.0 - (rh / 100.0) ** 8)
            kd = ko * 0.581 * math.exp(0.0365 * temp)
            mo = ed + (mo - ed) * (10.0 ** -kd)
        elif mo < ew:
            kl = 0.424 * (1.0 - ((100.0 - rh) / 100.0) ** 1.7) + 0.0694 * math.sqrt(wind) * (1.0 - ((100.0 - rh) / 100.0) ** 8)
            kw = kl * 0.581 * math.exp(0.0365 * temp)
            mo = ew - (ew - mo) * (10.0 ** -kw)

        self.ffmc = 59.5 * (250.0 - mo) / (147.2 + mo)
        self.ffmc = max(0.0, min(self.ffmc, 101.0))
        return self.ffmc

    def calculate_dmc(self, temp, rh, rain, month):
        """Calculates the Duff Moisture Code (Loosely compacted organic layer)."""
        temp = max(temp, -1.1)
        if rain > 1.5:
            re = 0.92 * rain - 1.27
            mo = 20.0 + math.exp(5.6348 - self.dmc / 43.43)
            if self.dmc <= 33.0:
                b = 100.0 / (0.5 + 0.3 * self.dmc)
            elif self.dmc <= 65.0:
                b = 14.0 - 1.3 * math.log(self.dmc)
            else:
                b = 6.2 * math.log(self.dmc) - 17.2
            mo += 1000.0 * re / (48.77 + b * re)
            self.dmc = 43.43 * (5.6348 - math.log(mo - 20.0))
            self.dmc = max(0.0, self.dmc)

        dl = self.day_length_dmc[month - 1]
        k = 1.894 * (temp + 1.1) * (100.0 - rh) * dl * (1e-6)
        
        # Only dry if temp is above freezing, else just carry over
        if temp > -1.1:
            self.dmc += k
            
        return self.dmc

    def calculate_dc(self, temp, rain, month):
        """Calculates the Drought Code (Deep, compact organic layer)."""
        temp = max(temp, -2.8)
        if rain > 2.8:
            rd = 0.83 * rain - 1.27
            qo = 800.0 * math.exp(-self.dc / 400.0)
            qo += 3.937 * rd
            self.dc = 400.0 * math.log(800.0 / qo)
            self.dc = max(0.0, self.dc)

        fl = self.day_length_dc[month - 1]
        v = 0.36 * (temp + 2.8) + fl
        v = max(0.0, v)
        
        self.dc += 0.5 * v
        return self.dc

    def process_season(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Iterates over a dataframe of daily weather and appends the calculated 
        FFMC, DMC, and DC columns.
        Expects columns: ['date', 'temperature_c', 'relative_humidity', 'wind_speed_kmh', 'rain_24h_mm']
        """
        ffmc_list, dmc_list, dc_list = [], [], []

        for index, row in df.iterrows():
            # Get the month directly from the date object (1-12)
            month = row['date'].month
            
            temp = row['temperature_c']
            rh = row['relative_humidity']
            wind = row['wind_speed_kmh']
            rain = row['rain_24h_mm']

            ffmc = self.calculate_ffmc(temp, rh, wind, rain)
            dmc = self.calculate_dmc(temp, rh, rain, month)
            dc = self.calculate_dc(temp, rain, month)

            ffmc_list.append(round(ffmc, 2))
            dmc_list.append(round(dmc, 2))
            dc_list.append(round(dc, 2))

        df['ffmc'] = ffmc_list
        df['dmc'] = dmc_list
        df['dc'] = dc_list
        
        return df