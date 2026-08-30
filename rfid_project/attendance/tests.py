import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import divera_kiosk
import rfid_serial_bridge
from django.test import TestCase, Client
from attendance.models import Student, Log
from attendance.uid_utils import preprocess_uid


class PreprocessUidTests(TestCase):
    def test_dash_strip(self):
        self.assertEqual(preprocess_uid("12-34-56-78"), 305419896)

    def test_rightmost_16_truncation(self):
        # 24 hex chars -> keep rightmost 16; value stays below the 999999999999 cap
        long_uid = "FFFFFFFFFFFF0000000000001234"
        expected = int("0000000000001234", 16)  # 4660
        self.assertEqual(preprocess_uid(long_uid), expected)

    def test_rightmost_16_truncation_with_dashes(self):
        # Hyphens are stripped before the rightmost-16 truncation applies.
        # 28 hex chars -> rightmost 16; value stays below the 999999999999 cap.
        long_dashed = "AB-CD-EF-01-23-45-00-00-00-00-00-00-12-34"
        expected = int("0000000000001234", 16)  # 4660
        self.assertEqual(preprocess_uid(long_dashed), expected)

    def test_odd_length_padding(self):
        self.assertEqual(preprocess_uid("123"), int("0123", 16))

    def test_cap_at_999999999999(self):
        self.assertEqual(preprocess_uid("DEADBEEFCAFE1234"), 999999999999)

    def test_non_hex_raises(self):
        with self.assertRaises(ValueError):
            preprocess_uid("ZZ")
        with self.assertRaises(ValueError):
            preprocess_uid("invalid-g1")


class ProcessEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_invalid_uid_returns_400(self):
        resp = self.client.get("/process/?uid=ZZ")
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"invalid uid", resp.content)

    def test_invalid_card_id_returns_400(self):
        resp = self.client.get("/process/?card_id=abc")
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"invalid card id", resp.content)

    def test_delete_flag_removes_open_log(self):
        card_id = 777
        Student.objects.create(card_id=card_id, name="Dan")
        self.client.get("/process/?card_id=777")  # opens a Log (attend -> auth)
        self.assertTrue(Log.objects.filter(card_id=card_id, time_out__isnull=True).exists())
        resp = self.client.get("/process/?card_id=777&delete=1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"deleted", resp.content)
        self.assertFalse(Log.objects.filter(card_id=card_id).exists())

    def test_delete_flag_with_no_open_entry(self):
        Student.objects.create(card_id=888, name="Eve")
        resp = self.client.get("/process/?card_id=888&delete=1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"no open entry", resp.content)

    def test_end_to_end_creates_student_and_log(self):
        card_id = 305419896
        # First scan registers a new student (name is None at this point)
        resp1 = self.client.get("/process/?uid=12-34-56-78")
        self.assertEqual(resp1.status_code, 200)
        self.assertTrue(Student.objects.filter(card_id=card_id).exists())
        # Simulate the operator completing the student's profile (real flow)
        Student.objects.filter(card_id=card_id).update(name="Test User")
        # Second scan now triggers attend() which creates a Log
        resp2 = self.client.get("/process/?uid=12-34-56-78")
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(Log.objects.filter(card_id=card_id).exists())


class LegacyCardIdEndpointTests(TestCase):
    """Guards the legacy decoded-number acceptance path (?card_id=<int>)."""

    def setUp(self):
        self.client = Client()

    def test_legacy_card_id_path_returns_auth(self):
        Student.objects.create(card_id=999, name="Carol")
        resp = self.client.get("/process/?card_id=999")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"auth", resp.content)


class PresentEndpointTests(TestCase):
    """Tests for the JSON /present/ endpoint (today's open attendance logs)."""

    def setUp(self):
        self.client = Client()

    def test_no_data_returns_empty_list(self):
        resp = self.client.get("/present/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_open_log_today_is_listed(self):
        student = Student.objects.create(card_id=1234, name="Alice")
        Log.objects.create(ida=student.id, card_id=student.card_id, name=student.name,
                           date=datetime.now(), time_in=datetime.now(), status="")
        resp = self.client.get("/present/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertEqual(set(entry.keys()), {"name", "card_id", "date"})
        self.assertEqual(entry["name"], "Alice")
        self.assertEqual(entry["card_id"], 1234)
        self.assertEqual(entry["date"], datetime.now().strftime("%d.%m.%Y"))

    def test_closed_and_yesterday_logs_are_excluded(self):
        student = Student.objects.create(card_id=5678, name="Bob")
        # Closed log today: time_out is set -> must not appear
        Log.objects.create(ida=student.id, card_id=student.card_id, name=student.name,
                           date=datetime.now(), time_in=datetime.now(),
                           time_out=datetime.now(), status="")
        # Open log yesterday: right date window but wrong day -> must not appear
        Log.objects.create(ida=student.id, card_id=student.card_id, name=student.name,
                           date=datetime.now() - timedelta(days=1),
                           time_in=datetime.now() - timedelta(days=1), status="")
        resp = self.client.get("/present/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])


class DiveraParseTests(TestCase):
    """Pure-function tests for divera_kiosk.parse_latest_alarm.

    Contract (verified live): ``GET /api/v2/pull/all?accesskey=...`` returns
    ``{"success": true, "data": {"alarm": {"items": [...]}}}`` where ``items``
    is a list of alarm objects (id: int, closed: bool). The function returns
    ``(active: bool, newest_id: int | None)``.
    """

    def test_active_alarm_in_items_list(self):
        payload = {
            "success": True,
            "data": {"alarm": {"items": [{"id": 123, "closed": False}]}},
        }
        active, newest_id = divera_kiosk.parse_latest_alarm(payload)
        self.assertTrue(active)
        self.assertEqual(newest_id, 123)

    def test_closed_alarm_is_inactive(self):
        payload = {
            "success": True,
            "data": {"alarm": {"items": [{"id": 123, "closed": True}]}},
        }
        active, _ = divera_kiosk.parse_latest_alarm(payload)
        self.assertFalse(active)

    def test_newest_id_is_max_across_items(self):
        payload = {
            "success": True,
            "data": {
                "alarm": {
                    "items": [
                        {"id": 1, "closed": True},
                        {"id": 42, "closed": False},
                        {"id": 17, "closed": True},
                    ]
                }
            },
        }
        active, newest_id = divera_kiosk.parse_latest_alarm(payload)
        self.assertTrue(active)
        self.assertEqual(newest_id, 42)

    def test_any_open_alarm_means_active(self):
        payload = {
            "success": True,
            "data": {
                "alarm": {
                    "items": [
                        {"id": 1, "closed": True},
                        {"id": 2, "closed": False},
                    ]
                }
            },
        }
        active, _ = divera_kiosk.parse_latest_alarm(payload)
        self.assertTrue(active)

    def test_items_as_dict_keyed_by_id(self):
        payload = {
            "success": True,
            "data": {
                "alarm": {
                    "items": {
                        "123": {"id": 123, "closed": False},
                        "456": {"id": 456, "closed": True},
                    }
                }
            },
        }
        active, newest_id = divera_kiosk.parse_latest_alarm(payload)
        self.assertTrue(active)
        self.assertEqual(newest_id, 456)

    def test_empty_items_is_inactive(self):
        payload = {"success": True, "data": {"alarm": {"items": []}}}
        active, newest_id = divera_kiosk.parse_latest_alarm(payload)
        self.assertFalse(active)
        self.assertIsNone(newest_id)

    def test_missing_data_key_is_inactive(self):
        payload = {"success": True}
        active, newest_id = divera_kiosk.parse_latest_alarm(payload)
        self.assertFalse(active)
        self.assertIsNone(newest_id)

    def test_success_false_is_inactive(self):
        payload = {"success": False, "data": {"alarm": {"items": [{"id": 1, "closed": False}]}}}
        active, _ = divera_kiosk.parse_latest_alarm(payload)
        self.assertFalse(active)

    def test_malformed_payloads_do_not_raise(self):
        for payload in (None, [], "boom", {}, {"success": True, "data": []},
                        {"data": {"alarm": "not-a-dict"}},
                        {"success": True, "data": {"alarm": {"items": "nope"}}},
                        {"success": True, "data": {"alarm": {"items": [None, "x"]}}}):
            active, newest_id = divera_kiosk.parse_latest_alarm(payload)
            self.assertFalse(active)
            self.assertIsNone(newest_id)


class ForwardUidTests(TestCase):
    """Tests for rfid_serial_bridge.forward_uid retry/drop policy.

    Contract: 2xx -> accepted (True, single request); 4xx -> dropped
    immediately (False, single request); 5xx and network errors -> retried
    with backoff up to max_attempts, then dropped (False).
    """

    def setUp(self):
        self.uid = "74-10-37-94"

    def _get(self, status=200, raise_on_call=None):
        mock = Mock(side_effect=raise_on_call)
        if raise_on_call is None:
            mock.return_value = Mock(status_code=status)
        return mock

    def test_2xx_returns_true_single_request(self):
        with patch("rfid_serial_bridge.requests.get", self._get(200)) as get:
            result = rfid_serial_bridge.forward_uid("http://api", self.uid)
        self.assertTrue(result)
        get.assert_called_once()

    def test_4xx_drops_immediately(self):
        with patch("rfid_serial_bridge.requests.get", self._get(400)) as get:
            result = rfid_serial_bridge.forward_uid("http://api", self.uid)
        self.assertFalse(result)
        get.assert_called_once()

    def test_5xx_retries_then_drops(self):
        with patch("rfid_serial_bridge.time.sleep"):
            with patch("rfid_serial_bridge.requests.get", self._get(503)) as get:
                result = rfid_serial_bridge.forward_uid(
                    "http://api", self.uid, max_attempts=3)
        self.assertFalse(result)
        self.assertEqual(get.call_count, 3)

    def test_5xx_then_2xx_recovers(self):
        side_effect = [Mock(status_code=500), Mock(status_code=200)]
        with patch("rfid_serial_bridge.time.sleep"):
            with patch("rfid_serial_bridge.requests.get", Mock(side_effect=side_effect)) as get:
                result = rfid_serial_bridge.forward_uid(
                    "http://api", self.uid, max_attempts=3)
        self.assertTrue(result)
        self.assertEqual(get.call_count, 2)

    def test_network_error_retries_then_drops(self):
        import requests
        with patch("rfid_serial_bridge.time.sleep"):
            with patch("rfid_serial_bridge.requests.get",
                       Mock(side_effect=requests.exceptions.ConnectionError("down"))) as get:
                result = rfid_serial_bridge.forward_uid(
                    "http://api", self.uid, max_attempts=2)
        self.assertFalse(result)
        self.assertEqual(get.call_count, 2)


class AlarmViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    def _mock_success(self, payload):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        return mock_resp

    def test_alarm_active_renders_title_and_vehicle_name(self):
        payload = {
            "success": True,
            "data": {
                "alarm": {
                    "items": [
                        {
                            "id": 1,
                            "closed": False,
                            "title": "Testalarm",
                            "priority": True,
                            "address": "Musterstr. 1",
                            "vehicle": [68687],
                        }
                    ]
                },
                "vehicle": {"68687": {"name": "LF 10"}},
            },
        }
        with patch.dict(os.environ, {"DIVERA_ACCESS_KEY": "test-key"}):
            with patch("attendance.views.requests.get", return_value=self._mock_success(payload)) as mock_get:
                resp = self.client.get("/alarm/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Testalarm", content)
        self.assertIn("LF 10", content)
        self.assertIn("Sonderrechte", content)
        self.assertIn("no-store", resp["Cache-Control"])
        self.assertGreaterEqual(mock_get.call_count, 1)
        self.assertIn("Fahrzeugstatus", content)

    def test_alarm_closed_shows_idle(self):
        payload = {
            "success": True,
            "data": {"alarm": {"items": [{"id": 1, "closed": True, "title": "Old alarm"}]}},
        }
        with patch.dict(os.environ, {"DIVERA_ACCESS_KEY": "test-key"}):
            with patch("attendance.views.requests.get", return_value=self._mock_success(payload)):
                resp = self.client.get("/alarm/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Keine Einsatzkräfte", resp.content.decode())
        self.assertIn("no-store", resp["Cache-Control"])

    def test_alarm_empty_items_shows_idle(self):
        payload = {"success": True, "data": {"alarm": {"items": []}}}
        with patch.dict(os.environ, {"DIVERA_ACCESS_KEY": "test-key"}):
            with patch("attendance.views.requests.get", return_value=self._mock_success(payload)):
                resp = self.client.get("/alarm/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Keine Einsatzkräfte", resp.content.decode())

    def test_alarm_items_as_dict(self):
        payload = {
            "success": True,
            "data": {
                "alarm": {
                    "items": {
                        "1": {"id": 1, "closed": False, "title": "DictAlarm", "priority": False},
                        "2": {"id": 2, "closed": True, "title": "Old"},
                    }
                }
            },
        }
        with patch.dict(os.environ, {"DIVERA_ACCESS_KEY": "test-key"}):
            with patch("attendance.views.requests.get", return_value=self._mock_success(payload)):
                resp = self.client.get("/alarm/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("DictAlarm", content)
        self.assertNotIn("Kein aktiver Alarm", content)

    def test_alarm_malformed_payload_shows_idle(self):
        payload = {"success": True, "data": {"alarm": {"items": "nope"}}}
        with patch.dict(os.environ, {"DIVERA_ACCESS_KEY": "test-key"}):
            with patch("attendance.views.requests.get", return_value=self._mock_success(payload)):
                resp = self.client.get("/alarm/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Keine Einsatzkräfte", resp.content.decode())
        self.assertNotIn("Daten nicht verf", resp.content.decode())

    def test_alarm_api_error_shows_banner(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch.dict(os.environ, {"DIVERA_ACCESS_KEY": "test-key"}):
            with patch("attendance.views.requests.get", return_value=mock_resp):
                resp = self.client.get("/alarm/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Daten nicht verf", content)
        self.assertIn("Keine Einsatzkräfte", content)
        self.assertIn("no-store", resp["Cache-Control"])

    def test_alarm_network_error_shows_banner(self):
        import requests

        with patch.dict(os.environ, {"DIVERA_ACCESS_KEY": "test-key"}):
            with patch("attendance.views.requests.get", side_effect=requests.exceptions.ConnectionError("down")):
                resp = self.client.get("/alarm/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Daten nicht verf", content)
        self.assertIn("Keine Einsatzkräfte", content)
        self.assertIn("no-store", resp["Cache-Control"])

    def test_alarm_address_fallback_uses_map_link(self):
        payload = {
            "success": True,
            "data": {
                "alarm": {
                    "items": [
                        {
                            "id": 2,
                            "closed": False,
                            "title": "AddrFallback",
                            "address": "",
                            "lat": 52.5,
                            "lng": 13.4,
                        }
                    ]
                }
            },
        }
        with patch.dict(os.environ, {"DIVERA_ACCESS_KEY": "test-key"}):
            with patch("attendance.views.requests.get", return_value=self._mock_success(payload)):
                resp = self.client.get("/alarm/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("AddrFallback", content)
        self.assertIn("openstreetmap", content.lower())
        self.assertIn("mlat=", content.lower())
        self.assertTrue("52.5" in content or "52,5" in content)
        self.assertTrue("13.4" in content or "13,4" in content)

    def test_alarm_requires_get(self):
        resp = self.client.post("/alarm/")
        self.assertEqual(resp.status_code, 405)
        self.assertIn("Method Not Allowed", resp.content.decode())
