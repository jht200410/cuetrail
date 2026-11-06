# 程序案例开发与构建核验

CueTrail 的程序记忆实现位于 `src/`，案例位于 `procedure_cases/`，行为规范测试位于 `specifications/`。案例变更应检查适用条件、约束、来源证据与返回结果之间的一致性。

## 准备与测试

在独立虚拟环境中，从项目根目录执行：

```shell
python -m pip install -e ".[native]"
python -m unittest discover -s specifications -p "test_*.py"
```

测试使用合成输入和模拟编码器；实际运行所需凭据与数据库应独立配置。服务启动和接口约定见 [运行指南](RUN_GUIDE.zh-CN.md)。

## 固定运行构建

`vendor/` 和 `runtime/` 保存运行依赖及其身份清单。先核验依赖，再将运行构建输出到一个新目录：

```shell
python scripts/verify_vendor.py
python scripts/build_runtime.py --output <新目录>
```

构建对应原运行清单所标识的版本。开发目录的案例或规范测试通过，不会自动改变已发布构建。

开发文件和固定材料的哈希检查分别为：

```shell
python scripts/verify_layout.py
python scripts/verify_layout.py --frozen-only
```

许可见根目录 [LICENSE](../LICENSE)，依赖身份以 `vendor/manifest.json` 为准。
