# `rules_matched.json` 输入契约

步骤二输出示例：

```json
{
  "case_id": "report_5",
  "source": {
    "file": "招标文件2.pdf"
  },
  "rules": [
    {
      "rule_id": 20,
      "rule_raw": "投标保证金不得超过招标项目估算价的2%",
      "rule_text": "【描述】……【法规依据】……【公式】……",
      "check_method": "结构化数据检查",
      "structured_fields": "投标保证金金额字段、项目估算价字段",
      "evidence": [
        {
          "location": {
            "file": "招标文件2.pdf",
            "section": "投标人须知—投标保证金",
            "pdf_pages": {"start": 20, "end": 21},
            "document_pages": {"start": 12, "end": 13},
            "page_basis": "original_pdf"
          },
          "text": "……"
        }
      ]
    }
  ]
}
```

约定：

- `case_id` 由程序根据 `reports/report_x/` 自动生成。
- `source` 只包含 `file`。
- `rule_id` 是正整数，对应规则表“序号”。
- `rule_raw` 对应“重点排查情形”，决定审查主题。
- `rule_text` 对应混合的生成内容；只解析其中明确的 `【法规依据】` 作为补充参考，公式、开发说明和其他生成块不参与召回或判定。
- `check_method` 对应“检查方式”，用于执行器路由。
- `structured_fields` 对应“结构化数据展示字段”，允许空字符串，属于字段映射提示。
- `evidence` 固定为数组；未匹配时为空数组。
- `pdf_pages` 保留旧字段名，具体页码口径由 `page_basis` 区分。
- `document_pages` 没有可靠正文印刷页码时为 `null`。

兼容性：

- 旧 JSON 没有 `check_method` 时默认 `大模型分析`。
- 旧 JSON 没有 `structured_fields` 时默认空字符串。
- 旧 JSON 没有 `page_basis` 时默认 `original_pdf`。

`MatchedCase.from_json_file()` 负责读取和校验。
