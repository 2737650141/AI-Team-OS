"""SecretStore / SecretResolver（010 二十六~二十八 / 009-A 五）。

- SecretStore Protocol：set_secret/get_secret/delete_secret/has_secret。
- SessionSecretStore：进程内存，不落盘，后端重启失效（009-A 5.1）。
- WindowsSecretStore：DPAPI 加密后写 runtime/secrets/<name>.bin（009-A 5.2）；
  非 Windows 平台不可用时明确报错（不降级到明文）。
- 真实密钥严禁写入：Git/日志/Checkpoint/Event/Evidence/Artifact/Audit/Trace/浏览器。
- SecretResolver：Session → Windows Secure Store → Environment Variable → Missing。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Protocol


class SecretStore(Protocol):
    def set_secret(self, name: str, value: str) -> None: ...

    def get_secret(self, name: str) -> str | None: ...

    def delete_secret(self, name: str) -> None: ...

    def has_secret(self, name: str) -> bool: ...


class SessionSecretStore:
    """009-A 5.1：仅后端进程内存。不落盘、不进入任何持久化。"""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}
        self._lock = threading.Lock()

    def set_secret(self, name: str, value: str) -> None:
        with self._lock:
            self._secrets[name] = value

    def get_secret(self, name: str) -> str | None:
        with self._lock:
            return self._secrets.get(name)

    def delete_secret(self, name: str) -> None:
        with self._lock:
            self._secrets.pop(name, None)

    def has_secret(self, name: str) -> bool:
        with self._lock:
            return name in self._secrets


def _dpapi_encrypt(data: bytes) -> bytes:
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    blob_in = DATA_BLOB(
        len(data),
        ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)),
    )
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _dpapi_decrypt(data: bytes) -> bytes:
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    blob_in = DATA_BLOB(
        len(data),
        ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)),
    )
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


class WindowsSecretStore:
    """009-A 5.2：Windows DPAPI 加密落盘（当前用户范围）。非 Windows 明确报错。"""

    def __init__(self, secrets_dir: Path | None = None) -> None:
        if os.name != "nt":
            raise RuntimeError("WindowsSecretStore requires Windows (DPAPI)")
        self._dir = secrets_dir or Path("runtime/secrets")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, name: str) -> Path:
        # name 白名单字符（防路径注入）；URL 编码无关，仅 [A-Za-z0-9._-]
        safe = "".join(c for c in name if c.isalnum() or c in "._-")[:64]
        if safe != name:
            raise ValueError(f"invalid secret name: {name}")
        return self._dir / f"{safe}.bin"

    def set_secret(self, name: str, value: str) -> None:
        blob = _dpapi_encrypt(value.encode("utf-8"))
        with self._lock:
            self._path(name).write_bytes(blob)

    def get_secret(self, name: str) -> str | None:
        p = self._path(name)
        if not p.exists():
            return None
        with self._lock:
            raw = p.read_bytes()
        try:
            return _dpapi_decrypt(raw).decode("utf-8")
        except Exception:  # noqa: BLE001  损坏/跨用户 → 视为缺失
            return None

    def delete_secret(self, name: str) -> None:
        with self._lock:
            p = self._path(name)
            if p.exists():
                p.unlink()

    def has_secret(self, name: str) -> bool:
        return self._path(name).exists()


# ---- 进程级解析器（本地单用户） ----
class SecretResolver:
    """统一密钥解析：Session → Windows Secure Store → Environment Variable → Missing。

    业务代码禁止散落 os.getenv("API_KEY")（010 二十八）。
    """

    def __init__(
        self,
        session: SessionSecretStore | None = None,
        secure: WindowsSecretStore | None = None,
    ) -> None:
        self._session = session or SessionSecretStore()
        self._secure = secure

    def resolve(self, name: str, env_names: list[str] | None = None) -> str | None:
        """解析密钥；env_names 为向后兼容的环境变量名列表。"""
        v = self._session.get_secret(name)
        if v:
            return v
        if self._secure is not None:
            v = self._secure.get_secret(name)
            if v:
                return v
        for env_name in env_names or []:
            v = os.environ.get(env_name)
            if v:
                return v
        return None

    def store_mode(self, name: str) -> str:
        """当前生效的存储来源（UI 显示用；绝不返回值）。"""
        if self._session.has_secret(name):
            return "session"
        if self._secure is not None and self._secure.has_secret(name):
            return "windows_secure_store"
        for env_name in _ENV_ALIASES.get(name, []):
            if os.environ.get(env_name):
                return "environment_variable"
        return "missing"

    def set(self, name: str, value: str, storage_mode: str = "session") -> str:
        """保存（storage_mode=session|secure）。返回实际存储模式。"""
        if storage_mode == "secure":
            if self._secure is None:
                raise RuntimeError("secure store unavailable on this platform")
            self._secure.set_secret(name, value)
            self._session.delete_secret(name)  # 替换时清除旧 session 副本
            return "windows_secure_store"
        self._session.set_secret(name, value)
        return "session"

    def delete(self, name: str) -> None:
        self._session.delete_secret(name)
        if self._secure is not None:
            self._secure.delete_secret(name)


# 环境变量别名（向后兼容；010 二十八 Advanced/Deployment mode）
_ENV_ALIASES: dict[str, list[str]] = {
    "openai_compatible.api_key": ["AI_TEAM_MODEL_API_KEY"],
    "github.token": ["AI_TEAM_GITHUB_TOKEN"],
}


def default_resolver(data_dir: Path | None = None) -> SecretResolver:
    """默认解析器：Windows 平台自动启用 Secure Store（runtime/secrets）。"""
    secure = None
    if os.name == "nt":
        try:
            secure = WindowsSecretStore((data_dir or Path("data")) / "runtime" / "secrets")
        except RuntimeError:
            secure = None
    return SecretResolver(session=SessionSecretStore(), secure=secure)


# ---- 工具函数 ----
def fingerprint(value: str) -> str:
    """密钥指纹（仅用于诊断显示前 8 位，非安全用途）。"""
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
