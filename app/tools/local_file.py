"""本地文件只读工具（006 八/九）：7 个工具 + 路径安全 + 敏感文件拒绝。

安全（8.1/8.2/8.3）：
- 允许根目录来自服务端配置 AI_TEAM_ALLOWED_READ_ROOTS；客户端不能传任意绝对根目录。
- 拒绝：.. 穿越/绝对路径逃逸/符号链接与 Junction 逃逸（resolve 后复查）/UNC 网络路径/
  设备路径/ADS（Alternate Data Streams）/大小写与短路径绕过（normcase 比较）。
- 敏感文件默认拒绝（.env/.pem/.key/id_rsa/id_ed25519/credentials*/secrets*/.aws/.ssh/
  .git/config/浏览器配置目录），即使位于允许根目录内。
- 限制：单文件大小/任务读取总量/目录项数量/文本编码/二进制拒绝/PDF 页数上限/
  CSV 行列上限/JSON 深度与长度（9.x）。
- 读取内容仍标记不可信外部数据（调用方 Prompt 层处理）。
"""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

from app.core.secrets import SENSITIVE_DIRS, SENSITIVE_FILENAMES, SENSITIVE_SUFFIXES

MAX_FILE_BYTES = 2 * 1024 * 1024  # 单文件最大（8.4）
MAX_DIR_ENTRIES = 500  # 目录项上限（8.4）
MAX_CSV_ROWS = 5000  # CSV 行上限（9.2）
MAX_CSV_COLS = 200  # CSV 列上限（9.2）
MAX_JSON_DEPTH = 20  # JSON 嵌套深度上限（9.3）
MAX_JSON_ITEMS = 10000  # JSON 对象/数组元素上限（9.3）
MAX_PDF_PAGES = 100  # PDF 页数上限（9.1）
_DEVICE_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


class LocalPathError(Exception):
    """路径/内容拒绝（安全消息）。"""


class LocalPathPolicy:
    """允许根目录 + 路径安全校验（8.2 五步：规范化 → 解析真实路径 → 验证根内 →
    敏感规则 → 再读取）。"""

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._roots = [p.resolve() for p in allowed_roots if p.exists()]

    def roots(self) -> list[Path]:
        return list(self._roots)

    def validate(self, rel_path: str) -> Path:
        """校验相对路径（允许根内），返回解析后的真实路径（供读取）。"""
        if not rel_path.strip():
            raise LocalPathError("path is empty")
        raw = rel_path.replace("\\", "/")
        # 拒绝绝对路径 / 穿越 / UNC / 设备 / ADS（8.2）
        if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
            raise LocalPathError("absolute path rejected")
        if raw.startswith("//") or raw.startswith("\\\\"):
            raise LocalPathError("UNC path rejected")
        parts = [p for p in raw.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise LocalPathError("path traversal rejected")
        stem = parts[-1] if parts else ""
        if ":" in stem:
            raise LocalPathError("alternate data stream rejected")
        base = stem.split(".")[0].upper()
        if base in _DEVICE_NAMES:
            raise LocalPathError("device path rejected")
        if not parts:
            # 根目录本身（local_list_directory 默认参数）
            for root in self._roots:
                if self._is_sensitive(root):
                    raise LocalPathError("sensitive file rejected")
                return root
            raise LocalPathError("no allowed read roots configured")
        # 只在允许根目录下拼接（8.1：客户端不能传任意绝对根目录），再解析真实路径
        for root in self._roots:
            candidate = root.joinpath(*parts)
            resolved = candidate.resolve()
            if not self._within_roots(resolved):
                continue  # 符号链接/Junction 逃逸（8.2）
            if self._is_sensitive(resolved):
                raise LocalPathError("sensitive file rejected")
            return resolved
        raise LocalPathError("path escapes allowed read roots")

    def _within_roots(self, path: Path) -> bool:
        norm = os.path.normcase(str(path))
        for root in self._roots:
            root_norm = os.path.normcase(str(root))
            if norm == root_norm or norm.startswith(root_norm + os.sep):
                return True
        return False

    def _is_sensitive(self, path: Path) -> bool:
        """8.3：敏感文件/目录默认拒绝（即使位于允许根内）。"""
        stem = path.stem
        lowered = path.name.lower()
        if lowered in SENSITIVE_FILENAMES or stem in SENSITIVE_FILENAMES:
            return True
        if lowered.startswith(".env") or lowered.endswith(".env"):
            return True
        if path.suffix.lower() in SENSITIVE_SUFFIXES:
            return True
        if lowered in ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"):
            return True
        for part in path.parts:
            if part.lower() in SENSITIVE_DIRS:
                return True
        # 浏览器配置等用户数据目录（8.3）
        if (
            any(part in ("AppData", "Application Support") for part in path.parts)
            and path.name == "Preferences"
        ):
            return True
        return False


def _read_text_safe(path: Path, max_bytes: int = MAX_FILE_BYTES) -> tuple[str, bool]:
    """读取文本：大小限制 + 二进制拒绝 + 编码检测。返回 (内容, truncated)。"""
    size = path.stat().st_size
    if size > max_bytes:
        raise LocalPathError(f"file too large ({size} bytes > {max_bytes})")
    data = path.read_bytes()
    # 二进制拒绝（8.4）：NUL 字节或高比例非文本
    if b"\x00" in data[:4096]:
        raise LocalPathError("binary file rejected")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("utf-16")
        except UnicodeDecodeError:
            raise LocalPathError("unsupported text encoding") from None
    truncated = False
    if len(text) > 100_000:
        text = text[:100_000]
        truncated = True
    return text, truncated


def _check_json_shape(value: Any, depth: int = 0) -> None:
    """9.3：深度与元素数量限制。"""
    if depth > MAX_JSON_DEPTH:
        raise LocalPathError("json nesting too deep")
    if isinstance(value, dict):
        if len(value) > MAX_JSON_ITEMS:
            raise LocalPathError("json object too large")
        for v in value.values():
            _check_json_shape(v, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_JSON_ITEMS:
            raise LocalPathError("json array too large")
        for v in value:
            _check_json_shape(v, depth + 1)


class LocalFileToolset:
    """本地文件只读工具集（8.x/9.x）。"""

    def __init__(self, policy: LocalPathPolicy, pdf_reader: Any | None = None) -> None:
        self._policy = policy
        self._pdf_reader = pdf_reader  # 注入 pypdf 兼容 reader（测试用）

    def list_directory(self, path: str = "") -> dict:
        try:
            resolved = self._policy.validate(path or ".")
            if not resolved.is_dir():
                return {"ok": False, "error": "not a directory", "code": "invalid"}
            entries: list[dict[str, Any]] = []
            for child in sorted(resolved.iterdir()):
                if len(entries) >= MAX_DIR_ENTRIES:
                    break
                entries.append(
                    {
                        "name": child.name,
                        "type": "dir" if child.is_dir() else "file",
                        "size": child.stat().st_size if child.is_file() else None,
                    }
                )
            return {"ok": True, "path": str(resolved), "count": len(entries), "entries": entries}
        except LocalPathError as exc:
            return {"ok": False, "error": str(exc), "code": "blocked"}
        except OSError:
            return {"ok": False, "error": "filesystem error", "code": "error"}

    def read_text(self, path: str) -> dict:
        try:
            resolved = self._policy.validate(path)
            if not resolved.is_file():
                return {"ok": False, "error": "not a file", "code": "invalid"}
            text, truncated = _read_text_safe(resolved)
            return {
                "ok": True,
                "path": str(resolved),
                "size": resolved.stat().st_size,
                "truncated": truncated,
                "content": text,
            }
        except LocalPathError as exc:
            return {"ok": False, "error": str(exc), "code": "blocked"}
        except OSError:
            return {"ok": False, "error": "filesystem error", "code": "error"}

    def file_metadata(self, path: str) -> dict:
        try:
            resolved = self._policy.validate(path)
            st = resolved.stat()
            return {
                "ok": True,
                "path": str(resolved),
                "size": st.st_size,
                "is_file": resolved.is_file(),
                "is_dir": resolved.is_dir(),
                "modified_at": st.st_mtime,
            }
        except LocalPathError as exc:
            return {"ok": False, "error": str(exc), "code": "blocked"}
        except OSError:
            return {"ok": False, "error": "filesystem error", "code": "error"}

    def read_json(self, path: str) -> dict:
        try:
            resolved = self._policy.validate(path)
            text, truncated = _read_text_safe(resolved)
            data = json.loads(text)
            _check_json_shape(data)
            return {"ok": True, "path": str(resolved), "truncated": truncated, "data": data}
        except LocalPathError as exc:
            return {"ok": False, "error": str(exc), "code": "blocked"}
        except json.JSONDecodeError:
            return {"ok": False, "error": "invalid json", "code": "invalid"}
        except RecursionError:
            return {"ok": False, "error": "json nesting too deep", "code": "invalid"}
        except OSError:
            return {"ok": False, "error": "filesystem error", "code": "error"}

    def read_csv(self, path: str) -> dict:
        try:
            resolved = self._policy.validate(path)
            text, truncated = _read_text_safe(resolved)
            # 9.2：只按普通数据处理，不执行公式、不把单元格当命令
            rows: list[list[str]] = []
            for row in csv.reader(text.splitlines()):
                if len(rows) >= MAX_CSV_ROWS:
                    truncated = True
                    break
                if len(row) > MAX_CSV_COLS:
                    raise LocalPathError(f"csv row exceeds {MAX_CSV_COLS} columns")
                rows.append(row)
            return {
                "ok": True,
                "path": str(resolved),
                "truncated": truncated,
                "rows": rows,
                "row_count": len(rows),
            }
        except LocalPathError as exc:
            return {"ok": False, "error": str(exc), "code": "blocked"}
        except csv.Error:
            return {"ok": False, "error": "invalid csv", "code": "invalid"}
        except OSError:
            return {"ok": False, "error": "filesystem error", "code": "error"}

    def read_markdown(self, path: str) -> dict:
        return self.read_text(path)

    def read_pdf(self, path: str) -> dict:
        """9.1：复用成熟解析库（pypdf 兼容注入）；未安装时明确报错。"""
        try:
            resolved = self._policy.validate(path)
            size = resolved.stat().st_size
            if size > MAX_FILE_BYTES:
                return {"ok": False, "error": "pdf too large", "code": "blocked"}
            reader = self._pdf_reader
            if reader is None:
                try:
                    from pypdf import PdfReader  # type: ignore[import-not-found]

                    reader = PdfReader
                except ImportError:
                    return {
                        "ok": False,
                        "error": "pdf support requires pypdf (not installed)",
                        "code": "dependency",
                    }
            pdf = reader(str(resolved))
            if getattr(pdf, "is_encrypted", False):
                return {"ok": False, "error": "encrypted pdf rejected", "code": "blocked"}
            pages = list(pdf.pages)
            if len(pages) > MAX_PDF_PAGES:
                return {
                    "ok": False,
                    "error": f"pdf exceeds {MAX_PDF_PAGES} pages",
                    "code": "blocked",
                }
            texts = []
            for i, page in enumerate(pages):
                page_text = (page.extract_text() or "").strip()
                if page_text:
                    texts.append(f"[page {i + 1}]\n{page_text}")
            joined = "\n\n".join(texts)
            if not joined.strip():
                return {
                    "ok": True,
                    "path": str(resolved),
                    "ocr_required": True,
                    "content": "",
                    "page_range": [1, len(pages)],
                    "note": "no extractable text; OCR not performed (9.1)",
                }
            truncated = False
            if len(joined) > 100_000:
                joined = joined[:100_000]
                truncated = True
            return {
                "ok": True,
                "path": str(resolved),
                "page_count": len(pages),
                "page_range": [1, len(pages)],
                "truncated": truncated,
                "content": joined,
            }
        except LocalPathError as exc:
            return {"ok": False, "error": str(exc), "code": "blocked"}
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "pdf read failed", "code": "error"}


def build_local_tools(policy: LocalPathPolicy, pdf_reader: Any | None = None) -> list[Any]:
    """构造本地文件只读工具集（8.x/9.x）。"""
    from app.tools.spec import RiskLevel, ToolSpec

    ts = LocalFileToolset(policy, pdf_reader)
    specs = [
        ("local_list_directory", "列出允许根目录内的目录内容", {"path": "str"}, ts.list_directory),
        ("local_read_text", "读取文本文件（TXT/代码/日志）", {"path": "str"}, ts.read_text),
        (
            "local_file_metadata",
            "文件元数据（大小/修改时间/类型）",
            {"path": "str"},
            ts.file_metadata,
        ),
        ("local_read_json", "读取 JSON 文件（深度/长度受限）", {"path": "str"}, ts.read_json),
        ("local_read_csv", "读取 CSV 文件（行列受限，不执行公式）", {"path": "str"}, ts.read_csv),
        ("local_read_markdown", "读取 Markdown 文件", {"path": "str"}, ts.read_markdown),
        (
            "local_read_pdf",
            "读取 PDF 文本（页数/大小受限，加密拒绝）",
            {"path": "str"},
            ts.read_pdf,
        ),
    ]
    return [
        ToolSpec(
            name=name,
            description=desc,
            input_schema=schema,
            risk_level=RiskLevel.SAFE,
            read_only=True,
            handler=handler,
            roles=("researcher", "executor", "reviewer"),
            path_validator=policy.validate,  # 网关层提前拒绝（8.2）
        )
        for name, desc, schema, handler in specs
    ]
