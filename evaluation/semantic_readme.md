# 独立语义评测

新增功能：用与生成模型不同的裁判判断faithfulness（事实句能否由证据支持）和context precision（召回片段是否帮助回答问题），并输出理由及逐字证据。语义判断是补充评测，不取代生产端的逐字出处、元数据硬核验、整段answer覆盖、拒答和审批限制。

实现：semantic_eval.py:judge走现有ModelService.complete_prompt；validate用Pydantic extra=forbid与StrictBool，要求每条输入恰好一个判断且支持/相关判断必须给真实证据；aggregate计算微平均事实支持率、相关片段比例和按排名平均精度。没有RAGAS、厂商SDK或新依赖，生产链不会为了评测额外调用裁判。

本次生成模型qwen3.8-flash，裁判为用户指定deepseek-v4.1-flash，复用既有兼容端点/凭据。没有查询或提交密钥。使用不同模型可减少自评偏差，不能替代独立业务评审。入口拒绝把同一模型名作为“独立裁判”，但不证明服务商底层模型或训练数据独立。

## 样本与分母

- semantic_questions.json：10个开发者校准样本，11条claim、16条上下文；含否定、数字、条件范围、伪操作完成、越权上传、提示词注入、返回上限与总数混淆。标签由开发者给定，不是业务人员盲标。
- local_focused_excerpts：原42题本地检索top-4与实际展示摘录，共104条摘录行、158片段。复制原文本身容易得到1.0忠实度，不应冒充模型生成准确率。题目/gold与原P0一致。
- new_raw_generation_exact_topk：固定N01/N02/P01/M01/M03/M04/C05/R01/R08共9题，真实chat新生成原始claims，不先按应用支持校验筛掉失败claim；独立裁判只用同次检索top-k。空claim不进入faithfulness分母，不记作1.0。
- previous_real_display_full_scoped_context：上轮真实生成历史只保存已核验展示文本，未保存原始top-k/claims，因此这6题只与全范围合成上下文核对；不能当原始生成评测，也不能与其他context precision混合。

context_precision为相关片段数/实际评判片段数；context_average_precision对相关片段按排名计算累计精度，无相关片段时AP不定义并另列数目。失败输出不进入成功判决分母，failed_samples明确列出，不能将成功子集高分外推全部。

所有模型reason仅为模型意见；evidence逐字存在才能通过本地schema校验。失败包括缺项、额外字段、截断或错误JSON、引用改写，以及服务错误；不重试语义错误，保留失败。第二版把裁判max_output_tokens从2048升到8192以容纳逐项理由，没有放宽schema/引用条件。首轮失败不能单凭错误码全部归因为截断。

## 运行

默认离线只准备样本与人工复核清单，输出semantic_offline，不覆盖已交付真实报告：

```powershell
& 'E:\python311\python.exe' -X utf8 evaluation/semantic_eval.py
```

显式授权真实裁判：

```powershell
& 'E:\python311\python.exe' -X utf8 evaluation/semantic_eval.py --allow-model-calls --config archive_tool/config/assistant.local.json --judge-model deepseek-v4.1-flash --output-dir evaluation/semantic_new
```

裁判可用另一个本地JSON配置（格式同ModelService）通过--judge-config传入。没有配置时不会建服务。新生成9题并只评该组和校准题：

```powershell
& 'E:\python311\python.exe' -X utf8 evaluation/semantic_eval.py --allow-model-calls --config archive_tool/config/assistant.local.json --judge-model deepseek-v4.1-flash --generate --raw-only --output-dir evaluation/semantic_raw_new
```

真实请求只发送合成资料/问题/字段与内置手册，不读生产archive.db。运行trace遵守摘要规则。samples.json是脱敏评测审查材料，保留问题、同次contexts及原始claim文本以便复算，并不是生产运行日志；不保存完整API响应、prompt或凭据。review_samples.json为待人工复核清单，尚未由独立业务人员评阅。

## 已交付报告

semantic/保留v1共58样本及其17个失败；semantic_v2/保留v2共58样本（42题本地组通过、历史展示组仍有逐字片段检查失败）；semantic_raw/为首次新原始生成19样本；semantic_raw_final/是补齐完整可审查samples.json后固定9题的另一次生成与判读。所有运行均保留，没有挑选最高分覆盖失败。

最新汇总从JSON自动生成到p0_p1_followup.md；原始判决以semantic_results.json为准。校准与标签一致25/27，冲突案例中两侧版本条款相关性出现分歧，不能在面试中说裁判100%准确。新原始生成仅9题，一次运行可受服务波动影响，和上轮15/18同模型蕴含核验不是同一批输出或同一裁判，不能当作同口径提升。

后续人工工作：从review_samples.json按否定、数值、冲突、拒答及随机普通题盲标，再比较模型裁判和人类标签；对不一致样本审查标注定义，而非只为提高符合率修改题库。此人工环节待完成，不伪造复核签名或生产质量结论。
