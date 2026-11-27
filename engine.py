import requests, pandas as pd, numpy as np, ephem, pytz, hashlib
from datetime import datetime, timedelta

PROTO = "https" + chr(58) + chr(47) + chr(47)
HOST = chr(46).join(["futures", "kraken", "com"])
BASE = PROTO + HOST + "/derivatives/api/v3"
CHART_BASE = PROTO + HOST + "/api/charts/v1/trade"
HEADERS = {"User-Agent": "Mozilla/5.0"}

EXCLUDE = {"XAG","XAU","XPT","XPD","EUR","GBP","JPY","AUD","CAD","CHF","NZD","SOXL","SOXS","TSLA","NVDA","AAPL","MSFT","AMZN","GOOGL","META","AMD","COIN","MSTR","PLTR","SPY","QQQ","IWM","TLT","GLD","SLV","HOOD","GME","AMC","NFLX","INTC","SMCI","ARM","MARA","RIOT"}
RULERS = {"SOL":"Sun","XRP":"Jupiter","SUI":"Moon","NEAR":"Mercury","LINK":"Saturn","FET":"Uranus","AVAX":"Mars","DOT":"Jupiter","ADA":"Venus","UNI":"Mercury","ATOM":"Uranus","TRX":"Mars","OM":"Saturn","SSV":"Saturn","HYPE":"Uranus","APT":"Mercury","ARB":"Uranus","OP":"Mercury","INJ":"Mars","TIA":"Uranus","LTC":"Moon","FIL":"Saturn","RENDER":"Uranus","SEI":"Moon"}
PLANETS = ["Sun","Moon","Mars","Mercury","Jupiter","Venus","Saturn"]
HORAS = ["Sun","Venus","Mercury","Moon","Saturn","Jupiter","Mars"]
NAKS = ["Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra","Punarvasu","Pushya","Ashlesha","Magha","Purva Phalguni","Uttara Phalguni","Hasta","Chitra","Swati","Vishakha","Anuradha","Jyeshtha","Mula","Purva Ashadha","Uttara Ashadha","Shravana","Dhanishta","Shatabhisha","Purva Bhadrapada","Uttara Bhadrapada","Revati"]

def get_astro(mode):
    now = datetime.now(pytz.UTC)
    obs = ephem.Observer()
    obs.date = now.strftime("%Y/%m/%d %H:%M:%S")
    bodies = {"Sun":ephem.Sun(obs),"Moon":ephem.Moon(obs),"Mars":ephem.Mars(obs),"Mercury":ephem.Mercury(obs),"Jupiter":ephem.Jupiter(obs),"Venus":ephem.Venus(obs),"Saturn":ephem.Saturn(obs)}
    aya = (23.853 + ((now.year + now.timetuple().tm_yday / 365.25) - 2000.0) * 0.0139688) if mode == "Vedic" else 0.0
    longs = {k: (np.degrees(ephem.Ecliptic(v).lon) - aya) % 360.0 for k, v in bodies.items()}
    hora = HORAS[({6:0,0:3,1:6,2:2,3:4,4:1,5:5}[now.weekday()] + now.hour) % 7]
    mdeg = longs["Moon"]
    aspects = []
    for p, deg in longs.items():
        if p == "Moon": continue
        diff = min(abs(mdeg - deg) % 360, 360 - (abs(mdeg - deg) % 360))
        for ang, lbl, mod in [(0,"Conj",12),(60,"Sextile",8),(90,"Square",-10),(120,"Trine",12),(180,"Opp",-10)]:
            if abs(diff - ang) <= 1.0: aspects.append((p, lbl, mod))
    return {"hora": hora, "aspects": aspects, "nak": NAKS[int(mdeg // (360.0 / 27.0))], "mins": max(30, min(60, 60 - now.minute))}

def score_astro(coin, ctx, mode):
    ruler = RULERS.get(coin, PLANETS[int(hashlib.md5(coin.encode()).hexdigest(), 16) % 7])
    sc = 50.0 + (25.0 if ctx["hora"] == ruler else (10.0 if ctx["hora"] in ["Jupiter","Venus","Sun"] else 0.0))
    notes = [f"Ruler:{ruler} | Hora:{ctx['hora']}"]
    if ctx["hora"] == ruler: notes.append(f"{ruler} Hora(+25)")
    for p, lbl, mod in ctx["aspects"]:
        sc += mod * (1.5 if p == ruler else 0.5)
        if p == ruler: notes.append(f"Moon {lbl} {ruler}")
    if mode == "Vedic":
        notes.append(f"Nak:{ctx['nak']}")
        if ctx["nak"] in ["Rohini","Pushya","Hasta","Shravana","Revati","Ashwini"]: sc += 10.0
    return float(np.clip(sc, 0, 100)), " | ".join(notes)

def run_market_scan(mode="Western"):
    try:
        r = requests.get(BASE + "/tickers", headers=HEADERS, timeout=8)
        if r.status_code != 200: return pd.DataFrame(), None, 0, f"HTTP {r.status_code}"
        cands = []
        for t in r.json().get("tickers", []):
            sym = t.get("symbol", "")
            if not sym.startswith("PF_") or not sym.endswith("USD"): continue
            base = "BTC" if sym == "PF_XBTUSD" else sym.replace("PF_", "").replace("USD", "")
            if base in EXCLUDE: continue
            p, vol, op = float(t.get("last") or 0), float(t.get("volumeQuote") or 0), float(t.get("open24h") or 0)
            pct = abs((p - op) / op) * 100.0 if op > 0 else 2.0
            if 0.10 <= p <= 100.00 and vol >= 150_000 and 1.2 <= pct <= 12.0:
                cands.append({"inst": sym, "base": base, "sym": f"{base}USDT", "vol": vol, "pct": pct, "fund": float(t.get("fundingRate") or 0)*100.0, "rank": pct * np.log10(max(vol, 10))})
        cands = sorted(cands, key=lambda x: x["rank"], reverse=True)[:25]
    except Exception as e:
        return pd.DataFrame(), None, 0, f"Err: {e}"

    ctx, rows = get_astro(mode), []
    for c in cands:
        try:
            k15 = requests.get(f"{CHART_BASE}/{c['inst']}/15m", headers=HEADERS, timeout=5).json().get("candles", [])[-55:]
            obd = requests.get(BASE + "/orderbook", params={"symbol": c["inst"]}, headers=HEADERS, timeout=5).json().get("orderBook", {})
            if len(k15) < 30: continue
            df = pd.DataFrame(k15).astype(float)
            price = float(df["close"].iat[-1])
            if price <= 0: continue

            e9 = float(df["close"].ewm(span=9).mean().iat[-1])
            e21 = float(df["close"].ewm(span=21).mean().iat[-1])
            e50 = float(df["close"].ewm(span=50).mean().iat[-1])
            vwap = float((df["close"] * df["volume"]).sum() / max(df["volume"].sum(), 1e-9))

            d = df["close"].diff()
            rsi = 100.0 - (100.0 / (1.0 + float(d.clip(lower=0).rolling(14).mean().iat[-1]) / max(float((-d.clip(upper=0)).rolling(14).mean().iat[-1]), 1e-9)))
            tr = pd.concat([df["high"]-df["low"], (df["high"]-df["close"].shift()).abs(), (df["low"]-df["close"].shift()).abs()], axis=1).max(axis=1)
            atr_pct = (float(tr.rolling(14).mean().iat[-1]) / price) * 100.0
            ob = sum(float(q) for _, q in obd.get("bids", [])[:20]) / max(sum(float(q) for _, q in obd.get("asks", [])[:20]), 1e-9)

            uptrend = e9 > e21 and price > e50
            downtrend = e9 < e21 and price < e50
            pullback_long = uptrend and (42 <= rsi <= 58) and (price >= vwap * 0.995)
            pullback_short = downtrend and (42 <= rsi <= 58) and (price <= vwap * 1.005)

            lp = 35.0 + (22.0 if uptrend else 0.0) + (20.0 if pullback_long else 0.0) + (10.0 if ob >= 1.1 else 0.0) + (8.0 if c["fund"] <= 0.01 else 0.0)
            sp = 35.0 + (22.0 if downtrend else 0.0) + (20.0 if pullback_short else 0.0) + (10.0 if ob <= 0.9 else 0.0) + (8.0 if c["fund"] >= -0.01 else 0.0)

            if rsi > 68: lp -= 25.0
            if rsi < 32: sp -= 25.0

            direction = "LONG" if lp >= sp else "SHORT"
            flow = float(np.clip(max(lp, sp), 0, 100))
            astro, anote = score_astro(c["base"], ctx, mode)
            total = round(min(99.0, flow * 0.70 + astro * 0.30), 1)

            rows.append({"Symbol": c["sym"], "Price": price, "24h Vol ($M)": round(c["vol"]/1e6, 2), "Direction": direction, "5m RSI": round(rsi, 1), "OB Ratio": round(ob, 2), "Funding %": round(fund, 4), "Flow Score": round(flow, 1), "Astro Score": round(astro, 1), "Total Score": total, "ATR %": atr_pct, "Astro Note": f"15m Pullback | {anote}"})
        except Exception:
            continue

    if not rows: return pd.DataFrame(), None, len(cands), "No setups"
    df = pd.DataFrame(rows).sort_values("Total Score", ascending=False).reset_index(drop=True)
    sig = None
    b = df.iloc
    if float(b["Total Score"]) >= 68.0:
        sc = float(b["Total Score"])
        lev = 30 if sc >= 85 else (25 if sc >= 76 else 20)
        ent = float(b["Price"])
        sl_p = max(0.011, min(0.015, (float(b["ATR %"]) * 1.5) / 100.0))
        sl = ent * (1 - sl_p) if b["Direction"] == "LONG" else ent * (1 + sl_p)
        tp1 = ent * (1 + 0.022) if b["Direction"] == "LONG" else ent * (1 - 0.022)
        tp2 = ent * (1 + 0.032) if b["Direction"] == "LONG" else ent * (1 - 0.032)
        c_utc = datetime.now(pytz.UTC) + timedelta(minutes=ctx["mins"])
        c_pkt = c_utc.astimezone(pytz.timezone("Asia/Karachi"))
        sig = dict(symbol=b["Symbol"], direction=b["Direction"], score=sc, leverage=lev, entry=ent, tp1=tp1, tp2=tp2, sl=sl, sl_pct=round(sl_p*100, 2), close_utc=c_utc.strftime("%H:%M:%S UTC"), close_pkt=c_pkt.strftime("%I:%M:%S %p PKT"), hold_mins=ctx["mins"], astro_note=b["Astro Note"], ob_ratio=b["OB Ratio"], rsi=b["5m RSI"])
    return df, sig, len(cands), f"15m Pullback 2.2%-3.2% ({len(rows)} scored)"
