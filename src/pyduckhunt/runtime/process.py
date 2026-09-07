"""Guarded process shell joining non-blocking IRC and game ownership."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from pyduckhunt.identity import rfc1459_casefold
from pyduckhunt.irc.socket_adapter import IRCAdapterResult, IRCSocketAdapter
from pyduckhunt.irc.message import IRCMessage
from pyduckhunt.irc.transport import IRCTransportState
from pyduckhunt.partyline.runtime import PartylineController
from pyduckhunt.runtime.application import BridgeResult, IRCGameBridge
from pyduckhunt.runtime.orchestrator import RuntimeOrchestrator


class ProcessShellState(str, Enum):
    NEW = "new"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProcessShellResult:
    network: IRCAdapterResult
    bridge_results: tuple[BridgeResult, ...]
    state: ProcessShellState
    failure: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.network, IRCAdapterResult):
            raise ValueError("process result requires an IRC adapter result")
        if type(self.bridge_results) is not tuple or any(
            not isinstance(result, BridgeResult) for result in self.bridge_results
        ):
            raise ValueError("process bridge results must be immutable")
        if not isinstance(self.state, ProcessShellState):
            raise ValueError("process result state is invalid")
        if self.failure is not None and self.failure not in (
            "application failed",
            "persistence shutdown failed",
        ):
            raise ValueError("process failure category is invalid")


class ProcessShell:
    """Drive one guarded application loop without signals, daemonizing or services."""

    def __init__(
        self,
        runtime: RuntimeOrchestrator,
        bridge: IRCGameBridge,
        adapter: IRCSocketAdapter,
        *,
        enabled: bool,
        partyline: PartylineController | None = None,
        message_observer: Callable[[IRCMessage], None] | None = None,
        persistence_close_timeout: float | None = 5.0,
    ) -> None:
        if not isinstance(runtime, RuntimeOrchestrator):
            raise ValueError("process shell requires a runtime orchestrator")
        if not isinstance(bridge, IRCGameBridge) or bridge.runtime is not runtime:
            raise ValueError("process shell bridge must own the supplied runtime")
        if not isinstance(adapter, IRCSocketAdapter):
            raise ValueError("process shell requires an IRC socket adapter")
        if type(enabled) is not bool:
            raise ValueError("process activation guard must be a truth value")
        if partyline is not None and (
            not isinstance(partyline, PartylineController)
            or partyline.runtime is not runtime
        ):
            raise ValueError("process partyline must share the supplied runtime")
        if message_observer is not None and not callable(message_observer):
            raise ValueError("process message observer must be callable or none")
        if persistence_close_timeout is not None and (
            isinstance(persistence_close_timeout, bool)
            or not isinstance(persistence_close_timeout, (int, float))
            or persistence_close_timeout < 0
        ):
            raise ValueError("persistence close timeout must be non-negative")
        bridge_channels = {rfc1459_casefold(channel) for channel in bridge.channels}
        transport_channels = {
            rfc1459_casefold(channel)
            for channel in adapter.transport.policy.channels
        }
        if bridge_channels != transport_channels:
            raise ValueError("process bridge and transport channels differ")
        self.runtime = runtime
        self.bridge = bridge
        self.adapter = adapter
        self.enabled = enabled
        self.partyline = partyline
        self.message_observer = message_observer
        self.persistence_close_timeout = persistence_close_timeout
        self._state = ProcessShellState.NEW
        self._failure: str | None = None
        self._last_now_ns: int | None = None
        self._owner_thread = threading.get_ident()

    @property
    def state(self) -> ProcessShellState:
        return self._state

    @property
    def failure(self) -> str | None:
        return self._failure

    def start(self, now_ns: int) -> ProcessShellResult:
        self._ensure_owner()
        self._accept_now(now_ns)
        if self._state is not ProcessShellState.NEW:
            raise RuntimeError("process shell can only start once")
        if not self.enabled:
            raise RuntimeError("process activation is disabled by configuration")
        try:
            if self.partyline is not None:
                self.partyline.start(now_ns)
            network = self.adapter.start(now_ns)
        except Exception:
            if self.partyline is not None:
                self.partyline.close("start-failure")
            raise
        self._state = ProcessShellState.RUNNING
        return self._result(network, ())

    def poll(self, now_ns: int) -> ProcessShellResult:
        self._ensure_owner()
        self._accept_now(now_ns)
        if self._state not in (
            ProcessShellState.RUNNING,
            ProcessShellState.STOPPING,
        ):
            raise RuntimeError("process shell cannot poll from its current state")

        network = self.adapter.poll(now_ns)
        handled: list[BridgeResult] = []
        partyline_work = False
        if self._state is ProcessShellState.RUNNING:
            try:
                if self.partyline is not None:
                    partyline_work = self.partyline.poll(now_ns)
                for message in network.messages:
                    if self.message_observer is not None:
                        self.message_observer(message)
                    if message.command not in ("PRIVMSG", "NOTICE", "TAGMSG"):
                        continue
                    consumed = (
                        False
                        if self.partyline is None
                        else self.partyline.handle_irc(
                            now_ns,
                            message,
                            self.adapter.transport.nickname,
                        )
                    )
                    partyline_work = partyline_work or consumed
                    if not consumed:
                        handled.append(self.bridge.handle(now_ns, message))
            except Exception:
                self._failure = "application failed"
                self._state = ProcessShellState.STOPPING
                if self.partyline is not None:
                    self.partyline.close("application-failure")
                network = self.adapter.stop(now_ns, "application failure")

        if self._state is ProcessShellState.RUNNING and (handled or partyline_work):
            flushed = self.adapter.flush(now_ns)
            network = IRCAdapterResult(
                network.messages,
                flushed.state,
                flushed.connected,
                flushed.pending_output_bytes,
                flushed.failure,
            )

        if network.state is IRCTransportState.STOPPED:
            self._finish_runtime()
        return self._result(network, tuple(handled))

    def stop(self, now_ns: int, reason: str = "shutdown") -> ProcessShellResult:
        self._ensure_owner()
        self._accept_now(now_ns)
        if self._state is ProcessShellState.NEW:
            network = self.adapter.stop(now_ns, reason)
            self._finish_runtime()
            return self._result(network, ())
        if self._state is ProcessShellState.RUNNING:
            self._state = ProcessShellState.STOPPING
            if self.partyline is not None:
                self.partyline.close(reason)
        if self._state is ProcessShellState.STOPPING:
            network = self.adapter.stop(now_ns, reason)
            if network.state is IRCTransportState.STOPPED:
                self._finish_runtime()
            return self._result(network, ())
        raise RuntimeError("process shell cannot stop from its current state")

    def _finish_runtime(self) -> None:
        if self._state in (ProcessShellState.STOPPED, ProcessShellState.FAILED):
            return
        if self.partyline is not None:
            self.partyline.close("runtime-stop")
        try:
            self.runtime.close(self.persistence_close_timeout)
        except Exception:
            self._failure = "persistence shutdown failed"
            self._state = ProcessShellState.FAILED
            return
        self._state = ProcessShellState.STOPPED

    def _result(
        self,
        network: IRCAdapterResult,
        bridge_results: tuple[BridgeResult, ...],
    ) -> ProcessShellResult:
        return ProcessShellResult(
            network,
            bridge_results,
            self._state,
            self._failure,
        )

    def _accept_now(self, now_ns: int) -> None:
        if type(now_ns) is not int or now_ns < 0:
            raise ValueError("process shell time must be a non-negative integer")
        if self._last_now_ns is not None and now_ns < self._last_now_ns:
            raise ValueError("process shell clock cannot move backwards")
        self._last_now_ns = now_ns

    def _ensure_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("process shell is owned by one event-loop thread")
