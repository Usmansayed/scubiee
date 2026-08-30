"""Hardware-level filesystem identity tracking across moves/renames.

Tracks permanent OS filesystem references (Windows NTFS FileIndex, macOS APFS/HFS+
volume_id:inode) so projects can be instantly located when moved/renamed with zero
disk traversal.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Any


def _darwin_getpath(fd: int) -> str | None:
    """Return the absolute path for an open file descriptor (macOS ``F_GETPATH``)."""
    try:
        import fcntl
    except ImportError:
        return None
    if not hasattr(fcntl, "F_GETPATH"):
        return None
    try:
        # Python's fcntl module requires a bytes buffer (<=1024 on 3.10); ctypes
        # create_string_buffer does not work reliably for F_GETPATH on Darwin.
        raw = fcntl.fcntl(fd, fcntl.F_GETPATH, b"\x00" * 1024)
    except OSError:
        return None
    if not raw:
        return None
    text = raw.split(b"\x00", 1)[0].decode("utf-8", errors="surrogateescape").strip()
    return text or None


def get_filesystem_id(path: Path | str) -> dict[str, Any] | None:
    """Capture permanent OS hardware filesystem identifier for a directory."""
    p = Path(path).resolve()
    if not p.exists():
        return None

    if os.name == "nt":
        try:
            from ctypes import wintypes

            FILE_READ_ATTRIBUTES = 0x80
            OPEN_EXISTING = 3
            FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

            class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("dwFileAttributes", wintypes.DWORD),
                    ("ftCreationTime", wintypes.FILETIME),
                    ("ftLastAccessTime", wintypes.FILETIME),
                    ("ftLastWriteTime", wintypes.FILETIME),
                    ("dwVolumeSerialNumber", wintypes.DWORD),
                    ("nFileSizeHigh", wintypes.DWORD),
                    ("nFileSizeLow", wintypes.DWORD),
                    ("nNumberOfLinks", wintypes.DWORD),
                    ("nFileIndexHigh", wintypes.DWORD),
                    ("nFileIndexLow", wintypes.DWORD),
                ]

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateFileW(
                str(p),
                FILE_READ_ATTRIBUTES,
                7,  # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
                None,
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS,
                None,
            )
            if handle == -1 or handle == 0:
                return None
            info = BY_HANDLE_FILE_INFORMATION()
            ok = kernel32.GetFileInformationByHandle(handle, ctypes.byref(info))
            kernel32.CloseHandle(handle)
            if not ok:
                return None

            file_id = (info.nFileIndexHigh << 32) | info.nFileIndexLow
            drive = p.drive or "C:"
            vol_path = f"\\\\.\\{drive}"
            return {
                "os": "nt",
                "vol_serial": int(info.dwVolumeSerialNumber),
                "file_id": int(file_id),
                "vol_path": vol_path,
            }
        except Exception:  # noqa: BLE001
            return None

    elif sys.platform == "darwin" or os.name == "posix":
        try:
            stat_info = p.stat()
            return {
                "os": sys.platform,
                "dev": int(stat_info.st_dev),
                "ino": int(stat_info.st_ino),
            }
        except Exception:  # noqa: BLE001
            return None

    return None


def resolve_moved_path(fs_id: dict[str, Any]) -> Path | None:
    """Resolve the current path of a moved folder using its hardware filesystem ID."""
    if not isinstance(fs_id, dict):
        return None

    target_os = fs_id.get("os")

    if target_os == "nt" and os.name == "nt":
        try:
            from ctypes import wintypes

            FILE_READ_ATTRIBUTES = 0x80
            OPEN_EXISTING = 3
            FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

            class FILE_ID_DESCRIPTOR(ctypes.Structure):
                class _ID_UNION(ctypes.Union):
                    _fields_ = [
                        ("FileId", wintypes.LARGE_INTEGER),
                        ("ObjectId", ctypes.c_byte * 16),
                        ("ExtendedFileId", ctypes.c_byte * 16),
                    ]

                _fields_ = [
                    ("dwSize", wintypes.DWORD),
                    ("Type", wintypes.DWORD),  # FileIdType = 0
                    ("u", _ID_UNION),
                ]

            kernel32 = ctypes.windll.kernel32
            vol_path = str(fs_id.get("vol_path") or "\\\\.\\C:")
            file_id = int(fs_id.get("file_id") or 0)
            if not file_id:
                return None

            vol_handle = kernel32.CreateFileW(
                vol_path,
                0,  # metadata query
                7,  # share all
                None,
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS,
                None,
            )
            if vol_handle == -1 or vol_handle == 0:
                return None

            desc = FILE_ID_DESCRIPTOR()
            desc.dwSize = ctypes.sizeof(FILE_ID_DESCRIPTOR)
            desc.Type = 0  # FileIdType
            desc.u.FileId = file_id

            target_handle = kernel32.OpenFileById(
                vol_handle,
                ctypes.byref(desc),
                FILE_READ_ATTRIBUTES,
                7,
                None,
                FILE_FLAG_BACKUP_SEMANTICS,
            )
            kernel32.CloseHandle(vol_handle)

            if target_handle == -1 or target_handle == 0:
                return None

            buf = ctypes.create_unicode_buffer(32768)
            res = kernel32.GetFinalPathNameByHandleW(target_handle, buf, 32768, 0)
            kernel32.CloseHandle(target_handle)

            if res > 0:
                p_str = buf.value
                if p_str.startswith("\\\\?\\"):
                    p_str = p_str[4:]
                p = Path(p_str).resolve()
                if p.is_dir():
                    return p
            return None
        except Exception:  # noqa: BLE001
            return None

    elif target_os == "darwin" and sys.platform == "darwin":
        try:
            dev = fs_id.get("dev")
            ino = fs_id.get("ino")
            if dev is None or ino is None:
                return None

            vol_path = f"/.vol/{dev}/{ino}"
            try:
                fd = os.open(vol_path, os.O_RDONLY)
            except OSError:
                return None

            try:
                resolved = _darwin_getpath(fd)
                if resolved:
                    p = Path(resolved).resolve()
                    if p.is_dir():
                        return p
            finally:
                os.close(fd)
            return None
        except Exception:  # noqa: BLE001
            return None

    return None
