"""System monitor — GPU (NVIDIA-SMI), RAM, disk, process info.

No third-party dependency: RAM comes from ``GlobalMemoryStatusEx`` on
Windows and ``/proc/meminfo`` elsewhere; GPU state parses nvidia-smi CSV
through the OpenShell executor (so even monitoring goes through policy).
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import sys
from typing import Any

from kernel.logging import get_logger
from openshell.executor import ExecResult, SafeExecutor
from tools.registry import Tool, ToolContext, ToolRegistry

logger = get_logger("sysmon")

GPU_QUERY = ("--query-gpu=name,utilization.gpu,memory.used,memory.total,"
             "temperature.gpu,power.draw --format=csv,noheader,nounits")


# ------------------------------------------------------------------ RAM probe
def ram_status() -> dict[str, Any]:
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            total_gb = stat.ullTotalPhys / 1024 ** 3
            avail_gb = stat.ullAvailPhys / 1024 ** 3
            return {"total_gb": round(total_gb, 1),
                    "available_gb": round(avail_gb, 1),
                    "used_pct": int(stat.dwMemoryLoad)}
    try:
        with open("/proc/meminfo", "r", encoding="ascii") as handle:
            info = {}
            for line in handle:
                key, _, value = line.partition(":")
                info[key.strip()] = int(value.strip().split()[0]) * 1024
        total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
        if total:
            return {"total_gb": round(total / 1024 ** 3, 1),
                    "available_gb": round(avail / 1024 ** 3, 1),
                    "used_pct": int((total - avail) * 100 / total)}
    except OSError:
        pass
    return {"available": False}


def gpu_status_sync() -> dict[str, Any]:
    """Synchronous nvidia-smi probe (used by the resource guard)."""
    if shutil.which("nvidia-smi") is None:
        return {"available": False, "detail": "nvidia-smi not on PATH"}
    import subprocess
    try:
        proc = subprocess.run(["nvidia-smi"] + GPU_QUERY.split(),
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "detail": f"nvidia-smi failed: {exc}"}
    return _parse_gpu_csv(proc.stdout, proc.returncode)


async def gpu_status(executor: SafeExecutor | None = None) -> dict[str, Any]:
    """GPU snapshot through the OpenShell executor when available."""
    if executor is not None:
        result: ExecResult = await executor.run("nvidia-smi", GPU_QUERY.split(),
                                                timeout=15)
        if result.ok:
            return _parse_gpu_csv(result.stdout, 0)
        if "not in the allowlist" in (result.blocked_reason or ""):
            return {"available": False, "detail": "nvidia-smi not allowlisted"}
        logger.debug("executor gpu probe failed (%s); falling back to direct",
                     result.blocked_reason or f"exit={result.exit_code}")
    return await _run_sync(gpu_status_sync)


def _parse_gpu_csv(stdout: str, returncode: int) -> dict[str, Any]:
    if returncode != 0:
        return {"available": False, "detail": f"nvidia-smi exit {returncode}"}
    gpus = []
    for line in stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        gpus.append({
            "name": parts[0],
            "utilization_pct": _num(parts[1]),
            "vram_used_mb": _num(parts[2]),
            "vram_total_mb": _num(parts[3]),
            "temperature_c": _num(parts[4]),
            "power_w": _num(parts[5]),
            "vram_free_mb": (None if _num(parts[2]) is None
                             or _num(parts[3]) is None
                             else _num(parts[3]) - _num(parts[2])),
        })
    if not gpus:
        return {"available": False, "detail": "no GPU rows parsed"}
    return {"available": True, "gpus": gpus}


def _num(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


async def _run_sync(fn, *args):
    import asyncio
    return await asyncio.to_thread(fn, *args)


async def system_snapshot(executor: SafeExecutor | None = None) -> dict[str, Any]:
    usage = shutil.disk_usage(os.getcwd())
    gpu = await gpu_status(executor)
    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "ram": ram_status(),
        "disk": {"free_gb": round(usage.free / 1024 ** 3, 1),
                 "total_gb": round(usage.total / 1024 ** 3, 1)},
        "gpu": gpu,
    }


async def vram_guard(executor: SafeExecutor | None, min_free_mb: float) -> bool:
    """Resource guard for the brain: False means 'don't use the local tier'."""
    gpu = await gpu_status(executor)
    if not gpu.get("available"):
        return True  # no GPU info -> don't block local inference
    free = [g.get("vram_free_mb") for g in gpu.get("gpus", [])
            if g.get("vram_free_mb") is not None]
    if not free:
        return True
    return min(free) >= min_free_mb


# ------------------------------------------------------------------- tool API
def register_tools(registry: ToolRegistry, executor: SafeExecutor | None) -> None:
    async def system_status(ctx: ToolContext) -> dict[str, Any]:
        """Snapshot of GPU/VRAM, RAM, disk — no arguments."""
        return await system_snapshot(executor)

    registry.register(Tool(
        name="system_status",
        description=("Report the machine's current status: GPU name/utilization/"
                     "VRAM used+free/temperature/power, system RAM, and disk "
                     "space. Call this to check GPU load before heavy local "
                     "work, or when the user asks about system health."),
        parameters={},
        handler=system_status))
