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
text = text.replace(old, new, 1)
old_assertion = "        assert placed_at == first.response_received_at\n"
new_assertion = "        assert placed_at.replace(tzinfo=UTC) == first.response_received_at\n"
if old_assertion not in text:
    raise SystemExit("finalize helper placement chronology assertion target not found")
path.write_text(text.replace(old_assertion, new_assertion, 1), encoding="utf-8")
