import re

def to_decimal_degrees(coord_string: str):
    """
    Takes a string like "64°03'29.64\"N 139°26'04.66\"W" or "64.05, -139.43"
    and forces it into a strict (float_lat, float_lon) tuple.
    """
    upper_str = coord_string.upper().strip()
    
    # 1. Check if it's already a simple decimal (e.g. 55.0, -115.0)
    if ',' in upper_str and not 'N' in upper_str and not 'S' in upper_str:
        parts = upper_str.split(',')
        try:
            return float(parts[0].strip()), float(parts[1].strip())
        except ValueError:
            raise ValueError("Invalid decimal format. Use 'lat, lon'.")

    # 2. Parse complex DMS (Degrees, Minutes, Seconds)
    numbers = [float(x) for x in re.findall(r'[-+]?\d*\.\d+|\d+', upper_str)]
    directions = re.findall(r'[NSWE]', upper_str)
    
    lat, lon = 0.0, 0.0

    if len(numbers) == 2: 
        lat, lon = numbers[0], numbers[1]
    elif len(numbers) == 4:
        lat = numbers[0] + (numbers[1] / 60.0)
        lon = numbers[2] + (numbers[3] / 60.0)
    elif len(numbers) >= 6:
        lat = numbers[0] + (numbers[1] / 60.0) + (numbers[2] / 3600.0)
        lon = numbers[3] + (numbers[4] / 60.0) + (numbers[5] / 3600.0)
    else: 
        raise ValueError("Cannot parse coordinate numbers.")

    if len(directions) >= 2:
        lat, lon = abs(lat), abs(lon)
        if directions[0] == 'S': lat = -lat
        if directions[1] == 'W': lon = -lon
        
    return lat, lon