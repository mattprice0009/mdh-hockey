"""Safely inspect and process Fantrax free-agent claims."""

from __future__ import annotations

import re
from typing import Any

import requests

from extension_announcement import (
    AnnouncementError,
    ClaimBid,
    Player,
    normalized_name,
    parse_money,
)

TRANSACTION_LIMIT = 250
ACQUISITION_LABELS = {"ADD", "CLAIM", "CLAIM - FA"}
REQUEST_TIMEOUT = 30

def fantrax_session() -> requests.Session:
    from helpers import FANTRAX_LOGIN_COOKIE

    session = requests.Session()
    session.headers.update({"Cookie": FANTRAX_LOGIN_COOKIE})
    return session

def fetch_transaction_rows(
    limit: int = TRANSACTION_LIMIT,
) -> list[dict[str, Any]]:
    """Load the transaction table once for all claim-related consumers."""
    from helpers import (
        FANTRAX_LEAGUE_ID,
        FANTRAX_LEAGUE_URL,
        FANTRAX_LOGIN_COOKIE,
    )

    payload = {
        "msgs": [
            {
                "method": "getTransactionDetailsHistory",
                "data": {
                    "leagueId": FANTRAX_LEAGUE_ID,
                    "maxResultsPerPage": str(limit),
                    "executedOnly": False,
                    "includeDeleted": False,
                    "view": "CLAIM_DROP",
                    "pageNumber": "1",
                },
            }
        ]
    }
    response = requests.post(
        FANTRAX_LEAGUE_URL,
        headers={"Cookie": FANTRAX_LOGIN_COOKIE},
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    try:
        rows = response.json()["responses"][0]["data"]["table"]["rows"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AnnouncementError(
            "Fantrax returned an unexpected transaction response."
        ) from exc
    if not isinstance(rows, list):
        raise AnnouncementError(
            "Fantrax returned an unexpected transaction response."
        )
    return rows

def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)

def _normalized_transaction_label(value: Any) -> str:
    label = re.sub(r"\s+", " ", str(value or "")).strip().upper()
    return re.sub(r"\s*-\s*", " - ", label)

def _transaction_labels(row: dict[str, Any]) -> set[str]:
    values = [
        row.get("transactionCode"),
        row.get("transactionType"),
        row.get("type"),
        row.get("description"),
    ]
    for cell in row.get("cells", []):
        if cell.get("key") in {
            "transactionCode",
            "transactionType",
            "type",
            "description",
        }:
            values.extend((cell.get("content"), cell.get("value")))
    return {
        label
        for value in values
        if (label := _normalized_transaction_label(value))
    }

def _transaction_player_name(row: dict[str, Any]) -> str | None:
    scorer = row.get("scorer")
    if isinstance(scorer, dict) and scorer.get("name"):
        return str(scorer["name"]).strip()
    for cell in row.get("cells", []):
        if cell.get("key") not in {"player", "scorer"}:
            continue
        content = cell.get("content") or cell.get("value")
        if isinstance(content, dict):
            content = content.get("name")
        if content:
            return str(content).strip()
    return None

def claim_bids_from_transactions(
    rows: list[dict[str, Any]],
) -> dict[str, list[ClaimBid]]:
    """Extract bids without loading transaction history again."""
    from helpers import FANTRAX_TEAM_MAP

    claims: dict[str, list[ClaimBid]] = {}
    for row in rows:
        if row.get("deleted") or "CLAIM" not in _transaction_labels(row):
            continue
        player_name = _transaction_player_name(row)
        cells = {cell.get("key"): cell for cell in row.get("cells", [])}
        bid = cells.get("bid", {}).get("content")
        team_id = cells.get("team", {}).get("teamId")
        owner = FANTRAX_TEAM_MAP.get(team_id)
        if not player_name or bid in (None, "") or owner is None:
            continue
        claim = ClaimBid(salary=parse_money(bid), owner=owner)
        player_claims = claims.setdefault(normalized_name(player_name), [])
        if claim not in player_claims:
            player_claims.append(claim)
    return claims

def executed_acquisition_names(
    rows: list[dict[str, Any]],
) -> dict[str, str]:
    """Return normalized names for executed adds and free-agent claims."""
    names: dict[str, str] = {}
    for row in rows:
        if row.get("deleted") or not _truthy(row.get("executed")):
            continue
        if not (_transaction_labels(row) & ACQUISITION_LABELS):
            continue
        player_name = _transaction_player_name(row)
        if player_name:
            names.setdefault(normalized_name(player_name), player_name)
    return names

def ensure_group_not_processed(
    players: list[Player], rows: list[dict[str, Any]]
) -> None:
    acquisitions = executed_acquisition_names(rows)
    duplicates = [
        player.name
        for player in players
        if normalized_name(player.name) in acquisitions
    ]
    if duplicates:
        raise AnnouncementError(
            "Refusing to process claims because these previous-group players "
            "already have executed add/claim transactions: "
            + ", ".join(duplicates)
            + ". This probably means the claims were already processed."
        )

def _commissioner_action_error(response: requests.Response) -> str | None:
    try:
        result = response.json()
    except (requests.JSONDecodeError, ValueError):
        return "Fantrax returned a non-JSON commissioner action response."
    if not isinstance(result, dict):
        return "Fantrax returned an unexpected commissioner action response."
    responses = result.get("responses")
    if not isinstance(responses, list) or len(responses) != 1:
        return "Fantrax returned an unexpected commissioner action response."
    action_response = responses[0]
    if not isinstance(action_response, dict):
        return "Fantrax returned an unexpected commissioner action response."
    error = action_response.get("error")
    if error:
        if isinstance(error, dict):
            error = error.get("message") or error.get("description") or error
        return str(error)
    data = action_response.get("data")
    if isinstance(data, dict):
        error = data.get("error") or data.get("errorMessage")
        if error:
            return str(error)
        if data.get("success") is False:
            return str(data.get("message") or "Fantrax rejected the action.")
    return None

def process_free_agent_claims(session: requests.Session) -> None:
    """Execute the commissioner free-agent claim action once."""
    from helpers import FANTRAX_LEAGUE_ID, FANTRAX_LEAGUE_URL

    hub_url = (
        "https://www.fantrax.com/fantasy/league/"
        f"{FANTRAX_LEAGUE_ID}/commissioner/hub"
    )
    payload = {
        "msgs": [
            {
                "method": "executeCommissionerHubAction",
                "data": {"actionKey": "processFreeAgentClaims"},
            }
        ],
        "uiv": 3,
        "refUrl": hub_url + "#league-commissioner-hub-action-dialog",
        "dt": 1,
        "at": 0,
        "tz": "America/New_York",
        "v": "184.2.4",
    }
    response = session.post(
        FANTRAX_LEAGUE_URL,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    if error := _commissioner_action_error(response):
        raise AnnouncementError(
            "Fantrax could not process free-agent claims. The configured "
            f"account may not be a commissioner: {error}"
        )
