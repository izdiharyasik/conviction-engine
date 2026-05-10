# MacroLens

MacroLens is a Streamlit macro intelligence and education platform for investors who want the **so what** behind macro data.

## Features

- Sticky macro-regime banner with weighted classification for Risk-On, Easing, Tightening, Stagflation, Risk-Off, and Crisis states.
- Dashboard indicator panels for fear/liquidity, growth/inflation, policy, risk assets, commodities, and Indonesia-specific markets.
- Asset conviction matrix mapping each regime to buy/avoid rankings across equities, bonds, commodities, gold, cash, and crypto.
- Macro-tagged Google News RSS feed with rule-based sentiment and plain-English investment implications.
- Strategy playbook with regime deep dive, sector rotation, historical analogies, and bull/bear scenarios.
- Learn hub with macro frameworks, searchable glossary, 10-module curriculum, and recommended resources.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Live data uses free Yahoo Finance endpoints where available. Missing macro series fall back to static placeholder values with a timestamp so the UI does not break.
