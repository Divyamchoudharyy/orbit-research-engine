
import asyncio
import threading

from src.api.stream_manager import JobStreamManager


def test_publish_from_background_thread():
    async def run_test():
        manager = JobStreamManager()
        queue = manager.subscribe("job-1")

        thread = threading.Thread(
            target=manager.publish,
            args=("job-1", {"event": "research_started"}),
        )
        thread.start()
        thread.join()

        message = await asyncio.wait_for(queue.get(), timeout=2)
        assert message == {"event": "research_started"}

    asyncio.run(run_test())


def test_multiple_subscribers_receive_events():
    async def run_test():
        manager = JobStreamManager()

        queue1 = manager.subscribe("job-1")
        queue2 = manager.subscribe("job-1")

        manager.publish("job-1", {"event": "research_completed"})

        message1 = await asyncio.wait_for(queue1.get(), timeout=2)
        message2 = await asyncio.wait_for(queue2.get(), timeout=2)

        assert message1 == message2
        assert message1["event"] == "research_completed"

    asyncio.run(run_test())


def test_unsubscribe_removes_only_selected_listener():
    async def run_test():
        manager = JobStreamManager()

        queue1 = manager.subscribe("job-1")
        queue2 = manager.subscribe("job-1")

        manager.unsubscribe("job-1", queue1)
        manager.publish("job-1", {"event": "still_connected"})

        message = await asyncio.wait_for(queue2.get(), timeout=2)

        assert message["event"] == "still_connected"
        assert queue1.empty()
        assert len(manager.listeners["job-1"]) == 1

    asyncio.run(run_test())


def test_publish_without_subscribers_does_not_fail():
    manager = JobStreamManager()

    manager.publish("unknown-job", {"event": "test"})

    assert "unknown-job" not in manager.listeners


def test_slow_subscriber_keeps_newest_events():
    async def run_test():
        manager = JobStreamManager(max_queue_size=2)
        queue = manager.subscribe("job-1")

        manager.publish("job-1", {"sequence": 1})
        manager.publish("job-1", {"sequence": 2})
        manager.publish("job-1", {"sequence": 3})

        # Let call_soon_threadsafe callbacks run on this event loop.
        await asyncio.sleep(0)

        first = await queue.get()
        second = await queue.get()

        assert first == {"sequence": 2}
        assert second == {"sequence": 3}

    asyncio.run(run_test())


def test_unsubscribe_unknown_queue_is_safe():
    async def run_test():
        manager = JobStreamManager()
        queue = manager.subscribe("job-1")
        manager.unsubscribe("job-1", asyncio.Queue())
        assert len(manager.listeners["job-1"]) == 1
        manager.unsubscribe("job-1", queue)
        assert "job-1" not in manager.listeners

    asyncio.run(run_test())
