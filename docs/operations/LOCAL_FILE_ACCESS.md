# 本地文件只读访问（docs/operations/LOCAL_FILE_ACCESS.md）

对应总管令 006 八。M3-B 实现。

## 1. 配置允许根目录

```bash
export AI_TEAM_ALLOWED_READ_ROOTS="D:/projects"          # 分号分隔多个根
ai-team-os allowed-read-roots                            # 查看生效根目录
```

默认没有允许目录——未配置时本地文件工具全部不可用（确定性拒绝）。

## 2. 项目别名（推荐用法）

CLI/API 不鼓励传任意绝对路径，使用别名映射到允许根目录的子目录：

```bash
ai-team-os run local_project_audit --model-mode real --project myapp
# 等价读取范围：D:/projects/myapp/**（别名不存在时回退整个根）
```

## 3. 安全边界

- 拒绝：绝对路径、`..`、符号链接/Junction 逃逸、UNC（`\\server`）、ADS（`file:stream`）、
  设备路径（CON/NUL/COM1...）、大小写与短路径绕过。
- 默认拒绝敏感文件（即使位于允许根内）：.env* / *.pem / *.key / id_rsa / id_ed25519 /
  credentials* / secrets* / .aws/ / .ssh/ / .git/config / 浏览器配置。
- 限制：单文件 2MB、目录 500 项、二进制拒绝、编码检测（UTF-8/UTF-16）、
  PDF 页数 100（pypdf 依赖缺失时明确报错）、CSV 行 5000/列 200、JSON 深度 20。

## 4. 读取内容

全部标记不可信外部数据（UNTRUSTED_EXTERNAL_CONTENT）；读取结果经 Tool Gateway
固化 Evidence（快照落 runtime/evidence/，已脱敏）。
