# PRODUCT-01 扩展验收报告

- 执行时间: 2026-08-12 16:51:05
- model_mode: fake（离线确定性基线）

## 1. 语义变体（20 个，纠偏令 032）

| goal | status | failure_code | tools | rework | replan | latency_s |
|---|---|---|---|---|---|---|
| 这个项目最近更新频繁吗？ | completed | - | 2 | 0 | 0 | 0.24 |
| 帮我查查 crewai 的 license。 | completed | - | 2 | 0 | 0 | 0.2 |
| 帮我总结一下这个项目是干嘛的。 | completed | - | 2 | 0 | 0 | 0.2 |
| 帮我看看项目的依赖有没有问题。 | completed | - | 2 | 0 | 0 | 0.21 |
| 搜一下 crewai 和 langgraph 哪个活跃。 | completed | - | 2 | 0 | 0 | 0.2 |
| 最近大家都在用什么 agent 框架？ | completed | - | 2 | 0 | 0 | 0.19 |
| 帮我分析一下这个项目的结构。 | completed | - | 2 | 0 | 0 | 0.18 |
| 看看最近 Agent 框架里哪些项目比较火。 | completed | - | 2 | 0 | 0 | 0.19 |
| 有没有类似的项目可以参考？ | completed | - | 2 | 0 | 0 | 0.2 |
| 找几个热门 Agent 项目 | completed | - | 2 | 0 | 0 | 0.18 |
| 这个文件夹里都有什么？ | completed | - | 2 | 0 | 0 | 0.19 |
| 帮我看看 GitHub 上比较火的 agent 库。 | completed | - | 2 | 0 | 0 | 0.25 |
| langgraph 的许可证是什么？ | completed | - | 2 | 0 | 0 | 0.31 |
| 帮我列一下这个目录里的文件。 | completed | - | 2 | 0 | 0 | 0.26 |
| 找几个和这个项目差不多的开源项目。 | completed | - | 2 | 0 | 0 | 0.26 |
| 帮我搜几个类似 JARVIS 的项目。 | completed | - | 2 | 0 | 0 | 0.26 |
| GitHub 上最近有什么值得看的 AI Agent 开源项目？ | completed | - | 2 | 0 | 0 | 0.26 |
| 这个仓库主要是做什么的？ | completed | - | 2 | 0 | 0 | 0.28 |
| 有哪些 AI 智能体框架值得关注？ | completed | - | 2 | 0 | 0 | 0.26 |
| 看看这个项目用了啥技术栈。 | completed | - | 2 | 0 | 0 | 0.25 |

## 2. 对抗性普通用户输入（纠偏令 033）

| goal | status | failure_code | tools | rework | replan | latency_s |
|---|---|---|---|---|---|---|
| [错别字] 帮我查一个 guthub 上热门的项目 | completed | - | 2 | 0 | 0 | 0.24 |
| [错别字] 帮我找一个热门的 giithub 项目 | completed | - | 2 | 0 | 0 | 0.24 |
| [口语] 哥们帮我找几个火的 agent 项目呗 | completed | - | 2 | 0 | 0 | 0.25 |
| [口语] 这项目咋样，帮我看看 | completed | - | 2 | 0 | 0 | 0.27 |
| [短句] 找项目 | paused | - | 0 | 0 | 0 | 0.2 |
| [短句] 总结 | paused | - | 0 | 0 | 0 | 0.19 |
| [模糊] 做点东西 | paused | - | 0 | 0 | 0 | 0.98 |
| [模糊] 帮我搞一下 | paused | - | 0 | 0 | 0 | 0.19 |
| [指代] 第二个 | paused | - | 0 | 0 | 0 | 0.19 |
| [指代] 就按刚才那个 | paused | - | 0 | 0 | 0 | 0.2 |
| [连续追问] 继续 | paused | - | 0 | 0 | 0 | 0.2 |
| [情绪化] 算了别改了 | paused | - | 0 | 0 | 0 | 0.19 |
| [中英混] 帮我 search 一下 agent 项目 | completed | - | 2 | 0 | 0 | 0.28 |
| [无标点] 帮我找几个热门的agent项目 | completed | - | 2 | 0 | 0 | 0.25 |
| [反义否定] 不用改代码，就看看 | completed | - | 2 | 0 | 0 | 0.47 |

## 3. Permission Mode 子集（SAFE 5 + MAXIMUM 5，纠偏令 035）

| goal | status | failure_code | tools | rework | replan | latency_s |
|---|---|---|---|---|---|---|
| [safe] 帮我找几个热门的 GitHub AI Agent 项目 | completed | - | 2 | 0 | 0 | 0.25 |
| [safe] 总结这个项目 | completed | - | 2 | 0 | 0 | 0.17 |
| [safe] 帮我查一下 langgraph 和 crewai 的区别 | completed | - | 2 | 0 | 0 | 0.19 |
| [safe] 列出当前目录下的文件 | completed | - | 2 | 0 | 0 | 0.17 |
| [safe] 现在几点了 | completed | - | 0 | 0 | 0 | 0.13 |
| [maximum] 帮我找几个热门的 GitHub AI Agent 项目 | completed | - | 2 | 0 | 0 | 0.23 |
| [maximum] 帮我分析一下这个项目的代码结构 | completed | - | 2 | 0 | 0 | 0.18 |
| [maximum] 总结这个项目 | completed | - | 2 | 0 | 0 | 0.2 |
| [maximum] 帮我查一下 crewai 的 license | completed | - | 2 | 0 | 0 | 0.19 |
| [maximum] 检查一下这个 Python 文件有没有明显问题 | completed | - | 2 | 0 | 0 | 0.2 |

## 4. 10-turn 连续会话（纠偏令 034）

| goal | status | failure_code | tools | rework | replan | latency_s |
|---|---|---|---|---|---|---|
| turn1: 帮我找几个热门的 GitHub AI Agent 项目 | completed | - | 2 | 0 | 0 | 0.25 |
| turn2: 第二个项目详细看看 | completed | - | 2 | 0 | 0 | 0.17 |
| turn3: 跟我们的项目比一下 | completed | - | 2 | 0 | 0 | 0.2 |
| turn4: 哪些东西值得借鉴 | completed | - | 2 | 0 | 0 | 0.18 |
| turn5: 先别改代码 | paused | - | 0 | 0 | 0 | 0.12 |
| turn6: 那写个方案 | paused | - | 0 | 0 | 0 | 0.87 |
| turn7: 继续 | paused | - | 0 | 0 | 0 | 0.11 |
| turn8: 把第一项实施 | paused | - | 0 | 0 | 0 | 0.13 |
| turn9: 看一下结果 | paused | - | 0 | 0 | 0 | 0.11 |
| turn10: 还有问题吗 | paused | - | 0 | 0 | 0 | 0.11 |

## 汇总

- 语义变体: 20/20 completed
- 对抗性输入: 7/15 completed，可解释结果 15/15
- Permission Mode: 10/10 completed（SAFE/MAXIMUM 各 5）
- 10-turn 会话: 4/10 completed；依赖会话上下文的 turn: [5, 6, 7, 8, 9, 10]
- 说明: 指代/连续追问类输入依赖会话状态，CLI 单任务模式返回 paused/澄清（可解释，非崩溃）；完整会话上下文为 UI/session 层能力，属后续待办。
