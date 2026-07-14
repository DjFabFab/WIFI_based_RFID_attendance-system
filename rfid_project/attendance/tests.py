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
