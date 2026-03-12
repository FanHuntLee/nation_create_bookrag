#!/usr/bin/env python3
"""
BookRAG 可视化脚本 - MQTT 协议案例
生成三张图:
1. 文档树结构图 (展示 PDF 的层次结构)
2. 知识图谱可视化 (展示实体和关系)
3. RAG 检索流程图 (展示从问题到答案的检索路径)
"""

import pickle
import json
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
from collections import defaultdict
import textwrap

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'WenQuanYi Micro Hei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

BASE = '/root/autodl-fs/bookrag/BookRAG/test1data/output/mqtt-paper-001'
OUT = '/root/autodl-fs/bookrag/BookRAG/test1data'


def wrap_text(text, width=18):
    if not text:
        return ""
    text = text.strip().replace('\n', ' ')
    if len(text) > width * 2:
        text = text[:width * 2] + '...'
    return '\n'.join(textwrap.wrap(text, width=width))


# ============================================================
# 图1: 文档树结构
# ============================================================
def plot_document_tree():
    tree = pickle.load(open(f'{BASE}/tree.pkl', 'rb'))

    fig, ax = plt.subplots(1, 1, figsize=(22, 14))
    ax.set_title('文档树结构 (Document Tree) - MQTT通信协议案例', fontsize=18, fontweight='bold', pad=20)

    # 只展示前3层 + 每个节点的部分子节点
    type_colors = {
        'root': '#2C3E50',
        'NodeType.TITLE': '#E74C3C',
        'NodeType.TEXT': '#3498DB',
        'NodeType.IMAGE': '#2ECC71',
        'NodeType.TABLE': '#F39C12',
        'NodeType.EQUATION': '#9B59B6',
    }

    G = nx.DiGraph()
    node_colors = []
    node_labels = {}
    nodes_to_show = set()

    # 收集要展示的节点: 所有 depth <= 3 的节点，加上 depth=4 的前几个
    for n in tree.nodes:
        if n.depth <= 3:
            nodes_to_show.add(n.index_id)
        elif n.depth == 4 and len([x for x in nodes_to_show if tree.nodes[x].depth == 3 and tree.nodes[x] == n.parent]) < 6:
            nodes_to_show.add(n.index_id)

    # 简化: 展示所有 TITLE 节点 + 每个 TITLE 下最多3个子节点
    title_ids = set()
    for n in tree.nodes:
        if 'TITLE' in str(n.type) or str(n.type) == 'root':
            title_ids.add(n.index_id)

    show_ids = set()
    for n in tree.nodes:
        ntype = str(n.type)
        if ntype == 'root' or 'TITLE' in ntype:
            show_ids.add(n.index_id)
        elif n.parent and n.parent.index_id in title_ids:
            # 每个 title 下最多显示 3 个子节点
            siblings = [c for c in tree.nodes if c.parent and c.parent.index_id == n.parent.index_id and c.index_id in show_ids and 'TITLE' not in str(c.type)]
            if len(siblings) < 3:
                show_ids.add(n.index_id)

    for n in tree.nodes:
        if n.index_id not in show_ids:
            continue
        ntype = str(n.type)
        content = n.meta_info.content if n.meta_info.content else ""
        label = wrap_text(content, 14) if content else f"[{ntype.split('.')[-1]}]"
        if ntype == 'root':
            label = "ROOT\nMQTT通信协议"

        G.add_node(n.index_id)
        node_labels[n.index_id] = label
        node_colors.append(type_colors.get(ntype, '#95A5A6'))

        if n.parent and n.parent.index_id in show_ids:
            G.add_edge(n.parent.index_id, n.index_id)

    # 使用层次布局
    try:
        pos = nx.nx_agraph.graphviz_layout(G, prog='dot')
    except:
        pos = nx.spring_layout(G, k=2, iterations=50, seed=42)

    nx.draw_networkx_edges(G, pos, ax=ax, arrows=True, arrowsize=10,
                           edge_color='#BDC3C7', width=1.0, alpha=0.7)
    nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_colors,
                           node_size=800, alpha=0.9, edgecolors='white', linewidths=1.5)
    nx.draw_networkx_labels(G, pos, labels=node_labels, ax=ax,
                            font_size=6, font_weight='bold')

    # 图例
    legend_items = [
        mpatches.Patch(color='#E74C3C', label='TITLE (标题/章节)'),
        mpatches.Patch(color='#3498DB', label='TEXT (正文)'),
        mpatches.Patch(color='#2ECC71', label='IMAGE (图片)'),
        mpatches.Patch(color='#F39C12', label='TABLE (表格)'),
    ]
    ax.legend(handles=legend_items, loc='upper left', fontsize=11, framealpha=0.9)

    # 统计信息
    type_counts = defaultdict(int)
    for n in tree.nodes:
        type_counts[str(n.type)] += 1
    stats = f"总节点数: {len(tree.nodes)} | TITLE: {type_counts.get('NodeType.TITLE',0)} | TEXT: {type_counts.get('NodeType.TEXT',0)} | IMAGE: {type_counts.get('NodeType.IMAGE',0)} | TABLE: {type_counts.get('NodeType.TABLE',0)}"
    ax.text(0.5, -0.02, stats, transform=ax.transAxes, ha='center', fontsize=11, color='#555')

    ax.axis('off')
    plt.tight_layout()
    plt.savefig(f'{OUT}/vis_1_document_tree.png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print("图1: 文档树 已保存")


# ============================================================
# 图2: 知识图谱
# ============================================================
def plot_knowledge_graph():
    graph_data = json.load(open(f'{BASE}/graph_data.json'))
    g_data = graph_data['graph']

    fig, ax = plt.subplots(1, 1, figsize=(20, 16))
    ax.set_title('知识图谱 (Knowledge Graph) - MQTT通信协议', fontsize=18, fontweight='bold', pad=20)

    G = nx.Graph()
    node_labels = {}
    node_colors = []
    node_sizes = []

    type_color_map = {
        'PRODUCT': '#E74C3C',
        'SECTION_TITLE': '#3498DB',
        'ORGANIZATION': '#2ECC71',
        'PERSON': '#F39C12',
        'BROKER': '#9B59B6',
        'TABLE': '#E67E22',
        'TASK_OR_PROBLEM': '#1ABC9C',
        'NUMBER': '#95A5A6',
        'STRING': '#95A5A6',
        'DATE': '#95A5A6',
    }

    # 过滤: 只保留有边连接的节点，或名字中含 mqtt/tcp 等关键词的
    nodes_in_links = set()
    for link in g_data['links']:
        nodes_in_links.add(link['source'])
        nodes_in_links.add(link['target'])

    # 选择有意义的节点
    selected_nodes = set()
    for node in g_data['nodes']:
        name = node.get('entity_name', '')
        nid = node.get('id', name)
        # 优先选有连接的 + 关键词相关的
        is_mqtt_related = any(kw in name.lower() for kw in ['mqtt', 'tcp', 'mosquitto', 'broker', 'client', 'pub', 'sub', 'eclipse', 'topic', 'qos', 'payload', 'sinewave', 'tronlong'])
        if nid in nodes_in_links or is_mqtt_related:
            selected_nodes.add(nid)

    # 限制节点数量
    if len(selected_nodes) > 60:
        # 优先保留有连接的
        selected_nodes = set(list(nodes_in_links)[:60])

    node_id_map = {}
    for node in g_data['nodes']:
        name = node.get('entity_name', '')
        nid = node.get('id', name)
        if nid not in selected_nodes:
            continue

        etype = node.get('entity_type', 'OTHER')
        label = wrap_text(name, 12)
        G.add_node(nid)
        node_id_map[nid] = node
        node_labels[nid] = label
        color = type_color_map.get(etype, '#BDC3C7')
        node_colors.append(color)
        # MQTT 相关的大一些
        is_key = any(kw in name.lower() for kw in ['mqtt', 'tcp', 'mosquitto', 'broker', 'client'])
        node_sizes.append(1200 if is_key else 500)

    for link in g_data['links']:
        src, tgt = link['source'], link['target']
        if src in selected_nodes and tgt in selected_nodes:
            G.add_edge(src, tgt)

    if len(G.nodes) == 0:
        print("图2: 无节点可展示")
        return

    pos = nx.spring_layout(G, k=1.8, iterations=80, seed=42)

    nx.draw_networkx_edges(G, pos, ax=ax, edge_color='#BDC3C7', width=1.2, alpha=0.5)
    nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_colors,
                           node_size=node_sizes, alpha=0.85, edgecolors='white', linewidths=1.5)
    nx.draw_networkx_labels(G, pos, labels=node_labels, ax=ax,
                            font_size=6, font_weight='bold')

    # 图例
    legend_items = [
        mpatches.Patch(color='#E74C3C', label='PRODUCT (产品/协议)'),
        mpatches.Patch(color='#3498DB', label='SECTION_TITLE (章节)'),
        mpatches.Patch(color='#2ECC71', label='ORGANIZATION (组织)'),
        mpatches.Patch(color='#9B59B6', label='BROKER (消息代理)'),
        mpatches.Patch(color='#1ABC9C', label='TASK (任务)'),
        mpatches.Patch(color='#F39C12', label='PERSON (人员)'),
    ]
    ax.legend(handles=legend_items, loc='upper left', fontsize=10, framealpha=0.9)

    stats = f"总实体数: {len(g_data['nodes'])} | 总关系数: {len(g_data['links'])} | 展示: {len(G.nodes)} 个实体, {len(G.edges)} 条关系"
    ax.text(0.5, -0.02, stats, transform=ax.transAxes, ha='center', fontsize=11, color='#555')

    ax.axis('off')
    plt.tight_layout()
    plt.savefig(f'{OUT}/vis_2_knowledge_graph.png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print("图2: 知识图谱 已保存")


# ============================================================
# 图3: RAG 检索流程图
# ============================================================
def plot_rag_pipeline():
    fig, ax = plt.subplots(1, 1, figsize=(20, 12))
    ax.set_title('RAG 检索流程 - "MQTT协议构建在什么协议上？"', fontsize=18, fontweight='bold', pad=20)

    # 加载实际数据
    tree = pickle.load(open(f'{BASE}/tree.pkl', 'rb'))
    graph_data = json.load(open(f'{BASE}/graph_data.json'))
    rag_res = json.load(open(f'{BASE}/eval_test1_gbc_standard/query_001/retrieval_res.json'))

    # 流程框的位置和内容
    boxes = [
        # (x, y, width, height, title, content, color)
        (0.02, 0.78, 0.18, 0.18, "① 输入", f"问题: MQTT协议构建在\n什么协议上？\n\n标准答案: TCP/IP协议", '#3498DB'),
        (0.22, 0.78, 0.18, 0.18, "② 问题规划", f"LLM 分类结果:\n类型: {rag_res['plan']['query_type']}\n操作: {rag_res['plan'].get('operation','N/A')}\n过滤: {rag_res['plan']['filters'][0]['filter_value'] if rag_res['plan'].get('filters') else 'N/A'}", '#E74C3C'),
        (0.42, 0.78, 0.18, 0.18, "③ 实体检索", f"kg_vdb 检索:\n匹配实体数: 0\n\n⚠ 实体匹配失败\n(中文问题 vs 英文实体)", '#F39C12'),
        (0.62, 0.78, 0.18, 0.18, "④ 检索结果", f"检索节点数: 0\n\n⚠ 全局过滤无匹配\nfilter='协议' 未找到\n对应章节标题", '#E74C3C'),
        (0.82, 0.78, 0.16, 0.18, "⑤ 输出", f"回答: 未找到\n相关内容\n\n(流程中断)", '#95A5A6'),
    ]

    for (x, y, w, h, title, content, color) in boxes:
        rect = mpatches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01",
                                        facecolor=color, alpha=0.15, edgecolor=color, linewidth=2)
        ax.add_patch(rect)
        ax.text(x + w/2, y + h - 0.02, title, ha='center', va='top',
                fontsize=12, fontweight='bold', color=color)
        ax.text(x + w/2, y + h/2 - 0.02, content, ha='center', va='center',
                fontsize=8.5, color='#333', linespacing=1.4)

    # 箭头连接
    for i in range(4):
        x1 = boxes[i][0] + boxes[i][2]
        x2 = boxes[i+1][0]
        y_mid = boxes[i][1] + boxes[i][3]/2
        ax.annotate('', xy=(x2, y_mid), xytext=(x1, y_mid),
                    arrowprops=dict(arrowstyle='->', color='#555', lw=2))

    # 下半部分: 展示实际的离线索引数据
    # 文档树统计
    type_counts = defaultdict(int)
    for n in tree.nodes:
        type_counts[str(n.type)] += 1

    tree_box = mpatches.FancyBboxPatch((0.02, 0.08), 0.28, 0.58, boxstyle="round,pad=0.01",
                                        facecolor='#3498DB', alpha=0.08, edgecolor='#3498DB', linewidth=2)
    ax.add_patch(tree_box)
    ax.text(0.16, 0.63, '离线索引: 文档树', ha='center', fontsize=13, fontweight='bold', color='#3498DB')

    tree_info = (
        f"节点总数: {len(tree.nodes)}\n"
        f"├ TITLE: {type_counts.get('NodeType.TITLE',0)} 个章节\n"
        f"├ TEXT: {type_counts.get('NodeType.TEXT',0)} 个段落\n"
        f"├ IMAGE: {type_counts.get('NodeType.IMAGE',0)} 张图片\n"
        f"└ TABLE: {type_counts.get('NodeType.TABLE',0)} 个表格\n\n"
        f"主要章节:\n"
    )
    titles = [n for n in tree.nodes if 'TITLE' in str(n.type) and n.depth <= 3]
    for t in titles[:8]:
        content = (t.meta_info.content or "")[:25].strip()
        tree_info += f"  · {content}\n"

    ax.text(0.16, 0.52, tree_info, ha='center', va='top', fontsize=8, color='#333',
            linespacing=1.5, family='monospace')

    # 知识图谱统计
    g_data = graph_data['graph']
    kg_box = mpatches.FancyBboxPatch((0.35, 0.08), 0.28, 0.58, boxstyle="round,pad=0.01",
                                      facecolor='#E74C3C', alpha=0.08, edgecolor='#E74C3C', linewidth=2)
    ax.add_patch(kg_box)
    ax.text(0.49, 0.63, '离线索引: 知识图谱', ha='center', fontsize=13, fontweight='bold', color='#E74C3C')

    # 实体类型统计
    etype_counts = defaultdict(int)
    for node in g_data['nodes']:
        etype_counts[node.get('entity_type', 'OTHER')] += 1

    kg_info = (
        f"实体总数: {len(g_data['nodes'])}\n"
        f"关系总数: {len(g_data['links'])}\n"
        f"tree→kg映射: {len(graph_data['tree2kg'])} 个\n\n"
        f"实体类型分布:\n"
    )
    for etype, cnt in sorted(etype_counts.items(), key=lambda x: -x[1])[:6]:
        kg_info += f"  · {etype}: {cnt}\n"

    kg_info += f"\nMQTT相关实体:\n"
    mqtt_ents = [n['entity_name'] for n in g_data['nodes']
                 if any(kw in n.get('entity_name','').lower() for kw in ['mqtt','tcp','broker','mosquitto'])]
    for e in mqtt_ents[:6]:
        kg_info += f"  · {e[:25]}\n"

    ax.text(0.49, 0.52, kg_info, ha='center', va='top', fontsize=8, color='#333',
            linespacing=1.5, family='monospace')

    # 向量数据库统计
    vdb_box = mpatches.FancyBboxPatch((0.68, 0.08), 0.28, 0.58, boxstyle="round,pad=0.01",
                                       facecolor='#2ECC71', alpha=0.08, edgecolor='#2ECC71', linewidth=2)
    ax.add_patch(vdb_box)
    ax.text(0.82, 0.63, '离线索引: 向量数据库', ha='center', fontsize=13, fontweight='bold', color='#2ECC71')

    vdb_info = (
        f"Tree VDB (ChromaDB):\n"
        f"  文本向量: 143 条\n"
        f"  图片向量: 28 条\n"
        f"  模型: gme-Qwen2-VL-2B\n\n"
        f"KG VDB (ChromaDB):\n"
        f"  实体向量: {len(g_data['nodes'])} 条\n"
        f"  模型: Qwen3-Embedding\n\n"
        f"⚠ RAG 失败原因分析:\n"
        f"  1. LLM 将 simple 问题\n"
        f"     误分为 global/COUNT\n"
        f"  2. 中文 filter '协议' 无法\n"
        f"     匹配英文章节标题"
    )
    ax.text(0.82, 0.52, vdb_info, ha='center', va='top', fontsize=8, color='#333',
            linespacing=1.5, family='monospace')

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    plt.tight_layout()
    plt.savefig(f'{OUT}/vis_3_rag_pipeline.png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print("图3: RAG流程 已保存")


if __name__ == '__main__':
    plot_document_tree()
    plot_knowledge_graph()
    plot_rag_pipeline()
    print("\n所有可视化图片已生成!")
