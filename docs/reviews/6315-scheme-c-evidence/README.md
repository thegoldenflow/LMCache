# 审核证据

对应主报告 `../lmcache-6315-scheme-c-review.zh.md`；这是审计材料，不是产品实现改动。

日志中的 `$WORK` 表示本次临时工作目录。manifest 变体差异在各目录的 `manifest.diff`；完整变体可运行脚本生成。`build-probes.json` 是 **NO_NATIVE_EXT=1 快速语义实验**；H1、H2 另分别用 **NO_GPU_EXT=1 的真实 native 构建**验证，见 `build-summary.log` 与 `audit-native.log`。wheel 变异来自原始真实 native wheel；变异副本都重新生成合法 RECORD。

复现需要 Python 3.12 和独立空工作目录。clone 公开 fork 后，按主报告的完整 SHA fetch 并 detached checkout 至 `$WORK/LMCache-review`；在 `$WORK/venv-build` 创建环境，按用户指定 CPU index 安装 torch 2.14.0，再安装 requirements/build.txt 与 build。导出 `LMCACHE_REVIEW_WORKSPACE=$WORK`，依次运行 `scripts/run_manifest_probes.py`、`scripts/run_build_probes.py`。按主报告 B 命令额外构建 H1/H2 的 `native-dist`。基线真实 native 产物须位于 `$WORK/evidence/baseline/transitional`，随后运行 `scripts/run_wheel_probes.py`。`run_dynamic_probe.py` 还需准备已安装依赖的 venv-client 及 CPU-init 排除版 wheel。

运行真实 E2E 前设置 `LMCACHE_TRACK_USAGE=false DO_NOT_TRACK=1`。本轮 gRPC 通过；ZMQ 受环境限制失败，不将其记录为实现回归。没有附带任何默认遥测请求的载荷或旧服务端日志。

脚本是一次性反例探针，不进入默认 pytest 发现。仅修改 manifest/wheel 副本和独立工作树，不修改五个实现分支。
