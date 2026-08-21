"""AsyncClient.connect must survive the server not being up yet.

`task run:local` starts the MQ, the agent and the model server in parallel,
so the agent reliably reaches connect() before the server has bound its
port. These tests pin the two properties that makes tolerable: the right
exception is caught, and the client keeps trying.
"""

import asyncio
import socket

import pytest

from src.communicate.mq import AsyncClient


def _dual_stack_getaddrinfo(port_is_open):
    """Stand in for macOS resolving `localhost` to both ::1 and 127.0.0.1.

    Linux CI runners are IPv4-only for localhost, so without this the
    single-address path runs and the bug under test cannot appear.
    """

    async def getaddrinfo(host, port, *args, **kwargs):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", port, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ]

    return getaddrinfo


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_retries_when_localhost_is_dual_stack(monkeypatch):
    """The multi-address failure is a bare OSError, not a ConnectionError.

    asyncio's create_connection does not re-raise the per-address
    ConnectionRefusedError when several addresses were tried; it raises
    OSError("Multiple exceptions: ..."). Catching ConnectionError misses it
    and connect() gives up after one attempt.
    """
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", _dual_stack_getaddrinfo(False), raising=False)

    attempts = 0
    real_open = asyncio.open_connection

    async def counting_open(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return await real_open(*args, **kwargs)

    monkeypatch.setattr(asyncio, "open_connection", counting_open)
    real_sleep = asyncio.sleep  # capture before patching, or the stub recurses
    monkeypatch.setattr(asyncio, "sleep", lambda _: real_sleep(0))

    client = AsyncClient("localhost", _free_port())
    with pytest.raises(OSError):
        await client.connect()

    assert attempts > 1, (
        f"connect() gave up after {attempts} attempt(s); the dual-stack "
        "OSError escaped the retry loop"
    )


@pytest.mark.asyncio
async def test_connects_once_the_server_appears():
    """A server that binds late still gets connected to, not crashed on."""
    port = _free_port()
    client = AsyncClient("127.0.0.1", port)

    server = None

    async def bind_after_a_couple_of_failures():
        nonlocal server
        await asyncio.sleep(0.15)
        server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", port)

    late = asyncio.create_task(bind_after_a_couple_of_failures())
    try:
        await client.connect()
        assert client.writer is not None
    finally:
        await late
        if server is not None:
            server.close()
            await server.wait_closed()
