方案 C 目前不能按本轮标尺验收：`exclude` 的优先级和生成文件的审计均存在已复现的绕过，另有审计遗漏、动态注册及 CI 随配置变化失配的问题。

# LMCache #6315 方案 C：独立对抗性审核

审核日期：2026-11-13，多伦多时间。只读审核实现；没有修改、推送五个实现分支，没有评论或操作 PR。报告及复现材料放在公开 fork 的独立报告分支。

## 审核范围与口径

先读了两份项目迁移约定、仓库 `AGENTS.md`、`docs/coding_standards.md`、`pr-review` 指引、边界设计，以及 #6305、#6315 和五个 PR 的当前描述、评审。用户本轮明确授权的新打包工具是审核对象，不将“纯迁移”误解为禁止这些工具本身存在。

**主审核对象是任务指定的快照**，代码行号均指最终叠加 head `dea67b3b4bb666f42ddfa1d94ae579824536d16a`。读取 GitHub 时五个 PR 已重新整理并 rebase，因此同时核对了最新快照：

| PR | 任务指定 head | 读取时当前 head | 当前 merge-base |
|---|---|---|---|
| [#6582](https://github.com/LMCache/LMCache/pull/6582) | `d848990d` | `0bc6be07` | `3bfa771a` |
| [#6584](https://github.com/LMCache/LMCache/pull/6584) | `68a27383` | `f0fb4ea8` | `3bfa771a` |
| [#6594](https://github.com/LMCache/LMCache/pull/6594) | `e13269a6` | `86710315` | `3bfa771a` |
| [#6597](https://github.com/LMCache/LMCache/pull/6597) | `7f4df2bd` | `b5ead5a6` | `3bfa771a` |
| [#6630](https://github.com/LMCache/LMCache/pull/6630) | `dea67b3b` | `03e89b19` | `3bfa771a` |

指定快照基线是 `58c11e386d804854608e132aa94712608272ab04`；读取时 upstream/dev 是 `bcafb031401d404a5dabae4853f5e23bf9e5685c`。当前五个 PR 都是 Draft，base 都是 upstream/dev；它们实际上叠加依赖，不能当作五条互不依赖的改动。

新旧最终 head 的工具差异只涉及禁止写 `__pycache__`、README 清理提示和 shellcheck 指令；下列发现涉及的关键逻辑没有修复。最新 `check_imports.py` 也复现了兼容文件排除案例。旧快照写 `__pycache__` 的问题已在新 head 修复，不计作当前新发现。用户预先列出的已知事项也不重复计入发现。

证据保存在报告旁的 `6315-scheme-c-evidence/`。其中 manifest 实验都修改独立副本，源工作树保持不变。另明确标注的 wheel 变异实验修改 wheel 副本，不冒充 manifest 实验。

以下命令缩写对应本次工作目录；换环境时替换三个绝对路径即可：

```bash
R=/workspace/scratch/8d58f04f4058/LMCache-review
E=/workspace/scratch/8d58f04f4058/evidence
P=/workspace/scratch/8d58f04f4058/venv-build/bin/python
cd "$R"
B() { CC=gcc CXX=g++ NO_GPU_EXT=1 "$P" -B tools/client_wheel/build.py --no-isolation --boundary transitional --version 0.0.0.dev0 "$@"; }
I() { "$P" -B tools/client_wheel/check_imports.py --source-tree . --boundary transitional "$@"; }
A() { "$P" -B tools/client_wheel/audit.py --boundary transitional "$@"; }
```

## 高严重程度

### H1．`exclude` 不优先于 compat / transitional，默认配置本身也有重叠

**问题和证据。** `scope.py:78–87` 先判断 `allowed()`，命中即返回 True，之后才看排除。`build.py:93–98` 还明确允许 transitional 与 exclude 重叠。默认的 `platform/base/cache_context.py` 同时出现在 `manifest.toml:147` 的 exclude 和最后一个 transitional 组，因此 transitional wheel 实际只排除六个条目中的五个。

在 manifest 副本末尾新增 **5 行**，排除兼容文件 `lmcache/v1/multiprocess/group_view.py`：

```toml
[[exclude]]
owner = "adversarial-review"
reason = "counterexample"
paths = ["lmcache/v1/multiprocess/group_view.py"]
```

```bash
B --manifest "$E/exclude-shim/manifest.toml" --out "$E/exclude-shim/native-dist"
I --manifest "$E/exclude-shim/manifest.toml"
A "$E/exclude-shim/native-dist/"*.whl --manifest "$E/exclude-shim/manifest.toml" --staging "$E/exclude-shim/native-dist/STAGING_MANIFEST.json"
```

结果：三个命令均退出 **0**；wheel 仍有 **339** 个 `lmcache/` 文件，包含这个明确排除的文件；审计输出 `0 failure(s)`。这不是用户已知的 `from 包 import 模块` 识别问题，而是选文件和审计共用的优先级错误。

另新增 5 行排除 transitional 的 `distributed/api.py`，选文件仍保留它，但静态检查退出 1，报 `excluded, not in boundary_gaps`。也就是说，同一配置在选文件器和 import 检查中的含义并不一致。

**影响。** 配置中的禁止意图可能无声失效；“排除永远优先”不是当前实现的契约。

**建议、估算和归属。** 在选择器入口先处理排除，配置重叠要么报错，要么在保持绝对排除的前提下重新表达迁移期规则；所有工具使用同一结果。不能只调换两行后就宣布修好，因为默认重叠还承担着 transitional 闭包职责。约 **15–35 行代码及少量配置调整**，主要落在 **#6582**，#6584 复核审计结果。

### H2．排除的 protobuf `.pyi` 会被重新生成，审计又把生成文件整体豁免

**问题和证据。** `setup.py:33–40` 无条件调用 protobuf 生成器。`audit.py:46,75,78–81` 将整个 `_proto_gen/\w+.py[i]` 命名区域视为生成物，跳过常规选入与排除判断。

在副本新增 **5 行**，只排除 `lmcache/v1/transport/grpc/_proto_gen/common_pb2.pyi`：

```bash
B --manifest "$E/exclude-generated-pyi/manifest.toml" --out "$E/exclude-generated-pyi/native-dist"
A "$E/exclude-generated-pyi/native-dist/"*.whl --manifest "$E/exclude-generated-pyi/manifest.toml" --staging "$E/exclude-generated-pyi/native-dist/STAGING_MANIFEST.json"
```

结果：选择器确实从 staging 输入拿掉该文件；实际 CPU/native 构建仍重新产出它，wheel 仍为 **339** 个包内文件，审计退出 **0**、输出 `0 failure(s)`。静态检查也退出 0，因为只扫描 `.py`。

**影响。** 即使修好 H1，生成流程仍可绕过排除。这也说明当前“精确白名单”对生成结果实际退化成了按目录和名字形状放行。

**建议、估算和归属。** 配置要能表达生成输入与允许输出；构建后对生成输出再应用排除或给出明确冲突错误。审计只放行明确预期的生成结果，不能无条件豁免整片命名区域。约 **30–60 行**，**#6582 的生成流程 + #6584 的审计**。无需修改业务实现或引入通用插件框架。

## 中严重程度

### M1．审计只约束 `lmcache/`，其他 wheel 顶层及 `.data/scripts/` 没有准入检查

**问题和证据。** `audit.py:69–86` 的集合都从 `p.startswith("lmcache/")` 出发；`main():200–213` 没有补全 wheel 其他路径的白名单，入口点检查只检查 `entry_points.txt`。

在**实际 CPU wheel 的副本**中分别加入：

```text
unexpected_server.py
lmcache_client-0.0.0.dev0.data/scripts/lmcache-server
```

各新增 1 个文件，重新生成合法 RECORD，再运行与基线相同的 `audit.py WHEEL --staging ... --boundary transitional`。两个案例均退出 **0**、输出 `0 failure(s)`。完整复现见 `scripts/run_wheel_probes.py`、`wheel-mutations/results.json`。

例如：`A "$E/wheel-mutations/top-level-module/"*.whl --staging "$E/baseline/transitional/STAGING_MANIFEST.json"`。

**影响。** 独立 artifact audit 并不能保证拦住所有模块、脚本或服务端 CLI 泄漏。当前构建没有被证明产生这些额外文件；组合 CI 的 superset 检查通常还能拦住完整 wheel 没有的额外路径，因此不将其描述成整个 CI 已被绕过。

**建议、估算和归属。** 对 wheel 全部路径做封闭分类：精确的 package 文件、允许的生成物、允许的 dist-info / license，拒绝其他顶层和 `.data` 内容。约 **15–30 行**，**#6584**。

### M2．staging 记录里的源文件哈希没有用于核对 wheel 内容

**问题和证据。** `build.py:153–171,217–230` 记录了文件及 tooling 的 SHA-256；`audit.py:198–203` 对 `staging["files"]` 只取路径，并不读取各文件哈希。

在 wheel 副本的 `lmcache/logging.py` 末尾加 **1 行**：

```python
raise RuntimeError("adversarial audit source mismatch")
```

保持原 staging 记录，更新 wheel RECORD，再运行审计：退出 **0**，`0 failure(s)`。见 `wheel-mutations/source-changed/audit.log`。

命令：`A "$E/wheel-mutations/source-changed/"*.whl --staging "$E/baseline/transitional/STAGING_MANIFEST.json"`。

**影响。** 有效的 RECORD 只能说明 wheel 自己如何描述自己，不能证明它仍是记录中的 canonical 源码。运行时检查可能拦住这个特定的显式异常，但对未被执行的逻辑变化没有同样保障。

**建议、估算和归属。** 对非生成源码与 package data 校验 staging 哈希；生成输入和实际输出明确区分。不要把构建时记录了哈希写成已经完成了内容校验。约 **20–40 行**，**#6584**；若记录实际生成输出，#6582 约再 **10–20 行**。

### M3．`native_allow` 只是上限，缺少必需原生库时审计仍成功

**问题和证据。** `audit.py:205–210` 只遍历已有原生库检查“不允许”，没有检查“应有但缺失”。静态和运行时检查还在 `check_imports.py:218–221,359–363` 将 `native_allow` 中的模块视为可缺失。

从 CPU wheel 副本删除 **1 个文件** `lmcache/lmcache_native.cpython-312-x86_64-linux-gnu.so`，更新 RECORD。审计退出 **0**、`0 failure(s)`，见 `wheel-mutations/native-missing/audit.log`。

命令：`A "$E/wheel-mutations/native-missing/"*.whl --staging "$E/baseline/transitional/STAGING_MANIFEST.json"`。

**影响。** 单独审计无法证明“required native support”存在。当前 workflow 通过 `assert_native_ops.py` 另行补上 CPU/CUDA 的存在与加载检查，所以不是当前整条 CI 会接受缺失 native；问题是 artifact audit 的能力与要求不一致。

**建议、估算和归属。** 在配置中区分允许库与当前构建 profile 的必需库，审计同时检查上下界；保留已有直接加载验证。约 **15–30 行**，**#6584**，#6594 / #6597 只需传递相应 profile 或必需项。

### M4．动态注册的能力丢失检查不到，`scanned` 又一刀切拒绝可选模块的部分排除

**问题和证据。** `check_imports.py:137–142` 只识别绝对字符串常量的 `import_module()`。实际设备注册通过 `_device_detect.py:113–121` 的 `discover_subclasses("lmcache.v1.platform.devices", ...)` 加载。`scope.py:99–105` 对另两个 `scanned` 目录却直接禁止任何部分排除。

两个只改 manifest 的案例：

1. 新增 **5 行**排除 `platform/devices/cpu/__init__.py`，静态检查退出 **0**，CPU/native 构建和审计也均退出 **0**。从两个 wheel 解包后的独立目录运行同一 `get_device_spec("cpu")` 探针，基线输出 `CPU_SPEC CpuDeviceSpec`，排除版输出 `CPU_SPEC None`。删除该模块对应的两条 stale gap 配置后（合计 **7 行增删**），ratchet 也返回 `strict failures == transitional: True`。
2. 新增 **5 行**只排除 `common/kv_format/detectors/atom.py`，检查在读取配置时就退出 **1**：`exclude: ...atom.py is inside scanned ...detectors/; exclude the whole directory`。即使同时移除 ATOM integration 的配置行（合计 **6 行增删**），仍拒绝。`detectors/registry.py:23–26` 实际枚举的是**剩余文件**，不存在“删除任意叶子就必然 import 不存在模块”的规则。

完整证据：`dynamic-probe.json`、两个 manifest diff 及 `exclude-device-cpu-clean-gaps/ratchet.log`。解包探针是有意控制模块来源的差分实验，不冒充完整 clean-venv smoke。

命令分别为 `I --manifest "$E/exclude-device-cpu/manifest.toml"`、`"$P" ../run_dynamic_probe.py`，以及 `"$P" -B tools/client_wheel/check_imports.py --source-tree . --ratchet --manifest "$E/exclude-device-cpu-clean-gaps/manifest.toml"`。scanned 反例用 `I --manifest "$E/exclude-scanned-leaf/manifest.toml"`。

**影响。** 当前既有漏检，也有过度限制。CPU E2E 能发现第一例的后果，但静态闭包不能解释动态能力损失；未执行的其他设备/引擎路径没有同等兜底。第二例使“共享目录内按配置排除一块”无法兑现。删除一个能力是否允许，应由所声明的支持范围决定，不能由两个硬编码目录代替判断。

**建议、估算和归属。** 利用已有 `[smokes]` 检查承诺支持的设备 spec、detector、IPC wrapper 和 gRPC 服务是否可解析；允许配置撤销某项可选能力及其 smoke。不要禁止整个 scanned 目录的所有部分排除，也不需要实现通用 Python 动态执行分析器。约 **20–50 行配置/检查调整**，**#6582 / #6584 / #6594**；支持范围需要用户决定。

### M5．源码和大部分依赖变化不会直接触发本工作流

**问题和证据。** `.github/workflows/build_client_artifacts.yml:19–29` 的 paths 包含工具、构建 glue 及 `requirements/build.txt`，没有 `lmcache/**`、`requirements/common.txt` 等实际内容和运行依赖路径。把例如 `lmcache/v1/common/...py` 作为唯一变更路径代入，全部 paths 均不匹配；不需要执行 Actions 就能确定这一事件不会从该 paths 入口触发。

`pr_full_build.yml:61–68` 是另一入口，但要求非 Draft 且带 `full` 标签。不能据此把没有该标签的源码 PR 说成已持续执行 client 闭包验证。该工作流内部关于“其他源码迁移只 warning”的处理，也只有进入工作流后才生效。

匹配探针读取原 YAML 的 paths，输出（见 `workflow-paths.json`）：`common/custom_types.py=false`、`grpc/protos/common.proto=false`、`requirements/common.txt=false`，对照 `tools/client_wheel/manifest.toml=true`。这只是路径匹配验证，没有声称实际启动过 GitHub Actions。可用 `rg -n 'paths:|tools/client_wheel|requirements/build.txt|lmcache/\*\*|requirements/\*\*' .github/workflows/build_client_artifacts.yml` 核对原配置。

**影响。** 共享目录新增依赖、proto 或源码变化时，client 包的检查可能没有运行；配置和实际源文件的关系要等后续 full build 才暴露。

**建议、估算和归属。** 按用户希望的粗目录加入 `lmcache/**`、相关 `csrc/**`、`requirements/**` 等触发路径，或明确将该调用作为每个相关 PR 的常规门禁。保留迁移期间仅对 stale 状态 warning 的政策，但别将普通闭包失败一起降级。约 **5–15 行 YAML**，**#6582**。

### M6．反例断言绑定具体迁移文件，正常迁移会造成假失败

**问题和证据。** 工作流 `196–204` 用 transitional 当作“完整 wheel”、strict 当作“client”做反例，随后硬性 grep：

```text
not in the full wheel: lmcache/v1/multiprocess/custom_types.py
```

但 manifest 自己在 `157–160` 说明，#6541 之后该文件要从 transitional 变为 compat shim。届时两个 wheel 都包含它：即使这个反例仍因其他 transitional 文件正确失败，grep 也会失败；若所有迁移完成，反例本身会成功，脚本里的 `then exit 1` 仍会报错。README:66 已承认需要随迁移删改这个 grep。

其他反例还固定使用 `multiprocess/server.py`、`logging.py` 和特定 `native_allow` 的 sed 文本（工作流 `123–146,402–409`），也需要对应路径与配置格式继续存在。这里只对已登记的 custom_types 迁移确认必然失效，不把所有路径假设都说成当前故障。

当前实际执行 `"$P" -B tools/client_wheel/check_install.py superset "$E/baseline/transitional/"*.whl "$E/baseline/strict/"*.whl`，退出 1、输出 `64 failure(s)`，其中包含上述 custom_types 行，当前 grep 能通过。未来移为 shim 后的失效是依据该成员关系作出的源码判断；本轮没有实现未来 #6541，也没有声称当前该步骤已经失败。

**影响。** 正常上游迁移可以把有效构建打成红色，而且必须编辑检查脚本才能恢复。它不是在检测产品回归。

**建议、估算和归属。** 从配置实际差集选择反例目标；差集为空时明确跳过“两个边界必须不同”的历史断言。更稳定的是对 wheel 副本注入单一确定的违例，并检查对应错误。manifest 反例统一用副本和 `--manifest`。约 **15–35 行**，主要 **#6594**，其余反例在 **#6584 / #6597** 各少量调整。

### M7．独立 E2E 工具没有关闭遥测，会对外发送运行信息

**问题和证据。** `check_e2e.py:205–216` 直接继承环境启动完整 server；工作流 `222–231` 没有设置 opt-out。既有 `usage_telemetry/identity.py:25–42` 默认启用遥测；`usage_telemetry/mp.py:91–98` 在开启时启动后台发送。已有 `tests/conftest.py:24` 专门设置 `LMCACHE_TRACK_USAGE=false`，独立脚本不经过该 fixture。

首次执行工具时日志出现初始化 usage reporting，自动审批随后明确拒绝向 `stats.lmcache.ai:8080` 发送未授权的运行元数据。该次执行没有取得完整成功报告，不能计为通过。核对 opt-out 代码后，使用更安全的现有配置重新运行：

```bash
LMCACHE_TRACK_USAGE=false DO_NOT_TRACK=1 "$P" -B tools/client_wheel/check_e2e.py \
  --server-python /workspace/scratch/8d58f04f4058/venv-full/bin/python \
  --client-python /workspace/scratch/8d58f04f4058/venv-client/bin/python \
  --transport grpc --report "$E/baseline/e2e-grpc-no-telemetry.json" \
  --logs "$E/baseline/e2e-grpc-no-telemetry-logs"
```

这次退出 **0**；第二次命中 512/512、字节相同、服务端退出并释放端口。

**影响。** 一个本应可控的本地打包验收依赖外部网络，并产生与验证无关的报告；受限运行环境可能直接阻止它完成。

**建议、估算和归属。** 在测试子进程环境显式关闭遥测，或在此 CI job 统一关闭；不要依赖使用者碰巧设置变量。约 **2–6 行**，**#6630**。这是测试工具的隔离缺口，不要求顺带修改生产遥测的默认设计。

## 低严重程度

### L1．安装矩阵和 E2E 不支持自然的相对 venv 路径

**问题和证据。** `check_install.py:50–55` 在临时 cwd 执行传入的 python；`check_e2e.py:183–207,211–213` 也在临时目录使用未绝对化的解释器/脚本路径。对照 `check_imports.py:458–460`，那里专门做了绝对化。

```bash
"$P" -B tools/client_wheel/check_install.py matrix ../venv-matrix/bin/python \
  "$E/baseline/strict/"*.whl "$E/baseline/full-git/"*.whl "$E/baseline/cli/"*.whl
```

实际传入存在的 wheel 后，第一次 pip 调用能启动，但后续临时目录中的检查报：`FileNotFoundError: ... '../venv-matrix/bin/python'`。改用绝对路径，整个矩阵通过。E2E 的相对 server 路径有同样的源码原因。

**影响。** README 风格的本地调用容易失败，错误看起来像 venv 未创建。

**建议、估算和归属。** 在参数入口统一转成绝对路径；保留 venv 的 symlink 语义，使用 `absolute()` / `abspath()`，不要 `resolve()` 到基础解释器。约 **4–8 行**，**#6594 / #6630**。

## 选文件、工具与 workflow 的补充核对

| 边界/文件类型 | 本次结果 |
|---|---|
| `common/` 与 `common_x/` | `matches()` 的尾斜杠前缀边界正确；前者不匹配后者。 |
| 不带尾斜杠的目录 | 视为精确文件路径；把 `common/` 改成 `common`，2 行增删，build 选择校验报 `matches no tracked file`。不会隐式扩大成前缀。 |
| `__init__.py` | 按实际路径选取；排除 import-free 的 `common/__init__.py`，静态检查成功，不能仅凭成功判漏检，namespace package 可以合法存在；CPU provider 的 init 不同，见 M4。 |
| `.pyi` | 普通文件受选择规则控制；生成的 `.pyi` 有 H2 绕过。不能把 `.py` 闭包检查当作 `.pyi` 内容检查。 |
| `.proto` | 基线 wheel 包含 10 个 schema；新增 5 行排除被其他 schema 引用的 `common.proto`，protoc 失败并最终退出 1。没有悄悄构建成功。 |
| 任意数据文件 | 当前 package-data 只覆盖 `*.pyi` / `*.proto`。加入一个实际 JSON 并移除相应 deny 前缀（2 行配置变动），构建成功但审计退出 1：`staged but not shipped: ...config.json`。需要同时修改 package-data 配置；此项被正确拦住，不算遗漏。 |
| 普通共享模块排除 | 5 行排除 `logging.py`，静态退出 1，明确显示 owner / reason。 |
| runtime smoke 反例 | 在 `[smokes]` 新增 1 行，执行 `import lmcache.review_missing_module`；实际运行 253 个模块、7 个 smoke，退出 1：`FAIL smoke: adversarial missing module: ModuleNotFoundError`。此例被正确拦住。 |
| manifest 指纹 | 副本新增注释及空行，共 2 行，产物和 staging 不变；审计退出 1：`scope: the staging record was not built from ...`。此项不等于 M2 所缺的文件内容哈希校验。 |
| deny 区域 | 向 `files` 新增 1 行 `multiprocess/server.py`，实际 build 在 staging 前退出 1：`in a deny area: ...server.py`。 |
| compat / transitional 重叠 | 见 H1；不是统一的“排除优先”。 |
| 按名字、注册表加载 | 只有少量字面量调用可识别；设备发现、IPC wrapper 表及 gRPC descriptor 枚举没有完整静态能力验证，见 M4。 |

工具接口也需纠正一个前提：`scope.py`、`build.py`、`audit.py`、`check_imports.py` 接受 `--manifest`；**`check_install.py` 和 `check_e2e.py` 不接受**，实测 argparse 拒绝。后两者是针对环境/产物的测试，因此本次用实际安装矩阵、wheel 副本和真实请求验证，没有伪造 manifest-only 案例。`setup.py` 是 staging backend，不是独立审核 CLI。

workflow 顺序是：build 两种 wheel → checkout 快照比较 → 两次审计与 transitional 静态检查 → ratchet → 反例 → transitional clean-venv/runtime → strict report → CLI/matrix/superset → full CLI → E2E → 全包变化比较 → 收集产物。额外的 vLLM、CUDA 是独立 job。

必须通过的包括审计、transitional 闭包、实际 runtime 错误、矩阵、superset、E2E。明确只报告/可降级的包括 strict runtime 的 `|| true`、特定条件下的 stale ratchet/runtime gap，以及根打包变化的 compare warning。当前 strict artifact **不具备 runtime 验收成功的含义**；迁移结束后必须有一次明确的门禁切换，不能仅删除 transitional 配置就认为完成。依赖差异只报告是用户已知事项，不再另报。

## PR 拆分及描述核对

| PR | 指定快照相对上一层增删 | 当前快照相对上一层增删 | 独立 head 的实际验证 |
|---|---:|---:|---|
| #6582 | 819 | 819 | 独立工作树的 staging/backend 构建通过；该 head 本来不含审计。 |
| #6584 | 689 | 699 | 独立 head 构建及 transitional source closure 通过。 |
| #6594 | 633 | 638 | 独立 head 构建及 source closure 通过；最终叠加 head 上完整执行了矩阵/runtime。 |
| #6597 | 76 | 76 | 独立 head CPU 路径通过；CUDA 未实际编译。 |
| #6630 | 328 | 331 | 最终 head 实际 CPU/native 构建、安装与 gRPC E2E 通过。 |

前四个 head 的独立构建探针为节省重复编译使用 `NO_NATIVE_EXT=1`，因此只能证明该层 staging/backend 可工作，**不能冒充各 head 分别完成 native / 全量 CI**。最终 head 两种模式和 H1/H2 反例另实际编译了 CPU native。没有发现这五个指定 head 缺前置工具而无法启动的情况；中间单个 commit 能否执行是另一问题，不应混同于 PR head。

逻辑拆分大体对应 build、静态审计、环境验证、CUDA、E2E，但前三条分别超出 200–500 行目标，CUDA 切片则只有 76 行。当前 GitHub 相对 dev 的大 diff 还包含前置 PR，不能把累计的 2,547 行都算成 #6630 自己新增。是否继续拆分，应由可独立验收的职责决定，不建议为行数拆出暂时不能工作的中间态。

**维护者明确意见：** 当前 #6584 两条 inline review 是“目前可以把 platform 包含进 client”及“应尽量避免包含 distributed”（[评论一](https://github.com/LMCache/LMCache/pull/6584#discussion_r4560274217)、[评论二](https://github.com/LMCache/LMCache/pull/6584#discussion_r4560291781)）。这既不是批准所有排除/放行语义，也不是已经批准本实现。约 200–500 行来自 #6305 明文；其他关于偏好简洁的判断不能伪装成针对这些 head 的维护者结论。

### 单独列出描述与代码不一致或口径不清的说法

| 来源/说法 | 与实际代码的对照 |
|---|---|
| #6582：`exclude ... always wins`；六个 hook 被排除 | H1 直接反例推翻“永远优先”；其中 base hook 在 transitional 实际仍被打包。strict 六个被排除与此不矛盾。 |
| #6584：`cryptography` 仅为某 transitional group 声明，删除该组即删除依赖 | `pyproject.toml:32` 是无条件基础依赖；manifest 组中没有依赖声明或自动更新 METADATA 的实现。必须另改 pyproject，README 最新版本实际上也写了要手动删除依赖。 |
| #6594：253 个模块、6 个 smokes，`with no failure` | 数量复核相符，但工具“成功”的口径包含 engine / optional / runtime_gaps。基线两条 request smoke 都因缺少 Starlette 被归为 gap，并未成功创建客户端。描述宜写“检查返回 0，其中哪些跳过/豁免”，不能让读者理解成 259 次实际执行全部成功。 |
| PR 描述中的 AI explainer | 读取时五条 body 都只有 `<!-- attach pr-explainer-....html -->` 注释，没有实际可访问的 HTML 链接。无法验证其中设计、数字和当前 head 是否同步。 |

另外，275/339 个包内文件、64 个 transitional 条目、253 个 runtime 模块/6 个 smoke 的数量与指定快照相符；不将这些数字报告为错误。#6630 的 gRPC 请求结果本轮复核通过，ZMQ 的既有成功声明因环境限制不能独立确认。历史评论引用不同旧 head 的数字不作为当前描述造假的证据。

## 配置驱动要求与需要用户拍板的事项

普通 Python 文件落在已选目录时，构建器不需要改代码；新的依赖、数据格式、smoke 仍需修改对应配置。当前实现不是“单独改 manifest，就自动推导依赖、smoke 和 CI”的系统。

删除 gRPC 目录的 5 行排除实验会在 `setup.py:34` 找不到固定生成器；静态检查也能显示仍有 gRPC 调用方。它说明当前生成能力和运行能力仍绑定具体实现，**不证明可以在不处理调用方的前提下删掉一个必需依赖**。这种冲突应明确报告，不应让构建代码悄悄放行。

需要决定的是：

1. **配置的范围。** 是要求仅改 manifest 自动联动，还是允许同步编辑 manifest、pyproject、smoke 和 workflow 配置？若要前者，需要再确定最小声明结构；不能把当前分散的手工修改称为已实现自动联动。
2. **默认重叠如何收口。** 绝对排除优先是本轮硬要求；在此基础上，默认 base cache-context 如何显式表达“仅迁移期需要”，以及是否必须先等对应上游迁移落地，需要确定。不能暗中放松排除规则来保住现有原型。
3. **可选能力的支持契约。** 删除 detector / device provider 时，允许撤销哪些能力，哪些必须由配置中的 smoke 强制保持？这决定 M4 的正确门禁，不能用“整个目录不能部分排除”替代产品范围。
4. **PR 行数与职责的取舍。** 保留五条并明确申请前三条超量，还是继续拆成更小、可独立验收的 PR？本报告不擅自重排实现分支。

## 实际验证与未能验证的部分

| 项目 | 结果 |
|---|---|
| Python / torch | Python 3.12.14；构建与主要运行环境为 torch 2.14.0+cpu。使用用户指定的 CPU index。 |
| CPU 构建 | strict / transitional 均成功，包内文件分别 275 / 339；仅在新 staging 中生成。环境原先指定的 clang++ 不存在，改用已安装 gcc/g++ 后完成。 |
| artifact audit | 两个原始 wheel 均 0 failure；H1/H2 额外用实际 CPU/native 构建复核，仍出现错误放行。 |
| 静态闭包 | transitional 返回 0；ratchet 64/64、相等。strict wheel 返回 1，当前为 4 个首层缺失 server 文件，这是迁移尚未完成的结果。 |
| clean-venv import | 运行 253 个模块和 6 个 smoke；返回 0，包含明确记录的 engine / optional / Starlette gap；runtime 与静态 import-time server reach 均为 8 个文件。 |
| 必需 native | 实际直接加载 `lmcache_native` 成功。附加探针在 torch 2.13.0+cpu 上也能加载该 CPU 扩展，因此没有把“torch 未钉 runtime 版本”推断成已复现的 ABI 故障。 |
| 替换/卸载 | strict client → full → client → CLI → client，矩阵 0 failure；不卸载直接安装 full 时正确观察到两个 owner。 |
| full superset | strict / transitional 对未修改根打包生成的 full wheel 均 0 failure。full 使用独立 git worktree 构建；无 `.git` 的 archive 会改变 SCM 文件发现，未拿那份产物冒充基线。 |
| 真实 gRPC | 关闭遥测后完整通过：0/512 cold、512/512 warm，warm_lookups=1，store/retrieve 成功，bytes_match=true，161 个 lmcache 模块来自 client venv，server_exit=-15，退出并释放端口。 |
| 真实 ZMQ | 尝试后失败：服务端在当前受限环境 `Operation not permitted (src/ip_resolver.cpp:542)`，退出 -6；没有取得缓存命中结果。不据此认定实现回归。 |
| 源工作树 | 最终 `git status --porcelain` 为空，`git diff --check` 通过；五个实现分支未修改、未推送。 |

**未能验证：** CUDA 编译与真实 GPU 执行、macOS/Windows/其他架构与其他 Python 版本、安装真实 vLLM nightly 的专用 job、SGLang / TRT-LLM / ATOM 的真实引擎链路、ZMQ 完整 E2E，以及 GitHub 托管 runner 上这五个当前 head 的完整 workflow。没有重新执行全仓 pre-commit；本轮没有修改实现代码，也没有把本地阅读/探针说成完整 lint 通过。

自动审批拒绝的首次遥测执行不计通过；随后已使用源码证实的 opt-out 完成更安全的 gRPC 验证。私有笔记仓库访问被拒绝后，报告改为提交到本轮已授权的公开 fork 的独立报告分支。
