# 第二轮审核证据

对应 `../lmcache-6315-scheme-c-r2-review.zh.md`；这些是审核夹具和记录，不是实现修复。

所有 `$WORK` 是可替换的本地工作目录。关键 H1/H2 使用真实 `NO_GPU_EXT=1` CPU/native 构建；`requirements-no-reason` 仅为退出码的快速实验，使用 `NO_NATIVE_EXT=1`。前四个 PR 的独立 head 探针也使用 NO_NATIVE_EXT=1，不能当作 GPU/native 验证。

复现应使用新的空工作目录：

1. 将公开 fork 的本轮 head `e0dbe8f296e7d279e07b5fcf6f365a19cd5b8e07` checkout 到 `$WORK/LMCache-review`；为新旧属性夹具对照，另外 fetch `03e89b199ab47804d19a3e55f93a4ff1d58c70c1`。
2. 在 `$WORK/r2-venv` 创建 Python 3.12 环境，安装 requirements/build.txt、build，以及官方 CPU index 的 torch 2.14.0。
3. 设置 `LMCACHE_REVIEW_WORKSPACE=$WORK`，运行 scripts/r2-manifest-probes.py 与 scripts/r2-targeted-probes.py；后者会生成两种 Python import 语义夹具。
4. 按主报告 B 命令将基线 transitional wheel 放入 `$WORK/evidence/baseline/transitional`，随后运行 scripts/r2-wheel-probes.py。再按主报告构建两个关键排除变体并审计。
5. 运行真实 E2E 前用独立 client/full venv 安装相应 CPU wheel；按 workflow 补入登记的 runtime_gaps，并设置 `LMCACHE_TRACK_USAGE=false DO_NOT_TRACK=1`。

wheel 变异实验都重新生成合法 RECORD，保留原 staging 记录，用以验证审计的具体边界。attribute-shadow/source 是 checkout 语义夹具（源码以 .py.txt 保存为数据，脚本复现时自动创建实际 .py）；运行时对照还使用没有被排除模块的独立目录，见 runtime-shipped.log。module-import-positive 仅把包属性移除，证明新修复确实补到了真正子模块的漏报。

脚本不进入默认 pytest 发现。没有附带 wheel 二进制、venv、私人数据或遥测载荷。
