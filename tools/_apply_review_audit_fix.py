from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1))


# Keep record-based reconciliation and review eligibility aligned with the
# real-start-anchor-aware domain rule.
path = Path("app/ai/eligibility.py")
text = path.read_text()
old = '''def ai_decision_is_game_time_eligible(
    snapshot: DecisionSnapshot, *, min_game_time_seconds: int
) -> bool:
    """Decision eligibility on REAL elapsed time when the start anchor exists.

    The anchor is the series scheduled start (stored in snapshot quality
    live_anchors): DLTV broadcasts lag the real game, so the broadcast game
    clock cannot schedule decisions on real time.  When the anchor is known,
    eligibility uses real elapsed time since the scheduled start; otherwise it
    falls back to the broadcast game clock.
    """
    anchor_value = (snapshot.quality.get("live_anchors") or {}).get("real_start_anchor")
    if isinstance(anchor_value, str):
        try:
            anchor = datetime.fromisoformat(anchor_value.replace("Z", "+00:00"))
        except ValueError:
            anchor = None
        if anchor is not None and anchor.tzinfo is not None:
            elapsed = (snapshot.decision_at - anchor).total_seconds()
            return elapsed >= min_game_time_seconds
    game_time = ai_decision_live_game_time(snapshot)
    return game_time is not None and game_time >= min_game_time_seconds


def ai_record_is_game_time_eligible(
    canonical_payload: dict[str, Any], *, min_game_time_seconds: int
) -> bool:
    game_time = ai_record_live_game_time(canonical_payload)
    return game_time is not None and game_time >= min_game_time_seconds
'''
new = '''def ai_decision_is_game_time_eligible(
    snapshot: DecisionSnapshot, *, min_game_time_seconds: int
) -> bool:
    """Decision eligibility on REAL elapsed time when the start anchor exists.

    The anchor is the series scheduled start (stored in snapshot quality
    live_anchors): DLTV broadcasts lag the real game, so the broadcast game
    clock cannot schedule decisions on real time.  When the anchor is known,
    eligibility uses real elapsed time since the scheduled start; otherwise it
    falls back to the broadcast game clock.
    """
    return _is_game_time_eligible(
        quality=snapshot.quality,
        live=snapshot.live,
        decision_at=snapshot.decision_at,
        min_game_time_seconds=min_game_time_seconds,
    )


def ai_record_is_game_time_eligible(
    canonical_payload: dict[str, Any],
    *,
    min_game_time_seconds: int,
    decision_at: datetime | None = None,
) -> bool:
    resolved_decision_at = decision_at or _payload_datetime(canonical_payload.get("decision_at"))
    quality = canonical_payload.get("quality")
    live = canonical_payload.get("live")
    return _is_game_time_eligible(
        quality=quality if isinstance(quality, dict) else {},
        live=live,
        decision_at=resolved_decision_at,
        min_game_time_seconds=min_game_time_seconds,
    )


def _is_game_time_eligible(
    *,
    quality: dict[str, Any],
    live: object,
    decision_at: datetime | None,
    min_game_time_seconds: int,
) -> bool:
    anchor_value = (quality.get("live_anchors") or {}).get("real_start_anchor")
    if decision_at is not None and isinstance(anchor_value, str):
        try:
            anchor = datetime.fromisoformat(anchor_value.replace("Z", "+00:00"))
        except ValueError:
            anchor = None
        if anchor is not None and anchor.tzinfo is not None and decision_at.tzinfo is not None:
            return (decision_at - anchor).total_seconds() >= min_game_time_seconds
    game_time = _live_game_time_seconds(live)
    return game_time is not None and game_time >= min_game_time_seconds


def _payload_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None
'''
if old not in text:
    raise SystemExit("eligibility function block changed")
path.write_text(text.replace(old, new, 1))

# Review endpoint: explicit audit eligibility, exact minute semantics, safe
# closing timestamps, and a small anti-stampede TTL cache.
replace(
    "app/web/review.py",
    "from collections import defaultdict\nfrom statistics import mean\nfrom typing import Any\nfrom uuid import UUID\n",
    "import asyncio\nfrom collections import defaultdict\nfrom statistics import mean\nfrom time import monotonic\nfrom typing import Any\nfrom uuid import UUID\n",
)
replace(
    "app/web/review.py",
    "from app.market.fair_probability import remove_vig\n",
    "from app.ai.eligibility import ai_record_is_game_time_eligible\nfrom app.market.fair_probability import remove_vig\n",
)
replace(
    "app/web/review.py",
    "ROSH_REFERENCE_MINUTE = 30\nROSH_REVIEW_MINUTES = (20, 30, 40)\n_ROSH_EVEN_EPSILON = 0.05\n",
    "ROSH_REFERENCE_MINUTE = 30\nROSH_REVIEW_MINUTES = (20, 30, 40)\nREVIEW_CACHE_TTL_SECONDS = 15.0\n_ROSH_EVEN_EPSILON = 0.05\n",
)
replace(
    "app/web/review.py",
    '''def create_review_router(
    session_factory: async_sessionmaker[AsyncSession],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/review/matches")
    async def review_matches(
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        async with session_factory() as session:
            return await build_review_payload(session, limit=limit)

    return router


async def build_review_payload(session: AsyncSession, *, limit: int = 100) -> dict[str, Any]:
''',
    '''def create_review_router(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    ai_min_game_time_seconds: int = 600,
    cache_ttl_seconds: float = REVIEW_CACHE_TTL_SECONDS,
) -> APIRouter:
    router = APIRouter()
    cache: dict[int, tuple[float, dict[str, Any]]] = {}
    cache_lock = asyncio.Lock()

    @router.get("/api/review/matches")
    async def review_matches(
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        now = monotonic()
        cached = cache.get(limit)
        if cached is not None and now - cached[0] < cache_ttl_seconds:
            return cached[1]
        async with cache_lock:
            now = monotonic()
            cached = cache.get(limit)
            if cached is not None and now - cached[0] < cache_ttl_seconds:
                return cached[1]
            async with session_factory() as session:
                payload = await build_review_payload(
                    session,
                    limit=limit,
                    ai_min_game_time_seconds=ai_min_game_time_seconds,
                )
            cache[limit] = (monotonic(), payload)
            return payload

    return router


async def build_review_payload(
    session: AsyncSession,
    *,
    limit: int = 100,
    ai_min_game_time_seconds: int = 600,
) -> dict[str, Any]:
''',
)
replace(
    "app/web/review.py",
    '''                "odds": _odds_review(
                    map_snapshots,
                    closings=closings_by_map.get(canonical_map.id, []),
                ),
''',
    '''                "odds": _odds_review(
                    map_snapshots,
                    closings=closings_by_map.get(canonical_map.id, []),
                    ai_min_game_time_seconds=ai_min_game_time_seconds,
                ),
''',
)
path = Path("app/web/review.py")
path.write_text(
    path.read_text().replace(
        "EARLIEST_VALID_DECISION_SNAPSHOT_MARKET",
        "EARLIEST_AI_ELIGIBLE_SNAPSHOT_WITH_ELIGIBLE_MARKET",
    )
)
replace(
    "app/web/review.py",
    '''    review_points = []
    for minute in ROSH_REVIEW_MINUTES:
        point = _curve_point(points, minute)
        pure = _number(point.get("pure_radiant_edge")) if point is not None else None
        adjusted = _number(point.get("adjusted_radiant_edge")) if point is not None else None
        review_points.append(
            {
                "minute": minute,
                "pure": _rosh_edge_payload(pure, side_identity, winner_team_id),
                "adjusted": _rosh_edge_payload(adjusted, side_identity, winner_team_id),
            }
        )

    reference = next(
        (item for item in review_points if item["minute"] == ROSH_REFERENCE_MINUTE),
        None,
    )
''',
    '''    review_points = []
    reference = None
    for minute in ROSH_REVIEW_MINUTES:
        point = _curve_point(points, minute)
        pure = _number(point.get("pure_radiant_edge")) if point is not None else None
        adjusted = _number(point.get("adjusted_radiant_edge")) if point is not None else None
        review_point = {
            "minute": minute,
            "pure": _rosh_edge_payload(pure, side_identity, winner_team_id),
            "adjusted": _rosh_edge_payload(adjusted, side_identity, winner_team_id),
        }
        review_points.append(review_point)
        if minute == ROSH_REFERENCE_MINUTE and point is not None:
            reference = review_point
''',
)
replace(
    "app/web/review.py",
    '''def _curve_point(points: list[Any], minute: int) -> dict[str, Any] | None:
    candidates = [
        item
        for item in points
        if isinstance(item, dict) and _number(item.get("minute")) is not None
    ]
    if not candidates:
        return None
    exact = next(
        (item for item in candidates if _number(item.get("minute")) == float(minute)), None
    )
    if exact is not None:
        return exact
    nearest = min(candidates, key=lambda item: abs((_number(item.get("minute")) or 0.0) - minute))
    nearest_minute = _number(nearest.get("minute"))
    if nearest_minute is None or abs(nearest_minute - minute) > 1.0:
        return None
    return nearest
''',
    '''def _curve_point(points: list[Any], minute: int) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in points
            if isinstance(item, dict) and _number(item.get("minute")) == float(minute)
        ),
        None,
    )
''',
)
replace(
    "app/web/review.py",
    '''def _odds_review(
    snapshots: list[DecisionSnapshotRecord],
    *,
    closings: list[DecisionFutureOdds],
) -> dict[str, Any] | None:
    pairs = [
        pair for snapshot in snapshots if (pair := _snapshot_market_pair(snapshot)) is not None
    ]
''',
    '''def _odds_review(
    snapshots: list[DecisionSnapshotRecord],
    *,
    closings: list[DecisionFutureOdds],
    ai_min_game_time_seconds: int = 600,
) -> dict[str, Any] | None:
    pairs = [
        pair
        for snapshot in snapshots
        if (
            pair := _snapshot_market_pair(
                snapshot,
                min_game_time_seconds=ai_min_game_time_seconds,
            )
        )
        is not None
    ]
''',
)
replace(
    "app/web/review.py",
    '''        and item.odds_b > 1
        and item.status == "CAPTURED"
    ]
''',
    '''        and item.odds_b > 1
        and item.status == "CAPTURED"
        and (item.observed_at is not None or item.triggered_at is not None)
    ]
''',
)
replace(
    "app/web/review.py",
    '''def _snapshot_market_pair(snapshot: DecisionSnapshotRecord) -> dict[str, Any] | None:
    payload = snapshot.canonical_payload
    identity = payload.get("identity") if isinstance(payload, dict) else None
    market = payload.get("market") if isinstance(payload, dict) else None
    if not isinstance(identity, dict) or not isinstance(market, dict):
        return None
''',
    '''def _snapshot_market_pair(
    snapshot: DecisionSnapshotRecord,
    *,
    min_game_time_seconds: int = 600,
) -> dict[str, Any] | None:
    payload = snapshot.canonical_payload
    identity = payload.get("identity") if isinstance(payload, dict) else None
    market = payload.get("market") if isinstance(payload, dict) else None
    snapshot_quality = payload.get("quality") if isinstance(payload, dict) else None
    market_quality = market.get("quality") if isinstance(market, dict) else None
    if (
        not isinstance(identity, dict)
        or not isinstance(market, dict)
        or not isinstance(snapshot_quality, dict)
        or snapshot_quality.get("eligible") is not True
        or not isinstance(market_quality, dict)
        or market_quality.get("eligible") is not True
        or not ai_record_is_game_time_eligible(
            payload,
            decision_at=snapshot.decision_at,
            min_game_time_seconds=min_game_time_seconds,
        )
    ):
        return None
''',
)

# Thread the configured production threshold into the web layer.
replace(
    "app/web/api.py",
    "    market_max_pair_skew_seconds: float = 5.0,\n) -> FastAPI:\n",
    "    market_max_pair_skew_seconds: float = 5.0,\n    ai_min_game_time_seconds: int = 600,\n) -> FastAPI:\n",
)
replace(
    "app/web/api.py",
    "    app.include_router(create_review_router(session_factory))\n",
    '''    app.include_router(
        create_review_router(
            session_factory,
            ai_min_game_time_seconds=ai_min_game_time_seconds,
        )
    )
''',
)
replace(
    "app/web/__init__.py",
    "    market_max_pair_skew_seconds: float = 5.0,\n) -> FastAPI:\n",
    "    market_max_pair_skew_seconds: float = 5.0,\n    ai_min_game_time_seconds: int = 600,\n) -> FastAPI:\n",
)
replace(
    "app/web/__init__.py",
    "        market_max_pair_skew_seconds=market_max_pair_skew_seconds,\n    )\n",
    "        market_max_pair_skew_seconds=market_max_pair_skew_seconds,\n        ai_min_game_time_seconds=ai_min_game_time_seconds,\n    )\n",
)
replace(
    "app/main.py",
    "        market_max_pair_skew_seconds=settings.market_max_pair_skew_seconds,\n    )\n",
    "        market_max_pair_skew_seconds=settings.market_max_pair_skew_seconds,\n        ai_min_game_time_seconds=settings.ai_min_game_time_seconds,\n    )\n",
)

# Exact /review route only, not /reviewfoo.
replace(
    "frontend/src/App.tsx",
    '''export function App() {
  const reviewRoute = typeof window !== "undefined" && window.location.pathname.startsWith("/review");
''',
    '''export function App() {
  const reviewRoute = typeof window !== "undefined" && isReviewRoute(window.location.pathname);
''',
)
replace(
    "frontend/src/App.tsx",
    "\nfunction DashboardApp() {\n",
    '''
export function isReviewRoute(pathname: string): boolean {
  return pathname === "/review" || pathname.startsWith("/review/");
}

function DashboardApp() {
''',
)
replace(
    "frontend/src/components/ReviewPage.tsx",
    '''    queryFn: () => fetchReviewMatches(100),
    refetchInterval: 30_000
''',
    '''    queryFn: () => fetchReviewMatches(100),
    staleTime: 30_000,
    refetchInterval: 60_000
''',
)

# Existing review fixture now carries the same eligibility fields as production snapshots.
replace(
    "tests/test_review_api.py",
    '''                "market": {
                    "market_type": "Winner",
''',
    '''                "market": {
                    "quality": {"eligible": True, "blockers": [], "warnings": []},
                    "market_type": "Winner",
''',
)
replace(
    "tests/test_review_api.py",
    '''                "draft": {
''',
    '''                "quality": {"eligible": True, "blockers": [], "warnings": []},
                "live": {"game_time_seconds": 1800},
                "draft": {
''',
)
replace(
    "tests/test_review_api.py",
    "from decimal import Decimal\nfrom uuid import uuid4\n",
    "from decimal import Decimal\nfrom types import SimpleNamespace\nfrom uuid import UUID, uuid4\n",
)
replace(
    "tests/test_review_api.py",
    "from app.web.api import create_app\n",
    "from app.web.api import create_app\nfrom app.web.review import _odds_review, _rosh_review, _snapshot_market_pair\n",
)
path = Path("tests/test_review_api.py")
text = path.read_text()
marker = "\n\n@pytest.mark.asyncio\nasync def test_review_api_empty_contract() -> None:\n"
if marker not in text:
    raise SystemExit("review test insertion anchor missing")
extra = r'''


def _review_snapshot_record(
    *,
    decision_at: datetime,
    team_a_id: UUID,
    team_b_id: UUID,
    game_time_seconds: int = 700,
    snapshot_eligible: bool = True,
    market_eligible: bool = True,
    curve_points: list[dict] | None = None,
) -> DecisionSnapshotRecord:
    return DecisionSnapshotRecord(
        id=uuid4(),
        canonical_map_id=uuid4(),
        decision_at=decision_at,
        created_at=decision_at,
        mode="LIVE_BASIC",
        snapshot_hash=f"review-{uuid4()}",
        canonical_payload={
            "decision_at": decision_at.isoformat(),
            "identity": {
                "team_a": {"id": str(team_a_id), "name": "A"},
                "team_b": {"id": str(team_b_id), "name": "B"},
                "side_identity": {
                    "status": "RESOLVED",
                    "radiant_team_id": str(team_a_id),
                    "dire_team_id": str(team_b_id),
                },
            },
            "quality": {"eligible": snapshot_eligible, "blockers": [], "warnings": []},
            "live": {"game_time_seconds": game_time_seconds},
            "market": {
                "quality": {"eligible": market_eligible, "blockers": [], "warnings": []},
                "observations": [
                    {"selection_team_id": str(team_a_id), "price": "2.20"},
                    {"selection_team_id": str(team_b_id), "price": "1.70"},
                ],
            },
            "draft": {
                "curve": {
                    "model_version": "rosh-test",
                    "data_version": "data-test",
                    "points": curve_points or [],
                }
            },
        },
    )


def test_review_odds_start_requires_snapshot_market_and_ai_time_eligibility() -> None:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    team_a_id, team_b_id = uuid4(), uuid4()
    assert _snapshot_market_pair(
        _review_snapshot_record(
            decision_at=now,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            game_time_seconds=599,
        )
    ) is None
    assert _snapshot_market_pair(
        _review_snapshot_record(
            decision_at=now,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            market_eligible=False,
        )
    ) is None
    assert _snapshot_market_pair(
        _review_snapshot_record(
            decision_at=now,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            snapshot_eligible=False,
        )
    ) is None
    eligible = _snapshot_market_pair(
        _review_snapshot_record(
            decision_at=now,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            game_time_seconds=600,
        )
    )
    assert eligible is not None
    assert eligible["odds_a"] == 2.2


def test_rosh_review_keeps_earliest_frozen_curve_when_later_snapshot_changes() -> None:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    team_a_id, team_b_id = uuid4(), uuid4()
    early = _review_snapshot_record(
        decision_at=now,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        curve_points=[
            {"minute": 20, "pure_radiant_edge": 2.0, "adjusted_radiant_edge": 1.0},
            {"minute": 30, "pure_radiant_edge": 4.0, "adjusted_radiant_edge": -2.0},
            {"minute": 40, "pure_radiant_edge": 1.0, "adjusted_radiant_edge": -3.0},
        ],
    )
    late = _review_snapshot_record(
        decision_at=now + timedelta(minutes=5),
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        curve_points=[
            {"minute": 20, "pure_radiant_edge": -20.0, "adjusted_radiant_edge": 20.0},
            {"minute": 30, "pure_radiant_edge": -30.0, "adjusted_radiant_edge": 30.0},
            {"minute": 40, "pure_radiant_edge": -40.0, "adjusted_radiant_edge": 40.0},
        ],
    )
    review = _rosh_review([early, late], winner_team_id=team_a_id)
    assert review is not None
    assert review["snapshot_id"] == str(early.id)
    assert review["reference"]["pure"]["edge_pp"] == 4.0
    assert review["reference"]["adjusted"]["edge_pp"] == -2.0


def test_rosh_reference_requires_exact_30_minute_point() -> None:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    team_a_id, team_b_id = uuid4(), uuid4()
    snapshot = _review_snapshot_record(
        decision_at=now,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        curve_points=[
            {"minute": 29, "pure_radiant_edge": 4.0, "adjusted_radiant_edge": 2.0},
            {"minute": 31, "pure_radiant_edge": 5.0, "adjusted_radiant_edge": 3.0},
        ],
    )
    review = _rosh_review([snapshot], winner_team_id=team_a_id)
    assert review is not None
    assert review["reference"] is None
    assert next(item for item in review["points"] if item["minute"] == 30)["pure"]["edge_pp"] is None


def test_review_odds_ignores_capture_without_any_timestamp() -> None:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    team_a_id, team_b_id = uuid4(), uuid4()
    snapshot = _review_snapshot_record(
        decision_at=now,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
    )
    invalid_closing = SimpleNamespace(
        odds_a=Decimal("1.80"),
        odds_b=Decimal("2.05"),
        status="CAPTURED",
        observed_at=None,
        triggered_at=None,
    )
    review = _odds_review([snapshot], closings=[invalid_closing])
    assert review is not None
    assert review["end_kind"] == "LATEST_DECISION"
'''
path.write_text(text.replace(marker, extra + marker, 1))

# Record-based eligibility now has parity coverage with the domain path.
replace(
    "tests/test_ai_eligibility.py",
    "from app.ai.eligibility import ai_decision_is_game_time_eligible\n",
    "from app.ai.eligibility import ai_decision_is_game_time_eligible, ai_record_is_game_time_eligible\n",
)
path = Path("tests/test_ai_eligibility.py")
path.write_text(
    path.read_text()
    + r'''


def test_record_eligibility_uses_real_time_anchor_before_broadcast_clock() -> None:
    decision_at = datetime(2026, 8, 14, 3, 3, 15, tzinfo=UTC)
    payload = {
        "decision_at": decision_at.isoformat(),
        "quality": {
            "live_anchors": {
                "real_start_anchor": (decision_at - timedelta(minutes=5)).isoformat(),
            }
        },
        "live": {"game_time_seconds": 800},
    }
    assert ai_record_is_game_time_eligible(payload, min_game_time_seconds=600) is False
    payload["quality"]["live_anchors"]["real_start_anchor"] = (
        decision_at - timedelta(minutes=11)
    ).isoformat()
    assert ai_record_is_game_time_eligible(payload, min_game_time_seconds=600) is True
'''
)

# Route predicate contract.
replace(
    "frontend/src/App.test.tsx",
    'import { App } from "./App";\n',
    'import { App, isReviewRoute } from "./App";\n',
)
path = Path("frontend/src/App.test.tsx")
path.write_text(
    path.read_text()
    + r'''


test("review route predicate does not capture unrelated prefixes", () => {
  expect(isReviewRoute("/review")).toBe(true);
  expect(isReviewRoute("/review/map-1")).toBe(true);
  expect(isReviewRoute("/reviewfoo")).toBe(false);
  expect(isReviewRoute("/review-anything")).toBe(false);
});
'''
)
