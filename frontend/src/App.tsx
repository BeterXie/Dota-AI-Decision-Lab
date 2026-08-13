import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchJobs,
  fetchMap,
  fetchMaps,
  fetchRuntime,
  type AiDecision,
  type JobSummary,
  type MapDetail,
  type MapSummary,
  type MarketObservation,
  queryKeys,
  type RuntimeSnapshot,
  useRuntimeSocket
} from "./api";
import {
  I18nProvider,
  translateDependency,
  translateStatus,
  useI18n,
  type Locale
} from "./i18n";
import IntelligenceChart from "./Chart";

const AI_ORDER = ["openai", "anthropic", "google", "deepseek", "kimi"];
const DEPENDENCY_ORDER = [
  "RAYBET_HTTP",
  "RAYBET_SOCKET",
  "DLTV_SOCKET",
  "DLTV_DRAFT",
  "LIVE_SYNC",
  "STRATZ",
  "DRAFT_ENGINE",
  "HISTORY",
  "GPT",
  "CLAUDE",
  "GEMINI",
  "DEEPSEEK",
  "KIMI",
  "EMAIL"
];

export function App() {
  return (
    <I18nProvider>
      <Dashboard />
    </I18nProvider>
  );
}

function Dashboard() {
  useRuntimeSocket();
  const { locale, setLocale, t } = useI18n();
  const queryClient = useQueryClient();
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);

  const runtime = useQuery({
    queryKey: queryKeys.runtime,
    queryFn: fetchRuntime,
    refetchInterval: 5000
  });
  const maps = useQuery({
    queryKey: queryKeys.maps,
    queryFn: fetchMaps,
    refetchInterval: 5000
  });
  const jobs = useQuery({
    queryKey: queryKeys.jobs,
    queryFn: fetchJobs,
    refetchInterval: 5000
  });

  useEffect(() => {
    if (!maps.data?.length) {
      setSelectedMapId(null);
      return;
    }
    if (!maps.data.some((match) => match.id === selectedMapId)) {
      setSelectedMapId(maps.data[0].id);
    }
  }, [maps.data, selectedMapId]);

  const selectedMatch = maps.data?.find((match) => match.id === selectedMapId);
  const selectedCanonicalMapId = selectedMatch?.canonical_map_id ?? null;

  const detail = useQuery({
    queryKey: selectedCanonicalMapId ? queryKeys.map(selectedCanonicalMapId) : ["map", "none"],
    queryFn: () => fetchMap(selectedCanonicalMapId!),
    enabled: Boolean(selectedCanonicalMapId),
    refetchInterval: 4000
  });

  const refresh = () => void queryClient.invalidateQueries();

  return (
    <div className="player-app" data-theme="dark">
      <TopBar
        locale={locale}
        setLocale={setLocale}
        overall={runtime.data?.overall ?? "UNKNOWN"}
        onDiagnostics={() => setDiagnosticsOpen(true)}
        onRefresh={refresh}
      />

      <div className="app-frame">
        <MatchRail
          maps={maps.data ?? []}
          loading={maps.isLoading}
          selectedId={selectedMapId}
          onSelect={setSelectedMapId}
        />

        <main className="main-workspace">
          {maps.isError ? (
            <ErrorState
              title={t("mapFeedUnavailable")}
              detail={errorMessage(maps.error, t("unknownError"))}
            />
          ) : !maps.data?.length ? (
            <EmptyWorkspace overall={runtime.data?.overall} />
          ) : selectedMatch?.identity_status === "PENDING_MAP_IDENTITY" ? (
            <PendingIdentityWorkspace match={selectedMatch} />
          ) : detail.isLoading && selectedCanonicalMapId ? (
            <WorkspaceSkeleton />
          ) : detail.isError ? (
            <ErrorState
              title={t("mapDetailUnavailable")}
              detail={errorMessage(detail.error, t("unknownError"))}
            />
          ) : detail.data ? (
            <PlayerMatchWorkspace
              detail={detail.data}
              runtime={runtime.data}
              jobs={jobs.data}
              onDiagnostics={() => setDiagnosticsOpen(true)}
            />
          ) : (
            <EmptyWorkspace overall={runtime.data?.overall} />
          )}
        </main>
      </div>

      <DiagnosticsDrawer
        open={diagnosticsOpen}
        onClose={() => setDiagnosticsOpen(false)}
        runtime={runtime.data}
        jobs={jobs.data}
        detail={detail.data}
      />
    </div>
  );
}

function TopBar({
  locale,
  setLocale,
  overall,
  onDiagnostics,
  onRefresh
}: {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  overall: string;
  onDiagnostics: () => void;
  onRefresh: () => void;
}) {
  const { t } = useI18n();
  return (
    <header className="topbar">
      <div className="brand-lockup">
        <div className="brand-mark">D</div>
        <div>
          <strong>DOTA AI</strong>
          <span>DECISION LAB</span>
        </div>
      </div>

      <div className="topbar-actions">
        <button className="system-pill" type="button" onClick={onDiagnostics}>
          <span className={`status-dot ${tone(overall)}`} />
          <span>{t("systemReadiness")}</span>
          <strong>{translateStatus(overall, locale)}</strong>
        </button>

        <div className="language-switcher" role="group" aria-label={t("language")}>
          <button
            type="button"
            className={locale === "zh-CN" ? "selected" : undefined}
            aria-pressed={locale === "zh-CN"}
            onClick={() => setLocale("zh-CN")}
          >
            中文
          </button>
          <button
            type="button"
            className={locale === "en" ? "selected" : undefined}
            aria-pressed={locale === "en"}
            onClick={() => setLocale("en")}
          >
            EN
          </button>
        </div>

        <button className="icon-button" type="button" onClick={onRefresh} aria-label={t("refreshData")}>
          ↻
        </button>
      </div>
    </header>
  );
}

function MatchRail({
  maps,
  loading,
  selectedId,
  onSelect
}: {
  maps: MapSummary[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { locale, t } = useI18n();

  if (loading) {
    return (
      <aside className="match-rail">
        <div className="rail-title"><span>{t("trackedMaps")}</span><strong>…</strong></div>
        <div className="rail-skeleton">{Array.from({ length: 4 }).map((_, i) => <span key={i} />)}</div>
      </aside>
    );
  }

  const live = maps.filter((m) => Boolean(m.live) || m.latest_snapshot?.mode?.startsWith("LIVE"));
  const upcoming = maps.filter((m) => !live.includes(m) && isFuture(m.scheduled_at));
  const tracked = maps.filter((m) => !live.includes(m) && !upcoming.includes(m));

  const sections = [
    { key: "live", label: ui(locale, "LIVE", "直播"), items: live },
    { key: "upcoming", label: ui(locale, "UPCOMING", "即将开始"), items: upcoming },
    { key: "tracked", label: ui(locale, "TRACKED", "追踪中"), items: tracked }
  ].filter((group) => group.items.length);

  return (
    <aside className="match-rail" aria-label={t("trackedMaps")}>
      <div className="rail-title">
        <span>{t("trackedMaps")}</span>
        <strong>{maps.length}</strong>
      </div>

      {!maps.length ? (
        <div className="rail-empty">
          <strong>{t("noCanonicalMaps")}</strong>
          <span>{t("waitingForProviderDiscovery")}</span>
        </div>
      ) : (
        <div className="rail-groups">
          {sections.map((section) => (
            <section className="rail-group" key={section.key}>
              <div className="rail-group-label">
                <span>{section.key === "live" && <i className="live-pulse" />}{section.label}</span>
                <small>{section.items.length}</small>
              </div>
              <div className="match-list">
                {section.items.map((map) => (
                  <MatchCard
                    key={map.id}
                    map={map}
                    selected={map.id === selectedId}
                    onSelect={() => onSelect(map.id)}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </aside>
  );
}

function MatchCard({
  map,
  selected,
  onSelect
}: {
  map: MapSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const { locale, t } = useI18n();
  const pair = primaryMarketPair(map.market, map.team_a?.id, map.team_b?.id);
  const isLive = Boolean(map.live) || map.latest_snapshot?.mode?.startsWith("LIVE");

  return (
    <button
      type="button"
      className={`match-card${selected ? " selected" : ""}`}
      onClick={onSelect}
    >
      <div className="match-card-meta">
        <span className={isLive ? "live-label" : ""}>
          {isLive ? `● ${formatGameTime(map.live?.game_time_seconds, locale)}` : formatSchedule(map.scheduled_at, locale)}
        </span>
        <span>{map.tournament_name ?? t("unknownTournament")}</span>
      </div>

      <div className="match-card-team">
        <strong>{map.team_a?.name ?? t("unknownTeam")}</strong>
        <b>{pair ? formatOdds(pair.teamA.price) : "—"}</b>
      </div>
      <div className="match-card-team">
        <strong>{map.team_b?.name ?? t("unknownTeam")}</strong>
        <b>{pair ? formatOdds(pair.teamB.price) : "—"}</b>
      </div>

      <div className="match-card-foot">
        <span>{map.entity_type === "MAP" ? `${t("map")} ${map.map_number ?? "?"}` : map.round ?? t("series")}</span>
        <span>{translateStatus(map.latest_snapshot?.mode ?? map.identity_status, locale)}</span>
      </div>
    </button>
  );
}

function PlayerMatchWorkspace({
  detail,
  runtime,
  jobs,
  onDiagnostics
}: {
  detail: MapDetail;
  runtime: RuntimeSnapshot | undefined;
  jobs: JobSummary | undefined;
  onDiagnostics: () => void;
}) {
  const { locale } = useI18n();
  const [tab, setTab] = useState<"overview" | "draft" | "history" | "evaluation">("overview");
  const quality = detail.latest_snapshot?.quality;
  const blockers = quality?.blockers ?? [];
  const warnings = quality?.warnings ?? [];
  const pair = primaryMarketPair(detail.market, detail.team_a?.id, detail.team_b?.id);

  return (
    <div className="match-page">
      <MatchHero detail={detail} pair={pair} />
      <DecisionTrustBanner detail={detail} blockers={blockers} warnings={warnings} />

      <AiDecisionStrip detail={detail} />

      <nav className="player-tabs" aria-label="Map intelligence views">
        {([
          ["overview", ui(locale, "Overview", "总览")],
          ["draft", ui(locale, "Draft", "阵容")],
          ["history", ui(locale, "History", "历史")],
          ["evaluation", ui(locale, "Evaluation", "评估")]
        ] as const).map(([key, label]) => (
          <button
            key={key}
            className={tab === key ? "active" : ""}
            onClick={() => setTab(key)}
            type="button"
          >
            {label}
          </button>
        ))}
        <button className="diagnostics-tab" type="button" onClick={onDiagnostics}>
          {ui(locale, "Diagnostics", "诊断")}
        </button>
      </nav>

      {tab === "overview" && (
        <OverviewTab detail={detail} pair={pair} />
      )}
      {tab === "draft" && <DraftDetail detail={detail} />}
      {tab === "history" && <HistoryDetail detail={detail} />}
      {tab === "evaluation" && <EvaluationDetail detail={detail} />}

      <footer className="page-footer">
        <span>{ui(locale, "Snapshot", "快照")} {shortHash(detail.latest_snapshot?.snapshot_hash)}</span>
        <span>{ui(locale, "Decision at", "决策时间")} {formatDateTime(detail.latest_snapshot?.decision_at, locale)}</span>
        <button type="button" onClick={onDiagnostics}>
          {ui(locale, "Open system diagnostics", "打开系统诊断")}
        </button>
      </footer>
    </div>
  );
}

function MatchHero({
  detail,
  pair
}: {
  detail: MapDetail;
  pair: ReturnType<typeof primaryMarketPair>;
}) {
  const { locale, t } = useI18n();
  const live = detail.live;

  return (
    <section className="match-hero card">
      <div className="match-hero-kicker">
        <span>{detail.tournament_name ?? t("unknownTournament")}</span>
        <i>•</i>
        <span>{detail.round ?? "—"}</span>
        <i>•</i>
        <span>{t("map")} {detail.map_number ?? "?"}</span>
        {live && <>
          <i>•</i>
          <strong className="live-chip">LIVE {formatGameTime(live.game_time_seconds, locale)}</strong>
        </>}
      </div>

      <div className="scoreboard">
        <TeamIdentity
          side="radiant"
          name={detail.team_a?.name ?? t("unknownTeam")}
          odds={pair ? pair.teamA.price : null}
        />

        <div className="scoreboard-center">
          {live?.radiant_kills != null && live?.dire_kills != null ? (
            <div className="kill-score">
              <strong>{live.radiant_kills}</strong>
              <span>:</span>
              <strong>{live.dire_kills}</strong>
            </div>
          ) : (
            <div className="versus-mark">VS</div>
          )}
          <div className="map-mode">{translateStatus(detail.latest_snapshot?.mode ?? "NO_SNAPSHOT", locale)}</div>
        </div>

        <TeamIdentity
          side="dire"
          name={detail.team_b?.name ?? t("unknownTeam")}
          odds={pair ? pair.teamB.price : null}
          align="right"
        />
      </div>

      <div className="hero-live-summary">
        <span>{ui(locale, "Net worth", "经济差")} <strong>{signedGold(live?.radiant_nw_lead, locale)}</strong></span>
        <span>{ui(locale, "First blood", "一血")} <strong>{firstBloodLabel(live?.first_blood, locale)}</strong></span>
        <span>{ui(locale, "Effective age", "有效状态年龄")} <strong>{seconds(live?.effective_state_age_seconds, locale)}</strong></span>
        <span>{ui(locale, "Sync", "同步")} <strong>{translateStatus(detail.sync?.status ?? "UNKNOWN", locale)}</strong></span>
      </div>
    </section>
  );
}

function TeamIdentity({
  side,
  name,
  odds,
  align
}: {
  side: "radiant" | "dire";
  name: string;
  odds: string | number | null;
  align?: "right";
}) {
  return (
    <div className={`team-identity ${side} ${align === "right" ? "right" : ""}`}>
      <div className="team-emblem" aria-hidden>{initials(name)}</div>
      <div>
        <span className="side-label">{side.toUpperCase()}</span>
        <h1>{name}</h1>
        <strong className="hero-odds">{formatOdds(odds)}</strong>
      </div>
    </div>
  );
}

function DecisionTrustBanner({
  detail,
  blockers,
  warnings
}: {
  detail: MapDetail;
  blockers: string[];
  warnings: string[];
}) {
  const { locale } = useI18n();
  const state = blockers.length ? "negative" : warnings.length ? "warning" : "positive";
  const title = blockers.length
    ? ui(locale, "Decision unavailable", "当前无法决策")
    : warnings.length
      ? ui(locale, "Decision available with limitations", "决策可用，但存在限制")
      : ui(locale, "Decision data ready", "决策数据已就绪");

  const subtitle = blockers.length
    ? blockers.map((x) => translateStatus(x, locale)).join(" · ")
    : warnings.length
      ? warnings.map((x) => translateStatus(x, locale)).join(" · ")
      : ui(locale, "Market, identity and data-quality checks passed", "市场、身份与数据质量检查通过");

  return (
    <section className={`trust-banner ${state}`}>
      <div className="trust-icon">{state === "positive" ? "✓" : state === "warning" ? "!" : "×"}</div>
      <div>
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </div>
      <div className="trust-mode">{translateStatus(detail.latest_snapshot?.mode ?? "NO_SNAPSHOT", locale)}</div>
    </section>
  );
}

function AiDecisionStrip({ detail }: { detail: MapDetail }) {
  const { locale } = useI18n();
  const sorted = [...detail.decisions].sort((a, b) => {
    const ai = AI_ORDER.indexOf(a.provider.toLowerCase());
    const bi = AI_ORDER.indexOf(b.provider.toLowerCase());
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
  });

  const probabilities = sorted
    .map((record) => record.decision?.fair_probability_a)
    .filter((value): value is number => typeof value === "number");
  const min = probabilities.length ? Math.min(...probabilities) : null;
  const max = probabilities.length ? Math.max(...probabilities) : null;
  const buyA = sorted.filter((r) => r.decision?.action === "BUY_A").length;
  const buyB = sorted.filter((r) => r.decision?.action === "BUY_B").length;
  const noBuy = sorted.filter((r) => r.decision?.action === "NO_BUY").length;

  return (
    <section className="ai-decision card">
      <div className="section-heading">
        <div>
          <span className="section-eyebrow">{ui(locale, "MULTI-AI ANALYSIS", "多模型分析")}</span>
          <h2>{ui(locale, "Independent AI decisions", "独立 AI 决策")}</h2>
        </div>
        <div className="agreement-summary">
          <span>{buyA} BUY A</span>
          <span>{buyB} BUY B</span>
          <span>{noBuy} NO BUY</span>
        </div>
      </div>

      {sorted.length ? (
        <div className="ai-card-row">
          {sorted.map((record) => <AiModelCard key={record.id} record={record} />)}
        </div>
      ) : (
        <div className="soft-empty">
          <strong>{ui(locale, "Waiting for AI decisions", "等待 AI 决策")}</strong>
          <span>{ui(locale, "The snapshot is preserved; model results will appear independently.", "快照已保留，各模型结果会独立出现。")}</span>
        </div>
      )}

      <div className="ai-range">
        <span>{ui(locale, "Fair probability A", "A 队公平概率")}</span>
        <div className="range-track">
          {min != null && max != null ? (
            <>
              <i style={{ left: `${Math.max(0, min * 100)}%`, width: `${Math.max(1, (max - min) * 100)}%` }} />
              <b style={{ left: `${Math.max(0, min * 100)}%` }}>{percent(min, locale)}</b>
              <b className="max" style={{ left: `${Math.min(96, max * 100)}%` }}>{percent(max, locale)}</b>
            </>
          ) : <em>{ui(locale, "No probability range yet", "暂无概率区间")}</em>}
        </div>
      </div>
    </section>
  );
}

function AiModelCard({ record }: { record: AiDecision }) {
  const { locale } = useI18n();
  const [open, setOpen] = useState(false);
  const action = record.decision?.action ?? record.parse_status;
  const probability = record.decision?.fair_probability_a;
  const confidence = record.decision?.confidence;

  return (
    <article className={`ai-model-card ${tone(action)}`}>
      <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <div className="ai-model-head">
          <strong>{providerName(record.provider)}</strong>
          <span>{record.model}</span>
        </div>
        <div className={`ai-action ${tone(action)}`}>{humanAction(action, locale)}</div>
        <div className="ai-numbers">
          <div><span>{ui(locale, "Fair A", "A 公平概率")}</span><strong>{probability == null ? "—" : percent(probability, locale)}</strong></div>
          <div><span>{ui(locale, "Confidence", "信心")}</span><strong>{confidence == null ? "—" : percent(confidence, locale)}</strong></div>
        </div>
        <div className="ai-card-foot">
          <span>{formatLatency(record.latency_seconds, locale)}</span>
          <span>{open ? "−" : "+"}</span>
        </div>
      </button>

      {open && (
        <div className="ai-detail">
          <ReasonGroup title={ui(locale, "Reasons", "主要理由")} values={record.decision?.primary_reasons} />
          <ReasonGroup title={ui(locale, "Counter arguments", "反方观点")} values={record.decision?.counter_arguments} />
          <ReasonGroup title={ui(locale, "Data concerns", "数据质量关注")} values={record.decision?.data_quality_concerns} />
          {record.error && <p className="model-error">{record.error}</p>}
          <div className="model-meta">
            <span>{record.model_version}</span>
            <span>{record.prompt_version}</span>
            <span>{record.decision_policy_version}</span>
          </div>
        </div>
      )}
    </article>
  );
}

function OverviewTab({
  detail,
  pair
}: {
  detail: MapDetail;
  pair: ReturnType<typeof primaryMarketPair>;
}) {
  const { locale } = useI18n();

  return (
    <div className="overview-stack">
      <section className="insight-grid">
        <MarketCard detail={detail} pair={pair} />
        <DraftAdvantageCard detail={detail} />
      </section>

      <LineupCard detail={detail} />

      <section className="secondary-grid">
        <LiveStateCard detail={detail} />
        <HistoricalSummary detail={detail} />
      </section>

      <div className="overview-note">
        <span>{ui(locale, "PLAYER VIEW", "玩家视图")}</span>
        <p>{ui(locale,
          "Technical provenance, workers, jobs and raw readiness are kept in Diagnostics so the match view stays readable.",
          "技术溯源、Worker、Job 与底层就绪状态保留在“诊断”中，让比赛主界面保持清晰。"
        )}</p>
      </div>
    </div>
  );
}

function MarketCard({
  detail,
  pair
}: {
  detail: MapDetail;
  pair: ReturnType<typeof primaryMarketPair>;
}) {
  const { locale } = useI18n();
  const series = useMemo(() => marketSeries(detail, pair), [detail, pair]);
  const quality = detail.market_quality;
  const maxAge = pair ? Math.max(pair.teamA.age_seconds, pair.teamB.age_seconds) : null;

  return (
    <section className="insight-card card">
      <div className="section-heading compact">
        <div>
          <span className="section-eyebrow">{ui(locale, "MARKET", "市场")}</span>
          <h2>{ui(locale, "Winner odds", "胜负赔率")}</h2>
        </div>
        <StateBadge value={quality?.eligible ? "READY" : pair ? "DEGRADED" : "MISSING"} />
      </div>

      {pair ? (
        <>
          <div className="odds-pair">
            <div>
              <span>{detail.team_a?.name ?? "Team A"}</span>
              <strong className="radiant-text">{formatOdds(pair.teamA.price)}</strong>
              <small>{pair.teamA.fair_probability == null ? "—" : percent(pair.teamA.fair_probability, locale)}</small>
            </div>
            <i />
            <div className="right">
              <span>{detail.team_b?.name ?? "Team B"}</span>
              <strong className="dire-text">{formatOdds(pair.teamB.price)}</strong>
              <small>{pair.teamB.fair_probability == null ? "—" : percent(pair.teamB.fair_probability, locale)}</small>
            </div>
          </div>

          {series.length ? (
            <div className="mini-chart">
              <IntelligenceChart
                label="Market odds timeline"
                option={{
                  animation: false,
                  tooltip: { trigger: "axis" },
                  color: ["#41C98E", "#F06A72"],
                  grid: { left: 36, right: 12, top: 18, bottom: 26 },
                  xAxis: { type: "time", axisLabel: { color: "#687386", hideOverlap: true }, axisLine: { lineStyle: { color: "rgba(255,255,255,.08)" } } },
                  yAxis: { type: "value", scale: true, axisLabel: { color: "#687386" }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
                  series
                }}
              />
            </div>
          ) : <div className="soft-empty small">{ui(locale, "Waiting for odds trend", "等待赔率趋势")}</div>}

          <div className="card-micro-meta">
            <span>{ui(locale, "Freshness", "新鲜度")} <strong>{seconds(maxAge, locale)}</strong></span>
            <span>{ui(locale, "Pair skew", "配对偏差")} <strong>{seconds(quality?.pair_skew_seconds, locale)}</strong></span>
          </div>
        </>
      ) : <div className="soft-empty">{ui(locale, "Market unavailable", "当前无可用市场")}</div>}
    </section>
  );
}

function DraftAdvantageCard({ detail }: { detail: MapDetail }) {
  const { locale } = useI18n();
  const curve = detail.draft?.curve ?? [];
  const features = detail.draft?.features ?? {};
  const adjusted = curve.map((point) => [point.minute, point.adjusted_radiant_edge]);
  const pure = curve.map((point) => [point.minute, point.pure_radiant_edge]);

  return (
    <section className="insight-card card">
      <div className="section-heading compact">
        <div>
          <span className="section-eyebrow">{ui(locale, "DRAFT INTELLIGENCE", "阵容智能")}</span>
          <h2>{ui(locale, "R.O.S.H. advantage", "R.O.S.H. 阵容优势")}</h2>
        </div>
        <StateBadge value={detail.draft?.complete ? "READY" : detail.draft ? "PARTIAL" : "MISSING"} />
      </div>

      <div className="draft-kpis">
        <MetricPill label={ui(locale, "Current", "当前")} value={signedPercent(features.current_edge, locale)} />
        <MetricPill label={ui(locale, "Next 5m", "未来5分钟")} value={signedPercent(features.next_5m_edge, locale)} />
        <MetricPill label={ui(locale, "Peak", "峰值")} value={signedPercent(features.peak_edge, locale)} />
        <MetricPill label={ui(locale, "Peak min", "峰值时间")} value={numberText(features.peak_minute, locale, "m")} />
      </div>

      {curve.length ? (
        <div className="mini-chart">
          <IntelligenceChart
            label="Draft advantage"
            option={{
              animation: false,
              tooltip: { trigger: "axis" },
              color: ["#7C9CFF", "#9C82FF"],
              grid: { left: 36, right: 12, top: 18, bottom: 26 },
              xAxis: { type: "value", min: 20, max: 60, axisLabel: { color: "#687386", formatter: "{value}m" }, axisLine: { lineStyle: { color: "rgba(255,255,255,.08)" } } },
              yAxis: { type: "value", axisLabel: { color: "#687386", formatter: "{value}%" }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
              series: [
                { name: "Pure", type: "line", showSymbol: false, smooth: true, data: pure },
                { name: "Player Adjusted", type: "line", showSymbol: false, smooth: true, areaStyle: { opacity: .08 }, data: adjusted }
              ]
            }}
          />
        </div>
      ) : <div className="soft-empty small">{ui(locale, "Waiting for validated draft curve", "等待有效阵容曲线")}</div>}
    </section>
  );
}

function LineupCard({ detail }: { detail: MapDetail }) {
  const { locale } = useI18n();
  const slots = detail.draft?.slots ?? [];
  const bySide = (side: "radiant" | "dire") =>
    slots.filter((slot) => slot.side === side).sort((a, b) => a.position - b.position);

  return (
    <section className="lineup-card card">
      <div className="section-heading">
        <div>
          <span className="section-eyebrow">{ui(locale, "DRAFT", "阵容")}</span>
          <h2>{ui(locale, "Hero lineup", "英雄阵容")}</h2>
        </div>
        <span className="lineup-ready">
          {detail.draft?.hero_ready_count ?? 0}/10 {ui(locale, "heroes", "英雄")}
        </span>
      </div>

      {!slots.length ? (
        <div className="soft-empty">{ui(locale, "Waiting for DLTV to confirm all draft slots.", "等待 DLTV 确认完整阵容。")}</div>
      ) : (
        <div className="lineup-versus">
          <HeroSide side="radiant" slots={bySide("radiant")} />
          <div className="lineup-vs">VS</div>
          <HeroSide side="dire" slots={bySide("dire")} />
        </div>
      )}
    </section>
  );
}

function HeroSide({
  side,
  slots
}: {
  side: "radiant" | "dire";
  slots: NonNullable<MapDetail["draft"]>["slots"];
}) {
  const { locale } = useI18n();
  return (
    <div className={`hero-side ${side}`}>
      <div className="hero-side-label">
        <strong>{side === "radiant" ? "RADIANT" : "DIRE"}</strong>
        <span>{ui(locale, side === "radiant" ? "Team A" : "Team B", side === "radiant" ? "A 队" : "B 队")}</span>
      </div>
      <div className="hero-slot-row">
        {slots.map((slot) => (
          <HeroSlot key={`${side}-${slot.position}`} slot={slot} side={side} />
        ))}
      </div>
    </div>
  );
}

function HeroSlot({
  slot,
  side
}: {
  slot: NonNullable<MapDetail["draft"]>["slots"][number];
  side: "radiant" | "dire";
}) {
  const { locale } = useI18n();
  const image = heroImageUrl(slot.hero_name);

  return (
    <article className={`hero-slot ${side}`}>
      <div className="hero-portrait">
        {image ? (
          <img
            src={image}
            alt={slot.hero_name ?? ui(locale, "Unknown hero", "未知英雄")}
            loading="lazy"
            onError={(event) => { event.currentTarget.style.display = "none"; }}
          />
        ) : null}
        <span>{slot.hero_name ? initials(slot.hero_name) : "?"}</span>
        <b>POS {slot.position}</b>
      </div>
      <strong>{slot.player_name ?? (slot.account_id ? `#${slot.account_id}` : ui(locale, "Unknown", "未知"))}</strong>
      <small>{slot.hero_name ?? ui(locale, "Hero unknown", "英雄未知")}</small>
    </article>
  );
}

function LiveStateCard({ detail }: { detail: MapDetail }) {
  const { locale } = useI18n();
  const live = detail.live;

  return (
    <section className="secondary-card card">
      <div className="section-heading compact">
        <div>
          <span className="section-eyebrow">{ui(locale, "LIVE STATE", "实时状态")}</span>
          <h2>{ui(locale, "Map state", "比赛状态")}</h2>
        </div>
        <StateBadge value={detail.sync?.status ?? (live ? "UNKNOWN" : "MISSING")} />
      </div>

      {live ? (
        <>
          <div className="live-primary">
            <strong>{formatGameTime(live.game_time_seconds, locale)}</strong>
            <span>{live.radiant_kills == null || live.dire_kills == null ? "—" : `${live.radiant_kills} : ${live.dire_kills}`}</span>
          </div>
          <div className="live-stat-grid">
            <MetricPill label={ui(locale, "Net worth", "经济差")} value={signedGold(live.radiant_nw_lead, locale)} />
            <MetricPill label={ui(locale, "First blood", "一血")} value={firstBloodLabel(live.first_blood, locale)} />
            <MetricPill label={ui(locale, "State age", "状态年龄")} value={seconds(live.effective_state_age_seconds, locale)} />
            <MetricPill label={ui(locale, "Message age", "消息年龄")} value={seconds(live.message_age_seconds, locale)} />
          </div>
        </>
      ) : <div className="soft-empty">{ui(locale, "Live unavailable — using a safer decision mode.", "实时数据不可用，系统将使用更安全的决策模式。")}</div>}
    </section>
  );
}

function HistoricalSummary({ detail }: { detail: MapDetail }) {
  const { locale } = useI18n();
  const coverage = detail.historical_prewarm ?? detail.latest_snapshot?.history_coverage ?? {};
  const history = detail.snapshot_payload?.history ?? {};

  return (
    <section className="secondary-card card">
      <div className="section-heading compact">
        <div>
          <span className="section-eyebrow">{ui(locale, "HISTORY", "历史")}</span>
          <h2>{ui(locale, "Historical context", "历史情报")}</h2>
        </div>
      </div>

      <div className="history-readiness">
        <MetricPill label={ui(locale, "Team strength", "队伍强度")} value={`${valueFrom(coverage, "team_strength_ready_count") ?? 0}/2`} />
        <MetricPill label={ui(locale, "Player form", "选手状态")} value={`${valueFrom(coverage, "player_form_ready_count") ?? 0}/10`} />
        <MetricPill label={ui(locale, "Player×Hero", "选手×英雄")} value={`${valueFrom(coverage, "player_hero_ready_count") ?? 0}/10`} />
      </div>

      <details className="data-disclosure">
        <summary>{ui(locale, "View historical detail", "查看历史详情")}</summary>
        <pre>{JSON.stringify(history, null, 2)}</pre>
      </details>
    </section>
  );
}

function DraftDetail({ detail }: { detail: MapDetail }) {
  const { locale } = useI18n();
  return (
    <div className="detail-page">
      <LineupCard detail={detail} />
      <DraftAdvantageCard detail={detail} />
      <section className="card detail-card">
        <h2>{ui(locale, "Draft provenance", "阵容溯源")}</h2>
        <div className="detail-meta-grid">
          <MetricPill label={ui(locale, "Model", "模型")} value={detail.draft?.model_version ?? "—"} />
          <MetricPill label={ui(locale, "Data", "数据版本")} value={detail.draft?.data_version ?? "—"} />
          <MetricPill label={ui(locale, "Cutoff", "统计截止")} value={formatDateTime(detail.draft?.statistics_cutoff, locale)} />
          <MetricPill label={ui(locale, "Complete", "完整")} value={detail.draft?.complete ? ui(locale, "Yes", "是") : ui(locale, "No", "否")} />
        </div>
      </section>
    </div>
  );
}

function HistoryDetail({ detail }: { detail: MapDetail }) {
  const { locale } = useI18n();
  return (
    <div className="detail-page">
      <HistoricalSummary detail={detail} />
      <section className="card detail-card">
        <h2>{ui(locale, "Snapshot historical payload", "快照历史数据")}</h2>
        <pre className="json-panel">{JSON.stringify(detail.snapshot_payload?.history ?? {}, null, 2)}</pre>
      </section>
    </div>
  );
}

function EvaluationDetail({ detail }: { detail: MapDetail }) {
  const { locale } = useI18n();
  return (
    <div className="detail-page">
      <section className="card detail-card">
        <div className="section-heading">
          <div>
            <span className="section-eyebrow">{ui(locale, "EVALUATION", "评估")}</span>
            <h2>{ui(locale, "Future & closing odds", "未来与收盘赔率")}</h2>
          </div>
        </div>
        {detail.future_odds.length ? (
          <div className="evaluation-grid">
            {detail.future_odds.map((capture) => (
              <article key={capture.id}>
                <span>{capture.capture_type === "CLOSING" ? ui(locale, "Closing", "收盘") : `+${capture.horizon_seconds ?? 0}s`}</span>
                <strong>{capture.odds_a == null ? "—" : formatOdds(capture.odds_a)} / {capture.odds_b == null ? "—" : formatOdds(capture.odds_b)}</strong>
                <small>{translateStatus(capture.status, locale)}</small>
              </article>
            ))}
          </div>
        ) : <div className="soft-empty">{ui(locale, "No future-odds captures yet.", "暂无未来赔率记录。")}</div>}
      </section>

      <section className="card detail-card">
        <h2>{ui(locale, "Result evidence", "赛果证据")}</h2>
        {detail.result ? (
          <div className="result-summary">
            <MetricPill label={ui(locale, "Winner", "胜者")} value={teamNameById(detail, detail.result.winner_team_id)} />
            <MetricPill label={ui(locale, "Conflict", "冲突")} value={detail.result.provider_conflict ? ui(locale, "YES", "是") : ui(locale, "NO", "否")} />
            <MetricPill label={ui(locale, "Settled", "结算")} value={formatDateTime(detail.result.settled_at, locale)} />
          </div>
        ) : <div className="soft-empty">{ui(locale, "Map result not settled yet.", "比赛结果尚未结算。")}</div>}

        <div className="evidence-list">
          {detail.result_evidence.map((evidence) => (
            <article key={evidence.id}>
              <strong>{evidence.provider}</strong>
              <span>{teamNameById(detail, evidence.winner_team_id)}</span>
              <small>{formatDateTime(evidence.first_usable_at, locale)}</small>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function DiagnosticsDrawer({
  open,
  onClose,
  runtime,
  jobs,
  detail
}: {
  open: boolean;
  onClose: () => void;
  runtime: RuntimeSnapshot | undefined;
  jobs: JobSummary | undefined;
  detail: MapDetail | undefined;
}) {
  const { locale } = useI18n();

  return (
    <>
      <div className={`drawer-backdrop ${open ? "open" : ""}`} onClick={onClose} />
      <aside className={`diagnostics-drawer ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="drawer-head">
          <div>
            <span>{ui(locale, "SYSTEM", "系统")}</span>
            <h2>{ui(locale, "Diagnostics", "诊断")}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close diagnostics">×</button>
        </div>

        <section className="diagnostic-section">
          <h3>{ui(locale, "Readiness", "就绪状态")}</h3>
          <div className="dependency-list">
            {DEPENDENCY_ORDER.map((name) => {
              const value = runtime?.dependencies[name];
              return (
                <article key={name}>
                  <div>
                    <strong>{translateDependency(name, locale)}</strong>
                    <span>{value?.message ?? "—"}</span>
                  </div>
                  <StateBadge value={value?.status ?? "UNKNOWN"} />
                  <small>{seconds(value?.age_seconds, locale)}</small>
                </article>
              );
            })}
          </div>
        </section>

        <section className="diagnostic-section">
          <h3>{ui(locale, "Workers", "Worker")}</h3>
          <div className="worker-list">
            {Object.values(runtime?.workers ?? {}).map((worker) => (
              <article key={worker.name}>
                <div><strong>{worker.name}</strong><span>{worker.last_error ?? "—"}</span></div>
                <StateBadge value={worker.state} />
                <small>{worker.messages_received}</small>
              </article>
            ))}
          </div>
        </section>

        <section className="diagnostic-section">
          <h3>{ui(locale, "Durable jobs", "持久任务")}</h3>
          <div className="job-grid">
            {Object.entries(jobs?.by_status ?? {}).map(([status, count]) => (
              <div key={status}><span>{status}</span><strong>{count}</strong></div>
            ))}
          </div>
          {jobs?.recent_failures?.length ? (
            <div className="failure-list">
              {jobs.recent_failures.map((failure) => (
                <article key={failure.id}>
                  <strong>{failure.job_type}</strong>
                  <span>{failure.last_error ?? "—"}</span>
                </article>
              ))}
            </div>
          ) : null}
        </section>

        {detail && (
          <section className="diagnostic-section">
            <h3>{ui(locale, "Snapshot & provenance", "快照与溯源")}</h3>
            <dl className="diagnostic-kv">
              <div><dt>Snapshot</dt><dd>{detail.latest_snapshot?.snapshot_hash ?? "—"}</dd></div>
              <div><dt>Valve Match ID</dt><dd>{detail.valve_match_id ?? "—"}</dd></div>
              <div><dt>Market metadata</dt><dd>{detail.market_quality?.metadata_version ?? "—"}</dd></div>
              <div><dt>Sync p90</dt><dd>{seconds(detail.sync?.p90_seconds, locale)}</dd></div>
              <div><dt>Sync support</dt><dd>{detail.sync?.sample_size ?? 0}</dd></div>
            </dl>
          </section>
        )}
      </aside>
    </>
  );
}

function PendingIdentityWorkspace({ match }: { match: MapSummary }) {
  const { locale, t } = useI18n();
  const pair = primaryMarketPair(match.market, match.team_a?.id, match.team_b?.id);
  const coverage = match.historical_prewarm ?? match.latest_snapshot?.history_coverage ?? {};

  return (
    <div className="pending-page">
      <section className="card pending-hero">
        <span className="section-eyebrow">{match.tournament_name ?? t("unknownTournament")}</span>
        <h1>{match.team_a?.name ?? t("unknownTeam")} {t("versus")} {match.team_b?.name ?? t("unknownTeam")}</h1>
        <StateBadge value="PENDING_MAP_IDENTITY" />
        <p>{t("pendingIdentityDescription")}</p>
      </section>

      <section className="insight-grid">
        <section className="card insight-card">
          <h2>{t("primaryWinnerMarket")}</h2>
          {pair ? (
            <div className="odds-pair" aria-label={t("headlineOdds")}>
              <div><span>{match.team_a?.name}</span><strong>{formatOdds(pair.teamA.price)}</strong></div>
              <i />
              <div className="right"><span>{match.team_b?.name}</span><strong>{formatOdds(pair.teamB.price)}</strong></div>
            </div>
          ) : <div className="soft-empty">{t("marketUnavailable")}</div>}
        </section>

        <section className="card insight-card">
          <h2>{t("historicalPrewarm")}</h2>
          <div className="history-readiness">
            <MetricPill label={t("teamHistoryReady")} value={`${valueFrom(coverage, "team_strength_ready_count") ?? 0}/2`} />
            <MetricPill label={t("rosterPlayersReady")} value={`${valueFrom(coverage, "player_form_ready_count") ?? 0}/10`} />
            <MetricPill label={t("playerHeroReady")} value={`${valueFrom(coverage, "player_hero_ready_count") ?? 0}/10`} />
          </div>
        </section>
      </section>
    </div>
  );
}

function WorkspaceSkeleton() {
  return (
    <div className="workspace-skeleton">
      <span className="skeleton wide" />
      <span className="skeleton medium" />
      <div className="skeleton-grid">
        <span className="skeleton block" />
        <span className="skeleton block" />
      </div>
      <span className="skeleton tall" />
    </div>
  );
}

function EmptyWorkspace({ overall }: { overall: string | undefined }) {
  const { locale, t } = useI18n();
  return (
    <section className="empty-workspace">
      <div className="empty-logo">D</div>
      <h1>{t("noCanonicalMaps")}</h1>
      <p>{t("waitingForProviderDiscovery")}</p>
      <StateBadge value={overall ?? "UNKNOWN"} />
      <span>{ui(locale, "Matches will appear here automatically.", "比赛会在发现后自动出现在这里。")}</span>
    </section>
  );
}

function ErrorState({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="empty-workspace error">
      <div className="empty-logo">!</div>
      <h1>{title}</h1>
      <p>{detail}</p>
    </section>
  );
}

function StateBadge({ value }: { value: string }) {
  const { locale } = useI18n();
  return <span className={`state-badge ${tone(value)}`}>{translateStatus(value, locale)}</span>;
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return <div className="metric-pill"><span>{label}</span><strong>{value}</strong></div>;
}

function ReasonGroup({ title, values }: { title: string; values?: string[] }) {
  if (!values?.length) return null;
  return (
    <div className="reason-group">
      <strong>{title}</strong>
      {values.map((value, index) => <p key={`${title}-${index}`}>{value}</p>)}
    </div>
  );
}

function marketSeries(detail: MapDetail, pair: ReturnType<typeof primaryMarketPair>) {
  if (!pair) return [];
  const wanted = new Set([pair.teamA.odds_id, pair.teamB.odds_id]);
  const grouped = new Map<number, Array<[string, number]>>();
  detail.market_timeline.forEach((item) => {
    if (!wanted.has(item.odds_id)) return;
    const values = grouped.get(item.odds_id) ?? [];
    values.push([item.received_at, Number(item.price)]);
    grouped.set(item.odds_id, values);
  });
  return [pair.teamA, pair.teamB].map((market, index) => ({
    name: index === 0 ? detail.team_a?.name ?? "Team A" : detail.team_b?.name ?? "Team B",
    type: "line",
    showSymbol: false,
    smooth: true,
    lineStyle: { width: 2 },
    data: grouped.get(market.odds_id) ?? []
  })).filter((item) => item.data.length >= 2);
}

function primaryMarketPair(
  market: MarketObservation[],
  teamAId: string | undefined,
  teamBId: string | undefined
) {
  if (!teamAId || !teamBId) return null;
  const teamA = market
    .filter((item) => item.selection_team_id === teamAId)
    .sort((a, b) => Date.parse(b.received_at) - Date.parse(a.received_at))[0];
  const teamB = market
    .filter((item) => item.selection_team_id === teamBId)
    .sort((a, b) => Date.parse(b.received_at) - Date.parse(a.received_at))[0];
  return teamA && teamB ? { teamA, teamB } : null;
}

function heroImageUrl(heroName: string | null): string | null {
  if (!heroName) return null;
  const exceptions: Record<string, string> = {
    "Anti-Mage": "antimage",
    "Nature's Prophet": "furion",
    "Necrophos": "necrolyte",
    "Outworld Destroyer": "obsidian_destroyer",
    "Queen of Pain": "queenofpain",
    "Shadow Fiend": "nevermore",
    "Timbersaw": "shredder",
    "Wraith King": "skeleton_king",
    "Windranger": "windrunner",
    "Zeus": "zuus",
    "Clockwerk": "rattletrap",
    "Lifestealer": "life_stealer",
    "Io": "wisp",
    "Centaur Warrunner": "centaur",
    "Magnus": "magnataur",
    "Doom": "doom_bringer",
    "Treant Protector": "treant",
    "Underlord": "abyssal_underlord"
  };
  const slug = exceptions[heroName] ?? heroName
    .toLowerCase()
    .replace(/['’]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
  return `https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/${slug}.png`;
}

function ui(locale: Locale, en: string, zh: string) {
  return locale === "zh-CN" ? zh : en;
}

function tone(value: string) {
  const normalized = value.toUpperCase();
  if (["READY", "RUNNING", "SAFE", "FRESH", "BUY_A", "BUY_B", "CAPTURED", "SUCCEEDED", "LIVE_BASIC", "LIVE_FULL"].some((x) => normalized.includes(x))) return "positive";
  if (["DEGRADED", "CAUTION", "PARTIAL", "WARNING", "NO_BUY", "NO BUY", "UNKNOWN", "PENDING"].some((x) => normalized.includes(x))) return "warning";
  if (["FAILED", "BLOCK", "UNSAFE", "ACTION_REQUIRED", "ERROR", "MISSING", "INSUFFICIENT"].some((x) => normalized.includes(x))) return "negative";
  return "neutral";
}

function humanAction(action: string, locale: Locale) {
  const map: Record<string, [string, string]> = {
    BUY_A: ["BUY A", "买 A"],
    BUY_B: ["BUY B", "买 B"],
    NO_BUY: ["NO BUY", "不买"],
    INSUFFICIENT_DATA: ["INSUFFICIENT", "数据不足"]
  };
  const item = map[action];
  return item ? ui(locale, item[0], item[1]) : translateStatus(action, locale);
}

function providerName(provider: string) {
  const names: Record<string, string> = {
    openai: "GPT",
    anthropic: "Claude",
    google: "Gemini",
    deepseek: "DeepSeek",
    kimi: "Kimi"
  };
  return names[provider.toLowerCase()] ?? provider;
}

function formatOdds(value: string | number | null | undefined) {
  if (value == null) return "—";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "—";
}

function percent(value: number, locale: Locale) {
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

function signedPercent(value: unknown, locale: Locale) {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(n)}%`;
}

function signedGold(value: number | null | undefined, locale: Locale) {
  if (value == null) return "—";
  const abs = Math.abs(value);
  const formatted = abs >= 1000 ? `${(abs / 1000).toFixed(1)}k` : new Intl.NumberFormat(locale).format(abs);
  return `${value > 0 ? "Radiant +" : value < 0 ? "Dire +" : ""}${formatted}`;
}

function seconds(value: number | null | undefined, locale: Locale) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value)}s`;
}

function formatLatency(value: number | null, locale: Locale) {
  return value == null ? "—" : `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value)}s`;
}

function formatGameTime(value: number | null | undefined, locale: Locale) {
  if (value == null) return ui(locale, "PRE", "赛前");
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  const minutes = Math.floor(abs / 60);
  const seconds = Math.floor(abs % 60).toString().padStart(2, "0");
  return `${sign}${minutes}:${seconds}`;
}

function formatSchedule(value: string | null, locale: Locale) {
  if (!value) return ui(locale, "TBD", "待定");
  return new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", month: "short", day: "numeric" }).format(new Date(value));
}

function formatDateTime(value: string | null | undefined, locale: Locale) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function isFuture(value: string | null) {
  return Boolean(value && Date.parse(value) > Date.now());
}

function initials(value: string) {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "?";
}

function firstBloodLabel(value: string | null | undefined, locale: Locale) {
  if (!value) return "—";
  const normalized = value.toLowerCase();
  if (normalized.includes("radiant")) return ui(locale, "Radiant", "天辉");
  if (normalized.includes("dire")) return ui(locale, "Dire", "夜魇");
  return value;
}

function numberText(value: unknown, locale: Locale, suffix = "") {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(n)}${suffix}` : "—";
}

function valueFrom(value: unknown, key: string): string | number | null {
  if (!value || typeof value !== "object") return null;
  const item = (value as Record<string, unknown>)[key];
  return typeof item === "string" || typeof item === "number" ? item : null;
}

function shortHash(value: string | null | undefined) {
  return value ? value.slice(0, 12) : "—";
}

function teamNameById(detail: MapDetail, id: string | null) {
  if (!id) return "—";
  if (id === detail.team_a?.id) return detail.team_a.name;
  if (id === detail.team_b?.id) return detail.team_b.name;
  return shortHash(id);
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}
