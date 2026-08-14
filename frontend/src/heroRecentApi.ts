export interface HeroRecentUseSummary {
  maps: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  knowledge_cutoff: string | null;
  last_included_match_id: string | null;
}

export interface DraftHeroRecentSlot {
  side: "radiant" | "dire";
  position: number;
  canonical_player_id: string | null;
  hero_id: number | null;
  recent: HeroRecentUseSummary | null;
}

export interface DraftHeroRecentResponse {
  canonical_map_id: string;
  statistics_cutoff: string | null;
  window: number;
  slots: DraftHeroRecentSlot[];
}

export async function fetchDraftHeroRecent(
  canonicalMapId: string,
  signal?: AbortSignal,
): Promise<DraftHeroRecentResponse> {
  const response = await fetch(`/api/maps/${canonicalMapId}/draft-hero-recent`, {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<DraftHeroRecentResponse>;
}
