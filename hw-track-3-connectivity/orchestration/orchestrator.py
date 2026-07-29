"""
Chronis HW-3 — Service Orchestration.

Startup ordering contract: the security/encryption daemon starts FIRST, and
nothing else is allowed to start until it confirms ready. Mirrors the boot
order from HW-2 (power rails -> security chip -> ... ) at the service level.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional


class ServiceState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"


@dataclass
class ServiceDef:
    name: str
    start_fn: Callable[[], bool]          # returns ready-ok
    requires: List[str] = field(default_factory=list)
    critical: bool = False                # failure of a critical service halts startup


# canonical startup order (systemd-style After= dependencies)
SERVICE_ORDER = [
    "encryption",     # ALWAYS first — nothing runs without it
    "storage",
    "motion",
    "heart_rate",
    "camera",
    "audio",
    "state_machine",
    "power",
    "ble",
    "sync",
]


class Orchestrator:
    def __init__(self):
        self._defs: Dict[str, ServiceDef] = {}
        self.states: Dict[str, ServiceState] = {}
        self.start_log: List[str] = []

    def register(self, svc: ServiceDef):
        self._defs[svc.name] = svc
        self.states[svc.name] = ServiceState.STOPPED

    def start_all(self) -> bool:
        """Start services in canonical order, honoring dependencies."""
        for name in SERVICE_ORDER:
            if name not in self._defs:
                continue
            svc = self._defs[name]

            # encryption gate: nothing starts unless encryption is READY
            if name != "encryption" and \
               self.states.get("encryption") != ServiceState.READY:
                self.start_log.append(
                    f"BLOCKED {name}: encryption daemon not ready")
                return False

            # dependency gate
            for dep in svc.requires:
                if self.states.get(dep) != ServiceState.READY:
                    self.start_log.append(f"BLOCKED {name}: requires {dep}")
                    return False

            self.states[name] = ServiceState.STARTING
            ok = svc.start_fn()
            self.states[name] = ServiceState.READY if ok else ServiceState.FAILED
            self.start_log.append(f"{name}: {'ready' if ok else 'FAILED'}")

            if not ok and svc.critical:
                self.start_log.append(f"HALT: critical service {name} failed")
                return False
        return True
