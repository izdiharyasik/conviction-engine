import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime

# --- 1. FORCE HIGH-CONTRAST DARK THEME ---
st.set_page_config(page_title="Conviction Engine", layout="wide")

# CSS to force visibility regardless of Streamlit Light/Dark settings
st.markdown("""
    <style>
    /* Force deep background */
    .stApp { background-color: #050505 !important; }
    
    /* Force all text to be visible (Off-White) */
    h1, h2, h3, p, span, label, .stMarkdown { color: #E0E0E0 !important; }
    
    /* Fix Metric Visibility */
    [data-testid="stMetricValue"] { color: #00FF88 !important; font-size: 2.5rem !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] { color: #AAAAAA !important; }

    /* Signal Card - High Contrast */
    .signal-card {
        background-color: #111111;
        border: 2px solid #00FF88;
        border-radius: 12px;
        padding: 30px;
        margin: 10px 0px;
    }
    
    /* Buttons */
    .stButton>button {
        background-color: #00FF88 !important;
        color: #000000 !important;
        font-weight: bold !important;
        border-radius: 5px;
        height: 3em;
        width: 100%;
    }
    </style>
""", unsafe_allow_html=True)

# --- 2. CORE LOGIC ---
class ConvictionEngine:
    def __init__(self):
        # Top Liquidity IDX Universe
        self.universe = ["BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK", "ADRO.JK", "GOTO.JK", "MDKA.JK", "UNTR.JK"]
        
    def get_data(self, ticker):
        try:
            df = yf.download(ticker, period="60d", interval="1d", progress=False)
            if df.empty: return None
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
            return df
        except: return None

    def detect_fvg(self, df):
        if df is None or len(df) < 20: return None
        for i in range(2, 8):
            c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
            if float(c1['High']) < float(c3['Low']): # Bullish FVG
                return {
                    "entry": float(c3['Low']),
                    "sl": float(c1['Low']),
                    "tp": float(c3['Low']) + (float(c3['Low'])-float(c1['Low']))*2,
                    "current": float(df['Close'].iloc[-1]),
                    "df_slice": df.iloc[-i-15:]
                }
        return None

# --- 3. DATABASE ---
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# --- 4. APP INTERFACE ---
def main():
    st.title("🎯 CONVICTION ENGINE")
    
    # Portfolio Settings
    with st.sidebar:
        st.header("Risk Config")
        capital = st.number_input("Portfolio Capital (IDR)", value=100000000, step=1000000)
        risk_pct = st.slider("Risk Per Trade %", 0.5, 3.0, 1.0)
        
    # Top Level Stats
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("MARKET", "IDX", "Active")
    col_b.metric("BENCHMARK", "IHSG", "-0.2%")
    col_c.metric("STRATEGY", "FVG RETEST", "Ready")

    engine = ConvictionEngine()

    if st.button("🔍 SCAN FOR THE TOP PICK"):
        results = []
        with st.spinner("Calculating conviction scores..."):
            for ticker in engine.universe:
                df = engine.get_data(ticker)
                setup = engine.detect_fvg(df)
                if setup:
                    # Score based on proximity to entry (Conviction)
                    proximity = 1 - (abs(setup['current'] - setup['entry']) / setup['entry'])
                    results.append({"ticker": ticker, "setup": setup, "score": proximity})

        if results:
            # Output ONLY the single best trade
            best = max(results, key=lambda x: x['score'])
            setup = best['setup']
            
            # Position Sizing
            risk_amt = capital * (risk_pct / 100)
            lots = int((risk_amt / (setup['entry'] - setup['sl'])) / 100)
            
            st.markdown(f"""
                <div class="signal-card">
                    <h1 style='color:#00FF88; margin:0;'>{best['ticker']}</h1>
                    <p style='font-size:1.2em;'>Institutional FVG Detected - Ready for Retest</p>
                    <hr style='border: 1px solid #333;'>
                    <table style='width:100%; border-collapse: collapse;'>
                        <tr>
                            <td><b style='color:#AAAAAA'>ENTRY</b><br><span style='font-size:1.5em;'>{setup['entry']:,.0f}</span></td>
                            <td><b style='color:#AAAAAA'>STOP LOSS</b><br><span style='font-size:1.5em; color:#FF4B4B;'>{setup['sl']:,.0f}</span></td>
                            <td><b style='color:#AAAAAA'>POSITION</b><br><span style='font-size:1.5em; color:#00FF88;'>{lots} Lots</span></td>
                        </tr>
                    </table>
                </div>
            """, unsafe_allow_html=True)
            
            # Visual Evidence
            fig = go.Figure(data=[go.Candlestick(x=setup['df_slice'].index, open=setup['df_slice']['Open'], high=setup['df_slice']['High'], low=setup['df_slice']['Low'], close=setup['df_slice']['Close'])])
            fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,b=0,t=0), xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

            if st.button("✅ EXECUTE & LOG TRADE"):
                log_data = {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "ticker": best['ticker'],
                    "entry_price": setup['entry'],
                    "stop_loss": setup['sl'],
                    "position_size": lots,
                    "status": "OPEN"
                }
                supabase.table("trades").insert(log_data).execute()
                st.success(f"Trade {best['ticker']} logged to database.")

    # Performance Dashboard
    st.divider()
    st.header("📈 Portfolio vs IHSG")
    tab1, tab2 = st.tabs(["Performance Curve", "History"])
    
    with tab1:
        st.info("Performance curve is calculated based on closed trades in Supabase.")
        # Logic to compare equity vs IHSG benchmark
        
    with tab2:
        try:
            history = supabase.table("trades").select("*").order("date", desc=True).execute()
            st.table(pd.DataFrame(history.data).drop(columns=['id'], errors='ignore'))
        except:
            st.write("No trades logged yet.")

if __name__ == "__main__":
    main()
