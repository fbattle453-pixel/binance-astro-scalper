import requests
import pandas as pd
import numpy as np
import ephem
import pytz
import hashlib
from datetime import datetime, timedelta

SLASH = chr(47)
COLON = chr(58)
DOT = chr(46)
PROTO = "https" + COLON + SLASH + SLASH
HOST = DOT.join(["futures", "kraken", "com"])
BASE = PROTO + HOST + "/derivatives/api/v3"
CHART_BASE = PROTO + HOST + "/api/charts/v1/trade"
HEADERS = {"User-Agent": "Mozilla/5.0"}

NON_CRYPTO_EXCLUDE = {
    "XAG", "XAU", "XPT", "XPD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD",
    "SOXL", "SOXS", "TSLA", "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META",
    "AMD", "COIN", "MSTR", "PLTR", "SPY", "QQQ", "IWM", "TLT", "GLD", "SLV",
    "HOOD", "GME", "AMC", "NFLX", "INTC", "SMCI", "ARM", "MARA", "RIOT"
}

KNOWN_RULERS = {
    "SOL": "Sun", "XRP": "Jupiter", "SUI": "Moon", "NEAR": "Mercury",
    "LINK": "Saturn", "FET": "Uranus", "AVAX": "Mars", "DOT": "Jupiter",
    "ADA": "Venus", "UNI": "Mercury", "ATOM": "Uranus", "TRX": "Mars",
    "OM": "Saturn", "SSV": "Saturn", "HYPE": "Uranus", "APT": "Mercury",
    "ARB": "Uranus", "OP": "Mercury", "INJ": "Mars", "TIA": "Uranus",
    "LTC": "Moon", "FIL": "Saturn", "RENDER": "Uranus", "SEI": "Moon",
    "TON": "Mercury", "ENA": "Venus", "WLD": "Uranus", "ICP": "Saturn",
    "ETC": "Saturn", "ALGO": "Mercury", "VET": "Venus", "RNDR": "Uranus"
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


def get_ruler(base_coin):
    if base_coin in KNOWN_RULERS:
        return KNOWN_RULERS[base_coin]
    idx = int(hashlib.md5(base_coin.encode()).hexdigest(), 16) % len(PLANETS)
    return PLANETS[idx]


def get_astro_context(mode="Western"):
    now_utc = datetime.now(pytz.UTC)
    obs = ephem.Observer()
    obs.date = now_utc.strftime("%Y/%m/%d %H:%M:%S")
    bodies = {
        "Sun": ephem.Sun(obs),
        "Moon": ephem.Moon(obs),
        "Mars": ephem.Mars(obs),
        "Mercury": ephem.Mercury(obs),
        "Jupiter": ephem.Jupiter(obs),
        "Venus": ephem.Venus(obs),
        "Saturn": ephem.Saturn(obs),
    }
    year_frac = now_utc.year + (now_utc.timetuple().tm_yday / 365.25)
    ayanamsa = (23.853 + (year_frac - 2000.0) * 0.0139688) if mode == "Vedic" else 0.0
    longs = {k: (np.degrees(ephem.Ecliptic(v).lon) - ayanamsa) % 360.0 for k, v in bodies.items()}

    weekday_map = {6: 0, 0: 3, 1: 6, 2: 2, 3: 4, 4: 1, 5: 5}
    hora = HORA_ORDER[(weekday_map[now_utc.weekday()] + now_utc.hour) % 7]
    moon_deg = longs["Moon"]
    aspects = []
    for p, deg in longs.items():
        if p == "Moon":
            continue
        diff = min(abs(moon_deg - deg) % 360, 360 - (abs(moon_deg - deg) % 360))
        for ang, lbl, mod in [(0, "Conj", 12), (60, "Sextile", 8), (90, "Square", -10), (120, "Trine", 12), (180, "Opp", -10)]:
            if abs(diff - ang) <= 1.0:
                aspects.append((p, lbl, mod))
    nak = NAKSHATRAS[int(moon_deg // (360.0 / 27.0))]
    return {
        "hora": hora,
        "aspects": aspects,
        "nakshatra": nak,
        "mins": max(15, min(45, 60 - now_utc.minute)),
    }


def score_astro(base_coin, ctx, mode):
    ruler = get_ruler(base_coin)
    score = 55.0
    notes = [f"Ruler:{ruler} | Hora:{ctx['hora']}"]
    if ctx["hora"] == ruler:
        score += 25.0
        notes.append(f"{ruler} Hora(+25)")
    elif ctx["hora"] in ["Jupiter", "Venus", "Sun"]:
        score += 10.0
    for p, lbl, mod in ctx["aspects"]:
        score += mod * (1.5 if p == ruler else 0.5)
        if p == ruler:
            notes.append(f"Moon {lbl} {ruler}")
    if mode == "Vedic":
        notes.append(f"Nak:{ctx['nakshatra']}")
        if ctx["nakshatra"] in ["Rohini", "Pushya", "Hasta", "Shravana", "Revati", "Ashwini"]:
            score += 10.0
    return float(np.clip(score, 0, 100)), " | ".join(notes)


def fetch_candidates():
    try:
        r = requests.get(BASE + "/tickers", headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return [], f"Kraken HTTP {r.status_code}"
        tickers = r.json().get("tickers", [])
        out = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.startswith("PF_") or not sym.endswith("USD"):
                continue
            base = sym.replace("PF_", "").replace("USD", "")
            if base == "XBT":
                base = "BTC"
            if base in NON_CRYPTO_EXCLUDE:
                continue

            p = float(t.get("last") or 0)
            vol_usd = float(t.get("volumeQuote") or 0)
            open24 = float(t.get("open24h") or 0)
            pct = abs((p - open24) / open24) * 100.0 if open24 > 0 else 1.0
            fund = float(t.get("fundingRate") or 0) * 100.0

            if 0.10 <= p <= 100.00 and vol_usd >= 100_000:
                out.append({
                    "inst": sym,
                    "base": base,
                    "symbol": f"{base}USDT",
                    "price": p,
                    "vol": vol_usd,
                    "funding": fund,
                    "rank": pct * np.log10(max(vol_usd, 10)),
                })
        return sorted(out, key=lambda x: x["rank"], reverse=True)[:25], f"Crypto Only ({len(out)} matched)"
    except Exception as e:
        return [], f"Err: {e}"


def run_market_scan(mode="Western"):
    cands, status_msg = fetch_candidates()
    ctx = get_astro_context(mode)
    rows = []
    for c in cands:
        inst = c["inst"]
        try:
            k5 = requests.get(f"{CHART_BASE}/{inst}/5m", headers=HEADERS, timeout=5).json().get("candles", [])[-30:]
            ob_data = requests.get(BASE + "/orderbook", params={"symbol": inst}, headers=HEADERS, timeout=5).json().get("orderBook", {})
            if len(k5) < 15:
                continue

            df5 = pd.DataFrame(k5).astype(float)
            price = float(df5["close"].iat[-1])
            if price <= 0:
                continue
            e9 = float(df5["close"].ewm(span=9).mean().iat[-1])
            e21 = float(df5["close"].ewm(span=21).mean().iat[-1])
            vwap = float((df5["close"] * df5["volume"]).sum() / max(df5["volume"].sum(), 1e-9))

            d = df5["close"].diff()
            gain = float(d.clip(lower=0).rolling(14).mean().iat[-1])
            loss = float((-d.clip(upper=0)).rolling(14).mean().iat[-1])
            rsi = 100.0 - (100.0 / (1.0 + gain / max(loss, 1e-9)))

            tr = pd.concat([
                df5["high"] - df5["low"],
                (df5["high"] - df5["close"].shift()).abs(),
                (df5["low"] - df5["close"].shift()).abs(),
            ], axis=1).max(axis=1)
            atr_val = float(tr.rolling(14).mean().iat[-1])
            atr_pct = max(0.35, min(0.75, (atr_val / price) * 100.0))

            bids = ob_data.get("bids", [])[:20]
            asks = ob_data.get("asks", [])[:20]
            bid_vol = sum(float(qty) for _, qty in bids)
            ask_vol = sum(float(qty) for _, qty in asks)
            ob = bid_vol / max(ask_vol, 1e-9)
            fund = c["funding"]

            lp, sp = 45.0, 45.0
            if e9 > e21:
                lp += 20.0
            else:
                sp += 20.0
            if price > vwap:
                lp += 12.0
            else:
                sp += 12.0
            if ob >= 1.25:
                lp += 15.0
            elif ob <= 0.80:
                sp += 15.0
            if 50 <= rsi <= 72:
                lp += 8.0
            elif 28 <= rsi <= 50:
                sp += 8.0

            direction = "LONG" if lp >= sp else "SHORT"
            flow = float(np.clip(max(lp, sp), 0, 100))
            astro, anote = score_astro(c["base"], ctx, mode)
            tot = round(flow * 0.6 + astro * 0.4, 1)

            rows.append({
                "Symbol": c["symbol"],
                "Price": price,
                "24h Vol ($M)": round(c["vol"] / 1e6, 2),
                "Direction": direction,
                "5m RSI": round(rsi, 1),
                "OB Ratio": round(ob, 2),
                "Funding %": round(fund, 4),
                "Flow Score": round(flow, 1),
                "Astro Score": round(astro, 1),
                "Total Score": tot,
                "ATR %": atr_pct,
                "Astro Note": anote,
            })
        except Exception:
            continue

    if not rows:
        return pd.DataFrame(), None, len(cands), status_msg

    df = pd.DataFrame(rows).sort_values("Total Score", ascending=False).reset_index(drop=True)

    sig = None
    for _, best in df.head(1).iterrows():
        sc = float(best["Total Score"])
        if sc >= 60.0:
            lev = 50 if sc >= 85 else (35 if sc >= 75 else 20)
            ent = float(best["Price"])
            sl_p = float(best["ATR %"]) / 100.0
            sl = ent * (1 - sl_p) if best["Direction"] == "LONG" else ent * (1 + sl_p)
            tp1 = ent * (1 + sl_p * 1.8) if best["Direction"] == "LONG" else ent * (1 - sl_p * 1.8)
            tp2 = ent * (1 + sl_p * 3.2) if best["Direction"] == "LONG" else ent * (1 - sl_p * 3.2)
            c_utc = datetime.now(pytz.UTC) + timedelta(minutes=ctx["mins"])
            c_pkt = c_utc.astimezone(pytz.timezone("Asia/Karachi"))
            sig = {
                "symbol": best["Symbol"],
                "direction": best["Direction"],
                "score": sc,
                "leverage": lev,
                "entry": ent,
                "tp1": tp1,
                "tp2": tp2,
                "sl": sl,
                "sl_pct": round(sl_p * 100, 2),
                "close_utc": c_utc.strftime("%H:%M:%S UTC"),
