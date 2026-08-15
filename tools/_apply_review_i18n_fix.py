from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1))


# Add all review copy to the shared dictionary instead of local bilingual ternaries.
en_anchor = '''    backToMatches: "Back to match list",
    filterMatches: "Filter matches",
    selectMatchPrompt: "Select a match from the directory to inspect AI decisions, odds telemetry, and draft intelligence."
'''
en_replacement = '''    backToMatches: "Back to match list",
    filterMatches: "Filter matches",
    reviewLiveDashboard: "Live dashboard",
    reviewTitle: "Match Review",
    reviewHeadline: "One view for draft, AI and market performance",
    reviewDescription: "R.O.S.H. uses the curve frozen in the original DecisionSnapshot. AI reruns count once per checkpoint, and the odds start is the first decision-eligible snapshot rather than a claimed bookmaker open.",
    reviewNoLeakage: "No post-match leakage",
    reviewLoading: "Loading review data…",
    reviewSettledMaps: "Settled maps",
    reviewRoshPure: "R.O.S.H. pure",
    reviewRoshAdjusted: "R.O.S.H. adjusted",
    reviewClosingCoverage: "Closing odds coverage",
    reviewModelPerformance: "Model performance",
    reviewModelHint: "BUY accuracy counts BUY_A / BUY_B only; lower Brier is better",
    reviewNoEvaluatedAi: "No evaluated AI decisions yet",
    reviewLedger: "Review ledger",
    reviewSearchPlaceholder: "Search team / event",
    reviewFilterAll: "All",
    reviewFilterRoshMiss: "ROSH misses",
    reviewFilterAiBuy: "AI BUY",
    reviewFilterClosing: "Closing captured",
    reviewNoMatches: "No matches for this filter",
    reviewBuyAccuracy: "BUY accuracy",
    reviewOneUnitRoi: "1-unit ROI",
    reviewRounds: "Rounds",
    reviewNoAuditableDraft: "No auditable draft snapshot",
    reviewFinalMapResult: "Final map result",
    reviewAiDecisions: "AI decisions",
    reviewOddsMovement: "Odds movement",
    reviewClosing: "closing",
    reviewLastDecision: "last decision",
    reviewNoValidOdds: "No valid odds pair",
    reviewCorrect: "correct",
    reviewNoSettledBuy: "no settled BUY",
    reviewNA: "N/A",
    reviewWinnerTitle: "Winner",
    selectMatchPrompt: "Select a match from the directory to inspect AI decisions, odds telemetry, and draft intelligence."
'''
replace("frontend/src/i18n.tsx", en_anchor, en_replacement)

zh_anchor = '''    backToMatches: "返回比赛列表",
    filterMatches: "筛选比赛",
    selectMatchPrompt: "从比赛列表中选择一场比赛，以查看 AI 决策快照、赔率走势与选人情报。"
'''
zh_replacement = '''    backToMatches: "返回比赛列表",
    filterMatches: "筛选比赛",
    reviewLiveDashboard: "实时看盘",
    reviewTitle: "比赛复盘",
    reviewHeadline: "用同一张表看阵容、AI 与市场到底准不准",
    reviewDescription: "R.O.S.H. 使用当时冻结的 DecisionSnapshot 阵容曲线；AI 重跑按同一 checkpoint 只计一次；赔率起点是首个可决策快照，不伪装成真实开盘价。",
    reviewNoLeakage: "无赛后信息回填",
    reviewLoading: "正在读取复盘数据…",
    reviewSettledMaps: "已结算地图",
    reviewRoshPure: "R.O.S.H. 纯阵容",
    reviewRoshAdjusted: "R.O.S.H. 选手修正",
    reviewClosingCoverage: "收盘赔率覆盖",
    reviewModelPerformance: "模型整体表现",
    reviewModelHint: "BUY 命中只统计 BUY_A / BUY_B；Brier 越低越好",
    reviewNoEvaluatedAi: "暂无已评估 AI 决策",
    reviewLedger: "复盘比赛列表",
    reviewSearchPlaceholder: "搜索队伍 / 赛事",
    reviewFilterAll: "全部",
    reviewFilterRoshMiss: "ROSH 错误",
    reviewFilterAiBuy: "有 AI BUY",
    reviewFilterClosing: "有收盘",
    reviewNoMatches: "当前筛选条件没有比赛",
    reviewBuyAccuracy: "BUY 命中",
    reviewOneUnitRoi: "1单位 ROI",
    reviewRounds: "决策轮数",
    reviewNoAuditableDraft: "无可审计阵容快照",
    reviewFinalMapResult: "最终 Map 结果",
    reviewAiDecisions: "AI 决策",
    reviewOddsMovement: "赔率变化",
    reviewClosing: "收盘",
    reviewLastDecision: "最后决策",
    reviewNoValidOdds: "无有效赔率对",
    reviewCorrect: "命中",
    reviewNoSettledBuy: "无已结算 BUY",
    reviewNA: "暂无",
    reviewWinnerTitle: "获胜方",
    selectMatchPrompt: "从比赛列表中选择一场比赛，以查看 AI 决策快照、赔率走势与选人情报。"
'''
replace("frontend/src/i18n.tsx", zh_anchor, zh_replacement)

# ReviewPage now consumes the shared dictionary. Locale remains only for numeric/date formatting.
path = Path("frontend/src/components/ReviewPage.tsx")
text = path.read_text()
text = text.replace(
    'import { useI18n } from "../i18n";',
    'import { translate, useI18n, type Locale } from "../i18n";',
)
text = text.replace('  const { locale, setLocale } = useI18n();', '  const { locale, setLocale, t } = useI18n();')
replacements = {
    '{locale === "zh-CN" ? "实时看盘" : "Live dashboard"}': '{t("reviewLiveDashboard")}',
    '{locale === "zh-CN" ? "比赛复盘" : "Match Review"}': '{t("reviewTitle")}',
    '{locale === "zh-CN" ? "刷新" : "Refresh"}': '{t("refreshData")}',
    '{locale === "zh-CN" ? "用同一张表看阵容、AI 与市场到底准不准" : "One view for draft, AI and market performance"}': '{t("reviewHeadline")}',
    '''{locale === "zh-CN"
              ? "R.O.S.H. 使用当时冻结的 DecisionSnapshot 阵容曲线；AI 重跑按同一 checkpoint 只计一次；赔率起点是首个可决策快照，不伪装成真实开盘价。"
              : "R.O.S.H. uses the curve frozen in the original DecisionSnapshot. AI reruns count once per checkpoint, and the odds start is the first decision-eligible snapshot rather than a claimed bookmaker open."}''': '{t("reviewDescription")}',
    '{locale === "zh-CN" ? "无赛后信息回填" : "No post-match leakage"}': '{t("reviewNoLeakage")}',
    '{locale === "zh-CN" ? "正在读取复盘数据…" : "Loading review data…"}': '{t("reviewLoading")}',
    'label={locale === "zh-CN" ? "已结算地图" : "Settled maps"}': 'label={t("reviewSettledMaps")}',
    'label={locale === "zh-CN" ? `R.O.S.H. 纯阵容 ${summary.rosh.reference_minute}m` : `R.O.S.H. pure ${summary.rosh.reference_minute}m`}': 'label={`${t("reviewRoshPure")} ${summary.rosh.reference_minute}m`}',
    'label={locale === "zh-CN" ? `R.O.S.H. 选手修正 ${summary.rosh.reference_minute}m` : `R.O.S.H. adjusted ${summary.rosh.reference_minute}m`}': 'label={`${t("reviewRoshAdjusted")} ${summary.rosh.reference_minute}m`}',
    'label={locale === "zh-CN" ? "收盘赔率覆盖" : "Closing odds coverage"}': 'label={t("reviewClosingCoverage")}',
    '{locale === "zh-CN" ? "模型整体表现" : "Model performance"}': '{t("reviewModelPerformance")}',
    '{locale === "zh-CN" ? "BUY 命中只统计 BUY_A / BUY_B；Brier 越低越好" : "BUY accuracy counts BUY_A / BUY_B only; lower Brier is better"}': '{t("reviewModelHint")}',
    '{locale === "zh-CN" ? "暂无已评估 AI 决策" : "No evaluated AI decisions yet"}': '{t("reviewNoEvaluatedAi")}',
    '{locale === "zh-CN" ? "复盘比赛列表" : "Review ledger"}': '{t("reviewLedger")}',
    'placeholder={locale === "zh-CN" ? "搜索队伍 / 赛事" : "Search team / event"}': 'placeholder={t("reviewSearchPlaceholder")}',
    '["ALL", locale === "zh-CN" ? "全部" : "All"]': '["ALL", t("reviewFilterAll")]',
    '["ROSH_WRONG", locale === "zh-CN" ? "ROSH 错误" : "ROSH misses"]': '["ROSH_WRONG", t("reviewFilterRoshMiss")]',
    '["AI_BUY", locale === "zh-CN" ? "有 AI BUY" : "AI BUY"]': '["AI_BUY", t("reviewFilterAiBuy")]',
    '["CLOSING", locale === "zh-CN" ? "有收盘" : "Closing captured"]': '["CLOSING", t("reviewFilterClosing")]',
    '{locale === "zh-CN" ? "当前筛选条件没有比赛" : "No matches for this filter"}': '{t("reviewNoMatches")}',
}
for old_value, new_value in replacements.items():
    if old_value not in text:
        raise SystemExit(f"ReviewPage top-level i18n anchor missing: {old_value[:90]!r}")
    text = text.replace(old_value, new_value)

text = text.replace('function ModelSummary({ item, locale }: { item: ReviewAiGroup; locale: string }) {', 'function ModelSummary({ item, locale }: { item: ReviewAiGroup; locale: Locale }) {')
text = text.replace('function MatchReviewCard({ match, locale }: { match: ReviewMatch; locale: string }) {', 'function MatchReviewCard({ match, locale }: { match: ReviewMatch; locale: Locale }) {')
text = text.replace('function AiBadge({ item, match, locale }: { item: ReviewAiGroup; match: ReviewMatch; locale: string }) {', 'function AiBadge({ item, match, locale }: { item: ReviewAiGroup; match: ReviewMatch; locale: Locale }) {')
text = text.replace('function accuracyLabel(correct: number, evaluated: number, locale: string): string {', 'function accuracyLabel(correct: number, evaluated: number, locale: Locale): string {')
text = text.replace('function rate(value: number | null, locale: string): string {', 'function rate(value: number | null, locale: Locale): string {')
text = text.replace('function formatDate(value: string, locale: string): string {', 'function formatDate(value: string, locale: Locale): string {')
child_replacements = {
    'label={locale === "zh-CN" ? "BUY 命中" : "BUY accuracy"}': 'label={translate("reviewBuyAccuracy", locale)}',
    'label={locale === "zh-CN" ? "1单位 ROI" : "1-unit ROI"}': 'label={translate("reviewOneUnitRoi", locale)}',
    'label={locale === "zh-CN" ? "决策轮数" : "Rounds"}': 'label={translate("reviewRounds", locale)}',
    'label={locale === "zh-CN" ? "纯阵容" : "Pure"}': 'label={translate("pure", locale)}',
    'label={locale === "zh-CN" ? "选手修正" : "Adjusted"}': 'label={translate("playerAdjusted", locale)}',
    '{locale === "zh-CN" ? "无可审计阵容快照" : "No auditable draft snapshot"}': '{translate("reviewNoAuditableDraft", locale)}',
    '{locale === "zh-CN" ? "获胜方" : "Winner"}': '{translate("winner", locale)}',
    '{locale === "zh-CN" ? "最终 Map 结果" : "Final map result"}': '{translate("reviewFinalMapResult", locale)}',
    '{locale === "zh-CN" ? "AI 决策" : "AI decisions"}': '{translate("reviewAiDecisions", locale)}',
    '{locale === "zh-CN" ? "赔率变化" : "Odds movement"}': '{translate("reviewOddsMovement", locale)}',
    '(locale === "zh-CN" ? "收盘" : "closing")': 'translate("reviewClosing", locale)',
    '(locale === "zh-CN" ? "最后决策" : "last decision")': 'translate("reviewLastDecision", locale)',
    '{locale === "zh-CN" ? "无有效赔率对" : "No valid odds pair"}': '{translate("reviewNoValidOdds", locale)}',
    '${locale === "zh-CN" ? "命中" : "correct"}': '${translate("reviewCorrect", locale)}',
    '(locale === "zh-CN" ? "无已结算 BUY" : "no settled BUY")': 'translate("reviewNoSettledBuy", locale)',
    '(locale === "zh-CN" ? "暂无" : "N/A")': 'translate("reviewNA", locale)',
}
for old_value, new_value in child_replacements.items():
    if old_value not in text:
        raise SystemExit(f"ReviewPage child i18n anchor missing: {old_value!r}")
    text = text.replace(old_value, new_value)

# Winner tooltip follows the active locale too.
text = text.replace(
    '<TeamName team={match.team_a.name} winner={winnerA} />',
    '<TeamName team={match.team_a.name} winner={winnerA} winnerTitle={translate("reviewWinnerTitle", locale)} />',
)
text = text.replace(
    '<TeamName team={match.team_b.name} winner={winnerB} />',
    '<TeamName team={match.team_b.name} winner={winnerB} winnerTitle={translate("reviewWinnerTitle", locale)} />',
)
text = text.replace(
    'function TeamName({ team, winner }: { team: string; winner: boolean }) {\n  return <strong className={winner ? "review-team winner" : "review-team"}>{team}{winner && <span className="winner-trophy" title="Winner">🏆</span>}</strong>;\n}',
    'function TeamName({ team, winner, winnerTitle }: { team: string; winner: boolean; winnerTitle: string }) {\n  return <strong className={winner ? "review-team winner" : "review-team"}>{team}{winner && <span className="winner-trophy" title={winnerTitle}>🏆</span>}</strong>;\n}',
)
path.write_text(text)

# Make the no-leakage regression fixture truly two snapshots of the same map.
path = Path("tests/test_review_api.py")
text = path.read_text()
text = text.replace(
    '''    curve_points: list[dict] | None = None,
) -> DecisionSnapshotRecord:
    return DecisionSnapshotRecord(
        id=uuid4(),
        canonical_map_id=uuid4(),
''',
    '''    curve_points: list[dict] | None = None,
    canonical_map_id: UUID | None = None,
) -> DecisionSnapshotRecord:
    return DecisionSnapshotRecord(
        id=uuid4(),
        canonical_map_id=canonical_map_id or uuid4(),
''',
    1,
)
old = '''    team_a_id, team_b_id = uuid4(), uuid4()
    early = _review_snapshot_record(
        decision_at=now,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
'''
new = '''    team_a_id, team_b_id = uuid4(), uuid4()
    canonical_map_id = uuid4()
    early = _review_snapshot_record(
        decision_at=now,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        canonical_map_id=canonical_map_id,
'''
if old not in text:
    raise SystemExit("R.O.S.H. same-map early fixture anchor missing")
text = text.replace(old, new, 1)
old = '''    late = _review_snapshot_record(
        decision_at=now + timedelta(minutes=5),
        team_a_id=team_a_id,
        team_b_id=team_b_id,
'''
new = '''    late = _review_snapshot_record(
        decision_at=now + timedelta(minutes=5),
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        canonical_map_id=canonical_map_id,
'''
if old not in text:
    raise SystemExit("R.O.S.H. same-map late fixture anchor missing")
text = text.replace(old, new, 1)
path.write_text(text)

# Make the architecture contract explicit so "decision-eligible" cannot drift.
replace(
    "docs/ARCHITECTURE.md",
    "赔率起点定义为首个可决策 Snapshot 的 Winner market，而不是伪称 bookmaker open；终点优先使用已捕获 CLOSING，否则明确降级为最后一个有效 DecisionSnapshot market。",
    "赔率起点定义为首个可决策 Snapshot 的 Winner market，而不是伪称 bookmaker open；这里的“可决策”必须同时满足 Snapshot `quality.eligible=true`、Winner market `quality.eligible=true`，以及与生产 AI 完全相同的 `AI_MIN_GAME_TIME_SECONDS` 时间门槛（有 real-start anchor 时按真实经过时间，否则回退到 broadcast game clock）。终点优先使用已捕获 CLOSING，否则明确降级为最后一个满足上述条件的 DecisionSnapshot market。",
)
