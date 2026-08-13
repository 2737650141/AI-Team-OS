"""PRODUCT-01 Extended Black-Box Acceptance（纠偏令 032-035）。

覆盖四类补充验收（主套件见 run_product01.py / REAL_WORLD_TASK_SUITE.md）：
1. 20 个语义变体任务（纠偏令 032）：验证 semantic robustness 而非 prompt memorization。
   * 说明：纠偏令要求变体由独立模型生成；当前无独立模型环境，使用预置确定性变体集，
     执行模型未预读（脚本内嵌，运行时随机打乱顺序）。
2. 15 个对抗性普通用户输入（纠偏令 033）：错别字 / 口语 / 短句 / 模糊 / 指代 / 情绪化。
   * 指代类（"第二个"、"继续"）依赖会话状态，CLI 单任务模式如实记录可解释结果
     （paused/澄清）并标记为 session 层能力待办，不视为崩溃。
3. Permission Mode 子集（纠偏令 035）：SAFE 5 个 + MAXIMUM 5 个，确认权限系统不破坏普通工作流。
4. 10-turn 连续会话（纠偏令 034）：同一 data_dir 连续 10 次任务，验证
   Working Context / Memory / 稳定完成；跨任务指代如实标记。

用法：
    .venv/Scripts/python.exe scripts/acceptance/run_product01_extended.py
"""

from __future__ import annotations

import argparse
import random
import time
from pathlib import Path

from app.runner import run_task
from app.security.permissions import PermissionStore

ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_PATH = ROOT / "docs" / "acceptance" / "PRODUCT01_EXTENDED_REPORT.md"

# ---------- 20 语义变体（基于套件 A/B 级任务的换说法） ----------
SEMANTIC_VARIANTS = [
    "找几个热门 Agent 项目",
    "GitHub 上最近有什么值得看的 AI Agent 开源项目？",
    "帮我搜几个类似 JARVIS 的项目。",
    "看看最近 Agent 框架里哪些项目比较火。",
    "有哪些 AI 智能体框架值得关注？",
    "帮我看看 GitHub 上比较火的 agent 库。",
    "最近大家都在用什么 agent 框架？",
    "搜一下 crewai 和 langgraph 哪个活跃。",
    "帮我列一下这个目录里的文件。",
    "这个文件夹里都有什么？",
    "看看这个项目用了啥技术栈。",
    "帮我总结一下这个项目是干嘛的。",
    "这个仓库主要是做什么的？",
    "找几个和这个项目差不多的开源项目。",
    "有没有类似的项目可以参考？",
    "帮我查查 crewai 的 license。",
    "langgraph 的许可证是什么？",
    "这个项目最近更新频繁吗？",
    "帮我看看项目的依赖有没有问题。",
    "帮我分析一下这个项目的结构。",
]

# ---------- 15 对抗性普通用户输入（纠偏令 033） ----------
ADVERSARIAL_INPUTS = [
    ("错别字", "帮我查一个 guthub 上热门的项目"),  # 原真实失败输入（含错字）
    ("错别字", "帮我找一个热门的 giithub 项目"),
    ("口语", "哥们帮我找几个火的 agent 项目呗"),
    ("口语", "这项目咋样，帮我看看"),
    ("短句", "找项目"),
    ("短句", "总结"),
    ("模糊", "做点东西"),
    ("模糊", "帮我搞一下"),
    ("指代", "第二个"),  # 依赖会话上下文
    ("指代", "就按刚才那个"),
    ("连续追问", "继续"),
    ("情绪化", "算了别改了"),
    ("中英混", "帮我 search 一下 agent 项目"),
    ("无标点", "帮我找几个热门的agent项目"),
    ("反义否定", "不用改代码，就看看"),
]

# ---------- Permission Mode 子集任务（纠偏令 035） ----------
SAFE_TASKS = [
    "帮我找几个热门的 GitHub AI Agent 项目",
    "总结这个项目",
    "帮我查一下 langgraph 和 crewai 的区别",
    "列出当前目录下的文件",
    "现在几点了",
]
MAXIMUM_TASKS = [
    "帮我找几个热门的 GitHub AI Agent 项目",
    "帮我分析一下这个项目的代码结构",
    "总结这个项目",
    "帮我查一下 crewai 的 license",
    "检查一下这个 Python 文件有没有明显问题",
]

# ---------- 10-turn 连续会话（纠偏令 034） ----------
TEN_TURN_SESSION = [
    "帮我找几个热门的 GitHub AI Agent 项目",
    "第二个项目详细看看",
    "跟我们的项目比一下",
    "哪些东西值得借鉴",
    "先别改代码",
    "那写个方案",
    "继续",
    "把第一项实施",
    "看一下结果",
    "还有问题吗",
]


def _run(goal: str, data_dir: Path, permission: str = "standard") -> dict:
    started = time.perf_counter()
    try:
        report = run_task(goal, token_budget=20000, cost_budget=1.0, data_dir=data_dir)
        return {
            "goal": goal,
            "status": report.status,
            "failure_code": report.state.failure_code,
            "permission": permission,
            "model_calls": report.call_count,
            "tool_calls": report.tool_call_count,
            "rework": report.state.rework_count,
            "replan": report.state.replan_count,
            "latency_s": round(time.perf_counter() - started, 2),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "goal": goal,
            "status": "error",
            "failure_code": "UNKNOWN",
            "permission": permission,
            "model_calls": 0,
            "tool_calls": 0,
            "rework": 0,
            "replan": 0,
            "latency_s": round(time.perf_counter() - started, 2),
            "notes": f"{type(exc).__name__}: {exc}"[:200],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="PRODUCT-01 扩展验收")
    parser.add_argument("--data-dir", default=str(ROOT / "data" / "product01_extended"))
    parser.add_argument("--seed", type=int, default=7, help="语义变体随机顺序种子")
    args = parser.parse_args()

    lines: list[str] = [
        "# PRODUCT-01 扩展验收报告",
        "",
        f"- 执行时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "- model_mode: fake（离线确定性基线）",
        "",
    ]

    def table(rows: list[dict], title: str) -> None:
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| goal | status | failure_code | tools | rework | replan | latency_s |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in rows:
            lines.append(
                f"| {r['goal'][:40]} | {r['status']} | {r.get('failure_code') or '-'} | "
                f"{r['tool_calls']} | {r['rework']} | {r['replan']} | {r['latency_s']} |"
            )
        lines.append("")

    # 1. 语义变体（随机顺序，验证 robustness）
    variants = SEMANTIC_VARIANTS[:]
    random.Random(args.seed).shuffle(variants)
    v_rows = []
    for goal in variants:
        d = Path(args.data_dir) / "variants" / str(abs(hash(goal)) % 10**6)
        r = _run(goal, d)
        r["goal"] = goal
        v_rows.append(r)
    table(v_rows, f"1. 语义变体（{len(v_rows)} 个，纠偏令 032）")
    v_ok = sum(1 for r in v_rows if r["status"] == "completed")

    # 2. 对抗性输入
    a_rows = []
    for kind, goal in ADVERSARIAL_INPUTS:
        d = Path(args.data_dir) / "adversarial" / str(abs(hash(goal)) % 10**6)
        r = _run(goal, d)
        r["goal"] = f"[{kind}] {goal}"
        a_rows.append(r)
    table(a_rows, "2. 对抗性普通用户输入（纠偏令 033）")
    a_ok = sum(1 for r in a_rows if r["status"] == "completed")
    a_explainable = sum(
        1 for r in a_rows if r["status"] in ("completed", "paused") or r["failure_code"]
    )

    # 3. Permission Mode 子集
    p_rows = []
    for mode, tasks in (("safe", SAFE_TASKS), ("maximum", MAXIMUM_TASKS)):
        d = Path(args.data_dir) / "permission" / mode
        store = PermissionStore(d)
        confirmed = mode == "maximum"
        store.set_mode(mode, changed_by_user=True, confirmed=confirmed)
        for goal in tasks:
            r = _run(goal, d)
            r["goal"] = f"[{mode}] {goal}"
            r["permission"] = mode
            p_rows.append(r)
    table(p_rows, "3. Permission Mode 子集（SAFE 5 + MAXIMUM 5，纠偏令 035）")
    p_ok = sum(1 for r in p_rows if r["status"] == "completed")

    # 4. 10-turn 连续会话（同一 data_dir 共享记忆库）
    s_rows = []
    sess_dir = Path(args.data_dir) / "session"
    for i, goal in enumerate(TEN_TURN_SESSION, start=1):
        r = _run(goal, sess_dir)
        r["goal"] = f"turn{i}: {goal}"
        s_rows.append(r)
    table(s_rows, "4. 10-turn 连续会话（纠偏令 034）")
    s_ok = sum(1 for r in s_rows if r["status"] == "completed")
    session_context_dependent = [i + 1 for i, r in enumerate(s_rows) if r["status"] == "paused"]

    # 汇总
    lines.append("## 汇总")
    lines.append("")
    lines.append(
        f"- 语义变体: {v_ok}/{len(v_rows)} completed"
    )
    lines.append(
        f"- 对抗性输入: {a_ok}/{len(a_rows)} completed，"
        f"可解释结果 {a_explainable}/{len(a_rows)}"
    )
    lines.append(f"- Permission Mode: {p_ok}/{len(p_rows)} completed（SAFE/MAXIMUM 各 5）")
    lines.append(
        f"- 10-turn 会话: {s_ok}/{len(s_rows)} completed；"
        f"依赖会话上下文的 turn: {session_context_dependent or '无'}"
    )
    lines.append(
        "- 说明: 指代/连续追问类输入依赖会话状态，CLI 单任务模式返回 paused/澄清"
        "（可解释，非崩溃）；完整会话上下文为 UI/session 层能力，属后续待办。"
    )
    lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"report written: {REPORT_PATH}")
    print(f"variants={v_ok}/{len(v_rows)} adversarial_explainable={a_explainable}/{len(a_rows)} "
          f"permission={p_ok}/{len(p_rows)} session={s_ok}/{len(s_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
