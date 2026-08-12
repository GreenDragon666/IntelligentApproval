# 步骤一、二代码阅读标注

步骤一、二实现“招标文档 + 政策规则 → `rules_matched.json`”，不是原医疗规则抽取程序的直接改版。

## 1. 调用顺序

```text
prepare_case.py::main
  → cont_match.pipeline.prepare_case
      ├─ dir_extr.extract_document     # 多格式适配 + 归一化分页
      ├─ dir_extr.split_sections       # 书签优先，标题规则兜底
      ├─ cont_match.load_policy_rules     # JSON/XLSX政策规则
      ├─ HybridSectionMatcher                # 字符TF-IDF + BGE-M3融合top-k
      ├─ cont_match.select_candidates         # 可选本地Qwen重排/拒绝
      ├─ rule_schema.MatchedCase             # 正式契约校验
      └─ outline/sections/matches/manifest   # 可追溯中间产物
```

## 2. 内部数据结构

| 类型 | 作用 | 生命周期 |
|---|---|---|
| `PageText` | 一页来源/转换/逻辑页的页码、标签和文本 | 文档提取 → 章节拆分 |
| `DocumentSection` | 一个可匹配章节的标题、双页码范围和原文 | 章节拆分 → 候选召回/正式 evidence |
| `PolicyRule` | 从政策表读出的整数序号、原文、逻辑、检查方式、结构化字段和匹配提示 | 规则加载 → 候选召回/正式 rule |
| `SectionCandidate` | 某规则与某章节及字符、embedding、融合分数 | 召回 → Qwen 重排/调试产物 |
| `MatchedCase` | 对外正式 JSON 契约 | 流水线最终输出 |

## 3. 逐函数说明

### `src/dir_extr/documents.py`

| 函数/类型 | 作用 |
|---|---|
| `ExtractedDocument` | 统一返回分页文本、目录、源格式、提取方法和页码口径 |
| `is_supported_document` | 判断文件是否属于 PDF、Office 或纯文本支持范围 |
| `_convert_office_to_pdf` | 使用独立 LibreOffice profile 临时转换 Office 文档，避免污染源文件 |
| `_extract_docx_xml` | LibreOffice 不可用时，从 DOCX XML 抽取段落、表格和显式分页符 |
| `_read_text` | 按 UTF-8/GB18030 读取 TXT、Markdown |
| `extract_document` | 格式分派总入口，归一为 `PageText`，并可保存转换 PDF 供页码复核 |

### `src/dir_extr/pdf.py`

| 函数 | 作用 | 与原代码关系 |
|---|---|---|
| `_normalize` | 清理换行、行尾空格和连续空行，不改写正文含义 | 重写了原 `norm_text` 的通用思想 |
| `_extract_with_fitz` | 首选 PyMuPDF，逐页读取并保持页边界 | 参考原 `extract_pdf_plain_text`，但处理完整招标 PDF |
| `_extract_with_pypdf` | PyMuPDF 不可用时用 pypdf 降级 | 参考原多提取器思路 |
| `_extract_with_pdftotext` | Python PDF 库不可用时调用系统 `pdftotext -layout` | 新增的本机无依赖降级路径 |
| `detect_document_page_1` / `extract_pdf_pages` | 从 PDF Page Labels 或连续页眉/页脚页码推断正文第1页，按顺序选择文本提取器并计算正文页码偏移 | 支持人工参数覆盖；检测失败时正文页码保持为空 |
| `extract_pdf_outline` | 用 PyMuPDF 读取 `(层级, 标题, PDF页)` 书签目录；失败返回空 | 新增；供目录拆分和 `outline.json` 使用 |

### `src/dir_extr/sections.py`

| 函数 | 作用 | 说明 |
|---|---|---|
| `_heading_from_page` | 在每页前30个非空行中寻找通用中文章节标题 | 无义齿、医疗、具体招标行业词表 |
| `_make_section` | 将连续页组合成章节，计算双页码范围并插入带页码口径的标记 | 区分原始 PDF、转换 PDF 和逻辑页 |
| `_split_long` | 把过长章节按最大页数切块 | 防止检索和模型上下文被超长章节占满 |
| `_from_outline` | 按 PDF 书签起始页构造章节，同页多书签只保留一个切分点 | 书签优先路径 |
| `_heuristic` | 无书签时，根据每页检测到的标题形成连续章节 | 通用兜底路径 |
| `split_sections` | 参数校验并选择书签路径或标题启发式路径 | 对外章节拆分入口 |

### `src/cont_match/rules.py`

| 函数 | 作用 | 说明 |
|---|---|---|
| `_first` | 从一组兼容列名中读取第一个非空值 | 支持中文政策表和正式 JSON 字段 |
| `_rule_id` | 从序号单元格解析正整数，空值时用行号 | 最终仍由 `MatchedRule` 再校验 |
| `_rows_to_rules` | 把通用行字典转换为 `PolicyRule`，读取“检查方式/结构化数据展示字段”、收集匹配提示并检查重复编号 | 不读取旧 Excel 最后一列匹配原文 |
| `_load_json` | 接受规则数组或带 `rules` 数组的正式对象 | 可把无 evidence 的正式规则 JSON 再用于匹配 |
| `_column_index` | 将 XLSX 单元格列字母转换为零基下标 | 供无 openpyxl 的 XML 读取器使用 |
| `_load_xlsx` | 用 zip/XML 读取第一个工作表、共享字符串和单元格 | 重写了原 XLSX 读取思路，不保留 CSV 转换 |
| `load_policy_rules` | 按后缀选择 JSON/XLSX，拒绝其他格式 | 规则加载对外入口 |

### `src/cont_match/retrieval.py`

| 函数 | 作用 | 与原代码关系 |
|---|---|---|
| `_terms` | 将调用方已选定的查询/章节文本构造成中文/英文字符2-3 gram及特殊数字词项 | 重写原字符 TF-IDF 思路 |
| `LexicalSectionMatcher.__init__` | 为章节和标题建立词频、文档频率和 IDF | 对应原 `RpsMatcher.__init__`，但对象改为招标章节 |
| `_cosine` | 用对数词频和 IDF 计算两个稀疏 Counter 的余弦相似度 | 新增长度归一化，避免长章节天然得高分 |
| `rank` | 分别计算 rule_raw、法规依据与正文/标题的相似度并加权，返回 top-k 正分候选 | 删除原 RPS 章节和医疗关键词先验 |
| `_section_chunks` | 将长章节切成有重叠的字符窗口，避免向量模型只看到章节开头 | 新增 embedding 预处理 |
| `HybridSectionMatcher.rank_all` | 批量编码全部章节切片与规则查询，融合字符/向量分数后返回 top-k | 新增混合召回；批量方式避免逐对调用 |

### `src/cont_match/llm_matcher.py`

| 函数 | 作用 | 与原代码关系 |
|---|---|---|
| `_parse_json_object` | 依次解析 JSON 代码块或混杂文本中的第一个 JSON 对象 | 重写原 `extract_json_from_text` 思路 |
| `select_candidates` | 把规则和 top-k 候选交给本地 Qwen3-8B，校验并返回至多 N 个候选 | 重写本地 OpenAI 兼容调用；模型可返回空数组 |

### `src/cont_match/pipeline.py`

| 函数 | 作用 | 说明 |
|---|---|---|
| `_write_json` | 建立父目录并以 UTF-8、中文不转义的格式写 JSON | 统一正式输出和调试产物格式 |
| `_to_evidence` | 将内部 `DocumentSection` 转为正式 `MatchedEvidence` | 负责双页码和文件名映射 |
| `_retrieval_selection` | 无重排或模型失败时，按最低融合分数选择前 N 个召回候选 | 高召回降级，不负责判断违规 |
| `prepare_case` | 串联全部步骤、处理 LLM 严格/降级模式、写正式 JSON 和四类产物 | 步骤一、二唯一业务总入口 |

`prepare_case` 内部阶段：

1. 校验参数；
2. 提取页文本和目录；
3. 拆章节并加载规则；
4. 批量执行字符 TF-IDF 与 embedding 混合召回；
5. 可选 Qwen 重排，失败时按参数中止或降级；
6. 转为 `MatchedRule/MatchedEvidence`；
7. 先通过 `MatchedCase` 构造校验，再写正式 JSON；
8. 可选写 `outline.json`、`sections.json`、`matches.json`、`manifest.json`。

### 根目录 `prepare_case.py`

| 函数 | 作用 |
|---|---|
| `_build_parser` | 声明步骤一、二的单文件/目录批量参数，不接收手工 `case_id` |
| `_main_argv` | 将分阶段参数转换成统一入口参数，并固定加入 `--preprocess-only` |
| `main` | 解析参数后调用统一入口，自动创建 `reports/report_x` |

### 根目录 `main.py`

| 函数 | 作用 |
|---|---|
| `_reset_reports` | 新的单文件/批量任务开始前覆盖根 `reports/`；`--input` 续跑不调用 |
| `_allocate_report_dir` | 在本次运行的干净 `reports/` 中依次原子创建 `report_1`、`report_2` 等目录 |
| `_discover_documents` | 递归发现 `--reports_path` 下所有支持文档，并排除自动输出目录 |
| `_process_document` | 复制输入文档、运行步骤一二，并按参数继续执行步骤三 |
| `_write_report` | 调用审批引擎并写案件级 `summary.json`、详细 `summary.md` |
| `_write_brief` | 将本次完成的一个或多个案件写成唯一的根目录 `reports/summary_brief.md` |
| `_validate_args` | 校验三种输入模式和模型/生成参数组合 |
| `main` | 处理已有 JSON、单个文档或目录中的全部支持文档 |

## 4. 明确没有复用的部分

- 从医疗 DOCX 中“发现新规则”的整套启发式；
- 义齿、医疗器械、产品标签、RPS 章节先验；
- 医疗标准文件索引、前4页 OCR 和引用标准展开；
- 医疗规则 A/B/C 分类及固定“审评流程/发补意见”生成；
- stage1/stage2 CSV 中间接口；
- 进程内 transformers 模型加载、显卡选择和 bitsandbytes 量化；
- 原 stage2 JSONL 模型结果缓存。

## 5. 当前边界

- 支持有文本层 PDF；扫描 PDF 当前明确报错，尚无通用 OCR 适配器。
- 无模型模式是高召回候选模式，不能可靠拒绝“文件中没有相关内容”的规则。
- `--use-llm` 只控制步骤二的章节相关性重排；最终判定由步骤三全局结构化执行器或语义 LLM 完成。
