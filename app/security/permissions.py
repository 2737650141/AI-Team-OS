from __future__ import annotations

import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PermissionMode(StrEnum):
    SAFE = "safe"
    STANDARD = "standard"
    MAXIMUM = "maximum"

    @classmethod
    def normalize(cls, value: str | PermissionMode) -> PermissionMode:
        if value == "full_access":  # migration from the pre-M6-P task-only switch
            return cls.MAXIMUM
        return cls(value)


class RiskClass(StrEnum):
    READ_ONLY = "read_only"
    LOW = "low"
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    DESTRUCTIVE = "destructive"
    EXTERNAL_EFFECT = "external_effect"
    SYSTEM = "system"
    FORBIDDEN = "forbidden"


class ActionDecision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    BLOCK = "block"


class PermissionModeSetting(BaseModel):
    mode: PermissionMode = PermissionMode.STANDARD
    changed_at: str = Field(default_factory=utc_now)
    changed_by_user: bool = False
    version: int = 1
    maximum_confirmed: bool = False


class ActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=200)
    risk: RiskClass
    target: str = Field(default="", max_length=1000)
    task_id: str | None = None
    task_explicit: bool = True
    source: str = "system"


class PolicyDecision(BaseModel):
    mode: PermissionMode
    risk: RiskClass
    decision: ActionDecision
    reason: str
    action: str
    target: str = ""


class AutomaticActionRecord(BaseModel):
    action_id: str
    timestamp: str
    task_id: str | None = None
    action: str
    target: str = ""
    risk: RiskClass
    permission_mode: PermissionMode
    decision: ActionDecision
    reason: str


class PermissionChangeError(ValueError):
    pass


class RiskClassifier:
    """Classify actions without trusting model-provided risk labels."""

    _FORBIDDEN_MARKERS = (
        "extract_password",
        "read_password_field",
        "export_browser_password",
        "credential_manager",
        "extract_secret",
        "export_private_key",
        "bypass_uac",
        "click_uac_yes",
        "administrator_password",
        "disable_safety",
        "modify_safety_kernel",
        "bypass_secret_store",
        "bypass_stop",
        "agent_change_permission_mode",
        "prompt_change_permission_mode",
    )
    _EXTERNAL_MARKERS = (
        "git_push",
        "upload",
        "send_email",
        "send_message",
        "publish",
        "submit_form",
        "deploy",
        "release",
    )
    _SENSITIVE_MARKERS = (
        "sensitive_data",
        "private_data",
        "financial",
        "legal_submission",
        "purchase",
        "payment",
        "order",
    )
    _SYSTEM_MARKERS = (
        "install_software",
        "uninstall_software",
        "system_settings",
        "startup_item",
        "registry_write",
    )
    _DESTRUCTIVE_MARKERS = ("delete", "remove", "close_window", "overwrite_important")

    @classmethod
    def classify(
        cls,
        action: str,
        *,
        read_only: bool = False,
        risk_hint: str = "",
        target: str = "",
    ) -> RiskClass:
        text = f"{action} {target}".lower()
        if any(marker in text for marker in cls._FORBIDDEN_MARKERS):
            return RiskClass.FORBIDDEN
        if any(marker in text for marker in cls._SENSITIVE_MARKERS):
            return RiskClass.SENSITIVE
        if any(marker in text for marker in cls._EXTERNAL_MARKERS):
            return RiskClass.EXTERNAL_EFFECT
        if any(marker in text for marker in cls._SYSTEM_MARKERS):
            return RiskClass.SYSTEM
        if read_only:
            return RiskClass.READ_ONLY
        if any(marker in text for marker in cls._DESTRUCTIVE_MARKERS):
            return RiskClass.DESTRUCTIVE
        if action in {
            "windows_launch_app",
            "windows_focus_window",
            "windows_open_safe_path",
        }:
            return RiskClass.LOW
        if risk_hint.lower() == "dangerous":
            return RiskClass.DESTRUCTIVE
        return RiskClass.NORMAL


class PermissionPolicy:
    """One policy decision point shared by every enforcement gateway."""

    def decide(
        self, mode: PermissionMode | str, request: ActionRequest
    ) -> PolicyDecision:
        normalized = PermissionMode.normalize(mode)
        risk = request.risk
        if risk is RiskClass.FORBIDDEN:
            return self._result(
                normalized,
                request,
                ActionDecision.BLOCK,
                "Hard Safety Kernel forbids this action in every permission mode.",
            )
        if normalized is PermissionMode.SAFE:
            decision = (
                ActionDecision.ALLOW
                if risk in {RiskClass.READ_ONLY, RiskClass.LOW}
                else ActionDecision.ASK
            )
            reason = (
                "Read-only and genuinely low-risk actions are automatic in Safe mode."
                if decision is ActionDecision.ALLOW
                else "Safe mode requires confirmation for write, execution, and state changes."
            )
            return self._result(normalized, request, decision, reason)
        if normalized is PermissionMode.STANDARD:
            decision = (
                ActionDecision.ALLOW
                if risk in {RiskClass.READ_ONLY, RiskClass.LOW, RiskClass.NORMAL}
                else ActionDecision.ASK
            )
            reason = (
                "Normal task operations are automatic in Standard mode."
                if decision is ActionDecision.ALLOW
                else "Sensitive, destructive, external, or system effects require confirmation."
            )
            return self._result(normalized, request, decision, reason)
        if risk is RiskClass.SENSITIVE:
            return self._result(
                normalized,
                request,
                ActionDecision.ASK,
                "A sensitive final effect requires one user confirmation even in Maximum mode.",
            )
        if risk in {RiskClass.EXTERNAL_EFFECT, RiskClass.SYSTEM} and not request.task_explicit:
            return self._result(
                normalized,
                request,
                ActionDecision.ASK,
                "Maximum mode cannot expand the user's goal to an unrequested external effect.",
            )
        return self._result(
            normalized,
            request,
            ActionDecision.ALLOW,
            "The action is directly required by the task and is automatic in Maximum mode.",
        )

    @staticmethod
    def _result(
        mode: PermissionMode,
        request: ActionRequest,
        decision: ActionDecision,
        reason: str,
    ) -> PolicyDecision:
        return PolicyDecision(
            mode=mode,
            risk=request.risk,
            decision=decision,
            reason=reason,
            action=request.action,
            target=request.target,
        )


class PermissionStore:
    """Explicit user setting and decision history; never semantic memory or task state."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "runtime" / "security" / "permissions.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS permission_setting (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    mode TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    changed_by_user INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    maximum_confirmed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS permission_actions (
                    action_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    task_id TEXT,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    permission_mode TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO permission_setting
                (singleton, mode, changed_at, changed_by_user, version, maximum_confirmed_at)
                VALUES (1, 'standard', ?, 0, 1, NULL)
                """,
                (utc_now(),),
            )

    def get(self) -> PermissionModeSetting:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM permission_setting WHERE singleton=1").fetchone()
        assert row is not None
        return PermissionModeSetting(
            mode=PermissionMode.normalize(row["mode"]),
            changed_at=row["changed_at"],
            changed_by_user=bool(row["changed_by_user"]),
            version=int(row["version"]),
            maximum_confirmed=bool(row["maximum_confirmed_at"]),
        )

    def mode(self) -> PermissionMode:
        return self.get().mode

    def set_mode(
        self,
        mode: PermissionMode | str,
        *,
        changed_by_user: bool,
        confirmed: bool = False,
        source: str = "user_explicit_action",
    ) -> tuple[PermissionModeSetting, PermissionMode]:
        if not changed_by_user or source != "user_explicit_action":
            raise PermissionChangeError(
                "Only an explicit user UI action may change permission mode"
            )
        normalized = PermissionMode.normalize(mode)
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM permission_setting WHERE singleton=1").fetchone()
            assert row is not None
            old = PermissionMode.normalize(row["mode"])
            maximum_confirmed_at = row["maximum_confirmed_at"]
            if normalized is PermissionMode.MAXIMUM and not maximum_confirmed_at:
                if not confirmed:
                    raise PermissionChangeError("MAXIMUM_CONFIRMATION_REQUIRED")
                maximum_confirmed_at = utc_now()
            changed_at = utc_now()
            version = int(row["version"]) + 1
            conn.execute(
                """
                UPDATE permission_setting
                SET mode=?, changed_at=?, changed_by_user=1, version=?, maximum_confirmed_at=?
                WHERE singleton=1
                """,
                (normalized.value, changed_at, version, maximum_confirmed_at),
            )
        return self.get(), old

    def record(self, decision: PolicyDecision, task_id: str | None = None) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO permission_actions
                (action_id, timestamp, task_id, action, target, risk,
                 permission_mode, decision, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex[:16],
                    utc_now(),
                    task_id,
                    decision.action,
                    decision.target[:1000],
                    decision.risk.value,
                    decision.mode.value,
                    decision.decision.value,
                    decision.reason,
                ),
            )

    def recent(self, limit: int = 50) -> list[AutomaticActionRecord]:
        bounded = max(1, min(limit, 200))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM permission_actions ORDER BY timestamp DESC LIMIT ?", (bounded,)
            ).fetchall()
        return [AutomaticActionRecord(**dict(row)) for row in rows]

    def explain(
        self,
        *,
        action: str,
        read_only: bool = False,
        risk: RiskClass | None = None,
        target: str = "",
        task_explicit: bool = True,
        source: str = "user",
    ) -> PolicyDecision:
        classified = risk or RiskClassifier.classify(
            action, read_only=read_only, target=target
        )
        return PermissionPolicy().decide(
            self.mode(),
            ActionRequest(
                action=action,
                risk=classified,
                target=target,
                task_explicit=task_explicit,
                source=source,
            ),
        )


class PermissionRuntime:
    """Live mode source: every action re-reads settings, so running tasks update immediately."""

    def __init__(
        self,
        store: PermissionStore,
        mode_provider: Callable[[], PermissionMode] | None = None,
    ) -> None:
        self.store = store
        self.mode_provider = mode_provider or store.mode
        self.policy = PermissionPolicy()

    def decide(self, request: ActionRequest, *, record: bool = True) -> PolicyDecision:
        decision = self.policy.decide(self.mode_provider(), request)
        if record and decision.decision is ActionDecision.ALLOW:
            self.store.record(decision, request.task_id)
        return decision
