# 模型调用可靠性与预算

新增功能：有限重试/退避、实例级熔断、共享任务总时间与请求/token预算、可选金额估算护栏。所有调用仍复用urllib，无额外SDK、框架或重依赖。

## 文件与实现

- assistant/runtime.py:RequestBudget、task_budget、budgeted：ContextVar使一次ask/ask_manual/run_agent及嵌套模型/嵌入/蕴含请求共享预算；重试每次都预留次数和token，不退还超时请求，以防服务端已计费。函数返回后清理上下文，摘要写既有JSONL。
- assistant/services.py:ModelService._post：根据剩余总时间压缩socket timeout，发送前检查预算，成功后再次检查截止时间；聊天请求加max_tokens上限；只在暂时性故障下有限重试。类别/耗时/attempt/delay进入脱敏trace，不记录异常正文、端点或凭据。
- ask/ask_manual/run_agent：使用budgeted；现有本地回退保留。Agent计划不因服务错误丢失，不批准/不执行。请求预算与原4轮、8调用/轮、16工具调用为不同限制：一次模型轮次内部还可能有嵌入或重试，全部HTTP均计入预算。

配置沿用assistant.local.json；示例见assistant.example.json。默认值：

| 参数 | 默认 | 含义 |
|---|---:|---|
| timeout | 30秒（既有本地配置可能不同） | 单次urllib等待上限，范围1–600秒 |
| task_timeout | 180秒 | 一次问答共享时间预算，范围0.01–3600秒 |
| max_requests | 16 | 包含重试、嵌入与事实核验的实际请求次数 |
| max_task_tokens | 256000 | 请求内容UTF-8字节数+256封装余量+最大输出的估算累计预算 |
| max_output_tokens | 2048 | 每次聊天最大输出，裁判评测单独设8192 |
| max_retries | 1 | 首次之外最多重试数，允许0–3 |
| retry_backoff | 0.25秒 | 指数退避起点，附小随机抖动 |
| breaker_threshold | 3 | 同服务实例、端点和路由连续暂时性失败次数 |
| breaker_cooldown | 30秒 | 实例级熔断冷却时间 |

开启金额预算必须同时填max_task_cost，以及chat的input_price_per_million/output_price_per_million或embedding的embedding_price_per_million；单位均为用户选择的同一货币。没有单价时reserved_cost=null，不冒充免费或准确账单；要求金额护栏但缺单价会在发送前拒绝。token为估算，实际usage单独记录reported_tokens。未知分词、供应商隐藏思考token或忽略max_tokens都可能造成估算与实际账单差异；不能称财务硬上限。一个持续会话若要共享预算，必须由上层用task_budget包住多次问答；当前桌面每轮问答分别建预算，没有新增多轮会话记忆。

## 重试与熔断规则

重试TimeoutError、URLError/ConnectionError、HTTP429/500/502/503/504。401/400、其他HTTP错误、JSON格式失败、参数/支持核验错误都不重试。它只重发模型推理请求，不重试工具审批或executor写操作；服务器超时后可能已经收费，所以每次都消耗预算。

退避为base×2^attempt加0到base/4抖动，支持Retry-After秒数或HTTP日期；若服务器要求等待超过10秒或超过剩余预算，立即降级，不长时间占用后台线程。熔断在实例中按端点/路由维护，成功清零，连续暂时性故障后冷却内不请求；冷却后允许试探。不是跨进程熔断、没有严格单探针half-open，UI创建新实例也会重置熔断状态，不能夸大为全应用服务治理。

urllib timeout是socket操作超时，不能强行中断任意阻塞的系统调用、分块慢速响应或本地SVD；因此task_timeout是请求入口与回包边界的deadline守卫，不是绝对实时终止保证。超时不会让executor在后台继续自动写库。

## 桌面同步为何暂可接受

UI已经把问答任务放到后台Worker，ModelService内部同步等待并不等于主线程卡住。单用户、有限轮次和请求预算下，这种结构容易调试；但Worker占用到返回、关闭/取消仍需遵循已有流程。本次不加流式答案：未核验事实不能提前展示。

服务化时应改为可取消的异步HTTP/连接复用、排队与并发限流、请求级deadline传播、按租户共享预算与熔断；SQLite连接/事务与鉴权另行设计。单纯给现有函数加async不会让urllib变非阻塞。当前没有实现异步网络、流式、多用户或部署监控。

回退：max_retries=0可关闭重试；原离线默认与授权开关不变。预算/熔断失败沿本地摘录/只读工具回退。不要通过提高模型权限、开放删除/上传或自动批准来“提高成功率”。tests/test_runtime_guards.py用假时钟/假网络覆盖暂时/永久错误、Retry-After、恢复、嵌套预算、金额、token和本地回退，不发真实请求。
