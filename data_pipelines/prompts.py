"""
QA 数据集构建流水线 —— Prompt 模板模块

所有与 LLM 交互的 Prompt 均定义在此文件中，便于集中管理和版本维护。
"""

from string import Template


# ──────────────────────────────────────────────
# 单 chunk：文本节点
# ──────────────────────────────────────────────

SINGLE_TEXT_QA_PROMPT = Template("""你是一名技术文档问答数据集标注专家，正在为 RAG 检索系统构建召回率测试集。

请根据以下文档片段，生成 1 个高质量的问答对。

要求：
- 问题类型：$question_type
  （factual=直接事实提取；reasoning=推理/比较/分析；numerical=数值/参数/计算；structural=章节结构/文档组织）
- 难度级别：$difficulty
  （easy=答案直接可读取；medium=需要理解分析；hard=需要深度推理或综合多处）
- 问题必须能够完全基于所给内容来回答，不得引入外部知识
- 答案需简洁准确，不超过 200 字
- 问题和答案均使用中文
- 【关键】问题必须是独立自然的提问句，就像用户直接向搜索系统提问一样，
  禁止出现"这段文本""上述内容""文中""文档中提到""根据以上"等指代当前素材的表述。
  错误示例："这段文本中提到了哪些启动顺序？"
  正确示例："SOM-TL3588 系统上电后，BootRom 会按照什么顺序检测启动介质？"

【文档片段】
所在文档：$doc_name
所在章节：$section_path
页码：第 $page_idx 页
内容：
$content

请严格以如下 JSON 格式输出（不要有任何多余文字）：
{"question": "...", "answer": "..."}""")


# ──────────────────────────────────────────────
# 单 chunk：表格节点
# ──────────────────────────────────────────────

SINGLE_TABLE_QA_PROMPT = Template("""你是一名技术文档问答数据集标注专家，正在为 RAG 检索系统构建召回率测试集。

请根据以下表格内容，生成 1 个高质量的问答对。

要求：
- 问题类型：$question_type
  （factual=查询具体数值或参数；reasoning=比较或推断；numerical=数值计算或统计；structural=表格结构本身）
- 难度级别：$difficulty
- 问题需利用表格中的具体数据（数值、参数名、对比关系）
- 答案需引用表格中的具体数字或参数
- 问题和答案均使用中文
- 【关键】问题必须是独立自然的提问句，就像用户直接向搜索系统提问一样，
  禁止出现"这张表格""表中""上表""根据表格"等指代当前素材的表述。
  错误示例："这张表格中列出的 eMMC 容量规格有哪些？"
  正确示例："SOM-TL3588 核心板支持哪些容量规格的 eMMC？"

【表格信息】
所在文档：$doc_name
页码：第 $page_idx 页
表格标题：$caption
表格内容（HTML）：
$table_body

请严格以如下 JSON 格式输出（不要有任何多余文字）：
{"question": "...", "answer": "..."}""")


# ──────────────────────────────────────────────
# 单 chunk：图片节点
# ──────────────────────────────────────────────

SINGLE_IMAGE_QA_PROMPT = Template("""你是一名技术文档问答数据集标注专家，正在为 RAG 检索系统构建召回率测试集。

请根据以下图片信息，生成 1 个高质量的问答对。
注意：仅依据提供的图片标题和摘要描述构建问题，不得凭空猜测图片的其他内容。

要求：
- 问题类型：$question_type
  （factual=图片展示的具体内容；reasoning=图片所表达的含义或用途；numerical=图片中涉及的数值；structural=图片在文档中的作用）
- 难度级别：$difficulty
- 如果图片摘要信息不足以支撑有效问题，可以基于标题构造一个简单的 factual 问题
- 问题和答案均使用中文
- 【关键】问题必须是独立自然的提问句，就像用户直接向搜索系统提问一样，
  禁止出现"这张图""图中""上图""该图片""根据图片"等指代当前素材的表述。
  错误示例："这张图中展示的是什么电路连接关系？"
  正确示例："SOM-TL3588 核心板的 MIPI CSI 摄像头接口引脚是如何连接到主控芯片的？"

【图片信息】
所在文档：$doc_name
页码：第 $page_idx 页
图片标题：$caption
图片内容摘要（VLM 生成）：$summary

请严格以如下 JSON 格式输出（不要有任何多余文字）：
{"question": "...", "answer": "..."}""")


# ──────────────────────────────────────────────
# 单 chunk：标题节点（结构型问题）
# ──────────────────────────────────────────────

SINGLE_TITLE_QA_PROMPT = Template("""你是一名技术文档问答数据集标注专家，正在为 RAG 检索系统构建召回率测试集。

请根据以下章节标题及其摘要，生成 1 个关于文档结构或章节内容的问答对。

要求：
- 问题类型：structural（文档结构、章节组织、内容范围）
- 难度级别：$difficulty
- 问题可以询问：该章节介绍了哪些内容、该章节的主要目的、该章节与其他章节的关系等
- 问题和答案均使用中文
- 【关键】问题必须是独立自然的提问句，就像用户直接向搜索系统提问一样，
  禁止出现"这一章节""该章节""此节""上述章节"等模糊指代表述，
  必须用具体的章节名称或文档名称来提问。
  错误示例："这一章节主要介绍了哪些内容？"
  正确示例："$doc_name 的「$title_text」章节主要涵盖哪些技术内容？"

【章节信息】
所在文档：$doc_name
页码：第 $page_idx 页
标题层级：$title_level 级标题
标题文本：$title_text
章节摘要：$summary

请严格以如下 JSON 格式输出（不要有任何多余文字）：
{"question": "...", "answer": "..."}""")


# ──────────────────────────────────────────────
# 多 chunk：综合 QA 生成
# ──────────────────────────────────────────────

MULTI_CHUNK_QA_PROMPT = Template("""你是一名技术文档问答数据集标注专家，正在为 RAG 检索系统构建召回率测试集。

请根据以下多个相关文档片段，生成 1 个需要综合多处信息才能完整回答的问答对。

要求：
- 问题必须需要参考所有或大多数给定片段才能完整回答（而非只用其中一个）
- 问题类型：$question_type
  （factual=综合多处事实；reasoning=跨片段推理/比较；numerical=跨片段数值汇总；structural=跨章节结构理解）
- 难度级别：$difficulty（多 chunk 问题通常为 medium 或 hard）
- 答案需要清晰整合多个片段中的信息，不超过 300 字
- 问题和答案均使用中文
- 【关键】问题必须是独立自然的提问句，就像用户直接向搜索系统提问一样，
  禁止出现"这些片段""上述内容""根据以上资料""文中提到"等指代当前素材的表述。
  错误示例："根据以上多个片段，SOM-TL3588 的电源管理方案有哪些特点？"
  正确示例："SOM-TL3588 核心板采用了哪种电源管理方案，其主要特点和供电拓扑是什么？"

【相关文档片段（共 $chunk_count 个，来自第 $page_range 页）】
$multi_chunk_content

请严格以如下 JSON 格式输出（不要有任何多余文字）：
{"question": "...", "answer": "..."}""")


# ──────────────────────────────────────────────
# LLM 语义分组 Prompt
# ──────────────────────────────────────────────

LLM_SEMANTIC_GROUPING_PROMPT = Template("""你是一名技术文档分析专家。以下是来自同一技术文档的若干文本片段，每段有编号（index_id）和内容摘要。

请识别出其中可以构成"多 chunk 综合问题"的组合，即：将这几个片段内容放在一起，能够提出一个需要综合多处信息才能回答的合理技术问题。

要求：
- 每组包含 2-4 个片段（用 index_id 表示）
- 至少给出 $min_groups 个分组，最多 $max_groups 个
- 组内片段之间必须有明确的语义关联（相同主题、互补参数、因果关系、比较对比等）
- 简要说明每组的关联理由（一句话即可）
- 不同分组之间的 chunk 可以重叠，但同一分组内每个 chunk 只出现一次

【文档片段列表】
$chunk_summaries

请严格以如下 JSON 数组格式输出（不要有任何多余文字）：
[
  {"group": [index_id1, index_id2], "relation": "关联说明"},
  {"group": [index_id3, index_id4, index_id5], "relation": "关联说明"}
]""")


# ──────────────────────────────────────────────
# 辅助函数：格式化多 chunk 内容
# ──────────────────────────────────────────────

def format_chunk_for_prompt(node: dict, idx: int) -> str:
    """将单个 chunk 节点格式化为 Prompt 中的片段文本。"""
    meta = node.get("meta_info", {})
    page = meta.get("page_idx", "?")
    if page is not None:
        page = int(page) + 1  # 转为 1-based 页码

    chunk_type = node.get("type", "")
    lines = [f"【片段 {idx + 1}（index_id={node['index_id']}，第 {page} 页）】"]

    if "NodeType.TABLE" in chunk_type:
        caption = meta.get("caption") or ""
        table_body = meta.get("table_body") or ""
        if caption:
            lines.append(f"表格标题：{caption}")
        lines.append(f"表格内容：{table_body[:800]}")
    elif "NodeType.IMAGE" in chunk_type:
        caption = meta.get("caption") or ""
        summary = node.get("summary") or ""
        if caption:
            lines.append(f"图片标题：{caption}")
        if summary:
            lines.append(f"图片摘要：{summary[:400]}")
    elif "NodeType.TITLE" in chunk_type:
        content = meta.get("content") or ""
        summary = node.get("summary") or ""
        lines.append(f"章节标题：{content}")
        if summary:
            lines.append(f"章节摘要：{summary[:400]}")
    else:
        content = meta.get("content") or ""
        lines.append(f"内容：{content[:800]}")

    return "\n".join(lines)


def format_chunk_summary_for_grouping(node: dict) -> str:
    """将节点格式化为 LLM 分组 Prompt 中的摘要条目。"""
    meta = node.get("meta_info", {})
    page = meta.get("page_idx", "?")
    if page is not None:
        page = int(page) + 1

    chunk_type = node.get("type", "")
    summary = node.get("summary") or ""
    content = meta.get("content") or meta.get("caption") or ""

    type_label = "文本"
    if "TABLE" in chunk_type:
        type_label = "表格"
    elif "IMAGE" in chunk_type:
        type_label = "图片"
    elif "TITLE" in chunk_type:
        type_label = "标题"

    short_text = (summary or content)[:120].replace("\n", " ")
    return f"- index_id={node['index_id']}（第 {page} 页，{type_label}）：{short_text}"
