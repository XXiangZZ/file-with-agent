# 流式、异步HTTP、ANN迁移与会话记忆

已实现四项可选能力并接入桌面问答。安全边界保持：只在用户勾选外部授权后建模型服务；模型原始流文本不展示；写类工具仍只提计划、逐条人工批准、主线程executor独立事务执行。没有编辑planner/executor或根目录EXE，不新增删除/上传工具。

## 新增功能与简练实现方法

| 新功能 | 文件/函数 | 实现方法 |
|---|---|---|
| 流式接收 | assistant/async_http.py:SSEMessage、AsyncModelService._request | HTTPX异步接收SSE，增量UTF-8解码，按SSE事件拼装content和分片tool_calls；只有finish_reason和[DONE]完整结束才返回。过大/中断/无效JSON不执行工具、不显示正文 |
| 核验后逐段展示 | ui/components/assistant_dialog.py:Work、publish_verified、ask；manual_dialog.py:ask | Worker可执行协程；接收时仅显示进度计数，正文经原verify_grounded_answer/手册整行校验后，通过Qt信号每80字符逐段展示。原始SSE正文从不发到QTextEdit |
| 原生异步HTTP | assistant/async_http.py:AsyncModelService.post；async_api.py:arun_agent/aask/aask_manual | async with管理HTTPX AsyncClient连接复用，原生await读写并允许取消；本地检索/SQLite/有界工具循环放在线程里，AsyncBridge把模型请求投递回事件循环。不是用to_thread包装urllib冒充异步网络 |
| 实际ANN后端 | assistant/index.py:ann_selection/ann_search；retrieval.py:ArchiveRetriever(mode='ann') | 采用本机已有SciPy cKDTree近似树，向量归一化后按欧氏距离查邻居，等价于余弦排序。先按scope/kind/model筛选再建树，eps=0.15，召回候选后沿用规则重排 |
| 向量迁移/回退 | evaluation/ann_migrate.py:migrate；KnowledgeIndex._invalidate_ann/revision | 从已存在SQLite vectors构建NPZ侧车快照，原SQLite不改、向量不删；原子替换侧车文件。进程内树缓存，重启从快照建树；导入/更新/删除/换模型使缓存失效，损坏快照从SQLite重建；默认hybrid保留 |
| 有界会话记忆 | assistant/agent/session.py:AgentSession/session_turn；runner.py:run_agent | 窗口内可选保存最近6轮、12000字符、15分钟有效的用户问题与已核验回答；不保存完整工具消息/字段值快照/计划参数。历史仅供理解指代，每轮仍须重新拿工具证据，批准状态从不进入历史 |

本次助手依赖明确增加httpx==0.28.1、scipy>=1.11,<2；本机原已安装0.28.1/1.17.1，未执行安装。没有LangGraph、langchain元包或模型厂商SDK。NumPy仍沿用已有约束。requirements-assistant.txt包含依赖，其他机器应按该文件安装。

## 桌面使用

“档案著录智能辅助工作台”新增：

1. “流式接收；核验后逐段显示”：默认勾选；仅在外部授权且配置聊天模型后请求SSE。可以取消勾选用异步非流式JSON。没有外部授权时仍本地处理，无外部请求。
2. “本窗口记住已核验对话”：默认不勾选，只有受控Agent模式使用。问题历史会随授权后的下一轮请求发送，因此需同时明确勾选外部授权。清空按钮不会批准计划；有pending/approved计划时先处理计划。窗口关闭会拒绝未处理计划并释放记忆。
3. “默认混合检索 / ANN近似向量检索”：默认保留原混合方式。ANN需要范围内已有同模型完整向量及本次嵌入授权；缺失/失效时沿现有失败路径回退本地hybrid，不悄悄为整库联网重嵌入。
4. “取消当前问答”：取消异步HTTP，关闭响应连接并等待本地循环收尾；已创建计划仍在列表待处理。取消不会执行/批准计划，也不强制中断OCR或索引事务。处理中仍禁止关闭窗口。

手册助手改为原生异步请求并在核验后逐段展示。知识库导入/OCR和旧同步ModelService接口仍保留；这些动作已在QThread后台，不宣称全部导入链改成协程。录入、校验、保存和审批流程不变。

流式并不等于即时展示未经核验token：为了保留原证据边界，本次在接收期间只显示进度，整段输出解析/核验通过后才逐段呈现。首段可见答案仍需等待完整核验；不以“打字动画”宣称降低模型首token时延。SSE真实发生在网络层，工具参数直到完整结束后才进入原有StructuredTool/PlanStore。

## 异步API与可靠性

```python
from assistant.async_api import aask, arun_agent
from assistant.agent.session import AgentSession

# service=None：完全本地；远端服务仍由调用方先取得明确授权。
result = await aask(index, "文件题名如何填写", "文书", service=authorized_service,
                    use_embeddings=True, stream=True, mode="ann")

session = AgentSession()
result = await arun_agent("查看知识库", index, service=authorized_service,
    allow_model_calls=True, session=session, stream=True)
```

AsyncModelService也直接提供async post/embed_documents/embed_query/complete_prompt/check_claim_support。必须使用async with管理生命周期；不要把异步服务对象直接传给同步run_agent，而应使用async_api，它会建立桥接。

异步路径继续共享runtime.task_budget：HTTP重试、嵌入和事实核验均消耗同一任务预算；保留token/可选金额估算、总deadline、输出上限和实例级熔断。asyncio.wait_for限制HTTP整体时间，包括不断少量返回的响应；取消会传播到HTTPX并关闭连接。本地检索/SQLite不能安全强杀，因此取消会等本地小任务收尾。SSE一旦收到数据后发生断流，绝不重试该流；可能重复收费的HTTP重试仍预留预算，不重试executor写动作。

限制：原生异步默认不跟随重定向；非本机HTTPS、凭据环境变量规则沿用ModelService。异步Retry-After支持数值秒（HTTP日期仍仅同步路径支持）；不是跨实例/跨进程熔断。直接AsyncModelService.post没有上层run_agent的完整trace span，但仍记录摘要事件；async_api通过工作线程上下文将原run_id/预算传播到HTTP协程。不写原始prompt/响应、问题正文或凭据到运行日志。

## ANN迁移、更新与一致性

`ARCHIVE_RAG_RETRIEVAL=ann`或ArchiveRetriever(mode='ann')是API开关；桌面下拉选择只影响本窗口调用，不修改全局环境或磁盘配置。默认hybrid与bm25_rrf路径保留。没有向量的本地路径自动回到hybrid。

对明确指定的知识库迁移已有向量，不调用模型：

```powershell
Set-Location -LiteralPath 'D:\软件归档\archive_tool\source'
& 'E:\python311\python.exe' -X utf8 evaluation/ann_migrate.py --db '你的knowledge.sqlite3路径' --scope '文书' --model '与vectors.model完全一致的服务身份#模型名' --kind '规范'
```

迁移器先用只读连接验证sources/chunks/vectors/feedback且不是档案records业务库；仅为知识库建立同目录`knowledge.sqlite3.ann/<范围类型模型哈希>.npz`。快照保存归一化矩阵与片段元数据/文本，不是运行日志；和本地SQLite相同隐私级别，不上传GitHub，不用于恢复批准计划。

这是**SciPy近似树ANN**，不是FAISS、HNSW或向量数据库。NPZ保存的是可安全读取的派生快照（allow_pickle=False），树本身在内存重建，不pickle可执行对象。cKDTree的eps允许近似距离，不能承诺所有查询都找回精确top-k；高维可能退化到接近扫描。本轮不声称百万级或高维预训练模型加速。

查询先校验过滤范围、模型、维度、缺失向量与版本，再调用一次问题嵌入；树构建与查询前后比较SQLite文件/WAL的纳秒时间戳和大小，变化就拒用/重建；最多保留8个范围缓存。导入、删除或重新嵌入后清理派生快照和内存树；旧快照无法删除时仍因版本指纹不符而不能使用。反馈落表也会改变文件指纹，可能引起保守重建，这是开销而非错误授权。

未使用数据库schema变更计数器，因此人为修改数据库后又伪造相同文件时间戳/大小不在保障范围；SQLite仍为权威数据。正在查询时其他进程修改会拒绝当前树结果，不是跨文件ACID快照。没有多用户权限体系或多进程共享ANN缓存。退回原模式无需删SQLite向量或重建业务库；侧车可以从SQLite重新生成。

## 会话边界

记忆在AgentSession中，关闭即丢；没有SQLite计划持久化或checkpointer。切换批次、模板、授权状态、聊天/嵌入服务身份或知识库版本会清空历史，超时同样清空。只保存通过最终核验的回答，未核验文本、完整工具结果和批准状态不记。历史消息在system中明确标为上下文而非证据；每轮仅本轮ToolMessage可提供引用ID。

会话级begin锁防止同一会话并发；pending/approved计划禁止新一轮推理或清空记忆，拒绝或执行完成后才继续。取消后产生的计划依旧pending并可见，仍需人工处理。未增加工具结果缓存，因为业务元数据随写库变化，不能用旧状态支撑当前事实。

## 验证与实测

```powershell
& 'E:\python311\python.exe' -m pytest tests -q
& 'E:\python311\python.exe' -X utf8 evaluation/async_session_eval.py
& 'E:\python311\python.exe' -X utf8 evaluation/ann_eval.py
& 'E:\python311\python.exe' -X utf8 evaluation/p0_eval.py
```

本轮完整测试138 passed，包含原119项及新增19项。覆盖SSE分片/中文/工具参数/中断、native async并发、总deadline、预算、取消关闭连接；真实本机HTTP服务贯通两轮Agent；Qt只展示核验后正文；取消后计划保留且业务库零写入；会话裁剪/过期/范围变化/并发/计划阻断；ANN范围隔离、模型/维度/零向量、更新/删除、损坏快照重建、只读迁移和精确余弦参考召回。

async_ann_memory/async_session_results.json：本机合成HTTP/SSE服务器4次请求贯通两轮，16次进度事件不含正文，两次答案核验通过，第二轮包含已核验历史；外部模型请求数0。测试证明传输/状态贯通，不证明真实模型的多轮指代能力或供应商SSE兼容性。

ann/ann_results.json：固定随机种子42、1万条32维合成向量、20次查询，eps=0.15，近邻Recall@4=1.0；warm ANN查询P50约22.16ms、P95约23.54ms；旧SQLite每次加载矩阵参考P50约228.22ms。结果包含缓存/向量加载差异，不是同缓存条件纯算法竞速；首次建树约515ms另列；不是RAG答案效果，不外推1536/3072维或百万级。更新了安全检查后耗时可能随环境略变，原始样本随报告保留。

未做：真实厂商SSE验收、真实高维ANN质量/压力测试、跨窗口会话、工具结果缓存、计划持久化恢复、服务部署和多用户；未打开模型直接写库、删除/上传或自动审批。对外口径仍为“证据约束RAG + 受控有界工具循环”。本次修改验证后推送GitHub。
