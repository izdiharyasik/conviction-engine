import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np

# --- CONFIGURATION & STYLING ---
st.set_page_config(page_title="Conviction Engine", layout="wide")
st.markdown("""
    <style>
    .metric-card { background-color: #1e2130; padding: 20px; border-radius: 10px; border: 1px solid #3e4251; }
    .stButton>button { width: 100%; border-radius: 5px; height: 3em; background-color: #007bff; color: white; }
    </style>
""", unsafe_allow_html=True)

# --- DATABASE CONNECTION ---
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(URL, KEY)

# --- IDX UNIVERSE (Sample of high-cap tickers) ---
# In production, this would be fetched from an API or updated weekly
IDX_TICKERS = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK", 
    "BYAN.JK", "AMRT.JK", "BBNI.JK", "ICBP.JK", "GOTO.JK",
    "UNTR.JK", "KLBF.JK", "PGAS.JK", "ADRO.JK", "CPIN.JK"
]

# --- CORE LOGIC: SCANNER & SCORING ---
class ConvictionEngine:
    def __init__(self, tickers):
        self.tickers = tickers

    def get_data(self, ticker):
        try:
            df = yf.download(ticker, period="100d", interval="1d", progress=False, auto_adjust=True)
            return df
        except:
            return pd.DataFrame()

    def detect_fvg(self, df):
        if df is None or len(df) < 20: 
            return None
        try:
            # We look back over the last 5 candles to find the most recent valid FVG
            for i in range(2, 7):
                c1 = df.iloc[-i-2]
                c2 = df.iloc[-i-1] 
                c3 = df.iloc[-i]
                
                c1_high = float(c1['High'])
                c1_low = float(c1['Low'])
                c3_low = float(c3['Low'])
                current_price = float(df['Close'].iloc[-1])

                # Bullish FVG Pattern
                if c1_high < c3_low:
                    body_size = abs(float(c2['Close']) - float(c2['Open']))
                    # Safe ATR calculation
                    atr = (df['High'] - df['Low']).rolling(14).mean().iloc[-i-1]
                    
                    if body_size > (atr * 1.2):
                        # Calculate Score within detection to help filtering
                        # SIGNAL: Price is currently inside the gap
                        if current_price <= c3_low and current_price >= c1_high:
                            return {
                                "type": "SIGNAL", 
                                "entry": c3_low, 
                                "sl": c1_low, 
                                "tp": c3_low + ((c3_low - c1_low) * 2),
                                "gap": (c1_high, c3_low),
                                "volume_spike": bool(float(c2['Volume']) > df['Volume'].rolling(20).mean().iloc[-i-1])
                            }
                        
                        # WATCHLIST: Gap exists but price is still above it
                        if current_price > c3_low:
                            return {
                                "type": "WATCHLIST", 
                                "entry": c3_low, 
                                "sl": c1_low, 
                                "tp": c3_low + ((c3_low - c1_low) * 2),
                                "gap": (c1_high, c3_low),
                                "volume_spike": bool(float(c2['Volume']) > df['Volume'].rolling(20).mean().iloc[-i-1])
                            }
            return None
        except:
            return None

    def score_setup(self, ticker, setup, df):
        if not setup: return 0
        score = 0
        try:
            # 1. Volume Spike
            if setup.get('volume_spike'): score += 5
            # 2. Trend (Price > SMA20)
            if float(df['Close'].iloc[-1]) > df['Close'].rolling(20).mean().iloc[-1]: score += 5
            # 3. Gap Width
            gap_pct = (setup['gap'][1] - setup['gap'][0]) / setup['gap'][0]
            score += min(5, gap_pct * 500)
            # 4. Liquidity
            avg_val = (df['Close'] * df['Volume']).rolling(20).mean().iloc[-1]
            if avg_val > 50_000_000_000: score += 10
        except:
            pass
        return round(score, 2)

    def scan_all(self):
        signals = []
        watchlist = []
        for ticker in self.tickers:
            df = self.get_data(ticker)
            if df.empty: continue
            setup = self.detect_fvg(df)
            if setup:
                score = self.score_setup(ticker, setup, df)
                item = {"ticker": ticker, "setup": setup, "score": score}
                if setup['type'] == "SIGNAL" and score >= 15:
                    signals.append(item)
                elif score >= 10:
                    watchlist.append(item)
        
        best_pick = max(signals, key=lambda x: x['score']) if signals else None
        return best_pick, watchlist

def main():
    st.title("🎯 Conviction Engine")
    st.subheader("IDX High-Conviction FVG Strategy")
    
    capital, risk_pct = render_sidebar()
    
    if st.button("🔍 Run Full Market Scan"):
        with st.spinner("Analyzing IDX Top Tickers..."):
            engine = ConvictionEngine(IDX_TICKERS)
            best_pick, watchlist_items = engine.scan_all()
            
            st.session_state.best_pick = best_pick
            st.session_state.watchlist = watchlist_items

    # --- 1. DISPLAY CONVICTION PICK ---
    if 'best_pick' in st.session_state:
        st.header("🏆 Today's Conviction Pick")
        pick = st.session_state.best_pick
        if pick:
            setup = pick['setup']
            ticker = pick['ticker']
            
            # Position Sizing
            risk_amount = capital * (risk_pct / 100)
            sl_dist = setup['entry'] - setup['sl']
            lots = int((risk_amount / sl_dist) / 100) if sl_dist > 0 else 0
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Conviction Score", f"{pick['score']}/25")
                st.write(f"**Ticker:** {ticker}")
                st.write(f"**Entry Zone:** {setup['entry']:,.0f}")
                st.write(f"**Stop Loss:** {setup['sl']:,.0f}")
            with col2:
                st.write(f"**Target Lots:** {lots}")
                if st.button("📝 Log This Trade"):
                    trade_data = {"date": datetime.now().strftime("%Y-%m-%d"), "ticker": ticker, "entry_price": setup['entry'], "stop_loss": setup['sl'], "take_profit": setup['tp'], "position_size": lots, "score": pick['score']}
                    supabase.table("trades").insert(trade_data).execute()
                    st.success("Trade Logged!")
        else:
            st.warning("No high-conviction signals right now. Check the watchlist below.")

    # --- 2. DISPLAY WATCHLIST ---
    if 'watchlist' in st.session_state:
        st.divider()
        st.header("👀 Setup Watchlist")
        st.write("Quality FVGs waiting for price to retrace into the zone:")
        
        items = st.session_state.watchlist
        if items:
            cols = st.columns(3)
            for idx, item in enumerate(items[:6]):
                with cols[idx % 3]:
                    st.info(f"**{item['ticker']}**")
                    st.write(f"Score: {item['score']}")
                    st.write(f"Wait for: {item['setup']['gap'][0]:,.0f}")
        else:
            st.write("Watchlist is empty. Market is quiet.")

    # --- 3. HISTORY & DASHBOARD --
    st.divider()
    trades_resp = supabase.table("trades").select("*").order("date", desc=True).execute()
    trades_df = pd.DataFrame(trades_resp.data)
    equity_resp = supabase.table("equity_history").select("*").order("date").execute()
    equity_df = pd.DataFrame(equity_resp.data)
    
    t1, t2 = st.tabs(["📊 Analytics", "📜 History"])
    with t1: render_performance(trades_df, equity_df)
    with t2: st.dataframe(trades_df, use_container_width=True)

if __name__ == "__main__":
    main()

