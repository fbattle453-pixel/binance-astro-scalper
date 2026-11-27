import streamlit as st, requests, os, time, pytz
from datetime import datetime
from engine import run_market_scan

st.set_page_config(page_title="Futures Astro Scalp Scanner", page_icon="⚡", layout="wide")

def get_secret(key):
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return os.environ.get(key, "").strip()

def send_telegram(msg):
    token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"
    try:
        host = "api.telegram.org"
        endpoint = f"https://{host}/bot{token}/sendMessage"
        r = requests.post(endpoint, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=8)
        if r.status_code == 200:
            return True, "OK"
        return False, r.json().get("description", f"HTTP {r.status_code}")
    except Exception as e:
        return False, str(e)

if "last_alert" not in st.session_state:
    st.session_state.last_alert = {}

st.title("⚡ Futures Market-Wide Astro Scalper ($0.10 – $100)")
c1, c2, c3 = st.columns([1.2, 1.5, 1])
with c1:
    scanner_on = st.toggle("🟢 Live Scalp Scanner (20s Auto-Scan)", value=True)
with c2:
    astro_mode = st.radio("Astrology System:", ["Western", "Vedic"], horizontal=True)
with c3:
    tg_ready = bool(get_secret("TELEGRAM_BOT_TOKEN") and get_secret("TELEGRAM_CHAT_ID"))
    st.markdown(f"**Telegram Alerts:** {'✅ Connected' if tg_ready else '⚠️ Missing Secrets'}")

with st.sidebar:
    st.header("🛡️ 20x–50x Position Calculator")
    wallet_usdt = st.number_input("Futures Wallet (USDT)", min_value=10.0, value=500.0, step=50.0)
    risk_pct = st.slider("Max Risk per Scalp (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5)
    st.divider()
    if st.button("📲 Send Test Telegram Alert"):
        ok, info = send_telegram("✅ *Test Alert:* Futures Astro Scalper is connected and scanning!")
        if ok:
            st.success("Sent! Check your Telegram.")
        else:
            st.error(f"Telegram Error: {info}")

with st.spinner("Scanning Futures Order Books & Planetary Transits..."):
    df_results, signal, matched, debug_msg = run_market_scan(astro_mode)

now_pkt = datetime.now(pytz.timezone("Asia/Karachi")).strftime("%I:%M:%S %p PKT")
st.caption(f"Last Scan: {now_pkt} | Filtered Liquid Pairs ($0.10–$100): Top {matched} analyzed | Mode: {astro_mode} | Status: {debug_msg}")

if signal:
    risk_usdt = wallet_usdt * (risk_pct / 100.0)
    rec_margin = round((risk_usdt / (signal["sl_pct"] / 100.0)) / signal["leverage"], 2)
    dir_icon = "🟢 LONG" if signal["direction"] == "LONG" else "🔴 SHORT"
    st.success(f"### 🎯 TOP QUALIFIED SCALP: **{signal['symbol']}** — {dir_icon} ({signal['score']}%)")

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Entry Price", f"${signal['entry']:.4f}")
    m2.metric("Leverage (Isolated)", f"{signal['leverage']}x")
    m3.metric("TP 1 (50%)", f"${signal['tp1']:.4f}")
    m4.metric("TP 2 (Runner)", f"${signal['tp2']:.4f}")
    m5.metric("Stop-Loss", f"${signal['sl']:.4f}", f"-{signal['sl_pct']}%")
    m6.metric("Suggested Margin", f"${rec_margin} USDT")

    st.info(f"⏳ **Close By:** **{signal['close_pkt']}** ({signal['close_utc']} — ~{signal['hold_mins']}m) | {signal['astro_note']} | OB: {signal['ob_ratio']}x | RSI: {signal['rsi']}")

    akey = f"{signal['symbol']}_{signal['direction']}"
    if time.time() - st.session_state.last_alert.get(akey, 0) > 900:
        msg = (
            f"⚡ *SCALP ({astro_mode.upper()})*\n"
            f"🪙 `{signal['symbol']}` | {dir_icon} ({signal['score']}%)\n"
            f"⚙️ *{signal['leverage']}x Isolated*\n"
            f"💵 Entry: `${signal['entry']:.4f}`\n"
            f"✅ TP1: `${signal['tp1']:.4f}` | TP2: `${signal['tp2']:.4f}`\n"
            f"🛑 SL: `${signal['sl']:.4f}` (-{signal['sl_pct']}%)\n"
            f"⏳ Close: {signal['close_pkt']}"
        )
        ok, _ = send_telegram(msg)
        if ok:
            st.session_state.last_alert[akey] = time.time()
else:
    st.warning("🔍 **NO ULTRA-HIGH PROBABILITY SCALP (>=82%) — SCANNING ORDER BOOKS ($0.10–$100)**")

st.subheader("📊 Top 25 Active Futures Pairs ($0.10 – $100.00)")
if not df_results.empty:
    st.dataframe(
        df_results[["Symbol", "Price", "24h Vol ($M)", "Direction", "5m RSI", "OB Ratio", "Funding %", "Flow Score", "Astro Score", "Total Score", "Astro Note"]],
        use_container_width=True,
        hide_index=True
    )

if scanner_on:
    time.sleep(20)
    st.rerun()
