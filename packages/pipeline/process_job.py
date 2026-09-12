"""Session job so the engine dies with the logon supervisor.

Windows: a named Job Object with KILL_ON_JOB_CLOSE. The supervisor creates and
joins it; the engine process joins the same job. When the user logs off, the
supervisor task ends, the job closes, and leftover GPU processes are killed.

POSIX: no-op. Idle-stop plus next-logon standby cover leftovers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

JOB_NAME = "Local\\ContextEngineCpuJob"
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
DEFAULT_ENGINE_CPU_CAP_PCT = 30.0
DEFAULT_ENGINE_JOB_MEMORY_MB = 800
# Named job objects with KILL_ON_JOB_CLOSE die when the last handle closes.
# ctypes HANDLEs are not auto-closed, but keep them anyway so a future wrapper
# cannot GC-close the supervisor job while the engine is still a member.
_OPEN_JOB_HANDLES: list[Any] = []


def engine_cpu_cap_pct() -> float:
    """Hard CPU cap for the engine job (percent of the machine). Default 30."""
    raw = (os.environ.get("CTX_ENGINE_CPU_CAP_PCT") or "").strip()
    if not raw:
        return DEFAULT_ENGINE_CPU_CAP_PCT
    try:
        return max(1.0, min(100.0, float(raw)))
    except ValueError:
        return DEFAULT_ENGINE_CPU_CAP_PCT


def cpu_rate_for_percent(pct: float) -> int:
    """Windows JOB_OBJECT CpuRate: hundredths of a percent (30 → 3000 of 10000)."""
    return max(1, min(10000, int(round(float(pct) * 100.0))))


def windows_hidden_creationflags() -> int:
    """Spawn without a console flash. DETACHED_PROCESS flashes cmd.exe."""
    if os.name != "nt":
        return 0
    no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW))
    new_group = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return no_window | new_group


def engine_creationflags() -> int:
    """Engine daemon spawn flags.

    Prefer CREATE_NO_WINDOW only. DETACHED_PROCESS is known to flash console
    windows on Windows and often fails with Access Denied from WMI/pythonw
    parents — soft spawn is the default for reliability + no blink.
    """
    if os.name == "nt":
        # Hard detach only when explicitly requested.
        if (os.environ.get("CTX_ENGINE_HARD_DETACH") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW))
            detached = int(getattr(subprocess, "DETACHED_PROCESS", DETACHED_PROCESS))
            new_group = int(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", CREATE_NEW_PROCESS_GROUP)
            )
            return no_window | CREATE_BREAKAWAY_FROM_JOB | detached | new_group
        return windows_hidden_creationflags()
    return 0


def engine_popen_kwargs(*, soft: bool | None = None) -> dict[str, Any]:
    """Spawn the search daemon without console flashes.

    Default is soft (CREATE_NO_WINDOW). Set CTX_ENGINE_HARD_DETACH=1 only when
    you need full DETACHED+BREAKAWAY and accept flash/Access-Denied risk.
    """
    if soft is None:
        hard = (os.environ.get("CTX_ENGINE_HARD_DETACH") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        soft = not hard
    if os.name == "nt":
        if soft:
            return {
                "creationflags": windows_hidden_creationflags(),
                "close_fds": True,
            }
        return {
            "creationflags": engine_creationflags(),
            "close_fds": True,
        }
    kwargs: dict[str, Any] = {"close_fds": True}
    if sys.platform != "darwin":
        kwargs["start_new_session"] = True
    return kwargs


def hidden_popen_kwargs() -> dict[str, Any]:
    """Flags for background python.exe children that must not blink a console."""
    if os.name == "nt":
        return {"creationflags": windows_hidden_creationflags()}
    kwargs: dict[str, Any] = {}
    if sys.platform != "darwin":
        kwargs["start_new_session"] = True
    return kwargs


def attach_mcp_kill_job() -> dict[str, Any]:
    """Per-bridge job: when Cursor kills this process, MCP workers die with it."""
    if os.name != "nt":
        return {"ok": True, "skipped": True, "platform": "posix"}
    name = f"Local\\ScubieeMcpKill-{os.getpid()}"
    return _windows_assign(create=True, job_name=name, kill_on_close=True, cpu_cap=False)


def engine_job_memory_mb() -> int:
    raw = (os.environ.get("CTX_CE_RSS_CAP_MB") or "").strip()
    if raw:
        try:
            return max(256, min(4096, int(raw)))
        except ValueError:
            pass
    return DEFAULT_ENGINE_JOB_MEMORY_MB


def attach_supervisor_job() -> dict[str, Any]:
    """Create (or open) the kill-on-close + 30% CPU job and assign this process."""
    if os.name != "nt":
        return {"ok": True, "skipped": True, "platform": "posix"}
    return _windows_assign(
        create=True,
        job_name=JOB_NAME,
        kill_on_close=True,
        cpu_cap=True,
        memory_mb=0,
    )


def join_supervisor_job() -> dict[str, Any]:
    """Engine child: join the supervisor job if it exists; create it if Cursor spawned us."""
    if os.name != "nt":
        return {"ok": True, "skipped": True, "platform": "posix"}
    opened = _windows_assign(
        create=False,
        job_name=JOB_NAME,
        kill_on_close=True,
        cpu_cap=True,
        memory_mb=0,
    )
    if opened.get("reason") == "job_absent":
        return attach_supervisor_job()
    return opened


def _windows_assign(
    *,
    create: bool,
    job_name: str = JOB_NAME,
    kill_on_close: bool = True,
    cpu_cap: bool = True,
    memory_mb: int = 0,
) -> dict[str, Any]:
    try:
        import ctypes
        from ctypes import wintypes
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenJobObjectW.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.SetInformationJobObject.restype = wintypes.BOOL

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
    JobObjectExtendedLimitInformation = 9
    JobObjectCpuRateControlInformation = 15
    JOB_OBJECT_ALL_ACCESS = 0x1F001F
    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
    JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4

    handle = wintypes.HANDLE(0)
    if create:
        handle = kernel32.CreateJobObjectW(None, job_name)
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
            flags = 0
            if kill_on_close:
                flags |= JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if memory_mb > 0:
                flags |= JOB_OBJECT_LIMIT_JOB_MEMORY
                info.JobMemoryLimit = int(memory_mb) * 1024 * 1024
            # MCP children must stay in this job (Cursor close → kill workers).
            if not kill_on_close:
                flags |= JOB_OBJECT_LIMIT_BREAKAWAY_OK
            info.BasicLimitInformation.LimitFlags = flags
            kernel32.SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if cpu_cap:
                _set_job_cpu_rate(
                    kernel32,
                    handle,
                    JobObjectCpuRateControlInformation,
                    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
                )
    else:
        handle = kernel32.OpenJobObjectW(JOB_OBJECT_ALL_ACCESS, False, job_name)
        if not handle:
            return {"ok": True, "joined": False, "reason": "job_absent"}
        if cpu_cap:
            _set_job_cpu_rate(
                kernel32,
                handle,
                JobObjectCpuRateControlInformation,
                JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP,
            )

    if not handle:
        err = kernel32.GetLastError()
        return {"ok": False, "error": f"job handle failed winerr={err}"}

    assigned = bool(
        kernel32.AssignProcessToJobObject(handle, kernel32.GetCurrentProcess())
    )
    try:
        _OPEN_JOB_HANDLES.append(handle)
    except Exception:  # noqa: BLE001
        pass
    if not assigned:
        err = kernel32.GetLastError()
        # 5 = access denied, 87 = already in a job — both mean we keep running.
        if err in {5, 87}:
            return {"ok": True, "joined": False, "reason": f"winerr={err}"}
        return {"ok": False, "error": f"AssignProcessToJobObject winerr={err}"}
    return {"ok": True, "joined": True, "created": create, "job": job_name}


def _set_job_cpu_rate(
    kernel32: Any,
    handle: Any,
    info_class: int,
    control_flags: int,
) -> None:
    """Best-effort hard CPU cap. Failure must not block engine start."""
    try:
        import ctypes
        from ctypes import wintypes

        class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("ControlFlags", wintypes.DWORD),
                ("CpuRate", wintypes.DWORD),
            ]

        rate = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
        rate.ControlFlags = int(control_flags)
        rate.CpuRate = cpu_rate_for_percent(engine_cpu_cap_pct())
        kernel32.SetInformationJobObject(
            handle,
            info_class,
            ctypes.byref(rate),
            ctypes.sizeof(rate),
        )
    except Exception:
        return


def apply_cpu_affinity_pct(pct: float | None = None) -> dict[str, Any]:
    """Limit this process to ~pct of logical CPUs when JobObject CPU rate cannot attach."""
    try:
        import psutil
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    n = int(os.cpu_count() or 4)
    keep = max(1, int(round(n * (engine_cpu_cap_pct() if pct is None else pct) / 100.0)))
    keep = min(keep, n)
    try:
        psutil.Process().cpu_affinity(list(range(keep)))
        return {"ok": True, "cpus": keep, "of": n}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def attach_engine_on_start() -> None:
    """Best-effort; never block engine startup."""
    try:
        result = join_supervisor_job()
        if not result.get("ok") or not result.get("joined"):
            print(f"[engine] job join note: {result}", file=sys.stderr, flush=True)
            aff = apply_cpu_affinity_pct()
            print(f"[engine] cpu affinity fallback: {aff}", file=sys.stderr, flush=True)
        elif result.get("joined"):
            print(f"[engine] job joined {result.get('job')}", file=sys.stderr, flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[engine] job join note: {exc}", file=sys.stderr, flush=True)
        try:
            apply_cpu_affinity_pct()
        except Exception:
            pass


def background_python() -> str:
    """Interpreter for hidden background spawns (prefer ``pythonw`` on Windows)."""
    from pipeline.daemon import daemon_python

    exe = daemon_python()
    if os.name == "nt":
        candidate = Path(exe).with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return exe


def hidden_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """``subprocess.run`` that never flashes a console on Windows."""
    if os.name == "nt":
        kwargs.setdefault(
            "creationflags",
            int(getattr(subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW)),
        )
    return subprocess.run(cmd, **kwargs)  # noqa: S603


def taskkill_silent(
    pid: int,
    *,
    tree: bool = False,
    force: bool = True,
) -> subprocess.CompletedProcess[Any] | None:
    """Kill a PID on Windows without flashing a console (CREATE_NO_WINDOW).

    ``taskkill.exe`` is a console subsystem binary — spawning it without
    CREATE_NO_WINDOW is a common source of "blinking terminals" when the
    watchdog/MCP restart loop runs often.
    """
    if os.name != "nt":
        return None
    cmd = ["taskkill", "/PID", str(int(pid))]
    if tree:
        cmd.append("/T")
    if force:
        cmd.append("/F")
    return hidden_run(cmd, capture_output=True, check=False, timeout=30)


def windows_wmi_create_process(
    command_line: str,
    *,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Spawn a process whose parent is WMI (not the caller / MCP tree).

    Uses in-process COM (pywin32) — never powershell/cmd (those flash consoles).
    ``ShowWindow=0`` keeps the child hidden. Parent becomes WmiPrvSE so Cursor
    MCP reload cannot reap the supervisor/engine job.
    """
    if os.name != "nt":
        return {"ok": False, "error": "windows_only"}
    cwd_s = str(cwd or Path.cwd())
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
    except ImportError as exc:
        return {"ok": False, "error": f"pywin32_missing:{exc}", "method": "wmi_com"}

    pythoncom.CoInitialize()
    try:
        wmi = win32com.client.GetObject(r"winmgmts:\\.\root\cimv2")
        startup = wmi.Get("Win32_ProcessStartup").SpawnInstance_()
        # SW_HIDE — critical so WMI-created console apps do not blink.
        startup.Properties_("ShowWindow").Value = 0
        process = wmi.Get("Win32_Process")
        in_params = process.Methods_("Create").InParameters.SpawnInstance_()
        in_params.Properties_("CommandLine").Value = command_line
        in_params.Properties_("CurrentDirectory").Value = cwd_s
        in_params.Properties_("ProcessStartupInformation").Value = startup
        out = process.ExecMethod_("Create", in_params)
        rv = int(out.Properties_("ReturnValue").Value)
        pid = int(out.Properties_("ProcessId").Value or 0)
        return {
            "ok": rv == 0 and pid > 0,
            "return_value": rv,
            "pid": pid,
            "method": "wmi_com",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "method": "wmi_com"}
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:  # noqa: BLE001
            pass
