"""AsyncClient.connect must survive the server not being up yet.

voiceChannel's `task run:local` starts the MQ, the agent and the model
server in parallel, so the agent reliably reaches connect() before the
server has bound its port. These tests pin the two properties that makes
tolerable: the right exception is caught, and the client keeps trying.

Written as sync tests driving asyncio.run(), matching test_store.py. This
repo's CI installs only pytest and pydantic, so pytest-asyncio is not
available and an `@pytest.mark.asyncio` test would be collected and fail
rather than run.
"""

import asyncio
import socket

from src.communicate.mq import AsyncClient


def _dual_stack_getaddrinfo():
    """Stand in for macOS resolving `localhost` to both ::1 and 127.0.0.1.

    The Linux runner's localhost is IPv4-only, so without this the
    single-address path runs and the bug under test cannot appear.
    """

    async def getaddrinfo(host, port, *args, **kwargs):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", port, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ]

    return getaddrinfo


def _free_port():
    """A port nothing is listening on, so connecting to it is refused."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_retries_when_localhost_is_dual_stack(monkeypatch):
    """The multi-address failure is a bare OSError, not a ConnectionError.

    asyncio's create_connection does not re-raise the per-address
    ConnectionRefusedError when several addresses were tried; it raises
    OSError("Multiple exceptions: ..."). Catching ConnectionError misses it,
    and connect() gives up after one attempt instead of waiting out a
    server that is merely slow to bind.
    """
    attempts = 0
    real_open = asyncio.open_connection
    real_sleep = asyncio.sleep  # capture before patching, or the stub recurses

    async def counting_open(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return await real_open(*args, **kwargs)

    monkeypatch.setattr(asyncio, "open_connection", counting_open)
    monkeypatch.setattr(asyncio, "sleep", lambda _: real_sleep(0))

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.getaddrinfo = _dual_stack_getaddrinfo()
        try:
            await AsyncClient("localhost", _free_port()).connect()
        except OSError:
            return
        raise AssertionError("connect() should have exhausted its retries")

    asyncio.run(scenario())

    assert attempts > 1, (
        f"connect() gave up after {attempts} attempt(s); the dual-stack "
        "OSError escaped the retry loop"
    )


def test_connects_once_the_server_appears():
    """A server that binds late still gets connected to, not crashed on."""
    port = _free_port()

    async def scenario():
        client = AsyncClient("127.0.0.1", port)

        async def bind_after_the_first_refusal():
            await asyncio.sleep(0.15)
            return await asyncio.start_server(lambda r, w: None, "127.0.0.1", port)

        late = asyncio.create_task(bind_after_the_first_refusal())
        try:
            await client.connect()
            assert client.writer is not None
        finally:
            server = await late
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())
