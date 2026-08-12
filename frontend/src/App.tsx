import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Header,
  HeaderGlobalBar,
  HeaderName,
  InlineNotification,
  SkeletonText,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Tag,
  Theme
} from "@carbon/react";
import { Renew } from "@carbon/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchJobs,
  fetchMap,
  fetchMaps,
  fetchRuntime,
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
  translate,
  translateDependency,
  translateStatus,
  useI18n,
  type Locale
} from "./i18n";
import IntelligenceChart from "./Chart";

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
  "GEMINI"
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

  const refresh = () => {
    void queryClient.invalidateQueries();
  };

  return (
    <Theme theme="g100">
      <Header aria-label="Dota AI Decision Lab">
        <HeaderName href="/" prefix="">
          Dota AI Decision Lab
        </HeaderName>
        <HeaderGlobalBar>
          <div className="header-status">
            <LanguageSwitcher locale={locale} setLocale={setLocale} label={t("language")} />
            <StatusLabel status={runtime.data?.overall ?? "UNKNOWN"} />
            <Button
              kind="ghost"
              size="sm"
              hasIconOnly
              renderIcon={Renew}
              iconDescription={t("refreshData")}
              onClick={refresh}
            />
          </div>
        </HeaderGlobalBar>
      </Header>
      <div className="app-shell">
        <aside className="match-rail" aria-label={t("trackedMaps")}>
          <div className="rail-heading">
            <span>{t("trackedMaps")}</span>
            <strong>{maps.data?.length ?? 0}</strong>
          </div>
          {maps.isLoading ? (
            <div className="rail-loading">
              <SkeletonText paragraph lineCount={5} />
            </div>
          ) : maps.isError ? (
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title={t("mapFeedUnavailable")}
              subtitle={errorMessage(maps.error, t("unknownError"))}
            />
          ) : maps.data?.length ? (
            <nav className="match-list">
              {maps.data.map((map) => (
                <MatchButton
                  key={map.id}
                  map={map}
                  selected={map.id === selectedMapId}
                  onSelect={() => setSelectedMapId(map.id)}
                />
              ))}
            </nav>
          ) : (
            <div className="empty-rail">
              <strong>{t("noCanonicalMaps")}</strong>
              <span>{t("waitingForProviderDiscovery")}</span>
            </div>
          )}
        </aside>

        <main className="workspace">
          <ReadinessSummary runtime={runtime.data} loading={runtime.isLoading} />
          {selectedMatch?.identity_status === "PENDING_MAP_IDENTITY" ? (
            <PendingIdentityWorkspace match={selectedMatch} />
          ) : detail.isLoading && selectedCanonicalMapId ? (
            <WorkspaceSkeleton />
          ) : detail.isError ? (
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title={t("mapDetailUnavailable")}
              subtitle={errorMessage(detail.error, t("unknownError"))}
            />
          ) : detail.data ? (
            <MapWorkspace detail={detail.data} runtime={runtime.data} jobs={jobs.data} />
          ) : (
            <EmptyWorkspace overall={runtime.data?.overall} />
          )}
        </main>
      </div>
    </Theme>
  );
}

function LanguageSwitcher({
  locale,
  setLocale,
  label
}: {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  label: string;
}) {
  return (
    <div className="language-switcher" role="group" aria-label={label}>
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
  );
}

function MatchButton({
  map,
  selected,
  onSelect
}: {
  map: MapSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const { locale, t } = useI18n();
  const teamA = map.team_a?.name ?? t("unknownTeam");
  const teamB = map.team_b?.name ?? t("unknownTeam");
  const headlinePair = primaryMarketPair(map.market, map.team_a?.id, map.team_b?.id);
  const status = map.identity_status === "PENDING_MAP_IDENTITY"
    ? map.identity_status
    : map.latest_snapshot?.mode ?? "NO_SNAPSHOT";
  return (
    <button
      type="button"
      className={`match-button${selected ? " selected" : ""}`}
      onClick={onSelect}
    >
      <span className="match-button-kicker">
        <time dateTime={map.scheduled_at ?? undefined}>{formatSchedule(map.scheduled_at, locale)}</time>
        <span>{map.tournament_name ?? t("unknownTournament")}</span>
      </span>
      <span className="match-button-teams">
        <span>{teamA}</span>
        <span>{teamB}</span>
      </span>
      <span className="match-button-footer">
        <span>{map.entity_type === "MAP" ? `${t("map")} ${map.map_number ?? "?"}` : map.round ?? t("series")}</span>
        <span className={`match-button-status ${statusTone(status)}`}>{translateStatus(status, locale)}</span>
      </span>
      <span className="match-button-prices" aria-label={t("headlineOdds")}>
        <span>{headlinePair ? Number(headlinePair.teamA.price).toFixed(2) : "-"}</span>
        <span>{headlinePair ? Number(headlinePair.teamB.price).toFixed(2) : "-"}</span>
      </span>
    </button>
  );
}

function PendingIdentityWorkspace({ match }: { match: MapSummary }) {
  const { locale, t } = useI18n();
  const title = `${match.team_a?.name ?? t("unknownTeam")} ${t("versus")} ${match.team_b?.name ?? t("unknownTeam")}`;
  const historyCoverage = match.historical_prewarm ?? match.latest_snapshot?.history_coverage;
  const teamHistoryReady = Number(historyCoverage?.team_strength_ready_count ?? 0);
  const pair = primaryMarketPair(match.market, match.team_a?.id, match.team_b?.id);
  return (
    <section className="pending-identity-workspace">
      <header className="pending-identity-header">
        <div>
          <span className="eyebrow">{match.tournament_name ?? t("unknownTournament")} · {formatSchedule(match.scheduled_at, locale)}</span>
          <h1>{title}</h1>
          <p>{t("pendingIdentityDescription")}</p>
        </div>
        <StatusLabel status={match.identity_status} />
      </header>
      <div className="pending-workbench">
        <section className="pending-market-section">
          <PanelHeading title={t("primaryWinnerMarket")} status={pair ? "READY" : "UNKNOWN"} />
          {pair ? (
            <>
              <MarketPair pair={pair} teamA={match.team_a?.name} teamB={match.team_b?.name} />
              <div className="market-quality-line">
                <span>{marketLabel(pair.teamA, t("winnerMarket"))}</span>
                <span>{t("updatedAt")} {formatTime(latestReceivedAt([pair.teamA, pair.teamB]), locale)}</span>
              </div>
            </>
          ) : <PanelEmpty text={t("marketUnavailable")} />}
          {match.market.length > 2 && (
            <details className="market-disclosure">
              <summary>{t("allMarkets")} <span>{match.market.length}</span></summary>
              <div className="market-table-wrap">
                <table className="cds--data-table cds--data-table--sm">
                  <thead><tr><th>{t("selection")}</th><th>{t("market")}</th><th>{t("odds")}</th><th>{t("observed")}</th></tr></thead>
                  <tbody>{match.market.slice(0, 24).map((item) => (
                    <tr key={item.odds_id}>
                      <td>{teamNameForSelection(match, item.selection_team_id, t("unknown"))}</td>
                      <td>{marketLabel(item, t("unknown"))}</td>
                      <td>{Number(item.price).toFixed(2)}</td>
                      <td>{formatTime(item.received_at, locale)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </details>
          )}
        </section>
        <section className="pending-history-section">
          <PanelHeading title={t("historicalPrewarm")} status={teamHistoryReady === 2 ? "READY" : "UNKNOWN"} />
          <div className="pending-history-metrics">
            <Metric label={t("teamHistoryReady")} value={`${teamHistoryReady}/2`} />
            <Metric label={t("rosterPlayersReady")} value={`${metricText(historyCoverage?.player_form_ready_count, locale)}/10`} />
            <Metric label={t("playerHeroReady")} value={`${metricText(historyCoverage?.player_hero_ready_count, locale)}/10`} />
          </div>
          <p className="pending-history-note">{t("waitingForDraftIdentity")}</p>
          <div className="pending-provenance">
            <span>{t("knowledgeCutoff")}</span>
            <time>{formatDateTime(stringValue(historyCoverage?.latest_knowledge_cutoff), locale)}</time>
          </div>
        </section>
      </div>
      <details className="match-metadata">
        <summary>{t("matchDetails")}</summary>
        <div className="pending-identity-facts">
          <Metric label={t("raybetMatchId")} value={String(match.provider_match_id ?? t("unknown"))} />
          <Metric label={t("format")} value={match.round ?? t("unknown")} />
          <Metric label={t("scheduledAt")} value={formatDateTime(match.scheduled_at, locale)} />
          <Metric label={t("lastDiscoveredAt")} value={formatDateTime(match.provider_observed_at, locale)} />
        </div>
      </details>
    </section>
  );
}

function ReadinessSummary({
  runtime,
  loading
}: {
  runtime: RuntimeSnapshot | undefined;
  loading: boolean;
}) {
  const { locale, t } = useI18n();
  if (loading) {
    return <div className="readiness-summary loading" aria-label={t("loadingReadiness")} />;
  }
  const dependencies = DEPENDENCY_ORDER.map((name) => ({ name, value: runtime?.dependencies[name] }));
  const readyCount = dependencies.filter(({ value }) => value?.status === "READY").length;
  const attentionCount = dependencies.length - readyCount;
  return (
    <details className="readiness-summary">
      <summary>
        <span>{t("systemReadiness")}</span>
        <StatusLabel status={runtime?.overall ?? "UNKNOWN"} compact />
        <span className="readiness-count positive">{readyCount} {t("ready")}</span>
        <span className="readiness-count">{attentionCount} {t("needAttention")}</span>
        <span className="readiness-expand">{t("viewDetails")}</span>
      </summary>
      <section className="readiness-details" aria-label={t("businessReadiness")}>
        {dependencies.map(({ name, value }) => (
          <div className="dependency" key={name} title={value?.message ?? undefined}>
            <span>{translateDependency(name, locale)}</span>
            <StatusLabel status={value?.status ?? "UNKNOWN"} compact />
            <small>{t("dependencyAge")} {seconds(value?.age_seconds, locale)}</small>
          </div>
        ))}
      </section>
    </details>
  );
}

function MapWorkspace({
  detail,
  runtime,
  jobs
}: {
  detail: MapDetail;
  runtime: RuntimeSnapshot | undefined;
  jobs: JobSummary | undefined;
}) {
  const { locale, t } = useI18n();
  const quality = detail.latest_snapshot?.quality;
  const blockers = quality?.blockers ?? [];
  const warnings = quality?.warnings ?? [];
  const decisionStatus = blockers.length ? "ACTION_REQUIRED" : warnings.length ? "DEGRADED" : "READY";
  return (
    <>
      <header className="map-header">
        <div>
          <p className="map-context">
            {detail.tournament_name ?? t("unknownTournament")} · {t("map")} {detail.map_number ?? "?"}
          </p>
          <h1>
            {detail.team_a?.name ?? t("unknownTeam")} <span>{t("versus")}</span>{" "}
            {detail.team_b?.name ?? t("unknownTeam")}
          </h1>
        </div>
        <div className="map-state">
          <StatusLabel status={detail.latest_snapshot?.mode ?? "NO SNAPSHOT"} />
          <span>{t("decisionAt")} {formatTime(detail.latest_snapshot?.decision_at, locale)}</span>
        </div>
      </header>

      <section className={`decision-readiness ${statusTone(decisionStatus)}`} aria-label={t("decisionReadiness")}>
        <div className="decision-readiness-title">
          <span>{t("decisionReadiness")}</span>
          <strong>{blockers.length ? t("cannotDecide") : warnings.length ? t("limitedDecision") : t("decisionReady")}</strong>
        </div>
        <div className="quality-tags">
          {blockers.map((item) => <Tag key={item} type="red" size="sm" title={item}>{translateStatus(item, locale)}</Tag>)}
          {warnings.map((item) => <Tag key={item} type="warm-gray" size="sm" title={item}>{translateStatus(item, locale)}</Tag>)}
          {!blockers.length && !warnings.length && <span>{t("qualityChecksPassed")}</span>}
        </div>
        <details className="snapshot-details">
          <summary>{t("snapshotDetails")}</summary>
          <code title={detail.latest_snapshot?.snapshot_hash}>{t("snapshotHash")} {shortHash(detail.latest_snapshot?.snapshot_hash)}</code>
          <span>{t("valve")} {detail.valve_match_id ?? t("unresolved")}</span>
        </details>
      </section>

      <MatchOverview detail={detail} />

      <section className="decision-layout">
        <MarketPanel detail={detail} />
        <AiPanel detail={detail} />
      </section>

      <Tabs>
        <TabList aria-label={t("mapIntelligenceViews")} contained>
          <Tab>{t("draftIntelligence")}</Tab>
          <Tab>{t("live")}</Tab>
          <Tab>{t("historical")}</Tab>
          <Tab>{t("evaluation")}</Tab>
          <Tab>{t("runtime")}</Tab>
        </TabList>
        <TabPanels>
          <TabPanel><DraftPanel detail={detail} /></TabPanel>
          <TabPanel>
            <LivePanel detail={detail} />
          </TabPanel>
          <TabPanel>
            <HistoryPanel detail={detail} />
          </TabPanel>
          <TabPanel>
            <EvaluationPanel detail={detail} />
          </TabPanel>
          <TabPanel>
            <RuntimePanel runtime={runtime} jobs={jobs} />
          </TabPanel>
        </TabPanels>
      </Tabs>
    </>
  );
}

function MatchOverview({ detail }: { detail: MapDetail }) {
  const { locale, t } = useI18n();
  const latest = detail.live;
  const draftStatus = detail.draft?.complete ? "READY" : detail.draft ? "PARTIAL" : "MISSING";
  const liveStatus = latest ? detail.sync?.status ?? "UNKNOWN" : "MISSING";
  return (
    <section className="match-overview" aria-label={t("matchOverview")}>
      <div className="lineup-overview">
        <PanelHeading title={t("lineup")} status={draftStatus} />
        {detail.draft ? <LineupOverview detail={detail} /> : <PanelEmpty text={t("noValidatedLineup")} />}
      </div>
      <div className="live-state-overview">
        <PanelHeading title={t("liveState")} status={liveStatus} />
        {latest ? (
          <>
            <div className="live-scoreline">
              <Metric label={t("gameTime")} value={formatGameTime(latest.game_time_seconds, locale)} />
              <Metric
                label={t("kills")}
                value={
                  latest.radiant_kills == null || latest.dire_kills == null
                    ? t("unknown")
                    : `${latest.radiant_kills} - ${latest.dire_kills}`
                }
              />
              <Metric label={t("radiantNetWorth")} value={signed(latest.radiant_nw_lead, locale)} />
            </div>
            <dl className="live-facts">
              <div><dt>{t("firstBlood")}</dt><dd>{formatFirstBlood(latest.first_blood, locale)}</dd></div>
              <div><dt>{t("effectiveStateAge")}</dt><dd>{seconds(latest.effective_state_age_seconds, locale)}</dd></div>
              <div><dt>{t("sync")}</dt><dd>{translateStatus(detail.sync?.status ?? "UNKNOWN", locale)}</dd></div>
              <div><dt>{t("latestLiveUpdate")}</dt><dd>{formatTime(latest.last_message_received_at, locale)}</dd></div>
            </dl>
          </>
        ) : <PanelEmpty text={t("noLiveState")} />}
      </div>
    </section>
  );
}

function LineupOverview({ detail }: { detail: MapDetail }) {
  const { t } = useI18n();
  const slots = detail.draft?.slots ?? [];
  const sideSlots = (side: "radiant" | "dire") =>
    slots.filter((slot) => slot.side === side).sort((a, b) => a.position - b.position);
  return (
    <div className="lineup-grid">
      {(["radiant", "dire"] as const).map((side) => (
        <div className={`lineup-side ${side}`} key={side}>
          <h3>{t(side)}</h3>
          {sideSlots(side).map((slot) => (
            <div className="lineup-row" key={`${side}-${slot.position}`}>
              <span className="lineup-position">Pos{slot.position}</span>
              <span className="lineup-player">
                {slot.player_name ?? (slot.account_id ? `#${slot.account_id}` : t("playerUnknown"))}
              </span>
              <span className={`lineup-hero ${slot.hero_id == null ? "unknown" : ""}`}>
                {slot.hero_name ?? (slot.hero_id ? `Hero #${slot.hero_id}` : t("heroUnknown"))}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function MarketPanel({ detail }: { detail: MapDetail }) {
  const { locale, t } = useI18n();
  const quality = detail.market_quality;
  const pair = useMemo(
    () => primaryMarketPair(detail.market, detail.team_a?.id, detail.team_b?.id),
    [detail.market, detail.team_a?.id, detail.team_b?.id]
  );
  const series = useMemo(() => {
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
      name: index === 0 ? detail.team_a?.name ?? t("teamA") : detail.team_b?.name ?? t("teamB"),
      type: "line",
      showSymbol: false,
      symbol: "circle",
      lineStyle: { width: 2 },
      data: grouped.get(market.odds_id) ?? []
    })).filter((item) => item.data.length);
  }, [detail.market_timeline, detail.team_a?.name, detail.team_b?.name, pair, t]);
  const maxAge = pair ? Math.max(pair.teamA.age_seconds, pair.teamB.age_seconds) : null;
  const marketStatus = pair?.teamA.normalized_status ?? pair?.teamB.normalized_status ?? "UNKNOWN";
  const metadataVersion = quality?.metadata_version ?? pair?.teamA.metadata_version ?? pair?.teamB.metadata_version;
  const hasTrend = series.length === 2 && series.every((item) => item.data.length >= 2);
  return (
    <section className="intel-panel market-panel">
      <PanelHeading
        title={t("primaryWinnerMarket")}
        status={quality?.eligible ? "FRESH" : pair ? "DEGRADED" : "MISSING"}
      />
      {pair ? <MarketPair pair={pair} teamA={detail.team_a?.name} teamB={detail.team_b?.name} /> : <PanelEmpty text={t("marketUnavailable")} />}
      <div className={`market-quality-line ${quality?.eligible ? "positive" : "warning"}`}>
        <strong>{quality?.eligible ? t("marketUsable") : t("marketLimited")}</strong>
        <span>{t("marketState")} {translateStatus(marketStatus, locale)}</span>
        <span>{t("freshness")} {seconds(maxAge, locale)}</span>
        <span>{t("pairSkew")} {seconds(quality?.pair_skew_seconds, locale)}</span>
        <span title={metadataVersion ?? undefined}>{t("metadataVersion")} {shortVersion(metadataVersion, t("unknown"))}</span>
      </div>
      {hasTrend ? (
        <Chart
          option={{
            tooltip: { trigger: "axis" },
            color: ["#78a9ff", "#f1c21b"],
            legend: { top: 0, left: 0, textStyle: { color: "#c6c6c6" } },
            grid: { left: 44, right: 16, top: 38, bottom: 30 },
            xAxis: { type: "time", axisLabel: { color: "#8d8d8d" } },
            yAxis: { type: "value", scale: true, axisLabel: { color: "#8d8d8d" } },
            series
          }}
          label={t("marketOddsTimeline")}
        />
      ) : (
        <div className="trend-empty">{t("waitingForOddsTrend")}</div>
      )}
    </section>
  );
}

function DraftPanel({ detail }: { detail: MapDetail }) {
  const { locale, t } = useI18n();
  const curve = detail.draft?.curve ?? [];
  const features = detail.draft?.features ?? {};
  const data = (key: keyof (typeof curve)[number]) =>
    curve.map((point) => [point.minute, point[key]]);
  return (
    <section className="tab-content draft-panel">
      <PanelHeading
        title={t("draftIntelligence")}
        status={detail.draft?.complete ? "READY" : detail.draft ? "PARTIAL" : "MISSING"}
      />
      <div className="draft-readiness-line">
        <span>{t("playersIdentified")} <strong>{detail.draft?.roster_ready_count ?? 0}/10</strong></span>
        <span>{t("heroesIdentified")} <strong>{detail.draft?.hero_ready_count ?? 0}/10</strong></span>
        <span>{t("playerFormReady")} <strong>{detail.historical_prewarm?.player_form_ready_count ?? 0}/10</strong></span>
        <span>{t("playerHeroHistoryReady")} <strong>{detail.historical_prewarm?.player_hero_ready_count ?? 0}/10</strong></span>
      </div>
      <div className="compact-metrics">
        <Metric label={t("currentEdge")} value={signed(features.current_edge, locale)} />
        <Metric label={t("next5m")} value={signed(features.next_5m_edge, locale)} />
        <Metric label={t("peakMinute")} value={metricText(features.peak_minute, locale)} />
        <Metric label={t("peakEdge")} value={signed(features.peak_edge, locale)} />
      </div>
      {curve.length ? (
        <Chart
          option={{
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#c6c6c6" } },
            grid: { left: 44, right: 16, top: 42, bottom: 30 },
            xAxis: { type: "value", min: 20, max: 60, axisLabel: { color: "#8d8d8d" } },
            yAxis: { type: "value", axisLabel: { color: "#8d8d8d", formatter: "{value}%" } },
            series: [
              { name: t("pure"), type: "line", showSymbol: false, data: data("pure_radiant_edge") },
              {
                name: t("playerAdjusted"),
                type: "line",
                showSymbol: false,
                data: data("adjusted_radiant_edge")
              }
            ]
          }}
          label={t("draftMinuteCurve")}
        />
      ) : (
        <PanelEmpty text={t("noRoshCurve")} />
      )}
      {detail.draft?.model_version && (
        <div className="provenance-list">
          <span>{t("modelVersion")} {detail.draft.model_version}</span>
          <span>{t("dataVersion")} {detail.draft.data_version ?? t("unknown")}</span>
          <span>{t("statisticsCutoff")} {formatTime(detail.draft.statistics_cutoff, locale)}</span>
        </div>
      )}
    </section>
  );
}

function AiPanel({ detail }: { detail: MapDetail }) {
  const { locale, t } = useI18n();
  return (
    <section className="ai-panel">
      <PanelHeading title={t("independentAiDecisions")} status={`${detail.decisions.length}/3`} />
      {detail.decisions.length ? (
        <div className="decision-list">
          {detail.decisions.map((record) => (
            <article className="decision-item" key={record.id}>
              <div className="decision-heading">
                <strong>{providerName(record.provider)}</strong>
                <StatusLabel status={record.decision?.action ?? record.parse_status} compact />
              </div>
              <div className="decision-confidence">
                <span>{t("confidence")}</span>
                <strong>
                  {record.decision?.confidence == null
                    ? t("unknown")
                    : percent(record.decision.confidence, locale)}
                </strong>
              </div>
              {record.error ? (
                <p className="decision-error">{record.error}</p>
              ) : (
                <>
                  <ReasonList title={t("reasons")} values={record.decision?.primary_reasons} />
                  <ReasonList title={t("counterArguments")} values={record.decision?.counter_arguments} />
                  <ReasonList
                    title={t("qualityConcerns")}
                    values={record.decision?.data_quality_concerns}
                  />
                </>
              )}
              <footer>
                <span>{record.model}</span>
                <span>{formatLatency(record.latency_seconds, locale)}</span>
              </footer>
              <div className="provenance-list">
                <span>{t("modelVersion")} {record.model_version}</span>
                <span>{t("promptVersion")} {record.prompt_version}</span>
                <span>{t("policyVersion")} {record.decision_policy_version}</span>
                <span>{t("parseStatus")} {translateStatus(record.parse_status, locale)}</span>
                <span>{t("snapshotHash")} {shortHash(record.snapshot_hash)}</span>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="ai-empty">
          <strong>{t("aiWaiting")}</strong>
          <span>{t("noAiDecisions")}</span>
        </div>
      )}
    </section>
  );
}

function LivePanel({ detail }: { detail: MapDetail }) {
  const { locale, t } = useI18n();
  const latest = detail.live;
  return (
    <section className="tab-content">
      <div className="compact-metrics live-metrics">
        <Metric label={t("gameTime")} value={formatGameTime(latest?.game_time_seconds, locale)} />
        <Metric
          label={t("kills")}
          value={
            latest?.radiant_kills == null || latest.dire_kills == null
              ? t("unknown")
              : `${latest.radiant_kills} - ${latest.dire_kills}`
          }
        />
        <Metric label={t("radiantNetWorth")} value={signed(latest?.radiant_nw_lead, locale)} />
        <Metric label={t("firstBlood")} value={formatFirstBlood(latest?.first_blood, locale)} />
        <Metric label={t("sync")} value={translateStatus(detail.sync?.status ?? "UNKNOWN", locale)} />
        <Metric label={t("syncConfidence")} value={translateStatus(detail.sync?.confidence ?? "UNKNOWN", locale)} />
        <Metric label={t("p50Lag")} value={seconds(detail.sync?.p50_seconds, locale)} />
        <Metric label={t("p90Lag")} value={seconds(detail.sync?.p90_seconds, locale)} />
        <Metric label={t("jitter")} value={seconds(detail.sync?.jitter_seconds, locale)} />
        <Metric label={t("samples")} value={metricText(detail.sync?.sample_size, locale)} />
        <Metric label={t("acceptedPairs")} value={percentValue(detail.sync?.accepted_pair_ratio, locale)} />
        <Metric label={t("messageAge")} value={seconds(latest?.message_age_seconds, locale)} />
        <Metric
          label={t("effectiveStateAge")}
          value={seconds(latest?.effective_state_age_seconds, locale)}
        />
        <Metric label={t("latestLiveUpdate")} value={formatTime(latest?.last_message_received_at, locale)} />
        <Metric label={t("connectionGeneration")} value={metricText(latest?.reconnect_generation, locale)} />
      </div>
      {detail.live_timeline.length ? (
        <Chart
          option={{
            tooltip: { trigger: "axis" },
            grid: { left: 56, right: 16, top: 20, bottom: 32 },
            xAxis: { type: "value", axisLabel: { color: "#8d8d8d", formatter: "{value}s" } },
            yAxis: { type: "value", axisLabel: { color: "#8d8d8d" } },
            series: [
              {
                name: t("radiantNetWorthLead"),
                type: "line",
                showSymbol: false,
                data: detail.live_timeline.map((item) => [
                  item.game_time_seconds,
                  item.radiant_nw_lead
                ])
              }
            ]
          }}
          label={t("dltvLiveTimeline")}
        />
      ) : (
        <PanelEmpty text={t("noDltvStates")} />
      )}
    </section>
  );
}

function HistoryPanel({ detail }: { detail: MapDetail }) {
  const { locale, t } = useI18n();
  const history = (detail.snapshot_payload?.history ?? {}) as Record<string, unknown>;
  const teamA = objectValue(history.team_a);
  const teamB = objectValue(history.team_b);
  const playersA = arrayValue(history.players_a);
  const playersB = arrayValue(history.players_b);
  const coverage = objectValue(history.coverage) ?? detail.latest_snapshot?.history_coverage;
  if (!teamA && !teamB) return <PanelEmpty text={t("noHistoricalSnapshot")} />;
  return (
    <section className="tab-content">
      <div className="audit-grid history-coverage">
        <Metric label={t("historyCoverage")} value={`${metricText(coverage?.team_strength_ready_count, locale)}/2`} />
        <Metric label={t("workers")} value={metricText(coverage?.roster_player_count, locale)} />
        <Metric label={t("hero")} value={metricText(coverage?.player_hero_ready_count, locale)} />
        <Metric
          label={t("knowledgeCutoff")}
          value={formatTime(stringValue(coverage?.latest_knowledge_cutoff), locale)}
        />
      </div>
      <div className="history-grid">
        <TeamHistory name={detail.team_a?.name ?? t("teamA")} team={teamA} players={playersA} />
        <TeamHistory name={detail.team_b?.name ?? t("teamB")} team={teamB} players={playersB} />
      </div>
    </section>
  );
}

function EvaluationPanel({ detail }: { detail: MapDetail }) {
  const { locale, t } = useI18n();
  const futureOdds = detail.future_odds ?? [];
  const resultEvidence = detail.result_evidence ?? [];
  if (!futureOdds.length && !detail.result && !resultEvidence.length) {
    return <PanelEmpty text={t("noEvaluationEvidence")} />;
  }
  return (
    <section className="evaluation-layout tab-content">
      <div>
        <h3>{t("futureOdds")}</h3>
        <table className="cds--data-table cds--data-table--sm">
          <thead>
            <tr>
              <th>{t("capture")}</th>
              <th>{t("state")}</th>
              <th>{t("odds")}</th>
              <th>{t("observed")}</th>
              <th>{t("pairSkew")}</th>
            </tr>
          </thead>
          <tbody>
            {futureOdds.map((capture) => (
              <tr key={capture.id}>
                <td>{capture.capture_type === "CLOSING" ? t("closingOdds") : `${capture.horizon_seconds}s`}</td>
                <td><StatusLabel status={capture.status} compact /></td>
                <td>{capture.odds_a == null || capture.odds_b == null ? t("unknown") : `${Number(capture.odds_a).toFixed(2)} / ${Number(capture.odds_b).toFixed(2)}`}</td>
                <td>{formatTime(capture.observed_at, locale)}</td>
                <td>{seconds(capture.pair_skew_seconds, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3>{t("resultEvidence")}</h3>
        <div className="audit-grid result-summary">
          <Metric label={t("winner")} value={detail.result?.winner_team_id ?? t("unknown")} />
          <Metric label={t("resultConflict")} value={translateStatus(detail.result?.provider_conflict ? "DATA_CONFLICT" : detail.result ? "READY" : "UNKNOWN", locale)} />
          <Metric label={t("firstUsable")} value={formatTime(detail.result?.basic_first_usable_at, locale)} />
        </div>
        <div className="evidence-list">
          {resultEvidence.map((evidence) => (
            <article key={evidence.id}>
              <div><strong>{providerName(evidence.provider)}</strong><StatusLabel status={evidence.conflict_status} compact /></div>
              <span>{t("winner")} {evidence.winner_team_id ?? t("unknown")}</span>
              <span>{t("confidence")} {percent(evidence.identity_confidence, locale)}</span>
              <span>{t("firstUsable")} {formatTime(evidence.first_usable_at, locale)}</span>
              <small>{evidence.normalizer_version} / {evidence.provider_match_id}</small>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function TeamHistory({
  name,
  team,
  players
}: {
  name: string;
  team: Record<string, unknown> | null;
  players: unknown[];
}) {
  const { locale, t } = useI18n();
  return (
    <article className="team-history">
      <h3>{name}</h3>
      <div className="compact-metrics">
        <Metric label={t("baseElo")} value={metricText(team?.base_rating, locale)} />
        <Metric label={t("recentForm")} value={signed(team?.recent_form, locale)} />
        <Metric label={t("rosterStrength")} value={signed(team?.current_roster_strength, locale)} />
        <Metric label={t("rosterStability")} value={percentValue(team?.roster_stability, locale)} />
      </div>
      <table className="cds--data-table cds--data-table--sm">
        <thead>
          <tr>
            <th>{t("position")}</th>
            <th>{t("base")}</th>
            <th>{t("recent")}</th>
            <th>{t("hero")}</th>
            <th>{t("confidence")}</th>
          </tr>
        </thead>
        <tbody>
          {players.map((raw, index) => {
            const player = objectValue(raw) ?? {};
            return (
              <tr key={String(player.canonical_player_id ?? index)}>
                <td>{metricText(player.position, locale)}</td>
                <td>{signed(player.base_strength, locale)}</td>
                <td>{signed(player.recent_form, locale)}</td>
                <td>{signed(player.player_hero_strength, locale)}</td>
                <td>{percentValue(player.player_hero_confidence, locale)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </article>
  );
}

function RuntimePanel({
  runtime,
  jobs
}: {
  runtime: RuntimeSnapshot | undefined;
  jobs: JobSummary | undefined;
}) {
  const { locale, t } = useI18n();
  const workers = Object.values(runtime?.workers ?? {}).sort((a, b) =>
    a.name.localeCompare(b.name)
  );
  return (
    <section className="runtime-layout tab-content">
      <div>
        <h3>{t("businessReadiness")}</h3>
        <table className="cds--data-table cds--data-table--sm dependency-table">
          <thead>
            <tr>
              <th>{t("provider")}</th>
              <th>{t("state")}</th>
              <th>{t("dependencyAge")}</th>
              <th>{t("failures")}</th>
            </tr>
          </thead>
          <tbody>
            {Object.values(runtime?.dependencies ?? {}).map((dependency) => (
              <tr key={dependency.name}>
                <td>{translateDependency(dependency.name, locale)}</td>
                <td><StatusLabel status={dependency.status} compact /></td>
                <td>{seconds(dependency.age_seconds, locale)}</td>
                <td>{dependency.consecutive_failures}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3>{t("workers")}</h3>
        <table className="cds--data-table cds--data-table--sm worker-table">
          <thead>
            <tr>
              <th>{t("worker")}</th>
              <th>{t("state")}</th>
              <th>{t("messages")}</th>
              <th>{t("restarts")}</th>
              <th>{t("lastSuccess")}</th>
            </tr>
          </thead>
          <tbody>
            {workers.map((worker) => (
              <tr key={worker.name}>
                <td>{worker.name}</td>
                <td><StatusLabel status={worker.state} compact /></td>
                <td>{worker.messages_received}</td>
                <td>{worker.restart_count}</td>
                <td>{formatTime(worker.last_success_at, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3>{t("durableJobs")}</h3>
        <div className="job-statuses">
          {Object.entries(jobs?.by_status ?? {}).map(([status, count]) => (
            <Metric key={status} label={translateStatus(status, locale)} value={String(count)} />
          ))}
        </div>
        {jobs?.recent_failures.length ? (
          <div className="failure-list">
            {jobs.recent_failures.map((failure) => (
              <article key={failure.id}>
                <strong>{failure.job_type}</strong>
                <span>{failure.last_error ?? t("unknownError")}</span>
                <small>{failure.attempt_count} {t("attempts")}</small>
              </article>
            ))}
          </div>
        ) : (
          <PanelEmpty text={t("noTerminalFailures")} />
        )}
      </div>
    </section>
  );
}

function PanelHeading({ title, status }: { title: string; status: string }) {
  return (
    <header className="panel-heading">
      <h2>{title}</h2>
      <StatusLabel status={status} compact />
    </header>
  );
}

function StatusLabel({
  status,
  compact = false
}: {
  status: string;
  compact?: boolean;
}) {
  const { locale } = useI18n();
  return <span className={`status-label ${statusTone(status)}${compact ? " compact" : ""}`}>
    {translateStatus(status, locale)}
  </span>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric compact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MarketPair({
  pair,
  teamA,
  teamB
}: {
  pair: { teamA: MarketObservation; teamB: MarketObservation };
  teamA?: string | null;
  teamB?: string | null;
}) {
  const { locale, t } = useI18n();
  return (
    <div className="market-pair">
      <article>
        <span>{teamA ?? t("teamA")}</span>
        <strong>{Number(pair.teamA.price).toFixed(2)}</strong>
        <small>{t("fair")} {pair.teamA.fair_probability == null ? t("unknown") : percent(pair.teamA.fair_probability, locale)}</small>
      </article>
      <span className="market-pair-versus">{t("versus")}</span>
      <article>
        <span>{teamB ?? t("teamB")}</span>
        <strong>{Number(pair.teamB.price).toFixed(2)}</strong>
        <small>{t("fair")} {pair.teamB.fair_probability == null ? t("unknown") : percent(pair.teamB.fair_probability, locale)}</small>
      </article>
    </div>
  );
}

function ReasonList({ title, values }: { title: string; values?: string[] }) {
  if (!values?.length) return null;
  return (
    <div className="reason-group">
      <strong>{title}</strong>
      {values.slice(0, 3).map((value) => <p key={value}>{value}</p>)}
    </div>
  );
}

function Chart({ option, label }: { option: object; label: string }) {
  return (
    <div className="chart" role="img" aria-label={label}>
      <IntelligenceChart option={option} />
    </div>
  );
}

function PanelEmpty({ text }: { text: string }) {
  return <div className="panel-empty">{text}</div>;
}

function WorkspaceSkeleton() {
  return (
    <div className="workspace-skeleton">
      <SkeletonText heading width="42%" />
      <SkeletonText paragraph lineCount={12} />
    </div>
  );
}

function EmptyWorkspace({ overall }: { overall?: string }) {
  const { t } = useI18n();
  return (
    <section className="empty-workspace">
      <StatusLabel status={overall ?? "STARTING"} />
      <h1>{t("waitingCanonicalMap")}</h1>
      <p>{t("runtimeStatusVisible")}</p>
    </section>
  );
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function shortHash(value: string | null | undefined): string {
  return value ? `${value.slice(0, 12)}...` : "-";
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function statusTone(status: string): string {
  if (["READY", "RUNNING", "SAFE", "SUCCESS", "LIVE_BASIC", "LIVE_FULL"].includes(status)) {
    return "positive";
  }
  if (["FAILED", "FAILED_TERMINAL", "ACTION_REQUIRED", "UNSAFE", "MISSING"].includes(status)) {
    return "negative";
  }
  if (["DEGRADED", "CAUTION", "RESTARTING", "PARTIAL", "POST_DRAFT", "PENDING_MAP_IDENTITY"].includes(status)) {
    return "warning";
  }
  return "neutral";
}

function providerName(provider: string): string {
  return { openai: "GPT", anthropic: "Claude", gemini: "Gemini" }[provider] ?? provider;
}

function percent(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale, {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1
  }).format(value);
}

function percentValue(value: unknown, locale: Locale): string {
  return typeof value === "number" ? percent(value, locale) : translate("unknown", locale);
}

function signed(value: unknown, locale: Locale): string {
  return typeof value === "number"
    ? new Intl.NumberFormat(locale, {
        signDisplay: "exceptZero",
        minimumFractionDigits: 1,
        maximumFractionDigits: 1
      }).format(value)
    : translate("unknown", locale);
}

function metricText(value: unknown, locale: Locale): string {
  return typeof value === "number" || typeof value === "string"
    ? String(value)
    : translate("unknown", locale);
}

function seconds(value: number | null | undefined, locale: Locale): string {
  return value == null || !Number.isFinite(value) ? translate("unknown", locale) : `${value.toFixed(1)}s`;
}

function formatLatency(value: number | null, locale: Locale): string {
  return value == null ? translate("unknownLatency", locale) : `${(value * 1000).toFixed(0)}ms`;
}

function formatGameTime(value: number | null | undefined, locale: Locale): string {
  if (value == null) return translate("unknown", locale);
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

function formatFirstBlood(value: string | null | undefined, locale: Locale): string {
  if (!value) return translate("unknown", locale);
  const side = value.toLowerCase();
  if (side === "radiant" || side === "dire") return translate(side, locale);
  return value;
}

function formatTime(value: string | null | undefined, locale: Locale): string {
  if (!value) return translate("notObserved", locale);
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? translate("invalidTime", locale) : date.toLocaleTimeString(locale);
}

function formatDateTime(value: string | null | undefined, locale: Locale): string {
  if (!value) return translate("notObserved", locale);
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? translate("invalidTime", locale)
    : date.toLocaleString(locale);
}

function formatSchedule(value: string | null | undefined, locale: Locale): string {
  if (!value) return translate("scheduleUnknown", locale);
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return translate("invalidTime", locale);
  const today = new Date();
  const sameDay = date.getFullYear() === today.getFullYear()
    && date.getMonth() === today.getMonth()
    && date.getDate() === today.getDate();
  return sameDay
    ? date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleString(locale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function teamNameForSelection(
  match: MapSummary,
  selectionTeamId: string | null,
  fallback: string
): string {
  if (selectionTeamId === match.team_a?.id) return match.team_a.name;
  if (selectionTeamId === match.team_b?.id) return match.team_b.name;
  return fallback;
}

function primaryMarketPair(
  markets: MarketObservation[],
  teamAId: string | null | undefined,
  teamBId: string | null | undefined
): { teamA: MarketObservation; teamB: MarketObservation } | null {
  if (!teamAId || !teamBId) return null;
  const groups = new Map<string, MarketObservation[]>();
  for (const item of markets) {
    if (item.selection_team_id !== teamAId && item.selection_team_id !== teamBId) continue;
    const key = `${item.market_type ?? ""}\u0000${item.match_stage ?? ""}`;
    const group = groups.get(key) ?? [];
    group.push(item);
    groups.set(key, group);
  }
  const candidates = [...groups.entries()]
    .filter(([, group]) =>
      group.some((item) => item.selection_team_id === teamAId)
      && group.some((item) => item.selection_team_id === teamBId)
    )
    .sort(([left], [right]) => marketPriority(left) - marketPriority(right));
  const selected = candidates[0]?.[1];
  const teamA = selected?.find((item) => item.selection_team_id === teamAId);
  const teamB = selected?.find((item) => item.selection_team_id === teamBId);
  return teamA && teamB ? { teamA, teamB } : null;
}

function marketPriority(key: string): number {
  const normalized = key.toLowerCase();
  if (normalized.startsWith("winner\u0000final")) return 0;
  if (normalized.startsWith("winner\u0000")) return 1;
  return 2;
}

function marketLabel(item: MarketObservation, fallback: string): string {
  return [item.market_type, item.match_stage].filter(Boolean).join(" / ") || fallback;
}

function latestReceivedAt(items: MarketObservation[]): string | null {
  return items.map((item) => item.received_at).sort().at(-1) ?? null;
}

function shortVersion(value: string | null | undefined, fallback: string): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (!Number.isNaN(date.valueOf())) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return value.length > 18 ? `${value.slice(0, 15)}...` : value;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}
