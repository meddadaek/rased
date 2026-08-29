"""Open-Meteo client. Free, no API key, no account, no card.

Fetches what the FWI system needs at local solar noon — the convention the
Canadian system is calibrated against — plus the 24h rainfall total.

Why one endpoint and not two: the FWI moisture codes carry memory (the Drought
Code has a ~52 day time lag), so a cold start on today's weather is meaningless.
The forecast endpoint serves `past_days` up to 92, of which roughly the last 72
carry real values for Algeria. Spinning up from mid-June — the start of the
Algerian fire season — is enough for DC to converge, so the ERA5 archive is not
needed and the whole pipeline stays on a single keyless endpoint.
"""
import json
import time
import urllib.parse
import urllib.request

ENDPOINT = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo accepts many coordinates per call. Chunking keeps each response to a
# few MB and stays well inside the free tier's fair-use limits.
CHUNK = 8
PAST_DAYS = 92
FORECAST_DAYS = 7

HOURLY = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "wind_direction_10m"]
DAILY = ["precipitation_sum"]

USER_AGENT = "Rased/0.1 (Algeria wildfire risk; https://github.com/)"


def _get(url, retries=3, backoff=2.0):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - network shape varies too much to enumerate
            last = exc
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError("Open-Meteo request failed after %d attempts: %s" % (retries, last))


def fetch_chunk(points):
    """points: [(lat, lon), ...] -> list of raw Open-Meteo payloads, one per point."""
    q = {
        "latitude": ",".join("%.4f" % p[0] for p in points),
        "longitude": ",".join("%.4f" % p[1] for p in points),
        "hourly": ",".join(HOURLY),
        "daily": ",".join(DAILY),
        "timezone": "auto",
        "past_days": PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
        "wind_speed_unit": "kmh",
    }
    data = _get(ENDPOINT + "?" + urllib.parse.urlencode(q))
    # A single coordinate returns an object; several return a list. Normalise.
    return data if isinstance(data, list) else [data]


def noon_series(payload):
    """Collapse an hourly payload into one record per day at 12:00 local time.

    Returns [{date, temp, rh, wind, wind_dir, rain}, ...] with incomplete days
    dropped. Leading days of the `past_days` window come back null (the model
    archive does not reach that far), so callers get a shorter series than they
    asked for — that is expected, not an error.
    """
    h = payload["hourly"]
    times = h["time"]
    temp, rh = h["temperature_2m"], h["relative_humidity_2m"]
    wind, wdir = h["wind_speed_10m"], h["wind_direction_10m"]

    rain_by_day = dict(zip(payload["daily"]["time"], payload["daily"]["precipitation_sum"]))

    out = []
    for i, ts in enumerate(times):
        if not ts.endswith("T12:00"):
            continue
        day = ts[:10]
        t, r, w = temp[i], rh[i], wind[i]
        if t is None or r is None or w is None:
            continue
        rain = rain_by_day.get(day)
        out.append({
            "date": day,
            "temp": float(t),
            "rh": float(r),
            "wind": float(w),
            "wind_dir": float(wdir[i]) if wdir[i] is not None else 0.0,
            "rain": float(rain) if rain is not None else 0.0,
        })
    return out


def fetch_all(locations, progress=None):
    """locations: [{code, lat, lon}, ...] -> {code: [daily noon records]}."""
    result = {}
    for start in range(0, len(locations), CHUNK):
        batch = locations[start:start + CHUNK]
        payloads = fetch_chunk([(b["lat"], b["lon"]) for b in batch])
        if len(payloads) != len(batch):
            raise RuntimeError("expected %d payloads, got %d" % (len(batch), len(payloads)))
        for loc, payload in zip(batch, payloads):
            result[loc["code"]] = noon_series(payload)
        if progress:
            progress(min(start + CHUNK, len(locations)), len(locations))
        time.sleep(0.6)  # be a good citizen on a free community endpoint
    return result
