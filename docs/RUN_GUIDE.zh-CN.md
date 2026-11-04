# CueTrail v0.30 / V77 运行指南

服务入口为 `cuetrail_native.server:app`。本指南介绍公开仓库的构建与运行步骤；版本、构建标识和线上兼容性修复记录见[版本核对说明](EVALUATION_VERSION.zh-CN.md)。文档修订不部署新代码，也不改变已受理 Full 的配置。

## 1. 环境与安装

需要 Python 3.10 或更新版本、Git、可写的持久化目录，以及有效的百炼 embedding 服务凭证。无需本地 GPU 或生成式模型权重；生产环境需要能够访问登记的 embedding HTTPS 端点。

```shell
git clone https://github.com/jht200410/cuetrail.git
cd cuetrail
git rev-parse HEAD
python -m venv .venv
```

激活虚拟环境：

```bash
# Linux / macOS
source .venv/bin/activate
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

使用随运行源码提供的依赖锁：

```shell
python -m pip install -r vendor/context-weave-exact32/requirements.txt
python -m pip install --no-deps -e '.[native]'
python -m pip check
python scripts/verify_vendor.py
python scripts/build_runtime.py --output runtime/build-v77
```

构建目录必须不存在。构建逐文件验证 `runtime/manifest.json` 中的 SHA256，复制 47 个运行文件，并写入 `cuetrail-source-manifest.json`。构建过程不发起模型调用，不复制凭证或数据。需要重新构建时选择另一个新目录，不覆盖现有参评目录。

独立复现公开运行代码时，可在安装前固定到 `8f08ec79a8bea985c0962f9fbed5398977af54ca`。本次文档提交与该快照的运行文件一致，其构建输出应报告：

```text
b314607b21aae56132d71133c9fc79ed0b3fd642406ecd9cfc2ed29743139a44
```

以上是干净 Git 检出的 LF 清单哈希，已用独立检出实际验证。旧工作目录和历史部署清单使用 CRLF，哈希为 `be50255b25d11d1ebb356ed4274095b87e848e39517e64b5a57905b81b05a160`；两者的 JSON 内容及 47 个文件哈希相同。不要仅为统一清单换行而改动正在参评的运行目录。

## 2. 私有环境配置

使用进程环境、私有服务配置或密钥管理工具提供下列配置。服务不会自动读取仓库根目录的 `.env`；仅创建该文件不足以向进程注入变量。不要将有效密钥写入仓库、命令截图或公开运行记录。

| 环境变量 | 设置及含义 |
|---|---|
| `MEMORY_API_KEY` | Add/Search 接口鉴权凭证；正式实例沿用已登记值 |
| `DASHSCOPE_API_KEY` | embedding 提供商凭证 |
| `AE_EMBEDDING_BACKEND` | `dashscope` |
| `AE_EMBEDDING_URL` | 已配置的百炼原生 HTTPS 文本向量端点，无 URL 凭据、查询串或片段 |
| `AE_EMBEDDING_DIMENSIONS` | `1024` |
| `AE_EMBEDDING_BATCH_SIZE` | `10` |
| `AE_EMBEDDING_TIMEOUT` | 每次 embedding HTTP 请求超时，代码默认 `60` 秒；已登记实例沿用原配置 |
| `AE_EMBEDDING_MAX_ATTEMPTS` | embedding 有界尝试次数，代码默认 `3`；已登记实例沿用原配置 |
| `AE_EMBEDDING_MAX_REQUESTS` | 当前进程 embedding 请求预算，代码默认 `0` 表示不设此计数上限，不免除提供商配额 |
| `AE_DATABASE` | 本实例 SQLite 数据库的绝对路径 |
| `AE_MODE` | `query_document_evidence` |
| `AE_CONTEXT_CHARS` | `24000` |
| `CUETRAIL_REQUIRE_MANIFEST` | `1`，启动时要求完整运行清单 |
| `CUETRAIL_PROCEDURE_AUDIT` | 实例私有、可写的程序触发审计文件绝对路径 |
| `PYTHONPATH` | 构建输出目录的绝对路径 |

模型由运行代码固定为 `text-embedding-v4`，向量使用 1,024 维。原生端点路径通常为 `/api/v1/services/embeddings/text-embedding/text-embedding`，不能替换成 OpenAI 兼容端点后声称配置未变。模型、端点、维数及向量角色语义属于持久化向量身份；正式实例复用原配置。

数据库目录及审计文件父目录须允许服务用户写入。审计属于私有评测派生记录，可能包含来源标识及决策信息，同样受数据保留要求约束。生产环境不得设置 `AE_LOCAL_NO_AUTH=1`。

## 3. 启动独立本地实例

以下示例只用于新的本地演示实例，使用端口 **18407**。先在当前终端安全注入两个密钥和 `AE_EMBEDDING_URL`，其余配置如下；不要用本例的数据路径替换已有正式实例的数据库。

Linux / macOS，在仓库根目录执行：

```bash
export PYTHONPATH="$PWD/runtime/build-v77"
export AE_DATABASE="$PWD/data/docs-demo/memory.sqlite3"
export CUETRAIL_PROCEDURE_AUDIT="$PWD/data/docs-demo/procedure-audit.jsonl"
export AE_EMBEDDING_BACKEND=dashscope
export AE_EMBEDDING_DIMENSIONS=1024
export AE_EMBEDDING_BATCH_SIZE=10
export AE_MODE=query_document_evidence
export AE_CONTEXT_CHARS=24000
export CUETRAIL_REQUIRE_MANIFEST=1
mkdir -p data/docs-demo
cd runtime/build-v77
python -m uvicorn cuetrail_native.server:app --host 127.0.0.1 --port 18407 --workers 1
```

Windows PowerShell，在仓库根目录执行：

```powershell
$env:PYTHONPATH = (Resolve-Path -LiteralPath 'runtime/build-v77').Path
$env:AE_DATABASE = Join-Path $PWD.Path 'data/docs-demo/memory.sqlite3'
$env:CUETRAIL_PROCEDURE_AUDIT = Join-Path $PWD.Path 'data/docs-demo/procedure-audit.jsonl'
$env:AE_EMBEDDING_BACKEND = 'dashscope'
$env:AE_EMBEDDING_DIMENSIONS = '1024'
$env:AE_EMBEDDING_BATCH_SIZE = '10'
$env:AE_MODE = 'query_document_evidence'
$env:AE_CONTEXT_CHARS = '24000'
$env:CUETRAIL_REQUIRE_MANIFEST = '1'
New-Item -ItemType Directory -Path 'data/docs-demo' -Force | Out-Null
Set-Location -LiteralPath 'runtime/build-v77'
python -m uvicorn cuetrail_native.server:app --host 127.0.0.1 --port 18407 --workers 1
```

在第二个终端使用无需鉴权的健康检查：

```shell
curl http://127.0.0.1:18407/health
```

PowerShell 可改用 `Invoke-RestMethod -Uri 'http://127.0.0.1:18407/health'`。确认 `status=ok`、系统/版本正确、`source_build_id` 等于构建输出，并核对 embedding、批量、检索策略、证据预算和生成调用数。源码清单不一致时先查明原因。

## 4. 接口核验

请求与响应示例见[README](../README.md#add--search-接口)。本服务的路径相对于部署根为 `/add`、`/search`、`/health`。文本 `content` 与 `query` 必须是非空字符串，`timestamp` 为可选 Unix 毫秒整数；Search 的 `top_k` 为 1 至 100 的整数，正式配置为 100。

使用独立的人工演示用户和演示数据库核验以下行为，不向正式评测命名空间写入测试内容：

1. 无鉴权 Health 返回 200；错误鉴权 Add/Search 返回 401。
2. Add 成功响应为 `success=true`，原样返回 `request_id`、`user_id`、`session_id`；响应之后即可检索。
3. 原样重复同一请求不产生重复记忆；同一 `(user_id, request_id)` 改变内容返回 409。不能以 409 当作成功。
4. 相同用户的不同 Add 会话可一起检索；另一个用户不能取到这些记忆。
5. Search 只有 `data` 数组包装、条目数不超过 `top_k`，返回证据而非答案。没有相关记忆时为 `{"data": []}`。
6. 支持的明确程序在相关请求下可返回来源绑定卡片；助手的一次建议不会因被写入就成为长期用户约束。

原请求重试需保留全部逻辑载荷，包括时间戳；不能重生成 `request_id` 来规避冲突。Search 不接受 `session_id`、金标或答案字段。选择题的 `options` 仅为平台传入的候选文本，不包含正确答案标记。

## 5. 合同测试

在仓库根目录、已安装依赖的环境中执行：

```shell
python -m unittest discover -s tests
```

测试使用人工合成来源及确定性向量，不调用生产 embedding，也不运行官方 Answer/Judge。覆盖程序原文、范围、权限、版本、确认、撤回、前提见证、证据预算和原生 Add/Search 行为。2026-11-04 验证结果为 321 项通过、0 项跳过。测试报告应同时查看 `skipped`；缺依赖导致的跳过不能视为完整验证。若从尚未安装本包的源码目录运行，应先完成安装，避免 `ModuleNotFoundError`。

## 6. 已登记服务与容量

| 项目 | 登记 / 既有部署记录 |
|---|---|
| Add | `https://101.201.226.162/m03/add` |
| Search | `https://101.201.226.162/m03/search` |
| Health | `https://101.201.226.162/m03/health` |
| 生产后端端口 | `18103`，单 Uvicorn worker |
| 服务单元 | `memory-lab@m03.service` |
| 原持久化库 | `/var/lib/memory-lab/m03/memory.sqlite3` |
| Full 请求并发上限 | Add 16 / Search 16 |
| m03 内存硬上限记录 | 10 GiB；并非独占容量或吞吐保证 |

并发上限不代表每秒请求数。实际延迟与容量受用户历史规模、embedding 限流、磁盘和共享宿主机资源影响；未建立完整 Full 规模的负载保证。代码的 embedding 请求超时与赛事端到端请求超时是不同限制。平台按官方策略重试；本服务 embedding 异常返回 503 和 `Retry-After: 5`。

正式实例由 systemd 注入私有配置；不要将演示启动命令直接替换到正式服务。正式 Full 已受理时，保留代码、模型、算法、关键参数、原数据库、命名空间与幂等记录；不清库后续跑。需要改变参评实现，或原始数据无法恢复时，先联系 AML 确认处理方式。不要修改共享源码目录或其他实例。

故障排查先保存脱敏阶段、时间、状态码、构建身份和必要资源指标。不要公开评测请求正文、私有记忆、向量库或有效凭证；评测数据及派生副本只用于评测，按赛事要求在完成后 30 天内删除，延长保留需事先取得书面同意。
