"""Tests for the ApiKey model."""

from app.models.api_key import ALL_SCOPES, ApiKey, ApiKeyBindings, ApiKeyStatus


class TestApiKeyModel:
    """ApiKey model unit tests."""

    def test_default_values(self) -> None:
        """ApiKey has correct defaults when only required fields are given."""
        key = ApiKey(
            name="test key",
            key_hash="fake_hash",
            key_prefix="af_live_abc",
            owner_user_id="user_01",
        )
        assert key.scopes == []
        assert key.bindings == ApiKeyBindings()
        assert key.rate_limit == 60
        assert key.status == ApiKeyStatus.ACTIVE
        assert key.expires_at is None
        assert key.last_used_at is None
        assert key.id.startswith("apikey_")
        assert key.created_at != ""
        assert key.updated_at != ""

    def test_full_construction(self) -> None:
        """ApiKey can be constructed with all fields."""
        key = ApiKey(
            name="MES Key",
            key_hash="bcrypt_hash_value",
            key_prefix="af_live_xyz",
            owner_user_id="user_02",
            scopes=["agents:invoke", "agents:read"],
            bindings=ApiKeyBindings(agents=["agent_01"], workflows=[]),
            rate_limit=100,
            status=ApiKeyStatus.ACTIVE,
            expires_at="2027-01-01T00:00:00Z",
        )
        assert key.scopes == ["agents:invoke", "agents:read"]
        assert key.bindings.agents == ["agent_01"]
        assert key.bindings.workflows == []
        assert key.rate_limit == 100
        assert key.expires_at == "2027-01-01T00:00:00Z"

    def test_bindings_default_empty_means_all(self) -> None:
        """Empty bindings lists mean no restriction."""
        bindings = ApiKeyBindings()
        assert bindings.agents == []
        assert bindings.workflows == []

    def test_all_scopes_constant(self) -> None:
        """ALL_SCOPES contains all 5 defined scopes."""
        assert len(ALL_SCOPES) == 5
        assert "agents:read" in ALL_SCOPES
        assert "agents:invoke" in ALL_SCOPES
        assert "workflows:read" in ALL_SCOPES
        assert "workflows:invoke" in ALL_SCOPES
        assert "executions:read" in ALL_SCOPES

    def test_status_enum(self) -> None:
        """ApiKeyStatus has active and revoked values."""
        assert ApiKeyStatus.ACTIVE.value == "active"
        assert ApiKeyStatus.REVOKED.value == "revoked"
