import re
import os
import logging
from markdown_it import MarkdownIt
from typing import List, Dict, Optional, Tuple

log = logging.getLogger(__name__)


def parse_markdown_file(md_path: str, base_img_dir: Optional[str] = None) -> Tuple[List[Dict], List[Dict]]:
    """
    解析 MD 文件，返回 (content_list, title_outline)，格式和 PDF 的一致
    
    content_list: [
        {"type": "title", "text": "...", "text_level": 1, "pdf_id": 0, ...},
        {"type": "text", "text": "...", "pdf_id": 1, ...},
        {"type": "table", "text": "...", "table_caption": [], "table_footnote": [], "pdf_id": 2, ...},
        {"type": "image", "img_path": "...", "image_caption": "...", "pdf_id": 3, ...},
    ]
    
    title_outline: [
        {"text": "...", "text_level": 1, "pdf_id": 0, "parent_id": null, "end_id": 5},
        {"text": "...", "text_level": 2, "pdf_id": 1, "parent_id": 0, "end_id": 3},
    ]
    """
    
    log.info(f"Parsing markdown file: {md_path}")
    
    # 1. 读 MD 文件
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()
    
    # 2. 用 markdown-it-py 解析
    md = MarkdownIt('commonmark').enable('table')
    tokens = md.parse(md_text)
    
    # 3. 遍历 tokens，生成「块序列」
    content_list = []
    title_list = []  # 只存标题，后面用来生成 title_outline
    
    current_pdf_id = 0
    i = 0
    
    while i < len(tokens):
        token = tokens[i]
        
        # === 标题 ===
        if token.type == 'heading_open':
            level = int(token.tag[1])  # h1 -> 1, h2 -> 2
            content_token = tokens[i + 1] if i + 1 < len(tokens) else None
            
            if content_token and content_token.type == 'inline':
                title_text = content_token.content
                
                # 去掉 HTML 标签
                title_text = re.sub(r'<[^>]+>', '', title_text).strip()
                
                # 记录标题
                title_item = {
                    "text": title_text,
                    "text_level": level,
                    "pdf_id": current_pdf_id,
                }
                title_list.append(title_item)
                
                content_list.append({
                    "type": "title",
                    "text": title_text,
                    "text_level": level,
                    "pdf_id": current_pdf_id,
                })
                current_pdf_id += 1
                
                i += 3  # 跳过 heading_open, inline, heading_close
                continue
        
        # === 段落（正文）或图片 ===
        if token.type == 'paragraph_open':
            # 找到对应的 inline token
            inline_token = tokens[i + 1] if i + 1 < len(tokens) else None
            
            if inline_token and inline_token.type == 'inline':
                # 检查 inline 中是否包含图片
                has_image = False
                if inline_token.children:
                    for child in inline_token.children:
                        if child.type == 'image':
                            has_image = True
                            img_src = child.attrGet('src')
                            img_alt = child.content
                            
                            # 转成绝对路径
                            if base_img_dir and not img_src.startswith('/'):
                                img_path = os.path.join(base_img_dir, img_src)
                            else:
                                img_path = img_src
                            
                            content_list.append({
                                "type": "image",
                                "img_path": img_path,
                                "image_caption": img_alt,
                                "pdf_id": current_pdf_id,
                            })
                            current_pdf_id += 1
                
                # 如果没有图片，则作为普通段落文本处理
                if not has_image:
                    para_text = inline_token.content
                    
                    # 去掉 HTML 标签（如 <font style="...">）
                    para_text = re.sub(r'<[^>]+>', '', para_text).strip()
                    
                    if para_text:  # 非空才加
                        content_list.append({
                            "type": "text",
                            "text": para_text,
                            "pdf_id": current_pdf_id,
                        })
                        current_pdf_id += 1
                
                i += 3  # 跳过 paragraph_open, inline, paragraph_close
                continue
        
        # === 表格 ===
        if token.type == 'table_open':
            # 把从这个 table_open 到 table_close 的所有行聚合成一个表格
            table_tokens = [token]
            i += 1
            while i < len(tokens) and tokens[i].type != 'table_close':
                table_tokens.append(tokens[i])
                i += 1
            if i < len(tokens):
                table_tokens.append(tokens[i])  # 加上 table_close
                i += 1
            
            # 从 token 流里提取表格行
            table_grid = extract_table_grid_from_tokens(table_tokens)
            
            if table_grid:
                # 格式化为文本（简单的管道分隔符格式）
                row_strings = [
                    " | ".join(cell.strip() if cell else "" for cell in row) for row in table_grid
                ]
                table_text = "Table:\n" + "\n".join(row_strings)
                
                content_list.append({
                    "type": "table",
                    "text": table_text,
                    "table_caption": [],
                    "table_footnote": [],
                    "pdf_id": current_pdf_id,
                })
                current_pdf_id += 1
            
            continue
        
        i += 1
    
    # 4. 生成 title_outline（只有标题的层级关系）
    title_outline = generate_title_outline(title_list, len(content_list))
    
    log.info(f"Parsed {len(content_list)} content items and {len(title_outline)} titles from markdown")
    
    # 调试信息：统计各类型内容
    type_counts = {}
    for item in content_list:
        t = item.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    log.info(f"Content types breakdown: {type_counts}")
    
    return content_list, title_outline


def extract_table_grid_from_tokens(table_tokens: List) -> List[List[str]]:
    """
    从 table token 流里提取 grid（二维数组）
    
    markdown-it-py 的 table token 结构中，行通过 tr_open/tr_close，
    单元格通过 td_open/th_open，内容在 inline token 的 content 里。
    """
    grid = []
    current_row = []
    
    for token in table_tokens:
        if token.type == 'tr_open':
            current_row = []
        elif token.type == 'td_open' or token.type == 'th_open':
            pass
        elif token.type == 'inline':
            cell_text = token.content.strip()
            cell_text = re.sub(r'<[^>]+>', '', cell_text).strip()
            current_row.append(cell_text)
        elif token.type == 'tr_close':
            if current_row:
                grid.append(current_row)
                current_row = []
    
    return grid


def generate_title_outline(title_list: List[Dict], total_content_ids: int) -> List[Dict]:
    """
    生成 title_outline（标题的层级和范围）
    
    逻辑：
    - 按顺序遍历标题
    - 记下每个标题的 parent（上一个更高级的标题）
    - 记下每个标题的 end_id（下一个同级或更高级标题之前的最后一个 content id）
    """
    if not title_list:
        return []
    
    outline = []
    stack = []  # 栈里存 (level, index)，用来找 parent
    
    for i, title in enumerate(title_list):
        level = title['text_level']
        
        # 找 parent：弹出栈直到栈顶的 level < 当前 level
        while stack and stack[-1][0] >= level:
            stack.pop()
        
        parent_id = stack[-1][1] if stack else None
        
        # 加入 outline
        outline_item = {
            "text": title['text'],
            "text_level": level,
            "pdf_id": title['pdf_id'],
            "parent_id": parent_id,
            "end_id": None,  # 先占位，后面再填
        }
        outline.append(outline_item)
        
        # 压入栈
        stack.append((level, i))
    
    # 回填 end_id：每个标题的 end_id = 下一个同级或更高级标题的 pdf_id - 1
    for i in range(len(outline)):
        # 找下一个同级或更高级的标题
        next_same_or_higher = None
        for j in range(i + 1, len(outline)):
            if outline[j]['text_level'] <= outline[i]['text_level']:
                next_same_or_higher = j
                break
        
        if next_same_or_higher is not None:
            outline[i]['end_id'] = outline[next_same_or_higher]['pdf_id']
        else:
            # 没有后续标题，end_id 就是最后一个 content 的 id
            outline[i]['end_id'] = total_content_ids
    
    return outline


def build_tree_from_markdown(cfg):
    """
    从 MD 文件构建 Tree 索引
    入口函数，类似 build_tree_from_pdf
    """
    from pathlib import Path
    from Core.Index.Tree import DocumentTree
    from Core.pipelines.doc_tree_builder import construct_tree_index
    from Core.pipelines.tree_node_summary import generate_tree_node_summary
    from Core.pipelines.tree_node_builder import enrich_image_nodes_with_summary
    from Core.provider.llm import LLM
    from Core.provider.vlm import VLM
    from Core.provider.TokenTracker import TokenTracker
    
    tree_index_path = DocumentTree.get_save_path(cfg.save_path)
    
    # 如果已有缓存则加载
    if os.path.exists(tree_index_path):
        log.info(f"Loading existing tree index from {tree_index_path}...")
        tree_index = DocumentTree.load_from_file(tree_index_path)
        log.info("Tree index loaded successfully.")
        return tree_index
    
    log.info("Creating a new tree index from markdown...")
    
    # 解析 MD 文件
    md_path = cfg.pdf_path  # 可改名为 doc_path，或继续沿用 pdf_path
    base_img_dir = os.path.dirname(os.path.abspath(md_path))  # MD 文件所在目录
    
    content_list, title_outline = parse_markdown_file(md_path, base_img_dir)
    
    os.makedirs(cfg.save_path, exist_ok=True)
    
    # 创建树索引
    meta_dict = {
        "file_name": os.path.basename(md_path),
        "file_path": md_path,
    }
    tree_index = DocumentTree(meta_dict=meta_dict, cfg=cfg)
    
    # 调用现有的 construct_tree_index（复用）
    tree_index = construct_tree_index(tree_index, content_list, title_outline)
    
    token_tracker = TokenTracker.get_instance()
    tree_index_cost = token_tracker.record_stage("tree_index_construction")
    log.info(f"Tree index construction cost: {tree_index_cost}")
    
    # 后续逻辑和 PDF 一致（summary、保存等）
    if cfg.tree.node_summary:
        llm = LLM(cfg.llm)
        vlm = VLM(cfg.vlm) if cfg.tree.use_vlm else None
        
        tree_index = generate_tree_node_summary(
            tree_index=tree_index,
            llm=llm,
            use_VLM=cfg.tree.use_vlm,
            vlm=vlm,
        )
        
        token_tracker = TokenTracker.get_instance()
        summary_cost = token_tracker.record_stage("tree_node_summary")
        log.info(f"Tree node summary generation cost: {summary_cost}")
        
        # 富化 IMAGE 节点
        tree_index = enrich_image_nodes_with_summary(tree_index)
        log.info("IMAGE nodes enriched with summary information")
    
    # 保存
    tree_index.save_to_file()
    return tree_index
