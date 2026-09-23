"""Phase 7 — simple in-memory per-IP sliding-window rate limiter for public /track.

Single-process local app => a module-level/instance dict keyed by client IP is
sufficient (no Redis needed). The limiter is constructed per app instance and
stored on ``app.extensions["rate_limiter"]`` so tests get isolated state.

Two independent controls (spec §20):
  * Sliding-window volume cap: at most ``max_per_window`` lookups per IP within
    ``window_secs`` (default 20 / hour).
  * Fail cooldown: after ``fail_threshold`` consecutive failed lookups (success
    resets the counter) impose a ``cooldown_secs`` block for that IP (default
    5 fails -> 90s). Consecutive = a successful lookup clears the fail chain.

Thread-safety: Flask's dev server is threaded, so guard the dicts with a lock.
"""

import threading
import time


class IpLimiter:
    def __init__(self, window_secs=3600, max_per_window=20,
                 fail_threshold=5, cooldown_secs=90):
        self.window_secs = window_secs
        self.max_per_window = max_per_window
        self.fail_threshold = fail_threshold
        self.cooldown_secs = cooldown_secs
        self._lock = threading.Lock()
        self._lookups = {}          # ip -> list[float] lookups (recent)
        self._fails = {}            # ip -> list[float] recent failures
        self._cooldown_until = {}   # ip -> float

    def allowed(self, ip):
        """Return (allowed: bool, reason: str|None).

        reason is 'window' when the hourly volume cap is hit, 'cooldown' while a
        fail-cooldown is active, else None. Also prunes stale entries.
        """
        now = time.time()
        with self._lock:
            self._lookups[ip] = [t for t in self._lookups.get(ip, [])
                                 if now - t < self.window_secs]
            self._fails[ip] = [t for t in self._fails.get(ip, [])
                               if now - t < self.window_secs]
            if self._cooldown_until.get(ip, 0.0) > now:
                return False, "cooldown"
            if len(self._lookups[ip]) >= self.max_per_window:
                return False, "window"
            return True, None

    def record_lookup(self, ip):
        """Register one (post-submission) lookup against the hourly window."""
        now = time.time()
        with self._lock:
            self._lookups.setdefault(ip, [])
            self._lookups[ip] = [t for t in self._lookups[ip]
                                 if now - t < self.window_secs]
            self._lookups[ip].append(now)

    def record_failure(self, ip):
        """Register a failed lookup; returns True when it triggers a cooldown.

        On trigger the fail chain is reset so a fresh set of attempts is possible
        once the cooldown expires.
        """
        now = time.time()
        with self._lock:
            self._fails.setdefault(ip, [])
            self._fails[ip] = [t for t in self._fails[ip]
                               if now - t < self.window_secs]
            self._fails[ip].append(now)
            if len(self._fails[ip]) >= self.fail_threshold:
                self._cooldown_until[ip] = now + self.cooldown_secs
                self._fails[ip] = []
                return True
            return False

    def record_success(self, ip):
        """A valid lookup clears the consecutive-failure counter."""
        with self._lock:
            self._fails.pop(ip, None)