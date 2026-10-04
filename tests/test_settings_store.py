from sqlalchemy.orm import Session

from pipeline.settings_store import (
    DEFAULT_CRON_EXPRESSION,
    DEFAULT_RELEVANCE_THRESHOLD,
    get_cron_expression,
    get_interest_profile,
    get_relevance_threshold,
    get_x_tokens,
    set_cron_expression,
    set_interest_profile,
    set_relevance_threshold,
    set_x_tokens,
)


def test_interest_profile_defaults_to_empty_string(db_session: Session) -> None:
    assert get_interest_profile(db_session) == ""


def test_interest_profile_roundtrip(db_session: Session) -> None:
    set_interest_profile(db_session, "AI, cycling, and local politics")

    assert get_interest_profile(db_session) == "AI, cycling, and local politics"


def test_interest_profile_can_be_overwritten(db_session: Session) -> None:
    set_interest_profile(db_session, "first")
    set_interest_profile(db_session, "second")

    assert get_interest_profile(db_session) == "second"


def test_relevance_threshold_defaults(db_session: Session) -> None:
    assert get_relevance_threshold(db_session) == DEFAULT_RELEVANCE_THRESHOLD


def test_relevance_threshold_roundtrip(db_session: Session) -> None:
    set_relevance_threshold(db_session, 7.5)

    assert get_relevance_threshold(db_session) == 7.5


def test_cron_expression_defaults(db_session: Session) -> None:
    assert get_cron_expression(db_session) == DEFAULT_CRON_EXPRESSION


def test_cron_expression_roundtrip(db_session: Session) -> None:
    set_cron_expression(db_session, "0 6 * * *")

    assert get_cron_expression(db_session) == "0 6 * * *"


def test_x_tokens_fall_back_to_env_when_nothing_stored(db_session: Session) -> None:
    assert get_x_tokens(db_session, "env-access", "env-refresh") == ("env-access", "env-refresh")


def test_x_tokens_prefer_stored_pair_descended_from_current_env(db_session: Session) -> None:
    set_x_tokens(db_session, "new-access", "new-refresh", env_refresh_token="env-refresh")

    assert get_x_tokens(db_session, "env-access", "env-refresh") == ("new-access", "new-refresh")


def test_x_tokens_prefer_env_after_oauth_setup_is_rerun(db_session: Session) -> None:
    set_x_tokens(db_session, "new-access", "new-refresh", env_refresh_token="env-refresh")

    tokens = get_x_tokens(db_session, "fresh-access", "fresh-refresh")

    assert tokens == ("fresh-access", "fresh-refresh")
