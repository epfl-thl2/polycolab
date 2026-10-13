"""Physical slot bookkeeping shared by native sandbox backends."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path


class SlotPool:
    state_dir: Path

    def initialize_slots(self, capacity: int) -> None:
        self.capacity = capacity
        self.slots: asyncio.Queue[Path] = asyncio.Queue()
        for ordinal in range(capacity):
            self.slots.put_nowait(self.state_dir / "slots" / str(ordinal))
        self.terminated: list[dict[str, object]] = []
        self.states = {ordinal: "AVAILABLE" for ordinal in range(capacity)}
        self.reserved: ContextVar[Path | None] = ContextVar("hosted_slot", default=None)

    @asynccontextmanager
    async def reserve(self) -> AsyncIterator[int | None]:
        try:
            slot = self.slots.get_nowait()
            while self.states[int(slot.name)] == "QUARANTINED":
                slot = self.slots.get_nowait()
        except asyncio.QueueEmpty:
            yield None
            return
        ordinal = int(slot.name)
        self.states[ordinal] = "BUSY"
        token = self.reserved.set(slot)
        try:
            yield ordinal
        finally:
            self.reserved.reset(token)
            if self.states[ordinal] != "QUARANTINED":
                self.states[ordinal] = "AVAILABLE"
                self.slots.put_nowait(slot)

    def acknowledge(self, run_id: str, generation: int) -> None:
        for record in (self.state_dir / "attempts").glob("*.json"):
            data = json.loads(record.read_text())
            if data["run_id"] == run_id and data["generation"] == generation:
                record.unlink()
