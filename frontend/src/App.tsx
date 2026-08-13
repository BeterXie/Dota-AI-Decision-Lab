import React, { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchJobs,
  fetchMap,
  fetchMaps,
  fetchRuntime,
  queryKeys,
  useRuntimeSocket
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

  // Auto-select first map if none selected
  const activeMapId = useMemo(() => {
    if (selectedMapId) return selectedMapId;
    if (maps.data && maps.data.length > 0) {
      return maps.data[0].id;
    }
    return null;
  }, [selectedMapId, maps.data]);

  const selectedMatch = useMemo(() => {
    return maps.data?.find((m) => m.id === activeMapId) || maps.data?.[0];
  }, [maps.data, activeMapId]);

  const selectedCanonicalMapId = selectedMatch?.canonical_map_id ?? null;

  const detail = useQuery({
    queryKey: selectedCanonicalMapId ? queryKeys.map(selectedCanonicalMapId) : ["map", "none"],
    queryFn: () => fetchMap(selectedCanonicalMapId!),
    enabled: Boolean(selectedCanonicalMapId),
    refetchInterval: 4000
  });

  const handleRefresh = () => {
    void queryClient.invalidateQueries();
  };

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
