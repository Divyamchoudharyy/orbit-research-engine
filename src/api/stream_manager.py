"""Thread-safe, process-local fan-out for Server-Sent Events."""

import asyncio
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StreamListener:
    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop


class JobStreamManager:
    def __init__(self, max_queue_size: int = 500):
        self.listeners: dict[str, list[StreamListener]] = {}
        self.max_queue_size = max_queue_size
        self._lock = threading.RLock()

    def subscribe(self, job_id: str) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue(maxsize=self.max_queue_size)
        listener = StreamListener(queue=queue, loop=loop)

        with self._lock:
            self.listeners.setdefault(job_id, []).append(listener)

        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            listeners = [
                listener
                for listener in self.listeners.get(job_id, [])
                if listener.queue is not queue
            ]
            if listeners:
                self.listeners[job_id] = listeners
            else:
                self.listeners.pop(job_id, None)

    @staticmethod
    def _deliver(queue: asyncio.Queue, message: Any) -> None:
        """Keep the newest events if a slow client falls behind."""
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # Another callback may have filled the queue in the meantime.
            pass

    def publish(self, job_id: str, message: Any) -> None:
        with self._lock:
            listeners = tuple(self.listeners.get(job_id, []))

        stale = []
        for listener in listeners:
            try:
                if listener.loop.is_closed():
                    stale.append(listener)
                    continue
                listener.loop.call_soon_threadsafe(
                    self._deliver,
                    listener.queue,
                    message,
                )
            except RuntimeError:
                stale.append(listener)

        if stale:
            with self._lock:
                current = self.listeners.get(job_id, [])
                remaining = [
                    listener for listener in current
                    if listener not in stale
                ]
                if remaining:
                    self.listeners[job_id] = remaining
                else:
                    self.listeners.pop(job_id, None)


stream_manager = JobStreamManager()
