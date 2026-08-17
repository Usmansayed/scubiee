"""Session job so the engine dies with the logon supervisor.

Windows: a named Job Object with KILL_ON_JOB_CLOSE. The supervisor creates and
joins it; the engine process joins the same job. When the user logs off, the
supervisor task ends, the job closes, and leftover GPU processes are killed.

POSIX: no-op. Idle-stop plus next-logon standby cover leftovers.
"""

from __future__ import annotations

import os
import sys
from typing import Any

JOB_NAME = "Local\\ContextEngineKillJob"


def attach_supervisor_job() -> dict[str, Any]:
    """Create (or open) the kill-on-close job and assign this process."""
    if os.name != "nt":
        return {"ok": True, "skipped": True, "platform": "posix"}
    return _windows_assign(create=True)


def join_supervisor_job() -> dict[str, Any]:
    """Engine child: join the supervisor job if it exists."""
    if os.name != "nt":
        return {"ok": True, "skipped": True, "platform": "posix"}
    return _windows_assign(create=False)


def _windows_assign(*, create: bool) -> dict[str, Any]:
    try:
        import ctypes
        from ctypes import wintypes
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenJobObjectW.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.SetInformationJobObject.restype = wintypes.BOOL

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9
    JOB_OBJECT_ALL_ACCESS = 0x1F001F

    handle = wintypes.HANDLE(0)
    if create:
        handle = kernel32.CreateJobObjectW(None, JOB_NAME)
        if handle:
            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_uint64),
                    ("WriteOperationCount", ctypes.c_uint64),
                    ("OtherOperationCount", ctypes.c_uint64),
                    ("ReadTransferCount", ctypes.c_uint64),
                    ("WriteTransferCount", ctypes.c_uint64),
                    ("OtherTransferCount", ctypes.c_uint64),
                ]

            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            kernel32.SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
    else:
        handle = kernel32.OpenJobObjectW(JOB_OBJECT_ALL_ACCESS, False, JOB_NAME)
        if not handle:
            return {"ok": True, "joined": False, "reason": "job_absent"}

    if not handle:
        err = kernel32.GetLastError()
        return {"ok": False, "error": f"job handle failed winerr={err}"}

    assigned = bool(
        kernel32.AssignProcessToJobObject(
            handle,
            wintypes.HANDLE(kernel32.GetCurrentProcess()),
        )
    )
    if not assigned:
        err = kernel32.GetLastError()
        # 5 = access denied, 87 = already in a job — both mean we keep running.
        if err in {5, 87}:
            return {"ok": True, "joined": False, "reason": f"winerr={err}"}
        return {"ok": False, "error": f"AssignProcessToJobObject winerr={err}"}
    return {"ok": True, "joined": True, "created": create, "job": JOB_NAME}


def attach_engine_on_start() -> None:
    """Best-effort; never block engine startup."""
    try:
        result = join_supervisor_job()
        if not result.get("ok"):
            print(f"[engine] job join note: {result}", file=sys.stderr, flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[engine] job join note: {exc}", file=sys.stderr, flush=True)
