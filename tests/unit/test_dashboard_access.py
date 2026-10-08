from app.dashboard.access import is_valid_operator_token


def test_dashboard_access_requires_a_configured_matching_token() -> None:
    assert is_valid_operator_token("synthetic-operator-token", "synthetic-operator-token")
    assert not is_valid_operator_token("wrong-token", "synthetic-operator-token")
    assert not is_valid_operator_token("synthetic-operator-token", None)
