import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime
import numpy as np

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Conviction Engine Pro", layout="wide")

# Database Connection
try:
    URL = st.secrets["SUPABASE_URL"]
    KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(URL, KEY)
except:
    st.error("Database Keys Missing in Streamlit Secrets!")

# Curated IDX Universe (Focus on high liquidity)
IDX_TICKERS = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK", 
    "BYAN.JK", "AMRT.JK", "BBNI.JK", "ICBP.JK", "GOTO.JK",
    "UNTR.JK", "KLBF.JK", "PGAS.JK", "ADRO.JK", "CPIN.JK"
]

# --- 2. THE ENGINE LOGIC ---
class ConvictionEngine:
    def __init__(self, tickers):
        self.tickers = tickers

    def get_data(self, ticker, period="100d"):
        try:
            # We use 'auto_adjust=False' because '.JK' tickers sometimes fail with it
            df = yf.download(ticker, period=period, interval="1d", progress=False)
            if df.empty: return pd.DataFrame()
            # Standardize column names (fixes the "Adj Close" vs "Close" issue)
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            return df
        except Exception as e:
            return pd.DataFrame()

    def detect_fvg(self, df):
        if df.empty or len(df) < 20: return None
        try:
            # We look back through the last 10 candles to find ANY open gap
            for i in range(2, 12):
                c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
                c1_high, c1_low = float(c1['High']), float(c1['Low'])
                c2_open, c2_close = float(c2['Open']), float(c2['Close'])
                c3_low, c3_high = float(c3['Low']), float(c3['High'])
                current_price = float(df['Close'].iloc[-1])

                # Bullish FVG (Gaps are often smaller in IDX, so we remove the 1.2x ATR requirement for now)
                if c1_high < c3_low:
                    body_size = abs(c2_close - c2_open)
                    avg_body = abs(df['Close'] - df['Open']).rolling(14).mean().iloc[-i-1]
                    
                    # We only care if the displacement candle is bigger than average
                    if body_size > avg_body:
                        setup = {
                            "ticker": "", "entry": c3_low, "sl": c1_low, 
                            "tp": c3_low + ((c3_low - c1_low) * 1.5), # Lowered RR for IDX reality
                            "gap": (c1_high, c3_low),
                            "volume_spike": bool(float(c2['Volume']) > df['Volume'].rolling(20).mean().iloc[-i-1])
                        }
                        # If price is CURRENTLY in or near the gap
                        if current_price <= (c3_low * 1.01) and current_price >= (c1_high * 0.99):
                            setup["type"] = "SIGNAL"
                            return setup
                        elif current_price > c3_low:
                            setup["type"] = "WATCHLIST"
                            return setup
            return None
        except:
            return None

    def score_setup(self, ticker, setup, df):
        score = 10 # Base score
        if setup.get('volume_spike'): score += 5
        if float(df['Close'].iloc[-1]) > df['Close'].rolling(20).mean().iloc[-1]: score += 5
        # Liquidity check
        avg_val = (df['Close'] * df['Volume']).rolling(10).mean().iloc[-1]
        if avg_val > 10_000_000_000: score += 5 # 10 Bio IDR
        return score

# --- 3. UI FUNCTIONS ---
def main():
    st.title("🎯 Conviction Engine")
    
    # Sidebar Setup
    st.sidebar.header("Parameters")
    cap = st.sidebar.number_input("Capital", 100_000_000)
    risk = st.sidebar.slider("Risk %", 0.5, 2.0, 1.0)
    
    engine = ConvictionEngine(IDX_TICKERS)
    
    tab1, tab2, tab3 = st.tabs(["🔍 Live Scanner", "🧪 Backtest", "🛠 Diagnostics"])

    with tab3:
        st.subheader("Data Health Check")
        if st.button("Check Connectivity"):
            test_df = engine.get_data("BBCA.JK", period="5d")
            if not test_df.empty:
                st.success("Yahoo Finance Connection: OK ✅")
                st.write("Recent BBCA Data:", test_df.tail(3))
            else:
                st.error("Yahoo Finance Connection: FAILED ❌. This is why you see no picks.")

    with tab1:
        if st.button("Run Scanner"):
            results = []
            watchlist = []
            progress = st.progress(0)
            
            for idx, t in enumerate(IDX_TICKERS):
                df = engine.get_data(t)
                setup = engine.detect_fvg(df)
                if setup:
                    setup['ticker'] = t
                    score = engine.score_setup(t, setup, df)
                    if setup['type'] == "SIGNAL" and score >= 15:
                        results.append({"ticker": t, "setup": setup, "score": score})
                    else:
                        watchlist.append({"ticker": t, "setup": setup, "score": score})
                progress.progress((idx + 1) / len(IDX_TICKERS))
            
            if results:
                best = max(results, key=lambda x: x['score'])
                st.success(f"TOP PICK: {best['ticker']}")
                # Render Trade Card logic...
                st.json(best)
            else:
                st.warning("No 'Buy Now' Signals. Checking Watchlist...")
                if watchlist:
                    st.write("Current Watchlist (Stocks waiting for retest):")
                    st.table(pd.DataFrame([{"Ticker": w['ticker'], "Score": w['score'], "Zone": f"{w['setup']['gap'][0]:,.0f}-{w['setup']['gap'][1]:,.0f}"} for w in watchlist]))

    with tab2:
        st.write("Historical backtest logic here...")
        # (Insert your backtest function from previous message here)

if __name__ == "__main__":
    main()
