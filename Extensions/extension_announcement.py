"""Build MDH salary-keeper extension announcements."""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

DEFAULT_SHEET = "Extensions Research"
DEFAULT_BID_GRID_SHEET = "Bid Grid"
BID_GRID_ROW_LIMIT = 21
BID_GRID_COLUMN_LIMIT = 8

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

@dataclass(frozen=True)
class CompensationTier:
    picks: str
    minimum: Decimal
    maximum: Decimal | None

@dataclass(frozen=True)
class BidGrid:
    tiers: list[CompensationTier]
    availability: dict[str, tuple[str, ...]]

@dataclass(frozen=True)
class BidGridDecision:
    original: CompensationTier
    effective: CompensationTier
    status: str

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

def parse_compensation_amount(value: Any) -> Decimal | None:
    text = str(value).strip().upper().replace(",", "")
    if text == "MAX":
        return None
    match = re.fullmatch(
        r"\$?(\d+(?:\.\d+)?)\s*([KM])?(?:\s*\+\s*(\d+))?",
        text,
    )
    if not match:
        raise AnnouncementError(f"Invalid Bid Grid amount: {value!r}")
    amount = Decimal(match.group(1))
    multiplier = {
        None: Decimal("1"),
        "K": Decimal("1000"),
        "M": Decimal("1000000"),
    }[match.group(2)]
    increment = Decimal(match.group(3) or "0")
    return amount * multiplier + increment

def parse_compensation_tiers(values: list[list[Any]]) -> list[CompensationTier]:
    if len(values) < 3:
        raise AnnouncementError("Bid Grid must contain Picks, Min $, and Max $ rows.")
    tiers: list[CompensationTier] = []
    width = max(len(row) for row in values[:3])
    for column in range(1, width):
        picks = str(values[0][column]).strip() if column < len(values[0]) else ""
        if not picks:
            continue
        minimum_value = values[1][column] if column < len(values[1]) else ""
        maximum_value = values[2][column] if column < len(values[2]) else ""
        minimum = parse_compensation_amount(minimum_value)
        maximum = parse_compensation_amount(maximum_value)
        if minimum is None:
            raise AnnouncementError(
                f"Bid Grid minimum cannot be MAX for {picks!r}."
            )
        if maximum is not None and maximum < minimum:
            raise AnnouncementError(
                f"Bid Grid maximum is below minimum for {picks!r}."
            )
        tiers.append(CompensationTier(picks, minimum, maximum))
    if not tiers:
        raise AnnouncementError("No compensation tiers were found in Bid Grid.")
    return tiers

def parse_bid_grid(values: list[list[Any]]) -> BidGrid:
    """Parse compensation tiers and manager availability from A1:H21."""
    grid_values = [
        row[:BID_GRID_COLUMN_LIMIT]
        for row in values[:BID_GRID_ROW_LIMIT]
    ]
    tiers = parse_compensation_tiers(grid_values)
    availability: dict[str, tuple[str, ...]] = {}
    valid_statuses = {"yes", "no", "upgrade"}
    for row in grid_values[3:]:
        owner = str(row[0]).strip() if row else ""
        if not owner:
            continue
        statuses = tuple(
            str(row[column]).strip().casefold()
            if column < len(row)
            else ""
            for column in range(1, len(tiers) + 1)
        )
        invalid = [
            status
            for status in statuses
            if status and status not in valid_statuses
        ]
        if invalid:
            raise AnnouncementError(
                f"Invalid Bid Grid status for {owner!r}: {invalid[0]!r}."
            )
        availability[normalized_name(owner)] = statuses
    return BidGrid(tiers, availability)

def compensation_for_salary(
    salary: Decimal, tiers: list[CompensationTier]
) -> str:
    for tier in tiers:
        if salary >= tier.minimum and (
            tier.maximum is None or salary <= tier.maximum
        ):
            return tier.picks
    raise AnnouncementError(
        f"No Bid Grid compensation tier contains {format_money(salary)}."
    )

def bid_grid_decision(
    salary: Decimal, owner: str, bid_grid: BidGrid
) -> BidGridDecision:
    tier_index = next(
        (
            index
            for index, tier in enumerate(bid_grid.tiers)
            if salary >= tier.minimum
            and (tier.maximum is None or salary <= tier.maximum)
        ),
        None,
    )
    if tier_index is None:
        raise AnnouncementError(
            f"No Bid Grid compensation tier contains {format_money(salary)}."
        )

    original = bid_grid.tiers[tier_index]
    if not bid_grid.availability or not owner:
        return BidGridDecision(original, original, "yes")

    statuses = bid_grid.availability.get(normalized_name(owner))
    if statuses is None:
        raise AnnouncementError(
            f"Bid Grid does not contain a manager row for {owner!r}."
        )
    status = statuses[tier_index]
    if status == "yes":
        return BidGridDecision(original, original, status)
    if status == "no":
        return BidGridDecision(original, original, status)
    if status != "upgrade":
        raise AnnouncementError(
            f"Bid Grid status is blank for {owner!r} and {original.picks!r}."
        )

    for upgraded_index in range(tier_index - 1, -1, -1):
        if statuses[upgraded_index] == "yes":
            return BidGridDecision(
                original,
                bid_grid.tiers[upgraded_index],
                status,
            )
    raise AnnouncementError(
        f"Bid Grid says to upgrade {owner!r} from {original.picks!r}, "
        "but no higher compensation tier is marked Yes."
    )

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
    player: Player,
    claims: dict[str, Decimal | list[ClaimBid]],
    bid_grid: BidGrid,
) -> str:
    bids = claim_bids(player, claims)
    claim_salary = max((bid.salary for bid in bids), default=None)
    suffix = "" if claim_salary is not None else " (No bids, auto-matched)"
    salary = player.minimum_bid if claim_salary is None else claim_salary
    if player.is_rfa and claim_salary is not None:
        winning_owners = list(
            dict.fromkeys(
                bid.owner
                for bid in bids
                if bid.salary == claim_salary and bid.owner
            )
        )
        compensation = compensation_for_salary(salary, bid_grid.tiers)
        if len(winning_owners) == 1:
            compensation = bid_grid_decision(
                salary, winning_owners[0], bid_grid
            ).effective.picks
        suffix = f" ({compensation})"
    return (
        f"{format_owner(player.owner)} on {format_years(player.years)} of "
        f"{player.display_name} at {format_money(salary)}{suffix}"
    )

def bid_grid_alerts(
    player: Player,
    claims: dict[str, Decimal | list[ClaimBid]],
    bid_grid: BidGrid,
) -> list[str]:
    if not player.is_rfa or not bid_grid.availability:
        return []

    alerts: list[str] = []
    bids = claim_bids(player, claims)
    highest_salary = max((bid.salary for bid in bids), default=None)
    for bid in bids:
        if bid.salary != highest_salary:
            continue
        if not bid.owner:
            continue
        decision = bid_grid_decision(bid.salary, bid.owner, bid_grid)
        bidder = format_owner(bid.owner)
        bid_description = (
            f"{bidder}'s {format_money(bid.salary)} bid on {player.name}"
        )
        if decision.status == "no":
            alerts.append(
                f"⚠️ {bid_description} requires "
                f"{decision.original.picks} compensation, but their entry is No."
            )
        elif decision.status == "upgrade":
            alerts.append(
                f"⚠️ {bid_description} upgrades compensation from "
                f"{decision.original.picks} to {decision.effective.picks} "
                "(the next Yes)."
            )
    return alerts

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
        f"\n🚨 We have a tie! If {owner} decides to match, it ends there. "
        f"If {owner} does not match, then we will begin the tiebreaker process where "
        f"{bidders} bid again with no salary cap limit. Winner gets {player.name} at "
        f"{format_tie_salary(highest_salary)} and a has a \"Signing Bonus\" cap hit "
        "of the overage."
    )

def build_announcement(
    group: int,
    values: list[list[Any]],
    claims: dict[str, Decimal | list[ClaimBid]],
    bid_grid_values: list[list[Any]] | None = None,
) -> str:
    current_players = players_for_group(values, group)
    previous_players = players_for_group(values, group - 1) if group > 1 else []
    return build_announcement_for_players(
        group,
        current_players,
        previous_players,
        claims,
        bid_grid_values,
    )

def build_announcement_for_players(
    group: int,
    current_players: list[Player],
    previous_players: list[Player],
    claims: dict[str, Decimal | list[ClaimBid]],
    bid_grid_values: list[list[Any]] | None = None,
) -> str:
    """Build an announcement from player groups parsed by the caller."""
    bid_grid = (
        parse_bid_grid(bid_grid_values)
        if bid_grid_values is not None
        else BidGrid([], {})
    )

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
        matching_lines = [
            line
            for player in previous_players
            for line in (
                matching_line(player, claims, bid_grid),
                *bid_grid_alerts(player, claims, bid_grid),
            )
        ]
        lines.extend(
            [
                "",
                "Matching decisions are required from:",
                *matching_lines,
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
