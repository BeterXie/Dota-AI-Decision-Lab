import React, { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { I18nProvider } from "./i18n";
import { AppShell } from "./components/AppShell";

export function App() {
  return (
    <I18nProvider>
      <DashboardApp />
    </I18nProvider>
  );
}

function DashboardApp() {
  useRuntimeSocket();
  const queryClient = useQueryClient();
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null);

  const runtime = useQuery({ queryKey: queryKeys.runtime, queryFn: fetchRuntime, refetchInterval: 5000 });
  const maps = useQuery({ queryKey: queryKeys.maps, queryFn: fetchMaps, refetchInterval: 5000 });
  const jobs = useQuery({ queryKey: queryKeys.jobs, queryFn: fetchJobs, refetchInterval: 5000 });

  const activeMapId = useMemo(() => {
    if (selectedMapId && maps.data?.some((match) => match.id === selectedMapId)) {
      return selectedMapId;
    }
    // Prefer the live match over the first row so the dashboard opens on the
    // active game instead of an arbitrary pre-match entry.
    const live = maps.data?.find((match) => match.phase === "LIVE");
    if (live) return live.id;
    return maps.data?.[0]?.id ?? null;
  }, [selectedMapId, maps.data]);

  const selectedMatch = useMemo(() => {
    return maps.data?.find((match) => match.id === activeMapId) || maps.data?.[0];
  }, [maps.data, activeMapId]);

  const selectedCanonicalMapId = selectedMatch?.canonical_map_id ?? null;
  const detail = useQuery({
    queryKey: selectedCanonicalMapId ? queryKeys.map(selectedCanonicalMapId) : ["map", "none"],
    queryFn: () => fetchMap(selectedCanonicalMapId!),
    enabled: Boolean(selectedCanonicalMapId),
    placeholderData: isEmbeddedDetail(selectedMatch) ? selectedMatch : undefined,
    refetchInterval: 4000
  });

  const handleRefresh = () => { void queryClient.invalidateQueries(); };

  return (
    <AppShell
      runtime={runtime.data}
      jobs={jobs.data}
      matches={maps.data || []}
      selectedMatch={selectedMatch}
      detail={detail.data}
      selectedMapId={activeMapId}
      onSelectMatch={setSelectedMapId}
      onRefresh={handleRefresh}
    />
  );
}

function isEmbeddedDetail(match: MapSummary | undefined): match is MapDetail {
  return Boolean(match && "market_timeline" in match && "future_odds" in match && "result_evidence" in match);
}
