# SECURITY_INCIDENT_001：运行环境配置凭据误入库

状态：`SEC-01 CODE REMEDIATED / BLOCKED_BY_SECRET_ROTATION`（凭据轮换待用户确认）

## 1. 事件时间线

| 时间 | 事件 |
| ---- | ---- |
| M3-C 开发期 | 运行环境生成 `reasonix.toml`（含 API Key），在 `git add -A` 时被误纳入暂存区 |
| `e38b29b` | `reasonix.toml` 随 "feat: sandbox runtime fixes, rollback, cli/api" 首次进入提交历史（首次带入提交） |
| `86ea660` | 检出后立即移除：`git rm --cached reasonix.toml` 并加入 `.gitignore`（移除提交） |
| M3-C 封板 | 双审与证据包扫描均未覆盖 Git 历史（只扫描工作树/打包内容），泄漏未被发现 |
| 总管令 008 | 要求 SEC-01 凭据泄漏事件封板：全范围定位、历史清理、证据重扫、防复发 |

## 2. 根因

- `git add -A` 一次性纳入整个工作树，未先检查新增文件清单。
- 提交前无秘密扫描钩子（2.7-2 缺失），打包扫描也不覆盖 Git 对象库。
- 运行环境配置与源码同目录，且文件名未被 `.gitignore` 覆盖。

## 3. 影响范围

- 仓库：本地 `D:\agent`（**无 remote，从未 push**，风险未外溢）。
- 泄漏文件：`reasonix.toml`（运行环境配置文件）。
- 泄漏提交：首次带入 `e38b29b`（原哈希，历史重写后见 §7 对照表）；移除提交 `86ea660`。
- 泄漏 Blob：`7f5ddf95028966eba8b35de0a1f3e3f8c05b0e6b`。
- 凭据类型：API Key（`sk-` 前缀）。
- 凭据 Provider：openai-compatible（配置文件未设 base_url，指向默认 Provider）。
- 凭据指纹：`sha256(d5a07be50d57...)`（仅显示前 12 位，SEC-01 原则）。
- 是否被使用：未知（运行环境文件，推测可能被本机进程读取）。
- 是否已推送：**否**（仓库无 remote，从未配置 push）。

## 4. 检测方式

- `git log --all --oneline -- reasonix.toml` 定位提交。
- `git rev-parse <commit>:reasonix.toml` 定位 Blob；内容经共享 `SECRET_PATTERNS`
  （`app/core/secrets.py`，含 sk-/ghp_/AKIA/aws_secret/通用赋值/PEM DOTALL/Bearer）
  识别凭据并只输出 `sha256(secret)` 前 12 位指纹。
- `git reflog --all`、`git stash list`、`git fsck --full --no-reflogs` 排查引用与悬空对象。
- 证据 zip（`artifacts/**/*.zip`）逐个检查 `reasonix.toml` 条目。
- 扫描工具：`scripts/scan_incident.py`（新增，脱敏输出，全部 stdout 经 `redact()`）。

## 5. 修复方式

1. 物理隔离：工作树 `reasonix.toml` 移至 `D:\Reasonix\tmp\sec01-20260805\quarantine\`。
2. 安全备份：`git bundle create pre-rewrite-all.bundle --all`（完整对象+refs）。
3. 历史重写：`git filter-branch --index-filter 'git rm --cached --ignore-unmatch reasonix.toml' --prune-empty -- --all`（仅重写含泄漏的提交链；main / 2 / 3a / 3b / delivery 分支 unchanged，已核实）。
4. Reflog 清理：`git reflog expire --expire=now --all`；删除 `refs/original`。
5. 垃圾回收：`git gc --prune=now --aggressive`（泄漏 Blob 从对象库移除）。
6. 验证：`git log --all -- reasonix.toml` 空、reflog 无泄漏引用、`fsck --full --no-reflogs` clean、全量测试 301 passed。

> **已知残留（sa_20260808_101318/102018 记录）**：`.create_token`（blob `f2a6b6b2`，
> 32 位 hex 凭据 `0c2527a6...`，由提交 1580c9c 引入、f67843d 从树中移除）存在于
> **phase-3c/sandbox-execution 与宿主 delivery 分支**的历史（宿主分支另有同内容
> blob `5565ff84` 副本）。该文件不在本事件（reasonix.toml）范围内，且为裸 hex
> （无 key=/token= 形式），**不在 `SECRET_PATTERNS` 覆盖内**（扫描边界：模式
> 启发式，未覆盖的新形态不会拦截）。仓库无 remote、从未 push，本地暴露风险低；
> 清理历史由总管决定（涉及宿主分支时不得擅自重写）。

## 6. 防复发措施（008 2.7）

1. `.gitignore`：`reasonix.toml`、`.reasonix/`、`.env*`（保留 `.env.example`）默认忽略 ✓
2. 提交前秘密扫描：`githooks/pre-commit`（仅调用受审查脚本，不执行未知项目 Hook）+ `scripts/scan_staged_secrets.py`（staged 内容逐行 + 整段 DOTALL 扫描；豁免按**值前缀锚定**：`SK-PLACEHOLDER`/`TEST-TOKEN-` 且支持 `=`/`:`/`Bearer ` 形式；报告只输出模式 + sha256 指纹）✓
3. 打包前秘密扫描：`scripts/make_m3c_zip.py` 导入共享 `app.core.secrets.SECRET_PATTERNS` ✓
4. CI 秘密扫描：本仓库无 remote/CI；`.github/workflows/secret-scan.yml` 声明 CI 脚本，未来配置 CI 时启用（复用 `scan_staged_secrets.scan_text`）
5. Git Hook 仅阻止秘密提交 ✓
6. 测试用密钥使用明确前缀（`SK-PLACEHOLDER`）✓
7. 真实配置位于仓库外（环境变量，`env_file=None`；`.env.example` 仅占位）✓
8. 配置对象 `repr=False` ✓（M3-B）
9. 错误/审计/Trace 统一 `redact()` ✓（M3-B）
10. Incident 回归测试：`tests/test_sec01_incident.py` 7 项 ✓

## 7. 原提交对照表（历史重写后）

| 原哈希 | 新哈希 | 说明 |
| ------ | ------ | ---- |
| `dbd276e` | `3587bee` | docs: M3C_EVIDENCE final |
| `ecbfa4c` | `ee26c32` | chore: m3c evidence packaging script |
| `71c980c` | `5ad15e2` | docs: M3C_EVIDENCE final（重写后该链整体重排，以 `git log` 为准） |
| `386ece3` / `f0f83fa` / `95531a8` / `86ea660` / `e38b29b` 等 | 见 `artifacts/review/m3c-git-log.txt`（20 条全量） | 含泄漏链整体重写 |

## 8. 是否需要凭据轮换

**是。** 凭据已进入本地 Git 历史（无论是否 push），按最小权限原则必须轮换：

1. 用户在 Provider 控制台吊销旧 API Key。
2. 创建新 Key，仅通过环境变量注入（不写入仓库任何文件）。
3. 完成后设置 `AI_TEAM_SECRET_ROTATION_CONFIRMED=true`（本机、不入库）。

系统读取该环境变量作为轮换确认（008 2.3）；未设置时本阶段状态为
`BLOCKED_BY_SECRET_ROTATION`，M3-C **不得** merge 回 main、M4-A 分支不得创建。

## 9. 当前状态

- 历史清理：完成（log/reflog/fsck/stash/工作树全 clean，证据 zip 无泄漏条目）。
- 证据包：`artifacts/review/m3c-source-clean.zip`（139 files，扫描 clean）已重生成，旧 `m3c-source.zip` 已删除。
- 凭据轮换：**待用户确认**。
- 结论：`SEC-01 CODE REMEDIATED / BLOCKED_BY_SECRET_ROTATION`。

## 10. 备份位置

- `D:\Reasonix\tmp\sec01-20260805\pre-rewrite-all.bundle`（重写前完整对象库）
- `D:\Reasonix\tmp\sec01-20260805\quarantine\reasonix.toml`（隔离的泄漏文件）
- 凭据轮换确认后，按 008 2.4-8 彻底删除旧仓库备份。
