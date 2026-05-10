from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote_plus
from urllib.request import urlopen
import xml.etree.ElementTree as ET

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="MacroLens", page_icon="🧠", layout="wide")

REGIME_META = {
    "RISK_ON": {
        "name": "Risk-On",
        "color": "#22c55e",
        "description": "Growth is holding, volatility is contained, and capital is willing to own risk.",
        "implication": "Favor equities, emerging markets, high yield, and selective crypto while keeping stops disciplined.",
    },
    "EASING": {
        "name": "Easing",
        "color": "#38bdf8",
        "description": "Policy pressure is falling as central banks cut rates or markets price easier money.",
        "implication": "Duration and quality growth lead as lower discount rates lift long-duration assets.",
    },
    "TIGHTENING": {
        "name": "Tightening",
        "color": "#f59e0b",
        "description": "Inflation and real yields are forcing tighter financial conditions.",
        "implication": "Hold more cash, prefer value and commodities, and avoid expensive long-duration growth.",
    },
    "STAGFLATION": {
        "name": "Stagflation",
        "color": "#f97316",
        "description": "Inflation is hot while growth is weak, creating the hardest backdrop for balanced portfolios.",
        "implication": "Own real assets, gold, and defensive cash flows; avoid cyclicals and high-yield credit.",
    },
    "RISK_OFF": {
        "name": "Risk-Off",
        "color": "#ef4444",
        "description": "Volatility, credit stress, and curve signals say investors are protecting capital.",
        "implication": "Raise cash, add gold and high-quality bonds, and reduce EM equity and high-yield exposure.",
    },
    "CRISIS": {
        "name": "Crisis",
        "color": "#dc2626",
        "description": "Markets are in capital-preservation mode with panic volatility and broad risk liquidation.",
        "implication": "Do not catch falling knives; cash, gold, and Treasuries are the playbook until stress breaks.",
    },
}

CONVICTION_MATRIX = {
    "EM Equities": {"RISK_ON": 2, "EASING": 1, "TIGHTENING": -1, "STAGFLATION": -2, "RISK_OFF": -2, "CRISIS": -2},
    "Developed Equities": {"RISK_ON": 1, "EASING": 2, "TIGHTENING": 0, "STAGFLATION": -1, "RISK_OFF": -1, "CRISIS": -2},
    "Commodities": {"RISK_ON": 1, "EASING": 0, "TIGHTENING": 1, "STAGFLATION": 2, "RISK_OFF": -1, "CRISIS": -1},
    "Gold": {"RISK_ON": 0, "EASING": 1, "TIGHTENING": -1, "STAGFLATION": 2, "RISK_OFF": 2, "CRISIS": 2},
    "IG Bonds": {"RISK_ON": -1, "EASING": 2, "TIGHTENING": -2, "STAGFLATION": -1, "RISK_OFF": 1, "CRISIS": 2},
    "High Yield Bonds": {"RISK_ON": 1, "EASING": 1, "TIGHTENING": -1, "STAGFLATION": -2, "RISK_OFF": -2, "CRISIS": -2},
    "USD Cash": {"RISK_ON": -1, "EASING": -2, "TIGHTENING": 1, "STAGFLATION": 0, "RISK_OFF": 2, "CRISIS": 1},
    "Crypto": {"RISK_ON": 2, "EASING": 1, "TIGHTENING": -2, "STAGFLATION": -1, "RISK_OFF": -2, "CRISIS": -2},
}

SCORE_LABELS = {-2: "STRONG AVOID", -1: "AVOID", 0: "NEUTRAL", 1: "BUY", 2: "STRONG BUY"}

FALLBACK_MARKET = {
    "VIX": 18.7,
    "DXY": 104.2,
    "US 10Y": 4.45,
    "2Y-10Y": -0.22,
    "CPI YoY": 3.2,
    "GDP Growth": 2.1,
    "ISM PMI": 50.3,
    "Unemployment": 3.9,
    "Fed Funds": 5.33,
    "S&P 500": 5250.0,
    "Gold": 2325.0,
    "WTI Oil": 78.0,
    "Bitcoin": 68000.0,
    "Copper/Gold": 0.0019,
    "IHSG": 7200.0,
    "USD/IDR": 16200.0,
    "IDX10Y": 6.85,
}

SO_WHAT_RULES = {
    ("VIX", "Calm", "RISK_ON"): "Fear is low, capital is flowing into risk assets. Equities and EM have the green light.",
    ("VIX", "Crisis", "RISK_OFF"): "Panic is elevated. Cash and gold outperform. Avoid new longs until VIX crosses below 25.",
    ("VIX", "Crisis", "CRISIS"): "This is a capital-preservation tape. Cut leverage, keep cash, and wait for volatility to break lower.",
    ("DXY", "Weak", "RISK_ON"): "Weak dollar lifts risk assets. IDR gets relief, imported inflation pressure falls, and IHSG breadth improves.",
    ("DXY", "Strong", "RISK_OFF"): "Dollar strength signals risk aversion. Capital flees EM, IDR comes under pressure, and IHSG faces foreign selling.",
    ("yield_curve", "Inverted", "ANY"): "Yield curve inversion has preceded every US recession since 1950. It is not a timing signal, but a defensive posture is warranted.",
    ("CPI", "Hot", "TIGHTENING"): "Sticky inflation keeps the Fed hawkish. Growth stocks de-rate while commodities and value stocks hold better.",
    ("Gold", "Bullish", "RISK_OFF"): "Gold strength confirms investors want protection. Keep gold as portfolio insurance.",
    ("Bitcoin", "Bullish", "RISK_ON"): "Crypto strength confirms speculative appetite. It works best when liquidity and equity breadth are improving together.",
}

NEWS_KEYWORDS = {
    "Fed Policy": ["fed", "fomc", "powell", "rate cut", "rate hike", "interest rate"],
    "Inflation": ["inflation", "cpi", "pce", "prices"],
    "FX/EM": ["dollar", "rupiah", "idr", "emerging market", "currency"],
    "China": ["china", "beijing", "pboc", "stimulus"],
    "Commodities": ["oil", "gold", "copper", "coal", "nickel", "commodity"],
    "Risk Sentiment": ["stocks", "equities", "vix", "selloff", "rally"],
    "Indonesia": ["indonesia", "ihsg", "idx", "bank indonesia", "jakarta"],
    "Geopolitics": ["war", "sanction", "tariff", "geopolitical"],
}

NEWS_SO_WHAT = {
    "Fed Policy": {
        "TIGHTENING": "Rate-hike expectations suppress growth-stock multiples. Watch USD strength because it pressures IDR.",
        "EASING": "Rate-cut expectations pull yields lower. Quality growth and bonds get the first boost.",
        "DEFAULT": "Fed news moves discount rates first, then currencies, then equity leadership.",
    },
    "China": {
        "DEFAULT": "China stimulus benefits Indonesia through commodity demand in CPO, nickel, and coal. IDX commodity names usually react first.",
    },
    "Inflation": {
        "TIGHTENING": "Higher inflation delays cuts. Bond prices fall, the yield curve can flatten, and defensive sectors lead.",
        "DEFAULT": "Inflation surprises decide whether the market pays up for growth or hides in cash and real assets.",
    },
    "Indonesia": {
        "DEFAULT": "Indonesia macro news hits IDR and foreign flows first. Banks and commodity exporters are the cleanest transmission channels.",
    },
    "Commodities": {
        "DEFAULT": "Commodity strength supports Indonesia's terms of trade and helps coal, nickel, and plantation-linked equities.",
    },
    "FX/EM": {
        "DEFAULT": "Currency pressure changes the whole EM risk budget. A weaker IDR tightens financial conditions for Indonesian assets.",
    },
    "Risk Sentiment": {
        "DEFAULT": "Risk sentiment drives positioning. When breadth improves, equities rally; when volatility rises, cash wins.",
    },
    "Geopolitics": {
        "DEFAULT": "Geopolitical stress raises risk premiums. Gold, USD cash, and energy hedges get a bid.",
    },
}

FRAMEWORKS = [
    ("Dalio's Debt Cycle", "Credit drives booms and busts. Short cycles create recessions; long cycles end in deleveraging.", "Intermediate", "Debt creates spending power today and repayment pressure tomorrow. When income growth cannot cover debt service, borrowers cut spending and asset prices fall.", "2008 showed a private-debt deleveraging; 2020 showed a policy-driven reflation after a sudden stop.", "Investment implication: reduce leverage late-cycle, buy quality assets after forced deleveraging, and watch real rates."),
    ("The Yield Curve", "The curve compares short-term and long-term interest rates. Inversion means policy is tight relative to future growth.", "Beginner", "A normal curve slopes up because investors demand more yield for longer loans. An inverted curve says markets expect growth and inflation to weaken.", "The US 2Y-10Y curve inverted before the 2001, 2008, and 2020 recessions.", "Investment implication: use inversion as a risk-budget warning, not a sell-everything timer."),
    ("Sector Rotation Model", "Different sectors lead in different cycle phases. The market rotates before the economic data confirms it.", "Intermediate", "Cyclicals lead early recovery, technology and discretionary lead expansion, energy and staples lead late cycle, and defensives lead contraction.", "In 2022, energy outperformed while long-duration technology de-rated under inflation and rate pressure.", "Investment implication: align sector weights with the regime instead of chasing last quarter's winners."),
    ("Fed Policy Transmission", "Fed moves travel through yields, credit, currencies, and valuations. Your portfolio feels policy before the real economy does.", "Intermediate", "Higher rates lift discount rates, tighten lending, strengthen USD, and reduce speculative appetite.", "The 2022 hiking cycle crushed unprofitable growth stocks and lifted cash yields.", "Investment implication: when policy tightens, shorten duration and demand stronger balance sheets."),
    ("Purchasing Power Parity", "Currencies adjust toward relative purchasing power over long horizons. Short horizons are dominated by rates and flows.", "Advanced", "If Indonesia inflation runs hotter than US inflation, IDR needs compensation through higher rates or a cheaper currency.", "IDR weakness during dollar squeezes shows flows can dominate valuation for months.", "Investment implication: hedge FX when USD momentum and rate differentials move against IDR."),
    ("The Dollar Smile Theory", "USD strengthens in US booms and global busts. It weakens when global growth catches up.", "Advanced", "The dollar smiles at both extremes: strong US exceptionalism or global panic. It falls in the middle when risk appetite broadens.", "March 2020 was the panic side of the smile; 2017 was synchronized global growth and USD weakness.", "Investment implication: EM equities work best when USD is falling for growth reasons."),
    ("Commodity Supercycles", "Long waves of underinvestment and demand shocks drive multi-year commodity trends. China remains the swing buyer.", "Intermediate", "Supply cannot respond quickly to years of underinvestment. When demand accelerates, prices overshoot.", "The 2000s China buildout drove coal, copper, iron ore, and EM exporters higher.", "Investment implication: Indonesia benefits when coal, nickel, and CPO prices rise together."),
    ("Inflation Regimes", "Good inflation comes from demand; bad inflation comes from supply shocks. Stagflation is bad inflation plus weak growth.", "Beginner", "Reflation helps earnings. Stagflation squeezes margins and households at the same time.", "The 1970s were classic stagflation; 2021 was reopening reflation before the inflation problem broadened.", "Investment implication: own cyclicals in reflation, real assets in stagflation, and duration when inflation breaks lower."),
    ("Risk-On / Risk-Off Dynamics", "Capital either seeks return or seeks safety. EM assets are highly sensitive to that switch.", "Beginner", "Risk-on means investors buy equities, credit, and EM FX. Risk-off means they buy USD, Treasuries, cash, and gold.", "March 2020 showed classic risk-off liquidation; late 2020 showed risk-on recovery.", "Investment implication: size IHSG exposure around VIX, DXY, and foreign-flow pressure."),
    ("Reflexivity", "Markets change fundamentals by changing confidence, financing, and behavior. Price is not just a signal; it becomes a force.", "Advanced", "Rising prices lower funding stress and attract capital, which can improve fundamentals until the loop reverses.", "Soros used this lens for currency and credit bubbles where expectations became self-reinforcing.", "Investment implication: respect trends, but exit when the narrative stops improving despite higher prices."),
]

GLOSSARY = {
    "QE": ("Quantitative easing: central-bank bond buying that pushes liquidity into the system.", "When the Fed restarted QE in March 2020, yields fell and risk assets recovered.", "Fed balance sheet, yields"),
    "QT": ("Quantitative tightening: central-bank balance-sheet shrinkage that drains liquidity.", "QT makes markets absorb more bonds without central-bank support.", "Fed balance sheet, reserves"),
    "Taper": ("A slower pace of asset purchases before QE ends.", "The 2013 taper tantrum lifted yields and pressured EM currencies.", "Yields, USD, EM FX"),
    "Yield Curve": ("The line of yields across bond maturities.", "A 2Y-10Y inversion is a recession warning.", "2Y yield, 10Y yield"),
    "Spread": ("The gap between two yields or prices.", "Credit spreads widen when investors demand more compensation for default risk.", "Credit spreads"),
    "Real vs. Nominal": ("Nominal rates include inflation; real rates subtract inflation.", "A 5% yield with 3% inflation is a 2% real yield.", "TIPS, CPI"),
    "PMI": ("Purchasing Managers' Index: a survey where 50 separates expansion from contraction.", "PMI below 50 signals shrinking manufacturing activity.", "ISM PMI"),
    "CPI": ("Consumer Price Index: a broad measure of consumer inflation.", "Hot CPI can delay Fed cuts.", "CPI YoY"),
    "PCE": ("Personal Consumption Expenditures: the Fed's preferred inflation gauge.", "Core PCE guides Fed inflation decisions.", "PCE inflation"),
    "Fed Funds Rate": ("The overnight policy rate targeted by the Federal Reserve.", "Higher Fed Funds raises cash yields and discount rates.", "FOMC, SOFR"),
    "FOMC": ("The Fed committee that sets US monetary policy.", "FOMC days often move yields, USD, and equities.", "Fed Funds"),
    "Basis Points": ("One basis point is 0.01 percentage point.", "A 25 bp hike moves 4.75% to 5.00%.", "Rates"),
    "Duration": ("A bond's sensitivity to interest-rate changes.", "Long-duration bonds fall more when yields rise.", "10Y yield"),
    "Credit Spread": ("Extra yield paid by risky borrowers over safe government bonds.", "Wider spreads signal stress.", "HY OAS"),
    "Carry Trade": ("Borrow cheap currency, buy higher-yield currency, earn the gap.", "IDR carry works when USD is calm.", "FX, rates"),
    "Risk Premium": ("Extra return investors demand for taking risk.", "Equity risk premium compresses in bull markets.", "Valuations"),
    "Convexity": ("How rate sensitivity changes as yields move.", "Mortgage convexity can amplify bond-market moves.", "Duration"),
    "Reflation": ("Growth and inflation recover together from a weak base.", "2020 reopening was a reflation trade.", "PMI, CPI"),
    "Stagflation": ("High inflation plus weak growth.", "The 1970s punished stocks and bonds together.", "CPI, GDP"),
    "Tapering": ("Reducing asset purchases over time.", "Tapering is less stimulus, not outright tightening.", "QE"),
    "Hawkish/Dovish": ("Hawkish means tighter policy; dovish means easier policy.", "A hawkish Powell press conference can lift USD.", "Fed"),
    "Hot Money": ("Fast-moving capital that chases yield and exits quickly.", "Hot money leaves EM when USD spikes.", "DXY, EM FX"),
}

MODULES = [
    ("How the economic machine works", "Dalio's framework for credit, spending, income, and cycles.", "18 min", "Available", "Credit creates cycles."),
    ("Central banks", "What they do, why rates matter, and how liquidity moves markets.", "22 min", "Available", "Policy moves portfolios before GDP."),
    ("Inflation", "Causes, types, and investment implications.", "20 min", "Available", "Inflation quality matters."),
    ("Interest rates and bond markets", "Yield curves, duration, and credit spreads.", "25 min", "Locked", "Rates are the price of time."),
    ("Currency markets and EM dynamics", "Dollar cycles, carry, and IDR sensitivity.", "20 min", "Locked", "USD drives EM risk budgets."),
    ("Commodity markets and emerging economies", "Supply cycles, China demand, and Indonesia leverage.", "18 min", "Locked", "Indonesia is a commodity beta market."),
    ("Equity valuation in regimes", "Multiples, earnings, and discount rates.", "28 min", "Locked", "Regimes decide the multiple."),
    ("Portfolio construction through the cycle", "How to size risk across macro states.", "30 min", "Locked", "Diversification must be regime-aware."),
    ("Reading macro for trading", "Signals, timing, and false positives.", "24 min", "Locked", "Macro is a wind, not an entry trigger."),
    ("Indonesia-specific macro", "IHSG, IDR, Bank Indonesia, and fiscal data.", "26 min", "Locked", "Foreign flows connect global macro to IDX."),
]


def css() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #020617; color: #e5e7eb; }
        section[data-testid="stSidebar"] { background: #0f172a; border-right: 1px solid #1e293b; }
        h1,h2,h3,h4,p,span,label,li,td,th { color: #e5e7eb; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
        [data-testid="stMetricValue"], .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
        .regime { border-radius: 18px; padding: 20px; background: #0f172a; border: 1px solid #1e293b; position: sticky; top: 0; z-index: 10; }
        .card { border: 1px solid #1e293b; border-radius: 16px; padding: 18px; background: #0f172a; margin-bottom: 12px; }
        .badge { border-radius: 999px; padding: 3px 10px; font-size: 12px; font-weight: 800; display: inline-block; }
        .green { background: rgba(34,197,94,.18); color: #86efac; }
        .red { background: rgba(239,68,68,.18); color: #fca5a5; }
        .amber { background: rgba(245,158,11,.18); color: #fcd34d; }
        .blue { background: rgba(56,189,248,.18); color: #7dd3fc; }
        .muted { color: #94a3b8 !important; }
        div[data-testid="stTabs"] button { font-weight: 800; }
        </style>
        """,
        unsafe_allow_html=True,
    )


@dataclass
class Indicator:
    name: str
    value: float | str
    change: float | str
    signal: str
    meaning: str
    unit: str = ""
    key: str = ""


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_yahoo_last(ticker: str, fallback: float) -> tuple[float, float]:
    data = yf.download(ticker, period="1mo", interval="1d", progress=False, auto_adjust=False)
    if data.empty:
        return fallback, 0.0
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [column[0] for column in data.columns]
    if "Close" not in data:
        return fallback, 0.0
    close = data["Close"].dropna()
    if close.empty:
        return fallback, 0.0
    last = float(close.iloc[-1])
    previous = float(close.iloc[-2]) if len(close) > 1 else last
    return last, last - previous


def signal_badge(signal: str) -> str:
    lowered = signal.lower()
    cls = "blue"
    if any(word in lowered for word in ["calm", "contained", "solid", "expanding", "bullish", "tight", "weak dollar"]):
        cls = "green"
    if any(word in lowered for word in ["hot", "crisis", "inverted", "rising", "bearish", "strong dollar", "recession"]):
        cls = "red"
    if any(word in lowered for word in ["normal", "flat", "sticky", "elevated", "neutral", "mixed"]):
        cls = "amber"
    return f'<span class="badge {cls}">{signal}</span>'


def classify_value(name: str, value: float, change: float = 0) -> str:
    if name == "VIX":
        return "Calm" if value < 15 else "Normal" if value < 20 else "Elevated" if value < 30 else "Crisis"
    if name == "DXY":
        return "Weak" if change < -0.1 else "Strong" if change > 0.1 else "Neutral"
    if name == "US 10Y":
        return "Low" if value < 3 else "Normal" if value < 4.5 else "Elevated"
    if name == "2Y-10Y":
        return "Inverted" if value < 0 else "Flat" if value < 0.5 else "Normal"
    if name == "CPI YoY":
        return "Contained" if value < 2 else "Sticky" if value <= 4 else "Hot"
    if name == "GDP Growth":
        return "Recession" if value < 0 else "Weak" if value < 1.5 else "Solid" if value < 3 else "Strong"
    if name == "ISM PMI":
        return "Contracting" if value < 50 else "Expanding"
    if name == "Unemployment":
        return "Tight" if value < 4 else "Stable" if value < 5 else "Rising"
    if name in {"S&P 500", "Gold", "WTI Oil", "Bitcoin", "IHSG"}:
        return "Bullish" if change > 0 else "Bearish" if change < 0 else "Neutral"
    return "Neutral"


def load_market_data() -> dict[str, tuple[float, float]]:
    tickers = {
        "VIX": ("^VIX", FALLBACK_MARKET["VIX"]),
        "DXY": ("DX-Y.NYB", FALLBACK_MARKET["DXY"]),
        "US 10Y": ("^TNX", FALLBACK_MARKET["US 10Y"]),
        "S&P 500": ("^GSPC", FALLBACK_MARKET["S&P 500"]),
        "Gold": ("GC=F", FALLBACK_MARKET["Gold"]),
        "WTI Oil": ("CL=F", FALLBACK_MARKET["WTI Oil"]),
        "Bitcoin": ("BTC-USD", FALLBACK_MARKET["Bitcoin"]),
        "IHSG": ("^JKSE", FALLBACK_MARKET["IHSG"]),
        "USD/IDR": ("IDR=X", FALLBACK_MARKET["USD/IDR"]),
    }
    data = {name: fetch_yahoo_last(ticker, fallback) for name, (ticker, fallback) in tickers.items()}
    data.update({
        "2Y-10Y": (FALLBACK_MARKET["2Y-10Y"], -0.03),
        "CPI YoY": (FALLBACK_MARKET["CPI YoY"], -0.1),
        "GDP Growth": (FALLBACK_MARKET["GDP Growth"], 0.2),
        "ISM PMI": (FALLBACK_MARKET["ISM PMI"], 0.6),
        "Unemployment": (FALLBACK_MARKET["Unemployment"], 0.0),
        "Fed Funds": (FALLBACK_MARKET["Fed Funds"], 0.0),
        "Copper/Gold": (FALLBACK_MARKET["Copper/Gold"], 0.0001),
        "IDX10Y": (FALLBACK_MARKET["IDX10Y"], 0.03),
    })
    return data


def classify_regime(data: dict[str, tuple[float, float]]) -> tuple[str, int, dict[str, int]]:
    vix, vix_change = data["VIX"]
    dxy, dxy_change = data["DXY"]
    ten_year, ten_year_change = data["US 10Y"]
    curve, curve_change = data["2Y-10Y"]
    cpi, cpi_change = data["CPI YoY"]
    gdp, _ = data["GDP Growth"]
    pmi, _ = data["ISM PMI"]
    unemployment, unemployment_change = data["Unemployment"]
    spx, spx_change = data["S&P 500"]

    scores = {key: 0 for key in REGIME_META}
    if vix < 20 and dxy_change < 0 and abs(ten_year_change) < 0.1 and pmi > 50:
        scores["RISK_ON"] += 4
    if ten_year_change < -0.08 or curve_change > 0 or cpi_change < 0:
        scores["EASING"] += 3
    if ten_year_change > 0.08 or cpi > 3:
        scores["TIGHTENING"] += 3
    if cpi > 4 and gdp < 1.5 and unemployment_change > 0:
        scores["STAGFLATION"] += 5
    if vix > 25 or curve < 0:
        scores["RISK_OFF"] += 3
    if vix > 35 and spx_change / max(spx - spx_change, 1) < -0.1:
        scores["CRISIS"] += 6
    if vix < 20:
        scores["RISK_ON"] += 1
    if dxy_change > 0:
        scores["RISK_OFF"] += 1
    if curve < 0:
        scores["TIGHTENING"] += 1
    regime = max(scores, key=scores.get)
    confidence = min(92, max(52, 50 + scores[regime] * 9))
    return regime, confidence, scores


def build_indicators(data: dict[str, tuple[float, float]], regime: str) -> dict[str, list[Indicator]]:
    def item(name: str, meaning: str, unit: str = "", key: str = "") -> Indicator:
        value, change = data[name]
        signal = classify_value(name, value, change)
        rule = SO_WHAT_RULES.get((key or name, signal, regime)) or SO_WHAT_RULES.get((key or name, signal, "ANY"))
        return Indicator(name, value, change, signal, rule or meaning, unit, key or name)

    return {
        "Fear & Liquidity": [
            item("VIX", "VIX below 20 supports risk-taking; above 25 forces de-risking."),
            item("DXY", "Dollar direction drives EM currency pressure and global liquidity."),
            item("US 10Y", "The 10-year yield is the anchor for mortgage rates, equity multiples, and bond duration.", "%"),
            item("2Y-10Y", "An inverted curve warns that policy is tight relative to future growth.", "%", "yield_curve"),
        ],
        "Growth & Inflation": [
            item("CPI YoY", "Inflation controls the Fed reaction function and valuation multiples.", "%", "CPI"),
            item("GDP Growth", "GDP growth tells whether earnings have macro support.", "%"),
            item("ISM PMI", "PMI above 50 means manufacturing is expanding; below 50 means contraction."),
            item("Unemployment", "Labor-market slack decides wage pressure and recession risk.", "%"),
        ],
        "Central Banks & Policy": [
            Indicator("Fed Funds Rate", data["Fed Funds"][0], data["Fed Funds"][1], "Restrictive", "Policy is still restrictive. Cuts require softer inflation or weaker labor data.", "%"),
            Indicator("ECB Rate", "4.00%", "0 bp", "Restrictive", "Europe remains sensitive to weak growth because policy is still tight."),
            Indicator("BOJ Rate", "0.10%", "+10 bp", "Normalizing", "Japan normalization can pull capital home and pressure global carry trades."),
            Indicator("Fed Balance Sheet", "QT", "Shrinking", "Tightening", "QT drains liquidity. Risk assets need earnings momentum to offset the liquidity drag."),
            Indicator("Market-Implied Cuts", "2 cuts in 2026", "Stable", "Easing", "Markets expect policy relief, but timing depends on inflation breaking lower."),
        ],
        "Risk Assets & Commodities": [
            item("S&P 500", "The S&P 500 is the cleanest real-time read on global risk appetite."),
            item("Gold", "Gold rises when real yields fall or investors demand protection.", "$"),
            item("WTI Oil", "Oil is both an inflation input and a geopolitical stress gauge.", "$"),
            item("Bitcoin", "Bitcoin is a high-beta liquidity and risk-appetite proxy.", "$"),
            item("Copper/Gold", "A rising copper/gold ratio confirms growth optimism."),
            item("IHSG", "IHSG connects global macro to Indonesian equity risk."),
            item("USD/IDR", "A rising USD/IDR means IDR weakness and tighter imported inflation pressure."),
            item("IDX10Y", "Higher Indonesian bond yields compete with equities and tighten domestic financial conditions.", "%"),
        ],
    }


def render_regime_banner(regime: str, confidence: int) -> None:
    meta = REGIME_META[regime]
    st.markdown(
        f"""
        <div class="regime" style="border-left: 8px solid {meta['color']};">
            <div class="muted">CURRENT MACRO REGIME</div>
            <h1 style="margin: 0; color: {meta['color']} !important;">{meta['name']} <span class="mono" style="font-size: 22px;">{confidence}% confidence</span></h1>
            <p style="font-size: 18px; margin-bottom: 6px;">{meta['description']}</p>
            <b>So what:</b> {meta['implication']}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_indicator_card(title: str, indicators: list[Indicator]) -> None:
    with st.container(border=True):
        st.subheader(title)
        for indicator in indicators:
            value = indicator.value
            if isinstance(value, float):
                suffix = indicator.unit
                value_text = f"{value:,.2f}{suffix}" if suffix == "%" else f"{suffix}{value:,.2f}" if suffix == "$" else f"{value:,.2f}"
            else:
                value_text = str(value)
            change = indicator.change
            change_text = f"{change:+,.2f}" if isinstance(change, float) else str(change)
            color = "#22c55e" if (isinstance(change, float) and change >= 0) or str(change).startswith("+") else "#ef4444"
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid #1e293b;padding:8px 0;'>"
                f"<div><b>{indicator.name}</b><br><span class='muted'>{indicator.meaning}</span></div>"
                f"<div style='text-align:right;min-width:150px;'><span class='mono'>{value_text}</span><br>"
                f"<span style='color:{color};' class='mono'>{change_text}</span> {signal_badge(indicator.signal)}</div></div>",
                unsafe_allow_html=True,
            )


def render_dashboard(data: dict[str, tuple[float, float]], regime: str) -> None:
    indicators = build_indicators(data, regime)
    cols = st.columns(2)
    for idx, (category, rows) in enumerate(indicators.items()):
        with cols[idx % 2]:
            render_indicator_card(category, rows)

    st.subheader(f"Asset Conviction Matrix — driven by {REGIME_META[regime]['name']}")
    matrix_rows = []
    for asset, scores in CONVICTION_MATRIX.items():
        score = scores[regime]
        matrix_rows.append({"Asset Class": asset, "Score": score, "Label": SCORE_LABELS[score]})
    matrix_df = pd.DataFrame(matrix_rows).sort_values("Score", ascending=True)
    fig = px.bar(matrix_df, x="Score", y="Asset Class", color="Score", text="Label", orientation="h", range_x=[-2.2, 2.2], color_continuous_scale=["#ef4444", "#f59e0b", "#22c55e"])
    fig.update_layout(template="plotly_dark", height=430, margin=dict(l=0, r=0, t=10, b=0), coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_news() -> list[dict[str, str]]:
    query = quote_plus("Federal Reserve OR inflation OR interest rates OR IHSG OR rupiah OR commodity prices OR China economy OR US GDP")
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    articles = []
    try:
        with urlopen(url, timeout=8) as response:
            xml_text = response.read()
        root = ET.fromstring(xml_text)
        for item in root.findall("./channel/item")[:20]:
            articles.append({
                "title": item.findtext("title", default="Macro headline"),
                "link": item.findtext("link", default="#"),
                "published": item.findtext("pubDate", default="Recent"),
                "summary": item.findtext("description", default=""),
            })
    except Exception:
        articles = []
    if articles:
        return articles
    return [
        {"title": "Fed officials debate timing of rate cuts as inflation remains sticky", "link": "#", "published": "Fallback", "summary": ""},
        {"title": "China stimulus hopes lift copper and Indonesia commodity shares", "link": "#", "published": "Fallback", "summary": ""},
        {"title": "Rupiah steadies as dollar momentum cools", "link": "#", "published": "Fallback", "summary": ""},
    ]


def tag_news(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    for tag, keywords in NEWS_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return tag
    return "Risk Sentiment"


def sentiment(title: str) -> str:
    text = title.lower()
    bullish = ["rally", "gain", "stimulus", "cut", "eases", "optimism", "growth", "surge"]
    bearish = ["fall", "hot", "hike", "war", "selloff", "slump", "crisis", "sticky"]
    bull = sum(word in text for word in bullish)
    bear = sum(word in text for word in bearish)
    return "Bullish" if bull > bear else "Bearish" if bear > bull else "Neutral"


def news_so_what(tag: str, regime: str) -> str:
    tag_rules = NEWS_SO_WHAT.get(tag, {})
    return tag_rules.get(regime) or tag_rules.get("DEFAULT") or "This changes the macro risk budget. Track yields, USD, and equity breadth for confirmation."


def render_news(regime: str) -> None:
    st.subheader("Macro-Tagged News with So What")
    articles = fetch_news()
    all_tags = ["All"] + list(NEWS_KEYWORDS.keys())
    col1, col2 = st.columns([2, 1])
    selected = col1.selectbox("Filter by macro tag", all_tags)
    indonesia_only = col2.toggle("Indonesia-focused")
    for article in articles:
        tag = tag_news(article["title"], article["summary"])
        if selected != "All" and tag != selected:
            continue
        if indonesia_only and tag not in {"Indonesia", "FX/EM", "Commodities", "China"}:
            continue
        sent = sentiment(article["title"])
        with st.container(border=True):
            st.markdown(f"### [{article['title']}]({article['link']})")
            st.markdown(f"{signal_badge(tag)} {signal_badge(sent)} <span class='muted'>{article['published']}</span>", unsafe_allow_html=True)
            st.write(f"**So what:** {news_so_what(tag, regime)}")


def sector_playbook(regime: str) -> pd.DataFrame:
    base = {
        "Energy": ("OVERWEIGHT", "Oil and coal hedge inflation shocks.", "IDX Energy — ADRO, PTBA"),
        "Materials": ("OVERWEIGHT", "Commodity leverage works when global growth and China demand improve.", "Basic Materials — ANTM, INCO"),
        "Financials": ("NEUTRAL", "Banks need growth without funding stress.", "Financials — BBCA, BBRI, BMRI"),
        "Technology": ("UNDERWEIGHT", "Long-duration earnings suffer when yields stay high.", "Tech/Telco — GOTO, TLKM"),
        "Healthcare": ("NEUTRAL", "Defensive cash flows stabilize portfolios.", "Healthcare — KLBF, MIKA"),
        "Consumer Discretionary": ("NEUTRAL", "Works when wages and confidence improve.", "Consumer Cyclical — ASII, MAPI"),
        "Consumer Staples": ("OVERWEIGHT", "Staples defend margins in weak growth.", "Consumer Non-Cyclical — ICBP, UNVR"),
        "Utilities": ("OVERWEIGHT", "Stable dividends help when volatility rises.", "Infrastructure/Utilities — PGAS, JSMR"),
        "Real Estate": ("UNDERWEIGHT", "Higher rates pressure property valuations.", "Properties — BSDE, CTRA"),
        "Industrials": ("NEUTRAL", "Cyclicals need PMI confirmation.", "Industrials — UNTR"),
    }
    if regime in {"RISK_ON", "EASING"}:
        for sector in ["Technology", "Consumer Discretionary", "Financials", "Industrials"]:
            rating, rationale, tickers = base[sector]
            base[sector] = ("OVERWEIGHT" if sector != "Financials" else "NEUTRAL", "Risk appetite and easier yields support this sector.", tickers)
        base["Consumer Staples"] = ("UNDERWEIGHT", "Defensives lag when capital chases growth.", base["Consumer Staples"][2])
    if regime in {"RISK_OFF", "CRISIS"}:
        for sector in ["Healthcare", "Consumer Staples", "Utilities"]:
            base[sector] = ("OVERWEIGHT", "Defensive cash flows outperform when volatility rises.", base[sector][2])
        for sector in ["Technology", "Consumer Discretionary", "Materials", "Industrials"]:
            base[sector] = ("UNDERWEIGHT", "Cyclicals and high-duration assets get sold first in risk-off markets.", base[sector][2])
    return pd.DataFrame([{"Sector": k, "Rating": v[0], "Rationale": v[1], "IDX angle": v[2]} for k, v in base.items()])


def render_strategy(regime: str, data: dict[str, tuple[float, float]]) -> None:
    meta = REGIME_META[regime]
    st.subheader("Regime Deep Dive")
    st.write(
        f"""
        The current regime is **{meta['name']}** because the dashboard's volatility, dollar, curve, inflation, and growth inputs are pointing to the same investment conclusion: {meta['implication']} The cause is a mix of market pricing and macro fundamentals. VIX defines whether investors are willing to hold risk, DXY defines whether emerging-market liquidity is expanding or contracting, and the yield curve defines whether policy is tight relative to future growth.

        A close historical analogy is the post-shock recovery playbook: markets first demand proof that volatility is falling, then rotate into assets with earnings leverage. If inflation remains sticky, the analogy shifts toward 2022 tightening, when cash and commodities beat long-duration growth. If volatility rises above 25, the setup flips toward risk-off and the portfolio should move from return-seeking to capital preservation.

        This kind of regime usually lasts one to four quarters, but the clock is data-dependent. The three indicators to monitor right now are **VIX**, **DXY**, and **2Y-10Y yield curve**. VIX above 25 says risk budgets are being cut. DXY strength pressures IDR and foreign flows into IHSG. A persistent inverted curve says recession risk remains alive even if equities are rallying.
        """
    )
    st.subheader("Sector Rotation Playbook")
    st.dataframe(sector_playbook(regime), use_container_width=True, hide_index=True)
    st.subheader("Historical Regime Analogies")
    analogies = [
        ("Q4 2016 — Trump Reflation Trade", "Equities, USD, and yields rose; bonds lagged; cyclicals worked.", "Lesson: when growth and yields rise together, own banks, industrials, and commodities."),
        ("2009 Recovery Phase", "Equities and credit recovered sharply while safe havens lagged.", "Lesson: after panic, falling volatility is the signal to rebuild risk."),
        ("2022 Inflation Tightening", "Cash and energy beat long-duration technology and bonds.", "Lesson: when inflation controls policy, valuation discipline matters more than growth stories."),
    ]
    for period, outcome, lesson in analogies:
        with st.container(border=True):
            st.markdown(f"**{period}**")
            st.write(outcome)
            st.write(f"**Key lesson:** {lesson}")
    st.subheader("Risk Scenarios")
    col1, col2 = st.columns(2)
    with col1:
        st.error("Bear case: VIX breaks above 25, DXY rises, and credit spreads widen. Move to cash, gold, high-quality bonds, and cut EM beta.")
    with col2:
        st.success("Bull case: VIX stays below 20, DXY falls, PMI stays above 50, and yields stabilize. Add EM equities, cyclicals, and selective crypto.")


def render_learn() -> None:
    st.subheader("Core Frameworks Library")
    for title, summary, difficulty, explanation, example, implication in FRAMEWORKS:
        with st.expander(f"{title} — {difficulty}"):
            st.write(summary)
            st.write(f"**Plain English:** {explanation}")
            st.write(f"**Historical example:** {example}")
            st.code("Macro driver → Market pricing → Portfolio action", language="text")
            st.write(f"**Investment implication:** {implication}")
            st.write("**Indonesia angle:** Apply this through IDR pressure, foreign flows, IHSG sector leadership, and Bank Indonesia's policy reaction.")
    st.subheader("Macro Glossary")
    search = st.text_input("Search glossary")
    glossary_rows = []
    for term, (definition, example, related) in GLOSSARY.items():
        if not search or search.lower() in term.lower() or search.lower() in definition.lower():
            glossary_rows.append({"Term": term, "Definition": definition, "Example": example, "Related indicators": related})
    st.dataframe(pd.DataFrame(glossary_rows), use_container_width=True, hide_index=True)
    st.subheader("Macro Master Curriculum")
    for number, module in enumerate(MODULES, start=1):
        title, description, read_time, status, takeaway = module
        with st.container(border=True):
            st.markdown(f"**Module {number}: {title}** — {signal_badge(status)}", unsafe_allow_html=True)
            st.write(description)
            st.caption(f"Read time: {read_time} • Key takeaway: {takeaway}")
    st.subheader("Recommended Resources")
    st.markdown(
        """
        - **Books:** *Principles* (Ray Dalio), *The Alchemy of Finance* (George Soros), *When Money Dies* (Adam Fergusson), *The Bond King* (Mary Childs / Lefevre request mapped to bond-market history).
        - **Videos:** Ray Dalio's *How the Economic Machine Works*, central-bank explainers, and long-form macro interviews.
        - **Free tools:** FRED, TradingEconomics, Koyfin free tier, Yahoo Finance, World Bank Data.
        - **Indonesia-specific:** Bank Indonesia, BPS Statistics Indonesia, IDX investor data, Ministry of Finance releases.
        """
    )


def main() -> None:
    css()
    st.sidebar.title("🧠 MacroLens")
    st.sidebar.caption("Macro intelligence + self-education for investors")
    light_mode = st.sidebar.toggle("Light mode", value=False)
    if light_mode:
        st.sidebar.info("Light mode toggle saved for UX; dark mode remains default in this prototype.")
    data = load_market_data()
    regime, confidence, scores = classify_regime(data)
    render_regime_banner(regime, confidence)
    st.caption(f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} • Live market data uses Yahoo Finance when available; macro placeholders keep the UI stable when free APIs fail.")
    dashboard, news, strategy, learn = st.tabs(["Dashboard", "News", "Strategy", "Learn"])
    with dashboard:
        render_dashboard(data, regime)
    with news:
        render_news(regime)
    with strategy:
        render_strategy(regime, data)
    with learn:
        render_learn()


if __name__ == "__main__":
    main()
