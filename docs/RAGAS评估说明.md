# RAGAS 评估说明（真实评测，可复现）

本项目的评测数字由**真实 RAGAS 库**在隔离环境中跑出，不做任何人工修数。本文说明指标口径、如何复现，以及如何解读报告。

## 指标口径

| 指标 | 类型 | 含义 | 依赖 |
| --- | --- | --- | --- |
| `faithfulness` | LLM-only | 回答是否忠于检索到的上下文（幻觉越低越高） | 判分 LLM |
| `answer_relevancy` | 向量+LLM | 回答与用户问题的相关性 | 判分 LLM + 向量模型 |
| `context_recall` | 向量+LLM | 检索到的上下文对标准答案的覆盖度 | 判分 LLM + 向量模型 |
| `context_precision` | 向量+LLM | 检索结果中相关信息排在前面的程度 | 判分 LLM + 向量模型 |
| `hit@k` | 无模型 | 期望来源文档是否出现在检索 Top-k 中 | 仅检索 |

- **判分模型（judge）**：DeepSeek `deepseek-chat`（`backend/.env` 的 `DEEPSEEK_API_KEY`），temperature=0。
- **向量模型（embedder，可选）**：SiliconFlow `BAAI/bge-m3`。未配置 `EMBEDDING_API_KEY` 时，`answer_relevancy` / `context_recall` / `context_precision` 无法计算，只输出 `faithfulness` + `hit@k` + 延迟，并在报告注明。
- **评估数据**：`scripts/eval_golden.json` 手写 **64 条**跨品类 golden（9 个 demo 文档：8 电商品类 + 1 代码文档），每条含 `question`、`ground_truth`（模型答案级参考答案）、`expected_docs`（期望命中来源）。
- **通过率（pass rate）**：以 `faithfulness >= 0.8` 视为该 case 通过（默认口径，同时列出 ≥0.7 / ≥0.9 供参照），报告自动计算。

## 复现步骤

```bash
# 0. 前置：本地 Qdrant 已启动且 demo_data 已导入（9 个文档）
cd backend
.venv/Scripts/python.exe ../scripts/seed_kb.py        # 首次导入 / 重灌
.venv/Scripts/python.exe ../scripts/reindex_kb.py      # 分块策略升级后重建索引

# 1. 生成评估数据集（检索 + DeepSeek 生成答案，64 条）
.venv/Scripts/python.exe ../scripts/gen_eval_data.py

# 2. 运行 RAGAS 评测（首次自动创建隔离 .venv-eval 并安装固定版本依赖）
.venv/Scripts/python.exe ../scripts/eval_ragas.py

# 3. 报告输出
#    scripts/eval_output/eval_dataset.json   评估数据集（含每条 answer）
#    scripts/eval_output/ragas_report_*.md   评测报告（含通过率）

# 4. 接口压测（可选；需先按 scripts/load_test.py 注释起压测后端）
#    .venv/Scripts/python.exe ../scripts/load_test.py --base http://127.0.0.1:8001
#    -> scripts/eval_output/load_test_report_*.md（缓存命中 / 冷路径 QPS 与延迟分位）
```

## 为什么用隔离 `.venv-eval`

应用后端使用 LangChain 1.3，而 ragas 0.2.x 依赖 `langchain-core 0.3.x`，同环境必然依赖冲突。`eval_ragas.py` 自举：先用应用 venv 创建 `.venv-eval` 并安装固定版本（`ragas>=0.2.10,<0.3`、`langchain-core==0.3.*`、`langchain-openai==0.2.*`、`datasets`），再用 `.venv-eval` 的 python 重新执行自身完成评测。可用 `--skip-install` 复用已有环境。

## 降级链

| 场景 | 表现 |
| --- | --- |
| ragas 安装失败 / import 失败 | 报告只含 hit@k + 抽样回答，标注「ragas 不可用」 |
| 未配置 embedding API Key | 只跑 LLM-only 的 `faithfulness`，其余标注「需向量模型」 |
| 单条判分失败 | 该条该指标为 `—`（NaN），其余正常 |

## 如何解读报告

- `faithfulness` 接近 1 说明回答没有脱离检索上下文编造（幻觉控制好）。
- **通过率**：按指定阈值统计通过的 case 占比；阈值越低通过率越高，跨项目对比需标注同一口径。
- `hit@k` 反映**检索召回**是否把正确文档捞进 Top-k —— 这是 RAG 的根基，检索漏了生成再准也没用。
- 平均单条延迟 = 检索 + 生成全链路耗时；真实部署下语义缓存命中（余弦 >0.93）会显著更低（压测实测缓存命中 P50 64ms）。
