from sqlalchemy.orm import Session

from app.models import Setting

INTEREST_PROFILE_KEY = "interest_profile"
RELEVANCE_THRESHOLD_KEY = "relevance_threshold"
CRON_EXPRESSION_KEY = "cron_expression"
DEFAULT_RELEVANCE_THRESHOLD = 5.0
DEFAULT_CRON_EXPRESSION = "0 8 * * MON"  # weekly, Monday 08:00


def get_interest_profile(db: Session) -> str:
    setting = db.get(Setting, INTEREST_PROFILE_KEY)
    return setting.value if setting else ""


def set_interest_profile(db: Session, profile_text: str) -> None:
    _upsert(db, INTEREST_PROFILE_KEY, profile_text)


def get_relevance_threshold(db: Session) -> float:
    setting = db.get(Setting, RELEVANCE_THRESHOLD_KEY)
    return float(setting.value) if setting else DEFAULT_RELEVANCE_THRESHOLD


def set_relevance_threshold(db: Session, threshold: float) -> None:
    _upsert(db, RELEVANCE_THRESHOLD_KEY, str(threshold))


def get_cron_expression(db: Session) -> str:
    setting = db.get(Setting, CRON_EXPRESSION_KEY)
    return setting.value if setting else DEFAULT_CRON_EXPRESSION


def set_cron_expression(db: Session, cron_expression: str) -> None:
    _upsert(db, CRON_EXPRESSION_KEY, cron_expression)


def _upsert(db: Session, key: str, value: str) -> None:
    setting = db.get(Setting, key)
    if setting is None:
        db.add(Setting(key=key, value=value))
    else:
        setting.value = value
    db.commit()
