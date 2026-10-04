from sqlalchemy.orm import Session

from app.models import Setting

INTEREST_PROFILE_KEY = "interest_profile"
RELEVANCE_THRESHOLD_KEY = "relevance_threshold"
CRON_EXPRESSION_KEY = "cron_expression"
X_ACCESS_TOKEN_KEY = "x_access_token"
X_REFRESH_TOKEN_KEY = "x_refresh_token"
# The X_REFRESH_TOKEN env value the stored pair descends from — lets
# get_x_tokens notice a fresh scripts/x_oauth_setup.py run and prefer it.
X_TOKEN_SEED_KEY = "x_refresh_token_seed"
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


def get_x_tokens(
    db: Session, env_access_token: str, env_refresh_token: str
) -> tuple[str, str]:
    """Returns the (access, refresh) token pair to use for X: the most
    recently refreshed pair stored in the DB, unless the env tokens have
    been replaced since (a re-run of scripts/x_oauth_setup.py), in which
    case the env pair wins."""
    seed = db.get(Setting, X_TOKEN_SEED_KEY)
    access = db.get(Setting, X_ACCESS_TOKEN_KEY)
    refresh = db.get(Setting, X_REFRESH_TOKEN_KEY)
    if seed is None or access is None or seed.value != env_refresh_token:
        return env_access_token, env_refresh_token
    return access.value, refresh.value if refresh else ""


def set_x_tokens(
    db: Session, access_token: str, refresh_token: str, env_refresh_token: str
) -> None:
    _upsert(db, X_ACCESS_TOKEN_KEY, access_token)
    _upsert(db, X_REFRESH_TOKEN_KEY, refresh_token)
    _upsert(db, X_TOKEN_SEED_KEY, env_refresh_token)


def _upsert(db: Session, key: str, value: str) -> None:
    setting = db.get(Setting, key)
    if setting is None:
        db.add(Setting(key=key, value=value))
    else:
        setting.value = value
    db.commit()
