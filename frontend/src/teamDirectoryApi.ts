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

export interface TeamRosterSubject {
  type: "PLAYER" | "STAFF" | "UNKNOWN";
  id: string | null;
  name: string | null;
  account_id: number | null;
  real_name: string | null;
  country_code: string | null;
  avatar_url: string | null;
}

export interface TeamRosterMembership {
  id: string;
  subject: TeamRosterSubject;
  role: string;
  position: number | null;
  is_standin: boolean;
  valid_from: string | null;
  valid_to: string | null;
  source_name: string;
  source_url: string | null;
  observed_at: string;
  confidence: number;
}

export interface TeamDetail extends TeamDirectoryEntry {
  current_roster: TeamRosterMembership[];
  roster_history: TeamRosterMembership[];
}

export const teamDirectoryKey = ["product", "team-directory"] as const;

export async function fetchTeamDirectory(): Promise<TeamDirectoryEntry[]> {
  const response = await fetch("/api/teams", {
    cache: "no-store",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<TeamDirectoryEntry[]>;
}

export async function fetchTeamDetail(slug: string): Promise<TeamDetail> {
  const response = await fetch(`/api/teams/by-slug/${encodeURIComponent(slug)}`, {
    cache: "no-store",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<TeamDetail>;
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
