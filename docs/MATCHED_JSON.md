# `rules_matched.json` 输入契约

步骤一、二完成目录拆分、规则匹配和原文提取后，每个案件提供一个 JSON：

```json
{
  "case_id": "report_2",
  "source": {
    "file": "招标文件2.pdf"
  },
  "rules": [
    {
      "rule_id": 2,
      "rule_raw": "项目需求描述是否清晰，避免模糊或歧义。",
      "rule_text": "【描述】……【法规依据】……【公式】……【开发说明】……",
      "evidence": [
        {
          "location": {
            "file": "招标文件2.pdf",
            "section": "第一章 招标公告—二、项目概况与招标范围",
            "pdf_pages": {"start": 11, "end": 11},
            "document_pages": {"start": 3, "end": 3},
            "page_basis": "original_pdf"
          },
          "text": "二、项目概况与招标范围……"
        }
      ]
    }
  ]
}
```

约定：

- `case_id` 由程序根据新建的 `reports/report_x/` 自动生成，不从命令行传入。
- `source` 只允许 `file` 字段。
- `rule_id` 必须是正整数，对应规则序号。
- `rule_raw` 是规则原文，对应“重点排查情形”。
- `rule_text` 是用于生成 checker 的完整规则，对应“触发逻辑公式”。
- 一条规则可关联多个文件或章节，因此 `evidence` 固定为数组。
- 没有匹配到原文时使用 `"evidence": []`，不得填充模拟内容。
- `pdf_pages` 保留原字段名以兼容既有流程，具体口径由 `page_basis` 说明。
- `page_basis=original_pdf` 表示原始 PDF 物理页，`converted_pdf` 表示 Office 转换后 PDF 页，`logical_page` 表示显式换页形成的逻辑页。
- `document_pages` 是正文印刷页码。没有正文页码时为 `null`。
- 旧 JSON 没有 `page_basis` 时按 `original_pdf` 读取。

代码通过 `src.rule_schema.MatchedCase.from_json_file()` 读取并严格校验该结构。
