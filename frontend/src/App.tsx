import React, { lazy, Suspense, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchJobs,
  fetchMap,
  fetchMaps,
  fetchRuntime,
  queryKeys,
  useRuntimeSocket,
  type MapDetail,
  type MapSummary
} from "./api";
import { fetchAuthSession, logout, type AuthSessionState } from "./authApi";
import { I18nProvider, useI18n } from "./i18n";
import { AppShell } from "./components/AppShell";
import { AuthAccountBadge } from "./components/AuthAccountBadge";
import { LoginPage } from "./components/LoginPage";

const ReviewPage = lazy(() => import("./components/ReviewPage").then((module) => ({ default: module.ReviewPage })));
const authSessionKey = ["auth", "session"] as const;

export function App() {
  return (
    <I18nProvider>
      <AuthenticatedApp />
    </I18nProvider>
  );
}

function AuthenticatedApp() {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  const auth = useQuery({
    queryKey: authSessionKey,
    queryFn: fetchAuthSession,
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    retry: 1
  });

  if (auth.isLoading) {
    return <div className="auth-bootstrap">Dota AI Decision Lab</div>;
  }
  if (auth.isError || !auth.data) {
    return (
      <div className="auth-bootstrap">
        <div>
          <strong>{t("authSessionUnavailable")}</strong>
          <div style={{ marginTop: 10 }}>
            <button type="button" onClick={() => void auth.refetch()}>
              {t("authRetry")}
            </button>
          </div>
        </div>
      </div>
    );
  }
  if (auth.data.enabled && !auth.data.authenticated) {
    return (
      <LoginPage
        onAuthenticated={(session: AuthSessionState) => {
          queryClient.setQueryData(authSessionKey, session);
        }}
      />
    );
  }

  const handleLogout = async () => {
    await logout();
    queryClient.clear();
    queryClient.setQueryData<AuthSessionState>(authSessionKey, {
      enabled: true,
      authenticated: false,
      user: null
    });
  };
  const reviewRoute = typeof window !== "undefined" && isReviewRoute(window.location.pathname);
  const content = reviewRoute ? (
    <Suspense fallback={<div className="auth-bootstrap">Dota AI Decision Lab</div>}>
      <ReviewPage />
    </Suspense>
  ) : (
    <DashboardApp />
  );

  return (
    <>
      {content}
      {auth.data.enabled && auth.data.user && (
        <AuthAccountBadge user={auth.data.user} onLogout={handleLogout} />
      )}
    </>
  );
}

export function isReviewRoute(pathname: string): boolean {
  return pathname === "/review" || pathname.startsWith("/review/");
}

function DashboardApp() {
  useRuntimeSocket();
  const queryClient = useQueryClient();
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null);

  const runtime = useQuery({ queryKey: queryKeys.runtime, queryFn: fetchRuntime, refetchInterval: 5000 });
  const maps = useQuery({ queryKey: queryKeys.maps, queryFn: fetchMaps, refetchInterval: 5000 });
  const jobs = useQuery({ queryKey: queryKeys.jobs, queryFn: fetchJobs, refetchInterval: 5000 });

  // /api/matches intentionally stays lightweight and currently omits decisions.
  // Enrich only resolved LIVE maps from the detail endpoint so BUY-priority and
  // rail decision badges reflect real production data without fanning out over
  // every historical/upcoming match. Identical query keys share the cache with
  // the selected-map detail query below.
  const liveCanonicalMapIds = (maps.data ?? [])
    .filter((match) => match.phase === "LIVE" && match.canonical_map_id)
    .map((match) => match.canonical_map_id as string);
  const liveDetailQueries = useQueries({
    queries: liveCanonicalMapIds.map((canonicalMapId) => ({
      queryKey: queryKeys.map(canonicalMapId),
      queryFn: () => fetchMap(canonicalMapId),
      refetchInterval: 4000
    }))
  });
  const liveDetailsById = new Map<string, MapDetail>();
  for (const query of liveDetailQueries) {
    if (query.data?.canonical_map_id) {
      liveDetailsById.set(query.data.canonical_map_id, query.data);
    }
  }
  const enrichedMatches: MapSummary[] = (maps.data ?? []).map((match) =>
    match.canonical_map_id ? liveDetailsById.get(match.canonical_map_id) ?? match : match
  );

  const activeMapId = chooseActiveMapId(selectedMapId, enrichedMatches);
  const selectedMatch = enrichedMatches.find((match) => match.id === activeMapId) || enrichedMatches[0];
  const selectedCanonicalMapId = selectedMatch?.canonical_map_id ?? null;
  const detail = useQuery({
    queryKey: selectedCanonicalMapId ? queryKeys.map(selectedCanonicalMapId) : ["map", "none"],
    queryFn: () => fetchMap(selectedCanonicalMapId!),
    enabled: Boolean(selectedCanonicalMapId),
    placeholderData: isEmbeddedDetail(selectedMatch) ? selectedMatch : undefined,
    refetchInterval: 4000
  });

  // Once a non-live map is selected, reuse its loaded detail in the rail too.
  // This keeps the selected card's decision badge consistent without fetching
  // details for every non-live match.
  const shellMatches: MapSummary[] = detail.data?.canonical_map_id
    ? enrichedMatches.map((match) =>
        match.canonical_map_id === detail.data!.canonical_map_id ? detail.data! : match
      )
    : enrichedMatches;

  const handleRefresh = () => { void queryClient.invalidateQueries(); };

  return (
    <AppShell
      runtime={runtime.data}
      jobs={jobs.data}
      matches={shellMatches}
      selectedMatch={selectedMatch}
      detail={detail.data}
      detailLoading={detail.isLoading}
      detailError={detail.error}
      selectedMapId={activeMapId}
      onSelectMatch={setSelectedMapId}
      onRefresh={handleRefresh}
    />
  );
}

function chooseActiveMapId(selectedMapId: string | null, matches: MapSummary[]): string | null {
  if (selectedMapId && matches.some((match) => match.id === selectedMapId)) {
    return selectedMapId;
  }
  if (matches.length === 0) return null;

  // 1. Prioritize LIVE matches (especially those with BUY decisions).
  const liveMatches = matches.filter((match) => match.phase === "LIVE");
  if (liveMatches.length > 0) {
    const liveWithBuy = liveMatches.find((match) =>
      match.decisions?.some(
        (decision) => decision.decision?.action === "BUY_A" || decision.decision?.action === "BUY_B"
      )
    );
    if (liveWithBuy) return liveWithBuy.id;
    return liveMatches[0].id;
  }

  // 2. Prioritize closest UPCOMING / PREMATCH match.
  const upcomingMatches = matches.filter((match) => match.phase === "PREMATCH" || match.phase === "UNKNOWN");
  if (upcomingMatches.length > 0) {
    const sortedUpcoming = [...upcomingMatches].sort((a, b) => {
      const timeA = a.scheduled_at ? Date.parse(a.scheduled_at) : Infinity;
      const timeB = b.scheduled_at ? Date.parse(b.scheduled_at) : Infinity;
      return timeA - timeB;
    });
    return sortedUpcoming[0].id;
  }

  // 3. Fallback to newest finished POSTMATCH match.
  const finishedMatches = matches.filter((match) => match.phase === "POSTMATCH" || match.phase === "AWAITING_RESULT");
  if (finishedMatches.length > 0) {
    const sortedFinished = [...finishedMatches].sort((a, b) => {
      const timeA = a.scheduled_at ? Date.parse(a.scheduled_at) : 0;
      const timeB = b.scheduled_at ? Date.parse(b.scheduled_at) : 0;
      return timeB - timeA;
    });
    return sortedFinished[0].id;
  }

  return matches[0].id;
}

function isEmbeddedDetail(match: MapSummary | undefined): match is MapDetail {
  return Boolean(match && "market_timeline" in match && "future_odds" in match && "result_evidence" in match);
}
