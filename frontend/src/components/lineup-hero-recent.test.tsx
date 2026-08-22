import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { MapDetail } from "../api";
import { I18nProvider } from "../i18n";
import { LineupCard } from "./LineupCard";

const match = {
  canonical_map_id: "11111111-1111-1111-1111-111111111111",
  team_a: { id: "team-a", name: "Team Yandex" },
  team_b: { id: "team-b", name: "Aurora" },
  draft: {
    slots: [
      {
        side: "radiant",
        position: 1,
        canonical_player_id: "player-1",
        player_name: "watson",
        hero_id: 36,
        hero_name: "Necrophos",
      },
      {
        side: "radiant",
        position: 2,
        canonical_player_id: "player-2",
        player_name: "CHIRA_JUNIOR",
        hero_id: 62,
        hero_name: "Monkey King",
      },
      {
        side: "dire",
        position: 1,
        canonical_player_id: "player-3",
        player_name: "Nightfall",
        hero_id: 74,
        hero_name: "Shadow Fiend",
      },
    ],
  },
  market: [],
  decisions: [],
} as MapDetail;

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("dota-ai-decision-lab-locale", "zh-CN");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        canonical_map_id: match.canonical_map_id,
        statistics_cutoff: "2026-08-15T00:00:00Z",
        window: 10,
        slots: [
          {
            side: "radiant",
            position: 1,
            canonical_player_id: "player-1",
            hero_id: 36,
            recent: {
              maps: 10,
              wins: 7,
              losses: 3,
              win_rate: 0.7,
              knowledge_cutoff: "2026-08-14T00:00:00Z",
              last_included_match_id: "match-10",
            },
          },
          {
            side: "radiant",
            position: 2,
            canonical_player_id: "player-2",
            hero_id: 62,
            recent: {
              maps: 6,
              wins: 4,
              losses: 2,
              win_rate: 4 / 6,
              knowledge_cutoff: "2026-08-14T00:00:00Z",
              last_included_match_id: "match-6",
            },
          },
          {
            side: "dire",
            position: 1,
            canonical_player_id: "player-3",
            hero_id: 74,
            recent: {
              maps: 0,
              wins: 0,
              losses: 0,
              win_rate: null,
              knowledge_cutoff: null,
              last_included_match_id: null,
            },
          },
        ],
      }),
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("lineup cards show the actual recent sample, win rate, and record", async () => {
  render(
    <I18nProvider>
      <LineupCard match={match} />
    </I18nProvider>,
  );

  expect(await screen.findByText("近10场 70% · 7–3")).toBeInTheDocument();
  expect(screen.getByText("近6场 67% · 4–2")).toBeInTheDocument();
  expect(screen.getByText("近期无使用记录")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    `/api/maps/${match.canonical_map_id}/draft-hero-recent`,
    expect.objectContaining({ cache: "no-store" }),
  );
});

test("reports partial draft progress without inventing lineup slots", () => {
  render(
    <I18nProvider>
      <LineupCard
        match={{
          ...match,
          draft: {
            ...match.draft!,
            complete: false,
            roster_ready_count: 10,
            hero_ready_count: 9,
            slots: [],
          },
        }}
      />
    </I18nProvider>,
  );

  expect(screen.getByText(/已识别 10\/10 名选手、9\/10 个英雄/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /P1/ })).not.toBeInTheDocument();
});

function recentResponse(recent: unknown) {
  return {
    ok: true,
    json: async () => ({
      canonical_map_id: match.canonical_map_id,
      statistics_cutoff: "2026-08-15T00:00:00Z",
      window: 10,
      slots: [
        {
          side: "radiant",
          position: 1,
          canonical_player_id: "player-1",
          hero_id: 36,
          recent,
        },
      ],
    }),
  };
}

test("unknown heroes are labelled hero-not-picked instead of data unavailable", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(recentResponse(null)),
  );
  const partialDraft = {
    ...match,
    draft: {
      observed_at: "2026-08-15T01:00:00Z",
      slots: [
        {
          side: "radiant",
          position: 1,
          canonical_player_id: "player-1",
          player_name: "watson",
          hero_id: null,
          hero_name: null,
        },
      ],
    },
  } as MapDetail;

  render(
    <I18nProvider>
      <LineupCard match={partialDraft} />
    </I18nProvider>,
  );

  expect(await screen.findByText("英雄未确定")).toBeInTheDocument();
  expect(screen.queryByText("近期数据不可用")).not.toBeInTheDocument();
});

test("a picked hero with a missing label is not shown as unpicked", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(recentResponse(null)),
  );
  const missingLabel = {
    ...match,
    draft: {
      observed_at: "2026-08-15T01:00:00Z",
      slots: [
        {
          side: "radiant",
          position: 2,
          canonical_player_id: "player-1",
          player_name: "lorenof",
          hero_id: 35,
          hero_name: null,
        },
      ],
    },
  } as MapDetail;

  render(
    <I18nProvider>
      <LineupCard match={missingLabel} />
    </I18nProvider>,
  );

  expect(await screen.findByText("英雄 #35")).toBeInTheDocument();
  expect(screen.queryByText("英雄尚未选择")).not.toBeInTheDocument();
});

test("refetches hero recent data when the draft completes on a live match", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(recentResponse(null))
      .mockResolvedValueOnce(
        recentResponse({
          maps: 10,
          wins: 7,
          losses: 3,
          win_rate: 0.7,
          knowledge_cutoff: "2026-08-14T00:00:00Z",
          last_included_match_id: "match-10",
        }),
      ),
  );
  const beforePick = {
    ...match,
    draft: {
      observed_at: "2026-08-15T01:00:00Z",
      slots: [
        {
          side: "radiant",
          position: 1,
          canonical_player_id: "player-1",
          player_name: "watson",
          hero_id: null,
          hero_name: null,
        },
      ],
    },
  } as MapDetail;
  const afterPick = {
    ...match,
    draft: {
      observed_at: "2026-08-15T01:05:00Z",
      slots: [
        {
          side: "radiant",
          position: 1,
          canonical_player_id: "player-1",
          player_name: "watson",
          hero_id: 36,
          hero_name: "Necrophos",
        },
      ],
    },
  } as MapDetail;

  const view = render(
    <I18nProvider>
      <LineupCard match={beforePick} />
    </I18nProvider>,
  );

  expect(await screen.findByText("英雄未确定")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1);

  view.rerender(
    <I18nProvider>
      <LineupCard match={afterPick} />
    </I18nProvider>,
  );

  expect(await screen.findByText("近10场 70% · 7–3")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(2);
});
