# QA 数据集构建流水线设计说明

## 1. 概述

本流水线以已解析完成的文档树（`tree.json`）为输入，通过多维度的 chunk 采样策略与 LLM 驱动的问答生成，自动化构建高质量的 QA 评测数据集。输出的每条样本包含完整的问题、答案、来源 chunk 信息，可直接用于 RAG 系统的召回率与答案质量评测。

```
tree.json
    │
    ▼
ChunkSampler（多维度采样）
    │  ├── 单 chunk 采样（按类型 / 难度 / 回答模式分层）
    │  └── 多 chunk 采样（树结构分组 + LLM 语义分组）
    │
    ▼
QAGenerator（LLM 问答生成）
    │  ├── 根据 chunk 类型选择专属 Prompt
    │  └── 并发批量调用 LLM，结构化输出校验
    │
    ▼
DatasetAssembler（数据集组装 & 比例校验）
    │
    ▼
qa_dataset.json（输出数据集）
```

---

## 2. 输入输出格式

### 输入：tree.json

tree.json 结构与关键字段：

```json
{
  "nodes": [
    {
      "index_id": 42,
      "parent_id": 10,
      "type": "NodeType.TEXT",          // 节点类型
      "meta_info": {
        "file_path": "/path/to/doc.pdf", // 文档路径（根节点持有）
        "page_idx": 5,                   // 所在页码（0-based）
        "content": "正文文本内容...",    // 文本内容
        "table_body": "<table>...</table>", // 表格 HTML（TABLE 节点）
        "img_path": "/path/to/img.jpg", // 图片路径（IMAGE 节点）
        "caption": "图2 电路示意图",    // 图片/表格标题
        "title_level": -1               // -1=非标题; 0/1/2=标题层级
      },
      "summary": "LLM 生成的节点摘要"
    }
  ]
}
```

### 输出：qa_dataset.json 样本格式

```json
{
  "question": "SOM-TL3588 的 eMMC 接口支持哪些速率模式？",
  "answer": "支持 HS200 和 HS400 两种高速模式，最高数据率为 400MB/s。",
  "chunk_ids": [42],                     // 单 chunk 时为列表，多 chunk 时含多个 ID
  "evidences": [
    {
      "chunk_id": 42,
      "chunk_type": "text",
      "page_idx": 5,
      "content": "eMMC 接口支持 HS200/HS400 模式..."
    }
  ],
  "doc_uuid": "som-001",                 // 对应 working_dir 中的文档 UUID
  "doc_path": "/path/to/doc.pdf",
  "question_type": "factual",            // factual / reasoning / numerical / structural
  "difficulty": "medium",               // easy / medium / hard
  "chunk_types": ["text"],              // text / table / image / title（去重后的列表）
  "is_multi_chunk": false,              // 是否为多 chunk 问题
  "grouping_method": "single"           // single / tree_sibling / tree_parent_child / llm_semantic
}
```

---

## 3. Chunk 分类体系

### 3.1 节点类型（chunk_type）

| 类型 | tree.json 中的 `type` 字段 | 内容来源 |
|------|--------------------------|---------|
| `text` | `NodeType.TEXT` | `meta_info.content` |
| `table` | `NodeType.TABLE` | `meta_info.table_body`（HTML）+ `meta_info.caption` |
| `image` | `NodeType.IMAGE` | `meta_info.img_path` + `meta_info.caption` + `summary` |
| `title` | `NodeType.TITLE` | `meta_info.content`（标题文本）+ `summary` |

### 3.2 问题类型（question_type）

| 类型 | 说明 | 典型例子 |
|------|------|---------|
| `factual` | 直接事实提取，答案明确在原文中 | "SOM-TL3588 的 CPU 主频是多少？" |
| `reasoning` | 需要推理、比较或综合多处信息 | "为什么说该板卡适合工业场景？" |
| `numerical` | 涉及数值、规格参数、计算 | "该电路图中共有多少个去耦电容？" |
| `structural` | 关于文档结构、章节组织 | "硬件说明书共分为几个主要章节？" |

### 3.3 难度级别（difficulty）

| 级别 | 判断依据 |
|------|---------|
| `easy` | 单 chunk、答案直接可读取，无需推理 |
| `medium` | 单 chunk 但需要理解/分析，或两个强关联 chunk |
| `hard` | 多 chunk（3 个以上）、跨章节推理、隐含信息提取 |

---

## 4. Chunk 采样策略

### 4.1 单 Chunk 采样

从树的所有叶节点（TEXT、TABLE、IMAGE）和部分标题节点（TITLE）中，按以下策略分层采样：

1. **过滤无效节点**：跳过 content 为空、长度 < 20 字符的节点，跳过 caption 和 content 均为空的 IMAGE 节点。
2. **按类型分桶**：将节点分入 `text_pool`、`table_pool`、`image_pool`、`title_pool`。
3. **按类型分配配额**（默认比例见第 6 节）：从每个桶中随机采样目标数量的节点。
4. **为每个节点指定问题类型和难度**：根据节点类型、内容长度、是否有数值等特征分配标签组合。

### 4.2 多 Chunk 采样——方法一：树结构分组

利用 tree.json 中的父子关系，构造语义相关的 chunk 组：

**兄弟节点组（Sibling Group）**：
- 同一父节点（TITLE）下的所有子节点（TEXT + TABLE + IMAGE）
- 天然形成一个"小节内容集合"，语义紧密
- 适合生成："SOM-TL3588 的 eMMC 接口在规格表和正文描述中分别列出了哪些速率参数？"

**父子节点组（Parent-Child Group）**：
- 一个 TITLE 节点 + 其直接子节点（TEXT 为主）
- 适合生成跨标题层级的综合问题

**跨章节相邻组（Cross-Section Adjacent）**：
- 相邻兄弟 TITLE 节点下各取 1-2 个代表性 TEXT 子节点
- 适合生成比较两个章节的问题

```
                    ROOT
                   /    \
              TITLE_A    TITLE_B     ← 相邻兄弟 TITLE
             /     \    /     \
         TEXT_1  TABLE_1  TEXT_2  IMAGE_1
            ↑                    ↑
            └──── 跨章节组 ──────┘
            (各取 1 个，来自不同 TITLE)

兄弟节点组：[TEXT_1, TABLE_1]           ← 同属 TITLE_A
父子节点组：[TITLE_A, TEXT_1, TABLE_1]   ← TITLE + 其子节点
跨章节组：  [TEXT_1, TEXT_2]             ← 分别来自 TITLE_A、TITLE_B
```

### 4.3 多 Chunk 采样——方法二：LLM 语义分组

当需要更高质量的跨章节多 chunk 组合时，调用 LLM 进行语义分组：

**步骤**：
1. 从 text pool 中随机批量取 30-50 个非重复节点，拼接其 `summary`（或前 100 字）。
2. 向 LLM 发送分组 Prompt（见第 5.4 节），要求 LLM 输出 JSON 格式的 chunk 分组：
   ```json
   [
     {"group": [12, 45, 78], "relation": "这三个chunk均描述了eMMC相关规格"},
     {"group": [23, 56],    "relation": "这两个chunk均涉及电源去耦设计"}
   ]
   ```
3. 保留关系描述合理、组内 chunk 数在 2-4 个的分组。
4. 每个合法分组作为一个多 chunk 采样结果。

> **选择建议**：默认优先使用树结构分组（速度快、关系可靠），对于需要跨章节问题的场景，可追加 LLM 语义分组模式（通过 `--grouping_method llm_semantic` 启用）。

---

## 5. Prompt 设计

> **核心约束（所有 Prompt 均适用）**：生成的问题必须是**独立自然的提问句**，就像用户直接向搜索系统提问一样。禁止出现"这段文本""这张表格""这张图""上述内容""文中提到""根据以上"等指代当前素材的表述。问题中应使用文档名称、章节名称、具体技术术语来定位上下文。
>
> | 错误示例 | 正确示例 |
> |---------|---------|
> | "这段文本中提到了哪些启动顺序？" | "SOM-TL3588 系统上电后，BootRom 会按照什么顺序检测启动介质？" |
> | "这张表格中列出的 eMMC 规格有哪些？" | "SOM-TL3588 核心板支持哪些容量规格的 eMMC？" |
> | "这张图展示了什么电路连接？" | "SOM-TL3588 的 MIPI CSI 接口是如何连接到主控芯片的？" |
> | "根据以上多个片段，电源方案有何特点？" | "SOM-TL3588 核心板采用了哪种电源管理方案，其供电拓扑和主要特点是什么？" |

### 5.1 单文本 Chunk QA 生成 Prompt

```
你是一名技术文档问答数据集标注专家，正在为 RAG 检索系统构建召回率测试集。

请根据以下文档片段，生成 1 个高质量的问答对。

要求：
- 问题类型：{question_type}
  （factual=直接事实提取；reasoning=推理/比较/分析；numerical=数值/参数/计算；structural=章节结构/文档组织）
- 难度级别：{difficulty}
  （easy=答案直接可读取；medium=需要理解分析；hard=需要深度推理或综合多处）
- 问题必须能够完全基于所给内容来回答，不得引入外部知识
- 答案需简洁准确，不超过 200 字
- 问题和答案均使用中文
- 【关键】问题必须是独立自然的提问句，禁止出现"这段文本""上述内容""文中""文档中提到"
  等指代当前素材的表述。
  错误示例："这段文本中提到了哪些启动顺序？"
  正确示例："SOM-TL3588 系统上电后，BootRom 会按照什么顺序检测启动介质？"

【文档片段】
所在文档：{doc_name}
所在章节：{section_path}
页码：第 {page_idx} 页
内容：
{content}

请严格以如下 JSON 格式输出（不要有任何多余文字）：
{"question": "...", "answer": "..."}
```

### 5.2 单表格 Chunk QA 生成 Prompt

```
你是一名技术文档问答数据集标注专家，正在为 RAG 检索系统构建召回率测试集。

请根据以下表格内容，生成 1 个高质量的问答对。

要求：
- 问题类型：{question_type}
  （factual=查询具体数值或参数；reasoning=比较或推断；numerical=数值计算或统计；structural=表格结构本身）
- 难度级别：{difficulty}
- 问题需利用表格中的具体数据（数值、参数名、对比关系）
- 答案需引用表格中的具体数字或参数
- 问题和答案均使用中文
- 【关键】问题必须是独立自然的提问句，禁止出现"这张表格""表中""上表""根据表格"
  等指代当前素材的表述。
  错误示例："这张表格中列出的 eMMC 容量规格有哪些？"
  正确示例："SOM-TL3588 核心板支持哪些容量规格的 eMMC？"

【表格信息】
所在文档：{doc_name}
页码：第 {page_idx} 页
表格标题：{caption}
表格内容（HTML）：
{table_body}

请严格以如下 JSON 格式输出（不要有任何多余文字）：
{"question": "...", "answer": "..."}
```

### 5.3 单图片 Chunk QA 生成 Prompt

```
你是一名技术文档问答数据集标注专家，正在为 RAG 检索系统构建召回率测试集。

请根据以下图片信息，生成 1 个高质量的问答对。
注意：仅依据提供的图片标题和摘要描述构建问题，不得凭空猜测图片的其他内容。

要求：
- 问题类型：{question_type}
  （factual=图片展示的具体内容；reasoning=图片含义或用途；numerical=图片中涉及的数值；structural=图片在文档中的作用）
- 难度级别：{difficulty}
- 如果图片摘要信息不足以支撑有效问题，可基于标题构造一个简单的 factual 问题
- 问题和答案均使用中文
- 【关键】问题必须是独立自然的提问句，禁止出现"这张图""图中""上图""该图片""根据图片"
  等指代当前素材的表述。
  错误示例："这张图中展示的是什么电路连接关系？"
  正确示例："SOM-TL3588 核心板的 MIPI CSI 摄像头接口引脚是如何连接到主控芯片的？"

【图片信息】
所在文档：{doc_name}
页码：第 {page_idx} 页
图片标题：{caption}
图片内容摘要（VLM 生成）：{summary}

请严格以如下 JSON 格式输出（不要有任何多余文字）：
{"question": "...", "answer": "..."}
```

### 5.4 单标题 Chunk QA 生成 Prompt

```
你是一名技术文档问答数据集标注专家，正在为 RAG 检索系统构建召回率测试集。

请根据以下章节标题及其摘要，生成 1 个关于文档结构或章节内容的问答对。

要求：
- 问题类型：structural（文档结构、章节组织、内容范围）
- 难度级别：{difficulty}
- 问题可以询问：该章节介绍了哪些内容、该章节的主要目的、该章节与其他章节的关系等
- 问题和答案均使用中文
- 【关键】问题必须是独立自然的提问句，禁止出现"这一章节""该章节""此节"等模糊指代，
  必须使用具体的章节名称或文档名称来定位。
  错误示例："这一章节主要介绍了哪些内容？"
  正确示例："{doc_name} 的「{title_text}」章节主要涵盖哪些技术内容？"

【章节信息】
所在文档：{doc_name}
页码：第 {page_idx} 页
标题层级：{title_level} 级标题
标题文本：{title_text}
章节摘要：{summary}

请严格以如下 JSON 格式输出（不要有任何多余文字）：
{"question": "...", "answer": "..."}
```

### 5.5 LLM 语义分组 Prompt

```
你是一名技术文档分析专家。以下是来自同一技术文档的若干文本片段，每段有编号（index_id）和内容摘要。

请识别出其中可以构成"多 chunk 综合问题"的组合，即：将这几个片段内容放在一起，
能够提出一个需要综合多处信息才能回答的合理技术问题。

要求：
- 每组包含 2-4 个片段（用 index_id 表示）
- 至少给出 {min_groups} 个分组，最多 {max_groups} 个
- 组内片段之间必须有明确的语义关联（相同主题、互补参数、因果关系、比较对比等）
- 简要说明每组的关联理由（一句话即可）
- 不同分组之间的 chunk 可以重叠，但同一分组内每个 chunk 只出现一次

【文档片段列表】
{chunk_summaries}

请严格以如下 JSON 数组格式输出（不要有任何多余文字）：
[
  {"group": [index_id1, index_id2], "relation": "关联说明"},
  {"group": [index_id3, index_id4, index_id5], "relation": "关联说明"}
]
```

### 5.6 多 Chunk 综合 QA 生成 Prompt

```
你是一名技术文档问答数据集标注专家，正在为 RAG 检索系统构建召回率测试集。

请根据以下多个相关文档片段，生成 1 个需要综合多处信息才能完整回答的问答对。

要求：
- 问题必须需要参考所有或大多数给定片段才能完整回答（而非只用其中一个）
- 问题类型：{question_type}
  （factual=综合多处事实；reasoning=跨片段推理/比较；numerical=跨片段数值汇总；structural=跨章节结构理解）
- 难度级别：{difficulty}（多 chunk 问题通常为 medium 或 hard）
- 答案需要清晰整合多个片段中的信息，不超过 300 字
- 问题和答案均使用中文
- 【关键】问题必须是独立自然的提问句，禁止出现"这些片段""上述内容""根据以上资料""文中提到"
  等指代当前素材的表述。
  错误示例："根据以上多个片段，SOM-TL3588 的电源管理方案有哪些特点？"
  正确示例："SOM-TL3588 核心板采用了哪种电源管理方案，其主要特点和供电拓扑是什么？"

【相关文档片段（共 {chunk_count} 个，来自第 {page_range} 页）】
{multi_chunk_content}

请严格以如下 JSON 格式输出（不要有任何多余文字）：
{"question": "...", "answer": "..."}
```

---

## 6. 采样比例配置

### 默认目标比例（可通过配置文件调整）

| 维度 | 分类 | 目标占比 |
|------|------|---------|
| **chunk 数量** | 单 chunk | 60% |
| | 多 chunk（2-4 个）| 40% |
| **chunk 类型** | text | 50% |
| | table | 25% |
| | image | 15% |
| | title（结构型）| 10% |
| **问题类型** | factual | 35% |
| | reasoning | 30% |
| | numerical | 20% |
| | structural | 15% |
| **难度** | easy | 30% |
| | medium | 40% |
| | hard | 30% |

> 当某类型 chunk 数量不足时，流水线会自动按实际比例重分配，并在日志中记录警告。

---

## 7. 运行方式

### 基本用法

```bash
# 从 tree.json 构建 QA 数据集（约 50 条）
python -m data_pipelines.build_qa_dataset \
  --tree_json /path/to/tree.json \
  --doc_uuid som-001 \
  --output /path/to/qa_dataset.json \
  --num_samples 50 \
  --llm_base_url http://localhost:8003/v1 \
  --llm_model Qwen/Qwen3-8B-AWQ

# 启用 LLM 语义分组（用于多 chunk 跨章节问题）
python -m data_pipelines.build_qa_dataset \
  --tree_json /path/to/tree.json \
  --doc_uuid som-001 \
  --output /path/to/qa_dataset.json \
  --num_samples 50 \
  --grouping_method llm_semantic \
  --llm_base_url http://localhost:8003/v1 \
  --llm_model Qwen/Qwen3-8B-AWQ

# 使用配置 YAML（推荐）
python -m data_pipelines.build_qa_dataset --config /path/to/pipeline_config.yaml
```

### 配置文件格式（pipeline_config.yaml）

```yaml
tree_json: /root/autodl-fs/bookrag/BookRAG/TL3588_data_and_output/somdata/output/som-001/tree.json
doc_uuid: som-001
output: /root/autodl-fs/bookrag/BookRAG/TL3588_data_and_output/somdata/qa_dataset.json
num_samples: 50
grouping_method: tree  # tree 或 llm_semantic

llm:
  model_name: Qwen/Qwen3-8B-AWQ
  api_base: http://localhost:8003/v1
  api_key: openai
  temperature: 0.7
  max_tokens: 1024
  max_workers: 4

ratio:
  single_chunk: 0.6
  multi_chunk: 0.4
  type:
    text: 0.50
    table: 0.25
    image: 0.15
    title: 0.10
  question_type:
    factual: 0.35
    reasoning: 0.30
    numerical: 0.20
    structural: 0.15
  difficulty:
    easy: 0.30
    medium: 0.40
    hard: 0.30
```

---

## 8. 模块文件结构

```
data_pipelines/
├── __init__.py
├── build_qa_dataset.py      # 主流水线入口（CLI & 函数接口）
├── chunk_sampler.py         # Chunk 采样（单 chunk & 多 chunk）
├── qa_generator.py          # LLM 问答生成 & 结果校验
└── prompts.py               # 所有 Prompt 模板定义
```

---

## 9. 质量控制

1. **生成后校验**：检查 LLM 输出是否为合法 JSON，question 和 answer 字段非空，答案长度合理（> 10 字）。
2. **重试机制**：单条生成失败时最多重试 2 次，仍失败则跳过并记录日志。
3. **去重**：对最终数据集中的 question 文本做相似度去重（基于 Jaccard 相似度），过滤重复问题。
4. **比例验证**：生成完成后打印各维度的实际分布，与目标比例对比，偏差超过 10% 时发出警告。
