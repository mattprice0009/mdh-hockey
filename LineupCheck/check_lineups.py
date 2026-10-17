#!/usr/bin/env python3
"""Report Fantrax teams that could start more eligible players today."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from owner_tags import format_owner

DEFAULT_TIMEZONE = "America/New_York"
REQUEST_TIMEOUT = 120
RUN_STATE_PATH = Path(__file__).with_name(".lineup_check_state.json")
SCHEDULE_REQUEST_TIMEOUT = 15
ACTIVE_STATUS = "1"
RESERVE_STATUS = "2"
INJURED_RESERVE_STATUS = "3"
MINORS_STATUS = "9"
MINOR_LEAGUES_ICON = "4"
CONFIRMED_STARTER_ICON = "12"
GOALIE_POSITION = "201"
UNAVAILABLE_ICONS = {"1", "2", "6", "7", "30"}
STATUS_NAMES = {
    ACTIVE_STATUS: "active",
    RESERVE_STATUS: "reserve",
    INJURED_RESERVE_STATUS: "injured reserve",
    MINORS_STATUS: "minors",
}
POSITION_NAMES = {
    "201": "G",
    "202": "D",
    "203": "LW",
    "204": "RW",
    "206": "C",
    "207": "F",
    "208": "Skt",
}


class LineupCheckError(RuntimeError):
    """An expected Fantrax value could not be loaded or interpreted."""


@dataclass(frozen=True)
class Player:
    player_id: str
    name: str
    status_id: str
    current_position: str | None
    eligible_positions: frozenset[str]
    eligible_statuses: frozenset[str]
    icon_ids: frozenset[str]
    plays_today: bool

    @property
    def qualifies(self) -> bool:
        return (
            self.plays_today
            and (
                GOALIE_POSITION not in self.eligible_positions
                or CONFIRMED_STARTER_ICON in self.icon_ids
            )
            and MINOR_LEAGUES_ICON not in self.icon_ids
            and not (self.icon_ids & UNAVAILABLE_ICONS)
            and ACTIVE_STATUS in self.eligible_statuses
        )


@dataclass(frozen=True)
class Slot:
    index: int
    position: str | None
    status_id: str = ACTIVE_STATUS


@dataclass(frozen=True)
class TeamRoster:
    team_id: str
    team_name: str
    slots: tuple[Slot, ...]
    players: tuple[Player, ...]
    status_capacities: tuple[tuple[str, int], ...] = ()
    illegal_roster_warning: tuple[str, ...] = ()


@dataclass(frozen=True)
class LineupIssue:
    team_id: str
    team_name: str
    current_count: int
    possible_count: int
    additions: tuple[tuple[Player, str], ...]
    moves: tuple[tuple[Player, str, str], ...]
    status_moves: tuple[tuple[Player, str, str], ...]


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=f"Fantrax lineup timezone (default: {DEFAULT_TIMEZONE})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=REQUEST_TIMEOUT,
        help=f"request timeout in seconds (default: {REQUEST_TIMEOUT})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="run now without waiting for the first-game schedule window",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    try:
        ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError:
        parser.error(f"unknown timezone: {args.timezone}")
    return args


def _fantrax_settings() -> tuple[str, str, str, dict[str, str]]:
    try:
        from helpers import (
            FANTRAX_LEAGUE_ID,
            FANTRAX_LEAGUE_URL,
            FANTRAX_LOGIN_COOKIE,
            FANTRAX_TEAM_MAP,
        )
    except (ImportError, KeyError) as exc:
        raise LineupCheckError(
            "Could not load Fantrax settings. Install the project requirements "
            "and configure config.cfg."
        ) from exc
    return (
        FANTRAX_LEAGUE_ID,
        FANTRAX_LEAGUE_URL,
        FANTRAX_LOGIN_COOKIE,
        FANTRAX_TEAM_MAP,
    )


def _load_run_state() -> dict[str, str]:
    if not RUN_STATE_PATH.exists():
        return {}
    try:
        state = json.loads(RUN_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LineupCheckError(f"Could not read lineup check state: {exc}") from exc
    if not isinstance(state, dict):
        raise LineupCheckError("Lineup check state has an unexpected format.")
    return {key: str(value) for key, value in state.items()}


def _save_run_state(state: dict[str, str]) -> None:
    temporary_path = RUN_STATE_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(state), encoding="utf-8")
    temporary_path.replace(RUN_STATE_PATH)


def fetch_first_game_start(
    day: date, timezone_name: str, timeout: float
) -> datetime | None:
    """Fetch today's earliest NHL game using the league-wide schedule feed."""
    from helpers import NHL_API_BASE_URL

    response = requests.get(
        f"{NHL_API_BASE_URL.rstrip('/')}/schedule/{day.isoformat()}",
        timeout=min(timeout, SCHEDULE_REQUEST_TIMEOUT),
    )
    response.raise_for_status()
    try:
        game_week = response.json()["gameWeek"]
    except (KeyError, TypeError, ValueError) as exc:
        raise LineupCheckError("NHL schedule returned an unexpected response.") from exc
    if not isinstance(game_week, list):
        raise LineupCheckError("NHL schedule returned an invalid game week.")

    starts = []
    for schedule_day in game_week:
        if not isinstance(schedule_day, dict):
            continue
        if schedule_day.get("date") != day.isoformat():
            continue
        games = schedule_day.get("games", [])
        if not isinstance(games, list):
            continue
        for game in games:
            if not isinstance(game, dict):
                continue
            start_time = game.get("startTimeUTC")
            if not start_time:
                continue
            try:
                starts.append(datetime.fromisoformat(start_time.replace("Z", "+00:00")))
            except (AttributeError, ValueError) as exc:
                raise LineupCheckError(
                    f"NHL schedule returned an invalid game time: {start_time!r}."
                ) from exc
    if not starts:
        return None
    return min(starts).astimezone(ZoneInfo(timezone_name))


def lineup_check_is_due(timezone_name: str, timeout: float) -> bool:
    now = datetime.now(ZoneInfo(timezone_name))
    state = _load_run_state()
    today = now.date().isoformat()
    if state.get("last_run_date") == today:
        return False

    first_game = fetch_first_game_start(now.date(), timezone_name, timeout)
    if first_game is None:
        if state.get("no_games_logged_date") != today:
            print(f"No NHL games found for {today}; lineup check will retry.")
            state["no_games_logged_date"] = today
            _save_run_state(state)
        return False

    return first_game - timedelta(hours=1) <= now < first_game


def fetch_roster_responses(
    timezone: str, timeout: float
) -> list[tuple[str, dict[str, Any]]]:
    """Fetch every team roster for Fantrax's current lineup day."""
    league_id, url, cookie, team_map = _fantrax_settings()
    messages = [
        {
            "method": "getTeamRosterInfo",
            "data": {
                "leagueId": league_id,
                "reload": "1",
                "period": "",
                "teamId": team_id,
            },
        }
        for team_id in team_map
    ]
    payload = {
        "msgs": messages,
        "uiv": 3,
        "refUrl": (
            f"https://www.fantrax.com/fantasy/league/{league_id}"
            "/team/roster;reload=1"
        ),
        "dt": 0,
        "at": 0,
        "av": "0.0",
        "tz": timezone,
    }
    response = requests.post(
        url,
        headers={"Cookie": cookie},
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    try:
        responses = response.json()["responses"]
    except (KeyError, TypeError, ValueError) as exc:
        raise LineupCheckError("Fantrax returned an unexpected response.") from exc
    if not isinstance(responses, list) or len(responses) != len(messages):
        raise LineupCheckError(
            "Fantrax did not return one roster for every fantasy team."
        )
    results = []
    for team_id, item in zip(team_map, responses):
        if not isinstance(item, dict):
            raise LineupCheckError(f"Fantrax returned an invalid roster for {team_id}.")
        error = item.get("error") or item.get("errors")
        if error:
            raise LineupCheckError(f"Fantrax could not load {team_map[team_id]}: {error}")
        data = item.get("data")
        if not isinstance(data, dict):
            raise LineupCheckError(
                f"Fantrax returned no roster data for {team_map[team_id]}."
            )
        results.append((team_id, data))
    return results


def _opponent_cell_index(table: dict[str, Any]) -> int | None:
    cells = table.get("header", {}).get("cells", [])
    return next(
        (index for index, cell in enumerate(cells) if cell.get("key") == "opponent"),
        None,
    )


def parse_team_roster(
    team_id: str, data: dict[str, Any], fallback_name: str
) -> TeamRoster:
    """Convert a raw Fantrax team response into slots and players."""
    team_name = next(
        (
            team.get("shortName") or team.get("name")
            for team in data.get("fantasyTeams", [])
            if team.get("id") == team_id
        ),
        fallback_name,
    )
    slots = []
    players = []
    for table in data.get("tables", []):
        opponent_index = _opponent_cell_index(table)
        for row in table.get("rows", []):
            status_id = str(row.get("statusId") or "")
            position = row.get("posId")
            if status_id == ACTIVE_STATUS and position:
                slots.append(Slot(len(slots), str(position)))
            scorer = row.get("scorer")
            if not isinstance(scorer, dict) or not scorer.get("name"):
                continue
            cells = row.get("cells", [])
            opponent_cell = (
                cells[opponent_index]
                if opponent_index is not None and opponent_index < len(cells)
                else {}
            )
            players.append(
                Player(
                    player_id=str(scorer.get("scorerId") or ""),
                    name=str(scorer["name"]),
                    status_id=status_id,
                    current_position=str(position) if position else None,
                    eligible_positions=frozenset(
                        str(value)
                        for value in (
                            row.get("eligiblePosIds") or scorer.get("posIds") or []
                        )
                    ),
                    eligible_statuses=frozenset(
                        str(value) for value in row.get("eligibleStatusIds", [])
                    ),
                    icon_ids=frozenset(
                        str(icon.get("typeId"))
                        for icon in scorer.get("icons", [])
                        if icon.get("typeId") is not None
                    ),
                    plays_today=bool(
                        opponent_cell.get("eventId")
                        or str(opponent_cell.get("content") or "").strip()
                    ),
                )
            )
    if not slots:
        raise LineupCheckError(f"Fantrax returned no active slots for {team_name}.")
    misc_data = data.get("miscData", {})
    status_capacities = []
    for status in misc_data.get("statusTotals", []):
        status_id = str(status.get("id") or "")
        maximum = status.get("max")
        if status_id == ACTIVE_STATUS or maximum is None:
            continue
        if str(maximum).casefold() == "unlimited":
            capacity = sum(
                status_id in player.eligible_statuses for player in players
            )
        else:
            try:
                capacity = int(maximum)
            except (TypeError, ValueError) as exc:
                raise LineupCheckError(
                    f"Fantrax returned an invalid {status.get('name')} limit "
                    f"for {team_name}: {maximum!r}."
                ) from exc
        current_count = sum(player.status_id == status_id for player in players)
        if status_id != RESERVE_STATUS:
            capacity = max(capacity, current_count)
        status_capacities.append((status_id, capacity))
    warning_title = misc_data.get("illegalRosterMsgsTitle")
    warning_text = misc_data.get("illegalRosterMsgsText") or []
    illegal_roster_warning = tuple(
        _discord_markup(str(message)).strip()
        for message in ([warning_title] if warning_title else []) + warning_text
        if str(message).strip()
        and not _is_future_period_warning(str(message))
    )
    return TeamRoster(
        team_id,
        str(team_name),
        tuple(slots),
        tuple(players),
        tuple(status_capacities),
        illegal_roster_warning,
    )


def _is_future_period_warning(message: str) -> bool:
    return re.search(r"\bfuture lineup period\b", message, re.IGNORECASE) is not None


def _discord_markup(message: str) -> str:
    """Convert Fantrax HTML emphasis to Discord Markdown."""
    message = re.sub(r"</?\s*(?:b|strong)\s*>", "**", message, flags=re.IGNORECASE)
    return message


def _slot_order(player: Player, slots: tuple[Slot, ...]) -> list[Slot]:
    eligible = [
        slot
        for slot in slots
        if slot.status_id in player.eligible_statuses
        and (
            slot.status_id != ACTIVE_STATUS
            or slot.position in player.eligible_positions
        )
    ]
    return sorted(
        eligible,
        key=lambda slot: (
            slot.status_id != player.status_id,
            slot.position != player.current_position,
            slot.index,
        ),
    )


def _active_assignment(
    players: tuple[Player, ...], slots: tuple[Slot, ...]
) -> dict[int, Player] | None:
    ordered_players = tuple(sorted(
        players,
        key=lambda item: (
            item.status_id != ACTIVE_STATUS,
            len(item.eligible_positions),
            item.name,
        ),
    ))
    states: dict[int, tuple[int, tuple[int, ...]]] = {0: (0, ())}
    for player in ordered_players:
        next_states: dict[int, tuple[int, tuple[int, ...]]] = {}
        for mask, (cost, assigned_slots) in states.items():
            for slot in _slot_order(player, slots):
                bit = 1 << slot.index
                if mask & bit:
                    continue
                move_cost = int(slot.position != player.current_position)
                if player.status_id == ACTIVE_STATUS:
                    move_cost *= 1_000
                candidate = (cost + move_cost, assigned_slots + (slot.index,))
                existing = next_states.get(mask | bit)
                if existing is None or candidate < existing:
                    next_states[mask | bit] = candidate
        states = next_states
        if not states:
            return None
    _, assigned_slots = min(states.values())
    return {
        slot_index: player
        for player, slot_index in zip(ordered_players, assigned_slots)
    }


def _status_assignment(
    roster: TeamRoster, forced_main: frozenset[str]
) -> dict[str, str] | None:
    capacities = dict(roster.status_capacities)
    current_main = sum(
        player.status_id in {ACTIVE_STATUS, RESERVE_STATUS}
        for player in roster.players
    )
    main_capacity = max(
        current_main,
        len(roster.slots) + capacities.get(RESERVE_STATUS, 0),
    )
    status_slots = ["main"] * main_capacity
    for status_id in (INJURED_RESERVE_STATUS, MINORS_STATUS):
        status_slots.extend([status_id] * capacities.get(status_id, 0))
    matches: dict[int, Player] = {}

    def choices(player: Player) -> list[int]:
        allowed = {"main"} if player.player_id in forced_main else set()
        if player.player_id not in forced_main:
            if player.eligible_statuses & {ACTIVE_STATUS, RESERVE_STATUS}:
                allowed.add("main")
            allowed.update(
                status
                for status in (INJURED_RESERVE_STATUS, MINORS_STATUS)
                if status in player.eligible_statuses
            )
        current_group = (
            "main"
            if player.status_id in {ACTIVE_STATUS, RESERVE_STATUS}
            else player.status_id
        )
        return sorted(
            (index for index, status in enumerate(status_slots) if status in allowed),
            key=lambda index: (status_slots[index] != current_group, index),
        )

    def augment(player: Player, visited: set[int]) -> bool:
        for index in choices(player):
            if index in visited:
                continue
            visited.add(index)
            occupant = matches.get(index)
            if occupant is None or augment(occupant, visited):
                matches[index] = player
                return True
        return False

    ordered_players = sorted(
        roster.players,
        key=lambda player: (
            player.player_id not in forced_main,
            len(choices(player)),
            player.name,
        ),
    )
    if not all(augment(player, set()) for player in ordered_players):
        return None
    return {
        player.player_id: status_slots[index]
        for index, player in matches.items()
    }


def optimal_assignment(
    roster: TeamRoster,
) -> tuple[dict[int, Player], dict[str, str]]:
    """Find the no-drop lineup with the most qualifying starters."""
    current = tuple(
        player
        for player in roster.players
        if player.qualifies and player.status_id == ACTIVE_STATUS
    )
    current_ids = frozenset(player.player_id for player in current)
    bench = tuple(
        player
        for player in roster.players
        if player.qualifies and player.player_id not in current_ids
    )
    maximum_additions = min(len(bench), len(roster.slots) - len(current))
    for count in range(maximum_additions, -1, -1):
        for additions in combinations(bench, count):
            selected = current + additions
            active_assignment = _active_assignment(selected, roster.slots)
            if active_assignment is None:
                continue
            selected_ids = frozenset(player.player_id for player in selected)
            status_assignment = _status_assignment(roster, selected_ids)
            if status_assignment is not None:
                return active_assignment, status_assignment
    raise LineupCheckError(
        f"Could not preserve {roster.team_name}'s current qualifying starters."
    )


def find_issue(roster: TeamRoster) -> LineupIssue | None:
    current_players = {
        player.player_id: player
        for player in roster.players
        if player.qualifies and player.status_id == ACTIVE_STATUS
    }
    assignment, roster_statuses = optimal_assignment(roster)
    assigned_positions = {
        player.player_id: roster.slots[index].position
        for index, player in assignment.items()
    }
    possible_count = len(assignment)
    if possible_count <= len(current_players):
        return None
    additions = tuple(
        (player, assigned_positions[player.player_id])
        for player in assignment.values()
        if player.player_id not in current_players
    )
    moves = tuple(
        (player, player.current_position or "?", assigned_positions[player.player_id])
        for player in current_players.values()
        if assigned_positions.get(player.player_id) != player.current_position
    )
    added_ids = {player.player_id for player, _ in additions}
    status_moves = tuple(
        (
            player,
            STATUS_NAMES.get(player.status_id, player.status_id),
            STATUS_NAMES.get(roster_statuses[player.player_id], roster_statuses[player.player_id]),
        )
        for player in roster.players
        if roster_statuses[player.player_id] != "main"
        and roster_statuses[player.player_id] != player.status_id
        and player.player_id not in added_ids
    )
    return LineupIssue(
        team_id=roster.team_id,
        team_name=roster.team_name,
        current_count=len(current_players),
        possible_count=possible_count,
        additions=tuple(sorted(additions, key=lambda item: item[0].name)),
        moves=tuple(sorted(moves, key=lambda item: item[0].name)),
        status_moves=tuple(sorted(status_moves, key=lambda item: item[0].name)),
    )


def position_name(position: str) -> str:
    return POSITION_NAMES.get(position, position)


def format_report(
    issues: list[LineupIssue], team_count: int, timezone: str,
    illegal_rosters: list[TeamRoster] | None = None,
    include_first_game_notice: bool = True,
) -> str:
    from helpers import FANTRAX_TEAM_MAP

    today = datetime.now(ZoneInfo(timezone)).strftime("%A, %B %-d, %Y")
    lines = [f"Lineup check for {today}"]
    if include_first_game_notice:
        lines.insert(0, "First game starts in one hour.")
    illegal_rosters = illegal_rosters or []
    if not issues and not illegal_rosters:
        lines.append(f"All {team_count} teams have set lineups.")
        return "\n".join(lines)
    issues_by_team = {issue.team_id: issue for issue in issues}
    warnings_by_team = {roster.team_id: roster for roster in illegal_rosters}
    team_ids = sorted(
        issues_by_team.keys() | warnings_by_team.keys(),
        key=lambda team_id: (
            issues_by_team.get(team_id, warnings_by_team.get(team_id)).team_name.casefold()
        ),
    )
    for team_id in team_ids:
        issue = issues_by_team.get(team_id)
        warning = warnings_by_team.get(team_id)
        team_name = issue.team_name if issue else warning.team_name
        owner_tag = format_owner(FANTRAX_TEAM_MAP[team_id])
        lines.append(f"\n{owner_tag} ({team_name}):")
        if warning:
            lines.extend(f"  ILLEGAL LINEUP: {message}" for message in warning.illegal_roster_warning)
        if issue:
            for player, position in issue.additions:
                status = STATUS_NAMES.get(player.status_id, f"status {player.status_id}")
                lines.append(
                    f"  START {player.name} ({status}) -> {position_name(position)}"
                )
            for player, old_position, new_position in issue.moves:
                lines.append(
                    f"  MOVE  {player.name}: {position_name(old_position)} -> "
                    f"{position_name(new_position)}"
                )
            for player, old_status, new_status in issue.status_moves:
                lines.append(f"  MOVE  {player.name}: {old_status} -> {new_status}")
    return "\n".join(lines)


def _post_report(report: str, timeout: float = 30) -> None:
    """Post report lines in Discord-sized messages through the lineup webhook."""
    from discord_webhook import DiscordWebhookError, post_to_discord
    from helpers import LINEUP_DISCORD_WEBHOOK_URL

    if not LINEUP_DISCORD_WEBHOOK_URL.strip():
        raise LineupCheckError(
            "Discord lineup webhook is not configured in config.cfg."
        )
    chunks = []
    current = ""
    for line in report.splitlines():
        if len(line) > 2_000:
            raise LineupCheckError("A lineup report line exceeds Discord's limit.")
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > 2_000:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    try:
        for chunk in chunks:
            post_to_discord(
                chunk, webhook_url=LINEUP_DISCORD_WEBHOOK_URL, timeout=timeout
            )
    except DiscordWebhookError as exc:
        raise LineupCheckError(str(exc)) from exc


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not args.force:
            if not lineup_check_is_due(args.timezone, args.timeout):
                return 0
        _, _, _, team_map = _fantrax_settings()
        raw_rosters = fetch_roster_responses(args.timezone, args.timeout)
        rosters = [
            parse_team_roster(team_id, data, team_map[team_id])
            for team_id, data in raw_rosters
        ]
        issues = [issue for roster in rosters if (issue := find_issue(roster))]
        illegal_rosters = [
            roster
            for roster in rosters
            if roster.illegal_roster_warning
        ]
        report = format_report(
            issues,
            len(rosters),
            args.timezone,
            illegal_rosters,
            include_first_game_notice=not args.force,
        )
        _post_report(report)
        state = _load_run_state()
        state["last_run_date"] = datetime.now(
            ZoneInfo(args.timezone)
        ).date().isoformat()
        _save_run_state(state)
        posted_at = datetime.now(ZoneInfo(args.timezone))
        print(f"{posted_at:%Y-%m-%d} Lineup report posted to Discord.")
    except (LineupCheckError, requests.RequestException) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
