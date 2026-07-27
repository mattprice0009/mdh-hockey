#!/usr/bin/env python3
"""Update Fantrax contracts from the Extensions Research worksheet.

Running without --apply performs a read-only preview. Selected worksheet
players not found in Fantrax's Player Pool are reported and skipped.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from html.parser import HTMLParser
from typing import Iterable

import requests

from extension_announcement import DEFAULT_SHEET, Player, parse_player_row
from extension_data import fetch_sheet_values
from mdhhockey.helpers import (
    FANTRAX_LEAGUE_ID,
    FANTRAX_LOGIN_COOKIE,
)

FANTRAX_ADMIN_URL = (
    "https://www.fantrax.com/newui/fantasy/salaryContractAdmin.go"
)
FANTRAX_SAVE_URL = "https://www.fantrax.com/fxa/saveSalariesAndContracts"
FANTRAX_PLAYER_POOL = "~POOL_"
ROSTER_LIMIT_PERIOD = 1
REQUEST_TIMEOUT = 30

class ContractUpdateError(RuntimeError):
    """A safe contract update could not be prepared or completed."""

@dataclass(frozen=True)
class FantraxPlayer:
    scorer_id: str
    name: str

@dataclass(frozen=True)
class ContractUpdate:
    worksheet_player: Player
    fantrax_player: FantraxPlayer
    team_id: str
    salary: int
    contract_id: str
    contract_label: str

@dataclass(frozen=True)
class SkippedPlayer:
    worksheet_player: Player
    reason: str

class PlayerTableParser(HTMLParser):
    """Extract player IDs and names from Fantrax's contract-admin table."""

    PLAYER_LINK_PATTERN = re.compile(
        r"showPlayerProfileNew\(\s*['\"]([^'\"]+)['\"]"
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.players: list[FantraxPlayer] = []
        self._scorer_id: str | None = None
        self._name_parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag != "a":
            return
        onclick = dict(attrs).get("onclick") or ""
        match = self.PLAYER_LINK_PATTERN.search(onclick)
        if match:
            self._scorer_id = match.group(1)
            self._name_parts = []

    def handle_data(self, data: str) -> None:
        if self._scorer_id is not None:
            self._name_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._scorer_id is None:
            return
        name = html.unescape("".join(self._name_parts)).strip()
        if name:
            self.players.append(FantraxPlayer(self._scorer_id, name))
        self._scorer_id = None
        self._name_parts = []

def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sheet",
        default=DEFAULT_SHEET,
        help=f"worksheet to read (default: {DEFAULT_SHEET!r})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="submit the displayed updates to Fantrax",
    )
    parser.add_argument(
        "--players",
        nargs="+",
        metavar="NAME",
        help=(
            "only process these player names (for example: "
            '--players "Connor McDavid" "Nathan MacKinnon")'
        ),
    )
    return parser.parse_args(argv)

def normalized_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "", ascii_value.casefold())

def worksheet_players(values: list[list[object]]) -> list[Player]:
    players: list[Player] = []
    for row in values[1:]:
        if len(row) < 4:
            continue
        try:
            int(row[0])
        except (TypeError, ValueError):
            continue
        players.append(parse_player_row(row))
    if not players:
        raise ContractUpdateError(
            "No extension players were found in the worksheet."
        )
    return players

def select_players(
    players: list[Player], requested_names: Iterable[str] | None
) -> list[Player]:
    if requested_names is None:
        return players

    requested = {
        normalized_name(name): name
        for name in requested_names
    }
    selected = [
        player
        for player in players
        if normalized_name(player.name) in requested
    ]
    found = {normalized_name(player.name) for player in selected}
    missing = [
        original_name
        for normalized, original_name in requested.items()
        if normalized not in found
    ]
    if missing:
        raise ContractUpdateError(
            "Requested player(s) not found in the worksheet: "
            + ", ".join(repr(name) for name in missing)
        )
    return selected

def fantrax_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Cookie": FANTRAX_LOGIN_COOKIE})
    return session

def fetch_admin_page(
    session: requests.Session,
    team_id_or_pool: str,
    start_index: int | str = "",
) -> str:
    response = session.get(
        FANTRAX_ADMIN_URL,
        params={
            "leagueId": FANTRAX_LEAGUE_ID,
            "sortOrder": "NAME",
            "startIndex": start_index,
            "teamIdOrPool": team_id_or_pool,
            "period": ROSTER_LIMIT_PERIOD,
            "position": "ALL",
            "applyToFuturePeriods": "true",
            "_applyToFuturePeriods": "false",
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    if "saveSalariesAndContracts" not in response.text:
        raise ContractUpdateError(
            "Fantrax did not return the commissioner contract-admin page. "
            "The configured login cookie may be expired."
        )
    return response.text

def parse_fantrax_players(page: str) -> list[FantraxPlayer]:
    parser = PlayerTableParser()
    parser.feed(page)
    unique_players = {
        player.scorer_id: player for player in parser.players
    }
    return list(unique_players.values())

def parse_page_start_indices(page: str) -> list[int]:
    return sorted({
        int(start_index)
        for start_index in re.findall(
            r"__paginate\(\s*(\d+)\s*\)", page
        )
    })

def fetch_player_pool(
    session: requests.Session,
) -> tuple[list[FantraxPlayer], str]:
    first_page = fetch_admin_page(session, FANTRAX_PLAYER_POOL)
    pages = [first_page]
    for start_index in parse_page_start_indices(first_page):
        if start_index == 0:
            continue
        pages.append(
            fetch_admin_page(
                session,
                FANTRAX_PLAYER_POOL,
                start_index,
            )
        )

    players_by_id: dict[str, FantraxPlayer] = {}
    for page in pages:
        for player in parse_fantrax_players(page):
            players_by_id[player.scorer_id] = player
    return list(players_by_id.values()), first_page

def parse_contract_options(page: str) -> dict[int, tuple[str, str]]:
    option_pattern = re.compile(
        r"<option\s+value=['\"]([^'\"]+)['\"][^>]*>"
        r"\s*7/(\d{4})\s*</option>",
        re.IGNORECASE,
    )
    options = [
        (contract_id, int(year))
        for contract_id, year in option_pattern.findall(page)
    ]
    if not options:
        raise ContractUpdateError(
            "Could not read Fantrax's contract expiration options."
        )
    first_year = min(year for _, year in options)
    by_term = {
        year - first_year + 1: (contract_id, f"7/{year}")
        for contract_id, year in options
    }
    stream_match = re.search(
        r"<option\s+value=['\"]([^'\"]+)['\"][^>]*>"
        r"\s*Stream\s*</option>",
        page,
        re.IGNORECASE,
    )
    if not stream_match:
        raise ContractUpdateError(
            "Could not read Fantrax's Stream contract option."
        )
    by_term[1] = (stream_match.group(1), "Stream")
    expected_terms = set(range(1, 8))
    if not expected_terms.issubset(by_term):
        raise ContractUpdateError(
            "Fantrax did not provide expiration choices for every 1–7 year "
            "extension term."
        )
    return by_term

def match_player(
    worksheet_name: str, candidates: list[FantraxPlayer]
) -> FantraxPlayer:
    wanted = normalized_name(worksheet_name)
    exact = [
        candidate
        for candidate in candidates
        if normalized_name(candidate.name) == wanted
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ContractUpdateError(
            f"multiple exact matches in --Player Pool-- for {worksheet_name!r}"
        )
    raise ContractUpdateError("not found in --Player Pool--")

def rounded_salary(value: Decimal) -> int:
    salary = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if salary < 0:
        raise ContractUpdateError(f"Salary cannot be negative: {value}.")
    return salary

def build_updates(
    session: requests.Session, players: list[Player]
) -> tuple[list[ContractUpdate], list[SkippedPlayer]]:
    player_pool, first_page = fetch_player_pool(session)
    if not player_pool:
        raise ContractUpdateError(
            "No players were found under --Player Pool-- in Fantrax."
        )
    contract_options = parse_contract_options(first_page)

    updates: list[ContractUpdate] = []
    skipped: list[SkippedPlayer] = []
    used_scorer_ids: set[str] = set()
    for player in players:
        if player.years not in contract_options:
            raise ContractUpdateError(
                f"{player.name!r} has unsupported term {player.years}."
            )
        try:
            fantrax_player = match_player(player.name, player_pool)
        except ContractUpdateError as exc:
            skipped.append(SkippedPlayer(player, str(exc)))
            continue
        if fantrax_player.scorer_id in used_scorer_ids:
            raise ContractUpdateError(
                f"Fantrax player {fantrax_player.name!r} matched more than once."
            )
        used_scorer_ids.add(fantrax_player.scorer_id)
        contract_id, contract_label = contract_options[player.years]
        updates.append(
            ContractUpdate(
                worksheet_player=player,
                fantrax_player=fantrax_player,
                team_id=FANTRAX_PLAYER_POOL,
                salary=rounded_salary(player.minimum_bid),
                contract_id=contract_id,
                contract_label=contract_label,
            )
        )
    return updates, skipped

def print_preview(
    updates: list[ContractUpdate], skipped: list[SkippedPlayer]
) -> None:
    for update in updates:
        player = update.worksheet_player
        print(
            f"{player.owner:7} {player.name}: "
            f"${update.salary:,}, {update.contract_label}"
        )
    for skipped_player in skipped:
        player = skipped_player.worksheet_player
        print(
            f"Skipped {player.owner:7} {player.name}: "
            f"{skipped_player.reason}"
        )
    print(
        f"\nPrepared {len(updates)} contract updates; "
        f"skipped {len(skipped)} player(s)."
    )

def save_updates(
    session: requests.Session, updates: list[ContractUpdate]
) -> None:
    by_team: dict[str, list[ContractUpdate]] = {}
    for update in updates:
        by_team.setdefault(update.team_id, []).append(update)

    completed = 0
    for team_id, team_updates in by_team.items():
        payload = {
            "salaryMap": {
                update.fantrax_player.scorer_id: str(update.salary)
                for update in team_updates
            },
            "contractMap": {
                update.fantrax_player.scorer_id: update.contract_id
                for update in team_updates
            },
            "teamIdOrPool": team_id,
            "rosterLimitPeriod": ROSTER_LIMIT_PERIOD,
            "applyToFuturePeriods": True,
        }
        response = session.post(
            FANTRAX_SAVE_URL,
            params={"leagueId": FANTRAX_LEAGUE_ID},
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        result = response.text.strip().strip('"')
        if result != "OK":
            raise ContractUpdateError(
                f"Fantrax rejected an update after {completed} player(s): "
                f"{result or 'empty response'}"
            )
        completed += len(team_updates)
        print(f"Updated {len(team_updates)} player(s) in --Player Pool--.")
    print(f"Successfully updated {completed} Fantrax contracts.")

def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        values = fetch_sheet_values(args.sheet)
        players = worksheet_players(values)
        players = select_players(players, args.players)
        with fantrax_session() as session:
            updates, skipped = build_updates(session, players)
            print_preview(updates, skipped)
            if not args.apply:
                print(
                    "Preview only; no Fantrax changes were submitted. "
                    "Run again with --apply to save these updates."
                )
                return 0
            save_updates(session, updates)
    except (
        ContractUpdateError,
        requests.RequestException,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
