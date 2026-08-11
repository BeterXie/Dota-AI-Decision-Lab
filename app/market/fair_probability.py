def remove_vig(odds_a: float, odds_b: float) -> tuple[float, float, float]:
    if odds_a <= 1 or odds_b <= 1:
        raise ValueError("decimal odds must be greater than one")
    implied_a = 1.0 / odds_a
    implied_b = 1.0 / odds_b
    overround = implied_a + implied_b
    return implied_a / overround, implied_b / overround, overround
