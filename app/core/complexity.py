"""TaskComplexityClassifier（PRODUCT-01，纠偏令 019-024）。

目标：简单任务不过度编排。根据用户目标确定性分类：

- TRIVIAL  —— 问候/时间/日期等一句话问答：直接完成（空计划），不经 Planner/Reviewer。
- SIMPLE   —— 单步信息型任务（找/查/搜/列/总结等）：单 researcher 子任务快速路径，
              不调 LLM Planner、不配 Reviewer Gate（减少 model calls）。
- STANDARD —— 默认：现有完整编排（Planner → 并行执行 → Reviewer → 定向返工）。
- COMPLEX  —— 多步/跨领域/方案类：完整编排 + 允许 Rework/Replan。

设计约束（保持既有测试与行为稳定）：
- goal 以 "scenario:" / "sandbox_" 开头 → 一律 STANDARD（负面场景与沙箱测试语义不变）。
- 代码类关键词（修复/测试/代码/bug/patch/python/实现 等）→ STANDARD。
- 未命中任何降级短语 → STANDARD（默认保守）。
"""

from __future__ import annotations

from enum import Enum

TRIVIAL_MARKERS = (
    "现在几点",
    "几点了",
    "现在时间",
    "今天几号",
    "今天日期",
    "几月几号",
    "你好",
    "在吗",
    "hello",
    "hi",
    "what time",
    "date today",
    "介绍一下你自己",
    "你是谁",
    "who are you",
    "你可以干什么",
    "你能做什么",
    "what can you do",
)

SIMPLE_MARKERS = (
    "找几个",
    "找一下",
    "帮我找",
    "帮我查",
    "查一下",
    "查查",
    "查一查",
    "查几个",
    "搜一下",
    "搜搜",
    "搜一搜",
    "搜几个",
    "看看",
    "检查一下",
    "检查",
    "列一下",
    "列出",
    "总结一下",
    "总结这个",
    "整理一下",
    "有哪些",
    "有什么",
    "介绍一下",
    "分析一下",
    "find some",
    "search for",
    "look up",
    "summarize",
    "list ",
    "what are",
    "主要用了什么技术",
)

COMPLEX_MARKERS = (
    "架构方案",
    "架构设计",
    "影响范围",
    "改进方案",
    "实施方案",
    "调研报告",
    "研究报告",
    "结合我们的项目",
    "先别改代码",
    "提出方案",
    "然后执行",
    "再执行",
    "先给方案",
    "技术选型报告",
    "对比报告",
    "决策建议",
    "里程碑",
    "先测量再改",
)

# 多步研究意图：SIMPLE 快速路径只适用于单一动作（020-B 六：Standard 必须真实
# 出现 Supervisor/Planner/Researcher/Executor|Reviewer 全编排，不能全走单 researcher）
MULTI_STEP_MARKERS = (
    "对比",
    "比较一下",
    "跟我们的",
    "和我们的",
    "与我们的",
    "优缺点",
    "评估",
    "梳理",
    "找出",
    "设计得不好",
    "哪些",
    "依赖",
    "瓶颈",
    "安全",
    "审计",
    "调研",
    "类似我们的",
    "类似项目",
)

CODE_MARKERS = (
    "修复",
    "修好",
    "测试",
    "代码",
    "bug",
    "patch",
    "python",
    "pytest",
    "实现",
    "重构",
    "报错",
    "失败测试",
    "sandbox",
)

_TRIVIAL = "trivial"
_SIMPLE = "simple"
_STANDARD = "standard"
_COMPLEX = "complex"


class TaskComplexity(str, Enum):
    """任务复杂度等级。枚举值即状态存储值（稳定字符串）。"""

    TRIVIAL = _TRIVIAL
    SIMPLE = _SIMPLE
    STANDARD = _STANDARD
    COMPLEX = _COMPLEX


def classify_task(goal: str) -> TaskComplexity:
    """确定性分类：普通生产目标按规则分级，测试/场景目标保守保持 STANDARD。"""
    text = (goal or "").strip().lower()
    if not text:
        return TaskComplexity.STANDARD
    # 测试/场景目标：保持既有行为（负面场景、沙箱、fixture 测试）
    if goal.startswith(("scenario:", "sandbox_")) or text.startswith(("scenario:", "sandbox_")):
        return TaskComplexity.STANDARD
    if text.startswith("conversation_followup:"):
        return TaskComplexity.SIMPLE
    # Runtime facts and identity need no tools; resolve them before the generic
    # SIMPLE marker "介绍一下" can route them into research.
    if any(marker in text for marker in TRIVIAL_MARKERS) and len(text) <= 24:
        return TaskComplexity.TRIVIAL
    # Explicit multi-stage architecture/report workflows need the wider bounded
    # COMPLEX envelope. Evaluate this before generic comparison/code markers so
    # phrases such as "先给方案再执行" are not flattened to STANDARD.
    if any(marker in text for marker in COMPLEX_MARKERS):
        return TaskComplexity.COMPLEX
    # M7-A4B: background scheduling is a bounded single-step task-management
    # request handled by the governed background_job tool.
    schedule_markers = (
        "秒后", "分钟后", "小时后", "每天", "每隔", "每30秒", "每1小时",
        "后台任务", "后台", "提醒我", "定时", "暂停", "继续", "取消", "别再看",
        "别再检查", "有哪些后台", "schedule", "定时任务", "预约",
    )
    if any(marker in text for marker in schedule_markers):
        return TaskComplexity.SIMPLE
    # 代码类任务：完整编排（可能需要 Executor/Sandbox/审批）。
    # 注意：SIMPLE 只读动词（找/查/看/检查）优先于 CODE 判定——"检查这个
    # Python 文件"是只读研究（researcher 可完成），不应引出让 Executor 失效的编排。
    if any(marker in text for marker in MULTI_STEP_MARKERS):
        return TaskComplexity.STANDARD  # 多步研究/对比/评估：完整编排
    if any(marker in text for marker in SIMPLE_MARKERS):
        return TaskComplexity.SIMPLE
    if any(marker in text for marker in CODE_MARKERS):
        return TaskComplexity.STANDARD
    return TaskComplexity.STANDARD
