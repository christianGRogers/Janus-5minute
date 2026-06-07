"""
Polymarket loss counter.

Usage:
    PROXY_ADDRESS=0xabc123... python3 get_loss.py

Returns:
    Prints a single integer — the number of losses in the last 3 hours.
    A loss is either a closed position with negative PnL, or an open position
    whose market end time is more than 8 minutes in the past.
"""

import os
import sys
import time
import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import requests


DATA_API = "https://data-api.polymarket.com"

TITLE_TIME_RE = re.compile(
    r"-\s+(\w+ \d+),\s+\d+:\d+[AP]M-(\d+:\d+[AP]M)\s+ET",
    re.IGNORECASE,
)


def parse_market_end_time(title: str, reference_year: int = None) -> Optional[datetime]:
    match = TITLE_TIME_RE.search(title)
    if not match:
        return None
    date_str = match.group(1)
    time_str = match.group(2)
    if reference_year is None:
        reference_year = datetime.now().year
    try:
        naive = datetime.strptime(f"{date_str} {reference_year} {time_str}", "%B %d %Y %I:%M%p")
        edt_offset = timezone(timedelta(hours=-4))
        return naive.replace(tzinfo=edt_offset)
    except ValueError:
        return None


def is_expired(end_time: Optional[datetime], grace_minutes: int = 8) -> bool:
    if end_time is None:
        return False
    return datetime.now(timezone.utc) > end_time + timedelta(minutes=grace_minutes)


def fetch_activity(user: str, activity_type: str, limit: int = 500, start: int = None) -> list[dict]:
    results = []
    offset = 0
    while True:
        params = {
            "user": user,
            "type": activity_type,
            "limit": limit,
            "offset": offset,
            "sortBy": "TIMESTAMP",
            "sortDirection": "ASC",
        }
        if start is not None:
            params["start"] = start
        resp = requests.get(f"{DATA_API}/activity", params=params)
        resp.raise_for_status()
        page = resp.json()
        if not page:
            break
        results.extend(page)
        if len(page) < limit:
            break
        offset += limit
    return results


@dataclass
class Position:
    condition_id: str
    asset: str
    title: str
    outcome: str
    buys: list[dict] = field(default_factory=list)
    redeem: Optional[dict] = None

    @property
    def total_spent_usdc(self) -> float:
        return sum(b.get("usdcSize") or 0 for b in self.buys)

    @property
    def redeem_usdc(self) -> float:
        if self.redeem is None:
            return 0.0
        return self.redeem.get("usdcSize") or 0.0

    @property
    def pnl(self) -> float:
        return self.redeem_usdc - self.total_spent_usdc

    @property
    def is_loss(self) -> bool:
        if self.redeem is not None:
            return self.pnl <= 0
        return is_expired(parse_market_end_time(self.title))


def build_positions(buys: list[dict], redeems: list[dict]) -> list[Position]:
    buy_groups: dict[tuple, Position] = {}
    for buy in buys:
        if buy.get("side") != "BUY":
            continue
        cid = buy["conditionId"]
        asset = buy["asset"]
        key = (cid, asset)
        if key not in buy_groups:
            buy_groups[key] = Position(
                condition_id=cid,
                asset=asset,
                title=buy.get("title", "Unknown"),
                outcome=buy.get("outcome", "Unknown"),
            )
        buy_groups[key].buys.append(buy)

    redeem_by_cid: dict[str, list[dict]] = defaultdict(list)
    for redeem in redeems:
        redeem_by_cid[redeem["conditionId"]].append(redeem)

    for (cid, _), position in buy_groups.items():
        if cid in redeem_by_cid:
            all_redeems = redeem_by_cid[cid]
            combined_usdc = sum(r.get("usdcSize") or 0 for r in all_redeems)
            position.redeem = {**all_redeems[-1], "usdcSize": combined_usdc}

    return list(buy_groups.values())


def count_losses(address: str) -> int:
    three_hours_ago = int(time.time()) - (3 * 60 * 60)
    buys = [b for b in fetch_activity(address, "TRADE", start=three_hours_ago) if b.get("side") == "BUY"]
    redeems = fetch_activity(address, "REDEEM", start=three_hours_ago)
    positions = build_positions(buys, redeems)
    return sum(1 for p in positions if p.is_loss)


if __name__ == "__main__":
    address = os.getenv("PROXY_ADDRESS")
    if not address:
        print("Error: PROXY_ADDRESS environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    print(count_losses(address))