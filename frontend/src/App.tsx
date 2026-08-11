import { lazy, Suspense, useEffect, useMemo, useState } from "react";
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

const IntelligenceChart = lazy(() => import("./Chart"));

export function App() {
  useRuntimeSocket();
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
    if (!selectedMapId && maps.data?.length) setSelectedMapId(maps.data[0].id);
  }, [maps.data, selectedMapId]);

  const detail = useQuery({
    queryKey: selectedMapId ? queryKeys.map(selectedMapId) : ["map", "none"],
    queryFn: () => fetchMap(selectedMapId!),
    enabled: Boolean(selectedMapId),
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
            <StatusLabel status={runtime.data?.overall ?? "UNKNOWN"} />
            <Button
              kind="ghost"
              size="sm"
              hasIconOnly
              renderIcon={Renew}
              iconDescription="Refresh data"
              onClick={refresh}
            />
          </div>
        </HeaderGlobalBar>
      </Header>
      <div className="app-shell">
        <aside className="match-rail" aria-label="Tracked maps">
          <div className="rail-heading">
            <span>Tracked maps</span>
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
              title="Map feed unavailable"
              subtitle={errorMessage(maps.error)}
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
              <strong>No canonical maps</strong>
              <span>Waiting for provider discovery.</span>
            </div>
          )}
        </aside>

        <main className="workspace">
          <ReadinessStrip runtime={runtime.data} loading={runtime.isLoading} />
          {detail.isLoading && selectedMapId ? (
            <WorkspaceSkeleton />
          ) : detail.isError ? (
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title="Map detail unavailable"
              subtitle={errorMessage(detail.error)}
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

function MatchButton({
  map,
  selected,
  onSelect
}: {
  map: MapSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const title = `${map.team_a?.name ?? "Unknown"} vs ${map.team_b?.name ?? "Unknown"}`;
  return (
    <button
      type="button"
      className={`match-button${selected ? " selected" : ""}`}
      onClick={onSelect}
    >
      <span className="match-button-title">{title}</span>
      <span className="match-button-meta">
        Map {map.map_number ?? "?"}
        <span>{map.latest_snapshot?.mode ?? "NO SNAPSHOT"}</span>
      </span>
      <span className="match-button-market">
        {map.market.length
          ? map.market.map((item) => Number(item.price).toFixed(2)).join(" / ")
          : "Market unavailable"}
      </span>
    </button>
  );
}

function ReadinessStrip({
  runtime,
  loading
}: {
  runtime: RuntimeSnapshot | undefined;
  loading: boolean;
}) {
  if (loading) return <div className="readiness-strip loading" aria-label="Loading readiness" />;
  return (
    <section className="readiness-strip" aria-label="Business readiness">
      {DEPENDENCY_ORDER.map((name) => {
        const dependency = runtime?.dependencies[name];
        return (
          <div className="dependency" key={name} title={dependency?.message ?? undefined}>
            <span>{name.replaceAll("_", " ")}</span>
            <StatusLabel status={dependency?.status ?? "UNKNOWN"} compact />
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
  const quality = detail.latest_snapshot?.quality;
  const blockers = quality?.blockers ?? [];
  const warnings = quality?.warnings ?? [];
  return (
    <>
      <header className="map-header">
        <div>
          <p className="map-context">
            Map {detail.map_number ?? "?"} / Valve {detail.valve_match_id ?? "unresolved"}
          </p>
          <h1>
            {detail.team_a?.name ?? "Unknown"} <span>vs</span>{" "}
            {detail.team_b?.name ?? "Unknown"}
          </h1>
        </div>
        <div className="map-state">
          <StatusLabel status={detail.latest_snapshot?.mode ?? "NO SNAPSHOT"} />
          <span>{formatTime(detail.latest_snapshot?.decision_at)}</span>
        </div>
      </header>

      {(blockers.length > 0 || warnings.length > 0) && (
        <section className="quality-band" aria-label="Data quality">
          <div>
            <strong>Data quality</strong>
            <span>{blockers.length ? "Decision blocked" : "Decision degraded"}</span>
          </div>
          <div className="quality-tags">
            {blockers.map((item) => (
              <Tag key={item} type="red" size="sm">
                {item}
              </Tag>
            ))}
            {warnings.map((item) => (
              <Tag key={item} type="warm-gray" size="sm">
                {item}
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
        <TabList aria-label="Map intelligence views" contained>
          <Tab>Live</Tab>
          <Tab>Historical</Tab>
          <Tab>Runtime</Tab>
        </TabList>
        <TabPanels>
          <TabPanel>
            <LivePanel detail={detail} />
          </TabPanel>
          <TabPanel>
            <HistoryPanel detail={detail} />
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
  const series = useMemo(() => {
    const grouped = new Map<number, Array<[string, number]>>();
    detail.market_timeline.forEach((item) => {
      const values = grouped.get(item.odds_id) ?? [];
      values.push([item.received_at, Number(item.price)]);
      grouped.set(item.odds_id, values);
    });
    return [...grouped.entries()].map(([oddsId, data], index) => ({
      name: detail.market.find((item) => item.odds_id === oddsId)?.selection_team_id
        ? `Selection ${index + 1}`
        : `Odds ${oddsId}`,
      type: "line",
      showSymbol: false,
      data
    }));
  }, [detail.market, detail.market_timeline]);
  return (
    <section className="intel-panel market-panel">
      <PanelHeading title="Market" status={detail.market.length ? "FRESH" : "MISSING"} />
      <div className="metric-row">
        {detail.market.slice(0, 2).map((item, index) => (
          <div className="metric" key={item.odds_id}>
            <span>{index === 0 ? detail.team_a?.name : detail.team_b?.name}</span>
            <strong>{Number(item.price).toFixed(2)}</strong>
            <small>
              Fair {item.fair_probability == null ? "unknown" : percent(item.fair_probability)}
            </small>
          </div>
        ))}
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
          label="Market odds timeline"
        />
      ) : (
        <PanelEmpty text="No RayBet odds observations for this map." />
      )}
    </section>
  );
}

function DraftPanel({ detail }: { detail: MapDetail }) {
  const curve = detail.draft?.curve ?? [];
  const features = detail.draft?.features ?? {};
  const data = (key: keyof (typeof curve)[number]) =>
    curve.map((point) => [point.minute, point[key]]);
  return (
    <section className="intel-panel draft-panel">
      <PanelHeading
        title="Draft Intelligence"
        status={detail.draft?.complete ? "READY" : detail.draft ? "PARTIAL" : "MISSING"}
      />
      <div className="compact-metrics">
        <Metric label="Current edge" value={signed(features.current_edge)} />
        <Metric label="Next 5m" value={signed(features.next_5m_edge)} />
        <Metric label="Peak minute" value={metricText(features.peak_minute)} />
        <Metric label="Peak edge" value={signed(features.peak_edge)} />
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
              { name: "Pure", type: "line", showSymbol: false, data: data("pure_radiant_edge") },
              {
                name: "Player adjusted",
                type: "line",
                showSymbol: false,
                data: data("adjusted_radiant_edge")
              }
            ]
          }}
          label="Draft minute curve"
        />
      ) : (
        <PanelEmpty text="No validated R.O.S.H. curve is available." />
      )}
      {detail.draft?.model_version && (
        <p className="provenance">
          {detail.draft.model_version} / {detail.draft.data_version}
        </p>
      )}
    </section>
  );
}

function AiPanel({ detail }: { detail: MapDetail }) {
  return (
    <section className="ai-panel">
      <PanelHeading title="Independent AI decisions" status={`${detail.decisions.length}/3`} />
      {detail.decisions.length ? (
        <div className="decision-list">
          {detail.decisions.map((record) => (
            <article className="decision-item" key={record.id}>
              <div className="decision-heading">
                <strong>{providerName(record.provider)}</strong>
                <StatusLabel status={record.decision?.action ?? record.parse_status} compact />
              </div>
              <div className="decision-confidence">
                <span>Confidence</span>
                <strong>
                  {record.decision?.confidence == null
                    ? "unknown"
                    : percent(record.decision.confidence)}
                </strong>
              </div>
              {record.error ? (
                <p className="decision-error">{record.error}</p>
              ) : (
                <>
                  <ReasonList title="Reasons" values={record.decision?.primary_reasons} />
                  <ReasonList title="Counter arguments" values={record.decision?.counter_arguments} />
                  <ReasonList
                    title="Quality concerns"
                    values={record.decision?.data_quality_concerns}
                  />
                </>
              )}
              <footer>
                <span>{record.model}</span>
                <span>{formatLatency(record.latency_seconds)}</span>
              </footer>
            </article>
          ))}
        </div>
      ) : (
        <PanelEmpty text="No AI decisions exist for the latest snapshot." />
      )}
    </section>
  );
}

function LivePanel({ detail }: { detail: MapDetail }) {
  const latest = detail.live;
  return (
    <section className="tab-content">
      <div className="compact-metrics live-metrics">
        <Metric label="Game time" value={formatGameTime(latest?.game_time_seconds)} />
        <Metric
          label="Kills"
          value={
            latest?.radiant_kills == null || latest.dire_kills == null
              ? "unknown"
              : `${latest.radiant_kills} - ${latest.dire_kills}`
          }
        />
        <Metric label="Radiant NW" value={signed(latest?.radiant_nw_lead)} />
        <Metric label="Sync" value={detail.sync?.status ?? "UNKNOWN"} />
        <Metric label="P90 lag" value={seconds(detail.sync?.p90_seconds)} />
        <Metric label="Samples" value={metricText(detail.sync?.sample_size)} />
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
                name: "Radiant net worth lead",
                type: "line",
                showSymbol: false,
                data: detail.live_timeline.map((item) => [
                  item.game_time_seconds,
                  item.radiant_nw_lead
                ])
              }
            ]
          }}
          label="DLTV live state timeline"
        />
      ) : (
        <PanelEmpty text="No normalized DLTV fast states are available." />
      )}
    </section>
  );
}

function HistoryPanel({ detail }: { detail: MapDetail }) {
  const history = (detail.snapshot_payload?.history ?? {}) as Record<string, unknown>;
  const teamA = objectValue(history.team_a);
  const teamB = objectValue(history.team_b);
  const playersA = arrayValue(history.players_a);
  const playersB = arrayValue(history.players_b);
  if (!teamA && !teamB) return <PanelEmpty text="No Historical snapshot is attached." />;
  return (
    <section className="history-grid tab-content">
      <TeamHistory name={detail.team_a?.name ?? "Team A"} team={teamA} players={playersA} />
      <TeamHistory name={detail.team_b?.name ?? "Team B"} team={teamB} players={playersB} />
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
  return (
    <article className="team-history">
      <h3>{name}</h3>
      <div className="compact-metrics">
        <Metric label="Base Elo" value={metricText(team?.base_rating)} />
        <Metric label="Recent form" value={signed(team?.recent_form)} />
        <Metric label="Roster strength" value={signed(team?.current_roster_strength)} />
        <Metric label="Roster stability" value={percentValue(team?.roster_stability)} />
      </div>
      <table className="cds--data-table cds--data-table--sm">
        <thead>
          <tr>
            <th>Pos</th>
            <th>Base</th>
            <th>Recent</th>
            <th>Hero</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {players.map((raw, index) => {
            const player = objectValue(raw) ?? {};
            return (
              <tr key={String(player.canonical_player_id ?? index)}>
                <td>{metricText(player.position)}</td>
                <td>{signed(player.base_strength)}</td>
                <td>{signed(player.recent_form)}</td>
                <td>{signed(player.player_hero_strength)}</td>
                <td>{percentValue(player.player_hero_confidence)}</td>
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
  const workers = Object.values(runtime?.workers ?? {}).sort((a, b) =>
    a.name.localeCompare(b.name)
  );
  return (
    <section className="runtime-layout tab-content">
      <div>
        <h3>Workers</h3>
        <table className="cds--data-table cds--data-table--sm worker-table">
          <thead>
            <tr>
              <th>Worker</th>
              <th>State</th>
              <th>Messages</th>
              <th>Restarts</th>
              <th>Last success</th>
            </tr>
          </thead>
          <tbody>
            {workers.map((worker) => (
              <tr key={worker.name}>
                <td>{worker.name}</td>
                <td><StatusLabel status={worker.state} compact /></td>
                <td>{worker.messages_received}</td>
                <td>{worker.restart_count}</td>
                <td>{formatTime(worker.last_success_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3>Durable jobs</h3>
        <div className="job-statuses">
          {Object.entries(jobs?.by_status ?? {}).map(([status, count]) => (
            <Metric key={status} label={status} value={String(count)} />
          ))}
        </div>
        {jobs?.recent_failures.length ? (
          <div className="failure-list">
            {jobs.recent_failures.map((failure) => (
              <article key={failure.id}>
                <strong>{failure.job_type}</strong>
                <span>{failure.last_error ?? "Unknown error"}</span>
                <small>{failure.attempt_count} attempts</small>
              </article>
            ))}
          </div>
        ) : (
          <PanelEmpty text="No terminal job failures." />
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
  return (
    <span className={`status-label ${statusTone(status)}${compact ? " compact" : ""}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
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
      <Suspense fallback={<div className="chart-loading" />}>
        <IntelligenceChart option={option} />
      </Suspense>
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
  return (
    <section className="empty-workspace">
      <StatusLabel status={overall ?? "STARTING"} />
      <h1>Waiting for canonical map discovery</h1>
      <p>Runtime health and provider state remain visible above.</p>
    </section>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown request failure";
}

function statusTone(status: string): string {
  if (["READY", "RUNNING", "SAFE", "SUCCESS", "LIVE_BASIC", "LIVE_FULL"].includes(status)) {
    return "positive";
  }
  if (["FAILED", "FAILED_TERMINAL", "ACTION_REQUIRED", "UNSAFE", "MISSING"].includes(status)) {
    return "negative";
  }
  if (["DEGRADED", "CAUTION", "RESTARTING", "PARTIAL", "POST_DRAFT"].includes(status)) {
    return "warning";
  }
  return "neutral";
}

function providerName(provider: string): string {
  return { openai: "GPT", anthropic: "Claude", gemini: "Gemini" }[provider] ?? provider;
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function percentValue(value: unknown): string {
  return typeof value === "number" ? percent(value) : "unknown";
}

function signed(value: unknown): string {
  return typeof value === "number" ? `${value > 0 ? "+" : ""}${value.toFixed(1)}` : "unknown";
}

function metricText(value: unknown): string {
  return typeof value === "number" || typeof value === "string" ? String(value) : "unknown";
}

function seconds(value: number | null | undefined): string {
  return value == null ? "unknown" : `${value.toFixed(1)}s`;
}

function formatLatency(value: number | null): string {
  return value == null ? "unknown latency" : `${(value * 1000).toFixed(0)}ms`;
}

function formatGameTime(value: number | null | undefined): string {
  if (value == null) return "unknown";
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "not observed";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "invalid time" : date.toLocaleTimeString();
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}
