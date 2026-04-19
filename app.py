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
        # Force auto_adjust to True to simplify the columns
        df = yf.download(ticker, period="100d", interval="1d", progress=False, auto_adjust=True)
        return df

    def detect_fvg(self, df):
        # Check if we have enough data and that the dataframe isn't empty
        if df is None or len(df) < 20: 
            return None
        
        try:
            # Latest 3 candles (excluding current forming candle)
            # Using .iloc[].item() or float() ensures we get a single number, not a Series
            c1 = df.iloc[-4] 
            c2 = df.iloc[-3] 
            c3 = df.iloc[-2] 
            
            c1_high = float(c1['High'])
            c1_low = float(c1['Low'])
            c2_open = float(c2['Open'])
            c2_close = float(c2['Close'])
            c3_low = float(c3['Low'])
            c3_high = float(c3['High'])

            # Logic: Bullish FVG (Gap between Candle 1 High and Candle 3 Low)
            is_bullish = bool(c1_high < c3_low)
            
            # Displacement check (Body of C2 must be large)
            body_size = abs(c2_close - c2_open)
            
            # Calculate ATR safely
            df_diff = df['High'] - df['Low']
            atr_series = df_diff.rolling(14).mean()
            atr = float(atr_series.iloc[-3])
            
            # Use volume safely
            v_ma = df['Volume'].rolling(20).mean().iloc[-3]
            c2_volume = float(c2['Volume'])
            volume_spike = bool(c2_volume > v_ma)

            if is_bullish and body_size > (atr * 1.2):
                return {
                    "type": "BULLISH",
                    "gap_top": c3_low,
                    "gap_bottom": c1_high,
                    "entry": c3_low,
                    "sl": c1_low,
                    "tp": c3_low + ((c3_low - c1_low) * 2), 
                    "volume_spike": volume_spike
                }
        except Exception as e:
            # If a specific ticker has bad data, skip it and continue
            return None
            
        return None

    def score_setup(self, ticker, setup, df):
        score = 0
        if not setup: return 0
        
        try:
            last_close = float(df['Close'].iloc[-1])
            
            # 1. FVG Quality (Size of gap)
            gap_pct = (setup['gap_top'] - setup['gap_bottom']) / setup['gap_bottom']
            score += min(5, gap_pct * 500)
            
            # 2. Volume Spike
            if setup['volume_spike']: score += 5
            
            # 3. Trend Alignment (Above SMA 20)
            sma20 = df['Close'].rolling(20).mean().iloc[-1]
            if last_close > sma20: score += 5
            
            # 4. RR Quality
            risk = setup['entry'] - setup['sl']
            reward = setup['tp'] - setup['entry']
            if risk > 0:
                rr = reward / risk
                if rr >= 2: score += 5
            
            # 5. Liquidity (Average Daily Value > 50 Billion IDR)
            avg_val = (df['Close'] * df['Volume']).rolling(20).mean().iloc[-1]
            if avg_val > 50_000_000_000:
                score += 5
        except:
            return 0
            
        return round(score, 2)

    def find_best_trade(self):
        candidates = []
        for ticker in self.tickers:
            df = self.get_data(ticker)
            if df.empty: continue
            
            setup = self.detect_fvg(df)
            if setup:
                score = self.score_setup(ticker, setup, df)
                candidates.append({"ticker": ticker, "setup": setup, "score": score})
        
        if not candidates: return None
        
        # Return only the single highest score
        best = max(candidates, key=lambda x: x['score'])
        return best if best['score'] >= 15 else None

# --- UI COMPONENTS ---
def render_sidebar():
    st.sidebar.title("🛠 Settings")
    capital = st.sidebar.number_input("Total Capital (IDR)", value=100_000_000, step=1_000_000)
    risk_per_trade = st.sidebar.slider("Risk Per Trade (%)", 0.5, 5.0, 1.0)
    return capital, risk_per_trade

def render_performance(trades_df, equity_df):
    st.header("📈 Performance Analytics")
    col1, col2, col3, col4 = st.columns(4)
    
    if not trades_df.empty:
        win_rate = (len(trades_df[trades_df['pnl'] > 0]) / len(trades_df)) * 100
        total_pnl = trades_df['pnl'].sum()
        
        col1.metric("Total Return", f"IDR {total_pnl:,.0f}")
        col2.metric("Win Rate", f"{win_rate:.1f}%")
        col3.metric("Avg R:R", "1:2.0")
        col4.metric("Trades Executed", len(trades_df))

        # Plot Equity Curve
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=equity_df['date'], y=equity_df['portfolio_value'], name='Portfolio'))
        # Normalize IHSG to starting capital for comparison
        if not equity_df.empty:
            start_cap = equity_df['portfolio_value'].iloc[0]
            ihsg_norm = (equity_df['ihsg_value'] / equity_df['ihsg_value'].iloc[0]) * start_cap
            fig.add_trace(go.Scatter(x=equity_df['date'], y=ihsg_norm, name='IHSG Benchmark', line=dict(dash='dash')))
        
        st.plotly_chart(fig, use_container_width=True)

def detect_fvg(self, df):
        if df is None or len(df) < 20: return None
        try:
            # Check last few candles for an UNFILLED gap
            # We look back 5 days to see if any recent FVG is still "open"
            for i in range(2, 6):
                c1 = df.iloc[-i-2]
                c2 = df.iloc[-i-1] # The big displacement candle
                c3 = df.iloc[-i]
                
                c1_high = float(c1['High'])
                c3_low = float(c3['Low'])
                current_price = float(df['Close'].iloc[-1])

                # Bullish FVG check
                if c1_high < c3_low:
                    body_size = abs(float(c2['Close']) - float(c2['Open']))
                    atr = (df['High'] - df['Low']).rolling(14).mean().iloc[-i-1]
                    
                    if body_size > (atr * 1.2):
                        # Is it a SIGNAL or just a WATCHLIST?
                        # SIGNAL: Price is currently touching or just rejected the gap
                        if current_price <= c3_low and current_price >= c1_high:
                            return {"type": "SIGNAL", "entry": c3_low, "sl": float(c1['Low']), "gap": (c1_high, c3_low)}
                        
                        # WATCHLIST: Gap exists but price is still above it
                        if current_price > c3_low:
                            return {"type": "WATCHLIST", "entry": c3_low, "sl": float(c1['Low']), "gap": (c1_high, c3_low)}
        except:
            return None
        return None

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
                elif score >= 10: # Lower threshold for watchlist
                    watchlist.append(item)
        
        # Best Signal = Pick of the Day
        best_pick = max(signals, key=lambda x: x['score']) if signals else None
        return best_pick, watchlist
        
# --- MAIN APP ---
def main():
    st.title("🎯 Conviction Engine")
    st.subheader("IDX High-Conviction FVG Strategy")
    
    capital, risk_pct = render_sidebar()
    
    # 1. SCANNER SECTION
    if st.button("🔍 Scan Market for Today's Pick"):
        with st.spinner("Analyzing IDX Top 100 for high-quality FVGs..."):
            engine = ConvictionEngine(IDX_TICKERS)
            best_trade = engine.find_best_trade()
            
            if best_trade:
                st.session_state.current_pick = best_trade
            else:
                st.session_state.current_pick = "NO TRADE"

    # 2. TRADE DISPLAY
    if 'current_pick' in st.session_state:
        pick = st.session_state.current_pick
        if pick == "NO TRADE":
            st.warning("No high-conviction setups found today that meet the threshold.")
        else:
            setup = pick['setup']
            ticker = pick['ticker']
            
            # Position Sizing
            risk_amount = capital * (risk_pct / 100)
            sl_dist = setup['entry'] - setup['sl']
            lots = int((risk_amount / sl_dist) / 100) if sl_dist > 0 else 0
            capital_req = lots * 100 * setup['entry']
            
            col1, col2 = st.columns([1, 2])
            with col1:
                st.info(f"### Score: {pick['score']}/25")
                st.write(f"**Ticker:** {ticker}")
                st.write(f"**Action:** BUY LIMIT (FVG Retest)")
                st.write(f"**Entry:** {setup['entry']:,.0f}")
                st.write(f"**Stop Loss:** {setup['sl']:,.0f}")
                st.write(f"**Take Profit:** {setup['tp']:,.0f}")
                
            with col2:
                st.success("### Execution Plan")
                st.write(f"**Position Size:** {lots} Lots")
                st.write(f"**Capital Deployed:** IDR {capital_req:,.0f}")
                st.write(f"**Max Loss:** IDR {risk_amount:,.0f}")
                
                if st.button("📝 Log Trade to Database"):
                    trade_data = {
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "ticker": ticker,
                        "entry_price": setup['entry'],
                        "stop_loss": setup['sl'],
                        "take_profit": setup['tp'],
                        "position_size": lots,
                        "score": pick['score']
                    }
                    supabase.table("trades").insert(trade_data).execute()
                    st.success(f"Logged {ticker} to tracking database!")

                   if st.button("🔍 Run Full Market Scan"):
            with st.spinner("Scanning IDX Universe..."):
            engine = ConvictionEngine(IDX_TICKERS)
            best_pick, watchlist_items = engine.scan_all()
            
            # 1. TOP PICK (The "Conviction" Part)
            st.header("🏆 Today's Conviction Pick")
            if best_pick:
                # ... (Display your existing Trade Card for best_pick) ...
            else:
                st.warning("NO HIGH-CONVICTION TRADE TODAY")

            # 2. WATCHLIST (The "Nearing" Part)
            st.divider()
            st.header("👀 Setup Watchlist")
            st.write("Stocks with valid gaps waiting for a retest:")
            
            if watchlist_items:
                cols = st.columns(3)
                for idx, item in enumerate(watchlist_items[:6]): # Show top 6
                    with cols[idx % 3]:
                        st.markdown(f"""
                        <div style="border:1px solid #444; padding:10px; border-radius:5px">
                            <h4>{item['ticker']}</h4>
                            <p>Score: {item['score']}</p>
                            <p>Buy Zone: {item['setup']['gap'][0]:,.0f} - {item['setup']['gap'][1]:,.0f}</p>
                        </div>
                        """, unsafe_allow_html=True)
            else:
                st.write("No setups currently forming.")     

     

    # 3. HISTORY & PERFORMANCE
    st.divider()
    trades_resp = supabase.table("trades").select("*").order("date", desc=True).execute()
    trades_df = pd.DataFrame(trades_resp.data)
    
    equity_resp = supabase.table("equity_history").select("*").order("date").execute()
    equity_df = pd.DataFrame(equity_resp.data)
    
    tab1, tab2 = st.tabs(["📊 Performance", "📜 Trade History"])
    
    with tab1:
        render_performance(trades_df, equity_df)
        
    with tab2:
        if not trades_df.empty:
            st.dataframe(trades_df[['date', 'ticker', 'entry_price', 'status', 'pnl', 'score']], use_container_width=True)
        else:
            st.write("No trades logged yet.")

    # 4. DAILY MAINTENANCE (Background Update of IHSG)
    if st.sidebar.button("🔄 Sync Benchmark (IHSG)"):
        ihsg = yf.download("^JKSE", period="1d")['Close'].iloc[-1]
        today = datetime.now().strftime("%Y-%m-%d")
        # Logic to update equity_history would go here
        st.sidebar.write(f"IHSG Sync: {ihsg:,.2f}")

if __name__ == "__main__":
    main()
