# CueTrail

CueTrail 是面向条件、约束和步骤的记忆系统：保留用户原文，并在当前请求满足适用范围时，返回少量有来源依据的程序记忆（Procedure）。本仓库提供 **CueTrail v0.30 / V77** 的运行源码、构建清单、合同测试和运行说明，用于 Agent Memory Challenge 的 **Textual / 开源方法榜** 接入与复现。

参赛服务实现 `Add` 和 `Search`；最终回答及评分由 AML 平台统一执行。记忆服务不调用生成式 LLM，也不返回当前问题的最终答案。

## 方法概览

1. **保存来源。** 同步 Add 将消息、角色、会话、原始时间戳与请求身份持久化，保留可检索的原文及向量。
2. **表示程序。** 从受支持的明确表述中构造带适用范围、触发条件、步骤、原文区间、来源哈希、权限类别和版本的 Procedure。
3. **核对当前意图。** 区分请求执行与回顾历史，核对主题、显式前提、用户身份、来源版本及撤回记录。当前用户对前提的陈述不代表系统已验证外部环境。
4. **返回证据。** 满足条件时，在第一条原始检索结果之后加入最多两张程序证据卡；否则沿用原检索结果。卡片本身不执行步骤，也不自动采纳长期规则。

V77 的程序通道是确定性解析与触发，启用条件为 `query_document_evidence`、`top_k=100` 且未进入受保护的文档先验路径。卡片合计最多 6,000 字符，并服从总证据预算 24,000 字符。来源发生变化、条件不明、预算不足或核验失败时回退。

| 来源类别 | 处理方式 |
|---|---|
| `user_constraint` | 明确的用户约束；仍需核对适用范围、有效版本和生命周期 |
| `user_confirmed_habit` | 受支持的用户明确确认，保留建议与确认两份来源 |
| `assistant_suggestion` | 未确认的建议，可作为历史归因证据，不自动变为执行约束 |

当前解析器支持明确格式的中英文程序、显式确认、绑定撤回和前提见证；不声称可以可靠理解任意自然语言中的隐含规则。研究用的语义选择器与其他实验模块不属于 V77 服务入口的执行链。

## 版本与复现入口

| 项目 | 值 |
|---|---|
| 系统 / 参赛版本 | CueTrail / v0.30（V77） |
| Python 服务入口 | `cuetrail_native.server:app` |
| 公开运行源码快照 | [`8f08ec79a8bea985c0962f9fbed5398977af54ca`](https://github.com/jht200410/cuetrail/tree/8f08ec79a8bea985c0962f9fbed5398977af54ca) |
| 干净 Git 检出的运行构建 SHA256 | `b314607b21aae56132d71133c9fc79ed0b3fd642406ecd9cfc2ed29743139a44` |
| 文件核验 | [`runtime/manifest.json`](runtime/manifest.json)、[`vendor/manifest.json`](vendor/manifest.json) |
| 完整安装、配置与启动 | [运行指南](docs/RUN_GUIDE.zh-CN.md) |
| 参评身份与运行记录的区别 | [版本核对说明](docs/EVALUATION_VERSION.zh-CN.md) |

本次仓库补充仅修改文档，运行构建清单和代码保持不变。历史部署清单的 CRLF 换行产生 `be50255b…` 构建标识，与上表 LF 清单包含相同的运行文件哈希；另有一次查询长度恢复构建，包含实际代码差异。具体身份与复现范围见版本核对说明。Python 分发包的 `0.1.0` 是打包版本，不是平台登记的系统版本。

## 安装与构建

需要 Python 3.10 或更新版本，建议使用独立虚拟环境。以下命令在仓库根目录执行：

```shell
git clone https://github.com/jht200410/cuetrail.git
cd cuetrail
python -m venv .venv
```

Linux / macOS 执行 `source .venv/bin/activate`；Windows PowerShell 执行 `.\.venv\Scripts\Activate.ps1`。然后安装锁定依赖并构建：

```shell
python -m pip install -r vendor/context-weave-exact32/requirements.txt
python -m pip install --no-deps -e '.[native]'
python scripts/verify_vendor.py
python scripts/build_runtime.py --output runtime/build-v77
```

目标构建目录必须不存在。脚本逐文件验证 SHA256 后复制运行源码，不含凭证、数据库、模型权重或评测数据。配置环境、启动服务及核对 `source_build_id` 的完整步骤见[运行指南](docs/RUN_GUIDE.zh-CN.md)。

## 模型与关键参数

| 项目 | V77 配置 |
|---|---|
| Embedding | 百炼原生 HTTPS 接口，`text-embedding-v4` |
| 向量维数 / 批量 | 1,024 / 10 |
| 检索模式 | `query_document_evidence` |
| 返回证据预算 | `AE_CONTEXT_CHARS=24000`，单位为字符 |
| 存储 | SQLite，实例独立持久化路径 |
| 记忆服务生成式 LLM 调用 | 0 |
| Answer / Judge | 由赛事平台执行，仓库不更改其模型、提示或评分 |
| Full 申报请求并发上限 | Add 16 / Search 16 |
| 正式 Search | `top_k=100` |

Embedding 需要参赛方自行提供有效服务凭证并承担调用费用。24,000 字符是本系统选择与打包记忆的预算，不是赛事 API 的通用请求上限。

## Add / Search 接口

`GET /health` 无需鉴权；`POST /add` 与 `POST /search` 支持 `Authorization: Bearer …`、`Authorization: Token …` 或 `X-Api-Key`。密钥通过私有环境提供。

以下均为人工编写的演示数据。Textual 的 `content`、`query` 使用字符串；本参赛版本未实现多模态图片内容数组。

Add 请求：

```json
{
  "request_id": "docs-demo:add-1",
  "user_id": "docs-demo:user-a",
  "session_id": "docs-demo:session-1",
  "messages": [{
    "role": "user",
    "timestamp": 1704067200000,
    "content": "Always include the backup checksum when I ask about backup checks."
  }]
}
```

持久化完成且后续 Search 写后可见时返回 HTTP 200：

```json
{
  "success": true,
  "request_id": "docs-demo:add-1",
  "user_id": "docs-demo:user-a",
  "session_id": "docs-demo:session-1"
}
```

Search 请求不带 `session_id`；选择题可在顶层传入 `options` 文本数组：

```json
{
  "user_id": "docs-demo:user-a",
  "query": "How should I prepare backup checks?",
  "top_k": 100
}
```

成功响应顶层为 `data` 数组，每项至少包含稳定的 `id` 和非空 `content`。无相关记忆时返回 `{"data": []}`。返回顺序就是交给 Answer 的证据优先顺序，条目数不超过本次 `top_k`；程序卡仍是附有来源的记忆证据。

五项接入约束：

- **隔离：** 仅在请求的 `user_id` 内检索，同一用户可跨 `session_id` 检索。
- **写后可见：** Add 不以后台排队完成作为成功条件。
- **幂等：** 以 `(user_id, request_id)` 识别写入，并检查载荷身份；相同请求不重复写入，同一身份不同内容返回 409。
- **标准结构：** Add 原样回传三个 ID，Search 返回 `data` 数组并遵守 `top_k`。
- **返回记忆：** 不将当前问题答案、选项字母或金标伪装为记忆。

非法载荷返回 422，鉴权失败返回 401；服务未配置鉴权或 embedding 暂不可用时返回 503，后者附 `Retry-After: 5`。返回 409 不是写入成功。重试必须保留原始 `request_id`、`user_id`、`session_id` 和消息载荷。

## 验证与运维

```shell
python -m unittest discover -s tests
```

2026-11-04 本地 321 项合同测试通过，无跳过；测试使用合成数据和确定性测试向量，覆盖程序触发、原文绑定、确认、撤回、用户隔离、幂等与接口行为。平台 API 同日确认既有 Textual Full 任务状态为 `succeeded`，完成时间为 2026-11-03 13:23:18（Asia/Shanghai）；正式榜单与成绩发布以 AML 复核为准。

已受理的 Full 应保留固定代码、模型、关键参数、已写入记忆、命名空间与幂等记录。发生故障时保留脱敏时间、阶段、状态码与构建身份；涉及参评实现更改或数据无法恢复时，先由 AML 确认处理方式。评测数据仅用于评测，保持私有，并按赛事要求在任务完成后 30 天内删除；延期保留需事先取得书面同意。

## 目录与许可证

| 路径 | 内容 |
|---|---|
| `src/cuetrail_native/` | V77 服务入口、原生存储接入与证据卡注入 |
| `src/cuetrail_governance/` | 来源权限、确认、撤回、前提与程序库存核验 |
| `src/cuetrail_scope/` | 程序范围与触发模块，亦包含研究用选择器 |
| `src/cuetrail/` | 独立程序记忆库及实验模块 |
| `vendor/` | 构建所需依赖源码、来源清单及许可证 |
| `runtime/`、`scripts/` | 运行文件清单、完整性验证与构建脚本 |
| `tests/`、`examples/` | 合成合同测试和示例 |
| `docs/` | 完整运行与版本核对说明 |

仓库采用 [MIT License](LICENSE)。随附依赖的许可证位于各自目录，来源与文件身份保留在 `vendor/manifest.json`。

赛事协议参考：[参赛说明](https://agentmemoryleaderboard.ai/rules)、[API Guide](https://agentmemoryleaderboard.ai/api-guide)、[Documentation](https://agentmemoryleaderboard.ai/docs)。接入字段、重试与数据要求以赛事现行文档和主办方对该参评版本的确认为准。
