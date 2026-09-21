import httpx
import respx

from pipeline.notifications import notify_failure


def test_notify_failure_noop_when_topic_blank() -> None:
    with respx.mock:
        notify_failure("something broke", ntfy_topic="")
        # no assertion needed beyond "doesn't raise" — respx.mock with no
        # routes registered would error on any unexpected call


@respx.mock
def test_notify_failure_posts_message_to_ntfy() -> None:
    route = respx.post("https://ntfy.sh/my-topic").mock(return_value=httpx.Response(200))

    notify_failure("something broke", ntfy_topic="my-topic")

    assert route.called
    assert route.calls[0].request.content == b"something broke"


@respx.mock
def test_notify_failure_swallows_delivery_errors() -> None:
    respx.post("https://ntfy.sh/my-topic").mock(side_effect=httpx.ConnectError("no route"))

    notify_failure("something broke", ntfy_topic="my-topic")  # should not raise
