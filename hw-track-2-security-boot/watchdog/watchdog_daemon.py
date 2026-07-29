"""
Watchdog daemon (Day 3).
Monitors liveness of all daemons. Special case per spec:
  encryption daemon failure → SYSTEM HALT (everything depends on it — Rule 1).
  any other daemon failure → isolated restart of that daemon only.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional


class DaemonStatus(Enum):
    ALIVE = "alive"
    DEAD = "dead"
    UNAVAILABLE = "unavailable"  # Rule 3: explicit, never a zero


class WatchdogAction(Enum):
    HALT = "HALT"
    RESTART = "RESTART"
    OK = "OK"


@dataclass
class WatchdogEvent:
    daemon: str
    action: WatchdogAction
    reason: str


class WatchdogDaemon:
    """
    Polls registered daemons for liveness.
    encryption_daemon failure → HALT immediately (Rule 1 — everything depends on it).
    All other failures → isolated restart, system continues.
    """

    ENCRYPTION_DAEMON = "encryption_daemon"

    def __init__(
        self,
        halt_fn: Callable[[str], None],
        restart_fn: Callable[[str], None],
        log_fn: Callable[[str], None],
    ):
        self._halt_fn = halt_fn
        self._restart_fn = restart_fn
        self._log_fn = log_fn
        self._daemons: Dict[str, Callable[[], DaemonStatus]] = {}
        self._events: List[WatchdogEvent] = []
        self._system_halted = False

    def register(self, name: str, liveness_check: Callable[[], DaemonStatus]) -> None:
        self._daemons[name] = liveness_check

    def check_all(self) -> List[WatchdogEvent]:
        """Run one liveness sweep. Returns events from this sweep only."""
        sweep_events: List[WatchdogEvent] = []

        for name, check in self._daemons.items():
            status = check()
            if status == DaemonStatus.ALIVE:
                continue

            event = self._handle_failure(name, status)
            sweep_events.append(event)
            self._events.append(event)

            if event.action == WatchdogAction.HALT:
                self._system_halted = True
                return sweep_events  # stop sweep immediately

        return sweep_events

    def _handle_failure(self, name: str, status: DaemonStatus) -> WatchdogEvent:
        reason = f"{name} reported {status.value}"

        if name == self.ENCRYPTION_DAEMON:
            # Special case: encryption daemon down → HALT everything.
            # Rule 1: no other daemon can safely operate without encryption.
            msg = f"SYSTEM HALT: {reason} — encryption daemon failure is unrecoverable."
            self._halt_fn(msg)
            self._log_fn(msg)
            return WatchdogEvent(daemon=name, action=WatchdogAction.HALT, reason=msg)

        # All other daemons: isolated restart, rest of system unaffected.
        msg = f"Restarting {name}: {reason}"
        self._restart_fn(name)
        self._log_fn(msg)
        return WatchdogEvent(daemon=name, action=WatchdogAction.RESTART, reason=msg)

    @property
    def system_halted(self) -> bool:
        return self._system_halted

    @property
    def all_events(self) -> List[WatchdogEvent]:
        return list(self._events)
