import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime

# --- 1. SETTINGS & STYLING (Readability Fix) ---
st.set_page_config(page_title="Conviction Engine", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #0d1117; }
    /* Metric Readability */
    [data-testid="stMetricValue"] { color: #00ff88 !important; font-weight: bold; }
    [data-testid="stMetricLabel"] { color: #e1e4e8 !important; }
    
    /* Card Contrast Fix */
    .setup-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 20px;
        color: #f0f6fc;
        margin-bottom: 10px;
    }
    .watchlist-box {
        background-color: #0d1117;
        border: 1px solid #3d444d;
        padding: 15px;
        border-radius: 5px;
        color: #c9d1d9;
    }
    h1, h2, h3, p { color: #f0f6fc !important; }
    </style>
""", unsafe_allow_html=True)

# --- 2. CORE ENGINE LOGIC ---
class ConvictionEngine:
    def __init__(self):
        self.universe = ["BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK", "ADRO.JK", "GOTO.JK", "MDKA.JK"]
        
    @st.cache_data(ttl=3600) # Cache data for 1 hour to save speed
    def get_data(_self, ticker):
        try:
            df = yf.download(ticker, period="60d", interval="1d", progress=False)
            if df.empty: return None
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            return df
        except: return None

    def detect_fvg(_self, df):
        if df is None or len(df) < 15: return None
        # Check last 5 candles
        for i in range(2, 7):
            c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
            if float(c1['High']) < float(c3['Low']): # Bullish FVG
                return {
                    "entry": round(float(c3['Low']), 0),
                    "sl": round(float(c1['Low']), 0),
                    "tp": round(float(c3['Low']) + (float(c3['Low'])-float(c1['Low']))*2, 0),
                    "gap": (float(c1['High']), float(c3['Low'])),
                    "current": float(df['Close'].iloc[-1]),
                    "df_slice": df.iloc[-i-10 : ]
                }
        return None

# --- 3. DATABASE CONNECTION ---
@st.cache_resource
def init_db():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_db()

# --- 4. MAIN APP ---
def main():
    st.title("🎯 Conviction Engine")
    
    # Sidebar Setup
    with st.sidebar:
        st.header("Portfolio Config")
        capital = st.number_input("Total Capital (IDR)", value=100000000, step=1000000)
        risk_pct = st.slider("Risk per Trade (%)", 0.5, 3.0, 1.0)
        st.divider()
        st.write("Targeting LQ45 Institutional Flow")

    # Metrics Row
    m1, m2, m3 = st.columns(3)
    m1.metric("Market", "IDX", "Active")
    m2.metric("Strategy", "FVG Retest", "Bullish")
    m3.metric("Universe", "LQ45 Core", "Liquid")

    engine = ConvictionEngine()

    if st.button("🚀 SCAN FOR HIGH-CONVICTION TRADES"):
        signals = []
        watchlist = []
        
        with st.spinner("Scanning Institutional Flow..."):
            for ticker in engine.universe:
                df = engine.get_data(ticker)
                setup = engine.detect_fvg(df)
                if setup:
                    setup['ticker'] = ticker
                    # If price is near the FVG zone, it's a signal
                    if setup['current'] <= setup['entry'] * 1.02:
                        signals.append(setup)
                    else:
                        watchlist.append(setup)

        if signals:
            st.subheader("🏆 Primary Signal")
            best = signals[0] # Take first for MVP pick
            
            # Position Sizing
            risk_amt = capital * (risk_pct / 100)
            sl_points = best['entry'] - best['sl']
            lots = int((risk_amt / sl_points) / 100) if sl_points > 0 else 0
            
            col_chart, col_info = st.columns([2, 1])
            
            with col_chart:
                # Plotly Chart
                df_plot = best['df_slice']
                fig = go.Figure(data=[go.Candlestick(x=df_plot.index, open=df_plot['Open'], high=df_plot['High'], low=df_plot['Low'], close=df_plot['Close'])])
                fig.add_shape(type="rect", x0=df_plot.index[0], x1=df_plot.index[-1], y0=best['gap'][0], y1=best['gap'][1], fillcolor="LightGreen", opacity=0.3, layer="below", line_width=0)
                fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
                
            with col_info:
                st.markdown(f"""
                <div class="setup-card">
                    <h3>{best['ticker']}</h3>
                    <p><b>Entry:</b> {best['entry']:,.0f}</p>
                    <p><b>Stop Loss:</b> {best['sl']:,.0f}</p>
                    <p><b>Take Profit:</b> {best['tp']:,.0f}</p>
                    <hr style='border: 0.5px solid #30363d;'>
                    <p style='color:#00ff88'><b>Position: {lots} Lots</b></p>
                    <small>Risk: IDR {risk_amt:,.0f}</small>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button("📝 LOG THIS TRADE"):
                    data = {"ticker": best['ticker'], "entry_price": best['entry'], "stop_loss": best['sl'], "take_profit": best['tp'], "position_size": lots, "date": datetime.now().strftime("%Y-%m-%d"), "status": "OPEN"}
                    supabase.table("trades").insert(data).execute()
                    st.success("Trade Logged Successfully!")

        # Watchlist Section
        st.divider()
        st.subheader("👀 Watchlist (Nearing Zones)")
        if watchlist:
            w_cols = st.columns(3)
            for i, w in enumerate(watchlist[:3]):
                with w_cols[i]:
                    st.markdown(f"""
                    <div class="watchlist-box">
                        <b>{w['ticker']}</b><br>
                        Wait for: {w['entry']:,.0f}<br>
                        <small>Current: {w['current']:,.0f}</small>
                    </div>
                    """, unsafe_allow_html=True)

    # Performance Tabs
    st.divider()
    t1, t2 = st.tabs(["📊 Performance", "📜 Trade History"])
    with t1:
        st.write("Equity Curve Tracking (Supabase Integration)")
    with t2:
        try:
            history = supabase.table("trades").select("*").order("date", desc=True).execute()
            st.dataframe(pd.DataFrame(history.data), use_container_width=True)
        except:
            st.info("Log a trade to see history.")

if __name__ == "__main__":
    main()
