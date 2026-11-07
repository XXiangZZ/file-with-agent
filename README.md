# 档案著录智能辅助工作台（最小版本）

在原 PySide6 桌面应用上增量扩展，原 SQLite 著录、JSON 字段模板、必填/日期格式校验、草稿和 Excel 导入导出流程继续使用。源码位于 `archive_tool/`；旧发布目录中的 EXE 不包含本次改动，需要从源码启动或另行重新打包。

## 项目来源与贡献范围

本仓库是 [XXiangZZ/file-with-agent](https://github.com/XXiangZZ/file-with-agent) 维护的独立增强版，基于共同开发项目 [wordsandideas/code](https://github.com/wordsandideas/code)，从原项目提交 `72be23b2d42fc35c989575233a9d27d3740c2849` 继续开发，并保留原有完整 Git 提交历史与作者署名。

原项目提供档案著录、模板、校验、草稿、扫描预览、PaddleOCR 和 Excel 导入导出基础。本增强版新增 LangChain 文档切分与检索链、本地知识库、带出处的规范摘录问答、字段建议与确认回填，以及对应测试、脱敏评测和运行说明。原系统属于共同开发成果，不将其全部归为增强版维护者的独立贡献。

原项目未提供根目录 LICENSE 文件；本仓库不擅自为原有代码重新指定开源许可证。原有代码和随附第三方模型的使用与分发条件，仍以原作者约定及各自许可说明为准。

## 运行

本次验证环境：Windows、Python 3.11.9、PySide6 6.11.1、PaddleOCR 2.9.1、PaddlePaddle 2.6.2、NumPy 1.26.4。推荐新建虚拟环境，不改动已有生产环境。

在本 README 所在目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r archive_tool/requirements.txt -r archive_tool/requirements-assistant.txt
.\launch_workbench.ps1
```

已有依赖可直接安装 `requirements-assistant.txt`。启动脚本为旧 Paddle 设置 protobuf 的纯 Python 兼容模式；也可以在启动前自行设置 `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`。辅助依赖使用 LangChain Core 的真实 `Document`、`BaseRetriever`、Runnable 链，以及 LangChain 的递归切分器，不是依赖占位。

程序继续使用源码目录 `archive_tool/data/archive.db`。仓库已含历史数据库，测试不会以它为测试库。知识库另存为 `archive_tool/data/knowledge.sqlite3`；不会迁移或修改发布目录 `../data/archive.db`。正式使用前应备份自己的档案数据库，并明确要启动哪个版本。

### 本地 OCR

原项目历史包含 OCR 模型文件，本增强版保留它们；若下载方式遗漏大型模型文件，或希望复用已有发布包，请指定完整模型目录，包含检测、识别和方向三个子目录的模型及参数文件：

```powershell
$env:ARCHIVE_OCR_MODEL_DIR = '完整路径\models\paddleocr'
.\launch_workbench.ps1
```

若本仓库位于旧发布目录的 `source` 子目录，启动脚本会自动找到相邻的 `_internal/models/paddleocr`。辅助解析器不自动下载模型；缺失权重会提示失败并保留旧索引。Windows 下模型目录含中文时，为兼容 Paddle 2.x 原生加载器，将模型复制到临时目录后加载。系统临时目录也需为 Paddle 可读取的路径。

PDF 逐页提取文本，无文本页才 OCR。图片支持 PNG/JPEG/BMP/TIFF（含多帧），文本支持 UTF-8 TXT/MD，TXT 中换页符保留页号。少量文本覆盖在扫描图上的混合 PDF 不会自动整页 OCR，需人工核查；本版本不解析 Word/Excel 知识库资料，原应用的预览和 Excel 功能不受影响。

## 演示步骤

1. 启动后进入原“档案录入”，选择“文书”模板及自己的测试批次。点击“查规范 / 字段建议”。
2. 保持适用范围“文书”，导入 `evaluation/fixtures/rules.txt`、`manual.txt`、`ocr_errors.txt`。`manual.txt` 可选择“手册”；文件类型由导入时明确指定。所有资料都是人工构造测试文本，不是正式标准。
3. 把 `contract.txt` 以“合同”范围导入。将 `sample.txt` 以“样例”导入。样例不会被当成规范问答证据；合同资料不会在文书范围被检索。
4. 询问“文件题名如何填写”“跨页题名和副题名如何处理”；查看逐字摘录、来源文件、页码和片段起始字符位置。询问“档案密级如何确定”会返回证据不足。
5. 重复导入不变文件应跳过。修改测试文件后再次导入会替换该文件索引；也可删除选中资料或重建索引。不会监视磁盘文件变化；文件修改后必须重新导入。重建单文件失败保留该文件旧索引，并显示失败清单。
6. 点击“选择档案原文并获取建议”，选择 `sample.txt`（或先在原预览打开该文件，再选“从当前预览原文获取字段建议”）。查看题名、日期、责任者及对应原文。原文只在本机解析，不导入规范库，也不发送给模型。
7. 建议默认不勾选。勾选所需字段，点击确认回填并确认弹窗。仅填空字段；已有值不会被覆盖。然后使用原有校验、保存、导出功能。取消确认不会写入，确认回填本身也不会保存数据库。
8. `evaluation/fixtures/sample_scan.png` 是同一脱敏样例的人工生成图片，可用完整本地权重验证 OCR。它不是来自真实档案的扫描件。

## 可选模型与嵌入服务

复制 `archive_tool/config/assistant.example.json` 为同目录 `assistant.local.json`。配置 OpenAI 兼容的 `/embeddings` 和 `/chat/completions` 服务地址及实际模型名；密钥仅从 `api_key_env` 指定的环境变量读取，本地配置已加入忽略规则。非本机端点要求 HTTPS。

默认不调用任何模型服务。辅助窗口显示服务目标；每次打开窗口均需重新勾选允许发送。允许时发送的是问题及所选范围的知识库文本（嵌入会发送该范围全部规范/手册片段），不发送字段建议使用的档案原文。LangSmith 自动追踪在问答链调用内明确关闭。请不要将未脱敏档案作为规范导入后再授权外部服务。

未配置时：中文字符关键词余弦为基线；混合检索使用同义词扩展、字符/二元组 TF-IDF 与本地 SVD 潜在语义分析（LSA）加权组合。它不是预训练中文语义模型，不能承诺复杂语义理解。索引文本和元数据保存在本地 SQLite；LSA 在查询时基于当前语料重新计算，适合小型资料库，大库尚未优化。

配置嵌入模型并勾选后：远端嵌入相似度与词法得分组合。配置生成模型后：模型只能选择原文摘录；返回的片段 id 和逐字引用须匹配检索证据，不展示模型自由生成的结论。语义适用性仍需人工核查。模型超时或不可用时提示并退回本地检索摘录。当前未使用真实外部服务验证质量或兼容性。

## 测试和评测

```powershell
python -m pytest tests -q
python evaluation/run.py
$env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION = 'python'
$env:ARCHIVE_OCR_MODEL_DIR = '完整路径\models\paddleocr'
python evaluation/check_ocr.py
```

评测结果见 `evaluation/results.json`，逐题引用核对与限制见 `evaluation/human_review.md`。6 个可回答问题计算宏平均；另有 1 个无答案问题单独检查拒答。跨页题把两个来源页都列为相关，Recall 是召回相关页比例。

| 本次本地实测 | Recall@1 | Recall@3 |
|---|---:|---:|
| 关键词基线 | 0.8333 | 1.0000 |
| 混合检索 | 0.8333 | 1.0000 |

这组人工小样本没有测出混合检索整体提升，不代表生产准确率。OCR 错误题使用人为注入错字的文本；另一次真实 Paddle OCR 冒烟结果见 `evaluation/ocr_result.json`，只验证一张人工生成图片可解析，不能计算真实扫描件准确率。未测生产吞吐、延迟或业务效益。

## 实现清单与边界

- `assistant/parsing.py`：分页解析、已有 OCR 复用、模型缺失与空文本处理。
- `assistant/index.py`：SHA-256 增量判断、原子替换、本地独立 SQLite、类型/范围/来源/页码/位置/导入时间、删除和版本失效重建。
- `assistant/retrieval.py`：LangChain 检索器、词法基线、本地 LSA 混合及可选配置嵌入。
- `assistant/generation.py`：LangChain 检索→证据摘录链；明确标签的题名/日期/责任者提取，日期真实性及歧义检查，证据不足拒绝建议。
- `assistant/services.py`：可选模型/嵌入接口、凭据环境变量、超时、逐字引用校验。
- `assistant/form_fill.py` 与辅助窗口：后台处理、进度、失败提示、处理中防重复操作与关闭、默认未选建议、用户确认后仅回填空字段。
- `tests/`：索引、PDF/OCR 适配、范围、拒答、引用、歧义、真实录入页确认流程、后台状态、原校验与 Excel 导出回归。均使用临时测试数据库。

自由文本中没有明确标签的复杂题名/落款不做自动推断。尚未支持任意问题的自然语言归纳、规范冲突裁决、扫描图中文字高亮定位、大型向量库或中途取消 OCR。单文件重建原子提交，整库重建不是一个大事务；单个失败会保留其旧索引。已有索引保留导入时快照，来源文件改变后需重新导入；不以旧文件位置冒充实时文件状态。
