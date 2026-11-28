import requests, pandas as pd, numpy as np, pytz
from datetime import datetime, timedelta
from astro_core import EXCLUDE, get_astro, score_astro

PROTO = "https" + chr(58) + chr(47) + chr(47)
BASE = PROTO + chr(46).join(["futures", "kraken", "com"]) + "/derivatives/api/v3"
CC_BASE = PROTO + chr(46).join(["min-api", "cryptocompare", "com"])
HEADERS = {"User-Agent": "Mozilla/5.0"}

def last_val(series):
    return float(series.to_list().pop())

def get_btc_regime():
    try:
        url = f"{CC_BASE}/data/v2/histominute"
        p = {"fsym": "BTC", "tsym": "USDT", "limit": 30, "aggregate": 15}
        k15 = requests.get(url, params=p, headers=HEADERS, timeout=5).json()
        df = pd.DataFrame(k15["Data"]["Data"]).astype(float)
        price = last_val(df["close"])
        e9 = last_val(df["close"].ewm(span=9).mean())
        e21 = last_val(df["close"].ewm(span=21).mean())
        if price > e21 and e9 > e21:
            return "BULL"
        if price < e21 and e9 < e21:
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
            if base in EXCLUDE or base in ("BTC", "XBT"):
                continue
            p = float(t.get("last") or 0)
            vol = float(t.get("volumeQuote") or 0)
            op = float(t.get("open24h") or 0)
            pct = abs((p - op) / op) * 100.0 if op > 0 else 2.0
            fund = float(t.get("fundingRate") or 0) * 100.0
            if 0.001 <= p <= 200.00 and vol >= 1_000_000 and 1.0 <= pct <= 12.0:
                cands.append({"inst": sym, "base": base, "sym": f"{base}USDT", "vol": vol, "fund": fund, "rank": pct * np.log10(max(vol, 10))})
        cands = list(sorted(cands, key=lambda x: x["rank"], reverse=True))[:25]
    except Exception as e:
        return pd.DataFrame(), None, 0, f"Err: {e}"

    ctx, rows = get_astro(mode), []
    for c in cands:
        try:
            url = f"{CC_BASE}/data/v2/histominute"
            prm = {"fsym": c["base"], "tsym": "USDT", "limit": 96, "aggregate": 15}
            k15_raw = requests.get(url, params=prm, headers=HEADERS, timeout=5).json().get("Data", {}).get("Data", [])
            obd = requests.get(BASE + "/orderbook", params={"symbol": c["inst"]}, timeout=5).json().get("orderBook", {})
            if len(k15_raw) < 40:
                continue

            df = pd.DataFrame(k15_raw).astype(float)
            price = last_val(df["close"])
            if price <= 0:
                continue

            hi24, lo24 = float(df["high"].max()), float(df["low"].min())
            room_lo = ((price - lo24) / max(lo24, 1e-9)) * 100.0
            room_hi = ((hi24 - price) / max(price, 1e-9)) * 100.0

            e9, e21, e50 = last_val(df["close"].ewm(span=9).mean()), last_val(df["close"].ewm(span=21).mean()), last_val(df["close"].ewm(span=50).mean())
            vwap = float((df["close"] * df["volumeto"]).sum() / max(df["volumeto"].sum(), 1e-9))
            d = df["close"].diff()
            rsi = 100.0 - (100.0 / (1.0 + last_val(d.clip(lower=0).rolling(14).mean()) / max(last_val((-d.clip(upper=0)).rolling(14).mean()), 1e-9)))
            tr = pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift()).abs(), (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
            atr_pct = (last_val(tr.rolling(14).mean()) / price) * 100.0
            ob = sum(float(q) for _, q in list(obd.get("bids", []))[:20]) / max(sum(float(q) for _, q in list(obd.get("asks", []))[:20]), 1e-9)

            lp = 25.0 + (20.0 if (e9 > e21 and price > e50) else 0.0) + (15.0 if price > vwap else 0.0) + (18.0 if (46 <= rsi <= 62) else 0.0) + (12.0 if room_hi >= 1.8 else -25.0)
            sp = 25.0 + (20.0 if (e9 < e21 and price < e50) else 0.0) + (15.0 if price < vwap else 0.0) + (18.0 if (42 <= rsi <= 56) else 0.0) + (12.0 if room_lo >= 1.8 else -25.0)

            if btc_state == "BULL":
                lp, sp = lp + 12.0, sp - 20.0
            elif btc_state == "BEAR":
                sp, lp = sp + 12.0, lp - 20.0

            direction = "LONG" if lp >= sp else "SHORT"
            safe = (direction == "LONG" and room_hi >= 1.5 and rsi <= 65) or (direction == "SHORT" and room_lo >= 1.5 and rsi >= 38)
            btc_ok = (direction == "LONG" and btc_state != "BEAR") or (direction == "SHORT" and btc_state != "BULL")
            flow = float(np.clip(max(lp, sp), 0, 100))
            astro, anote = score_astro(c["base"], ctx, mode)
            total = round(min(99.0, flow * 0.72 + astro * 0.28), 1)
            r_txt = f"Room:{room_hi:.1f}%H" if direction == "LONG" else f"Room:{room_lo:.1f}%L"

            rows.append({"Symbol": c["sym"], "Price": price, "24h Vol ($M)": round(c["vol"] / 1e6, 2), "Direction": direction, "5m RSI": round(rsi, 1), "OB Ratio": round(ob, 2), "Funding %": round(c["fund"], 4), "Flow Score": round(flow, 1), "Astro Score": round(astro, 1), "Total Score": total, "SAFE": (safe and btc_ok), "ATR %": atr_pct, "Astro Note": f"BTC:{btc_state} | {r_txt} | {anote}"})
        except Exception:
            continue

    if not rows:
        return pd.DataFrame(), None, len(cands), f"BTC:{btc_state} | No setups"
    df = pd.DataFrame(rows).sort_values("Total Score", ascending=False).reset_index(drop=True)
    qual = df[(df["SAFE"] == True) & (df["Total Score"] >= 68.0)].to_dict("records")
    sig = None
    for b in qual[:1]:
        sc = float(b["Total Score"])
        lev = 30 if sc >= 85 else (25 if sc >= 76 else 20)
        ent, atr = float(b["Price"]), max(0.45, float(b["ATR %"]))
        tp1_p = round(max(0.012, min(0.018, (atr * 1.6) / 100.0)), 4)
        tp2_p = round(max(0.022, min(0.030, (atr * 2.8) / 100.0)), 4)
        sl_p = round(max(0.0095, min(0.0125, tp1_p * 0.72)), 4)
        sl = ent * (1 - sl_p) if b["Direction"] == "LONG" else ent * (1 + sl_p)
        tp1 = ent * (1 + tp1_p) if b["Direction"] == "LONG" else ent * (1 - tp1_p)
        tp2 = ent * (1 + tp2_p) if b["Direction"] == "LONG" else ent * (1 - tp2_p)
        c_utc = datetime.now(pytz.UTC) + timedelta(minutes=45)
        c_pkt = c_utc.astimezone(pytz.timezone("Asia/Karachi"))
        sig = dict(symbol=b["Symbol"], direction=b["Direction"], score=sc, leverage=lev, entry=ent, tp1=tp1, tp2=tp2, sl=sl, sl_pct=round(sl_p * 100, 2), close_utc=c_utc.strftime("%H:%M:%S UTC"), close_pkt=c_pkt.strftime("%I:%M:%S %p PKT"), hold_mins=45, astro_note=b["Astro Note"], ob_ratio=b["OB Ratio"], rsi=b["5m RSI"])
    return df, sig, len(cands), f"BTC:{btc_state} | USDT Sync ({len(rows)} scored)"
