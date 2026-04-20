import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime

# --- 1. THEME & UI FIXES ---
st.set_page_config(page_title="Conviction Engine", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #050505 !important; }
    h1, h2, h3, p, span, label, td { color: #E0E0E0 !important; font-family: 'Inter', sans-serif; }
    
    /* FIX: Scan Button Contrast (Black text on Neon Green) */
    .stButton>button {
        background-color: #00FF88 !important;
        color: #000000 !important;
        font-weight: 900 !important;
        text-transform: uppercase;
        border: none;
        letter-spacing: 1px;
    }

    [data-testid="stMetricValue"] { color: #00FF88 !important; font-weight: 800 !important; }

    /* Signal Card */
    .signal-card {
        background-color: #0F0F0F;
        border: 1px solid #00FF88;
        border-radius: 10px;
        padding: 25px;
        margin-top: 20px;
    }
    
    .reasoning-box {
        background-color: #1A1A1A;
        border-left: 4px solid #00FF88;
        padding: 15px;
        margin-top: 15px;
        font-size: 0.95em;
        line-height: 1.6;
    }
    </style>
""", unsafe_allow_html=True)

# --- 2. ENGINE LOGIC ---
class ConvictionEngine:
    def __init__(self):
        self.universe = ["BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK", "ADRO.JK", "GOTO.JK", "MDKA.JK", "UNTR.JK"]
        
    def get_data(self, ticker):
        try:
            df = yf.download(ticker, period="60d", interval="1d", progress=False)
            if df.empty: return None
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            return df
        except: return None

    def analyze_stock(self, ticker):
        df = self.get_data(ticker)
        if df is None or len(df) < 20: return None
        
        # FVG Detection
        for i in range(2, 8):
            c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
            c1_high = float(c1['High'])
            c3_low = float(c3['Low'])
            
            if c1_high < c3_low: # Bullish FVG
                # Conviction Scoring
                vol_spike = float(c2['Volume']) > df['Volume'].rolling(20).mean().iloc[-i-1]
                trend_ok = float(df['Close'].iloc[-1]) > df['Close'].rolling(20).mean().iloc[-1]
                gap_size = (c3_low - c1_high) / c1_high * 100
                
                score = 10
                reasons = [f"Institutional Gap (FVG) of {gap_size:.2f}% detected."]
                if vol_spike: 
                    score += 5
                    reasons.append("High volume displacement confirms institutional entry.")
                if trend_ok: 
                    score += 5
                    reasons.append("Price is trending above the 20-day SMA.")
                
                return {
                    "ticker": ticker,
                    "entry": c3_low,
                    "sl": float(c1['Low']),
                    "tp": c3_low + (c3_low - float(c1['Low'])) * 2,
                    "current": float(df['Close'].iloc[-1]),
                    "score": score,
                    "reasons": reasons,
                    "df_slice": df.iloc[-i-15:]
                }
        return None

# --- 3. DATABASE ---
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# --- 4. INTERFACE ---
def main():
    st.title("🎯 CONVICTION ENGINE")
    
    with st.sidebar:
        st.header("Settings")
        capital = st.number_input("Capital (IDR)", value=100000000, step=1000000)
        risk_pct = st.slider("Risk %", 0.5, 3.0, 1.0)

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("MARKET", "IDX", "Active")
    col_b.metric("SCORE", "CONVICTION", "High")
    col_c.metric("STRATEGY", "FVG RETEST", "Ready")

    engine = ConvictionEngine()

    if st.button("🔍 SCAN FOR THE TOP PICK"):
        with st.spinner("Analyzing institutional footprints..."):
            all_setups = []
            for ticker in engine.universe:
                setup = engine.analyze_stock(ticker)
                if setup:
                    # Calculate proximity to entry
                    dist = abs(setup['current'] - setup['entry']) / setup['entry']
                    all_setups.append((setup, dist))

            if all_setups:
                # Pick setup with highest score and closest to entry
                best_setup = sorted(all_setups, key=lambda x: (-x[0]['score'], x[1]))[0][0]
                
                # Sizing
                risk_amt = capital * (risk_pct / 100)
                lots = int((risk_amt / (best_setup['entry'] - best_setup['sl'])) / 100)
                
                # UI CARD
                st.markdown(f"""
                    <div class="signal-card">
                        <h1 style='color:#00FF88; margin:0;'>{best_setup['ticker']}</h1>
                        <p style='margin-bottom:20px; color:#AAAAAA;'>Top High-Conviction Pick for Today</p>
                        <table style='width:100%;'>
                            <tr>
                                <td><small>ENTRY</small><br><b style='font-size:1.4em;'>{best_setup['entry']:,.0f}</b></td>
                                <td><small>STOP LOSS</small><br><b style='font-size:1.4em; color:#FF4B4B;'>{best_setup['sl']:,.0f}</b></td>
                                <td><small>TAKE PROFIT</small><br><b style='font-size:1.4em; color:#00FF88;'>{best_setup['tp']:,.0f}</b></td>
                                <td><small>POSITION</small><br><b style='font-size:1.4em;'>{lots} Lots</b></td>
                            </tr>
                        </table>
                        <div class="reasoning-box">
                            <b style='color:#00FF88;'>CONVICTION BREAKDOWN:</b><br>
                            {''.join([f'• {r}<br>' for r in best_setup['reasons']])}
                        </div>
                    </div>
                """, unsafe_allow_html=True)
                
                # Chart
                fig = go.Figure(data=[go.Candlestick(
                    x=best_setup['df_slice'].index,
                    open=best_setup['df_slice']['Open'],
                    high=best_setup['df_slice']['High'],
                    low=best_setup['df_slice']['Low'],
                    close=best_setup['df_slice']['Close']
                )])
                fig.update_layout(template="plotly_dark", height=450, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)

                if st.button("✅ LOG TRADE TO DATABASE"):
                    supabase.table("trades").insert({
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "ticker": best_setup['ticker'],
                        "entry_price": best_setup['entry'],
                        "stop_loss": best_setup['sl'],
                        "take_profit": best_setup['tp'],
                        "position_size": lots,
                        "status": "OPEN"
                    }).execute()
                    st.success("Trade successfully logged.")

    st.divider()
    st.header("📜 Trade History")
    try:
        history = supabase.table("trades").select("*").order("date", desc=True).execute()
        st.table(pd.DataFrame(history.data).drop(columns=['id'], errors='ignore'))
    except:
        st.write("No trades logged.")

if __name__ == "__main__":
    main()
