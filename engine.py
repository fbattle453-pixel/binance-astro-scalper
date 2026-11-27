import requests, pandas as pd, numpy as np, ephem, pytz, hashlib
from datetime import datetime, timedelta

BASE_URL = "https://binance.com"
KNOWN_RULERS = {
    "SOLUSDT": "Sun", "XRPUSDT": "Jupiter", "SUIUSDT": "Moon", "NEARUSDT": "Mercury",
    "LINKUSDT": "Saturn", "FETUSDT": "Uranus", "AVAXUSDT": "Mars", "DOTUSDT": "Jupiter",
    "ADAUSDT": "Venus", "UNIUSDT": "Mercury", "ATOMUSDT": "Uranus", "TRXUSDT": "Mars",
    "OMUSDT": "Saturn", "SSVUSDT": "Saturn", "HYPEUSDT": "Uranus", "APTUSDT": "Mercury",
    "ARBUSDT": "Uranus", "OPUSDT": "Mercury", "INJUSDT": "Mars", "TIAUSDT": "Uranus"
}
PLANETS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
HORA_ORDER = ["Sun", "Venus", "Mercury", "Moon", "Saturn", "Jupiter", "Mars"]
NAKSHATRAS = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta",
    "Shatabhisha", "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"
]

def get_ruler(symbol):
    if symbol in KNOWN_RULERS:
        return KNOWN_RULERS[symbol]
    return PLANETS[int(hashlib.md5(symbol.encode()).hexdigest(), 16) % len(PLANETS)]

def get_astro_context(mode="Western"):
    now_utc = datetime.now(pytz.UTC)
    obs = ephem.Observer()
    obs.date = now_utc.strftime("%Y/%m/%d %H:%M:%S")
    bodies = {
        "Sun": ephem.Sun(obs), "Moon": ephem.Moon(obs), "Mars": ephem.Mars(obs),
        "Mercury": ephem.Mercury(obs), "Jupiter": ephem.Jupiter(obs),
        "Venus": ephem.Venus(obs), "Saturn": ephem.Saturn(obs)
    }
    year_frac = now_utc.year + (now_utc.timetuple().tm_yday / 365.25)
    ayanamsa = (23.853 + (year_frac - 2000.0) * 0.0139688) if mode == "Vedic" else 0.0
    longs = {k: (np.degrees(ephem.Ecliptic(v).lon) - ayanamsa) % 360.0 for k, v in bodies.items()}
    weekday_map = {6: 0, 0: 3, 1: 6, 2: 2, 3: 4, 4: 1, 5: 5}
    hora = HORA_ORDER[(weekday_map[now_utc.weekday()] + now_utc.hour) % 7]
    moon_deg = longs["Moon"]
    aspects = []
    for p, deg in longs.items():
        if p == "Moon": continue
        diff = min(abs(moon_deg - deg) % 360, 360 - (abs(moon_deg - deg) % 360))
        for ang, lbl, mod in [(0, "Conj", 12), (60, "Sextile", 8), (90, "Square", -10), (120, "Trine", 12), (180, "Opp", -10)]:
            if abs(diff - ang) <= 0.5:
                aspects.append((p, lbl, mod))
    nak = NAKSHATRAS[int(moon_deg // (360.0 / 27.0))]
    return {"hora": hora, "aspects": aspects, "nakshatra": nak, "mins": max(15, min(45, 60 - now_utc.minute))}

def score_astro(symbol, ctx, mode):
    ruler = get_ruler(symbol)
    score = 55.0
    notes = [f"Ruler:{ruler} | Hora:{ctx['hora']}"]
    if ctx["hora"] == ruler:
        score += 25.0
        notes.append(f"{ruler} Hora(+25)")
    elif ctx["hora"] in ["Jupiter", "Venus", "Sun"]:
        score += 10.0
    for p, lbl, mod in ctx["aspects"]:
        score += mod * (1.5 if p == ruler else 0.5)
        if p == ruler: notes.append(f"Moon {lbl} {ruler}")
    if mode == "Vedic":
        notes.append(f"Nak:{ctx['nakshatra']}")
        if ctx["nakshatra"] in ["Rohini", "Pushya", "Hasta", "Shravana", "Revati", "Ashwini"]:
            score += 10.0
    return float(np.clip(score, 0, 100)), " | ".join(notes)

def fetch_candidates():
    try:
        info = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=6).json()
        valid = {s["symbol"] for s in info.get("symbols", []) if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL"}
        tickers = requests.get(f"{BASE_URL}/fapi/v1/ticker/24hr", timeout=6).json()
        out = []
        for t in tickers:
            sym = t.get("symbol")
            if sym not in valid: continue
            p, v, pct = float(t.get("lastPrice", 0)), float(t.get("quoteVolume", 0)), abs(float(t.get("priceChangePercent", 0)))
            if 0.10 <= p <= 100.00 and v >= 25_000_000:
                out.append({"symbol": sym, "price": p, "vol": v, "rank": pct * np.log10(v)})
        return sorted(out, key=lambda x: x["rank"], reverse=True)[:25]
    except Exception:
        return []

def run_market_scan(mode="Western"):
    cands = fetch_candidates()
    ctx = get_astro_context(mode)
    rows = []
    for c in cands:
        sym = c["symbol"]
        try:
            k5 = requests.get(f"{BASE_URL}/fapi/v1/klines", params={"symbol": sym, "interval": "5m", "limit": 30}, timeout=4).json()
            k1 = requests.get(f"{BASE_URL}/fapi/v1/klines", params={"symbol": sym, "interval": "1m", "limit": 20}, timeout=4).json()
            depth = requests.get(f"{BASE_URL}/fapi/v1/depth", params={"symbol": sym, "limit": 20}, timeout=4).json()
            prem = requests.get(f"{BASE_URL}/fapi/v1/premiumIndex", params={"symbol": sym}, timeout=4).json()
            df5 = pd.DataFrame(k5, columns=["t","o","h","l","c","v","ct","qv","n","tb","tq","ig"]).astype(float)
            df1 = pd.DataFrame(k1, columns=["t","o","h","l","c","v","ct","qv","n","tb","tq","ig"]).astype(float)
            price = df1["c"].iloc[-1]
            e9_5, e21_5 = df5["c"].ewm(span=9).mean().iloc[-1], df5["c"].ewm(span=21).mean().iloc[-1]
            e9_1, e21_1 = df1["c"].ewm(span=9).mean().iloc[-1], df1["c"].ewm(span=21).mean().iloc[-1]
            vwap = (df5["c"] * df5["v"]).sum() / max(df5["v"].sum(), 1e-9)
            d = df5["c"].diff()
            rsi = 100 - (100 / (1 + d.clip(lower=0).rolling(14).mean().iloc[-1] / max((-d.clip(upper=0)).rolling(14).mean().iloc[-1], 1e-9)))
            tr = pd.concat([df5["h"]-df5["l"], (df5["h"]-df5["c"].shift()).abs(), (df5["l"]-df5["c"].shift()).abs()], axis=1).max(axis=1)
            atr_pct = max(0.35, min(0.75, (tr.rolling(14).mean().iloc[-1] / price) * 100.0))
            ob = sum(float(b) for b in depth.get("bids", [])) / max(sum(float(a) for a in depth.get("asks", [])), 1e-9)
            fund = float(prem.get("lastFundingRate", 0)) * 100.0
            lp, sp = 40.0, 40.0
            if e9_5 > e21_5 and e9_1 > e21_1: lp += 22.0
            elif e9_5 < e21_5 and e9_1 < e21_1: sp += 22.0
            lp += 12.0 if price > vwap else 0.0
            sp += 12.0 if price <= vwap else 0.0
            if ob >= 1.45: lp += 18.0
            elif ob <= 0.68: sp += 18.0
            if 52 <= rsi <= 70: lp += 10.0
            elif 30 <= rsi <= 48: sp += 10.0
            if fund < -0.01: lp += 8.0
            elif fund > 0.03: sp += 8.0
            direction = "LONG" if lp >= sp else "SHORT"
            flow = float(np.clip(max(lp, sp), 0, 100))
            astro, anote = score_astro(sym, ctx, mode)
            tot = round(flow * 0.6 + astro * 0.4, 1)
            aligned = (direction == "LONG" and ob >= 1.15 and e9_5 > e21_5) or (direction == "SHORT" and ob <= 0.87 and e9_5 < e21_5)
            rows.append({"Symbol": sym, "Price": price, "24h Vol ($M)": round(c["vol"]/1e6, 1), "Direction": direction, "5m RSI": round(rsi, 1), "OB Ratio": round(ob, 2), "Funding %": round(fund, 4), "Flow Score": round(flow, 1), "Astro Score": round(astro, 1), "Total Score": tot, "Aligned": aligned, "ATR %": atr_pct, "Astro Note": anote})
        except Exception:
            continue
    if not rows:
        return pd.DataFrame(), None, len(cands)
    df = pd.DataFrame(rows).sort_values("Total Score", ascending=False).reset_index(drop=True)
    qual = df[(df["Total Score"] >= 82.0) & (df["Aligned"] == True)]
    sig = None
    if not qual.empty:
        b = qual.iloc
        sc = b["Total Score"]
        lev = 50 if sc > 92 else (35 if sc >= 87 else 20)
        ent = b["Price"]
        sl_p = b["ATR %"] / 100.0
        sl = ent * (1 - sl_p) if b["Direction"] == "LONG" else ent * (1 + sl_p)
        tp1 = ent * (1 + sl_p * 1.8) if b["Direction"] == "LONG" else ent * (1 - sl_p * 1.8)
        tp2 = ent * (1 + sl_p * 3.2) if b["Direction"] == "LONG" else ent * (1 - sl_p * 3.2)
        c_utc = datetime.now(pytz.UTC) + timedelta(minutes=ctx["mins"])
        c_pkt = c_utc.astimezone(pytz.timezone("Asia/Karachi"))
        sig = {"symbol": b["Symbol"], "direction": b["Direction"], "score": sc, "leverage": lev, "entry": ent, "tp1": tp1, "tp2": tp2, "sl": sl, "sl_pct": round(sl_p*100, 2), "close_utc": c_utc.strftime("%H:%M:%S UTC"), "close_pkt": c_pkt.strftime("%I:%M:%S %p PKT"), "hold_mins": ctx["mins"], "astro_note": b["Astro Note"], "ob_ratio": b["OB Ratio"], "rsi": b["5m RSI"]}
    return df, sig, len(cands)
