from datetime import UTC, datetime

from app.providers.liquipedia.parser import parse_series, parse_tournaments

TOURNAMENTS_HTML = """
<ul><li>Upcoming
  <ul><li>PGL/Wallachia/9 | PGL Wallachia S9 | startdate=Sep 17 | enddate=Sep 27</li></ul>
</li></ul>
<ul><li>Ongoing
  <ul><li>The_International/2026 | TI 2026 | startdate=Aug 13 | enddate=Aug 23</li></ul>
</li></ul>
<ul><li>Completed
  <ul><li>DreamLeague/Season_28 | DreamLeague Season 28 |
    startdate=Jul 26 | enddate=Aug 12</li></ul>
</li></ul>
"""


MATCHES_HTML = """
<div class="match-info">
  <span class="match-info-countdown">
    <span class="timer-object" data-timestamp="1787054400">12:00</span>
  </span>
  <div class="match-info-header">
    <div class="match-info-header-opponent match-info-header-opponent-left">
      <span class="name"><a href="/dota2/Team_Liquid" title="Team Liquid">Liquid</a></span>
    </div>
    <div class="match-info-header-scoreholder"><span>vs</span><span>(Bo3)</span></div>
    <div class="match-info-header-opponent">
      <span class="name"><a href="/dota2/Team_Spirit" title="Team Spirit">TSpirit</a></span>
    </div>
  </div>
  <div class="match-info-tournament"><span class="match-info-tournament-name">
    <a href="/dota2/The_International/2026/Main_Event#Main_Event">TI 2026 - Main Event</a>
  </span></div>
  <div class="match-page-button">
    <a href="/dota2/index.php?title=Match:ID_TI2026Main_R01-M001&amp;action=edit">Details</a>
  </div>
</div>
<div class="match-info">
  <span class="match-info-countdown"><time datetime="2026-08-17T18:00:00Z">18:00</time></span>
  <div class="match-info-header">
    <div
      class="match-info-header-opponent match-info-header-opponent-left match-info-header-winner"
    >
      <span class="name"><a href="/dota2/Tundra_Esports" title="Tundra Esports">Tundra</a></span>
    </div>
    <div class="match-info-header-scoreholder"><span>2 - 0</span><span>(Bo3)</span></div>
    <div class="match-info-header-opponent match-info-header-loser">
      <span class="name"><a
        href="/dota2/index.php?title=BetBoom_Team&amp;action=edit&amp;redlink=1"
        title="BetBoom Team (page does not exist)"
      >BB</a></span>
    </div>
  </div>
  <div class="match-info-tournament"><span class="match-info-tournament-name">
    <a href="/dota2/DreamLeague/Season_28/Playoffs">DreamLeague Season 28 - Playoffs</a>
  </span></div>
  <div class="match-page-button"><a href="/dota2/Match:DL28-PO-001">Details</a></div>
</div>
"""


def test_parse_tournaments_preserves_phase_page_tier_and_date_label() -> None:
    observations = parse_tournaments(TOURNAMENTS_HTML)

    assert [item.phase for item in observations] == ["UPCOMING", "ONGOING", "COMPLETED"]
    assert observations[0].page_name == "PGL/Wallachia/9"
    assert observations[0].name == "PGL Wallachia S9"
    assert observations[0].tier is None
    assert observations[0].date_label == "Sep 17 - Sep 27"
    assert observations[1].page_name == "The International/2026"
    assert observations[1].name == "The International 2026"
    assert observations[2].page_name == "DreamLeague/Season 28"


def test_parse_series_extracts_teams_event_best_of_time_and_state() -> None:
    observations = parse_series(MATCHES_HTML)

    assert len(observations) == 2
    upcoming = observations[0]
    assert upcoming.team_a_name == "Team Liquid"
    assert upcoming.team_a_page == "Team Liquid"
    assert upcoming.team_b_name == "Team Spirit"
    assert upcoming.tournament_name == "The International 2026"
    assert upcoming.tournament_page == "The International/2026"
    assert upcoming.stage == "Main Event"
    assert upcoming.best_of == 3
    assert upcoming.scheduled_at == datetime.fromtimestamp(1787054400, tz=UTC)
    assert upcoming.state == "UPCOMING"
    assert upcoming.provider_key == "Match:ID_TI2026Main_R01-M001"

    completed = observations[1]
    assert completed.team_a_name == "Tundra Esports"
    assert completed.team_b_name == "BetBoom Team"
    assert completed.team_b_page == "BetBoom Team"
    assert completed.tournament_name == "DreamLeague Season 28"
    assert completed.tournament_page == "DreamLeague/Season 28"
    assert completed.stage == "Playoffs"
    assert completed.scheduled_at == datetime(2026, 8, 17, 18, 0, tzinfo=UTC)
    assert completed.state == "COMPLETED"
    assert completed.provider_key == "Match:DL28-PO-001"


def test_parse_series_is_deterministic_for_the_same_page() -> None:
    first = parse_series(MATCHES_HTML)
    second = parse_series(MATCHES_HTML)

    assert [item.provider_key for item in first] == [item.provider_key for item in second]
