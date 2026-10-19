# -*- coding: utf-8 -*-
"""Regression tests for UDP seat routing, with simulated time and real loopback sockets.

    python source\test_relay_routing.py

No cabinet, account, live relay or external network is used.
"""
import contextlib
import io
import os
import socket
import subprocess
import sys
import threading
import time
import types
import unittest
from unittest import mock

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
from server import relay as R  # noqa: E402

OLD = ("192.0.2.1", 10001)
ACTIVE = ("192.0.2.1", 20001)
OPPONENT = ("198.51.100.2", 20002)
NEW_IP = ("203.0.113.3", 30001)


def hello(seat):
    return R.MAGIC + b"R" + bytes([seat])


def packet(to_seat, from_seat, payload=b"inputs"):
    return R.MAGIC + b"D" + bytes([to_seat, from_seat]) + payload


class Clock:
    def __init__(self):
        self.now, self.wall_offset = 100.0, 1700000000.0

    def monotonic(self):
        return self.now

    def wall(self):
        return self.now + self.wall_offset


class ScriptedSocket:
    """recvfrom advances time, like a blocking socket; wall time can change independently."""
    def __init__(self, clock, events, fail_send=False):
        self.clock, self.events = clock, iter(events)
        self.sent, self.fail_send = [], fail_send

    def bind(self, addr):
        self.bound = addr

    def settimeout(self, timeout):
        self.timeout = timeout

    def recvfrom(self, size):
        try:
            event = next(self.events)
        except StopIteration:
            self.clock.now += 100.0
            raise socket.timeout()
        self.clock.now, data, addr = event[:3]
        if len(event) > 3:
            self.clock.wall_offset += event[3]
        return data[:size], addr

    def sendto(self, data, addr):
        if self.fail_send and data.startswith(R.MAGIC + b"F"):
            raise OSError(10065, "simulated unreachable destination")
        self.sent.append((data, addr))
        return len(data)

    def close(self):
        pass


def exercise(events, fail_send=False, capture_logs=True, wait_for_sink=None):
    clock, logs = Clock(), []
    sock = ScriptedSocket(clock, events, fail_send)
    if wait_for_sink is not None:
        receive = sock.recvfrom

        def after_sink_blocks(size):
            if not wait_for_sink.wait(2):
                raise AssertionError("simulated log sink never started")
            return receive(size)

        sock.recvfrom = after_sink_blocks
    fake_time = types.SimpleNamespace(monotonic=clock.monotonic, time=clock.wall)
    log_patch = mock.patch.object(R, "log", logs.append) if capture_logs else contextlib.nullcontext()
    with mock.patch.object(R, "time", fake_time), log_patch, \
            mock.patch.object(R.socket, "socket", return_value=sock):
        result = R.main(["60"])
    return result, sock.sent, logs


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.seats, self.rejects = {}, {}
        self.quiet = mock.patch.object(R, "log")
        self.quiet.start()
        self.addCleanup(self.quiet.stop)

    def claim(self, addr, now, data=False):
        return R.claim(self.seats, 1, addr, now, self.rejects, data=data)

    def test_old_hello_cannot_redirect_receiving_socket_after_data_pause(self):
        self.claim(OLD, 100.0)
        self.claim(ACTIVE, 100.1, data=True)
        self.claim(ACTIVE, 105.1)  # active socket remains alive while only receiving
        self.claim(OLD, 106.2)     # legacy panels keep historical sockets registered
        self.assertEqual(self.seats[1][0], ACTIVE)
        self.assertEqual(self.seats[1][1], 105.1)

    def test_ignored_hello_does_not_extend_an_abandoned_owners_lifetime(self):
        self.claim(ACTIVE, 100.0, data=True)
        self.claim(OLD, 104.0)
        self.assertTrue(self.claim(NEW_IP, 100.0 + R.FORGET + 0.01))
        self.assertEqual(self.seats[1][0], NEW_IP)

    def test_current_socket_hello_keeps_data_route_during_long_receive_only_phase(self):
        self.claim(ACTIVE, 100.0, data=True)
        for tick in (104.0, 109.0, 129.0, 150.0):
            self.claim(ACTIVE, tick)
            self.claim(OLD, tick + 0.1)
            self.assertEqual(self.seats[1][0], ACTIVE)
            self.assertFalse(self.claim(NEW_IP, tick + 0.2, data=True))

    def test_same_ip_data_migrates_immediately_even_when_hello_is_held(self):
        self.claim(OLD, 100.0, data=True)
        self.claim(ACTIVE, 101.0)
        self.assertEqual(self.seats[1][0], OLD)
        self.assertTrue(self.claim(ACTIVE, 101.01, data=True))
        self.assertEqual(self.seats[1][0], ACTIVE)
        self.assertFalse(self.rejects)

    def test_public_ip_takeover_boundary_and_expiry(self):
        self.claim(ACTIVE, 100.0, data=True)
        self.assertFalse(self.claim(NEW_IP, 100.0 + R.FORGET, data=True))
        self.assertEqual(self.seats[1][0], ACTIVE)
        self.assertTrue(self.claim(NEW_IP, 100.0 + R.FORGET + 0.01, data=True))
        self.assertEqual(self.seats[1][0], NEW_IP)

    def test_hello_can_recover_expired_route_but_cannot_pull_live_data_route(self):
        self.claim(ACTIVE, 100.0, data=True)
        self.claim(OLD, 100.0 + R.FORGET + 0.01)
        self.assertEqual(self.seats[1][0], OLD)


class MainLoopTests(unittest.TestCase):
    def test_forwarding_keeps_current_destination_after_stale_hello(self):
        _, sent, _ = exercise([
            (100.0, hello(1), OLD),
            (100.1, packet(2, 1), ACTIVE),
            (100.2, hello(2), OPPONENT),
            (100.3, packet(1, 2, b"before-pause"), OPPONENT),
            (105.1, hello(1), ACTIVE),
            (106.2, hello(1), OLD),
            (106.3, packet(1, 2, b"after-pause"), OPPONENT),
        ])
        forwarded = [(data[10:], addr) for data, addr in sent if data.startswith(R.MAGIC + b"F")]
        self.assertEqual(forwarded, [(b"before-pause", ACTIVE), (b"after-pause", ACTIVE)])

    def test_receive_time_is_sampled_after_blocking_receive(self):
        _, sent, _ = exercise([
            (100.0, hello(2), OPPONENT),
            (100.0 + R.FORGET - 0.5, hello(1), ACTIVE),
            (100.0 + R.FORGET + 0.01, packet(2, 1), ACTIVE),
        ])
        self.assertEqual(sent, [], "a target that expired while recvfrom waited is not forwarded to")

    def test_wall_clock_jump_does_not_end_relay_or_expire_live_ownership(self):
        _, sent, _ = exercise([
            (100.0, hello(1), ACTIVE),
            (100.1, hello(2), OPPONENT),
            (101.0, packet(1, 2, b"before-jump"), OPPONENT, 3600.0),
            (102.0, packet(1, 2, b"after-jump"), OPPONENT),
        ])
        self.assertEqual([data[10:] for data, _ in sent], [b"before-jump", b"after-jump"])

    def test_directional_silence_is_logged_once_then_resumption_is_timed(self):
        _, _, logs = exercise([
            (100.0, hello(1), ACTIVE),
            (100.1, hello(2), OPPONENT),
            (100.2, packet(1, 2), OPPONENT),
            (101.3, hello(2), OPPONENT),
            (102.3, hello(2), OPPONENT),
            (103.2, packet(1, 2), OPPONENT),
        ])
        quiet = [line for line in logs if "traffic 2->1: no data received" in line]
        resumed = [line for line in logs if "traffic 2->1: data resumed" in line]
        self.assertEqual(len(quiet), 1, logs)
        self.assertEqual(len(resumed), 1, logs)
        self.assertIn("3.000 s", resumed[0])

    def test_send_failures_are_not_reported_as_unregistered_destinations(self):
        _, _, logs = exercise([
            (100.0, hello(1), ACTIVE),
            (100.1, hello(2), OPPONENT),
            (100.2, packet(1, 2), OPPONENT),
            (100.3, packet(1, 2), OPPONENT),
            (131.0, hello(2), OPPONENT),
        ], fail_send=True)
        self.assertEqual(len([line for line in logs if "send failed" in line]), 1, logs)
        summary = [line for line in logs if line.startswith("last 30 s:")]
        self.assertEqual(len(summary), 1, logs)
        self.assertIn("send errors: ->1 2", summary[0])
        self.assertNotIn("seat not known", summary[0])


class LoggerTests(unittest.TestCase):
    def test_full_queue_is_bounded_nonblocking_and_reports_dropped_events(self):
        entered, release = threading.Event(), threading.Event()
        lines = []

        def stalled_sink(line, path):
            entered.set()
            release.wait(3)
            lines.append(line)

        with mock.patch.object(R, "_write_log", stalled_sink):
            logger = R._AsyncLog(None, capacity=2)
            try:
                logger.submit("first")
                self.assertTrue(entered.wait(1))
                started = time.monotonic()
                for number in range(1000):
                    logger.submit("queued %d" % number)
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertLessEqual(logger.items.qsize(), 2)
                self.assertEqual(logger.dropped, 998)
                started = time.monotonic()
                self.assertFalse(logger.stop(timeout=0.03))
                self.assertLess(time.monotonic() - started, 0.5, "shutdown must not wait for a stuck writer")
            finally:
                release.set()
                self.assertTrue(logger.stop(timeout=1))
        self.assertTrue(any("998 events omitted" in line for line in lines), lines)

    def test_clean_stop_drains_normal_logs_in_order(self):
        lines = []
        with mock.patch.object(R, "_write_log", lambda line, path: lines.append((line, path))):
            logger = R._AsyncLog("diagnostic.log")
            for line in ("first", "second", "last"):
                logger.submit(line)
            self.assertTrue(logger.stop(timeout=1))
        self.assertEqual(lines, [(line, "diagnostic.log") for line in ("first", "second", "last")])
        self.assertEqual(logger.dropped, 0)

    def test_blocked_log_sink_does_not_block_main_packet_forwarding(self):
        entered, release = threading.Event(), threading.Event()
        loggers = []
        logger_type = R._AsyncLog

        def stalled_sink(line, path):
            entered.set()
            release.wait(4)

        def remember_logger(path):
            logger = logger_type(path)
            loggers.append(logger)
            return logger

        with mock.patch.object(R, "_write_log", stalled_sink), mock.patch.object(R, "_AsyncLog", remember_logger):
            try:
                started = time.monotonic()
                result, sent, _ = exercise([
                    (100.0, hello(1), ACTIVE),
                    (100.1, hello(2), OPPONENT),
                    (100.2, packet(1, 2, b"forward-despite-stuck-log"), OPPONENT),
                    (100.3, packet(2, 1, b"return-despite-stuck-log"), ACTIVE),
                ], capture_logs=False, wait_for_sink=entered)
                self.assertEqual(result, 0)
                self.assertEqual([data[10:] for data, _ in sent], [
                    b"forward-despite-stuck-log", b"return-despite-stuck-log"])
                self.assertLess(time.monotonic() - started, 1.8, "only the bounded shutdown join may wait")
                self.assertTrue(loggers[0].worker.is_alive(), "sink remains stalled throughout forwarding")
            finally:
                release.set()
                for logger in loggers:
                    self.assertTrue(logger.stop(timeout=1))


class LoopbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clients = []
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        env = dict(os.environ, WCCF_RELAY_PORT=str(port))
        cls.target = ("127.0.0.1", port)
        cls.process = subprocess.Popen(
            [sys.executable, "-I", os.path.join(KIT, "code", "server", "relay.py"), "30"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        cls.a = cls.client()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            cls.a.sendto(R.MAGIC + b"Pstart", cls.target)
            try:
                if cls.a.recvfrom(4200)[0] == R.MAGIC + b"Qstart":
                    return
            except OSError:  # Windows may return an ICMP reset before the child has bound.
                if cls.process.poll() is not None:
                    break
        cls.tearDownClass()
        raise AssertionError("local relay failed to start")

    @classmethod
    def client(cls):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        s.settimeout(0.2)
        cls.clients.append(s)
        return s

    @classmethod
    def tearDownClass(cls):
        for s in cls.clients:
            s.close()
        if cls.process.poll() is None:
            cls.process.terminate()
        cls.process.communicate(timeout=4)

    def test_real_udp_forwarding_migration_and_ping(self):
        a, b, moved = self.a, self.client(), self.client()
        a.sendto(hello(5), self.target)
        b.sendto(packet(5, 6, b"hello"), self.target)
        received, _ = a.recvfrom(4200)
        self.assertEqual(received, R.MAGIC + b"F\x06" + socket.inet_aton("127.0.0.1") + b"hello")

        # D from a new port immediately selects that port, including maximum panel payloads.
        moved.sendto(packet(6, 5, bytes(range(256)) * 16), self.target)
        self.assertEqual(b.recvfrom(4200)[0][10:], bytes(range(256)) * 16)
        a.sendto(hello(5), self.target)  # historical socket cannot pull the new route
        b.sendto(packet(5, 6, b"migrated"), self.target)
        self.assertEqual(moved.recvfrom(4200)[0][10:], b"migrated")
        with self.assertRaises(socket.timeout):
            a.recvfrom(4200)

        moved.sendto(R.MAGIC + b"Pindependent", self.target)
        self.assertEqual(moved.recvfrom(4200)[0], R.MAGIC + b"Qindependent")
        b.sendto(packet(8, 6, b"unknown-target"), self.target)
        b.sendto(R.MAGIC + b"Pstill-running", self.target)
        self.assertEqual(b.recvfrom(4200)[0], R.MAGIC + b"Qstill-running")

    def test_real_udp_stale_socket_after_more_than_five_seconds(self):
        old, active, opponent = self.client(), self.client(), self.client()
        old.sendto(hello(1), self.target)
        opponent.sendto(hello(2), self.target)
        active.sendto(packet(2, 1, b"choose-active"), self.target)
        self.assertEqual(opponent.recvfrom(4200)[0][10:], b"choose-active")

        # This was HELLO_HOLD=5: after it elapsed a historical socket stole the return route.
        time.sleep(5.1)
        active.sendto(hello(1), self.target)
        old.sendto(hello(1), self.target)
        opponent.sendto(packet(1, 2, b"receive-after-pause"), self.target)
        self.assertEqual(active.recvfrom(4200)[0][10:], b"receive-after-pause")
        with self.assertRaises(socket.timeout):
            old.recvfrom(4200)


if __name__ == "__main__":
    with contextlib.redirect_stdout(io.StringIO()):
        suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("relay routing: %d tests, %d failures, %d errors" % (
        result.testsRun, len(result.failures), len(result.errors)))
    sys.exit(0 if result.wasSuccessful() else 1)
