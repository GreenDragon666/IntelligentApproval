# 招标文件智能合规审批

本项目消费步骤一、二生成的 `rules_matched.json`，使用服务器本地 Code-Agent
生成可复用的 Python checker，对匹配原文执行确定性校验，并输出案件级审批报告。

## 1. 技术框架

整套系统由四部分组成：

| 层次 | 使用的框架/组件 | 职责 |
|---|---|---|
| 模型服务 | vLLM | 在服务器加载 Qwen2.5-Coder，并提供 OpenAI 兼容的本地 HTTP 接口 |
| 模型客户端 | OpenAI Python SDK | 只连接本机 vLLM，例如 `http://127.0.0.1:8000/v1`，不调用外部 API |
| Code-Agent 编排 | LangGraph | 组织“生成代码 → 验证 → 失败反馈 → 重试 → 保存”状态图 |
| 确定性运行时 | Python 子进程 | 执行已生成 checker，限制执行时间并校验返回契约和证据引用 |

默认模型为 `Qwen2.5-Coder-3B-Instruct`，资源充足时可切换到
`Qwen2.5-Coder-14B-Instruct`。

```text
                         ┌──────────────────────────────┐
rules_matched.json ─────→│ 规则哈希与 checker 缓存查找 │
                         └──────────────┬───────────────┘
                                        │
                    ┌───────────────────┴───────────────────┐
                    │                                       │
              已有 checker                            缺少 checker
                    │                                       │
                    │                         LangGraph + 本地 Qwen 生成
                    │                                       │
                    └───────────────────┬───────────────────┘
                                        ↓
                               子进程验证并执行
                                        ↓
                           可选 LLM 复核与定向重生成
                                        ↓
                            summary.json + summary.md
```

## 2. 正式输入

输入格式见 [docs/MATCHED_JSON.md](docs/MATCHED_JSON.md)。案件目录建议为：

```text
reports/
  report_2/
    招标文件2.pdf
    matched/
      rules_matched.json
    results/
      summary.json
      summary.md
```

checker 生成提示词只包含 `rule_id`、`rule_raw` 和 `rule_text`，不包含某个案件的
原文。案件原文只在执行时通过 `evidence` 传入，因此相同规则的 checker 可以跨案件复用。

## 3. Checker 如何命名和定位

系统对规范化后的 `rule_text` 计算 SHA-256，再和整数 `rule_id` 组合：

```text
rule_<rule_id>_<规则哈希前12位>
```

例如：

```text
rule_2_ca58dcf50a00
```

对应文件：

```text
generated_checkers/
  rule_2_ca58dcf50a00.py      # checker 代码
  rule_2_ca58dcf50a00.json    # 模型、完整哈希、生成时间、生成尝试次数
```

每条报告记录都会包含：

```json
{
  "rule_id": 2,
  "checker_key": "rule_2_ca58dcf50a00",
  "checker_reused": true,
  "generation_attempts": 0,
  "result": {},
  "review": null,
  "error": ""
}
```

因此出现问题时：

1. 用 `rule_id` 定位案件 JSON 中的规则；
2. 用 `checker_key` 定位 `generated_checkers/` 中实际执行的代码和元数据；
3. 用 `error` 查看代码生成或执行错误；
4. 用 `review.feedback` 查看 LLM 复核不通过的原因。

列出报告中的失败规则：

```bash
python -c '
import json
data = json.load(open("reports/report_2/results/summary.json", encoding="utf-8"))
for item in data["rules"]:
    if item["error"]:
        print(item["rule_id"], item["checker_key"], item["error"])
'
```

查看指定 checker：

```bash
ls -l generated_checkers/rule_2_ca58dcf50a00.*
sed -n '1,240p' generated_checkers/rule_2_ca58dcf50a00.py
```

## 4. 某条规则出错后的处理

### 4.1 自动处理：代码执行异常

正常运行时，如果 checker 在真实 evidence 上出现异常，系统会：

```text
捕获当前规则的执行错误
  → 将“旧代码 + 错误信息 + 原规则”反馈给本地模型
  → 只重新生成当前 rule_id 的 checker
  → 再次验证并执行
  → 其他规则不受影响
```

该路径默认启用，不需要额外参数。每次代码生成内部最多尝试
`CODEGEN_MAX_RETRIES` 次，默认是 3 次。

### 4.2 自动处理：LLM 复核不通过

使用 `--review` 时，checker 执行后会由同一个本地模型复核“规则、证据、执行结果”是否一致：

```bash
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --review
```

如果复核返回 `approved=false`：

```text
review.feedback
  → 作为额外修改要求反馈给 Code-Agent
  → 覆盖式重新生成当前规则的 checker
  → 再执行
  → 再复核
```

复核反馈迭代次数由 `REVIEW_MAX_RETRIES` 控制，默认 1 次。

### 4.3 手工定位并重新生成单条规则

如果人工检查报告后认为第 2 条规则有问题：

```bash
python gen_checker.py \
  --input reports/report_2/matched/rules_matched.json \
  --rule-id 2 \
  --feedback "未正确区分有量化说明和无量化说明的合理表述，请修正上下文判断" \
  --force
```

其中：

- `--rule-id 2`：精确选择规则；
- `--feedback`：把人工发现的问题传给代码模型；
- `--force`：即使当前哈希已有 checker，也重新生成并覆盖。

生成后只复跑该规则：

```bash
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --rules 2 \
  --no-generate
```

如果还要做 LLM 复核：

```bash
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --rules 2 \
  --review
```

确认单条规则正常后，再运行全案：

```bash
python main.py --input reports/report_2/matched/rules_matched.json
```

### 4.4 直接在完整入口强制重新生成

不需要人工反馈时，可以用完整入口忽略缓存并重新生成指定规则：

```bash
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --rules 2 \
  --force-regenerate
```

### 4.5 “重新生成”和“恢复上一版”的区别

当前实现支持的是：

- 出错后重新生成；
- 复核失败后携带反馈重新生成；
- 人工指定规则强制重新生成。

当前保存方式是覆盖同一个 `checker_key` 的 `.py` 和 `.json` 文件，尚未内置 checker
历史版本目录。因此它不是严格意义上的“恢复上一版代码”。如果需要恢复旧版本，目前应通过
Git、服务器文件快照或手工备份恢复。后续可以增加：

```text
generated_checkers/history/<checker_key>/<timestamp>/
```

并提供显式的 `list-versions` 和 `rollback` 命令。在实现历史版本前，不应把“重新生成”描述为
“版本回滚”。

## 5. 服务器首次部署

以下路径按照当前服务器约定编写：

```text
Conda 环境：/home/zyl/miniconda3/envs/approval
3B 模型：/home/zyl/public/LLM Library/Qwen2.5-Coder-3B-Instruct
14B 模型：/home/zyl/public/LLM Library/Qwen2.5-Coder-14B-Instruct
```

### 5.1 进入环境

```bash
source /home/zyl/miniconda3/etc/profile.d/conda.sh
conda activate approval
cd /home/zyl/private/Coding/IntelligentApproval
```

如果服务器上的项目目录不同，以实际目录为准。

### 5.2 安装项目依赖

```bash
pip install -r requirements.txt
```

确认 vLLM 已安装：

```bash
vllm --version
```

如果没有安装，需要根据服务器 CUDA/PyTorch 环境安装：

```bash
pip install vllm
```

vLLM 体积较大，并且与 CUDA/PyTorch 版本相关，生产服务器上应固定经过验证的依赖版本。

### 5.3 检查模型目录

```bash
ls -ld "/home/zyl/public/LLM Library/Qwen2.5-Coder-3B-Instruct"
ls -ld "/home/zyl/public/LLM Library/Qwen2.5-Coder-14B-Instruct"
```

## 6. 启动本地模型服务

模型服务必须由用户手动启动，审批程序不会自动启动 vLLM。

### 6.1 启动 3B 模型

如果审批程序和模型在同一台服务器，建议只监听本机地址：

```bash
export LOCAL_LLM_HOST=127.0.0.1
export LOCAL_LLM_PORT=8000
export LOCAL_LLM_MODEL=Qwen2.5-Coder-3B-Instruct
export LOCAL_LLM_MODEL_PATH="/home/zyl/public/LLM Library/Qwen2.5-Coder-3B-Instruct"

bash scripts/serve_llm_3b.sh
```

脚本内部执行的是：

```text
vllm serve <模型路径>
  --served-model-name Qwen2.5-Coder-3B-Instruct
  --host 127.0.0.1
  --port 8000
  --max-model-len 4096
  --gpu-memory-utilization 0.85
```

如果需要更长上下文，例如启用包含较长 evidence 的 `--review`：

```bash
export LOCAL_LLM_MAX_MODEL_LEN=8192
bash scripts/serve_llm_3b.sh
```

上下文越长，显存占用越高，应根据服务器实际显存调整。

### 6.2 启动 14B 模型

```bash
export LOCAL_LLM_HOST=127.0.0.1
export LOCAL_LLM_PORT=8000
export LOCAL_LLM_MODEL=Qwen2.5-Coder-14B-Instruct
export LOCAL_LLM_MODEL_PATH="/home/zyl/public/LLM Library/Qwen2.5-Coder-14B-Instruct"

bash scripts/serve_llm_14b.sh
```

多 GPU 时，可把 vLLM 参数直接追加给脚本：

```bash
bash scripts/serve_llm_14b.sh --tensor-parallel-size 2
```

### 6.3 使用 tmux 保持服务运行

```bash
tmux new -s approval-llm
source /home/zyl/miniconda3/etc/profile.d/conda.sh
conda activate approval
cd /home/zyl/private/Coding/IntelligentApproval
bash scripts/serve_llm_3b.sh
```

按 `Ctrl+b`，再按 `d`，可以退出 tmux 而不停止服务。重新进入：

```bash
tmux attach -t approval-llm
```

停止服务时，在模型终端按 `Ctrl+C`。

## 7. 验证模型服务

另开一个服务器终端，激活相同环境并进入项目目录。

### 7.1 检查 OpenAI 兼容接口

```bash
curl http://127.0.0.1:8000/v1/models
```

返回内容中应出现：

```text
Qwen2.5-Coder-3B-Instruct
```

### 7.2 使用项目客户端检查

```bash
export LOCAL_LLM_BASE_URL=http://127.0.0.1:8000/v1
export LOCAL_LLM_MODEL=Qwen2.5-Coder-3B-Instruct

python -c "from src.llm import healthcheck; print(healthcheck())"
```

`ok` 应为 `True`。特别注意：

- vLLM 的 `--served-model-name`；
- 客户端的 `LOCAL_LLM_MODEL`；

两者必须一致。

如果模型服务使用其他端口，例如 8001：

```bash
export LOCAL_LLM_PORT=8001
# 模型服务终端使用上面的 PORT 启动

export LOCAL_LLM_BASE_URL=http://127.0.0.1:8001/v1
# 审批程序终端使用上面的 BASE_URL
```

## 8. 推荐的首次跑通顺序

不要第一次就直接生成全部 41 条。建议按以下顺序排查环境和模型质量。

### 第一步：校验正式 JSON，不调用模型

```bash
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --rules 2 \
  --no-generate
```

首次没有 checker 时，规则 2 显示 `error` 是预期结果；这一步只是确认 JSON 和案件入口正常。

### 第二步：生成一条 checker

```bash
python gen_checker.py \
  --input reports/report_2/matched/rules_matched.json \
  --rule-id 2
```

成功后应出现：

```text
generated_checkers/rule_2_<hash>.py
generated_checkers/rule_2_<hash>.json
```

### 第三步：不调用模型，执行已缓存 checker

```bash
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --rules 2 \
  --no-generate
```

这一步证明 checker 已经可以独立运行。

### 第四步：执行并启用 LLM 复核

```bash
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --rules 2 \
  --review
```

检查：

- `results/summary.json` 中的 `result`；
- `review.approved`；
- `review.feedback`；
- `generation_attempts`；
- `error`。

### 第五步：小批量规则

```bash
python main.py \
  --input reports/report_2/matched/rules_matched.json \
  --rules 2 3 4 5
```

### 第六步：完整案件

```bash
python main.py --input reports/report_2/matched/rules_matched.json
```

### 第七步：稳定运行时不启用模型生成

checker 经过验证并缓存后，可以在审批运行阶段执行：

```bash
python main.py \
  --input reports/report_3/matched/rules_matched.json \
  --no-generate
```

只要 report_3 的规则文本和已缓存版本相同，就会直接复用 checker。缺少 checker 的规则会明确
记录为 `error`，不会悄悄跳过。

## 9. 参数说明

### `main.py`

| 参数 | 含义 |
|---|---|
| `--input` | 必填，案件 `rules_matched.json` |
| `--rules 2 4 6` | 只运行指定整数规则序号 |
| `--out` | 自定义报告目录；默认是案件目录下 `results/` |
| `--no-generate` | 缺少 checker 时不调用模型生成 |
| `--force-regenerate` | 忽略已有缓存并重新生成 |
| `--review` | 使用本地 LLM 复核并反馈迭代 |
| `--checker-dir` | 自定义全局 checker 缓存目录 |

注意：`--no-generate` 只禁止代码生成。如果同时显式传入 `--review`，复核仍需要模型。严格无模型运行时
不要传 `--review`。

### 环境变量

| 环境变量 | 默认值 | 含义 |
|---|---|---|
| `LOCAL_LLM_BASE_URL` | `http://localhost:8000/v1` | 审批程序连接的 vLLM 地址 |
| `LOCAL_LLM_MODEL` | `Qwen2.5-Coder-3B-Instruct` | 客户端请求使用的 served model name |
| `LOCAL_LLM_MODEL_PATH` | 3B 模型目录 | vLLM 加载的权重目录 |
| `LOCAL_LLM_HOST` | `0.0.0.0` | vLLM 监听地址；同机部署建议设为 `127.0.0.1` |
| `LOCAL_LLM_PORT` | `8000` | vLLM 端口 |
| `LOCAL_LLM_MAX_MODEL_LEN` | `4096` | vLLM 最大上下文长度 |
| `LOCAL_LLM_GPU_MEM_UTIL` | 3B 为 `0.85` | vLLM 可使用的 GPU 显存比例 |
| `CODEGEN_MAX_RETRIES` | `3` | 单次 checker 生成内部最大尝试次数 |
| `REVIEW_MAX_RETRIES` | `1` | LLM 复核失败后的重生成次数 |
| `REVIEW_MAX_EVIDENCE_CHARS` | `20000` | 复核提示词最多携带的 evidence 字符数 |
| `CHECKER_TIMEOUT` | `30` | 单个 checker 最长执行秒数 |
| `GENERATED_DIR` | `generated_checkers` | 全局 checker 缓存目录 |

如果模型上下文只有 4096，启用 `--review` 时建议适当降低 `REVIEW_MAX_EVIDENCE_CHARS`，例如：

```bash
export REVIEW_MAX_EVIDENCE_CHARS=3000
```

或者提高 vLLM 的 `LOCAL_LLM_MAX_MODEL_LEN`，但要同步评估显存占用。

## 10. 无模型环境的准确含义

```bash
python main.py --input <rules_matched.json> --no-generate
```

执行逻辑为：

```text
读取并校验 JSON
  → evidence 为空：insufficient_input
  → evidence 非空：计算 checker_key
      ├── 缓存存在：直接执行 checker
      └── 缓存不存在：记录 error
  → 汇总报告
```

所以无模型环境不是“跳过审批”，而是“只能运行已生成的确定性 checker”。第一次运行、缓存为空时，
有 evidence 的规则出现 `error` 是正常现象；先在服务器生成并验证 checker 后，后续才可以不启动模型运行。

## 11. 测试

```bash
python -m unittest discover -s tests -v
```

当前测试使用真实的 `report_2` JSON，不包含手写业务 checker 或模拟审批数据。

## 12. 安全边界

- 不调用外部 API，OpenAI SDK 只连接服务器本机 vLLM。
- 生成代码禁止网络、文件读写、子进程和动态执行，并在执行前进行 AST 检查。
- checker 在独立临时目录的限时子进程中执行。
- 当前进程隔离不等于完整安全沙箱；正式生产应进一步使用禁网、只读文件系统、资源限额和非特权用户容器。
