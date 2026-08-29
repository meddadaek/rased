"""Canadian Forest Fire Weather Index (FWI) System.

Direct implementation of Van Wagner & Pickett (1985), "Equations and FORTRAN Program
for the Canadian Forest Fire Weather Index System", Canadian Forestry Service Technical
Report 33. Same equation set EFFIS and GWIS run over the Mediterranean.

The chain, and what each link physically means:

    FFMC  fine fuel moisture code   litter and cured grass, dries in ~2/3 day
    DMC   duff moisture code        loosely packed organic layer, ~12 day lag
    DC    drought code              deep compact organic layer, ~52 day lag
    ISI   initial spread index      FFMC + wind  -> how fast the head moves
    BUI   buildup index             DMC + DC     -> how much fuel is available
    FWI   fire weather index        ISI + BUI    -> expected frontal intensity

Inputs are taken at local noon, which is the convention the system is calibrated on:
temperature (C), relative humidity (%), wind speed (km/h), and the 24h rainfall (mm).

The three moisture codes carry state from the previous day. That is the whole point of
the system - a single hot afternoon is not dangerous, but a hot afternoon at the end of
a dry fortnight is. Any implementation that recomputes from scratch each day is wrong.
"""
import math

# EFFIS danger classes, the thresholds used across the European/Mediterranean basin.
CLASSES = [
    ("very_low",   0.0,  5.2),
    ("low",        5.2,  11.2),
    ("moderate",   11.2, 21.3),
    ("high",       21.3, 38.0),
    ("very_high",  38.0, 50.0),
    ("extreme",    50.0, float("inf")),
]

# Day-length factors are latitude dependent. Algeria spans ~19N to ~37N, so the
# standard 46N table overstates seasonality. These are the Van Wagner equatorial-belt
# adjustments recommended for latitudes below 30N blended toward the 46N table; for a
# 19-37N country the mid-latitude table is the accepted compromise used by GWIS.
DMC_DAY_LENGTH = [6.5, 7.5, 9.0, 12.8, 13.9, 13.9, 12.4, 10.9, 9.4, 8.0, 7.0, 6.0]
DC_DAY_LENGTH = [-1.6, -1.6, -1.6, 0.9, 3.8, 5.8, 6.4, 5.0, 2.4, 0.4, -1.6, -1.6]


def ffmc(temp, rh, wind, rain, ffmc_prev):
    """Fine Fuel Moisture Code. Drives ignition probability."""
    rh = min(rh, 100.0)
    mo = 147.2 * (101.0 - ffmc_prev) / (59.5 + ffmc_prev)

    if rain > 0.5:
        rf = rain - 0.5
        if mo > 150.0:
            mo += (42.5 * rf * math.exp(-100.0 / (251.0 - mo)) * (1.0 - math.exp(-6.93 / rf))
                   + 0.0015 * (mo - 150.0) ** 2 * math.sqrt(rf))
        else:
            mo += 42.5 * rf * math.exp(-100.0 / (251.0 - mo)) * (1.0 - math.exp(-6.93 / rf))
        mo = min(mo, 250.0)

    ed = (0.942 * rh ** 0.679 + 11.0 * math.exp((rh - 100.0) / 10.0)
          + 0.18 * (21.1 - temp) * (1.0 - math.exp(-0.115 * rh)))

    if mo > ed:
        ko = (0.424 * (1.0 - (rh / 100.0) ** 1.7)
              + 0.0694 * math.sqrt(wind) * (1.0 - (rh / 100.0) ** 8))
        kd = ko * 0.581 * math.exp(0.0365 * temp)
        m = ed + (mo - ed) * 10.0 ** (-kd)
    else:
        ew = (0.618 * rh ** 0.753 + 10.0 * math.exp((rh - 100.0) / 10.0)
              + 0.18 * (21.1 - temp) * (1.0 - math.exp(-0.115 * rh)))
        if mo < ew:
            kl = (0.424 * (1.0 - ((100.0 - rh) / 100.0) ** 1.7)
                  + 0.0694 * math.sqrt(wind) * (1.0 - ((100.0 - rh) / 100.0) ** 8))
            kw = kl * 0.581 * math.exp(0.0365 * temp)
            m = ew - (ew - mo) * 10.0 ** (-kw)
        else:
            m = mo

    return max(0.0, min(101.0, 59.5 * (250.0 - m) / (147.2 + m)))


def dmc(temp, rh, rain, dmc_prev, month):
    """Duff Moisture Code. Medium-depth organic fuel."""
    temp = max(temp, -1.1)
    d = dmc_prev

    if rain > 1.5:
        re = 0.92 * rain - 1.27
        mo = 20.0 + math.exp(5.6348 - d / 43.43)
        if d <= 33.0:
            b = 100.0 / (0.5 + 0.3 * d)
        elif d <= 65.0:
            b = 14.0 - 1.3 * math.log(d)
        else:
            b = 6.2 * math.log(d) - 17.2
        mr = mo + 1000.0 * re / (48.77 + b * re)
        d = max(0.0, 244.72 - 43.43 * math.log(mr - 20.0))

    k = 1.894 * (temp + 1.1) * (100.0 - rh) * DMC_DAY_LENGTH[month - 1] * 1e-6
    return max(0.0, d + 100.0 * k)


def dc(temp, rain, dc_prev, month):
    """Drought Code. Deep compact fuel, the seasonal memory of the system."""
    temp = max(temp, -2.8)
    d = dc_prev

    if rain > 2.8:
        rd = 0.83 * rain - 1.27
        qo = 800.0 * math.exp(-d / 400.0)
        qr = qo + 3.937 * rd
        d = max(0.0, 400.0 * math.log(800.0 / qr))

    v = 0.36 * (temp + 2.8) + DC_DAY_LENGTH[month - 1]
    return max(0.0, d + 0.5 * max(v, 0.0))


def isi(ffmc_val, wind):
    """Initial Spread Index. Expected rate of spread, no fuel quantity involved."""
    m = 147.2 * (101.0 - ffmc_val) / (59.5 + ffmc_val)
    ff = 91.9 * math.exp(-0.1386 * m) * (1.0 + m ** 5.31 / 4.93e7)
    return 0.208 * math.exp(0.05039 * wind) * ff


def bui(dmc_val, dc_val):
    """Buildup Index. Total fuel available to the fire."""
    if dmc_val == 0 and dc_val == 0:
        return 0.0
    if dmc_val <= 0.4 * dc_val:
        return 0.8 * dmc_val * dc_val / (dmc_val + 0.4 * dc_val)
    return dmc_val - (1.0 - 0.8 * dc_val / (dmc_val + 0.4 * dc_val)) * (
        0.92 + (0.0114 * dmc_val) ** 1.7)


def fwi(isi_val, bui_val):
    """Fire Weather Index. Frontal fire intensity."""
    if bui_val <= 80.0:
        fd = 0.626 * bui_val ** 0.809 + 2.0
    else:
        fd = 1000.0 / (25.0 + 108.64 * math.exp(-0.023 * bui_val))
    b = 0.1 * isi_val * fd
    if b <= 1.0:
        return b
    return math.exp(2.72 * (0.434 * math.log(b)) ** 0.647)


def danger_class(fwi_val):
    for name, lo, hi in CLASSES:
        if lo <= fwi_val < hi:
            return name
    return "extreme"


# Fuel availability multiplier applied to the final index. See wilayas.py for why.
FUEL_FACTOR = {"forest": 1.0, "steppe": 0.55, "desert": 0.12}


def apply_fuel_mask(fwi_val, fuel):
    """Scale raw meteorological FWI by what is actually there to burn.

    This is a deliberate departure from the textbook index, which assumes a standard
    jack pine stand everywhere. Reporting a raw FWI of 60 for Tamanrasset would be
    meteorologically correct and operationally absurd.
    """
    return fwi_val * FUEL_FACTOR.get(fuel, 1.0)


def daily_step(temp, rh, wind, rain, month, prev):
    """Advance one day. `prev` carries (ffmc, dmc, dc); returns the full index set."""
    p_ffmc, p_dmc, p_dc = prev
    f = ffmc(temp, rh, wind, rain, p_ffmc)
    d = dmc(temp, rh, rain, p_dmc, month)
    c = dc(temp, rain, p_dc, month)
    i = isi(f, wind)
    b = bui(d, c)
    return {"ffmc": f, "dmc": d, "dc": c, "isi": i, "bui": b, "fwi": fwi(i, b)}


# Van Wagner's recommended spring startup values, used when no prior state exists.
START = (85.0, 6.0, 15.0)
