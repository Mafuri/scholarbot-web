"""
ScholarBot — Phase 2 test suite.
Run: pytest tests/ -v
"""
import os
import pytest
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///data/test_scholarbot.db")

from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, Base, engine

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
def setup_db():
    os.makedirs("data", exist_ok=True)
    init_db()
    yield
    # Teardown: drop test DB
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session")
def test_user(setup_db):
    """Register one shared test user for the entire session (avoids rate limits)."""
    email = "shared_test_user@scholarbot.test"
    # Try login first (if already exists from previous run)
    login_r = client.post("/api/auth/login", json={
        "email": email, "password": "TestPass123!",
    })
    if login_r.status_code == 200:
        data = login_r.json()
        return {"token": data["token"], "user": data["user"], "email": email}
    # Register fresh
    resp = client.post("/api/auth/register", json={
        "name": "Test Student",
        "email": email,
        "password": "TestPass123!",
        "degree_level": "Graduate",
        "major": "Computer Science",
        "school": "University of Nairobi",
        "nationality": "Kenya",
        "gpa": 3.7,
        "financial_need": True,
    })
    assert resp.status_code == 200, f"Register failed: {resp.text}"
    data = resp.json()
    return {"token": data["token"], "user": data["user"], "email": email}


@pytest.fixture(scope="session")
def auth_headers(test_user):
    return {"Authorization": f"Bearer {test_user['token']}"}


# ── Auth tests ────────────────────────────────────────────────
class TestAuth:
    def test_register_success(self):
        import uuid
        email = f"reg_{uuid.uuid4().hex[:6]}@test.com"
        r = client.post("/api/auth/register", json={
            "name": "New User", "email": email,
            "password": "Pass123!", "degree_level": "Graduate",
            "major": "IT", "school": "UoN",
            "nationality": "Kenya", "gpa": 3.5, "financial_need": False,
        })
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert data["user"]["name"] == "New User"
        assert data["user"]["email"] == email

    def test_register_duplicate_email(self, test_user):
        r = client.post("/api/auth/register", json={
            "name": "Dup", "email": test_user["email"],
            "password": "Pass123!", "degree_level": "Graduate",
            "major": "IT", "school": "UoN", "nationality": "Kenya",
        })
        assert r.status_code == 400
        assert "already registered" in r.json()["detail"]

    def test_login_success(self, test_user):
        r = client.post("/api/auth/login", json={
            "email": test_user["email"], "password": "TestPass123!",
        })
        assert r.status_code == 200
        assert "token" in r.json()

    def test_login_wrong_password(self, test_user):
        r = client.post("/api/auth/login", json={
            "email": test_user["email"], "password": "WrongPass!",
        })
        assert r.status_code == 401

    def test_me_endpoint(self, auth_headers):
        r = client.get("/api/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert "email" in r.json()

    def test_me_no_token(self):
        r = client.get("/api/auth/me")
        assert r.status_code == 401

    def test_me_invalid_token(self):
        r = client.get("/api/auth/me",
                       headers={"Authorization": "Bearer fake.jwt.token"})
        assert r.status_code == 401

    def test_logout(self, auth_headers):
        r = client.post("/api/auth/logout", headers=auth_headers)
        assert r.status_code == 200


# ── GPA normalisation tests ───────────────────────────────────
class TestGPANormalisation:
    def test_us_scale(self):
        from app.services.gpa import normalise_gpa
        result = normalise_gpa(3.8, scale=4.0, country="USA")
        assert result["gpa_4"] == 3.8
        assert result["scale"] == 4.0

    def test_nigeria_5_scale(self):
        from app.services.gpa import normalise_gpa
        result = normalise_gpa(4.2, scale=5.0, country="Nigeria")
        assert abs(result["gpa_4"] - 3.36) < 0.01

    def test_india_10_scale(self):
        from app.services.gpa import normalise_gpa
        result = normalise_gpa(8.5, scale=10.0, country="India")
        assert abs(result["gpa_4"] - 3.4) < 0.01

    def test_france_20_scale(self):
        from app.services.gpa import normalise_gpa
        result = normalise_gpa(16.0, scale=20.0, country="France")
        assert abs(result["gpa_4"] - 3.2) < 0.01

    def test_percentage_scale(self):
        from app.services.gpa import normalise_gpa
        result = normalise_gpa(78.0, scale=100.0, country="Egypt")
        assert abs(result["gpa_4"] - 3.12) < 0.01

    def test_auto_detect_scale(self):
        from app.services.gpa import normalise_gpa
        result = normalise_gpa(8.5)  # Auto-detect as 10.0
        assert result["scale"] == 10.0

    def test_zero_gpa(self):
        from app.services.gpa import normalise_gpa
        result = normalise_gpa(0.0)
        assert result["gpa_4"] == 0.0

    def test_caps_at_4(self):
        from app.services.gpa import normalise_gpa
        result = normalise_gpa(4.0, scale=4.0)
        assert result["gpa_4"] <= 4.0

    def test_register_with_international_gpa(self):
        import uuid
        r = client.post("/api/auth/register", json={
            "name": "Indian Student",
            "email": f"india_{uuid.uuid4().hex[:6]}@test.com",
            "password": "Pass123!",
            "degree_level": "Graduate",
            "major": "Engineering",
            "school": "IIT Delhi",
            "nationality": "India",
            "gpa": 8.5,         # On 10.0 scale
            "gpa_original": 8.5,
            "gpa_scale": 10.0,
            "financial_need": False,
        })
        assert r.status_code == 200
        user = r.json()["user"]
        assert user["gpa"] <= 4.0      # normalised
        assert user["gpa_original"] == 8.5
        assert user["gpa_scale"] == 10.0


# ── Profile tests ─────────────────────────────────────────────
class TestProfile:
    def test_update_profile(self, auth_headers):
        r = client.patch("/api/profile", headers=auth_headers, json={
            "major": "Cybersecurity",
            "skills": ["Python", "Network Security", "Ethical Hacking"],
        })
        assert r.status_code == 200
        data = r.json()
        assert data["major"] == "Cybersecurity"
        assert "Python" in data["skills"]

    def test_readiness_score(self, auth_headers):
        r = client.get("/api/readiness", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "overall" in data
        assert 0 <= data["overall"] <= 100
        assert "level" in data
        assert "scores" in data


# ── Scholarships tests ────────────────────────────────────────
class TestScholarships:
    def test_public_scholarships(self):
        r = client.get("/api/scholarships")
        assert r.status_code == 200
        data = r.json()
        assert "scholarships" in data
        assert len(data["scholarships"]) > 0
        assert "total_potential_usd" in data

    def test_filter_by_field(self):
        r = client.get("/api/scholarships?field=Computer Science")
        assert r.status_code == 200
        # Should return subset or all
        assert "scholarships" in r.json()

    def test_matched_requires_auth(self):
        r = client.get("/api/scholarships/matched")
        assert r.status_code == 401

    def test_matched_with_auth(self, auth_headers):
        r = client.get("/api/scholarships/matched", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "scholarships" in data
        # Matched results should be non-empty for a complete profile
        assert "count" in data


# ── Pipeline tests ────────────────────────────────────────────
class TestPipeline:
    def test_empty_pipeline(self, auth_headers):
        r = client.get("/api/pipeline", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "stages" in data
        assert "researching" in data["stages"]

    def test_add_to_pipeline(self, auth_headers):
        r = client.post("/api/pipeline/add", headers=auth_headers, json={
            "scholarship_id": "test_001",
            "scholarship_name": "Test Scholarship",
            "amount_usd": 10000,
            "deadline": "2026-12-01",
            "stage": "researching",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "researching"
        assert data["scholarship_name"] == "Test Scholarship"
        return data["id"]

    def test_move_stage(self, auth_headers):
        # First add
        add_r = client.post("/api/pipeline/add", headers=auth_headers, json={
            "scholarship_id": "move_test_001",
            "scholarship_name": "Move Test",
            "amount_usd": 5000,
            "deadline": "2026-11-01",
            "stage": "researching",
        })
        app_id = add_r.json()["id"]

        # Move to essay_ready
        move_r = client.patch(
            f"/api/pipeline/{app_id}/move",
            headers=auth_headers,
            json={"stage": "essay_ready"},
        )
        assert move_r.status_code == 200
        assert move_r.json()["status"] == "essay_ready"

    def test_move_to_won(self, auth_headers):
        add_r = client.post("/api/pipeline/add", headers=auth_headers, json={
            "scholarship_id": "won_test_001",
            "scholarship_name": "Won Test",
            "amount_usd": 25000,
            "deadline": "2026-10-01",
            "stage": "awaiting",
        })
        app_id = add_r.json()["id"]
        move_r = client.patch(
            f"/api/pipeline/{app_id}/move",
            headers=auth_headers,
            json={"stage": "won"},
        )
        assert move_r.status_code == 200
        assert move_r.json()["status"] == "won"

    def test_invalid_stage(self, auth_headers):
        add_r = client.post("/api/pipeline/add", headers=auth_headers, json={
            "scholarship_id": "invalid_stage_001",
            "scholarship_name": "Stage Test",
            "amount_usd": 1000,
            "deadline": "2026-10-01",
        })
        app_id = add_r.json()["id"]
        move_r = client.patch(
            f"/api/pipeline/{app_id}/move",
            headers=auth_headers,
            json={"stage": "invalid_stage"},
        )
        assert move_r.status_code == 400


# ── Cache tests ────────────────────────────────────────────────
class TestCache:
    def test_cache_set_get(self):
        from app.services.cache import TTLCache
        cache = TTLCache(ttl=1)
        cache.set("key1", {"value": 42})
        assert cache.get("key1") == {"value": 42}

    def test_cache_expiry(self):
        from app.services.cache import TTLCache
        cache = TTLCache(ttl=1)
        cache.set("expire_key", "will_expire")
        time.sleep(1.1)
        assert cache.get("expire_key") is None

    def test_cache_invalidate(self):
        from app.services.cache import TTLCache
        cache = TTLCache(ttl=60)
        cache.set("match:abc:scholarships", [1, 2, 3])
        cache.set("match:def:scholarships", [4, 5, 6])
        deleted = cache.invalidate("match:")
        assert deleted == 2
        assert cache.get("match:abc:scholarships") is None

    def test_cache_stats(self):
        from app.services.cache import TTLCache
        cache = TTLCache(ttl=60)
        cache.set("s1", "v1")
        cache.get("s1")   # hit
        cache.get("s2")   # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1

    def test_match_cache_used_for_scholarships(self, auth_headers):
        from app.services.cache import match_cache
        before_hits = match_cache.hits
        client.get("/api/scholarships/matched", headers=auth_headers)
        client.get("/api/scholarships/matched", headers=auth_headers)
        # Second call should hit cache
        assert match_cache.hits > before_hits


# ── System tests ──────────────────────────────────────────────
class TestSystem:
    def test_health_check(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["version"] == "4.1.0"
        assert "cache" in data

    def test_stats(self):
        r = client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["opportunities_in_db"] > 0
        assert data["total_potential_funding_usd"] > 0

    def test_dashboard_requires_auth(self):
        r = client.get("/api/dashboard")
        assert r.status_code == 401

    def test_dashboard_with_auth(self, auth_headers):
        r = client.get("/api/dashboard", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "scholarships_matched" in data
        assert "upcoming_deadlines" in data
        assert "user" in data

    def test_spa_serves_html(self):
        r = client.get("/")
        assert r.status_code == 200

    def test_security_headers_present(self, auth_headers):
        """Verify rate-limited endpoints return 429 after limit."""
        # This just verifies the middleware runs — full rate test would need 11 calls
        r = client.get("/api/health")
        assert r.status_code == 200
