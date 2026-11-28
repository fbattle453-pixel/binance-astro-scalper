import numpy as np, ephem, pytz, hashlib
from datetime import datetime

EXCLUDE = {
    "XAG", "XAU", "XPT", "XPD", "EUR", "GBP", "JPY", "AUD", "CAD",
    "CHF", "NZD", "SOXL", "SOXS", "TSLA", "NVDA", "AAPL", "MSFT",
    "AMZN", "GOOGL", "META", "AMD", "COIN", "MSTR", "PLTR", "SPY",
    "QQQ", "IWM", "TLT", "GLD", "SLV", "HOOD", "GME", "AMC", "NFLX"
}

RULERS = {
    "SOL": "Sun", "XRP": "Jupiter", "SUI": "Moon", "NEAR": "Mercury",
    "LINK": "Saturn", "FET": "Uranus", "AVAX": "Mars", "DOT": "Jupiter",
    "ADA": "Venus", "UNI": "Mercury", "ATOM": "Uranus", "TRX": "Mars",
    "OM": "Saturn", "SSV": "Saturn", "HYPE": "Uranus", "APT": "Mercury",
    "ARB": "Uranus", "OP": "Mercury", "INJ": "Mars", "TIA": "Uranus",
    "LTC": "Moon", "FIL": "Saturn", "RENDER": "Uranus", "SEI": "Moon",
    "DOGE": "Moon", "PEPE": "Moon", "WIF": "Mars", "BONK": "Mars"
}

PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
HORAS = ["Sun", "Venus", "Mercury", "Moon", "Saturn", "Jupiter", "Mars"]
NAKS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni",
    "Uttara Phalguni", "Hasta", "Chitra", "Swati", "Vishakha",
    "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha", "Uttara Ashadha",
    "Shravana", "Dhanishta", "Shatabhisha", "Purva Bhadrapada",
    "Uttara Bhadrapada", "Revati"
]

def get_astro(mode):
    now = datetime.now(pytz.UTC)
    obs = ephem.Observer()
    obs.date = now.strftime("%Y/%m/%d %H:%M:%S")
    bodies = {
        "Sun": ephem.Sun(obs), "Moon": ephem.Moon(obs),
        "Mars": ephem.Mars(obs), "Mercury": ephem.Mercury(obs),
        "Jupiter": ephem.Jupiter(obs), "Venus": ephem.Venus(obs),
        "Saturn": ephem.Saturn(obs)
    }
    yr = now.year + (now.timetuple().tm_yday / 365.25)
    aya = (23.853 + (yr - 2000.0) * 0.0139688) if mode == "Vedic" else 0.0
    longs = {k: (np.degrees(ephem.Ecliptic(v).lon) - aya) % 360.0 for k, v in bodies.items()}
    wmap = {6: 0, 0: 3, 1: 6, 2: 2, 3: 4, 4: 1, 5: 5}
    hora = HORAS[(wmap[now.weekday()] + now.hour) % 7]
    mdeg = longs["Moon"]
    aspects = []
    for p, deg in longs.items():
        if p == "Moon":
            continue
        diff = min(abs(mdeg - deg) % 360, 360 - (abs(mdeg - deg) % 360))
        for ang, lbl, mod in [(0, "Conj", 14), (60, "Sextile", 9), (90, "Square", -12), (120, "Trine", 14), (180, "Opp", -12)]:
            if abs(diff - ang) <= 0.6:
                aspects.append((p, lbl, mod))
    return {"hora": hora, "aspects": aspects, "nak": NAKS[int(mdeg // (360.0 / 27.0))], "voc": (mdeg % 30.0) >= 27.5}

def score_astro(coin, ctx, mode):
    ruler = RULERS.get(coin, PLANETS[int(hashlib.md5(coin.encode()).hexdigest(), 16) % 7])
    sc = 50.0 + (22.0 if ctx["hora"] == ruler else 8.0)
    notes = [f"Ruler:{ruler} | Hora:{ctx['hora']}"]
    if ctx["voc"]:
        sc -= 18.0
        notes.append("VoC Moon(-18)")
    for p, lbl, mod in ctx["aspects"]:
        sc += mod * (1.5 if p == ruler else 0.6)
        if p == ruler:
            notes.append(f"Moon {lbl} {ruler}")
    if mode == "Vedic":
        notes.append(f"Nak:{ctx['nak']}")
        if ctx["nak"] in ["Rohini", "Pushya", "Hasta", "Shravana", "Revati"]:
            sc += 10.0
    return float(np.clip(sc, 0, 100)), " | ".join(notes)
