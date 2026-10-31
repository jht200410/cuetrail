# CueTrail v0.30 / V77 运行指南

本仓库包含完整运行源码、依赖源码及许可证。运行入口为
`cuetrail_native.server:app`。`runtime/manifest.json` 固定所有部署文件的
SHA256；`vendor/manifest.json` 记录依赖来源和文件身份。源码中的依赖版本信息
与许可证保留。作者的原创性说明位于 `AUTHOR_ORIGINAL_WORK.md`，当前留空。

## 安装与构建

使用 Python 3.10 或更新版本，在独立虚拟环境中执行：

```shell
python -m pip install -e '.[native]'
python scripts/verify_vendor.py
python scripts/build_runtime.py --output runtime/build-v77
```

构建目录必须不存在。脚本只复制经 SHA256 核验的源文件，不启动模型、不下载
权重、不包含凭证、数据库或评测数据。Linux 与 Windows 使用同一份运行源码。

## 配置与启动

通过私有环境文件或进程环境设置以下项目，凭证不要写入仓库：

| 环境变量 | 设置 |
|---|---|
| `MEMORY_API_KEY` | 已登记的 Add/Search 鉴权凭证 |
| `AE_DATABASE` | 本实例持久化 SQLite 的绝对路径 |
| `AE_EMBEDDING_BACKEND` | `dashscope` |
| `DASHSCOPE_API_KEY` | 本人提供的 embedding 服务凭证 |
| `AE_EMBEDDING_URL` | 已配置的百炼原生 HTTPS 文本向量接口 |
| `AE_EMBEDDING_DIMENSIONS` | `1024` |
| `AE_EMBEDDING_BATCH_SIZE` | `10` |
| `AE_MODE` | `query_document_evidence` |
| `AE_CONTEXT_CHARS` | `24000` |
| `CUETRAIL_REQUIRE_MANIFEST` | `1` |
| `CUETRAIL_PROCEDURE_AUDIT` | 本实例私有、可写的程序来源审计文件路径 |
| `PYTHONPATH` | 上一步构建目录的绝对路径 |

持久化目录和审计文件须允许实际服务用户写入。生产环境不得设置
`AE_LOCAL_NO_AUTH=1`。使用构建目录作为工作目录，执行：

```shell
python -m uvicorn cuetrail_native.server:app --host 127.0.0.1 --port 18103 --workers 1
```

已有服务器的独立实例为 `memory-lab@m03.service`，由 systemd 注入私有配置。
健康检查不需要鉴权；Add/Search 使用已登记鉴权。前端固定地址为
`https://101.201.226.162/m03/health`、`/m03/add` 和 `/m03/search`。
不要修改其他实例或共用源码目录。

## 接口行为

Add 持久化成功且 Search 写后可见才返回200；同一 user_id/request_id 的同一
逻辑写入幂等，不同内容返回冲突。Search 以 user_id 隔离，允许同一用户跨 session
检索；成功顶层为 `data` 数组，无结果时为空数组，条目数不超过 top_k。
返回内容是来源记忆证据，最终 Answer/Judge 由平台执行。记忆服务生成 LLM 调用为0。

## 验证

```shell
python -m unittest discover -s tests
```

这些是来源、程序、接口与治理合同测试，不代表 Full 成绩。正式提交前还须核验
当前服务的 build、已登记版本与端点、平台实时准入及最终作者材料，并由作者最终确认。
