import unittest
from unittest.mock import patch

from LineupCheck.check_lineups import (
    LineupIssue,
    Player,
    Slot,
    TeamRoster,
    find_issue,
    format_report,
)


def player(
    name,
    status,
    position,
    eligible,
    *,
    playing=True,
    icons=(),
):
    return Player(
        player_id=name,
        name=name,
        status_id=status,
        current_position=position,
        eligible_positions=frozenset(eligible),
        eligible_statuses=frozenset({"1", "2", status}),
        icon_ids=frozenset(icons),
        plays_today=playing,
    )


def roster(players, positions):
    status_counts = {}
    for item in players:
        if item.status_id != "1":
            status_counts[item.status_id] = status_counts.get(item.status_id, 0) + 1
    return TeamRoster(
        team_id="team",
        team_name="Test Team",
        slots=tuple(Slot(index, position) for index, position in enumerate(positions)),
        players=tuple(players),
        status_capacities=tuple(status_counts.items()),
    )


class LineupCheckerTests(unittest.TestCase):
    def test_flags_playing_reserve_when_slot_is_available(self):
        team = roster(
            [
                player("Starter", "1", "206", {"206"}, playing=False),
                player("Reserve", "2", "206", {"206"}),
            ],
            ["206"],
        )

        issue = find_issue(team)

        self.assertIsNotNone(issue)
        self.assertEqual(issue.current_count, 0)
        self.assertEqual(issue.possible_count, 1)
        self.assertEqual([item[0].name for item in issue.additions], ["Reserve"])

    def test_finds_position_shuffle_needed_to_add_player(self):
        team = roster(
            [
                player("Flexible", "1", "206", {"206", "207"}),
                player("Idle", "1", "207", {"207"}, playing=False),
                player("Center", "2", "206", {"206"}),
            ],
            ["206", "207"],
        )

        issue = find_issue(team)

        self.assertIsNotNone(issue)
        self.assertEqual(issue.possible_count, 2)
        self.assertEqual(issue.additions[0][0].name, "Center")
        self.assertEqual(issue.additions[0][1], "206")
        self.assertEqual(issue.moves[0][0].name, "Flexible")
        self.assertEqual(issue.moves[0][1:], ("206", "207"))

    def test_does_not_suggest_unnecessary_position_move(self):
        team = roster(
            [
                player("Current Forward", "1", "207", {"203", "207"}),
                player("Left Wing", "2", "203", {"203", "207"}),
                player("Flexible Addition", "2", "207", {"206", "207", "208"}),
            ],
            ["203", "206", "207"],
        )

        issue = find_issue(team)

        self.assertIsNotNone(issue)
        self.assertEqual(issue.possible_count, 3)
        self.assertEqual(issue.moves, ())

    def test_full_lineup_with_extra_playing_player_is_set(self):
        team = roster(
            [
                player("Center", "1", "206", {"206"}),
                player("Forward", "1", "207", {"207"}),
                player("Extra", "2", "206", {"206", "207"}),
            ],
            ["206", "207"],
        )

        self.assertIsNone(find_issue(team))

    def test_ignores_injured_minors_and_players_without_games(self):
        team = roster(
            [
                player("Idle", "1", "206", {"206"}, playing=False),
                player("Injured", "2", "206", {"206"}, icons={"1"}),
                player("Minor", "2", "206", {"206"}, icons={"4"}),
                player("No Game", "2", "206", {"206"}, playing=False),
            ],
            ["206"],
        )

        self.assertIsNone(find_issue(team))

    def test_only_counts_confirmed_starting_goalie(self):
        team = roster(
            [
                player("Unconfirmed", "1", "201", {"201"}),
                player("Confirmed", "2", "201", {"201"}, icons={"12"}),
            ],
            ["201"],
        )

        issue = find_issue(team)

        self.assertIsNotNone(issue)
        self.assertEqual(issue.current_count, 0)
        self.assertEqual(issue.additions[0][0].name, "Confirmed")

    def test_expected_goalie_is_not_treated_as_confirmed(self):
        team = roster(
            [
                player("Idle", "1", "201", {"201"}, playing=False),
                player("Expected", "2", "201", {"201"}, icons={"32"}),
            ],
            ["201"],
        )

        self.assertIsNone(find_issue(team))

    def test_does_not_flag_activation_that_would_require_drop(self):
        team = TeamRoster(
            team_id="team",
            team_name="Full Team",
            slots=(Slot(0, "206"),),
            players=(
                player("Idle", "1", "206", {"206"}, playing=False),
                player("Prospect", "9", "206", {"206"}),
            ),
            status_capacities=(("2", 0), ("9", 1)),
        )

        self.assertIsNone(find_issue(team))

    def test_flags_activation_when_another_player_can_be_demoted(self):
        demotable = Player(
            player_id="Demotable",
            name="Demotable",
            status_id="1",
            current_position="206",
            eligible_positions=frozenset({"206"}),
            eligible_statuses=frozenset({"1", "2", "9"}),
            icon_ids=frozenset(),
            plays_today=False,
        )
        team = TeamRoster(
            team_id="team",
            team_name="Flexible Team",
            slots=(Slot(0, "206"),),
            players=(demotable, player("Prospect", "9", "206", {"206"})),
            status_capacities=(("2", 0), ("9", 1)),
        )

        issue = find_issue(team)

        self.assertIsNotNone(issue)
        self.assertEqual(issue.additions[0][0].name, "Prospect")
        self.assertEqual(issue.status_moves[0][0].name, "Demotable")
        self.assertEqual(issue.status_moves[0][1:], ("active", "minors"))

    @patch.dict("helpers.FANTRAX_TEAM_MAP", {"team": "BAR"})
    def test_report_omits_qualifying_starter_counts(self):
        reserve = player("Reserve", "2", "206", {"206"})
        issue = LineupIssue(
            team_id="team",
            team_name="Test Team",
            current_count=1,
            possible_count=2,
            additions=((reserve, "206"),),
            moves=(),
            status_moves=(),
        )

        report = format_report([issue], 18, "America/New_York")

        self.assertIn("<@220731816099840000> (Test Team):\n", report)
        self.assertIn("START Reserve (reserve) -> C", report)
        self.assertNotIn("qualifying starter", report)
        self.assertNotIn("can fit", report)


if __name__ == "__main__":
    unittest.main()
