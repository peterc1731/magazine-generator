import httpx


def notify_failure(message: str, ntfy_topic: str, client: httpx.Client | None = None) -> None:
    """Pushes a failure notification via ntfy.sh (ARCHITECTURE.md §9). A
    no-op when no topic is configured. Notification delivery failures are
    swallowed — a broken notification channel shouldn't also break the run
    that's trying to report through it.
    """
    if not ntfy_topic:
        return

    owns_client = client is None
    client = client or httpx.Client(timeout=10.0)
    try:
        client.post(f"https://ntfy.sh/{ntfy_topic}", content=message.encode("utf-8"))
    except httpx.HTTPError:
        pass
    finally:
        if owns_client:
            client.close()
