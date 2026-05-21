import asyncio
from dataclasses import dataclass
from typing import Literal, Tuple

import psutil


@dataclass(frozen=True)
class GovernorConfig:
    pause_cpu: float = 85.0
    pause_mem: float = 85.0
    stop_cpu: float = 95.0
    stop_mem: float = 95.0
    resume_cpu: float = 80.0
    resume_mem: float = 80.0
    poll_interval_s: float = 0.5
    quality_cpu_high: float = 60.0
    quality_mem_high: float = 60.0
    quality_cpu_mid: float = 80.0
    quality_mem_mid: float = 80.0


class ResourceOverloaded(Exception):
    pass


QualityMode = Literal["high", "mid", "low"]


class ResourceGovernor:
    def __init__(self, config: GovernorConfig | None = None):
        self.config = config or GovernorConfig()
        try:
            psutil.cpu_percent(interval=0.1)
        except Exception:
            pass

    def get_usage(self) -> Tuple[float, float]:
        try:
            cpu = float(psutil.cpu_percent(interval=None))
        except Exception:
            cpu = float(self.config.pause_cpu)
        try:
            mem = float(psutil.virtual_memory().percent)
        except Exception:
            mem = float(self.config.pause_mem)
        return cpu, mem

    def quality(self) -> QualityMode:
        cpu, mem = self.get_usage()
        if cpu <= self.config.quality_cpu_high and mem <= self.config.quality_mem_high:
            return "high"
        if cpu <= self.config.quality_cpu_mid and mem <= self.config.quality_mem_mid:
            return "mid"
        return "low"

    def check_or_raise(self) -> None:
        cpu, mem = self.get_usage()
        if cpu >= self.config.stop_cpu or mem >= self.config.stop_mem:
            raise ResourceOverloaded(f"Resource stop triggered (cpu={cpu:.1f}%, mem={mem:.1f}%)")

    async def wait_until_resume(self) -> None:
        while True:
            cpu, mem = self.get_usage()
            if cpu <= self.config.resume_cpu and mem <= self.config.resume_mem:
                return
            await asyncio.sleep(self.config.poll_interval_s)

    async def wait_for_capacity(self, max_wait_s: float = 8.0) -> None:
        waited = 0.0
        while True:
            cpu, mem = self.get_usage()
            if cpu >= self.config.stop_cpu or mem >= self.config.stop_mem:
                # Don't block forever: long "stop" periods were stalling all workers.
                if waited >= max_wait_s:
                    return
                await asyncio.sleep(self.config.poll_interval_s)
                waited += self.config.poll_interval_s
                continue
            if cpu >= self.config.pause_cpu or mem >= self.config.pause_mem:
                if waited >= max_wait_s:
                    return
                await asyncio.sleep(self.config.poll_interval_s)
                waited += self.config.poll_interval_s
                continue
            return

