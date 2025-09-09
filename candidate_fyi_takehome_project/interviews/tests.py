from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from rest_framework.test import APITestCase
from rest_framework import status

from candidate_fyi_takehome_project.interviews.models import InterviewTemplate, Interviewer


# -------------------------
# Small helpers for tests
# -------------------------
def z(dt: datetime) -> str:
    """UTC ISO8601 with trailing Z (matches view output)."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def api_url(template_id: int, qs: str = "") -> str:
    base = f"/api/interviews/{template_id}/availability/"
    return f"{base}?{qs}" if qs else base


class InterviewAvailabilityViewTests(APITestCase):
    def setUp(self):
        # Two interviewers + a 60-minute template
        # NOTE: Interviewer has no "name" field — create with no args.
        self.alice = Interviewer.objects.create()
        self.bob = Interviewer.objects.create()
        self.template = InterviewTemplate.objects.create(name="Tech Interview", duration=60)
        self.template.interviewers.add(self.alice, self.bob)

    # -------------------------
    # Basic error handling
    # -------------------------
    def test_404_when_template_not_found(self):
        resp = self.client.get(api_url(999999))  # non-existent id
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        # This one still returns {"error": "..."} from the view
        self.assertIn("error", resp.json())

    def test_400_when_end_before_start(self):
        start = "2030-01-02T10:00:00Z"
        end = "2030-01-01T10:00:00Z"
        resp = self.client.get(api_url(self.template.id, f"start={start}&end={end}"))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        errors = resp.json()
        # Serializer-style field error: {"end": ["end must be after start"]}
        self.assertIn("end", errors)
        msgs = errors["end"] if isinstance(errors["end"], list) else [errors["end"]]
        self.assertTrue(any("must be after start" in str(m).lower() for m in msgs))

    def test_400_when_invalid_hour_values(self):
        start = "2030-01-01T09:00:00Z"
        end = "2030-01-01T17:00:00Z"

        # start_hour out of range
        resp = self.client.get(api_url(self.template.id, f"start={start}&end={end}&start_hour=25"))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        # end_hour out of range
        resp = self.client.get(api_url(self.template.id, f"start={start}&end={end}&end_hour=-1"))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        # start_hour >= end_hour
        resp = self.client.get(api_url(self.template.id, f"start={start}&end={end}&start_hour=17&end_hour=17"))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

        resp = self.client.get(api_url(self.template.id, f"start={start}&end={end}&start_hour=18&end_hour=17"))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    # -------------------------
    # Happy path: deterministic busy data, fixed future day
    # -------------------------
    @patch("candidate_fyi_takehome_project.interviews.views.get_free_busy_data")
    def test_slots_respect_duration_half_hour_and_all_interviewers_free(self, mock_busy):
        """
        Day: 2030-01-01 09:00-17:00 UTC, duration=60

        Busy blocks (half-open):
          Alice: [09:30,10:30), [13:00,13:30)
          Bob:   [10:00,11:00), [15:30,17:00)

        Common FREE windows:
          [09:00,09:30)   # < 60m, ignored
          [11:00,13:00)   # -> 11:00-12:00, 11:30-12:30, 12:00-13:00
          [13:30,15:30)   # -> 13:30-14:30, 14:00-15:00, 14:30-15:30
        """
        day = datetime(2030, 1, 1, tzinfo=timezone.utc)
        nine = day.replace(hour=9)
        five = day.replace(hour=17)

        def busy_for(ids):
            return [
                {
                    "interviewerId": self.alice.id,
                    "name": "Alice",
                    "busy": [
                        {"start": z(nine.replace(hour=9, minute=30)), "end": z(nine.replace(hour=10, minute=30))},
                        {"start": z(nine.replace(hour=13, minute=0)), "end": z(nine.replace(hour=13, minute=30))},
                    ],
                },
                {
                    "interviewerId": self.bob.id,
                    "name": "Bob",
                    "busy": [
                        {"start": z(nine.replace(hour=10, minute=0)), "end": z(nine.replace(hour=11, minute=0))},
                        {"start": z(nine.replace(hour=15, minute=30)), "end": z(five)},
                    ],
                },
            ]
        mock_busy.side_effect = busy_for

        start = z(day.replace(hour=9))
        end = z(day.replace(hour=17))
        resp = self.client.get(api_url(self.template.id, f"start={start}&end={end}&start_hour=9&end_hour=17"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()

        self.assertEqual(data["interviewId"], self.template.id)
        self.assertEqual(data["durationMinutes"], 60)
        slots = data["availableSlots"]

        expected = [
            (day.replace(hour=11, minute=0), day.replace(hour=12, minute=0)),
            (day.replace(hour=11, minute=30), day.replace(hour=12, minute=30)),
            (day.replace(hour=12, minute=0), day.replace(hour=13, minute=0)),
            (day.replace(hour=13, minute=30), day.replace(hour=14, minute=30)),
            (day.replace(hour=14, minute=0), day.replace(hour=15, minute=0)),
            (day.replace(hour=14, minute=30), day.replace(hour=15, minute=30)),
        ]
        expected_json = [{"start": z(s), "end": z(e)} for s, e in expected]
        self.assertEqual(slots, expected_json)

        for s in slots:
            sd = datetime.fromisoformat(s["start"].replace("Z", "+00:00"))
            ed = datetime.fromisoformat(s["end"].replace("Z", "+00:00"))
            self.assertIn(sd.minute, (0, 30))
            self.assertEqual(sd.second, 0)
            self.assertEqual(ed - sd, timedelta(minutes=60))

        self.assertTrue(any(i["name"] == "Alice" for i in data["interviewers"]))
        self.assertTrue(any(i["name"] == "Bob" for i in data["interviewers"]))

    # -------------------------
    # Work-hours window filtering
    # -------------------------
    @patch("candidate_fyi_takehome_project.interviews.views.get_free_busy_data")
    def test_work_hours_filter_applied(self, mock_busy):
        """
        With the same free windows as previous test and duration=60,
        if work hours are [10, 12], only 11:00-12:00 is valid.
        """
        day = datetime(2030, 1, 1, tzinfo=timezone.utc)

        def busy_for(ids):
            return [
                {
                    "interviewerId": self.alice.id,
                    "name": "Alice",
                    "busy": [
                        {"start": z(day.replace(hour=9, minute=30)), "end": z(day.replace(hour=10, minute=30))},
                        {"start": z(day.replace(hour=13, minute=0)), "end": z(day.replace(hour=13, minute=30))},
                    ],
                },
                {
                    "interviewerId": self.bob.id,
                    "name": "Bob",
                    "busy": [
                        {"start": z(day.replace(hour=10, minute=0)), "end": z(day.replace(hour=11, minute=0))},
                        {"start": z(day.replace(hour=15, minute=30)), "end": z(day.replace(hour=17, minute=0))},
                    ],
                },
            ]
        mock_busy.side_effect = busy_for

        start = z(day.replace(hour=9))
        end = z(day.replace(hour=17))
        resp = self.client.get(api_url(self.template.id, f"start={start}&end={end}&start_hour=10&end_hour=12"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        slots = resp.json()["availableSlots"]

        expected = [{"start": z(day.replace(hour=11, minute=0)), "end": z(day.replace(hour=12, minute=0))}]
        self.assertEqual(slots, expected)

    # -------------------------
    # 24-hour rule enforcement
    # -------------------------
    @patch("candidate_fyi_takehome_project.interviews.views.get_free_busy_data")
    def test_24h_rule_minimum_start_enforced(self, mock_busy):
        """
        If client asks for start < now+24h, the view must push the first allowed
        slot start to >= ceil_to_half_hour(now+24h), and still align to :00/:30.
        """
        def busy_for(ids):
            return [
                {"interviewerId": self.alice.id, "name": "Alice", "busy": []},
                {"interviewerId": self.bob.id, "name": "Bob", "busy": []},
            ]
        mock_busy.side_effect = busy_for

        now_utc = datetime.now(timezone.utc)
        start = z(now_utc + timedelta(hours=1))
        end = z(now_utc + timedelta(days=3))

        resp = self.client.get(api_url(self.template.id, f"start={start}&end={end}&start_hour=0&end_hour=23"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        slots = data["availableSlots"]
        self.assertGreater(len(slots), 0)

        earliest_allowed = now_utc + timedelta(hours=24)

        def ceil_half_hour(dt):
            dt = dt.astimezone(timezone.utc)
            if dt.second or dt.microsecond:
                dt = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
            else:
                dt = dt.replace(second=0, microsecond=0)
            rem = dt.minute % 30
            if rem:
                dt += timedelta(minutes=(30 - rem))
            return dt

        min_allowed = ceil_half_hour(earliest_allowed)

        for s in slots:
            sd = datetime.fromisoformat(s["start"].replace("Z", "+00:00"))
            self.assertGreaterEqual(sd, min_allowed)
            self.assertIn(sd.minute, (0, 30))
            self.assertEqual(sd.second, 0)

    # -------------------------
    # “All interviewers free” is enforced
    # -------------------------
    @patch("candidate_fyi_takehome_project.interviews.views.get_free_busy_data")
    def test_excludes_slots_where_any_interviewer_is_busy(self, mock_busy):
        """
        Alice free all day; Bob busy 11:00-12:00.
        With duration=60 and work hours 9-13, any slot overlapping 11:00-12:00
        must be excluded: 10:30-11:30, 11:00-12:00, 11:30-12:30.
        """
        day = datetime(2030, 1, 2, tzinfo=timezone.utc)

        def busy_for(ids):
            return [
                {"interviewerId": self.alice.id, "name": "Alice", "busy": []},
                {
                    "interviewerId": self.bob.id,
                    "name": "Bob",
                    "busy": [{"start": z(day.replace(hour=11)), "end": z(day.replace(hour=12))}],
                },
            ]
        mock_busy.side_effect = busy_for

        start = z(day.replace(hour=9))
        end = z(day.replace(hour=13))
        resp = self.client.get(api_url(self.template.id, f"start={start}&end={end}&start_hour=9&end_hour=13"))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        slots = resp.json()["availableSlots"]

        self.assertNotIn({"start": z(day.replace(hour=10, minute=30)), "end": z(day.replace(hour=11, minute=30))}, slots)
        self.assertNotIn({"start": z(day.replace(hour=11, minute=0)),  "end": z(day.replace(hour=12, minute=0))}, slots)
        self.assertNotIn({"start": z(day.replace(hour=11, minute=30)), "end": z(day.replace(hour=12, minute=30))}, slots)

        self.assertIn({"start": z(day.replace(hour=9,  minute=0)), "end": z(day.replace(hour=10, minute=0))}, slots)
        self.assertIn({"start": z(day.replace(hour=9,  minute=30)), "end": z(day.replace(hour=10, minute=30))}, slots)
        self.assertIn({"start": z(day.replace(hour=10, minute=0)), "end": z(day.replace(hour=11, minute=0))}, slots)
        self.assertIn({"start": z(day.replace(hour=12, minute=0)), "end": z(day.replace(hour=13, minute=0))}, slots)
