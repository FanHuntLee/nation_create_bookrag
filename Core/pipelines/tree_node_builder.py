from typing import Optional
from Core.Index.Tree import TreeNode, NodeType, DocumentTree
from Core.utils.table_utils import table2text
import logging

log = logging.getLogger(__name__)


def create_node_by_type(pdf_content: Optional[str], isTitle: bool) -> TreeNode:
    content_type = pdf_content.get("type", "unknown")
    
    # 如果 type 是 "title"，则设置 isTitle = True
    if content_type == "title":
        isTitle = True
        content_type = "text"  # 标题也是文本类型，但需要标记为 TITLE
    
    if content_type == "text":
        node_meta = {
            "content": pdf_content.get("text", ""),
            "pdf_id": pdf_content.get("pdf_id", -1),
            "page_idx": pdf_content.get("page_idx", -1),
            "pdf_para_block": pdf_content.get("middle_json", {}),
        }
        if isTitle:
            level = pdf_content.get("text_level", -1)
            if isinstance(level, str):
                try:
                    level = int(level)
                    node_meta["title_level"] = level
                except ValueError:
                    level = -1
                    isTitle = False
            else:
                node_meta["title_level"] = level

        node = TreeNode(node_meta)
        node.type = NodeType.TITLE if isTitle else NodeType.TEXT
        node.outline_node = isTitle
    elif content_type == "image":
        caption = pdf_content.get("image_caption", [])
        caption_str = " ".join(caption) if isinstance(caption, list) else ""
        footnote = pdf_content.get("image_footnote", [])
        footnote_str = " ".join(footnote) if isinstance(footnote, list) else ""
        node_meta = {
            "img_path": pdf_content.get("img_path", ""),
            "caption": caption_str,
            "footnote": footnote_str,
            "content": caption_str + footnote_str,
            "pdf_id": pdf_content.get("pdf_id", -1),
            "page_idx": pdf_content.get("page_idx", -1),
            "pdf_para_block": pdf_content.get("middle_json", {}),
        }
        node = TreeNode(node_meta)
        node.type = NodeType.IMAGE
    elif content_type == "table":
        caption = pdf_content.get("table_caption", [])
        caption_str = " ".join(caption) if isinstance(caption, list) else ""
        footnote = pdf_content.get("table_footnote", [])
        footnote_str = " ".join(footnote) if isinstance(footnote, list) else ""
        table_body_html = pdf_content.get("table_body", "")
        
        # Check if this is a pre-formatted table text (from Markdown)
        table_text_pre = pdf_content.get("text", "")
        
        if table_text_pre:
            # MD 表格：直接使用已格式化的文本
            table_text = table_text_pre
        elif table_body_html:
            # PDF 表格：转换 HTML 为文本
            table_data = {
                "caption": caption_str,
                "table_body": table_body_html,
                "footnote": footnote_str,
            }
            table_text = table2text(table_data)
        else:
            table_text = ""

        node_meta = {
            "img_path": pdf_content.get("img_path", ""),
            "caption": caption_str,
            "footnote": footnote_str,
            "content": table_text,
            "table_body": table_body_html,
            "pdf_id": pdf_content.get("pdf_id", -1),
            "page_idx": pdf_content.get("page_idx", -1),
            "pdf_para_block": pdf_content.get("middle_json", {}),
        }
        node = TreeNode(node_meta)
        node.type = NodeType.TABLE
    elif content_type == "equation":
        node_meta = {
            "content": pdf_content.get("text", ""),
            "pdf_id": pdf_content.get("pdf_id", -1),
            "page_idx": pdf_content.get("page_idx", -1),
            "pdf_para_block": pdf_content.get("middle_json", {}),
            "text_format": pdf_content.get("text_format", ""),
        }
        node = TreeNode(node_meta)
        node.type = NodeType.EQUATION
    else:
        log.warning(f"Unknown content type: {content_type}. Defaulting to text.")
        node_meta = {
            "content": pdf_content.get("text", ""),
            "pdf_id": pdf_content.get("pdf_id", -1),
            "page_idx": pdf_content.get("page_idx", -1),
            "pdf_para_block": pdf_content.get("middle_json", {}),
        }
        node = TreeNode(node_meta)
        node.type = NodeType.TEXT

    return node


def enrich_image_nodes_with_summary(tree_index: DocumentTree) -> DocumentTree:
    """
    For IMAGE nodes, concatenate caption + summary + footnote with spaces and set as content.
    This enriches the content field with summary information.
    """
    for node in tree_index.nodes:
        if node.type == NodeType.IMAGE:
            parts = []
            
            # Get caption
            caption = node.meta_info.caption or ""
            if caption.strip():
                parts.append(caption.strip())
            
            # Get summary
            summary = node.summary or ""
            if summary.strip():
                parts.append(summary.strip())
            
            # Get footnote
            footnote = node.meta_info.footnote or ""
            if footnote.strip():
                parts.append(footnote.strip())
            
            # Join all parts with space
            if parts:
                node.meta_info.content = " ".join(parts)
            
            log.info(f"Enriched IMAGE node {node.index_id} with summary. New content length: {len(node.meta_info.content)}")
    
    return tree_index
