import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np

# --- 1. CONFIGURATION & CONNECTION ---
st.set_page_config(page_title="Conviction Engine", layout="wide")

# Database Connection
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(URL, KEY)

# IDX Universe
IDX_TICKERS = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "TLKM.JK", "ASII.JK", 
    "BYAN.JK", "AMRT.JK", "BBNI.JK", "ICBP.JK", "GOTO.JK",
    "UNTR.JK", "KLBF.JK", "PGAS.JK", "ADRO.JK", "CPIN.JK",
    "ADMR.JK", "MDKA.JK", "ITMG.JK", "HRUM.JK", "INKP.JK"
]

# --- 2. HELPER FUNCTIONS ---
def render_sidebar():
    st.sidebar.title("🛠 Settings")
    capital = st.sidebar.number_input("Total Capital (IDR)", value=100_000_000, step=1_000_000)
    risk_per_trade = st.sidebar.slider("Risk Per Trade (%)", 0.5, 5.0, 1.0)
    return capital, risk_per_trade

def render_performance(trades_df, equity_df):
    st.header("📈 Performance Analytics")
    col1, col2, col3, col4 = st.columns(4)
    
    if not trades_df.empty:
        closed_trades = trades_df[trades_df['status'] != 'OPEN']
        win_rate = (len(closed_trades[closed_trades['pnl'] > 0]) / len(closed_trades)) * 100 if len(closed_trades) > 0 else 0
        total_pnl = trades_df['pnl'].sum()
        
        col1.metric("Total PnL", f"IDR {total_pnl:,.0f}")
        col2.metric("Win Rate", f"{win_rate:.1f}%")
        col3.metric("Avg R:R", "1:2.0")
        col4.metric("Trades Executed", len(trades_df))

        if not equity_df.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=equity_df['date'], y=equity_df['portfolio_value'], name='Portfolio'))
            start_cap = equity_df['portfolio_value'].iloc[0]
            ihsg_norm = (equity_df['ihsg_value'] / equity_df['ihsg_value'].iloc[0]) * start_cap
            fig.add_trace(go.Scatter(x=equity_df['date'], y=ihsg_norm, name='IHSG Benchmark', line=dict(dash='dash')))
            st.plotly_chart(fig, use_container_width=True) # use_container_width is still standard for Plotly
    else:
        st.info("Log your first trade to see performance analytics.")

# --- 3. THE ENGINE CLASS ---
class ConvictionEngine:
    def __init__(self, tickers):
        self.tickers = tickers

    def get_data(self, ticker, period="100d"):
        try:
            df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
            return df
        except:
            return pd.DataFrame()

    def detect_fvg(self, df):
        if df is None or len(df) < 20: return None
        try:
            for i in range(2, 7):
                c1, c2, c3 = df.iloc[-i-2], df.iloc[-i-1], df.iloc[-i]
                c1_high, c1_low, c3_low = float(c1['High']), float(c1['Low']), float(c3['Low'])
                current_price = float(df['Close'].iloc[-1])

                if c1_high < c3_low: # Bullish FVG
                    body_size = abs(float(c2['Close']) - float(c2['Open']))
                    atr = (df['High'] - df['Low']).rolling(14).mean().iloc[-i-1]
                    
                    if body_size > (atr * 1.2):
                        v_ma = df['Volume'].rolling(20).mean().iloc[-i-1]
                        volume_spike = bool(float(c2['Volume']) > v_ma)
                        setup_data = {
                            "entry": c3_low, "sl": c1_low, 
                            "tp": c3_low + ((c3_low - c1_low) * 2),
                            "gap": (c1_high, c3_low), "volume_spike": volume_spike
                        }
                        if current_price <= c3_low and current_price >= c1_high:
                            setup_data["type"] = "SIGNAL"
                            return setup_data
                        if current_price > c3_low:
                            setup_data["type"] = "WATCHLIST"
                            return setup_data
            return None
        except:
            return None

    def score_setup(self, ticker, setup, df):
        if not setup: return 0
        score = 0
        try:
            if setup.get('volume_spike'): score += 5
            if float(df['Close'].iloc[-1]) > df['Close'].rolling(20).mean().iloc[-1]: score += 5
            gap_pct = (setup['gap'][1] - setup['gap'][0]) / setup['gap'][0]
            score += min(5, gap_pct * 500)
            avg_val = (df['Close'] * df['Volume']).rolling(20).mean().iloc[-1]
            if avg_val > 50_000_000_000: score += 10
        except: pass
        return round(score, 2)

    def scan_all(self):
        signals, watchlist = [], []
        for ticker in self.tickers:
            df = self.get_data(ticker)
            if df.empty: continue
            setup = self.detect_fvg(df)
            if setup:
                score = self.score_setup(ticker, setup, df)
                item = {"ticker": ticker, "setup": setup, "score": score}
                if setup['type'] == "SIGNAL" and score >= 15: signals.append(item)
                elif score >= 10: watchlist.append(item)
        best_pick = max(signals, key=lambda x: x['score']) if signals else None
        return best_pick, watchlist

    def run_backtest(self, lookback_days=60):
        results = []
        all_tickers_data = {t: self.get_data(t, period="200d") for t in self.tickers}
        
        for i in range(lookback_days, 5, -1):
            daily_candidates = []
            for ticker, df in all_tickers_data.items():
                if len(df) < i + 30: continue
                df_past = df.iloc[:-i]
                current_date = df_past.index[-1]
                setup = self.detect_fvg(df_past)
                if setup and setup['type'] == "SIGNAL":
                    score = self.score_setup(ticker, setup, df_past)
                    if score >= 15:
                        daily_candidates.append({"date": current_date, "ticker": ticker, "setup": setup, "score": score, "future": df.iloc[-i:]})
            
            if daily_candidates:
                best = max(daily_candidates, key=lambda x: x['score'])
                outcome, pnl_r, s = "PENDING", 0, best['setup']
                for _, day in best['future'].iterrows():
                    if day['Low'] <= s['sl']:
                        outcome, pnl_r = "❌ LOSS", -1.0
                        break
                    elif day['High'] >= s['tp']:
                        outcome, pnl_r = "✅ WIN", 2.0
                        break
                results.append({"Date": best['date'].strftime("%Y-%m-%d"), "Ticker": best['ticker'], "Score": best['score'], "Result": outcome, "PnL (R)": pnl_r})
        return pd.DataFrame(results)

# --- 4. MAIN INTERFACE ---
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

    # 1. Conviction Pick Display
    if 'best_pick' in st.session_state:
        st.header("🏆 Today's Conviction Pick")
        pick = st.session_state.best_pick
        if pick:
            s = pick['setup']
            risk_amt = capital * (risk_pct / 100)
            sl_dist = s['entry'] - s['sl']
            lots = int((risk_amt / sl_dist) / 100) if sl_dist > 0 else 0
            
            c1, c2 = st.columns(2)
            c1.metric("Score", f"{pick['score']}/25")
            c1.write(f"**Ticker:** {pick['ticker']} | **Entry:** {s['entry']:,.0f}")
            c2.write(f"**Target Lots:** {lots} Lots")
            if c2.button("📝 Log Trade"):
                supabase.table("trades").insert({"date": datetime.now().strftime("%Y-%m-%d"), "ticker": pick['ticker'], "entry_price": s['entry'], "stop_loss": s['sl'], "take_profit": s['tp'], "position_size": lots, "score": pick['score']}).execute()
                st.success("Logged!")
        else:
            st.warning("No high-conviction signals right now.")

    # 2. Watchlist Display
    if 'watchlist' in st.session_state:
        st.divider()
        st.header("👀 Setup Watchlist")
        items = st.session_state.watchlist
        if items:
            cols = st.columns(3)
            for idx, item in enumerate(items[:6]):
                with cols[idx % 3]:
                    st.info(f"**{item['ticker']}** (Score: {item['score']})\n\nWait for: {item['setup']['entry']:,.0f}")

    # 3. Database & Tracking
    st.divider()
    try:
        trades_resp = supabase.table("trades").select("*").order("date", desc=True).execute()
        trades_df = pd.DataFrame(trades_resp.data)
        equity_resp = supabase.table("equity_history").select("*").order("date").execute()
        equity_df = pd.DataFrame(equity_resp.data)
        
        t1, t2, t3 = st.tabs(["📊 Analytics", "📜 History", "🧪 Backtest"])
        
        with t1: render_performance(trades_df, equity_df)
        with t2: st.dataframe(trades_df, width="stretch") 
        with t3:
            st.header("Historical Simulation")
            lookback = st.slider("Days to test", 30, 90, 60)
            if st.button("🚀 Run Backtest"):
                with st.spinner("Processing past market data..."):
                    engine = ConvictionEngine(IDX_TICKERS)
                    bt_results = engine.run_backtest(lookback)
                    if not bt_results.empty:
                        c1, c2 = st.columns(2)
                        wins = len(bt_results[bt_results['Result'] == "✅ WIN"])
                        total = len(bt_results[bt_results['Result'] != "PENDING"])
                        c1.metric("Simulated Win Rate", f"{(wins/total)*100:.1f}%" if total > 0 else "0%")
                        c2.metric("Total Profit (R)", f"{bt_results['PnL (R)'].sum():.1f}R")
                        st.dataframe(bt_results, width="stretch")
                    else:
                        st.write("No historical picks found in this period.")
    except Exception as e:
        st.error(f"Database/Engine Error: {e}")

if __name__ == "__main__":
    main()
