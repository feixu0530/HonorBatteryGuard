#!/usr/bin/env python3
"""Read-only probe: test whether HONOR kernel device objects can be opened.

Opens devices with GENERIC_READ/WRITE but sends NO IOCTLs. Also reports
elevation status. Safe to run repeatedly.
"""
import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetCurrentProcess.restype = wintypes.HANDLE

DEVICES = [
    r"\\.\HHAL",
    r"\\.\OS2SOC",
    r"\\.\HNOs2EcX64",
    r"\\.\HwOs2EcX64",
]


def token_elevation() -> str:
    """Return elevation / integrity info without changing anything."""
    try:
        is_admin = shell32.IsUserAnAdmin()
    except Exception as e:  # noqa: BLE001
        is_admin = f"error: {e}"
    return f"IsUserAnAdmin = {is_admin}"


def main() -> int:
    print(token_elevation())
    print("device open test (no IOCTL issued):")
    for name in DEVICES:
        h = kernel32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE,
                                 FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                 OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        err = ctypes.get_last_error()
        if h == INVALID_HANDLE_VALUE or h == 0:
            print(f"  {name:<24} FAILED  GetLastError={err} ({ctypes.FormatError(err).strip()})")
        else:
            print(f"  {name:<24} OK      handle=0x{h:X}")
            kernel32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
