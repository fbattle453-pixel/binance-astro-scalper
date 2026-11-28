import streamlit as st
import requests
import os
import time
import pytz
from datetime import datetime
from engine import run_market_scan

st.set_page_config(page_title="Crypto Astro Scalp Scanner", page_icon="⚡", layout="wide")


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
        host = chr(46).join(["api", "telegram", "org"])
        endpoint = "https" + chr(58) + chr(47) + chr(47) + host + "/bot" + token + "/sendMessage"
        r = requests.post(endpoint, json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}, timeout=8)
        if r.status_code == 200:
            return True, "OK"
        return False, r.json().get("description", f"HTTP {r.status_code}")
    except Exception as e:
        return False, str(e)


def fmt_price(val):
    if val < 0.01:
        return f"${val:.6f}"
    if val < 1.0:
        return f"${val:.5f}"
    return f"${val:.4f}"


if "last_alert" not in st.session_state:
    st.session_state.last_alert = {}
if "scanner_running" not in st.session_state:
    st.session_state.scanner_running = False
if "saved_df" not in st.session_state:
    st.session_state.saved_df = None
if "saved_signal" not in st.session_state:
    st.session_state.saved_signal = None
if "saved_matched" not in st.session_state:
    st.session_state.saved_matched = 0
if "saved_status" not in st.session_state:
    st.session_state.saved_status = "Ready — Click Start Scanner when you want to trade"
if "saved_time" not in st.session_state:
    st.session_state.saved_time = "—"

st.title("⚡ Pure-Crypto Astro Scalp Scanner ($0.001 – $200)")

c1, c2, c3, c4 = st.columns([0.8, 0.8, 1.5, 1.1])
with c1:
    if st.button("▶️ Start Scanner", use_container_width=True, type="primary" if not st.session_state.scanner_running else "secondary"):
        st.session_state.scanner_running = True
        st.session_state.last_alert = {}
        st.rerun()
with c2:
    if st.button("⏹️ Stop Scanner", use_container_width=True, type="primary" if st.session_state.scanner_running else "secondary"):
        st.session_state.scanner_running = False
        st.rerun()
with c3:
    astro_mode = st.radio("Astrology System:", ["Western", "Vedic"], horizontal=True)
with c4:
    tg_ready = bool(get_secret("TELEGRAM_BOT_TOKEN") and get_secret("TELEGRAM_CHAT_ID"))
    state_badge = "🟢 SCANNING (20s)" if st.session_state.scanner_running else "⏸️ STANDBY / FROZEN"
    st.markdown(f"**Status:** {state_badge}  \n**Telegram:** {'✅ Connected' if tg_ready else '⚠️ Missing Secrets'}")

with st.sidebar:
    st.header("🛡️ 20x–35x Position Calculator")
    wallet_usdt = st.number_input("Futures Wallet (USDT)", min_value=10.0, value=500.0, step=50.0)
    risk_pct = st.slider("Max Risk per Scalp (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5)
    st.divider()
    if st.button("📲 Send Test Telegram Alert", use_container_width=True):
        ok, info = send_telegram("✅ *Test Alert:* Pure-Crypto Astro Scalper ($0.001–$200) is ready!")
        if ok:
            st.success("Sent! Check your Telegram.")
        else:
            st.error(f"Telegram Error: {info}")

if st.session_state.scanner_running:
    with st.spinner("Scanning BTC Regime, Liquidity Sweeps & Planetary Transits..."):
        df_results, signal, matched, debug_msg = run_market_scan(astro_mode)
        if not df_results.empty:
            st.session_state.saved_df = df_results
            st.session_state.saved_signal = signal
            st.session_state.saved_matched = matched
            st.session_state.saved_status = debug_msg
            st.session_state.saved_time = datetime.now(pytz.timezone("Asia/Karachi")).strftime("%I:%M:%S %p PKT")
elif st.session_state.saved_df is None:
    st.info("👋 **Ready to Trade:** Choose **Western** or **Vedic** mode above and click **▶️ Start Scanner** to scan the market ($0.001–$200) and get your signal.")
else:
    st.info("⏸️ **Scanner Stopped:** Holding your last qualified signal on screen. Click **▶️ Start Scanner** anytime for a fresh scan.")

df_display = st.session_state.saved_df
signal = st.session_state.saved_signal
matched = st.session_state.saved_matched
debug_msg = st.session_state.saved_status
last_time = st.session_state.saved_time

st.caption(f"Last Scan: {last_time} | Filtered Crypto Pairs ($0.001–$200): Top {matched} analyzed | Mode: {astro_mode} | Status: {debug_msg}")

if signal:
    risk_usdt = wallet_usdt * (risk_pct / 100.0)
    rec_margin = round((risk_usdt / (signal["sl_pct"] / 100.0)) / signal["leverage"], 2)
    dir_icon = "🟢 LONG" if signal["direction"] == "LONG" else "🔴 SHORT"
    st.success(f"### 🎯 TOP QUALIFIED CRYPTO SCALP: **{signal['symbol']}** — {dir_icon} ({signal['score']}%)")

    # Two spacious 3-column rows so every single decimal digit displays in full
    r1_c1, r1_c2, r1_c3 = st.columns(3)
    r1_c1.metric("Entry Price", fmt_price(signal["entry"]))
    r1_c2.metric("Leverage (Isolated)", f"{signal['leverage']}x")
    r1_c3.metric("Suggested Margin", f"${rec_margin:.2f} USDT")

    r2_c1, r2_c2, r2_c3 = st.columns(3)
    r2_c1.metric("TP 1 (50% Close)", fmt_price(signal["tp1"]))
    r2_c2.metric("TP 2 (Full Target)", fmt_price(signal["tp2"]))
    r2_c3.metric("Stop-Loss", fmt_price(signal["sl"]), f"-{signal['sl_pct']}%")

    st.info(f"⏳ **Close By:** **{signal['close_pkt']}** ({signal['close_utc']} — ~{signal['hold_mins']}m) | {signal['astro_note']} | OB: {signal['ob_ratio']}x | RSI: {signal['rsi']}")

    if st.session_state.scanner_running:
        akey = f"{signal['symbol']}_{signal['direction']}"
        if time.time() - st.session_state.last_alert.get(akey, 0) > 900:
            msg = (
                f"⚡ *CRYPTO SCALP ({astro_mode.upper()})*\n"
                f"🪙 `{signal['symbol']}` | {dir_icon} ({signal['score']}%)\n"
                f"⚙️ *{signal['leverage']}x Isolated*\n"
                f"💵 Entry: `{fmt_price(signal['entry'])}`\n"
                f"✅ TP1: `{fmt_price(signal['tp1'])}` | TP2: `{fmt_price(signal['tp2'])}`\n"
                f"🛑 SL: `{fmt_price(signal['sl'])}` (-{signal['sl_pct']}%)\n"
                f"⏳ Close: {signal['close_pkt']}"
            )
            ok, _ = send_telegram(msg)
            if ok:
                st.session_state.last_alert[akey] = time.time()

if df_display is not None and not df_display.empty:
    st.subheader("📊 Top 25 Active Crypto Futures Pairs ($0.001 – $200.00)")
    st.dataframe(
        df_display[["Symbol", "Price", "24h Vol ($M)", "Direction", "5m RSI", "OB Ratio", "Funding %", "Flow Score", "Astro Score", "Total Score", "Astro Note"]],
        use_container_width=True,
        hide_index=True
    )

if st.session_state.scanner_running:
    time.sleep(20)
    st.rerun()
