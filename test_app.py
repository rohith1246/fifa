import os
import json
import unittest
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from app import app, run_ai_generation
from database import Base, engine, SessionLocal
from models import User, StadiumGate, Incident, ChatLog, StaffAllocation

# Configure environment for in-memory testing database
os.environ["DATABASE_URL"] = "sqlite:///:memory:"


class SmartStadiumTestCase(unittest.TestCase):
    """
    Automated test case suite verifying operations logic, security, accessibility boundaries,
    and AI integrations of the World Cup Smart Stadium application.
    """

    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

        # Initialize mock DB schemas
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()

        # Populate default gates for testing flow reallocations
        self.db.query(StaffAllocation).delete()
        self.db.query(Incident).delete()
        self.db.query(ChatLog).delete()
        self.db.query(StadiumGate).delete()
        self.db.query(User).delete()
        self.db.commit()

        self.gate_a = StadiumGate(
            name="Gate A (East Concourse)", capacity=15000, queue_time=15, staff_count=8
        )
        self.gate_b = StadiumGate(
            name="Gate B (South Concourse)",
            capacity=20000,
            queue_time=35,
            staff_count=12,
        )
        self.db.add_all([self.gate_a, self.gate_b])
        self.db.commit()

        # Create mock sessions
        self.test_user = User(
            username="OpsUser",
            password_hash=generate_password_hash("ops_password"),
            role="operations",
        )
        self.fan_user = User(
            username="FanUser",
            password_hash=generate_password_hash("fan_password"),
            role="fan",
        )
        self.db.add_all([self.test_user, self.fan_user])
        self.db.commit()

        # Default: logged in as operations
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.test_user.id
            sess["username"] = self.test_user.username
            sess["role"] = self.test_user.role

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=engine)

    # 1. Registration Constraints Tests
    def test_registration_short_password_rejected(self):
        """Verify registration fails if password length is under 6 characters."""
        payload = {
            "username": "NewUser",
            "password": "123",
            "confirm_password": "123",
            "role": "fan",
        }
        response = self.client.post("/register", data=payload)
        self.assertEqual(response.status_code, 302)
        # Should redirect back to registration page
        self.assertIn("/register", response.headers["Location"])

    def test_registration_password_mismatch_rejected(self):
        """Verify registration fails if passwords do not match."""
        payload = {
            "username": "NewUser",
            "password": "password123",
            "confirm_password": "differentpassword",
            "role": "fan",
        }
        response = self.client.post("/register", data=payload)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/register", response.headers["Location"])

    def test_registration_duplicate_username_rejected(self):
        """Verify that registering an already taken username fails."""
        payload = {
            "username": "OpsUser",  # Existing username
            "password": "newpassword123",
            "confirm_password": "newpassword123",
            "role": "fan",
        }
        response = self.client.post("/register", data=payload)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/register", response.headers["Location"])

    # 2. Login Credentials Tests
    def test_login_success(self):
        """Verify login succeeds with correct credentials."""
        payload = {"username": "OpsUser", "password": "ops_password"}
        response = self.client.post("/login", data=payload)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard", response.headers["Location"])

    def test_login_wrong_password_rejected(self):
        """Verify login fails with incorrect credentials."""
        payload = {"username": "OpsUser", "password": "wrongpassword"}
        response = self.client.post("/login", data=payload)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    # 3. Session Clearing on Logout Test
    def test_logout_destroys_session(self):
        """Verify logout clears user session and redirects to index."""
        response = self.client.get("/logout")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/", response.headers["Location"])

        # Accessing dashboard should now redirect to login page
        dash_response = self.client.get("/dashboard")
        self.assertEqual(dash_response.status_code, 302)
        self.assertIn("/login", dash_response.headers["Location"])

    # 4. Security Headers Parameter Test
    def test_security_headers_present(self):
        """Verify that essential security HTTP headers are present on responses."""
        response = self.client.get("/")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-XSS-Protection"), "1; mode=block")
        self.assertIn("Content-Security-Policy", response.headers)

    # 5. CSRF Shield Check
    def test_csrf_validation_enforced(self):
        """Verify that mutating POST routes block requests if CSRF token is missing/invalid."""
        app.config["TESTING"] = False  # Enable CSRF filter checks
        try:
            payload = {
                "title": "Turnstile Jam",
                "description": "Gate A turnstile is stuck.",
                "category": "facilities",
            }
            # No X-CSRF-Token or csrf_token parameter in payload
            response = self.client.post(
                "/api/incident/report",
                data=json.dumps(payload),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)
            data = json.loads(response.get_data(as_text=True))
            self.assertIn("error", data)
            self.assertIn("CSRF", data["error"])
        finally:
            app.config["TESTING"] = True

    # 6. Input HTML-escaping stored XSS prevention
    @patch("app.run_ai_generation")
    def test_xss_escaping_on_incident_inputs(self, mock_run_ai):
        """Verify that reported incident descriptions are html-escaped before DB storage."""
        mock_response_json = {
            "severity": "High",
            "dispatch_notes": "Alert stadium safety officers immediately.",
        }
        mock_run_ai.return_value = (json.dumps(mock_response_json), "gemini")

        malicious_input = "<script>alert('XSS')</script>"
        payload = {
            "title": "Security Issue",
            "description": malicious_input,
            "category": "security",
        }
        response = self.client.post(
            "/api/incident/report",
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-CSRF-Token": "mock_token"},
        )
        self.assertEqual(response.status_code, 201)

        # Retrieve incident from database
        self.db.expire_all()
        incident = self.db.query(Incident).filter(Incident.title == "Security Issue").first()
        self.assertIsNotNone(incident)
        # Check that description is escaped (does not contain raw script tags)
        self.assertNotIn("<script>", incident.description)
        self.assertIn("&lt;script&gt;", incident.description)

    # 7. Role-Based Route Protection Checks
    def test_unauthorized_incident_reporting_for_fan(self):
        """Verify that fans cannot access operations incident reporting endpoints."""
        # Switch session role to fan
        with self.client.session_transaction() as sess:
            sess["role"] = "fan"
            sess["username"] = self.fan_user.username
            sess["user_id"] = self.fan_user.id

        payload = {
            "title": "Medical help",
            "description": "Medic request in Sector 3",
            "category": "medical",
        }
        response = self.client.post(
            "/api/incident/report",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_unauthorized_staff_reallocation_for_fan(self):
        """Verify that fans cannot execute staff reallocation commands."""
        with self.client.session_transaction() as sess:
            sess["role"] = "fan"
            sess["username"] = self.fan_user.username
            sess["user_id"] = self.fan_user.id

        payload = {
            "gate_id": self.gate_a.id,
            "from_gate": self.gate_b.name,
            "quantity": 2,
            "reason": "Relieve congestion",
        }
        response = self.client.post(
            "/api/staff/allocate",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    # 8. Staff reallocation logical math tests
    def test_staff_reallocation_math_bounds(self):
        """Verify that re-allocating staff correctly deducts from source and adds to destination."""
        payload = {
            "gate_id": self.gate_a.id,
            "from_gate": self.gate_b.name,
            "quantity": 3,
            "reason": "Optimize flow",
        }
        response = self.client.post(
            "/api/staff/allocate",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

        # Expiry cache to force DB re-read
        self.db.expire_all()
        target = self.db.query(StadiumGate).filter(StadiumGate.id == self.gate_a.id).first()
        source = self.db.query(StadiumGate).filter(StadiumGate.name == self.gate_b.name).first()

        # Gate A started with 8 staff. Added 3 coordinators -> should be 11.
        self.assertEqual(target.staff_count, 11)
        # Gate B started with 12 staff. Deducted 3 coordinators -> should be 9.
        self.assertEqual(source.staff_count, 9)

        # Confirm queue times recalculated appropriately
        # More staff = faster flow (A time should decrease, B time should increase)
        self.assertTrue(target.queue_time < 15)
        self.assertTrue(source.queue_time > 35)

    def test_staff_reallocation_negative_quantity_rejected(self):
        """Verify that reallocating negative staff count is blocked with 400."""
        payload = {
            "gate_id": self.gate_a.id,
            "from_gate": self.gate_b.name,
            "quantity": -2,
            "reason": "Error",
        }
        response = self.client.post(
            "/api/staff/allocate",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_staff_reallocation_excessive_quantity_rejected(self):
        """Verify that reallocating more staff than the source gate holds is rejected."""
        payload = {
            "gate_id": self.gate_a.id,
            "from_gate": self.gate_b.name,
            "quantity": 50,  # Gate B only has 12 coordinators
            "reason": "Exceeding resources",
        }
        response = self.client.post(
            "/api/staff/allocate",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    # 9. AI Incident Classification Validation Test
    @patch("app.run_ai_generation")
    def test_incident_reporting_with_ai_classification(self, mock_run_ai):
        """Verify that reporting an incident categorizes severity and action protocol using AI."""
        mock_response_json = {
            "severity": "High",
            "dispatch_notes": "Deploy medical unit immediately to West aisle.",
        }
        mock_run_ai.return_value = (json.dumps(mock_response_json), "gemini")

        payload = {
            "title": "Severe Heatstroke",
            "description": "Fan unconscious near Gate A.",
            "category": "medical",
        }
        response = self.client.post(
            "/api/incident/report",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data["incident"]["severity"], "High")
        self.assertEqual(
            data["incident"]["dispatch_notes"],
            "Deploy medical unit immediately to West aisle.",
        )

    # 10. AI Optimization Planner Test
    @patch("app.run_ai_generation")
    def test_operations_ai_flow_optimization(self, mock_run_ai):
        """Verify that operations optimization recommendations are successfully returned by AI."""
        mock_recommendations = [
            {
                "from_gate": "Gate B (South Concourse)",
                "to_gate_id": self.gate_a.id,
                "quantity": 2,
                "reason": "Balance queue times.",
            }
        ]
        mock_run_ai.return_value = (json.dumps(mock_recommendations), "gemini")

        response = self.client.post("/api/operations/optimize")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(len(data["recommendations"]), 1)
        self.assertEqual(data["recommendations"][0]["quantity"], 2)

    # 11. Fan Real-Time Chat Log Test
    @patch("app.run_ai_generation")
    def test_fan_realtime_chat_saves_and_responds(self, mock_run_ai):
        """Verify that fan chat helper stores conversation in DB and returns AI reply."""
        mock_run_ai.return_value = (
            "Enter via Gate C. The wait time is under 8 minutes.",
            "gemini",
        )

        payload = {"message": "How do I get to my seat at the East side?"}
        response = self.client.post(
            "/api/chat", data=json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertIn("Enter via Gate C", data["response"])

        # Check that user chat log was stored
        self.db.expire_all()
        chat_count = self.db.query(ChatLog).filter(ChatLog.user_id == self.test_user.id).count()
        # 2 logs -> User query + AI response
        self.assertEqual(chat_count, 2)

    # 12. Dynamic Queue Simulation Check
    def test_crowd_simulation_fluctuates_metrics(self):
        """Verify crowd simulation correctly randomizes wait times and staff counts."""
        response = self.client.post("/api/gates/simulate")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertIn("message", data)
        self.assertEqual(len(data["gates"]), 2)

    # 13. Fallback to Groq API on Gemini failure
    @patch("app.requests.post")
    def test_ai_fallback_on_gemini_failure(self, mock_groq_post):
        """Verify that if Gemini fails, the app falls back to Groq REST API successfully."""
        mock_response_json = {
            "choices": [{"message": {"content": "Tactical response: deploy first response crew."}}]
        }
        mock_groq_post.return_value.status_code = 200
        mock_groq_post.return_value.json.return_value = mock_response_json

        # Force Gemini failure by setting environment keys to triggers
        with patch.dict(
            "os.environ",
            {
                "GEMINI_API_KEY": "invalid_placeholder_to_force_failure",
                "GROQ_API_KEY": "mocked_groq_api_key_for_testing",
            },
        ):
            prompt = "Simulate dispatch command prompt"
            result, provider = run_ai_generation(prompt, response_type="text")

            self.assertEqual(provider, "groq")
            self.assertEqual(result, "Tactical response: deploy first response crew.")
            self.assertTrue(mock_groq_post.called)

    # 14. AI Announcement Generator Tests
    @patch("app.run_ai_generation")
    def test_generate_announcement_success(self, mock_run_ai):
        """Verify operations team can successfully generate an announcement text via AI."""
        mock_run_ai.return_value = (
            "Attention all fans, Gate C is now open for entry.",
            "gemini",
        )
        payload = {"topic": "Gate C is now open", "language": "English"}
        response = self.client.post(
            "/api/announce",
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-CSRF-Token": "mock_token"},
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertIn("Attention all fans", data["announcement"])
        self.assertEqual(data["language"], "English")

    def test_generate_announcement_unauthorized_for_fan(self):
        """Verify that fans cannot access the AI announcement generation endpoint."""
        # Switch session role to fan
        with self.client.session_transaction() as sess:
            sess["role"] = "fan"
            sess["username"] = self.fan_user.username
            sess["user_id"] = self.fan_user.id

        payload = {"topic": "Gate C is open", "language": "English"}
        response = self.client.post(
            "/api/announce",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    # 15. Matchday Context Tests
    @patch("app.run_ai_generation")
    def test_matchday_context_success(self, mock_run_ai):
        """Verify logged-in user can access tournament context and AI ops briefing."""
        mock_run_ai.return_value = (
            "Briefing: Plan for high transport volumes at Gate B today.",
            "gemini",
        )
        response = self.client.get("/api/matchday")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(data["total_matches"], 104)
        self.assertEqual(data["host_countries"], ["USA", "Canada", "Mexico"])
        self.assertIn("MetLife Stadium", [v["name"] for v in data["venues"]])
        self.assertIn("Briefing: Plan for high", data["operations_briefing"])

    def test_matchday_context_unauthorized_for_anonymous(self):
        """Verify that anonymous users cannot access the matchday endpoint."""
        # Clear session
        with self.client.session_transaction() as sess:
            sess.clear()

        response = self.client.get("/api/matchday")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
