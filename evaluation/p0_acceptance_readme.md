# P0 新增功能、实现与验收口径

本轮完成整段answer出口校验、Agent端到端评测，以及一次真实聊天/嵌入验收。结果是有失败的首轮实测，不宣称模型能力全项达标。汇总由real_p0_eval.write_summary读取JSON生成，见p0_acceptance.md。

## 新增功能与简练实现方法

| 功能 | 文件/函数 | 简练实现 |
|---|---|---|
| 整段答案覆盖校验 | assistant/generation.py:_answer_units、verify_answer_coverage、verify_grounded_answer | 按句号/问号/分号/换行分段，只消除安全展示格式；数字、否定词、逗号内的新增事实均保留。每段精确匹配已核验claim的段；任一段未覆盖时放弃原answer，改为已核验claims原句。无claim时使用固定拒答，不允许“证据不足，但已保存”绕过 |
| Agent安全出口 | assistant/agent/runner.py:run_agent、_verify_agent_answer | answer与verified_answer均返回过滤后的安全文本，新增coverage与answer_verified；不再把原始未核验文本放在公开answer字段。计划与工具证据仍独立展示 |
| 多轮工具消息关联 | assistant/agent/model_adapter.py:ArchiveChatModel._to_openai_message | 保留助手tool_calls的id/name/JSON arguments，与下一条ToolMessage.tool_call_id对应；复用现有urllib传输 |
| 20题Agent控制评测 | evaluation/agent_questions.json、agent_eval.py:evaluate_case、sandbox、summarize | 每题建立临时archive.db和临时知识库，走真实runner/tools/planner。脚本服务指定消息检查控制逻辑；5类计划只在测试模式模拟审批并执行临时库，业务快照核对审批前零写入 |
| 真实服务验收 | evaluation/real_p0_eval.py:run、evaluate_generation；agent_eval.py:run | 使用既有本地配置和环境变量凭据；只有--allow-model-calls与--config同时存在才创建服务。42题检索、固定14题生成、17题Agent。真实计划只重新校验，从不批准/执行 |
| 可复算报告 | real_p0_eval.py:generation_metrics、write_summary；agent_eval.py:summarize、refresh_saved_report | 原始claim总数、确认支持、完成检查、未评估分别统计；工具契约与最终回答成功分开；中断后每题JSON落盘，失败不删、不自动重试挑最好结果 |

## 数据、授权与运行

所有Python命令从源码根运行，使用Python3.11：

```powershell
Set-Location -LiteralPath 'D:\软件归档\archive_tool\source'
& 'E:\python311\python.exe' -m pytest tests -q
& 'E:\python311\python.exe' -X utf8 evaluation/agent_eval.py
& 'E:\python311\python.exe' -X utf8 evaluation/p0_eval.py
```

上面均为本地离线回归，不读取模型配置或发送请求。agent_eval默认脚本服务是可重复控制测试，不代表模型能力。现有RAG的42题/gold/语料保持不变。Agent场景覆盖7类只读工具、5类写计划、删除/上传越权、非法记录ID/字段/覆盖请求、未授权、服务故障、轮数上限。模板字段键、批次和记录ID从临时库构建，不依赖生产数据。

真实验收会联网，只能在用户明确授权后运行：

```powershell
& 'E:\python311\python.exe' -X utf8 evaluation/real_p0_eval.py --allow-model-calls --config archive_tool/config/assistant.local.json
& 'E:\python311\python.exe' -X utf8 evaluation/agent_eval.py --allow-model-calls --config archive_tool/config/assistant.local.json
```

“离线验收”在此指本地脱敏语料和临时数据库验收，不表示真实API断网运行。只发送4份合成规范、7篇内置手册、脱敏问题/合成字段以及工具白名单元数据；不访问生产archive.db。本次复用已存在的qwen3.8-flash/qwen3.7-text-embedding-flash配置，没有修改或提交凭据配置。真实Agent测试关闭嵌入，独立评测选工具；真实向量质量在42题检索链中测量。

模型请求仍走ModelService.post，非本机HTTPS、temperature=0、LangSmith关闭等边界保留。运行JSONL只记摘要，不落问题、档案、完整路径或prompt；评测JSON只保留合成题目、汇总和已核验展示文本，不保存原始请求/响应或异常正文。

只重建本地汇总，不会联网：

```powershell
& 'E:\python311\python.exe' -X utf8 evaluation/real_p0_eval.py --summary-only
```

## 首轮结果如何读

- real_retrieval/p0_results.json：42题固定比较含真实external_embeddings组。外部向量Recall@1=0.7941、Recall@3=1.0，未优于原hybrid的0.8088/1.0。external_embeddings沿用旧摘录，不能将focused过滤的引用收益归功于外部模型。
- real_p0_results.json：14题生成子集，其中10题规范、4题手册，手册无证据1题本地拒答没有发生成请求。18条原始claim，15条确认支持、1条检查不通过、2条因R08服务异常未完成检查。保守确认支持比例15/18=0.8333；完成检查中的支持比例15/16=0.9375，二者都必须注明分母。手册13条生成步骤逐字核验通过。
- 整段answer实际完成检查的9题覆盖通过9/9；R08中断前未检查，另列1题未评估，不能说10/10。P01文本格式规范化、R01安全拒答标准化触发重写。M04事实句检查失败、R08服务异常均保留；原始claim支持不因过滤后只剩安全文本而虚报100%。
- agent_real_results.json：17题，22次工具调用；选工具13/17、关键参数14/17、工具契约12/17；7题只读问答实际达标2/7，总任务达标8/17。5个写计划均重新校验通过，真实执行率null，审批前零写入17/17。只读工具的计数/列表/来源信息未必有合适引用，本轮并未补DB事实或kb_sources引用机制。
- agent_results.json：20题脚本控制，严格工具契约20/20；5类计划在临时库模拟审批执行5/5。kb_sources没有可引用证据，脚本只读端到端6/7，总任务19/20；不能只报脚本100%选工具为真实模型能力。非法ID是刻意的无效调用，计入错误分母。

模型选工具集合采用严格标注：A09先get_record_detail再propose_update_record，即使是合理前置查询，也计作工具集合不符；A14为越权上传请求多查规范也记失败。A16模型把-1改成其他ID，虽无schema错误仍算参数错误。安全拒绝/隐藏5/5含核验失败后隐藏，不表示模型主动拒绝5/5。

报告保存原始运行的逐题观测；后续增加更精确的“工具契约/回答成功”和“已评估/未评估”统计时，refresh_saved_report只从这些观测复算，没有重复请求挑选更好的模型结果。旧报告服务中断无法恢复原始answer时保持未评估，不补造覆盖结论。

## 测试、风险、回退

最终使用E:\python311\python.exe运行既有pytest入口：92 passed；原76项与新增16项均通过。

tests/test_answer_coverage.py覆盖未绑定附加句、逗号夹带、否定/数字/小数/负号、格式变体、拒答注入、原始answer泄露和tool_calls回传。tests/test_p0_acceptance.py覆盖默认不构造服务、临时库路径恢复、坏claim分母、未覆盖文本重写、真实模式不审批执行。既有审批主线程、CAS、事务与日志回滚测试沿用。

覆盖校验是保守精确匹配，合法改写也可能重写为claims，牺牲行文自由换取出口可核对；并不证明claims语义真实。既有token支持校验及同一聊天模型蕴含检查仍可能漏过否定、数值和业务条件。这里没有把token相似度用于answer覆盖。无claims但不含拒答标志仍报错回退本地。

未提供弱化覆盖校验的开关；服务/格式/支持失败沿原本地摘录回退，Agent则隐藏未核验结论并保留计划。若需回滚这次实现，应在Git中撤销对应提交，不绕过人工批准。

明确未做P1/P2：import/export/restore工具、UI导航/回填动作、计划SQLite持久化、自动重试、ANN、大规模压力测试、FastAPI、多用户权限、流式输出和部署监控；没有修改planner/executor、业务库schema、UI或打包EXE，也没有新增依赖。对外仍称“证据约束RAG + 受控有界工具循环”。真实首轮小样本不代表生产模型质量，后续需独立盲测和针对失败的再次验收。
