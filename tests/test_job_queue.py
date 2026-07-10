"""
Tests for api.job_queue.JobQueue - the in-process job queue that caps how
many simulations run concurrently (default 2, see api/job_queue.py's module
docstring for why concurrency needs a cap at all: unbounded concurrent
simulations on a 1-vCPU box measured ~12% slower in aggregate than running
them one after another).

Pure in-process unit tests, no DB, no FastAPI - each test builds its own
JobQueue() instance (not the module-level singleton) so tests can't leak
state into each other. Tests that assert strict one-at-a-time / exact FIFO
completion order pass max_concurrent=1 explicitly, since those invariants
only hold with a single worker; separate tests cover max_concurrent=2
(today's actual default) directly.
"""
import threading
import time

from api.job_queue import JobQueue


class TestSingleWorkerExecution:

    def test_jobs_execute_in_submission_order(self):
        jq = JobQueue(max_concurrent=1)
        jq.start()
        order = []
        lock = threading.Lock()

        def make_job(n):
            def job():
                with lock:
                    order.append(n)
            return job

        futures = [jq.submit(str(n), make_job(n)) for n in range(5)]
        for f in futures:
            f.result(timeout=5)

        assert order == [0, 1, 2, 3, 4]

    def test_only_one_job_runs_at_a_time(self):
        jq = JobQueue(max_concurrent=1)
        jq.start()
        concurrent_count = []
        active = 0
        lock = threading.Lock()

        def job():
            nonlocal active
            with lock:
                active += 1
                concurrent_count.append(active)
            time.sleep(0.05)
            with lock:
                active -= 1

        futures = [jq.submit(str(n), job) for n in range(4)]
        for f in futures:
            f.result(timeout=5)

        assert max(concurrent_count) == 1

    def test_future_result_matches_return_value(self):
        jq = JobQueue(max_concurrent=1)
        jq.start()

        future = jq.submit("job-1", lambda: 42)

        assert future.result(timeout=5) == 42


class TestBoundedConcurrency:

    def test_at_most_max_concurrent_jobs_run_at_once(self):
        jq = JobQueue(max_concurrent=2)
        jq.start()
        concurrent_count = []
        active = 0
        lock = threading.Lock()

        def job():
            nonlocal active
            with lock:
                active += 1
                concurrent_count.append(active)
            time.sleep(0.05)
            with lock:
                active -= 1

        futures = [jq.submit(str(n), job) for n in range(6)]
        for f in futures:
            f.result(timeout=5)

        assert max(concurrent_count) == 2

    def test_two_jobs_actually_overlap_in_time(self):
        """Not just "never more than 2" - confirm 2 really do run simultaneously
        (i.e. the cap isn't accidentally behaving like max_concurrent=1)."""
        jq = JobQueue(max_concurrent=2)
        jq.start()
        both_running = threading.Event()
        release = threading.Event()
        arrived = []
        lock = threading.Lock()

        def job():
            with lock:
                arrived.append(1)
                if len(arrived) == 2:
                    both_running.set()
            release.wait(timeout=5)

        f1 = jq.submit("a", job)
        f2 = jq.submit("b", job)

        assert both_running.wait(timeout=5), "two jobs never ran concurrently"
        release.set()
        f1.result(timeout=5)
        f2.result(timeout=5)


class TestExceptionIsolation:

    def test_failing_job_does_not_kill_the_worker(self):
        jq = JobQueue(max_concurrent=1)
        jq.start()

        def boom():
            raise ValueError("simulated failure")

        failing_future = jq.submit("bad-job", boom)
        good_future = jq.submit("good-job", lambda: "ok")

        assert isinstance(failing_future.exception(timeout=5), ValueError)
        assert good_future.result(timeout=5) == "ok"


class TestPositionSingleWorker:

    def test_running_job_reports_position_zero_and_queued_jobs_count_up(self):
        jq = JobQueue(max_concurrent=1)
        jq.start()
        release = threading.Event()
        started = threading.Event()

        def blocking_job():
            started.set()
            release.wait(timeout=5)

        first = jq.submit("first", blocking_job)
        started.wait(timeout=5)  # ensure "first" is actually running before checking positions

        second = jq.submit("second", lambda: None)
        third = jq.submit("third", lambda: None)

        assert jq.position("first") == 0
        assert jq.position("second") == 1
        assert jq.position("third") == 2

        release.set()
        first.result(timeout=5)
        second.result(timeout=5)
        third.result(timeout=5)

    def test_position_shifts_down_only_once_the_running_job_finishes(self):
        jq = JobQueue(max_concurrent=1)
        jq.start()
        release = threading.Event()
        started = threading.Event()

        def blocking_job():
            started.set()
            release.wait(timeout=5)

        first = jq.submit("first", blocking_job)
        started.wait(timeout=5)
        second = jq.submit("second", lambda: None)

        # Still first's turn - dequeuing doesn't change anyone's position,
        # only finishing does.
        assert jq.position("first") == 0
        assert jq.position("second") == 1

        release.set()
        first.result(timeout=5)
        second.result(timeout=5)

        # Both finished - no longer tracked.
        assert jq.position("first") is None
        assert jq.position("second") is None

    def test_unknown_job_id_reports_none(self):
        jq = JobQueue(max_concurrent=1)
        jq.start()

        assert jq.position("never-submitted") is None


class TestPositionBoundedConcurrency:

    def test_two_active_slots_both_report_position_zero(self):
        jq = JobQueue(max_concurrent=2)
        jq.start()
        release = threading.Event()
        started = threading.Event()
        started_count = 0
        lock = threading.Lock()

        def blocking_job():
            nonlocal started_count
            with lock:
                started_count += 1
                if started_count == 2:
                    started.set()
            release.wait(timeout=5)

        first = jq.submit("first", blocking_job)
        second = jq.submit("second", blocking_job)
        started.wait(timeout=5)  # both occupy the two active slots

        third = jq.submit("third", lambda: None)

        assert jq.position("first") == 0
        assert jq.position("second") == 0
        assert jq.position("third") == 1

        release.set()
        first.result(timeout=5)
        second.result(timeout=5)
        third.result(timeout=5)
