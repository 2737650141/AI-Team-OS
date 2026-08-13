"""PRODUCT-01 Real-World Black-Box Acceptance Runner（纠偏令 020）。

用法（Windows）：
    .venv/Scripts/python.exe scripts/acceptance/run_product01.py --levels A B C
    .venv/Scripts/python.exe scripts/acceptance/run_product01.py --levels A --real

行为：
- 读取 docs/acceptance/REAL_WORLD_TASK_SUITE.md 中登记的 50 个真实用户任务
  （解析 Markdown 表格），默认以 fake 模式离线黑盒执行（真实 Provider 不可用时
  是确定性基线；配置 AI_TEAM_MODEL_* 后可加 --real 复验）。
- 每个任务经 app.runner.run_task 完整走运行时（不清洗、不预置 plan、不 mock）。
- 记录 status / failure_code / model_calls / tool_calls / rework / replan / latency。
- 输出 Failure Taxonomy 聚类 + 分级成功率 + Efficiency，写入
  docs/acceptance/PRODUCT01_REPORT.md，并打印门禁判定。
"""

from __future__ import annotations

import argparse
import re
import time
from dataclasses import dataclass
from pathlib import Path

from app.runner import run_task

ROOT = Path(__file__).resolve().parent.parent.parent
SUITE_PATH = ROOT / "docs" / "acceptance" / "REAL_WORLD_TASK_SUITE.md"
REPORT_PATH = ROOT / "docs" / "acceptance" / "PRODUCT01_REPORT.md"
# 生产 Provider Runtime 目录（含 Windows Secure Store 凭据与 Connections 配置）。
# 020-B：验收必须走生产凭据，不得在无凭据目录自动降级 Fake。
DEFAULT_DATA_DIR = ROOT / "data"


@dataclass
class TaskCase:
    id: str
    level: str
    user_input: str
    model_mode: str = "fake"
    permission_mode: str = "standard"
    status: str = ""
    failure_code: str | None = None
    model_calls: int = 0
    tool_calls: int = 0
    rework_count: int = 0
    replan_count: int = 0
    latency_s: float = 0.0
    notes: str = ""


def parse_suite(path: Path) -> list[TaskCase]:
    """从 REAL_WORLD_TASK_SUITE.md 提取任务表（A/B/C 三张表）。"""
    text = path.read_text(encoding="utf-8")
    cases: list[TaskCase] = []
    # 表格行：| A01 | 用户输入 | 预期 | 失败分类 |
    for level in ("A", "B", "C"):
        # 定位对应级别表格（"## 三/四/五" 标题下的第一个表格）
        marker = (
            "## 三、Level A" if level == "A"
            else "## 四、Level B" if level == "B" else "## 五、Level C"
        )
        idx = text.find(marker)
        if idx < 0:
            continue
        nxt = text.find("\n## ", idx + 1)
        block = text[idx : nxt if nxt > 0 else len(text)]
        for line in block.splitlines():
            m = re.match(r"\|\s*([A-C]\d{2})\s*\|\s*(.+?)\s*\|", line)
            if m:
                cases.append(TaskCase(id=m.group(1), level=level, user_input=m.group(2)))
    return cases


def run_case(case: TaskCase, data_dir: Path, real: bool) -> TaskCase:
    case.model_mode = "real" if real else "fake"
    started = time.perf_counter()
    try:
        report = run_task(
            case.user_input,
            token_budget=20000,
            cost_budget=1.0,
            data_dir=data_dir,
            model_mode=case.model_mode,
            permission_mode=case.permission_mode,
        )
        case.status = report.status
        case.failure_code = report.state.failure_code
        case.model_calls = report.call_count
        case.tool_calls = report.tool_call_count
        case.rework_count = report.state.rework_count
        case.replan_count = report.state.replan_count
        case.latency_s = round(time.perf_counter() - started, 2)
        if report.status == "failed":
            case.notes = (report.state.final_result or "")[:200]
    except Exception as exc:  # noqa: BLE001 — 黑盒必须捕获一切
        case.status = "error"
        case.failure_code = "UNKNOWN"
        case.notes = f"{type(exc).__name__}: {exc}"[:200]
        case.latency_s = round(time.perf_counter() - started, 2)
    return case


def main() -> int:
    parser = argparse.ArgumentParser(description="PRODUCT-01 黑盒验收")
    parser.add_argument("--levels", default="A", help="执行级别子集，如 'A' / 'A B' / 'A B C'")
    parser.add_argument(
        "--model-mode",
        default="auto",
        choices=["auto", "real", "fake"],
        help="auto=探测生产 Provider（有→real，无→WAITING，不降级 Fake）；fake=显式离线基线",
    )
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="运行时数据目录")
    args = parser.parse_args()

    from app.acceptance_runtime import (
        WAITING_FOR_USER_CREDENTIAL_INPUT,
        effective_model_mode,
    )

    data_dir = Path(args.data_dir)
    # 生产凭据探测与执行同目录（data-dir 必须为含生产 SecretStore 的目录，默认 data/）
    model_mode, provider_status = effective_model_mode(args.model_mode, data_dir)
    if model_mode == WAITING_FOR_USER_CREDENTIAL_INPUT:
        print("WAITING_FOR_USER_CREDENTIAL_INPUT")
        print(provider_status.get("hint", ""))
        print("本验收不得自动回退 Fake。请到 App: Settings → Connections 录入凭据后重试。")
        return 3

    cases = [c for c in parse_suite(SUITE_PATH) if c.level in args.levels.replace(" ", "")]
    if not cases:
        print(f"no cases found in {SUITE_PATH}")
        return 2

    print(
        "PRODUCT-01 acceptance: "
        f"{len(cases)} cases, levels={args.levels}, model_mode={model_mode}"
    )
    print(
        "provider: "
        f"{provider_status.get('provider_name')} / {provider_status.get('model')} "
        f"({provider_status.get('source')})"
    )
    results = [run_case(c, data_dir, model_mode == "real") for c in cases]

    # ---- 汇总 ----
    by_level = {"A": [], "B": [], "C": []}
    for c in results:
        by_level[c.level].append(c)
    lines: list[str] = []
    lines.append("# PRODUCT-01 验收报告")
    lines.append("")
    lines.append(f"- 执行时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(
        f"- 任务数: {len(results)}"
        f"（A={len(by_level['A'])}, B={len(by_level['B'])}, C={len(by_level['C'])}）"
    )
    lines.append(f"- model_mode: {model_mode}")
    lines.append("")

    # 成功率
    lines.append("## 分级成功率")
    lines.append("")
    lines.append("| Level | completed | total | rate | 门禁 |")
    lines.append("|---|---|---|---|---|")
    gates = {"A": (15, 15), "B": (19, 20), "C": (13, 15)}
    all_ok = True
    for level, name in (("A", "Simple"), ("B", "Standard"), ("C", "Complex")):
        if not by_level[level]:
            continue  # 未执行该级别：不参与本次门禁判定
        done = [c for c in by_level[level] if c.status == "completed"]
        need, total = gates[level]
        rate = len(done) / len(by_level[level]) if by_level[level] else 0.0
        gate_ok = len(done) >= need
        all_ok = all_ok and gate_ok
        lines.append(
            f"| {level} ({name}) | {len(done)} | {len(by_level[level])} | "
            f"{rate:.0%} | {'PASS' if gate_ok else 'FAIL'} |"
        )
    lines.append(
        f"| 合计 | {sum(1 for c in results if c.status == 'completed')} | {len(results)} | "
        f"{sum(1 for c in results if c.status == 'completed') / len(results):.0%} | |"
    )
    lines.append("")

    # Failure Taxonomy
    lines.append("## Failure Taxonomy")
    lines.append("")
    tax: dict[str, int] = {}
    for c in results:
        if c.status == "completed":
            continue
        code = c.failure_code or "UNKNOWN"
        tax[code] = tax.get(code, 0) + 1
    if tax:
        for code, n in sorted(tax.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {code}: {n}")
    else:
        lines.append("- 无失败")
    lines.append("")

    # Efficiency（Level A）
    a = [c for c in by_level["A"] if c.status == "completed"]
    if a:
        lines.append("## Efficiency（Simple）")
        lines.append("")
        lines.append(f"- 平均 model calls: {sum(c.model_calls for c in a) / len(a):.2f}")
        lines.append(f"- 平均 tool calls: {sum(c.tool_calls for c in a) / len(a):.2f}")
        lines.append(f"- 平均 latency: {sum(c.latency_s for c in a) / len(a):.2f}s")
        lines.append(f"- 平均 rework: {sum(c.rework_count for c in a) / len(a):.2f}")
        lines.append(f"- 平均 replan: {sum(c.replan_count for c in a) / len(a):.2f}")
        lines.append("")

    # 明细
    lines.append("## 明细")
    lines.append("")
    lines.append(
        "| ID | level | status | failure_code | model_calls | tool_calls | "
        "rework | replan | latency_s |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for c in results:
        lines.append(
            f"| {c.id} | {c.level} | {c.status} | {c.failure_code or '-'} | {c.model_calls} | "
            f"{c.tool_calls} | {c.rework_count} | {c.replan_count} | {c.latency_s} |"
        )
    lines.append("")
    status_line = "PRODUCT_BASELINE_VALIDATED" if all_ok else "FAILED"
    lines.append(f"## STATUS: {status_line}")
    lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"report written: {REPORT_PATH}")
    print(f"STATUS: {status_line}")
    for c in results:
        flag = "OK " if c.status == "completed" else "!! "
        print(f"{flag}{c.id}[{c.level}] {c.status} {c.failure_code or ''} "
              f"(model={c.model_calls}, tools={c.tool_calls}, "
              f"rework={c.rework_count}, replan={c.replan_count})")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
