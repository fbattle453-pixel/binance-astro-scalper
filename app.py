import streamlit as st
import requests
import os
import time
import pytz
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
        host = ".".join(["api", "telegram", "org"])
        endpoint = "https://" + host + "/bot" + token + "/sendMessage"
        r = requests.post(endpoint, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=8)
        if r.status_code == 200:
            return True, "OK"
        return False, r.json().get("description", f"HTTP {r.status_code}")
    except Exception as e:
        return False, str(e)


# Initialize persistent session state so stopping keeps the last signal visible
if "last_alert" not in st.session_state:
    st.session_state.last_alert = {}
if "scanner_running" not in st.session_state:
    st.session_state.scanner_running = True
if "saved_df" not in st.session_state:
    st.session_state.saved_df = None
if "saved_signal" not in st.session_state:
    st.session_state.saved_signal = None
if "saved_matched" not in st.session_state:
    st.session_state.saved_matched = 0
if "saved_status" not in st.session_state:
    st.session_state.saved_status = "Waiting for first scan..."
if "saved_time" not in st.session_state:
    st.session_state.saved_time = "—"

st.title("⚡ Futures Market-Wide Astro Scalper ($0.10 – $100)")

# Top Control Bar with dedicated Start / Stop buttons
c1, c2, c3, c4 = st.columns([0.8, 0.8, 1.5, 1.1])
with c1:
    if st.button("▶️ Start Scanner", use_container_width=True, type="primary" if not st.session_state.scanner_running else "secondary"):
        st.session_state.scanner_running = True
        st.rerun()
with c2:
    if st.button("⏹️ Stop Scanner", use_container_width=True, type="primary" if st.session_state.scanner_running else "secondary"):
        st.session_state.scanner_running = False
        st.rerun()
with c3:
    astro_mode = st.radio("Astrology System:", ["Western", "Vedic"], horizontal=True)
with c4:
    tg_ready = bool(get_secret("TELEGRAM_BOT_TOKEN") and get_secret("TELEGRAM_CHAT_ID"))
    state_badge = "🟢 RUNNING (20s)" if st.session_state.scanner_running else "⏸️ PAUSED (FROZEN)"
    st.markdown(f"**Status:** {state_badge}  \n**Telegram:** {'✅ Connected' if tg_ready else '⚠️ Missing Secrets'}")

# Sidebar Position Calculator & Test Alert
with st.sidebar:
    st.header("🛡️ 20x–50x Position Calculator")
    wallet_usdt = st.number_input("Futures Wallet (USDT)", min_value=10.0, value=500.0, step=50.0)
    risk_pct = st.slider("Max Risk per Scalp (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5)
    st.divider()
    if st.button("📲 Send Test Telegram Alert", use_container_width=True):
        ok, info = send_telegram("✅ *Test Alert:* Futures Astro Scalper is connected!")
        if ok:
            st.success("Sent! Check your Telegram.")
        else:
            st.error(f"Telegram Error: {info}")

# Run live scan ONLY when scanner_running is True (or if no scan has ever run yet)
if st.session_state.scanner_running or st.session_state.saved_df is None:
    with st.spinner("Scanning Futures Order Books & Planetary Transits..."):
        df_results, signal, matched, debug_msg = run_market_scan(astro_mode)
        # Only overwrite saved state if the scan returned valid data
        if not df_results.empty:
            st.session_state.saved_df = df_results
            st.session_state.saved_signal = signal
            st.session_state.saved_matched = matched
            st.session_state.saved_status = debug_msg
            st.session_state.saved_time = datetime.now(pytz.timezone("Asia/Karachi")).strftime("%I:%M:%S %p PKT")
else:
    st.info("⏸️ **Scanner Stopped:** Holding last qualified signal on screen. Click **▶️ Start Scanner** above to resume live market scanning.")

# Render from saved session state so screen NEVER blanks out when stopped
df_display = st.session_state.saved_df
signal = st.session_state.saved_signal
matched = st.session_state.saved_matched
debug_msg = st.session_state.saved_status
last_time = st.session_state.saved_time

st.caption(f"Last Scan: {last_time} | Filtered Pairs ($0.10–$100): Top {matched} analyzed | Mode: {astro_mode} | Status: {debug_msg}")

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

    # Send Telegram alert only while scanner is actively running
    if st.session_state.scanner_running:
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
    st.warning("🔍 **NO QUALIFIED SCALP (>=60%) — SCANNING ORDER BOOKS ($0.10–$100)**")

st.subheader("📊 Top 25 Active Futures Pairs ($0.10 – $100.00)")
if df_display is not None and not df_display.empty:
    st.dataframe(
        df_display[["Symbol", "Price", "24h Vol ($M)", "Direction", "5m RSI", "OB Ratio", "Funding %", "Flow Score", "Astro Score", "Total Score", "Astro Note"]],
        use_container_width=True,
        hide_index=True
    )

if st.session_state.scanner_running:
    time.sleep(20)
    st.rerun()
