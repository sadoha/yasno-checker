#!/usr/bin/env python3
# - CLI utility to fetch and calculate DTEK/Yasno power outage schedules
# - Enforces strict typing (PEP 484/585), DRY HTTP session management, and explicit error handling
# - Uses explicit timezone (Europe/Kyiv) for accurate active-slot calculations on any machine

"""Yasno power outage schedule analyzer.

Usage:
    python3 yasno_check.py --city "Kyiv" --street "Хрещатик" --house "22"
    python3 yasno_check.py --city "Kyiv Region" --street "Шевченка" --house "1"
    python3 yasno_check.py --group "3"
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

BASE_URL: str = "https://app.yasno.ua/api/blackout-service/public/shutdowns"
DEFAULT_TIMEOUT: int = 10
MINUTES_PER_DAY: int = 1440
KYIV_TZ = ZoneInfo("Europe/Kyiv")

# Universal mapping for regions serviced by Yasno/DTEK
CITY_MAPPING: Mapping[str, tuple[int, int]] = {
    # Kyiv City (DTEK Kyiv Grids)
    "київ": (25, 902),
    "kyiv": (25, 902),
    "kiev": (25, 902),
    # Kyiv Region (DTEK Kyiv Regional Grids)
    "київська область": (10, 903),
    "kyiv region": (10, 903),
    "kyivska oblast": (10, 903),
}

STATUS_LABELS: Mapping[str, str] = {
    "ScheduleApplies": "Schedule active (stabilization outages)",
    "WaitingForSchedule": "Waiting for schedule update",
    "EmergencyShutdowns": "WARNING: Emergency shutdowns active (schedule inactive!)",
}

logger = logging.getLogger("yasno_check")


def configure_logging() -> None:
    """Configure clean stdout/stderr separation for operational output."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def check_prerequisites() -> None:
    """Validate minimum Python runtime version before execution."""
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer is required.")


def fetch_json(
    session: requests.Session,
    endpoint: str,
    params: Mapping[str, str | int] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Any:
    """Execute a GET request and return parsed JSON payload."""
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    response = session.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def extract_label(item: Mapping[str, Any], fallback: str = "") -> str:
    """Extract display label from Yasno API address dictionary."""
    val = item.get("value")
    if val is not None:
        return str(val)
    name = item.get("name")
    if name is not None:
        return str(name)
    return fallback


def minutes_to_hhmm(minutes: int) -> str:
    """Convert minutes from midnight (0..1440) to HH:MM string."""
    hours, mins = divmod(minutes, 60)
    return f"{hours:02d}:{mins:02d}"


def format_duration(minutes: int) -> str:
    """Format duration in minutes into human-readable hours and minutes."""
    hours, mins = divmod(minutes, 60)
    if hours > 0 and mins > 0:
        return f"{hours}h {mins}m"
    if hours > 0:
        return f"{hours}h"
    return f"{mins}m"


def resolve_group_by_address(
    session: requests.Session,
    region_id: int,
    dso_id: int,
    street_query: str,
    house_query: str,
    timeout: int,
) -> str:
    """Resolve outage group.subgroup code for a given street and house."""
    streets_data = fetch_json(
        session,
        "addresses/v2/streets",
        params={"regionId": region_id, "dsoId": dso_id, "query": street_query},
        timeout=timeout,
    )
    if not isinstance(streets_data, list) or not streets_data:
        raise ValueError(f"Street matching '{street_query}' not found.")

    selected_street: Mapping[str, Any] = streets_data[0]
    for street in streets_data:
        label_lower = extract_label(street).lower()
        if "бул" in label_lower or street_query.lower() in label_lower:
            selected_street = street
            break

    street_id = int(selected_street["id"])
    street_label = extract_label(selected_street, street_query)

    houses_data = fetch_json(
        session,
        "addresses/v2/houses",
        params={
            "regionId": region_id,
            "dsoId": dso_id,
            "streetId": street_id,
            "query": house_query,
        },
        timeout=timeout,
    )
    if not isinstance(houses_data, list) or not houses_data:
        raise ValueError(f"House '{house_query}' on '{street_label}' not found.")

    if len(houses_data) > 1:
        variants = ", ".join(extract_label(h) for h in houses_data)
        logger.info("Found multiple house variants: %s", variants)

    selected_house: Mapping[str, Any] = houses_data[0]
    target_upper = house_query.upper()
    for house in houses_data:
        house_label_upper = extract_label(house).upper()
        if house_label_upper == target_upper or "СЕКЦІЯ А" in house_label_upper:
            selected_house = house
            break

    house_id = int(selected_house["id"])
    house_label = extract_label(selected_house, house_query)

    group_data = fetch_json(
        session,
        "addresses/v2/group",
        params={
            "regionId": region_id,
            "dsoId": dso_id,
            "streetId": street_id,
            "houseId": house_id,
        },
        timeout=timeout,
    )
    if not isinstance(group_data, Mapping) or "group" not in group_data or "subgroup" not in group_data:
        raise KeyError("Invalid API response while resolving group.")

    group_code = f"{group_data['group']}.{group_data['subgroup']}"
    print(f"Address: {street_label}, bld. {house_label} -> Group: {group_code}")
    return group_code


def render_day_schedule(
    day_title: str,
    day_data: Mapping[str, Any] | None,
    *,
    is_today: bool,
) -> None:
    """Calculate outage statistics and print formatted day schedule to stdout."""
    if day_data is None:
        print(f"\n=== {day_title}: No data available ===")
        return

    raw_status = str(day_data.get("status", "Unknown"))
    status_text = STATUS_LABELS.get(raw_status, raw_status)
    date_str = str(day_data.get("date", ""))[:10]
    slots = day_data.get("slots")

    print(f"\n{'=' * 58}")
    print(f" {day_title} ({date_str}) | Status: {status_text}")
    print(f"{'=' * 58}")

    if not isinstance(slots, list) or not slots:
        print(" No slots available.")
        return

    outage_minutes = 0
    power_minutes = 0
    outage_count = 0

    now = datetime.now(KYIV_TZ)
    current_minute = now.hour * 60 + now.minute

    # Initialize a 48-block timeline array (each block = 30 mins), default to Power ON
    timeline_blocks = ["█"] * 48

    for slot in slots:
        if not isinstance(slot, Mapping):
            continue
        start = int(slot["start"])
        end = int(slot["end"])
        slot_type = str(slot["type"])
        duration = end - start

        if slot_type == "Definite":
            outage_minutes += duration
            outage_count += 1
            status_icon = "🔴 NO POWER  "

            # Map outage slots to the visual timeline (30 mins per index)
            start_idx = start // 30
            end_idx = end // 30
            for i in range(start_idx, end_idx):
                if i < 48:
                    timeline_blocks[i] = "░"
        else:
            power_minutes += duration
            status_icon = "🟢 POWER ON  "

        marker = ""
        if is_today and start <= current_minute < end:
            remaining = end - current_minute
            marker = f"  <-- NOW (for {format_duration(remaining)})"

        print(
            f"  {minutes_to_hhmm(start)} - {minutes_to_hhmm(end)} "
            f"({format_duration(duration):>8}) : {status_icon}{marker}"
        )

    outage_pct = (outage_minutes / MINUTES_PER_DAY) * 100
    power_pct = (power_minutes / MINUTES_PER_DAY) * 100

    print(f"{'-' * 58}")
    print(" Daily summary:")
    print(f"  • Outage count       : {outage_count}")
    print(f"  • Total without power: {format_duration(outage_minutes):<8} ({outage_pct:.1f}% of day)")
    print(f"  • Total with power   : {format_duration(power_minutes):<8} ({power_pct:.1f}% of day)")

    # Render the chronological timeline chart
    timeline_str = "".join(timeline_blocks)
    print("\n Timeline (█ = Power, ░ = Outage):")
    print(f"  [{timeline_str}]")
    print("  00          06          12          18          24")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch and calculate Yasno power outage schedules."
    )
    parser.add_argument(
        "--city",
        default="kyiv",
        help="City name (e.g., 'Kyiv', 'Київ', 'Kyiv Region'). Default is 'Kyiv'.",
    )
    parser.add_argument(
        "--street",
        help="Street name to search (e.g., 'Хрещатик').",
    )
    parser.add_argument(
        "--house",
        help="House number (e.g., '22').",
    )
    parser.add_argument(
        "--group",
        help="Explicit group code (e.g., '19.1') to skip address search.",
    )
    parser.add_argument(
        "--region-id",
        type=int,
        help="Override Region ID manually.",
    )
    parser.add_argument(
        "--dso-id",
        type=int,
        help="Override Grid operator (DSO) ID manually.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP request timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )

    args_list = sys.argv[1:] if argv is None else argv
    if not args_list:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args(argv)

    if not args.group and not (args.street and args.house):
        parser.error("You must provide either --group OR both --street and --house.")

    # Resolve City to IDs
    city_key = args.city.strip().lower()
    if city_key in CITY_MAPPING:
        default_region, default_dso = CITY_MAPPING[city_key]
    else:
        # Fallback to Kyiv if city is unknown, but warn the user
        logger.warning("Unknown city '%s'. Defaulting to Kyiv region IDs.", args.city)
        default_region, default_dso = CITY_MAPPING["kyiv"]

    # Allow explicit override via CLI arguments
    args.region_id = args.region_id if args.region_id is not None else default_region
    args.dso_id = args.dso_id if args.dso_id is not None else default_dso

    return args


def main(argv: list[str] | None = None) -> int:
    """Run main CLI workflow."""
    configure_logging()
    try:
        check_prerequisites()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    args = parse_args(argv)

    with requests.Session() as session:
        session.headers.update({"User-Agent": "YasnoScheduleCLI/1.0"})

        try:
            if args.group is not None:
                group_code = str(args.group)
            else:
                group_code = resolve_group_by_address(
                    session=session,
                    region_id=args.region_id,
                    dso_id=args.dso_id,
                    street_query=args.street,
                    house_query=args.house,
                    timeout=args.timeout,
                )

            schedules = fetch_json(
                session,
                f"regions/{args.region_id}/dsos/{args.dso_id}/planned-outages",
                timeout=args.timeout,
            )
            if not isinstance(schedules, Mapping) or group_code not in schedules:
                available = ", ".join(schedules.keys()) if isinstance(schedules, Mapping) else "unknown"
                raise KeyError(f"Group '{group_code}' not found. Available: {available}")

            group_schedule = schedules[group_code]
            if not isinstance(group_schedule, Mapping):
                raise ValueError("Invalid schedule format for the group.")

            updated_on = str(group_schedule.get("updatedOn", "unknown"))
            print(f"Schedule last updated: {updated_on}")

            today_data = group_schedule.get("today")
            tomorrow_data = group_schedule.get("tomorrow")

            render_day_schedule(
                "TODAY",
                today_data if isinstance(today_data, Mapping) else None,
                is_today=True,
            )
            render_day_schedule(
                "TOMORROW",
                tomorrow_data if isinstance(tomorrow_data, Mapping) else None,
                is_today=False,
            )

        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.error("Execution error: %s", exc)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
