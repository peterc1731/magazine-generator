from sqlalchemy.orm import Session

from pipeline.settings_store import (
    DEFAULT_RELEVANCE_THRESHOLD,
    get_interest_profile,
    get_relevance_threshold,
    set_interest_profile,
    set_relevance_threshold,
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
