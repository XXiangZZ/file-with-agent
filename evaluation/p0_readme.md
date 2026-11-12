# P0 评测与本地诊断

已实现 42 道开发者编写的脱敏回归题，分为常规8、近义改写8、错字/OCR6、多证据6、冲突6、拒答8。34道有标注证据，8道应拒答。语料为4个合成文件与7篇内置操作指南，共11文件、13页、13切块；不是独立业务人员盲测。每题gold包含来源文件名、页码和必要原文片段，运行前逐一校验存在性。OCR题为人工错字转写，不测实际OCR准确率。

## 复现

在源码目录运行：

```powershell
Set-Location -LiteralPath 'D:\软件归档\archive_tool\source'
& 'E:\python311\python.exe' -X utf8 evaluation/p0_eval.py
& 'E:\python311\python.exe' -m pytest tests -q
```

默认模式不读取模型配置、不构造ModelService、不联网；KnowledgeIndex放在TemporaryDirectory，不访问生产archive.db。输出`p0_results.json`（逐题、分类、指标分子分母、依赖版本、语料哈希）、`p0_comparison.md`（对比表）、`p0_traces.jsonl`（本地诊断）。日志有时间和随机run_id，故不要求逐字一致；测试要求两次评测的逐题结果与指标一致。

需要指定其他输出位置可用`--output-dir`。外部向量路径只有同时提供`--allow-model-calls --config <配置文件>`才启用；该选项会发送合成夹具、内置手册和脱敏评测问题用于嵌入，仍不调用聊天模型。授权前先完成gold检查。该路径本次仅用假服务做自动测试，已交付报告中的真实外部向量标为未运行。

## 方法与指标

复用`ArchiveRetriever._get_relevant_documents()`、`latent_scores()`、`evidence_answer()`、`local_answer()`和`verify_grounded_answer()`。原hybrid保留并仍为默认检索方式；本地摘录默认使用focused过滤，可退回legacy。新增可选BM25+RRF；不改切块500/80和top-4。详细原因、配置、回退和风险见`rag_improvement_review.md`。

旧四组keyword、lsa_only、hybrid_no_rerank、hybrid显式使用legacy证据选择，继续复现P0；增加hybrid_filtered、bm25_only、bm25_rrf_legacy、bm25_rrf_no_rerank、bm25_rrf。完整定义在p0_comparison.md。所有组共享作用域、问题改写和类型过滤，返回top-4，计算其前1/3片段的来源页召回。无重排组用全量候选的retrieval_score排序，取前4；这对应生产候选初排前缀。LSA是当前语料上拟合的TF-IDF/SVD，不是预训练语义模型。单路和取消重排仅存在于评测，不进入生产默认路径。

- Recall@1/3：对34道可回答题，先计算期望来源页的召回比例，再宏平均。同页多个标注只算一个相关页。
- 引用正确率：出处存在且引用含该题至少一条gold必要原文的引用数/全部引用数；是严格标注对齐代理，不能称语义准确率。
- 引用真实性：引用逐字存在于对应来源页；空引用不参与分母，无样本为null。
- 拒答率：8道拒答题中无引用的比例；另报34道可回答题的误拒答率。R08的主题相关规则摘录仍按严格口径记为未拒答，并不意味着系统肯定了用户提供的日期。
- 摘录事实支持通过率：对展示的规范摘录行或手册编号行，同时检查出处存在及现有claims token支持核验。不把固定回答提示语计作事实句。由于内容为原文复制，高分不证明适用性。
- 必要证据全覆盖率：可回答题中所有gold片段均被至少一个引用覆盖的题数比例；不证明已完成多跳推理或冲突效力裁决。
- 生成事实句支持率：本次未运行聊天生成，输出null。现有verify_grounded_answer核验claims，不保证独立answer文本与claims完全一致。

P0旧keyword与hybrid均为Recall@1 0.8088、Recall@3 1.0、引用正确率39/73=0.5342、拒答7/8=0.875、误拒答1/34=0.0294、必要证据全覆盖31/34=0.9118。当前默认hybrid_filtered的检索指标不变，引用正确率41/49=0.8367、全覆盖33/34=0.9706。各组引用真实性与摘录支持通过率均1.0；这是复制原文核验结果，不是答案准确率。可选bm25_rrf的Recall@1为0.8235、Recall@3为0.9853，存在回退，因此没有设为默认；不声称新方法整体更好。

题库与gold保持原样。默认链路已补齐M03/M04的必要证据；保留O04“责仼者”错字误拒答及R08相关规则未完全拒答。BM25+RRF另有M03重排回退，完整逐题差异和被过滤原文由p0_results.json的changes/evidence_audit自动生成。p0_baseline.json保留验收的P0结果，测试逐项验证旧四组指标仍与其相同；stage1/stage2保留中间实现的历史输出，包含当时退化，不代表当前代码运行结果。

## 文件和函数

| 文件 | 入口与职责 |
|---|---|
| evaluation/p0_eval.py | load_questions/validate_gold验证标注；retrieve执行复用与消融；score_answer/metrics计算；run生成报告 |
| evaluation/p0_questions.json、fixtures/p0/ | 题目、必要证据、合成干扰与冲突条款 |
| assistant/tracing.py | LocalTrace.emit、traced、verification；本地轮转、上下文关联、问题指纹与摘要 |
| assistant/retrieval.py | _get_relevant_documents结束时记录ID、页码、两类分数 |
| assistant/rag_settings.py | evidence_mode/retrieval_mode读取请求时环境配置，支持回退 |
| tests/test_rag_improvements.py | 未见过的条款、条件归属、冲突保留、BM25公式、RRF、范围/向量校验与开关 |
| assistant/generation.py | ask记录链路与回退；verify_grounded_answer记录通过/失败；模型蕴含检查单独记录 |
| assistant/manual.py | ask_manual记录调用/回退；verify_model_answer记录整行步骤验证 |
| assistant/services.py | post记录耗时、chat/embedding路由、整数usage；timeout/http/network/invalid_json分类 |
| assistant/agent/runner.py | run_agent记录轮次/调用序号；_invoke_untraced记录工具和模型耗时；_verify_agent_answer记录最终核验 |
| tests/test_p0_evaluation.py | 分母/伪引用、全套重复运行、默认无服务、坏gold先失败、可选假向量路径 |
| tests/test_local_tracing.py | 嵌套链路、脱敏、未知工具/坏参数、服务错误、并发、轮转/目录保护、失败保留计划且业务零写入 |

## 本地轨迹取舍

选JSONL避免给档案库加表、事务和迁移；只用标准库。一个问题及其嵌套工具/RAG/模型请求共享run_id和递增seq。记录问题长度与SHA-256指纹，适合拿已知问题比对，不是可逆问题存档或匿名化保证。完整脱敏题目可查评测报告。工具参数仅数量、值类型和字段数量；结果仅错误标记、引用数量、计划标记和条数。未知工具名用unknown，不保存模型任意文本。来源仅chunk id和页码；不写完整路径或引用原文。模型响应仅整数token用量，缺失时不估算。

默认日志在知识库文件同级的logs/assistant.jsonl，独立post调用使用config.settings.LOG_DIR。测试及评测可传trace_path。单文件2 MiB，另保留一个.jsonl.1备份；进程内线程锁保证整行追加，ContextVar隔离并发问题。非普通文件或符号链接拒绝用作日志，避免误移动目录；日志写入失败不会中断业务或改变审批状态。采用有界覆盖而非永久审计，轮转可能切断旧轨迹；不支持多进程共享日志文件，无防篡改/崩溃持久性保证，日志失败目前不另增UI告警。

应用RAG、Agent原有LangSmith tracing_context(enabled=False)保留；新评测显式关闭远程追踪。事务operation_log仍由PlanExecutor按原逻辑与业务写入同提交，不由诊断日志替代。计划状态、快照与完整工具消息不落JSONL，不支持从轨迹批准/执行或恢复。

## 验收与排除范围

测试分层沿用现有pytest入口：指标/语料与离线授权；模型传输假响应与降级；Agent循环、待确认保留及零写入；原有审批/主线程/CAS/事务回滚与UI回归。新增测试全部使用临时知识库及临时archive.db。

本次未改planner、executor、数据库、业务UI和打包EXE；未安装依赖，未发真实模型请求。明确不做自动审批、直接模型写库、删除/上传工具、计划持久化恢复、FastAPI、大规模向量库、多用户权限、流式输出或部署监控。对外描述为“证据约束 RAG + 受控有界工具循环”。待补的独立业务盲测、真实模型质量评测及真实扫描件评测，不以本报告替代。
