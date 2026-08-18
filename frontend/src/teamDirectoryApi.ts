import { useQuery } from "@tanstack/react-query";

export interface TeamDirectoryEntry {
  id: string;
  name: string;
  slug: string | null;
  short_name: string | null;
  valve_team_id: number | null;
  identity_source: "registry" | "opendota" | null;
  country_code: string | null;
  logo_url: string | null;
  logo_source: string | null;
  website_url: string | null;
  source_url: string | null;
  observed_at: string | null;
}

const teamDirectoryKey = ["product", "team-directory"] as const;

export async function fetchTeamDirectory(): Promise<TeamDirectoryEntry[]> {
  const response = await fetch("/api/teams", {
    cache: "no-store",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<TeamDirectoryEntry[]>;
}

export function useTeamDirectory() {
  return useQuery({
    queryKey: teamDirectoryKey,
    queryFn: fetchTeamDirectory,
    staleTime: 5 * 60_000,
    retry: false,
    refetchOnWindowFocus: false
  });
}
