本轮修复仍未达到验收标尺：上一轮 10 项发现中，3 项已修复、1 项部分修复、6 项未关闭；另复现了 1 项新误报，目前仍有 2 项高、6 项中严重程度问题。

# LMCache #6315 方案 C：第二轮对抗性复审

日期：2026-11-14，多伦多时间。实现分支只读；未修改、推送实现分支，未评论、修改或新开 PR。报告和证据提交到公开 fork 的独立报告分支。

上一轮报告：[固定版本 `cea1688`](https://github.com/thegoldenflow/LMCache/blob/cea1688df8d5e350956f7355fd7d1545a5557189/docs/reviews/lmcache-6315-scheme-c-review.zh.md)。本报告保留原问题编号，另用 N1 标记修复引入的新发现。用户最初列出的已知事项不重复算作新发现。

## 1．审核快照与范围

已重读两份迁移约定、当前仓库 AGENTS / review 指引 / coding standards、边界设计，核对五个 PR 的 head、描述和 inline review。

| PR | 本轮 head | 相对上一层的增删 | 当前累计提交数 |
|---|---|---:|---:|
| [#6582](https://github.com/LMCache/LMCache/pull/6582) | `c49268b6` | 816 | 6 |
| [#6584](https://github.com/LMCache/LMCache/pull/6584) | `f6ff94a1` | 734 | 12 |
| [#6594](https://github.com/LMCache/LMCache/pull/6594) | `ec393ffe` | 647 | 19 |
| [#6597](https://github.com/LMCache/LMCache/pull/6597) | `6d7c39a4` | 76 | 20 |
| [#6630](https://github.com/LMCache/LMCache/pull/6630) | `e0dbe8f2` | 336 | 24 |

最终 head 完整 SHA：`e0dbe8f296e7d279e07b5fcf6f365a19cd5b8e07`。五个 PR 仍是 Draft，base/merge-base 均为 `bcafb031401d404a5dabae4853f5e23bf9e5685c`，且逐层为祖先关系。结束核对时远端五个 head 与本轮快照相同。

相对上轮读取的 `03e89b19`，打包工具和工作流有 10 个文件、98 行新增、52 行删除。两轮 base 不同，范围比较中另有 vLLM、SDK 和 AES-GCM 等上游变化；这些不是本轮打包 PR 新增的业务改动。当前整组 PR 对 base 的 diff 仍只包含 12 个打包工具/工作流文件，没有修改根 `pyproject.toml`、根 `setup.py` 或产品 Python 源码。

以下文件行号均指本轮最终 head。复现材料位于本报告旁的 `6315-scheme-c-r2-evidence/`。manifest、wheel 反例都使用副本；小型 Python 语义夹具也在隔离目录，不修改产品源码。

命令缩写：

```bash
R=/workspace/scratch/8d58f04f4058/LMCache-review
E=/workspace/scratch/8d58f04f4058/evidence
P=/workspace/scratch/8d58f04f4058/r2-venv/bin/python
cd "$R"
B() { CC=gcc CXX=g++ NO_GPU_EXT=1 "$P" -B tools/client_wheel/build.py --no-isolation --boundary transitional --version 0.0.0.dev0 "$@"; }
I() { "$P" -B tools/client_wheel/check_imports.py --source-tree . --boundary transitional "$@"; }
A() { "$P" -B tools/client_wheel/audit.py --boundary transitional "$@"; }
```

## 2．上一轮十项的处理结果

| 原编号 | 问题 | 本轮结论 | 核实结果 |
|---|---|---|---|
| H1 | exclude 与 compat / transitional 优先级 | **部分修复** | compat 冲突现在会拒绝构建；transitional 仍能覆盖 exclude，且存在完整构建/静态/审计都通过的反例。 |
| H2 | 生成 `.pyi` 绕过 exclude | **未关闭** | CPU/native 重建后，明确排除的 `.pyi` 仍被生成并打包，审计返回 0。 |
| M1 | 包外模块 / `.data/scripts` 漏审 | **已修复** | 两个原始 wheel 变异案例均退出 1，报 `files: outside lmcache/`。 |
| M2 | staging 源文件哈希未校验 | **未关闭** | 修改 logging.py 内容、更新 RECORD 后，审计仍返回 0。 |
| M3 | 必需 native 缺失未审出 | **未关闭** | 删除 `lmcache_native.so` 的 wheel 副本仍通过审计；已有 CI 的独立加载检查仍是兜底。 |
| M4 | 动态能力缺失 / scanned 过度限制 | **未关闭** | CPU provider 排除仍漏检；可选 detector 的部分排除仍被一刀切拒绝。README 增补一个动态 loader 名字不等于补齐检查。 |
| M5 | 工作流缺少源码 / 运行依赖触发路径 | **未关闭** | paths 未改，仍不直接匹配 `lmcache/**` 和 `requirements/common.txt`。 |
| M6 | 反例绑定迁移文件名 | **未关闭** | 仍固定 grep `custom_types.py`，README 仍写迁移后需要删改该断言。 |
| M7 | E2E 默认服务端遥测 | **已修复** | 子进程强制 `LMCACHE_TRACK_USAGE=false`；本轮 gRPC 实测成功，服务端日志没有启动 usage context。 |
| L1 | 相对 venv 路径失效 | **已修复** | 相对解释器路径的完整安装矩阵返回 0；gRPC E2E 也用相对 server/client 路径通过。 |

此外，本轮也验证了三项原先已知问题的修补：

- `top` 类型的 boundary gap 现在被 `scope.py:106–111` 明确拒绝，反例退出 1。
- client 不再复制一份 torch 构建 pin；`build.py:124–145,214–222` 从指定 revision 的根配置拼入 `[build-system]`。实际 CPU 构建通过；函数探针把根 pin 替换成测试值 `torch==2.15.0` 后，生成配置也同步变化。该探针没有安装或验证 torch 2.15。
- `audit.py --requirements` 已能在理由缺失时返回 3；删除 requests 的理由这一行、重新构建匹配的 staging 后，带该参数返回 3，不带参数仍返回 0。工作流仅在改动工具目录的 PR 上将该情况作为失败，其余情况仍警告；不能描述成无条件依赖门禁。

`from 包 import 模块` 的一个原始漏报模式已被补上，但出现了 N1 所述的属性误报，不能将这部分称为完整解决。

## 3．仍存在的高严重程度问题

### H1．transitional 仍覆盖 exclude，而且能让整个静态审核链通过

**问题与证据。** `scope.py:78–87` 仍先判断 allowed；`build.py:94–98` 仍明确允许 transitional 与 exclude 重叠。本轮新增的 `build.py:100–104` 只拒绝 compat 冲突。

在副本新增 **5 行**，排除一个仍在 transitional 中的服务端文件：

```toml
[[exclude]]
owner = "r2-review"
reason = "counterexample"
paths = ["lmcache/v1/distributed/serde/aesgcm.py"]
```

```bash
B --manifest "$E/exclude-transitional-server/manifest.toml" --out "$E/exclude-transitional-server/dist"
I --manifest "$E/exclude-transitional-server/manifest.toml"
"$P" -B tools/client_wheel/check_imports.py --source-tree . --ratchet --manifest "$E/exclude-transitional-server/manifest.toml"
A "$E/exclude-transitional-server/dist/"*.whl --staging "$E/exclude-transitional-server/dist/STAGING_MANIFEST.json" --manifest "$E/exclude-transitional-server/manifest.toml" --requirements
```

**输出：** 构建、transitional 静态检查、ratchet、审计均退出 **0**；ratchet 输出 `strict failures == transitional: True`，审计输出 `0 failure(s)`。实际 CPU/native wheel 有 339 个包内文件，包含被明确排除的 `aesgcm.py`。默认配置中的 `platform/base/cache_context.py` 也仍同时 excluded 与 shipped。

相对而言，旧 compat 反例现在实际退出 1，报 `compat shim in [[exclude]], remove it from [[compat_shims]] instead`，这一部分确实修复了，不能再沿用旧的“compat 反例构建成功”结论。

**影响。** “排除永远优先”仍不成立；从配置移除服务端能力可能没有任何审核失败，却仍被打包。

**最小修法 / 行数 / PR。** 统一 scope 对 exclude 的绝对优先级，并重新表达默认“仅 transitional 需要”的文件，不能只交换两个判断后忽略默认闭包。可在配置中明确 transitional-only 归属、清理重叠和相应 gap；另一条路线是等前置迁移解除该依赖后再收口。约 **15–35 行代码及少量配置调整**，主要 **#6582**，同步复核 **#6584**。本报告不替用户放松排除规则。

### H2．生成 `.pyi` 的排除绕过完全没有改变

**问题与证据。** `setup.py:33–40` 仍无条件生成 protobuf；`audit.py:54,83–87` 仍把 `_proto_gen/\w+.py[i]` 整片视为生成物，跳过一般选入/排除检查。

在副本新增 **5 行**，排除 `lmcache/v1/transport/grpc/_proto_gen/common_pb2.pyi`：

```bash
B --manifest "$E/exclude-generated-pyi/manifest.toml" --out "$E/exclude-generated-pyi/dist"
A "$E/exclude-generated-pyi/dist/"*.whl --staging "$E/exclude-generated-pyi/dist/STAGING_MANIFEST.json" --manifest "$E/exclude-generated-pyi/manifest.toml" --requirements
```

**输出：** 两个命令均退出 **0**；选择阶段拿掉该文件，但构建后又生成它，实际 CPU/native wheel 仍为 339 个包内文件；审计 `0 failure(s)`。静态检查也返回 0，因为不扫描 `.pyi`。

**影响。** 修好 transitional/compat 的选择逻辑，也不能自动修好这个生成后绕过；这是另一个阶段的缺口。

**最小修法 / 行数 / PR。** 对生成结果应用排除或明确拒绝配置冲突；生成白名单按预期输出声明，不依赖整个目录的名字形状。约 **30–60 行**，**#6582 + #6584**。

## 4．中严重程度：新增误报及未关闭问题

### N1．新 `dropped()` 把包属性误判成被排除的子模块

**问题与证据。** 新代码在 `check_imports.py:223–227` 只因 checkout 中存在同名 excluded 文件就认定它是模块；`272–273` 将其加入必须检查的目标。它没有判断包是否已经提供同名属性。

隔离的最小 Python 语义夹具如下，产品源码没有改：

```python
# lmcache/pkg/__init__.py
feature = 123

# lmcache/consumer.py
from lmcache.pkg import feature
assert feature == 123
```

checkout 中另有 `lmcache/pkg/feature.py`，manifest 排除这个子模块；打包后的模拟目录中没有它。Python 仍能正常取得包属性 `feature=123`。

用相同 fixture/manifest 对比两版 CLI：

```bash
"$P" -B tools/client_wheel/check_imports.py --source-tree "$E/attribute-shadow/source" --manifest "$E/attribute-shadow/manifest.toml"
```

**输出：** 旧 `03e89b19` 检查退出 **0**，新检查退出 **1**：

```text
FAIL excluded, not in boundary_gaps (r2-review: exclude optional submodule, keep scalar attribute): lmcache/pkg/feature.py <- lmcache/consumer.py:1 (top)
```

真正运行模拟打包目录，退出 **0**，输出：

```text
feature = 123
excluded module loaded = False
```

对照夹具把包的 `feature` 属性去掉，则旧检查仍错误地返回 0，新检查正确返回 1。这证明“补漏报有效”与“引入误报”同时存在，而不是主张撤销整个修复。

**影响。** 合法的包导出 API、与可选子模块同名的值/函数/类，会因为排除该子模块而被错误阻塞，违反本轮不能误报的要求。

**最小修法 / 行数 / PR。** 不能仅凭文件存在就决定 import 语义；对包中明确的属性定义/导出做有限区分，同时保留真正子模块缺失的错误。不要通过执行任意产品模块来完成静态检查。约 **20–40 行**，**#6584**；复用这两个小型工具反例作为聚焦回归，不进入默认 pytest 发现。

### M2．源文件内容仍未与 staging 哈希核对

**证据。** `build.py:228–241` 仍写入 SHA-256；`audit.py:209–219` 仍只取路径。对实际 CPU wheel 副本，在 `logging.py` 末尾新增 1 行 `raise RuntimeError("adversarial audit source mismatch")`，重写合法 RECORD，保持 staging 记录不变：

```bash
A "$E/wheel-mutations/source-changed/"*.whl --staging "$E/baseline/transitional/STAGING_MANIFEST.json"
```

退出 **0**，`0 failure(s)`。

**影响。** 审计不能证明内容仍来自记录中的 canonical 源；这个特定异常可能被 runtime 检查兜住，不代表未执行逻辑也受保护。

**修法 / 行数 / PR。** 校验非生成源和数据的内容哈希，明确区分生成输入/输出；约 **20–40 行，#6584**；若补记实际生成输出，**#6582 再约 10–20 行**。

### M3．必需 native 缺失仍可通过 artifact audit

**证据。** `audit.py:221–225` 仍只检查已有扩展是否在 allowlist 中；`check_imports.py:229–232,371–375` 仍把允许的 native 当作可缺失模块。从实际 wheel 副本删除 1 个 `lmcache_native...so`，重写 RECORD：

```bash
A "$E/wheel-mutations/native-missing/"*.whl --staging "$E/baseline/transitional/STAGING_MANIFEST.json"
```

退出 **0**，`0 failure(s)`。

**影响。** 单独 artifact audit 仍不能证明必需原生支持存在。当前 CI 另外调用 `assert_native_ops.py`，所以这不是对整条 CI 绕过的证明。本轮正常 wheel 的独立 native 加载检查成功。

**修法 / 行数 / PR。** 配置区分允许与 profile 必需扩展，审计上下界，保留已有加载检查；约 **15–30 行，#6584**，**#6594/#6597** 对齐 profile。

### M4．动态能力与 scanned 限制未补齐

**证据。** `scope.py:99–105` 的禁止部分排除逻辑未改；`check_imports.py:142–147` 仍只识别少量字面量动态导入；设备发现仍由 `_device_detect.py:113–121` 扫描注册。README:51–55 新增 `request_telemetry/factory.py` 名字，只是在承认另一处未覆盖路径。

- 增加 5 行排除 `platform/devices/cpu/__init__.py`，`I --manifest ...`、实际 CPU/native 构建和审计均退出 0。对解包 wheel 调用 `get_device_spec("cpu")`，正常版输出 `CPU_SPEC CpuDeviceSpec`，排除版输出 `CPU_SPEC None`。
- 增加 5 行只排除 `common/kv_format/detectors/atom.py`，仍在 load_scope 阶段退出 1：`exclude the whole directory`；同时移除 ATOM integration 的配置行（共 6 行增删）也不能通过。

这不是声称删除 CPU 能力一定不允许，而是检查尚不能证明/说明配置声明的支持能力是否仍存在；扫描剩余文件本身，也不等于不能删除某个可选 detector。

**影响。** 动态能力丢失和合理的部分排除仍没有一致的验证规则。CPU E2E 能兜住 CPU 路径，但不能代表其他设备和引擎。

**修法 / 行数 / PR。** 用现有 `[smokes]` 验证承诺支持的 spec / detector / wrapper / service，允许配置撤销可选能力及其 smoke；不要一刀切禁止部分目录排除。约 **20–50 行配置/检查调整，#6582/#6584/#6594**。支持范围需要用户决定。

### M5．CI 触发范围没有改

**证据。** `build_client_artifacts.yml:19–29` 仍没有 `lmcache/**`、运行依赖目录或 proto 源码路径。读取该 paths 的匹配探针输出：

```text
lmcache/v1/common/custom_types.py = false
lmcache/v1/transport/grpc/protos/common.proto = false
requirements/common.txt = false
tools/client_wheel/manifest.toml = true
```

可用 `rg -n 'paths:|tools/client_wheel|requirements/build.txt|lmcache/\*\*|requirements/\*\*' .github/workflows/build_client_artifacts.yml` 核对。此项是路径匹配与源码判断，没有冒充实际执行 Actions。带 full 标签的入口仍可兜底，不把它描述成发布门禁完全缺失。

**影响。** 源码/依赖变化不能直接触发这套检查，反馈可能延迟到 full build。

**修法 / 行数 / PR。** 增加相关粗目录触发，或明确纳入每个相关 PR 的常规调用；约 **5–15 行 YAML，#6582**。

### M6．正常迁移仍会使硬编码反例假失败

**证据。** 工作流 `206–214` 仍固定 grep `not in the full wheel: lmcache/v1/multiprocess/custom_types.py`；manifest 仍将该文件登记为将来移到 compat 的 transitional 项，README:72 仍明确写该 grep 会失败。

本轮 baseline wheel 的 static ratchet 仍为 64/64；当前断言有效不代表它能随 #6541 自动变化。一旦 custom_types 成为两种 wheel 都有的 shim，该 grep 就不再成立；所有 transitional 项清空时，“两种 wheel 必须不同”的反例本身也过时。这是源码确定的后续失效，没有冒充当前工作流已经红灯。

核对命令：`rg -n 'custom_types.py|superset' .github/workflows/build_client_artifacts.yml tools/client_wheel/README.md tools/client_wheel/manifest.toml`。

**影响。** 正常上游迁移仍需要改检查脚本，否则可能产生与产品回归无关的失败。

**修法 / 行数 / PR。** 从配置实际差集选择反例，差集为空时结束这个历史断言；或对 wheel 副本注入确定的单一违例。约 **15–35 行，主要 #6594**，其他固定反例在 **#6584/#6597** 少量对齐。

## 5．PR 描述仍需同步

| 项目 | 当前描述 | 实际情况 |
|---|---|---|
| #6582 的 exclude | 仍称 `always wins` | H1/H2 尚在；六个 hook 中 base hook 在 transitional 仍被打包。 |
| #6584 提交范围 | 前 5、后 5 | 当前应按前置 6、本层 6 区分；总计 12。 |
| #6594 提交范围 | 前 10、后 6 | 当前为前置 12、本层 7；总计 19。 |
| #6597 提交范围 | 前 16、后 1 | 当前为前置 19、本层 1；总计 20。 |
| #6630 提交范围 | 前 17、后 3 | 当前为前置 20、本层 4；总计 24。 |
| cryptography | 仍称只为某 transitional 组声明，删组即删依赖 | `pyproject.toml:18` 仍是无条件依赖，组中没有自动生成依赖/METADATA 的机制。 |
| 253 模块、6 smoke 均无失败 | 仍容易读成全部实际导入成功 | 本轮数量相符，但结果包含 engine / optional / Starlette gap；两条 request smoke 在未安装 Starlette 时仍是 gap。 |
| explainer | 五条 body 仍是旧 SHA 的 `attach ...html` 注释 | 没有可访问 HTML 链接，且注释 SHA 与五个新 head 均不一致。 |

这些描述问题不等于本轮实测数据虚假，但不应在新 head 下继续要求评审者按旧提交数和旧材料审核。

前三条 PR 的增删仍为 816 / 734 / 647，超过 200–500 行目标；CUDA 切片 76 行。原始逻辑职责没有进一步拆分。维护者本轮可核验的意见仍是“目前可包含 platform”和“尽量避免 distributed”，没有新意见批准这里的排除语义或豁免 PR 规模。是否保留五条并解释超量，仍需用户/维护者决定。

## 6．本轮实际验证

对照 #6315 与 `docs/design/v1/package_boundaries.md` 的契约：

| 契约 | 状态 | 依据 |
|---|---|---|
| 临时 staging、精确选入、版本传参、不改根打包 | 主要路径通过；排除语义失败 | 正常构建及工作树检查通过，但 H1/H2 违背精确排除。 |
| 文件、元数据、入口点、数据及 native 审计 | 部分通过 | 包外文件已拦住，M2/M3 与生成物缺口仍在。 |
| client import 闭包与支持能力 | 未完成 | transitional 可运行；strict 仍未闭合；M4/N1 仍影响检查正确性。 |
| 替换安装、完整包保留面 | 已测部分通过 | 矩阵与子集通过，根打包未改；没有覆盖全部 server 功能。 |
| 独立环境真实请求、第二次复用 | gRPC 通过；ZMQ 未验证成功 | 见下面真实请求记录；不能延伸为 CUDA/真实引擎链路已验证。 |

| 验证 | 结果与限制 |
|---|---|
| 环境 | Python 3.12.14，torch 2.14.0+cpu，gcc/g++；用户指定的 CPU index。 |
| 两种 CPU/native wheel | strict 275、transitional 339 个包内文件；构建和带 `--requirements` 的基线审计均通过。 |
| H1/H2 反例 | 都另做了实际 CPU/native 构建，使用与变体匹配的 staging；不是篡改 manifest 后只触发指纹不匹配。 |
| 静态闭包 | transitional 通过；ratchet 64/64；strict 仍有 4 个首层 server 缺失，这是迁移边界未完成的预期状态。 |
| clean-venv runtime | 253 个模块、6 个 smoke，退出 0；明确保留 engine / optional / Starlette gap；runtime 与静态 import-time server reach 均为 8 个文件。 |
| 替换/卸载 | 使用相对 `r2-matrix/bin/python`，client → full → client → CLI → client 完整通过；直接覆盖安装 full 时检测到两个 owner。 |
| 子集 | strict / transitional 对独立 git worktree 构建的 full wheel 均 0 failure。 |
| native 加载 | `assert_native_ops.py lmcache.lmcache_native` 在 client venv 中通过。 |
| gRPC E2E | 按工作流补装已登记的 Starlette gap 后，使用相对 server/client 路径通过；cold=0、warm=512/512、warm_lookups=1、bytes_match=true；161 个 lmcache 模块来自 client venv；服务端退出并释放端口。未补 gap 的首次尝试明确因 Starlette 缺失失败，不算通过，也不算新回归。 |
| ZMQ E2E | 服务端在当前受限环境报 `Operation not permitted (src/ip_resolver.cpp:542)`，退出 -6；未取得命中结果，不认定为本轮实现回归。 |
| 独立 PR head | 前四个 head 各自的 staging/backend 构建通过，含 scanner 的三个 head 各自 source closure 通过；这些快速探针使用 `NO_NATIVE_EXT=1`，不冒充四个 head 各自完成 native/CUDA/完整 CI。最终 head 则实际做了上述 native 与运行验证。 |
| DCO / 工作树 | 24/24 提交有 Signed-off-by；`git diff --check` 通过，源工作树干净；五个远端实现 head 与开始快照相同。 |

## 7．合入前仍需处理与未验证范围

优先处理 H1/H2 和新 N1，再补 M2/M3 的 artifact 审计保证；对 M4 的可选能力范围和 M5/M6 的 CI 政策作明确决定。不要用“正常构建都通过”代替这些反例已经关闭。

上一轮需要决定的配置范围、transitional-only 表达、可选能力支持契约和 PR 拆分取舍仍未在本轮得到新指令。它们不影响本轮两个高严重程度反例已经成立的判断，也不授权审核者自行降低硬要求或修改架构。

**未能验证：** CUDA 实际编译/加载与真实 GPU 请求，macOS/Windows/其他架构及其他 Python 版本，真实 vLLM nightly 的专用 job，SGLang / TRT-LLM / ATOM 真实引擎链路，ZMQ 完整 E2E，以及 GitHub 托管 runner 上五个 head 的全套工作流。没有重新执行全仓 pre-commit。报告将源码判断、隔离夹具、实际 CPU 构建和真实请求分开记录，没有把未覆盖部分算作通过。
