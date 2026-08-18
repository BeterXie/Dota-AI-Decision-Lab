from datetime import UTC, datetime

from app.providers.liquipedia.parser import parse_series, parse_tournaments


TOURNAMENTS_HTML = """
<ul class="tournaments-list">
  <li class="tournaments-list-type">
    <span class="tournaments-list-heading">Upcoming</span>
    <ul class="tournaments-list-type-list">
      <li>
        <div class="tournament-badge"><div class="tournament-badge__text">Tier 1</div></div>
        <span class="tournaments-list-name">
          <a href="/dota2/The_International/2026">The International 2026</a>
        </span>
        <small class="tournaments-list-dates">Aug 13 - 23, 2026</small>
      </li>
    </ul>
  </li>
  <li class="tournaments-list-type">
    <span class="tournaments-list-heading">Ongoing</span>
    <ul class="tournaments-list-type-list">
      <li>
        <div class="tournament-badge"><div class="tournament-badge__text">Tier 1</div></div>
        <span class="tournaments-list-name">
          <a href="/dota2/PGL/Wallachia/9">PGL Wallachia Season 9</a>
        </span>
        <small class="tournaments-list-dates">Aug 15 - 24, 2026</small>
      </li>
    </ul>
  </li>
  <li class="tournaments-list-type">
    <span class="tournaments-list-heading">Concluded</span>
    <ul class="tournaments-list-type-list">
      <li>
        <span class="tournaments-list-name">
          <a href="/dota2/DreamLeague/Season_28">DreamLeague Season 28</a>
        </span>
      </li>
    </ul>
  </li>
</ul>
"""


MATCHES_HTML = """
<table class="wikitable wikitable-striped infobox_matches_content">
  <tr>
    <td class="team-left"><a href="/dota2/Team_Liquid">Team Liquid</a></td>
    <td class="versus">vs. <span>(Bo3)</span></td>
    <td class="team-right"><a href="/dota2/Team_Spirit">Team Spirit</a></td>
  </tr>
  <tr>
    <td class="match-filler" colspan="3">
      <span class="match-countdown" data-timestamp="1787054400">12:00</span>
      <a href="/dota2/The_International/2026">The International 2026</a>
      - Group Stage
    </td>
  </tr>
</table>
<table class="wikitable wikitable-striped infobox_matches_content">
  <tr>
    <td class="team-left"><a href="/dota2/Tundra_Esports">Tundra Esports</a></td>
    <td class="versus">2 - 0 <span>(Bo3)</span></td>
    <td class="team-right"><a href="/dota2/BetBoom_Team">BetBoom Team</a></td>
  </tr>
  <tr>
    <td class="match-filler" colspan="3">
      <time datetime="2026-08-17T18:00:00Z">18:00</time>
      <a href="/dota2/DreamLeague/Season_28">DreamLeague Season 28</a>
      - Playoffs
    </td>
  </tr>
</table>
"""


def test_parse_tournaments_preserves_phase_page_tier_and_date_label() -> None:
    observations = parse_tournaments(TOURNAMENTS_HTML)

    assert [item.phase for item in observations] == ["UPCOMING", "ONGOING", "COMPLETED"]
    assert observations[0].page_name == "The International/2026"
    assert observations[0].name == "The International 2026"
    assert observations[0].tier == "Tier 1"
    assert observations[0].date_label == "Aug 13 - 23, 2026"
    assert observations[1].page_name == "PGL/Wallachia/9"
    assert observations[2].page_name == "DreamLeague/Season 28"


def test_parse_series_extracts_teams_event_best_of_time_and_state() -> None:
    observations = parse_series(MATCHES_HTML)

    assert len(observations) == 2
    upcoming = observations[0]
    assert upcoming.team_a_name == "Team Liquid"
    assert upcoming.team_a_page == "Team Liquid"
    assert upcoming.team_b_name == "Team Spirit"
    assert upcoming.tournament_page == "The International/2026"
    assert upcoming.stage == "12:00 - Group Stage"
    assert upcoming.best_of == 3
    assert upcoming.scheduled_at == datetime.fromtimestamp(1787054400, tz=UTC)
    assert upcoming.state == "UPCOMING"
    assert len(upcoming.provider_key) == 24

    completed = observations[1]
    assert completed.tournament_name == "DreamLeague Season 28"
    assert completed.stage == "18:00 - Playoffs"
    assert completed.scheduled_at == datetime(2026, 8, 17, 18, 0, tzinfo=UTC)
    assert completed.state == "COMPLETED"


def test_parse_series_is_deterministic_for_the_same_page() -> None:
    first = parse_series(MATCHES_HTML)
    second = parse_series(MATCHES_HTML)

    assert [item.provider_key for item in first] == [item.provider_key for item in second]
