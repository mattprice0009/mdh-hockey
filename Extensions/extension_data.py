"""Load extension announcement data from Microsoft Graph and Fantrax."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import quote

import requests

from extension_announcement import (
    AnnouncementError,
    ClaimBid,
    DEFAULT_SHEET,
    normalized_name,
    parse_money,
)

TRANSACTION_LIMIT = 250
POSTED_GROUP_CELL = "AB8"
POSTED_GROUP_ROW = 7
POSTED_GROUP_COLUMN = 27

def infer_next_group(values: list[list[Any]]) -> int:
    """Return one more than the group recorded in worksheet cell AB8."""
    try:
        posted_group = int(values[POSTED_GROUP_ROW][POSTED_GROUP_COLUMN])
    except (IndexError, TypeError, ValueError) as exc:
        raise AnnouncementError(
            "Could not infer --group because worksheet cell AB8 does not "
            "contain a valid group number."
        ) from exc
    next_group = posted_group + 1
    if next_group < 1:
        raise AnnouncementError(
            "Could not infer --group because worksheet cell AB8 contains "
            f"an invalid group number: {posted_group}."
        )
    return next_group

def fetch_sheet_values(sheet_name: str) -> list[list[Any]]:
    from mdhhockey.helpers import CAPFRIENDLY_GRAPH_URL_ROOT, _acquire_azure_token

    token_result = _acquire_azure_token()
    token = token_result.get("access_token")
    if not token:
        detail = token_result.get("error_description", "no access token returned")
        raise AnnouncementError(f"Microsoft authentication failed: {detail}")

    encoded_sheet = quote(sheet_name, safe="")
    url = (
        f"{CAPFRIENDLY_GRAPH_URL_ROOT}/worksheets/{encoded_sheet}"
        "/usedRange(valuesOnly=true)"
    )
    response = requests.get(
        url, headers={"Authorization": f"Bearer {token}"}, timeout=30
    )
    response.raise_for_status()
    values = response.json().get("values")
    if not isinstance(values, list):
        raise AnnouncementError(f"No values returned from worksheet {sheet_name!r}.")
    return values

def update_posted_group(group: int) -> None:
    """Record the most recently posted extension group in the workbook."""
    from mdhhockey.helpers import CAPFRIENDLY_GRAPH_URL_ROOT, _acquire_azure_token

    token_result = _acquire_azure_token()
    token = token_result.get("access_token")
    if not token:
        detail = token_result.get("error_description", "no access token returned")
        raise AnnouncementError(f"Microsoft authentication failed: {detail}")

    encoded_sheet = quote(DEFAULT_SHEET, safe="")
    url = (
        f"{CAPFRIENDLY_GRAPH_URL_ROOT}/worksheets/{encoded_sheet}"
        f"/range(address='{POSTED_GROUP_CELL}')"
    )
    response = requests.patch(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"values": [[group]]},
        timeout=30,
    )
    response.raise_for_status()

def fetch_recent_claims(limit: int = TRANSACTION_LIMIT) -> dict[str, list[ClaimBid]]:
    from mdhhockey.helpers import (
        FANTRAX_LEAGUE_ID,
        FANTRAX_LEAGUE_URL,
        FANTRAX_LOGIN_COOKIE,
        FANTRAX_TEAM_MAP,
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
        timeout=30,
    )
    response.raise_for_status()

    try:
        rows = response.json()["responses"][0]["data"]["table"]["rows"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AnnouncementError(
            "Fantrax returned an unexpected transaction response."
        ) from exc

    claims: dict[str, list[ClaimBid]] = {}
    for row in rows:
        if row.get("transactionCode") != "CLAIM" or row.get("deleted"):
            continue
        player_name = row.get("scorer", {}).get("name")
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
