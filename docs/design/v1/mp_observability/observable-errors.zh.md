# 把超时观察者扩展到其他异常：两种思路（调查分支）

- 分支：`investigate/6509-generic-error-observer`，基于 #6509 的 head `389e9979`，只在本地，没有推送。
- 定位：调查原型，不打算并进 #6509。#6509 是解耦搬迁，这里会新增 `EventType`、subscriber，还改了超时异常的基类，放进去会超出那个 PR 的范围。
- 行号说明：文中 `file:line` 指本分支的代码，除非标明“head”。

## 1. 背景

#6509 把 `LMCacheTimeoutError` 移到了 `lmcache/v1/common/timeouts.py`。为了不让 `common` 依赖 `mp_observability`，它用了一个单槽观察者：`common` 里有 `_observer` 和 `register_timeout_observer`，服务端 `init_event_bus()` 把 `errors.publish_timeout` 注册进去。

这套机制只服务一个类。问题是：别的异常能不能也这样上报？

答案分两半：

- **LMCache 自己定义的异常类**：把钩子挪到一个通用基类，想上报的类继承它就行（思路 A）。
- **内建和第三方异常**（`KeyError`、torch 的 `RuntimeError`、gRPC 的错误等）：它们的构造函数挂不上钩子，只能在捕获它们的地方上报（思路 B）。

两种思路共用同一个观察者和同一个事件出口，可以一起用。

## 2. 两种思路对比

| | A：构造时上报 | B：捕获点上报 |
|---|---|---|
| 入口 | `ObservableError.__init__` | `report_error(exc, session_id=...)` |
| 覆盖范围 | 只覆盖继承了 `ObservableError` 的 LMCache 类 | 任意异常，包括内建和第三方的 |
| 什么时候上报 | 每次构造都报，不管之后有没有 raise、有没有被吞 | 只有异常到达接入了的捕获点才报 |
| `stacktrace` | 构造栈：从线程入口到构造它的那一行 | `traceback.format_exception(exc)`：从抛出点到捕获点 |
| 失败时 | 取栈失败从 `__init__` 抛出（沿用 head 的契约）；发布失败吞掉 | 永不抛出 |
| 事件 | 超时类发 `TIMEOUT_RAISED`；其他类发 `ERROR_RAISED`，`source="constructed"` | `ERROR_RAISED`，`source="caught"` |

## 3. 共用的部分

### 3.1 `common` 里只有一个观察者

新文件 `lmcache/v1/common/observable_error.py`，不导入任何 `mp_observability` 模块：

```python
ErrorObserver = Callable[[BaseException, str, bool], None]   # (error, session_id, caught)

def register_error_observer(observer: ErrorObserver) -> None: ...

def report_error(error: BaseException, *, session_id: str = "") -> None:
    observer = _observer
    if observer is None:
        return
    with contextlib.suppress(Exception):
        observer(error, session_id, True)

class ObservableError(Exception):
    def __init__(self, *args: object, session_id: str = "") -> None:
        super().__init__(*args)
        if _observer is not None:
            _observer(self, session_id, False)
```

`LMCacheTimeoutError` 改成 `class LMCacheTimeoutError(ObservableError, TimeoutError)`，签名 `(message: str, *, session_id: str = "")` 不变。`register_timeout_observer` 被 `register_error_observer` 取代。

### 3.2 服务端只有一个出口

`init_event_bus()` 改为注册 `errors.publish_error`（原来是 `publish_timeout`），注册时机不变，仍然在 `_global_bus` 和开关设置之前。`publish_error(error, session_id, caught)` 的逻辑：

1. 观测关闭，或者这个异常对象已经报过（带 `_lmcache_error_reported` 标记），直接返回，也不取栈。
2. 取栈：`caught` 时用 `format_exception(error)`；构造时用 `format_stack(_construction_frame(error))`（见 4.2）。
3. 选事件：构造时、且是 `LMCacheTimeoutError` 或它的子类，发 `TIMEOUT_RAISED`；其余都发新增的 `ERROR_RAISED`。
4. 字段：`message`、`exception_type`、`stacktrace` 三个和原来一样；`ERROR_RAISED` 多一个 `source`。`TIMEOUT_RAISED` 的字段集合保持不变，有测试锁住。
5. 打标记，然后发布；发布失败只记 debug 日志。

`message` 的取法：构造时取 `error.args[0]`，和 head 一样（这时子类的 `__init__` 可能还没跑完，`__str__` 依赖的属性未必已经设好）。捕获时取 `str(error)`，这时对象已经构造完成。

### 3.3 为什么入口放在 `common`，而不是 `mp_observability`

最初的想法是在 `mp_observability` 里放一个 `report_exception()`，让服务端的捕获点直接调它。读代码时发现这条路走不通：客户端的 `lmcache/v1/client/transport/zmq_impl/mq_client.py:20` 导入了服务端的 `lmcache/v1/multiprocess/transport/zmq_impl/mq.py`，用它的 `msgspec_encode` 和 `msgspec_decode`。如果 `mq.py` 导入 `mp_observability`，客户端就又会把它加载进来，而去掉这个依赖正是 #6509 要做的事。

所以 `report_error` 也放在 `common`，捕获点只依赖 `common`，由服务端启动时注册观察者。实测导入 `mq_client` 后：

| | head `389e9979` | 本分支 |
|---|---|---|
| 加载的 `mp_observability` 模块 | 0 | 0 |
| 加载的 `lmcache` 模块里多出来的 | — | 只多了 `lmcache.v1.common.observable_error` |

（两边的总数都是 116。原因是 head 的 worktree 里有构建时生成的 `lmcache/_version.py`，本分支的新 worktree 里没有。两份模块清单逐行 diff，只有这两行不同。）

## 4. 思路 A：构造时上报

### 4.1 怎么接入一个类

把 `ObservableError` 加进基类，放在原来的基类前面：

```python
class CorruptEncodedKVError(ObservableError, CodecError): ...
```

原型接入了 `lmcache/v1/kv_codec/errors.py` 的 `CorruptEncodedKVError`，作为示例。选它的理由：

- 它代表数据完整性失败（magic 不对、CRC 不对、截断），应该很少出现，一出现就值得计数。
- 它只在服务端的 codec 里抛（`lmcache/v1/kv_codec/encoded_kv.py`），使用方是 `lmcache/v1/distributed/serde/asym_k16_v8.py`。
- 代码里没有按名字捕获它的地方（`grep "except .*CorruptEncodedKVError"` 为 0）。

### 4.2 取栈改成按帧回溯，不再固定切片

head 的写法是 `traceback.format_stack()[:-2]`，前提是观察者恰好在 `LMCacheTimeoutError.__init__` 里被直接调用：去掉最后两帧（`publish_timeout` 和 `__init__`），栈就停在构造处。

有了基类以后，调用链变成 `LMCacheTimeoutError.__init__ → ObservableError.__init__ → publish_error`，多了一层。固定切片会把 `timeouts.py` 那一帧留在栈里，现有测试 `assert "timeouts.py" not in event.metadata["stacktrace"]` 就会失败（见第 8 节的变异检查）。

本分支改成从当前帧往外找：先找到 `self is error` 的 `__init__` 帧，再跳过所有这样的帧，剩下的第一帧就是构造处（`lmcache/v1/mp_observability/errors.py` 的 `_construction_frame` 和 `_is_init_of`）。这样不依赖层数。

带来一处行为变化：子类自己重写了 `__init__` 时，head 的栈停在子类 `__init__` 里调 `super()` 的那一行，本分支停在构造它的那一行。用审计时的实验脚本在本分支重跑，这是 23 个比较项之外唯一真正的差异（见第 8 节）。我认为这是改进：栈停在调用方，而不是异常类的内部。

### 4.3 开销

原生文件系统，在 40 层调用深处构造一次（`timeit` 3000 次取平均）：

| 情况 | 每次耗时 |
|---|---|
| 普通 `Exception("x")` | 2.7 µs |
| `ObservableError`，观测关闭 | 3.5 µs |
| `ObservableError`，观测开启 | 185.0 µs |
| 子类自定义 `__init__`，观测开启 | 195.3 µs |
| 只做 head 式的 `format_stack()[:-2]` | 182.8 µs |
| 只做帧回溯（最坏情况：找不到 `__init__`，走完整个栈） | 11.6 µs |

结论：

- 开销几乎全在 `format_stack`。帧回溯在实际情况下只走两三帧，最坏也只有 11.6 µs。
- 观测开启时，每次构造比普通异常贵约 70 倍。所以只接入“每次构造都值得计数”的类；会被当成控制流、或者可能被大量构造的类不要接入。

（上一轮在 `/mnt/d` 上测到约 1.2 ms，偏大的原因是 9p 文件系统上 `linecache.checkcache` 对每个源文件 stat 很慢。）

### 4.4 哪些类该接入

head 上 `lmcache/v1` 一共有 29 个自定义异常类。原型只接入了一个，其余的初步判断如下：

- **可以考虑**：`CodecMismatchError`（跨模型的缓存污染）、`L2` 和 `L1` 的存储层内部故障类。
- **不该接入**：
  - `mp_coordinator` 下的类（`CheckpointWriteError`、`MetadataWriteError` 等）。coordinator 是单独的进程，从不初始化观测（审计时已确认），接入了也不会发任何事件。
  - 表示“请求被拒”的类：`cache_control` 的 `InvalidRequest`、`NotFound`、`Unavailable`，`L1ReconfigureError` 和 `L2ReconfigureError` 的 404、409。这些更像用户错误，不是服务故障。
  - `UnsupportedConfigError`：配置错了的话，每个 chunk 都会抛一次。
- 还没做的：逐个看构造频率。这一步需要在真实负载下看，静态读代码只能初筛。

### 4.5 坑：复制和 pickle 会重复上报

`copy.copy(e)` 和 `pickle.loads(pickle.dumps(e))` 都会用 `cls(*args)` 重建异常，也就会再跑一次 `__init__`。用 head 的真实 `LMCacheTimeoutError` 实测：构造 1 次，再 copy 1 次、pickle 往返 1 次，一共发 3 个事件，后两个的 `session_id` 变成空串。

- dev 和 head 都是这样，不是 #6509 引入的。
- 现在 `lmcache/v1` 里没有用进程池或 pickle 传异常的代码（`ProcessPoolExecutor`、`multiprocessing.Pool`、`pickle.dumps/loads` 都 grep 为 0），所以只是潜在问题。
- 本分支的去重标记挡不住这种情况：重建时 `__init__` 先执行，`__dict__`（连同标记）之后才恢复。
- 可选修法：在 `ObservableError` 上定义一个绕过 `__init__` 的 `__reduce__`。原型没有做。

## 5. 思路 B：捕获点上报

### 5.1 语义

- `report_error(exc, session_id=...)` 可以报任意异常，栈取异常自己的 traceback，从抛出点到捕获点。
- **永不抛出**。它是在 `except` 块里调用的，一旦抛出就会打断原有的错误处理。比如 ZMQ 的阻塞处理器会发不出错误响应，客户端只能等到超时。所以 `common` 里用 `contextlib.suppress(Exception)` 兜底，不依赖观察者自觉不抛。
- **去重**：构造时已经发布过的 `ObservableError`，或者已经报过一次的同一个异常对象，不再发布。`raise X from e` 里的 `X` 和 `e` 是两个对象，各报各的。

### 5.2 已经接入的捕获点：ZMQ（默认 transport，`MPServerConfig.transport = "zmq"`）

`lmcache/v1/multiprocess/transport/zmq_impl/mq.py` 里三处，都放在原有的 `logger.exception(...)` 之后：

- 流式响应的 `forward()`：`Error in ZMQ event stream`
- 阻塞处理器的 `_notify_response`：`Error in blocking handler %s`。这一处在发错误响应之前调用，所以客户端收到错误时，观察者已经被调用过了，测试据此是确定性的。
- `_handle_request`：`Error handling operation %s`，覆盖同步处理器。

### 5.3 还没接入的（head `389e9979` 的行号）

- gRPC 同步服务器 `grpc_impl/server.py`：`_dispatch`（L99 起）没有通用的 `except`，异常直接交给 grpc 运行时；流式的 `forward()` 在 L74。
- gRPC native `grpc_impl/native_server.py`：L401 的 `except Exception` 会进 `_fail_application`（L406）；流式在 L451；分发循环在 L343。
- gRPC aio `grpc_impl/aio_server.py`：L219 把异常塞进流里。
- HTTP `http_apis/error_handlers.py`：只处理 `CacheControlError` 这类领域错误，不是通用的接入点。

### 5.4 未决的点

- **`session_id`**：处理器边界只有 transport 层的 `request_uid`，拿不到请求的 session id，原型传的是空串。
- **`ValueError` 要不要计**：ZMQ 把 `ValueError` 映射成 `invalid_argument`，属于客户端传错参数。现在它也会被计成 `exception_type="ValueError", source="caught"`，是否排除还没定。
- **日志**：`ErrorLoggingSubscriber` 不记 `source="caught"` 的事件，因为捕获点自己已经 `logger.exception` 过了，再记一遍就是重复日志；它只记构造时上报的。
- **tracing**：还没有 `ErrorTracingSubscriber`。`TimeoutTracingSubscriber` 改一下事件类型和 span 名就能复用。
- **指标基数**：`lmcache_mp.errors` 以 `exception_type` 为标签。捕获点能看到任意异常类型，但类名的数量实际上有限，应该可控，需要在真实负载下确认。

## 6. 为什么不用 `sys.monitoring`

Python 3.12 的 PEP 669 有全局的 RAISE 事件，表面上能做到“任何异常都报”。不用它的原因：

- 每次 raise 都会触发，包括库内部当控制流用的 `StopIteration`、查字典 miss 的 `KeyError`，噪声太大，开销也大。
- 它不知道这个异常最后有没有被处理。思路 B 的捕获点天然带着“这个请求失败了”的语义。

## 7. 改动清单

| 文件 | 改动 |
|---|---|
| `lmcache/v1/common/observable_error.py` | 新增：`ErrorObserver`、`register_error_observer`、`report_error`、`ObservableError` |
| `lmcache/v1/common/timeouts.py` | `LMCacheTimeoutError` 改为继承 `ObservableError`，去掉自己的观察者槽位 |
| `lmcache/v1/mp_observability/errors.py` | `publish_timeout` 换成 `publish_error`，加上 `_construction_frame` |
| `lmcache/v1/mp_observability/event.py` | 新增 `EventType.ERROR_RAISED = "error.raised"` |
| `lmcache/v1/mp_observability/event_bus.py` | `init_event_bus()` 改为注册 `publish_error` |
| `lmcache/v1/mp_observability/subscribers/{logging,metrics}/error.py` | 新增 `ErrorLoggingSubscriber` 和 `ErrorMetricsSubscriber`（指标 `lmcache_mp.errors`，标签 `exception_type`、`source`） |
| `lmcache/v1/mp_observability/config.py` 和两个 `__init__.py` | 注册并导出这两个 subscriber |
| `lmcache/v1/kv_codec/errors.py` | 思路 A 的示例：`CorruptEncodedKVError` 接入 |
| `lmcache/v1/multiprocess/transport/zmq_impl/mq.py` | 思路 B：三处捕获点调用 `report_error` |
| `docs/design/v1/mp_observability/{errors,EVENTS,METRICS}.md` | 英文文档同步 |
| 测试 | `test_errors.py` 加 6 个；新增 `subscribers/logging/test_error.py`（2 个）和 `subscribers/metrics/test_error.py`（1 个）；`test_mq.py` 加 1 个 |

## 8. 验证

环境：本地 WSL Ubuntu 上的一个 venv（Python 3.12.3，没有 pip 安装 lmcache），`PYTHONPATH=<worktree>`，`python -B`，`PYTHONDONTWRITEBYTECODE=1`。下面提到的实验脚本、基准脚本和排查记录都在本地，没有放进这个分支。

### 8.1 测试

| 范围 | head `389e9979` | 本分支 |
|---|---|---|
| 超时相关的原有测试（`test_errors.py` 和三个 timeout subscriber 测试） | 18 passed | 18 passed，测试一行没改 |
| 定向：上面 18 个，加上新增的 11 个 | — | 29 passed |
| `tests/v1/mp_observability` 整个目录 | — | 524 passed, 1 skipped |
| `tests/v1/multiprocess/test_mq.py` 整个文件 | 33 passed, 2 skipped | 34 passed, 2 skipped（多出来的是新测试） |
| `tests/v1/distributed/serde`（`CorruptEncodedKVError` 的使用方） | — | 79 passed, 15 skipped |

过程中出过两次失败，都查清了（完整排查过程记在本地的调试案例集里）：

- `tests/v1/mp_observability` 第一次跑是 4 failed：`test_otel_init.py` 的 stub 里手写了一份指标订阅者名单，漏了新加的 `ErrorMetricsSubscriber`。这是本分支引入的问题，已经补上。
- `test_mq.py` 第一次跑时 `test_mq_noop_request` 和 `test_mq_noop_multiple_clients` 失败（`Client 0: timeout`）。这两个测试会起独立的服务端和客户端进程，服务端要在 5 秒内就绪。那一轮同时在跑基准测试，机器负载高。单独跑这两个测试，head 和本分支各两次，都通过；再在空闲时各跑一遍整个文件，结果就是上表。

### 8.2 变异检查：故意改坏，确认测试会抓到

每个变异单独打上去，跑对应的测试，再 `git checkout` 恢复。最后确认 worktree 是干净的。

| 故意改坏的地方 | 结果 |
|---|---|
| 删掉 ZMQ 阻塞处理器里的 `report_error(exc)` | `test_blocking_handler_error_is_reported` 失败 |
| 把帧回溯换回 head 的 `format_stack()[:-2]` | 2 个失败：原有的 `test_publishes_event_when_enabled`（栈里留下了 `timeouts.py`），和新的 `test_stack_ends_where_the_error_is_constructed` |
| 去掉“已报过就跳过”的检查 | `test_each_error_is_reported_once` 失败 |
| `report_error` 去掉 `contextlib.suppress` | `test_never_raises` 失败 |
| 超时也走 `ERROR_RAISED` | `test_timeout_keeps_its_own_event_and_metadata` 失败 |
| 日志订阅者不跳过 `caught` | `test_logs_constructed_errors_only[caught-False]` 失败 |

### 8.3 用审计时的实验脚本对比 head 和本分支

审计 #6509 时写过一个服务端流程的实验脚本（`exp.py`，不在本分支：导入 `lmcache.v1.multiprocess.server`，替换 `EventBus.publish` 来记录事件）。在本分支上原样重跑，只把最后读观察者的那一行指向新模块。26 个比较项里：

- **23 项完全相同**：注册前构造不发布；初始化后发 1 个、发到当前的 bus；连续初始化 3 次后仍然只发 1 个；子类覆盖 `__str__`、非字符串参数；`futures.py:130` 这个真实抛出点的消息；发布失败和 `get_event_bus` 失败都被吞掉；`format_stack` 失败和开关函数失败都从 `__init__` 抛出；关闭时 0 次发布、0 次取栈；`init_event_bus(None)` 会发布。
- **2 项只是脚本文件名不同**（`exp.py` 和 `exp_branch.py`）：`2_event`、`5_stack_tail`。把文件名统一以后逐字相同。
- **1 项是有意的变化**：`4a_stack_tail`，子类重写了 `__init__` 时栈的结尾（见 4.2）。
- 另外，观察者的名字从 `publish_timeout` 变成了 `publish_error`。

### 8.4 其他

- 客户端导入闭包：见 3.3。
- 复制和 pickle：在本分支上实测，和 head 一样，构造、copy、pickle 各发 1 个 `TIMEOUT_RAISED`，后两个的 `session_id` 是空串。`CorruptEncodedKVError` 发 `ERROR_RAISED`，`isinstance(..., CodecError)` 仍然为真。
- 行宽：改动的 `.py` 文件都没有超过 88 列（`pyproject.toml` 的 `line-length = 88`）。ruff、isort、mypy 在这个 venv 里没装，没有跑。

## 9. 和 #6509 的关系，以及下一步

- 本分支基于 #6509 的 head，依赖它已经把 `LMCacheTimeoutError` 移到 `common`。#6509 本身不需要改。
- 如果要正式做，建议等 #6509 合入以后分两个 PR：
  1. 通用观察者、`ERROR_RAISED`、两个 subscriber、ZMQ 捕获点，再加一个接入的类。
  2. gRPC 三种服务器的捕获点，加上 tracing subscriber。
- 正式做之前要先定下来的：第 4.4 节哪些类接入、第 5.4 节的 `ValueError` 和 `session_id`、第 4.5 节要不要处理 pickle。
