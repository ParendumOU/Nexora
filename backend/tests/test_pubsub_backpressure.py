"""Bounded per-subscriber pub/sub queues drop oldest under backpressure (#225)."""
import asyncio

from src.core.pubsub import _put_drop_oldest


def test_under_capacity_keeps_all():
    q: asyncio.Queue = asyncio.Queue(maxsize=5)
    for i in range(3):
        _put_drop_oldest(q, {"i": i})
    assert q.qsize() == 3
    assert [q.get_nowait()["i"] for _ in range(3)] == [0, 1, 2]


def test_over_capacity_drops_oldest():
    q: asyncio.Queue = asyncio.Queue(maxsize=3)
    for i in range(6):
        _put_drop_oldest(q, {"i": i})
    # capped at maxsize, and the OLDEST were dropped — newest survive in order
    assert q.qsize() == 3
    assert [q.get_nowait()["i"] for _ in range(3)] == [3, 4, 5]


def test_never_blocks_or_raises_when_full():
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    # repeated puts on a full queue must neither raise nor block
    for i in range(100):
        _put_drop_oldest(q, {"i": i})
    assert q.qsize() == 1
    assert q.get_nowait()["i"] == 99
