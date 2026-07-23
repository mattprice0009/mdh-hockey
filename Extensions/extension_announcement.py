"""Build MDH salary-keeper extension announcements."""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

DEFAULT_SHEET = "Extensions Research"

class AnnouncementError(RuntimeError):
    """An expected workbook or Fantrax value could not be read."""

@dataclass(frozen=True)
class Player:
    group: int
    name: str
    owner: str
    position: str
    years: int
    minimum_bid: Decimal
    is_rfa: bool

    @property
    def display_name(self) -> str:
        return f"{self.name}{'*' if self.is_rfa else ''}"

@dataclass(frozen=True)
class ClaimBid:
    salary: Decimal
    owner: str

def normalized_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

def parse_money(value: Any) -> Decimal:
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise AnnouncementError(f"Invalid salary value: {value!r}") from exc

def format_money(value: Decimal) -> str:
    rounded = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"${int(rounded):,}"

def format_years(years: int) -> str:
    return f"{years} {'year' if years == 1 else 'years'}"

owner_map = {
    "2PRO": "<@313547033526927361>",
    "BAR": "<@220731816099840000>",
    "BJS": "<@243201978191052800>",
    "BR0KE": "<@230875413423980545>",
    "CCHT": "<@486366622785994753>",
    "CHZ": "<@229287970186723339>",
    "CTU": "<@484443690610458624>",
    "DADS": "<@447077568403865620>",
    "DWM": "<@228258453599027200>",
    "EXP": "<@282997586020007937>",
    "GetRekt": "<@235638450064326657>",
    "HOGS": "<@785166734318764042>",
    "KINTO": "<@795705765049401364>",
    "SSH": "<@86530833749401600>",
    "SSKL": "<@222830283399888897>",
    "THFM": "<@256358277955321856>",
    "WRINGS": "<@364650172141273089>",
    "WTM": "<@274957566143102976>",
}
def format_owner(owner: str) -> str:
    return owner_map[owner]

def parse_player_row(row: list[Any]) -> Player:
    try:
        group = int(row[0])
        details = next(csv.reader([str(row[1])], skipinitialspace=True))
        owner = str(row[2]).strip()
        minimum_bid = parse_money(row[3])
    except (IndexError, TypeError, ValueError) as exc:
        raise AnnouncementError(f"Invalid extension row: {row!r}") from exc

    if len(details) < 5:
        raise AnnouncementError(f"Could not parse player details: {row[1]!r}")

    term_match = re.search(r"(\d+)\s*year", details[4], re.IGNORECASE)
    if not term_match:
        raise AnnouncementError(f"Could not parse extension term: {details[4]!r}")

    return Player(
        group=group,
        name=details[0].strip(),
        owner=owner,
        position=details[1].strip(),
        years=int(term_match.group(1)),
        minimum_bid=minimum_bid,
        is_rfa="(RFA)" in details[3].upper(),
    )

def players_for_group(values: list[list[Any]], group: int) -> list[Player]:
    players: list[Player] = []
    for row in values[1:]:
        if not row:
            continue
        try:
            row_group = int(row[0])
        except (TypeError, ValueError):
            continue
        if row_group == group:
            players.append(parse_player_row(row))

    if not players:
        raise AnnouncementError(f"Group {group} was not found in {DEFAULT_SHEET!r}.")
    return order_players(values, group, players)

def order_players(
    values: list[list[Any]], group: int, players: list[Player]
) -> list[Player]:
    """Use the sheet's Groups/F1/F2/D/G plan to reproduce its intended order."""
    groups_column = None
    groups_header_row = None
    for row_index, row in enumerate(values):
        for column_index, value in enumerate(row):
            if str(value).strip() == "Groups":
                groups_column = column_index
                groups_header_row = row_index
                break
        if groups_column is not None:
            break

    if groups_column is None or groups_header_row is None:
        return players

    labels: list[str] = []
    for row in values[groups_header_row + 1 :]:
        if len(row) <= groups_column:
            continue
        try:
            planned_group = int(row[groups_column])
        except (TypeError, ValueError):
            continue
        if planned_group == group:
            labels = [
                str(value).strip()
                for value in row[groups_column + 1 : groups_column + 5]
                if str(value).strip()
            ]
            break

    ordered: list[Player] = []
    remaining = list(players)
    for label in labels:
        label_key = normalized_name(label.replace("*", ""))
        label_key = re.sub(r"^[a-z]\s+", "", label_key)
        matches = [
            player
            for player in remaining
            if normalized_name(player.name).endswith(label_key)
        ]
        if len(matches) == 1:
            ordered.append(matches[0])
            remaining.remove(matches[0])

    return ordered + remaining

def player_line(player: Player, salary: Decimal | None = None) -> str:
    salary = player.minimum_bid if salary is None else salary
    return (
        f"{player.display_name} ({player.position}), "
        f"{format_years(player.years)}, {format_money(salary)}"
    )

def claim_bids(
    player: Player, claims: dict[str, Decimal | list[ClaimBid]]
) -> list[ClaimBid]:
    value = claims.get(normalized_name(player.name))
    if isinstance(value, Decimal):
        return [ClaimBid(salary=value, owner="")]
    return [] if value is None else value

def highest_claim(
    player: Player, claims: dict[str, Decimal | list[ClaimBid]]
) -> Decimal | None:
    bids = claim_bids(player, claims)
    return max((bid.salary for bid in bids), default=None)

def matching_line(
    player: Player, claims: dict[str, Decimal | list[ClaimBid]]
) -> str:
    claim_salary = highest_claim(player, claims)
    suffix = "" if claim_salary is not None else " (No bids, auto-matched)"
    salary = player.minimum_bid if claim_salary is None else claim_salary
    return (
        f"{format_owner(player.owner)} on {format_years(player.years)} of "
        f"{player.display_name} at {format_money(salary)}{suffix}"
    )

def join_owners(owners: list[str]) -> str:
    if len(owners) == 2:
        return " and ".join(owners)
    return ", ".join(owners[:-1]) + f", and {owners[-1]}"

def format_tie_salary(value: Decimal) -> str:
    if value >= Decimal("1000000") and value % Decimal("100000") == 0:
        millions = format(value / Decimal("1000000"), "f").rstrip("0").rstrip(".")
        return "$" + f"{millions}M"
    return format_money(value)

def tie_line(
    player: Player, claims: dict[str, Decimal | list[ClaimBid]]
) -> str | None:
    bids = claim_bids(player, claims)
    highest_salary = max((bid.salary for bid in bids), default=None)
    if highest_salary is None:
        return None

    tied_owners = list(
        dict.fromkeys(
            bid.owner
            for bid in bids
            if bid.salary == highest_salary and bid.owner
        )
    )
    if len(tied_owners) < 2:
        return None

    bidders = join_owners([format_owner(owner) for owner in tied_owners])
    owner = format_owner(player.owner)
    return (
        f":siren: We have a tie! If {owner} decides to match, it ends there. "
        f"If {owner} does not match, then we will begin the tiebreaker process where "
        f"{bidders} bid again with no salary cap limit. Winner gets {player.name} at "
        f"{format_tie_salary(highest_salary)} and a has a \"Signing Bonus\" cap hit "
        "of the overage."
    )

def build_announcement(
    group: int, values: list[list[Any]], claims: dict[str, Decimal | list[ClaimBid]]
) -> str:
    current_players = players_for_group(values, group)
    previous_players = players_for_group(values, group - 1) if group > 1 else []

    lines = [
        f"<@&483836819209715763> Group {group}! Each player listed includes their FA status "
        "(RFAs denoted with the * symbol), position, extension term, and minimum bid. "
        "All this info, plus info on upcoming groups, can be found on the CapFriendly "
        "under the Extensions Research tab.",
        "",
        *(player_line(player) for player in current_players),
        "",
        "React with a 👍 once you've wined and dined all players who interest you.",
    ]

    if previous_players:
        lines.extend(
            [
                "",
                "Matching decisions are required from:",
                *(matching_line(player, claims) for player in previous_players),
                *(
                    alert
                    for player in previous_players
                    if (alert := tie_line(player, claims)) is not None
                ),
            ]
        )

    lines.extend(
        [
            "",
            "A team that fails to announce their matching decision in 12 hours will be "
            "ruled to have not matched the bid.",
            "",
            "If any of the owners or bidders need help determining RFA compensation, "
            "please check the Bid Grid tab in the CapFriendly, and if you're still "
            "confused don't hesitate to contact your nearest commissioner. Members are "
            "asked to refrain from voicing their disgust or elation with the highest "
            "bids until the matching decisions have been received.",
        ]
    )
    return "\n".join(lines)
