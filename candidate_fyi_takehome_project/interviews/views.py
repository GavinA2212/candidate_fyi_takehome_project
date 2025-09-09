from datetime import datetime, timedelta, timezone
from typing import List, Dict, Tuple, Optional

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from candidate_fyi_takehome_project.interviews.models import InterviewTemplate
from services.mock_availability import get_free_busy_data
from .serializers import (
    AvailabilityQuerySerializer,
    AvailabilityResponseSerializer,
)

# =========================
# Constants
# =========================
HALF_HOUR = timedelta(minutes=30)
DEFAULT_SEARCH_DAYS = 7
DEFAULT_START_HOUR = 9     # 9 AM
DEFAULT_END_HOUR = 17      # 5 PM


# =========================
# Helpers (time & parsing)
# =========================
def parse_iso8601(iso_string: str) -> datetime:
    """
    Parse an ISO 8601 string (supports trailing 'Z' or timezone offsets).
    Always returns a timezone-aware datetime.
    """
    if not isinstance(iso_string, str):
        raise ValueError("datetime must be an ISO 8601 string")
    normalized = iso_string[:-1] + "+00:00" if iso_string.endswith("Z") else iso_string
    dt = datetime.fromisoformat(normalized)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def to_iso8601_utc(dt: datetime) -> str:
    """Format a datetime as UTC ISO 8601 with trailing 'Z'."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def format_datetime_human_readable(dt_str: str) -> str:
    """Convert ISO 8601 string to a friendly string like 'Monday, September 7, 2025 at 2:00 PM'."""
    dt = parse_iso8601(dt_str)
    return dt.strftime("%A, %B %d, %Y at %I:%M %p")

def format_interviewer_busy_times_human_readable(busy_schedules: List[Dict]) -> List[Dict]:
    """Turn busy blocks into a human-readable mirror for debugging/UI."""
    result: List[Dict] = []
    for person in busy_schedules:
        display = {
            "interviewerId": person["interviewerId"],
            "name": person.get("name", "Unknown"),
            "busyTimes": [],
        }
        for block in person.get("busy", []):
            raw_start = block.get("start") or block.get("startTime")
            raw_end = block.get("end") or block.get("endTime")
            if raw_start and raw_end:
                display["busyTimes"].append({
                    "start": format_datetime_human_readable(raw_start),
                    "end": format_datetime_human_readable(raw_end),
                })
        result.append(display)
    return result

def intersect_half_open_interval(start1: datetime, end1: datetime, start2: datetime, end2: datetime) -> Optional[Tuple[datetime, datetime]]:
    """
    Intersection of [start1, end1) and [start2, end2); return (start, end) or None if disjoint.
    Used to trim busy blocks to be within the search window, and not return blocks outside it.
    """
    start = max(start1, start2)
    end = min(end1, end2)
    return (start, end) if start < end else None

def ceil_to_half_hour_boundary(dt: datetime) -> datetime:
    """
    Round up to the next :00 or :30 boundary in UTC.
      12:00:00 -> 12:00
      12:00:01 -> 12:30
      12:30:00 -> 12:30
      12:30:01 -> 13:00
    """
    dt = dt.astimezone(timezone.utc)
    if dt.second or dt.microsecond:
        dt = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    else:
        dt = dt.replace(second=0, microsecond=0)
    remainder = dt.minute % 30
    if remainder:
        dt += timedelta(minutes=(30 - remainder))
    return dt

def compute_common_free_windows(busy_schedules: List[Dict], search_start: datetime, search_end: datetime) -> List[Tuple[datetime, datetime]]:
    """
    Build common-free windows across ALL interviewers within [search_start, search_end).
    busy_schedules: [
        { "interviewerId": int, "name": str, "busy": [{ "start": iso, "end": iso }, ...] },
        ...
    ]
    
    works as follows:
    
    Builds array of (timestamp, delta) events:
      +1: someone becomes busy at timestamp
      -1: someone becomes free at timestamp
      0: boundary event (search_start or search_end)
    
    Sorts events by timestamp, -1 delta (becomes free) is processed before +1 (becomes busy) when timestamps are equal.
    
    Builds free windows by scanning the timeline and counting how many are busy at each point, when busy = 0 we can start a window.
    
    Returns list of (free_start_dt, free_end_dt) in UTC.
    """
    
    events: List[Tuple[datetime, int]] = []

    for person in busy_schedules:
        for block in person.get("busy", []):
            raw_start = block.get("start") or block.get("startTime")
            raw_end = block.get("end") or block.get("endTime")
            if not raw_start or not raw_end:
                continue
            
            # Normalize to consistent datetime
            busy_start = parse_iso8601(raw_start)
            busy_end = parse_iso8601(raw_end)
            
            # Skip invalid blocks
            if busy_start >= busy_end:
                continue
            
            # Trim busy blocks to be in search window, if block is outside of window, overlap = null
            overlap = intersect_half_open_interval(busy_start, busy_end, search_start, search_end)
            if overlap:
                s, e = overlap
                # +1: someone becomes busy at s; -1: becomes free at e
                events.append((s, +1))
                events.append((e, -1))

    # Boundaries help capture free spans at the edges
    events.append((search_start, 0))
    events.append((search_end, 0))

    # Sort by time; at same timestamp process -1 before +1
    events.sort(key=lambda item: (item[0], item[1]))

    free_windows: List[Tuple[datetime, datetime]] = []
    active_busy = 0
    prev_time = search_start
    i = 0
    n = len(events)

    # Sweep the timeline, building free windows when active_busy = 0
    while i < n:
        t = events[i][0]

        # If nobody is busy between prev_time and t, that's a free window
        if active_busy == 0 and t > prev_time:
            free_windows.append((prev_time, t))

        # Sum all deltas at timestamp t
        delta_sum = 0
        while i < n and events[i][0] == t:
            delta_sum += events[i][1]
            i += 1

        active_busy += delta_sum
        prev_time = t

    return free_windows


# =========================
# Helpers (request params)
# =========================
def is_within_workday_utc(slot_start: datetime, slot_end: datetime, workday_start_hour: int, workday_end_hour: int) -> bool:
    """
    True if the slot lies entirely within the same UTC workday window:
      [slot_start.date() at workday_start_hour, slot_start.date() at workday_end_hour].
    This avoids cross-midnight mistakes and naturally allows ending exactly at closing time.
    """
    slot_start = slot_start.astimezone(timezone.utc)
    slot_end = slot_end.astimezone(timezone.utc)

    day_open = slot_start.replace(hour=workday_start_hour, minute=0, second=0, microsecond=0)
    day_close = slot_start.replace(hour=workday_end_hour, minute=0, second=0, microsecond=0)

    return day_open <= slot_start and slot_end <= day_close


# =========================
# View
# =========================
class InterviewAvailabilityView(APIView):
    """
    GET /api/interviews/{id}/available-slots?start=...&end=...&start_hour=...&end_hour=...

    - start/end (optional): ISO 8601 datetimes; default is [now+24h, now+24h+7d].
    - start_hour/end_hour (optional): Integer hour of day (0-23); default is [9, 17] (9 AM–5 PM).
    - Output:
        * Slots are exactly the interview duration.
        * Slots start on :00 or :30.
        * All interviewers free for the whole slot.
        * No slot starts < 24h in the future.
        * All times UTC in ISO 8601 (Z).
    """
    def get(self, request, id):
        # 1) Load template
        try:
            template = InterviewTemplate.objects.get(id=id)
        except InterviewTemplate.DoesNotExist:
            return Response({"error": "Interview template not found"}, status=status.HTTP_404_NOT_FOUND)

        duration_minutes = int(template.duration)
        duration_delta = timedelta(minutes=duration_minutes)

        # 2) Validate query params with serializer
        q = AvailabilityQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        vd = q.validated_data

        # Time range + 24h rule
        now_utc = datetime.now(timezone.utc)
        earliest_allowed = now_utc + timedelta(hours=24)

        # Defaults applied after validation
        search_start = (vd.get("start") or earliest_allowed).astimezone(timezone.utc)
        search_end = (vd.get("end") or (search_start + timedelta(days=DEFAULT_SEARCH_DAYS))).astimezone(timezone.utc)

        # In case only one bound provided, enforce end > start after defaults
        if search_end <= search_start:
            return Response({"error": "end must be after start"}, status=status.HTTP_400_BAD_REQUEST)

        workday_start_hour = vd.get("start_hour", DEFAULT_START_HOUR)
        workday_end_hour = vd.get("end_hour", DEFAULT_END_HOUR)
        # (Serializer checks when both provided; keep a defensive guard here, too)
        if workday_start_hour >= workday_end_hour:
            return Response({"error": "end_hour must be after start_hour"}, status=status.HTTP_400_BAD_REQUEST)

        # Apply 24h rule (if provided start is less than 24h from present) & half-hour alignment to the minimum slot start
        min_slot_start = ceil_to_half_hour_boundary(max(search_start, earliest_allowed))

        # 3) Busy data for all interviewers
        interviewer_qs = template.interviewers.all().only("id")
        interviewer_ids = [p.id for p in interviewer_qs]
        busy_schedules = get_free_busy_data(interviewer_ids)

        # 4) Compute common-free windows
        free_windows = compute_common_free_windows(busy_schedules, search_start, search_end)

        # 5) Expand free windows into aligned slots (:00 or :30) that fit duration & work hours
        available_slots: List[Dict[str, str]] = []

        for window_start, window_end in free_windows:
            # Round window start up to next :00 or :30
            slot_start = ceil_to_half_hour_boundary(max(window_start, min_slot_start))
            last_valid_start = window_end - duration_delta

            # Find all slots in the window that fit the duration, incrementing by 30 minutes
            while slot_start <= last_valid_start:
                slot_end = slot_start + duration_delta

                # Work hours constraint (UTC hours)
                within_hours = is_within_workday_utc(slot_start, slot_end, workday_start_hour, workday_end_hour)

                if within_hours:
                    available_slots.append({
                        "start": to_iso8601_utc(slot_start),
                        "end": to_iso8601_utc(slot_end),
                    })

                slot_start += HALF_HOUR  # keep starts on :00 / :30

        # Human-readable mirrors 
        human_readable_slots = [
            {"start": format_datetime_human_readable(s["start"]),
             "end":   format_datetime_human_readable(s["end"])}
            for s in available_slots
        ]
        human_readable_busy = format_interviewer_busy_times_human_readable(busy_schedules)

        # Map of interviewer IDs to names from the busy data
        interviewer_names = {
            interviewer["interviewerId"]: interviewer.get("name", "Unknown")
            for interviewer in busy_schedules
        }

        payload = {
            "interviewId": template.id,
            "name": template.name,
            "durationMinutes": duration_minutes,
            "interviewers": [
                {
                    "id": p.id,
                    "name": interviewer_names.get(p.id, "Unknown")
                }
                for p in interviewer_qs
            ],
            "availableSlots": available_slots,
            "workHours": {"startHour": workday_start_hour, "endHour": workday_end_hour},
            "humanReadable": {
                "availableSlots": human_readable_slots,
                "interviewerBusyTimes": human_readable_busy,
                "workHours": f"{workday_start_hour}:00 - {workday_end_hour}:00",
            },
        }

        # Validate/serialize response to lock schema
        out = AvailabilityResponseSerializer(payload)
        return Response(out.data, status=status.HTTP_200_OK)
