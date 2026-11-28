import requests, pandas as pd, numpy as np, ephem, pytz, hashlib
from datetime import datetime, timedelta

PROTO = "https" + chr(58) + chr(47) + chr(47)
HOST = chr(46).join(["futures", "kraken", "com"])
BASE = PROTO + HOST + "/derivatives/api/v3"
CHART_BASE = PROTO + HOST + "/api/charts/v1/trade"
HEADERS = {"User-Agent": "Mozilla/5.0"}

EXCLUDE = {"XAG","XAU","XPT","XPD","EUR","GBP","JPY","AUD","CAD","CHF","NZD","SOXL","SOXS","TSLA","NVDA","AAPL","MSFT","AMZN","GOOGL","META","AMD","COIN","MSTR","PLTR","SPY","QQQ","IWM","TLT","GLD","SLV","HOOD","GME","AMC","NFLX","INTC","SMCI","ARM","MARA","RIOT"}
RULERS = {"SOL":"Sun","XRP":"Jupiter","SUI":"Moon","NEAR":"Mercury","LINK":"Saturn","FET":"Uranus","AVAX":"Mars","DOT":"Jupiter","ADA":"Venus","UNI":"Mercury","ATOM":"Uranus","TRX":"Mars","OM":"Saturn","SSV":"Saturn","HYPE":"Uranus","APT":"Mercury","ARB":"Uranus","OP":"Mercury","INJ":"Mars","TIA":"Uranus","LTC":"Moon","FIL":"Saturn","RENDER":"Uranus","SEI":"Moon","DOGE":"Moon","PEPE":"Moon","WIF":"Mars","BONK":"Mars","AAVE":"Jupiter","TAO":"Uranus"}
PLANETS = ["Sun","Moon","Mars","Mercury","Jupiter","Venus","Saturn"]
HORAS = ["Sun","Venus","Mercury","Moon","Saturn","Jupiter","Mars"]
NAKS = ["Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra","Punarvasu","Pushya","Ashlesha","Magha","Purva Phalguni","Uttara Phalguni","Hasta","Chitra","Swati","Vishakha","Anuradha","Jyeshtha","Mula","Purva Ashadha","Uttara Ashadha","Shravana","Dhanishta","Shatabhisha","Purva Bhadrapada","Uttara Bhadrapada","Revati"]

def last_val(series):
    return float(series.to_list().pop())

def get_astro(mode):
    now = datetime.now(pytz.UTC)
    obs = ephem.Observer()
    obs.date = now.strftime("%Y/%m/%d %H:%M:%S")
    bodies = {"Sun":ephem.Sun(obs),"Moon":ephem.Moon(obs),"Mars":ephem.Mars(obs),"Mercury":ephem.Mercury(obs),"Jupiter":ephem.Jupiter(obs),"Venus":ephem.Venus(obs),"Saturn":ephem.Saturn(obs)}
    aya = (23.853 + ((now.year + now.timetuple().tm_yday / 365.25) - 2000.0) * 0.0139688) if mode == "Vedic" else 0.0
    longs = {k: (np.degrees(ephem.Ecliptic(v).lon) - aya) % 360.0 for k, v in bodies.items()}
    hora = HORAS[({6:0,0:3,1:6,2:2,3:4,4:1,5:5}[now.weekday()] + now.hour) % 7]
    mdeg = longs["Moon"]
    is_voc = (mdeg % 30.0) >= 27.5
    aspects = []
    for p, deg in longs.items():
        if p == "Moon": continue
        diff = min(abs(mdeg - deg) % 360, 360 - (abs(mdeg - deg) % 360))
        for ang, lbl, mod in [(0,"Conj",14),(60,"Sextile",9),(90,"Square",-12),(120,"Trine",14),(180,"Opp",-12)]:
            if abs(diff - ang) <= 0.6:
                aspects.append((p, lbl, mod))
    return {"hora": hora, "aspects": aspects, "nak": NAKS[int(mdeg // (360.0 / 27.0))], "voc": is_voc}

def score_astro(coin, ctx, mode):
    ruler = RULERS.get(coin, PLANETS[int(hashlib.md5(coin.encode()).hexdigest(), 16) % 7])
    sc = 50.0 + (22.0 if ctx["hora"] == ruler else (8.0 if ctx["hora"] in ["Jupiter","Venus","Sun"] else 0.0))
    notes = [f"Ruler:{ruler} | Hora:{ctx['hora']}"]
    if ctx["hora"] == ruler: notes.append(f"{ruler} Hora(+22)")
    if ctx["voc"]:
        sc -= 18.0
        notes.append("VoC Moon(-18)")
    for p, lbl, mod in ctx["aspects"]:
        sc += mod * (1.5 if p == ruler else 0.6)
        if p == ruler: notes.append(f"Moon {lbl} {ruler}")
    if mode == "Vedic":
        notes.append(f"Nak:{ctx['nak']}")
        if ctx["nak"] in ["Rohini","Pushya","Hasta","Shravana","Revati","Ashwini"]: sc += 10.0
    return float(np.clip(sc, 0, 100)), " | ".join(notes)

def get_btc_regime():
    try:
        k15 = requests.get(f"{CHART_BASE}/PF_XBTUSD/15m", headers=HEADERS, timeout=5).json().get("candles", [])
        df = pd.DataFrame(k15).tail(25).astype(float)
        p = last_val(df["close"])
        e9 = last_val(df["close"].ewm(span=9).mean())
        e21 = last_val(df["close"].ewm(span=21).mean())
        if p > e21 and e9 >= e21: return "BULL"
        if p < e21 and e9 <= e21: return "BEAR"
        return "CHOP"
    except Exception:
        return "NEUTRAL"

def run_market_scan(mode="Western"):
    btc_state = get_btc_regime()
    try:
        r = requests.get(BASE + "/tickers", headers=HEADERS, timeout=8)
        if r.status_code != 200: return pd.DataFrame(), None, 0, f"HTTP {r.status_code}"
        cands = []
        for t in r.json().get("tickers", []):
            sym = t.get("symbol", "")
            if not sym.startswith("PF_") or not sym.endswith("USD"): continue
            base = "BTC" if sym == "PF_XBTUSD" else sym.replace("PF_", "").replace("USD", "")
            if base in EXCLUDE or base == "BTC": continue
            p, vol, op = float(t.get("last") or 0), float(t.get("volumeQuote") or 0), float(t.get("open24h") or 0)
            pct = abs((p - op) / op) * 100.0 if op > 0 else 2.0
            if 0.001 <= p <= 200.00 and vol >= 150_000 and 1.0 <= pct <= 14.0:
                cands.append({"inst": sym, "base": base, "sym": f"{base}USDT", "vol": vol, "pct": pct, "fund": float(t.get("fundingRate") or 0)*100.0, "rank": pct * np.log10(max(vol, 10))})
        cands = sorted(cands, key=lambda x: x["rank"], reverse=True)
        cands = list(cands)[:25]
    except Exception as e:
        return pd.DataFrame(), None, 0, f"Err: {e}"

    ctx, rows = get_astro(mode), []
    for c in cands:
        try:
            k5_raw = requests.get(f"{CHART_BASE}/{c['inst']}/5m", headers=HEADERS, timeout=5).json().get("candles", [])
            k15_raw = requests.get(f"{CHART_BASE}/{c['inst']}/15m", headers=HEADERS, timeout=5).json().get("candles", [])
            obd = requests.get(BASE + "/orderbook", params={"symbol": c["inst"]}, headers=HEADERS, timeout=5).json().get("orderBook", {})
            if len(k5_raw) < 25 or len(k15_raw) < 25: continue

            df5 = pd.DataFrame(k5_raw).tail(36).astype(float)
            df15 = pd.DataFrame(k15_raw).tail(36).astype(float)
            price = last_val(df5["close"])
            open5 = last_val(df5["open"])
            if price <= 0: continue

            e9_15 = last_val(df15["close"].ewm(span=9).mean())
            e21_15 = last_val(df15["close"].ewm(span=21).mean())
            vwap5 = float((df5["close"] * df5["volume"]).sum() / max(df5["volume"].sum(), 1e-9))

            recent_vol = float(df5["volume"].tail(2).mean())
            prior_vol = float(df5["volume"].head(len(df5) - 2).mean())
            vol_ratio = recent_vol / max(prior_vol, 1e-9)

            prior_df = df5.head(len(df5) - 3).tail(15)
            recent_df = df5.tail(3)
            prev_low = float(prior_df["low"].min())
            prev_high = float(prior_df["high"].max())
            bull_sweep = (float(recent_df["low"].min()) <= prev_low) and (price > prev_low)
            bear_sweep = (float(recent_df["high"].max()) >= prev_high) and (price < prev_high)

            d = df5["close"].diff()
            gain = last_val(d.clip(lower=0).rolling(14).mean())
            loss = last_val((-d.clip(upper=0)).rolling(14).mean())
            rsi = 100.0 - (100.0 / (1.0 + gain / max(loss, 1e-9)))

            tr = pd.concat([df5["high"]-df5["low"], (df5["high"]-df5["close"].shift()).abs(), (df5["low"]-df5["close"].shift()).abs()], axis=1).max(axis=1)
            atr_pct = (last_val(tr.rolling(14).mean()) / price) * 100.0

            bids = list(obd.get("bids", []))[:20]
            asks = list(obd.get("asks", []))[:20]
            ob = sum(float(q) for _, q in bids) / max(sum(float(q) for _, q in asks), 1e-9)

            lp = 30.0 + (18.0 if e9_15 > e21_15 else 0.0) + (12.0 if price > vwap5 else 0.0) + (18.0 if bull_sweep else 0.0) + (12.0 if vol_ratio >= 1.25 and price > open5 else 0.0) + (10.0 if 40 <= rsi <= 62 else 0.0)
            sp = 30.0 + (18.0 if e9_15 < e21_15 else 0.0) + (12.0 if price < vwap5 else 0.0) + (18.0 if bear_sweep else 0.0) + (12.0 if vol_ratio >= 1.25 and price < open5 else 0.0) + (10.0 if 38 <= rsi <= 60 else 0.0)

            if btc_state == "BULL":
                lp += 12.0
                sp -= 18.0
            elif btc_state == "BEAR":
                sp += 12.0
                lp -= 18.0

            direction = "LONG" if lp >= sp else "SHORT"
            btc_aligned = (direction == "LONG" and btc_state != "BEAR") or (direction == "SHORT" and btc_state != "BULL")
            flow = float(np.clip(max(lp, sp), 0, 100))
            astro, anote = score_astro(c["base"], ctx, mode)
            total = round(min(99.0, flow * 0.72 + astro * 0.28), 1)

            setup_tag = "Sweep+Vol" if (bull_sweep or bear_sweep) else f"Vol:{vol_ratio:.1f}x"
            rows.append({"Symbol": c["sym"], "Price": price, "24h Vol ($M)": round(c["vol"]/1e6, 2), "Direction": direction, "5m RSI": round(rsi, 1), "OB Ratio": round(ob, 2), "Funding %": round(c["fund"], 4), "Flow Score": round(flow, 1), "Astro Score": round(astro, 1), "Total Score": total, "BTC_OK": btc_aligned, "ATR %": atr_pct, "Astro Note": f"BTC:{btc_state} | {setup_tag} | {anote}"})
        except Exception:
            continue

    if not rows: return pd.DataFrame(), None, len(cands), f"BTC:{btc_state} | No setups"
    df = pd.DataFrame(rows).sort_values("Total Score", ascending=False).reset_index(drop=True)

    qual_list = df[(df["BTC_OK"] == True) & (df["Total Score"] >= 68.0)].to_dict("records")
    sig = None
    for b in qual_list[:1]:
        sc = float(b["Total Score"])
        lev = 35 if sc >= 85 else (25 if sc >= 76 else 20)
        ent = float(b["Price"])
        atr = max(0.25, float(b["ATR %"]))
        tp1_p = round(max(0.0075, min(0.015, (atr * 2.5) / 100.0)), 4)
        tp2_p = round(max(0.0150, min(0.030, (atr * 4.8) / 100.0)), 4)
        sl_p = round(max(0.0055, min(0.011, tp1_p * 0.65)), 4)

        sl = ent * (1 - sl_p) if b["Direction"] == "LONG" else ent * (1 + sl_p)
        tp1 = ent * (1 + tp1_p) if b["Direction"] == "LONG" else ent * (1 - tp1_p)
        tp2 = ent * (1 + tp2_p) if b["Direction"] == "LONG" else ent * (1 - tp2_p)

