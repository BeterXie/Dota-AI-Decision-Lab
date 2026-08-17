from pathlib import Path

path = Path("tools/temporary_finalize_tournament_portfolio.py")
text = path.read_text(encoding="utf-8")
old = '''                    "market_log_loss": (
                        float(market_loss) if market_loss is not None else None
                    ),
'''
new = '''                    "market_log_loss": (float(market_loss) if market_loss is not None else None),
'''
if old not in text:
    raise SystemExit("finalize helper already differs from expected pre-Ruff market_log_loss block")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
