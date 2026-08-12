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
          <ReadinessStrip runtime={runtime.data} loading={runtime.isLoading} />
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
  const title = `${map.team_a?.name ?? t("unknownTeam")} ${t("versus")} ${map.team_b?.name ?? t("unknownTeam")}`;
  const headlineMarket = marketHeadline(map);
  return (
    <button
      type="button"
      className={`match-button${selected ? " selected" : ""}`}
      onClick={onSelect}
    >
      <span className="match-button-title">{title}</span>
      <span className="match-button-meta">
        {map.entity_type === "MAP"
          ? `${t("map")} ${map.map_number ?? "?"}`
          : map.round ?? t("series")}
        <span>{translateStatus(
          map.identity_status === "PENDING_MAP_IDENTITY"
            ? map.identity_status
            : map.latest_snapshot?.mode ?? "NO_SNAPSHOT",
          locale
        )}</span>
      </span>
      <span className="match-button-market">
        {headlineMarket ?? t("marketUnavailable")}
      </span>
    </button>
  );
}

function PendingIdentityWorkspace({ match }: { match: MapSummary }) {
  const { locale, t } = useI18n();
  const title = `${match.team_a?.name ?? t("unknownTeam")} ${t("versus")} ${match.team_b?.name ?? t("unknownTeam")}`;
  return (
    <section className="pending-identity-workspace">
      <header className="pending-identity-header">
        <div>
          <span className="eyebrow">{match.tournament_name ?? t("unknownTournament")}</span>
          <h1>{title}</h1>
          <p>{t("pendingIdentityDescription")}</p>
        </div>
        <StatusLabel status={match.identity_status} />
      </header>
      <div className="pending-identity-facts">
        <Metric label={t("raybetMatchId")} value={String(match.provider_match_id ?? t("unknown"))} />
        <Metric label={t("format")} value={match.round ?? t("unknown")} />
        <Metric label={t("scheduledAt")} value={formatDateTime(match.scheduled_at, locale)} />
        <Metric label={t("lastDiscoveredAt")} value={formatDateTime(match.provider_observed_at, locale)} />
      </div>
      <div className="pending-market-section">
        <PanelHeading title={t("raybetMarkets")} status={match.market.length ? "READY" : "UNKNOWN"} />
        {match.market.length ? (
          <table className="cds--data-table cds--data-table--sm">
            <thead>
              <tr>
                <th>{t("selection")}</th>
                <th>{t("market")}</th>
                <th>{t("odds")}</th>
                <th>{t("observed")}</th>
              </tr>
            </thead>
            <tbody>
              {match.market.slice(0, 12).map((item) => (
                <tr key={item.odds_id}>
                  <td>{teamNameForSelection(match, item.selection_team_id, t("unknown"))}</td>
                  <td>{[item.market_type, item.match_stage].filter(Boolean).join(" / ") || t("unknown")}</td>
                  <td>{Number(item.price).toFixed(2)}</td>
                  <td>{formatDateTime(item.received_at, locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <PanelEmpty text={t("marketUnavailable")} />
        )}
      </div>
    </section>
  );
}

function ReadinessStrip({
  runtime,
  loading
}: {
  runtime: RuntimeSnapshot | undefined;
  loading: boolean;
}) {
  const { locale, t } = useI18n();
  if (loading) {
    return <div className="readiness-strip loading" aria-label={t("loadingReadiness")} />;
  }
  return (
    <section className="readiness-strip" aria-label={t("businessReadiness")}>
      {DEPENDENCY_ORDER.map((name) => {
        const dependency = runtime?.dependencies[name];
        return (
          <div className="dependency" key={name} title={dependency?.message ?? undefined}>
            <span>{translateDependency(name, locale)}</span>
            <StatusLabel status={dependency?.status ?? "UNKNOWN"} compact />
            <small>{t("dependencyAge")} {seconds(dependency?.age_seconds, locale)}</small>
          </div>
        );
      })}
    </section>
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
  return (
    <>
      <header className="map-header">
        <div>
          <p className="map-context">
            {t("map")} {detail.map_number ?? "?"} / {t("valve")} {detail.valve_match_id ?? t("unresolved")}
          </p>
          <h1>
            {detail.team_a?.name ?? t("unknownTeam")} <span>{t("versus")}</span>{" "}
            {detail.team_b?.name ?? t("unknownTeam")}
          </h1>
        </div>
        <div className="map-state">
          <StatusLabel status={detail.latest_snapshot?.mode ?? "NO SNAPSHOT"} />
          <span>{t("decisionAt")} {formatTime(detail.latest_snapshot?.decision_at, locale)}</span>
          <code title={detail.latest_snapshot?.snapshot_hash}>
            {t("snapshotHash")} {shortHash(detail.latest_snapshot?.snapshot_hash)}
          </code>
        </div>
      </header>

      {(blockers.length > 0 || warnings.length > 0) && (
        <section className="quality-band" aria-label={t("dataQuality")}>
          <div>
            <strong>{t("dataQuality")}</strong>
            <span>{blockers.length ? t("decisionBlocked") : t("decisionDegraded")}</span>
          </div>
          <div className="quality-tags">
            {blockers.map((item) => (
              <Tag key={item} type="red" size="sm" title={item}>
                {translateStatus(item, locale)}
              </Tag>
            ))}
            {warnings.map((item) => (
              <Tag key={item} type="warm-gray" size="sm" title={item}>
                {translateStatus(item, locale)}
              </Tag>
            ))}
          </div>
        </section>
      )}

      <section className="decision-layout">
        <div className="primary-intelligence">
          <MarketPanel detail={detail} />
          <DraftPanel detail={detail} />
        </div>
        <AiPanel detail={detail} />
      </section>

      <Tabs>
        <TabList aria-label={t("mapIntelligenceViews")} contained>
          <Tab>{t("live")}</Tab>
          <Tab>{t("historical")}</Tab>
          <Tab>{t("evaluation")}</Tab>
          <Tab>{t("runtime")}</Tab>
        </TabList>
        <TabPanels>
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

function MarketPanel({ detail }: { detail: MapDetail }) {
  const { locale, t } = useI18n();
  const quality = detail.market_quality;
  const series = useMemo(() => {
    const grouped = new Map<number, Array<[string, number]>>();
    detail.market_timeline.forEach((item) => {
      const values = grouped.get(item.odds_id) ?? [];
      values.push([item.received_at, Number(item.price)]);
      grouped.set(item.odds_id, values);
    });
    return [...grouped.entries()].map(([oddsId, data], index) => ({
      name: detail.market.find((item) => item.odds_id === oddsId)?.selection_team_id
        ? `${t("selection")} ${index + 1}`
        : `${t("odds")} ${oddsId}`,
      type: "line",
      showSymbol: false,
      data
    }));
  }, [detail.market, detail.market_timeline, t]);
  return (
    <section className="intel-panel market-panel">
      <PanelHeading
        title={t("market")}
        status={quality?.eligible ? "FRESH" : detail.market.length ? "DEGRADED" : "MISSING"}
      />
      <div className="metric-row">
        {detail.market.slice(0, 2).map((item, index) => (
          <div className="metric" key={item.odds_id}>
            <span>{index === 0 ? detail.team_a?.name : detail.team_b?.name}</span>
            <strong>{Number(item.price).toFixed(2)}</strong>
            <small>
              {t("fair")} {item.fair_probability == null ? t("unknown") : percent(item.fair_probability, locale)}
            </small>
          </div>
        ))}
      </div>
      <div className="audit-grid">
        <Metric
          label={t("pairQuality")}
          value={translateStatus(quality?.eligible ? "READY" : "MISSING", locale)}
        />
        <Metric label={t("pairSkew")} value={seconds(quality?.pair_skew_seconds, locale)} />
        <Metric
          label={t("oddsAge")}
          value={seconds(Math.max(...detail.market.map((item) => item.age_seconds), 0), locale)}
        />
        <Metric
          label={t("metadataVersion")}
          value={quality?.metadata_version ?? detail.market[0]?.metadata_version ?? t("unknown")}
        />
      </div>
      {series.length ? (
        <Chart
          option={{
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#c6c6c6" } },
            grid: { left: 44, right: 16, top: 42, bottom: 30 },
            xAxis: { type: "time", axisLabel: { color: "#8d8d8d" } },
            yAxis: { type: "value", scale: true, axisLabel: { color: "#8d8d8d" } },
            series
          }}
          label={t("marketOddsTimeline")}
        />
      ) : (
        <PanelEmpty text={t("noRayBetOdds")} />
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
    <section className="intel-panel draft-panel">
      <PanelHeading
        title={t("draftIntelligence")}
        status={detail.draft?.complete ? "READY" : detail.draft ? "PARTIAL" : "MISSING"}
      />
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
        <PanelEmpty text={t("noAiDecisions")} />
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
  return value == null ? translate("unknown", locale) : `${value.toFixed(1)}s`;
}

function formatLatency(value: number | null, locale: Locale): string {
  return value == null ? translate("unknownLatency", locale) : `${(value * 1000).toFixed(0)}ms`;
}

function formatGameTime(value: number | null | undefined, locale: Locale): string {
  if (value == null) return translate("unknown", locale);
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
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

function teamNameForSelection(
  match: MapSummary,
  selectionTeamId: string | null,
  fallback: string
): string {
  if (selectionTeamId === match.team_a?.id) return match.team_a.name;
  if (selectionTeamId === match.team_b?.id) return match.team_b.name;
  return fallback;
}

function marketHeadline(match: MapSummary): string | null {
  const teamAId = match.team_a?.id;
  const teamBId = match.team_b?.id;
  if (!teamAId || !teamBId) return null;
  const groups = new Map<string, typeof match.market>();
  for (const item of match.market) {
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
  if (!selected) return null;
  const priceA = selected.find((item) => item.selection_team_id === teamAId)?.price;
  const priceB = selected.find((item) => item.selection_team_id === teamBId)?.price;
  return priceA != null && priceB != null
    ? `${Number(priceA).toFixed(2)} / ${Number(priceB).toFixed(2)}`
    : null;
}

function marketPriority(key: string): number {
  const normalized = key.toLowerCase();
  if (normalized.startsWith("winner\u0000final")) return 0;
  if (normalized.startsWith("winner\u0000")) return 1;
  return 2;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}
