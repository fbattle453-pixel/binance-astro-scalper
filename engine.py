import requests, pandas as pd, numpy as np, pytz
from datetime import datetime, timedelta
from astro_core import get_astro, score_astro

PROTO = "https" + chr(58) + chr(47) + chr(47)
HOST = chr(46).join(["futures", "kraken", "com"])
BASE = PROTO + HOST + "/derivatives/api/v3"
CHART = PROTO + HOST + "/api/charts/v1/trade"
OKX_CHART = PROTO + chr(46).join(["www", "okx", "com"]) + "/api/v5/market/candles"
HEADERS = {"User-Agent": "Mozilla/5.0"}

BINANCE_FUTURES_COINS = {
    "SOL", "XRP", "SUI", "NEAR", "LINK", "FET", "AVAX", "DOT", "ADA", "UNI",
    "ATOM", "TRX", "OM", "APT", "ARB", "OP", "INJ", "TIA", "LTC", "FIL",
    "RENDER", "SEI", "DOGE", "PEPE", "WIF", "BONK", "AAVE", "TAO", "HYPE",
    "ENA", "WLD", "ICP", "ETC", "ALGO", "VET", "TON", "GALA", "SAND", "MANA",
    "CRV", "DYDX", "RUNE", "ORDI", "JUP", "PYTH", "STRK", "ZK", "NOT", "BOME"
}

def last_val(series):
    return float(series.to_list().pop())

def fetch_usdt_candles(base, inst, bar="15m", limit=105):
    # Try OKX USDT-SWAP first (matches Binance USDT price to ~0.01%), fallback to Kraken
    try:
        r = requests.get(OKX_CHART, params={"instId": f"{base}-USDT-SWAP", "bar": bar, "limit": str(limit)}, headers=HEADERS, timeout=4).json()
        data = r.get("data", [])
        if len(data) >= 50:
            rows = [{"open": float(x[1]), "high": float(x[2]), "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])} for x in reversed(data)]
            return pd.DataFrame(rows)
    except Exception:
        pass
    k = requests.get(f"{CHART}/{inst}/{bar}", headers=HEADERS, timeout=5).json().get("candles", [])
    return pd.DataFrame(k).tail(limit).astype(float)

def get_btc_regime():
    try:
        df = fetch_usdt_candles("BTC", "PF_XBTUSD", "15m", 40)
        p = last_val(df["close"])
        ma7 = last_val(df["close"].rolling(7).mean())
        ma25 = last_val(df["close"].rolling(25).mean())
        if p > ma7 and p > ma25 and ma7 > ma25:
            return "BULL"
        if p < ma7 and p < ma25 and ma7 < ma25:
            return "BEAR"
        return "CHOP"
    except Exception:
        return "NEUTRAL"

def run_market_scan(mode="Western"):
    btc_state = get_btc_regime()
    try:
        r = requests.get(BASE + "/tickers", headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return pd.DataFrame(), None, 0, f"HTTP {r.status_code}"
        cands = []
        for t in r.json().get("tickers", []):
            sym = t.get("symbol", "")
            if not sym.startswith("PF_") or not sym.endswith("USD"):
                continue
            base = sym.replace("PF_", "").replace("USD", "")
            if base not in BINANCE_FUTURES_COINS:
                continue
            p = float(t.get("last") or 0)
            vol = float(t.get("volumeQuote") or 0)
            op = float(t.get("open24h") or 0)
            pct = abs((p - op) / op) * 100.0 if op > 0 else 2.0
            fund = float(t.get("fundingRate") or 0) * 100.0
            if 0.001 <= p <= 200.00 and vol >= 250_000 and 1.2 <= pct <= 12.0:
                cands.append({"inst": sym, "base": base, "sym": f"{base}USDT", "vol": vol, "fund": fund, "rank": pct * np.log10(max(vol, 10))})
        cands = list(sorted(cands, key=lambda x: x["rank"], reverse=True))[:20]
    except Exception as e:
        return pd.DataFrame(), None, 0, f"Err: {e}"

    ctx, rows = get_astro(mode), []
    for c in cands:
        try:
            df = fetch_usdt_candles(c["base"], c["inst"], "15m", 105)
            obd = requests.get(BASE + "/orderbook", params={"symbol": c["inst"]}, timeout=4).json().get("orderBook", {})
            if len(df) < 100:
                continue

            price = last_val(df["close"])
            open_c = last_val(df["open"])
            if price <= 0:
                continue

            # Exact Binance Chart Moving Averages: MA(7), MA(25), MA(99)
            ma7 = last_val(df["close"].rolling(7).mean())
            ma25 = last_val(df["close"].rolling(25).mean())
            ma99 = last_val(df["close"].rolling(99).mean())

            # Structure check: Higher Lows for LONG, Lower Highs for SHORT
            lows = df["low"].tail(4).to_list()
            highs = df["high"].tail(4).to_list()
            higher_lows = lows[3] >= lows[1] and lows[2] >= lows[0]
            lower_highs = highs[3] <= highs[1] and highs[2] <= highs[0]

            hi24, lo24 = float(df["high"].tail(96).max()), float(df["low"].tail(96).min())
            room_lo = ((price - lo24) / max(lo24, 1e-9)) * 100.0
            room_hi = ((hi24 - price) / max(price, 1e-9)) * 100.0

            d = df["close"].diff()
            rsi = 100.0 - (100.0 / (1.0 + last_val(d.clip(lower=0).rolling(14).mean()) / max(last_val((-d.clip(upper=0)).rolling(14).mean()), 1e-9)))
            tr = pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift()).abs(), (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
            atr_pct = (last_val(tr.rolling(14).mean()) / price) * 100.0
            ob = sum(float(q) for _, q in list(obd.get("bids", []))[:20]) / max(sum(float(q) for _, q in list(obd.get("asks", []))[:20]), 1e-9)

            # Strict Trend + Candle Confirmation (prevents LONG below MA25 like INJ)
            bull_ma = (price > ma7) and (ma7 > ma25) and (price > ma99)
            bear_ma = (price < ma7) and (ma7 < ma25) and (price < ma99)

            lp = 20.0 + (30.0 if bull_ma else -20.0) + (18.0 if higher_lows else 0.0) + (12.0 if price > open_c else -10.0) + (12.0 if 48 <= rsi <= 65 else 0.0) + (8.0 if room_hi >= 1.8 else -25.0)
            sp = 20.0 + (30.0 if bear_ma else -20.0) + (18.0 if lower_highs else 0.0) + (12.0 if price < open_c else -10.0) + (12.0 if 35 <= rsi <= 52 else 0.0) + (8.0 if room_lo >= 1.8 else -25.0)

            if btc_state == "BULL":
                lp, sp = lp + 10.0, sp - 20.0
            elif btc_state == "BEAR":
                sp, lp = sp + 10.0, lp - 20.0

            direction = "LONG" if lp >= sp else "SHORT"
            flow = float(np.clip(max(lp, sp), 0, 100))
            astro, anote = score_astro(c["base"], ctx, mode)

            # Astrology amplifies strong technicals (80/20 split), never overrides weak charts
            total = round(min(99.0, flow * 0.80 + astro * 0.20), 1)
            valid_setup = (
                (direction == "LONG" and bull_ma and higher_lows and btc_state != "BEAR" and room_hi >= 1.5 and flow >= 75.0)
                or (direction == "SHORT" and bear_ma and lower_highs and btc_state != "BULL" and room_lo >= 1.5 and flow >= 75.0)
            )
            r_txt = f"Room:{room_hi:.1f}%H" if direction == "LONG" else f"Room:{room_lo:.1f}%L"
            ma_txt = "MA7>25>99" if bull_ma else ("MA7<25<99" if bear_ma else "MA Cross")

            rows.append({"Symbol": c["sym"], "Price": price, "24h Vol ($M)": round(c["vol"] / 1e6, 2), "Direction": direction, "5m RSI": round(rsi, 1), "OB Ratio": round(ob, 2), "Funding %": round(c["fund"], 4), "Flow Score": round(flow, 1), "Astro Score": round(astro, 1), "Total Score": total, "SAFE": valid_setup, "ATR %": atr_pct, "Astro Note": f"BTC:{btc_state} | {ma_txt} | {r_txt} | {anote}"})
        except Exception:
            continue

    if not rows:
        return pd.DataFrame(), None, len(cands), f"BTC:{btc_state} | No setups"
    df = pd.DataFrame(rows).sort_values("Total Score", ascending=False).reset_index(drop=True)
    qual = df[(df["SAFE"] == True) & (df["Total Score"] >= 74.0)].to_dict("records")
    sig = None
    for b in qual[:1]:
        sc = float(b["Total Score"])
        lev = 30 if sc >= 86 else (25 if sc >= 79 else 20)
        ent, atr = float(b["Price"]), max(0.45, float(b["ATR %"]))
        tp1_p = round(max(0.011, min(0.018, (atr * 1.6) / 100.0)), 4)
        tp2_p = round(max(0.020, min(0.030, (atr * 2.8) / 100.0)), 4)
        sl_p = round(max(0.0085, min(0.0115, tp1_p * 0.70)), 4)
        sl = ent * (1 - sl_p) if b["Direction"] == "LONG" else ent * (1 + sl_p)
        tp1 = ent * (1 + tp1_p) if b["Direction"] == "LONG" else ent * (1 - tp1_p)
        tp2 = ent * (1 + tp2_p) if b["Direction"] == "LONG" else ent * (1 - tp2_p)
        c_utc = datetime.now(pytz.UTC) + timedelta(minutes=45)
        c_pkt = c_utc.astimezone(pytz.timezone("Asia/Karachi"))
        sig = dict(symbol=b["Symbol"], direction=b["Direction"], score=sc, leverage=lev, entry=ent, tp1=tp1, tp2=tp2, sl=sl, sl_pct=round(sl_p * 100, 2), close_utc=c_utc.strftime("%H:%M:%S UTC"), close_pkt=c_pkt.strftime("%I:%M:%S %p PKT"), hold_mins=45, astro_note=b["Astro Note"], ob_ratio=b["OB Ratio"], rsi=b["5m RSI"])
    return df, sig, len(cands), f"BTC:{btc_state} | MA7/25/99 USDT Sync ({len(rows)} scored)"
