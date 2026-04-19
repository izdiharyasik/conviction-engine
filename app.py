import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime
import numpy as np

# --- 1. CONFIGURATION & SECRETS ---
st.set_page_config(page_title="Conviction Engine v2", layout="wide")

try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(URL, KEY)
except Exception as e:
    st.error("Database Connection Error. Check Secrets.")

# Dynamic Universe: Top 80+ most active IDX stocks
# This covers LQ45 and Kompas100, filtering out the "trash" automatically later.
IDX_UNIVERSE = [
    "ADRO.JK", "AKRA.JK", "AMRT.JK", "ANTM.JK", "ASII.JK", "BBCA.JK", "BBNI.JK", "BBRI.JK",
    "BBTN.JK", "BMRI.JK", "BRIS.JK", "BRMS.JK", "BUKA.JK", "CPIN.JK", "DEWA.JK", "EXCL.JK",
    "GOTO.JK", "HRUM.JK", "ICBP.JK", "INCO.JK", "INDF.JK", "INKP.JK", "INTP.JK", "ITMG.JK",
    "JSMR.JK", "KLBF.JK", "MDKA.JK", "MEDC.JK", "MIKA.JK", "PGAS.JK", "PTBA.JK", "PTPP.JK",
    "SIDO.JK", "SMGR.JK", "TINS.JK", "TLKM.JK", "TOWR.JK", "UNTR.JK", "UNVR.JK", "VALE.JK",
    "ADMR.JK", "AVIA.JK", "BELI.JK", "ESSA.JK", "HEAL.JK", "MBMA.JK", "MTEL.JK", "NCKL.JK",
    "PERT.JK", "TMAS.JK", "ACES.JK", "AUTO.JK", "BSDE.JK", "CTRA.JK", "ERAA.JK", "IMAS.JK",
    "MYOR.JK", "PWON.JK", "SCMA.JK", "SMRA.JK", "TKIM.JK", "TPIA.JK", "TSET.JK", "WIKA.JK"
]

# --- 2. CORE ENGINE ---
class ConvictionEngine:
    def __init__(self):
        self.min_liquidity = 10_000_000_000  # IDR 10 Billion minimum daily turnover
        self.min_price = 100                 # Avoid "Penny Stocks" (Gorengan under 100)

    def get_data(self, ticker):
        try:
            # Fetch 100 days to calculate 20-day averages
            df = yf.download(ticker, period="100d", interval="1d", progress=False)
            if df.empty: return None
            # Standardize MultiIndex columns from YFinance
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            return df
        except:
            return None

    def is_gorengan(self, ticker, df):
        """ The Gorengan Killer Logic """
        last_close = float(df['Close'].iloc[-1])
        # Rule 1: Price must be above 100
        if last_close < self.min_price:
            return True, f"Price too low ({last_close})"
        
        # Rule 2: Average Daily Turnover must be > 10 Billion IDR
        # Traded Value = Price * Volume
        daily_turnover = (df['Close'] * df['Volume']).rolling(20).mean().iloc[-1]
        if daily_turnover < self.min_liquidity:
            return True, f"Liquidity too low (IDR {daily_turnover/1e9:.1f}B)"
        
        return False, "Liquid"

    def detect_fvg(self, df):
        if len(df) < 20: return None
        try:
            # Look back through recent history for an unfilled gap
            for i in range(2, 8):
                c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
                c1_high, c1_low = float(c1['High']), float(c1['Low'])
                c2_open, c2_close = float(c2['Open']), float(c2['Close'])
                c3_low, c3_high = float(c3['Low']), float(c3['High'])
                current_price = float(df['Close'].iloc[-1])

                # Bullish FVG check
                if c1_high < c3_low:
                    body_size = abs(c2_close - c2_open)
                    avg_body = abs(df['Close'] - df['Open']).rolling(14).mean().iloc[-i-1]
                    
                    if body_size > (avg_body * 1.5): # Strong displacement
                        setup = {
                            "entry": c3_low, "sl": c1_low, 
                            "tp": c3_low + ((c3_low - c1_low) * 2),
                            "gap_zone": (c1_high, c3_low),
                            "v_spike": bool(float(c2['Volume']) > df['Volume'].rolling(20).mean().iloc[-i-1])
                        }
                        # Determine if it's an immediate trade or watchlist
                        if current_price <= (c3_low * 1.005) and current_price >= (c1_high * 0.995):
                            setup["type"] = "SIGNAL"
                        elif current_price > c3_low:
                            setup["type"] = "WATCHLIST"
                        else:
                            continue
                        return setup
            return None
        except:
            return None

    def score(self, setup, df):
        s = 10
        if setup['v_spike']: s += 5
        if float(df['Close'].iloc[-1]) > df['Close'].rolling(20).mean().iloc[-1]: s += 5
        # Higher liquidity gets higher conviction score
        turnover = (df['Close'] * df['Volume']).rolling(20).mean().iloc[-1]
        if turnover > 50_000_000_000: s += 5 # Massive liquidity bonus
        return s

# --- 3. UI LAYOUT ---
def main():
    st.title("🎯 Conviction Engine")
    st.caption("Auto-Filtering 80+ IDX Stocks | Liquid & Institutional Only")
    
    # Capital Settings
    st.sidebar.header("Risk Management")
    capital = st.sidebar.number_input("Capital (IDR)", 100_000_000, step=10_000_000)
    risk_pct = st.sidebar.slider("Risk per Trade (%)", 0.5, 2.0, 1.0)

    engine = ConvictionEngine()
    
    if st.button("🔍 Scan All Liquid Stocks"):
        signals, watchlist, gorengan_count = [], [], 0
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, ticker in enumerate(IDX_UNIVERSE):
            status_text.text(f"Scanning {ticker}...")
            df = engine.get_data(ticker)
            if df is not None:
                # 1. APPLY GORENGAN KILLER
                is_trash, reason = engine.is_gorengan(ticker, df)
                if is_trash:
                    gorengan_count += 1
                    continue
                
                # 2. DETECT PATTERN
                setup = engine.detect_fvg(df)
                if setup:
                    setup['score'] = engine.score(setup, df)
                    item = {"ticker": ticker, "setup": setup}
                    if setup['type'] == "SIGNAL" and setup['score'] >= 15:
                        signals.append(item)
                    else:
                        watchlist.append(item)
            
            progress_bar.progress((idx + 1) / len(IDX_UNIVERSE))
        
        status_text.empty()
        
        # DISPLAY RESULTS
        st.sidebar.write(f"✅ Scanned: {len(IDX_UNIVERSE)}")
        st.sidebar.write(f"🚫 Gorengan Filtered: {gorengan_count}")

        # --- 1. Top Pick ---
        st.header("🏆 High-Conviction Signal")
        if signals:
            best = max(signals, key=lambda x: x['setup']['score'])
            s = best['setup']
            
            risk_amt = capital * (risk_pct / 100)
            lots = int((risk_amt / (s['entry'] - s['sl'])) / 100) if (s['entry'] - s['sl']) > 0 else 0
            
            c1, c2, c3 = st.columns([1,1,1])
            with c1:
                st.metric(best['ticker'], f"Score: {s['score']}/25")
            with c2:
                st.write(f"**Action:** BUY LIMIT")
                st.write(f"**Entry:** {s['entry']:,.0f}")
                st.write(f"**Stop Loss:** {s['sl']:,.0f}")
            with c3:
                st.write(f"**Position Size:** {lots} Lots")
                if st.button("📝 Log Trade"):
                    supabase.table("trades").insert({"date": datetime.now().strftime("%Y-%m-%d"), "ticker": best['ticker'], "entry_price": s['entry'], "stop_loss": s['sl'], "take_profit": s['tp'], "position_size": lots, "score": s['score']}).execute()
                    st.success("Trade stored.")
        else:
            st.warning("No high-conviction signals found. Market is currently consolidated.")

        # --- 2. Watchlist ---
        st.divider()
        st.header("👀 Watchlist (Nearing Zone)")
        if watchlist:
            sorted_watch = sorted(watchlist, key=lambda x: x['setup']['score'], reverse=True)
            cols = st.columns(3)
            for i, item in enumerate(sorted_watch[:6]):
                with cols[i % 3]:
                    st.info(f"**{item['ticker']}**\n\nScore: {item['setup']['score']}\n\nZone: {item['setup']['gap_zone'][0]:,.0f} - {item['setup']['gap_zone'][1]:,.0f}")

    # --- 3. DATABASE TABS ---
    st.divider()
    try:
        trades_resp = supabase.table("trades").select("*").order("date", desc=True).execute()
        t1, t2 = st.tabs(["📜 Trade History", "📈 Backtest (Last 60d)"])
        with t1:
            st.dataframe(pd.DataFrame(trades_resp.data), width="stretch")
        with t2:
            st.info("Click the button above to run the live scan first.")
    except:
        st.write("Connect Supabase to see history.")

if __name__ == "__main__":
    main()
