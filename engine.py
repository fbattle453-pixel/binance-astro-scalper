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
    return {"hora": hora, "aspects": aspects, "nak": NAKS[int(mdeg // (360.0 / 27.0))], "mins": max(20, min(55, 60 - now.minute))}

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
            # Prioritize tokens actively moving in the 1.5%-8.0% expansion zone (avoid exhausted >15% pumps)
            if 0.10 <= p <= 100.00 and vol >= 150_000 and pct <= 15.0:
                sweet_spot = 1.5 if 1.5 <= pct <= 6.5 else 1.0
                cands.append({"inst": sym, "base": base, "sym": f"{base}USDT", "vol": vol, "pct": pct, "fund": float(t.get("fundingRate") or 0)*100.0, "rank": sweet_spot * pct * np.log10(max(vol, 10))})
        cands = sorted(cands, key=lambda x: x["rank"], reverse=True)[:25]
    except Exception as e:
        return pd.DataFrame(), None, 0, f"Err: {e}"

    ctx, rows = get_astro(mode), []
    for c in cands:
        try:
            k5 = requests.get(f"{CHART_BASE}/{c['inst']}/5m", headers=HEADERS, timeout=5).json().get("candles", [])[-36:]
            obd = requests.get(BASE + "/orderbook", params={"symbol": c["inst"]}, headers=HEADERS, timeout=5).json().get("orderBook", {})
            if len(k5) < 20: continue
            df5 = pd.DataFrame(k5).astype(float)
            price = float(df5["close"].iat[-1])
            if price <= 0: continue
            e9, e21 = float(df5["close"].ewm(span=9).mean().iat[-1]), float(df5["close"].ewm(span=21).mean().iat[-1])
            vwap = float((df5["close"] * df5["volume"]).sum() / max(df5["volume"].sum(), 1e-9))
            vol_surge = float(df5["volume"].iloc[-3:].mean()) / max(float(df5["volume"].iloc[:-3].mean()), 1e-9)

            d = df5["close"].diff()
            rsi = 100.0 - (100.0 / (1.0 + float(d.clip(lower=0).rolling(14).mean().iat[-1]) / max(float((-d.clip(upper=0)).rolling(14).mean().iat[-1]), 1e-9)))
            tr = pd.concat([df5["high"]-df5["low"], (df5["high"]-df5["close"].shift()).abs(), (df5["low"]-df5["close"].shift()).abs()], axis=1).max(axis=1)
            atr_pct = (float(tr.rolling(14).mean().iat[-1]) / price) * 100.0
            ob = sum(float(q) for _, q in obd.get("bids", [])[:20]) / max(sum(float(q) for _, q in obd.get("asks", [])[:20]), 1e-9)
            fund = c["fund"]

            # Multi-condition confluence scoring for a 2%-5% breakout wave
            lp = 35.0 + (18.0 if e9 > e21 else 0.0) + (14.0 if price > vwap else 0.0) + (15.0 if ob >= 1.25 else 0.0) + (10.0 if 52 <= rsi <= 68 else 0.0) + (8.0 if vol_surge >= 1.15 and price > df5["open"].iat[-1] else 0.0) + (5.0 if fund < 0 else 0.0)
            sp = 35.0 + (18.0 if e9 < e21 else 0.0) + (14.0 if price < vwap else 0.0) + (15.0 if ob <= 0.80 else 0.0) + (10.0 if 32 <= rsi <= 48 else 0.0) + (8.0 if vol_surge >= 1.15 and price < df5["open"].iat[-1] else 0.0) + (5.0 if fund > 0.02 else 0.0)

            direction = "LONG" if lp >= sp else "SHORT"
            flow = float(np.clip(max(lp, sp), 0, 100))
            astro, anote = score_astro(c["base"], ctx, mode)
            # Extra confluence edge bonus when Technicals + Order Book + Astro all agree
            edge_bonus = 6.0 if (flow >= 75.0 and astro >= 70.0) else 0.0
            total = round(min(99.0, flow * 0.65 + astro * 0.35 + edge_bonus), 1)

            rows.append({"Symbol": c["sym"], "Price": price, "24h Vol ($M)": round(c["vol"]/1e6, 2), "Direction": direction, "5m RSI": round(rsi, 1), "OB Ratio": round(ob, 2), "Funding %": round(fund, 4), "Flow Score": round(flow, 1), "Astro Score": round(astro, 1), "Total Score": total, "ATR %": atr_pct, "Astro Note": f"{anote} | VolSurge:{vol_surge:.1f}x"})
        except Exception:
            continue

    if not rows: return pd.DataFrame(), None, len(cands), "No candles"
    df = pd.DataFrame(rows).sort_values("Total Score", ascending=False).reset_index(drop=True)
    sig = None
    b = df.iloc
    if float(b["Total Score"]) >= 65.0:
        sc = float(b["Total Score"])
        # Calibrated leverage (20x-35x) so a 2%-5% move has room to breathe without wick liquidation
        lev = 35 if sc >= 85 else (25 if sc >= 75 else 20)
        ent = float(b["Price"])
        # Target 2.0%-2.5% for TP1 and 3.8%-5.0% for TP2 with a protected ~1.0%-1.35% Stop-Loss
        sl_p = max(0.009, min(0.0135, (float(b["ATR %"]) * 2.2) / 100.0))
        tp1_p = max(0.020, min(0.025, sl_p * 2.1))
        tp2_p = max(0.038, min(0.050, sl_p * 3.8))
        sl = ent * (1 - sl_p) if b["Direction"] == "LONG" else ent * (1 + sl_p)
        tp1 = ent * (1 + tp1_p) if b["Direction"] == "LONG" else ent * (1 - tp1_p)
        tp2 = ent * (1 + tp2_p) if b["Direction"] == "LONG" else ent * (1 - tp2_p)
        c_utc = datetime.now(pytz.UTC) + timedelta(minutes=ctx["mins"])
        c_pkt = c_utc.astimezone(pytz.timezone("Asia/Karachi"))
        sig = dict(symbol=b["Symbol"], direction=b["Direction"], score=sc, leverage=lev, entry=ent, tp1=tp1, tp2=tp2, sl=sl, sl_pct=round(sl_p*100, 2), close_utc=c_utc.strftime("%H:%M:%S UTC"), close_pkt=c_pkt.strftime("%I:%M:%S %p PKT"), hold_mins=ctx["mins"], astro_note=b["Astro Note"], ob_ratio=b["OB Ratio"], rsi=b["5m RSI"])
    return df, sig, len(cands), f"2%-5% Edge Filter ({len(rows)} scored)"
