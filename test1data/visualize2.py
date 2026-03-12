#!/usr/bin/env python3
"""简洁清晰的可视化"""
import pickle, json, os
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx

plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

BASE = '/root/autodl-fs/bookrag/BookRAG/test1data/output/mqtt-paper-001'
OUT = '/root/autodl-fs/bookrag/BookRAG/test1data'

# ============================================================
# 图1: 文档树 - 只展示章节骨架 + 子节点统计
# ============================================================
def plot_tree():
    tree = pickle.load(open(f'{BASE}/tree.pkl', 'rb'))
    fig, ax = plt.subplots(figsize=(16, 10))

    G = nx.DiGraph()
    labels = {}
    colors = []
    sizes = []

    # 只取 TITLE 和 ROOT 节点
    title_nodes = []
    for n in tree.nodes:
        ntype = str(n.type)
        if ntype == 'root' or 'TITLE' in ntype:
            title_nodes.append(n)

    # 统计每个 title 下的叶子节点数
    def count_leaves(parent_id):
        counts = defaultdict(int)
        for n in tree.nodes:
            if n.parent and n.parent.index_id == parent_id and 'TITLE' not in str(n.type):
                short = str(n.type).split('.')[-1]
                counts[short] += 1
        return counts

    for n in title_nodes:
        nid = n.index_id
        G.add_node(nid)
        content = (n.meta_info.content or "").strip()[:20]
        if str(n.type) == 'root':
            content = "MQTT通信协议案例"

        leaves = count_leaves(nid)
        leaf_str = ""
        if leaves:
            parts = []
            for k in ['TEXT', 'IMAGE', 'TABLE']:
                if k in leaves:
                    parts.append(f"{leaves[k]}{k[0]}")  # 5T, 3I, 1Tb
            leaf_str = f"\n[{', '.join(parts)}]"

        labels[nid] = f"{content}{leaf_str}"

        if str(n.type) == 'root':
            colors.append('#2C3E50'); sizes.append(2000)
        elif n.depth == 1:
            colors.append('#C0392B'); sizes.append(1600)
        elif n.depth == 2:
            colors.append('#E74C3C'); sizes.append(1200)
        elif n.depth == 3:
            colors.append('#3498DB'); sizes.append(900)
        else:
            colors.append('#85C1E9'); sizes.append(700)

        if n.parent and n.parent.index_id in [x.index_id for x in title_nodes]:
            G.add_edge(n.parent.index_id, nid)

    try:
        pos = nx.nx_agraph.graphviz_layout(G, prog='dot')
    except:
        pos = nx.planar_layout(G)
        if not pos:
            pos = nx.spring_layout(G, k=3, seed=42)

    nx.draw_networkx_edges(G, pos, ax=ax, arrows=True, arrowsize=15,
                           edge_color='#AAB7B8', width=2, alpha=0.8,
                           connectionstyle="arc3,rad=0.05")
    nx.draw_networkx_nodes(G, pos, ax=ax, node_color=colors,
                           node_size=sizes, alpha=0.9, edgecolors='white', linewidths=2)
    nx.draw_networkx_labels(G, pos, labels=labels, ax=ax, font_size=7.5, font_weight='bold')

    ax.set_title('文档树结构 — MQTT通信协议案例\n(仅展示章节骨架，括号内为子节点统计: T=文本, I=图片, Tb=表格)',
                 fontsize=14, fontweight='bold', pad=15)
    ax.axis('off')
    plt.tight_layout()
    plt.savefig(f'{OUT}/vis_1_tree.png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print("图1 done")


# ============================================================
# 图2: 知识图谱 - 只展示 MQTT 核心子图
# ============================================================
def plot_kg():
    graph_data = json.load(open(f'{BASE}/graph_data.json'))
    g = graph_data['graph']

    # 手工挑选有意义的实体子集
    keep_names = {
        'mqtt', '1 mqtt', '3mqtt', 'tcp',
        'mosquitto', '1.3 mosquitto i', 'eclipse',
        'mqtt client', '2 mqtt_client 15',
        'mqtt sinewave pub', '3 mqtt_sinewave_pub 15]',
        'toolsweb mqtt sub',
        'tronlong', 'tronlong com',
        'broker',
    }

    id2node = {}
    for node in g['nodes']:
        nid = node.get('id', node.get('entity_name',''))
        id2node[nid] = node

    # 确定实际存在的节点 id
    keep_ids = set()
    name2id = {}
    for node in g['nodes']:
        nid = node.get('id', node.get('entity_name',''))
        name = node.get('entity_name', '').lower()
        if name in keep_names:
            keep_ids.add(nid)
            name2id[name] = nid

    # 找这些节点之间的边
    edges = []
    for link in g['links']:
        s, t = link['source'], link['target']
        if s in keep_ids and t in keep_ids:
            edges.append((s, t, link.get('description', '')[:40]))

    # 也把有边连接但不在 keep 中的节点加进来 (一跳扩展)
    extra = set()
    for link in g['links']:
        s, t = link['source'], link['target']
        if s in keep_ids and t not in keep_ids:
            tn = id2node.get(t, {}).get('entity_name', '').lower()
            if any(kw in tn for kw in ['mqtt','tcp','broker','mosquitto','client','pub','sub','eclipse','qos','topic','sinewave']):
                extra.add(t)
                edges.append((s, t, link.get('description','')[:40]))
        if t in keep_ids and s not in keep_ids:
            sn = id2node.get(s, {}).get('entity_name', '').lower()
            if any(kw in sn for kw in ['mqtt','tcp','broker','mosquitto','client','pub','sub','eclipse','qos','topic','sinewave']):
                extra.add(s)
                edges.append((s, t, link.get('description','')[:40]))
    keep_ids |= extra

    fig, ax = plt.subplots(figsize=(16, 12))

    G = nx.Graph()
    labels = {}
    colors = []
    sizes = []

    type_colors = {
        'PRODUCT': '#E74C3C',
        'SECTION_TITLE': '#3498DB',
        'ORGANIZATION': '#27AE60',
        'BROKER': '#8E44AD',
        'TASK_OR_PROBLEM': '#F39C12',
        'PERSON': '#D35400',
    }

    for nid in keep_ids:
        node = id2node.get(nid, {})
        name = node.get('entity_name', str(nid))
        etype = node.get('entity_type', 'OTHER')
        G.add_node(nid)
        labels[nid] = name[:22]
        colors.append(type_colors.get(etype, '#95A5A6'))
        is_core = any(kw in name.lower() for kw in ['mqtt', 'tcp', 'mosquitto', 'broker'])
        sizes.append(1800 if is_core else 900)

    for s, t, desc in edges:
        if s in keep_ids and t in keep_ids:
            G.add_edge(s, t)

    # 去除孤立节点
    isolates = list(nx.isolates(G))
    G.remove_nodes_from(isolates)
    for iso in isolates:
        if iso in labels: del labels[iso]

    # 重新对齐 colors 和 sizes
    ordered_nodes = list(G.nodes())
    id_set = set(ordered_nodes)
    colors2 = []
    sizes2 = []
    for nid in ordered_nodes:
        node = id2node.get(nid, {})
        etype = node.get('entity_type', 'OTHER')
        name = node.get('entity_name', '')
        colors2.append(type_colors.get(etype, '#95A5A6'))
        is_core = any(kw in name.lower() for kw in ['mqtt', 'tcp', 'mosquitto', 'broker'])
        sizes2.append(1800 if is_core else 900)

    pos = nx.spring_layout(G, k=2.5, iterations=100, seed=42)

    nx.draw_networkx_edges(G, pos, ax=ax, edge_color='#BDC3C7', width=2, alpha=0.6)
    nx.draw_networkx_nodes(G, pos, ax=ax, nodelist=ordered_nodes,
                           node_color=colors2, node_size=sizes2,
                           alpha=0.9, edgecolors='white', linewidths=2)
    nx.draw_networkx_labels(G, pos, labels=labels, ax=ax, font_size=9, font_weight='bold')

    # 边标签 - 只标注重要的
    edge_labels = {}
    for s, t, desc in edges:
        if s in id_set and t in id_set and desc:
            short = desc[:30]
            edge_labels[(s, t)] = short
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, ax=ax, font_size=6, alpha=0.7)

    legend_items = [
        mpatches.Patch(color='#E74C3C', label='PRODUCT (产品/协议)'),
        mpatches.Patch(color='#3498DB', label='SECTION (章节)'),
        mpatches.Patch(color='#27AE60', label='ORGANIZATION'),
        mpatches.Patch(color='#8E44AD', label='BROKER (代理)'),
        mpatches.Patch(color='#95A5A6', label='OTHER'),
    ]
    ax.legend(handles=legend_items, loc='upper left', fontsize=10, framealpha=0.9)
    ax.set_title(f'知识图谱 (MQTT 核心子图)\n总实体: {len(g["nodes"])}  总关系: {len(g["links"])}  展示: {len(G.nodes)}实体 {len(G.edges)}关系',
                 fontsize=14, fontweight='bold', pad=15)
    ax.axis('off')
    plt.tight_layout()
    plt.savefig(f'{OUT}/vis_2_kg.png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print("图2 done")


# ============================================================
# 图3: RAG 流程示意图 - 纯手绘风格流程图
# ============================================================
def plot_rag_flow():
    fig, ax = plt.subplots(figsize=(18, 8))

    def draw_box(x, y, w, h, text, color, fontsize=9, bold_title=None):
        rect = mpatches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.015",
                                        facecolor=color, alpha=0.15, edgecolor=color, linewidth=2.5)
        ax.add_patch(rect)
        if bold_title:
            ax.text(x + w/2, y + h - 0.03, bold_title, ha='center', va='top',
                    fontsize=fontsize+2, fontweight='bold', color=color)
            ax.text(x + w/2, y + h/2 - 0.01, text, ha='center', va='center',
                    fontsize=fontsize, color='#333', linespacing=1.5)
        else:
            ax.text(x + w/2, y + h/2, text, ha='center', va='center',
                    fontsize=fontsize, color='#333', linespacing=1.5)

    def draw_arrow(x1, y1, x2, y2, label=None):
        ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle='->', color='#555', lw=2.5))
        if label:
            mx, my = (x1+x2)/2, (y1+y2)/2 + 0.03
            ax.text(mx, my, label, ha='center', fontsize=7.5, color='#777', style='italic')

    # 上面一行: RAG 在线流程 (5 个步骤)
    y_top = 0.55
    bw, bh = 0.155, 0.35

    draw_box(0.02, y_top, bw, bh, '问题:\nMQTT协议构建在\n什么协议上？', '#3498DB', bold_title='① 输入')
    draw_box(0.20, y_top, bw, bh, 'LLM 分类问题类型\nsimple/complex/global\n\n实际结果: global\n(应为 simple)', '#E67E22', bold_title='② 问题规划')
    draw_box(0.38, y_top, bw, bh, '问题 → Embedding →\nkg_vdb 检索实体\n→ LLM 提取实体\n→ 映射到图谱实体', '#9B59B6', bold_title='③ 实体检索')
    draw_box(0.56, y_top, bw, bh, '实体 → 定位树节点\n→ LLM 选章节\n→ Graph+Text\n   双重 Rerank\n→ Skyline 过滤', '#E74C3C', bold_title='④ 检索过滤')
    draw_box(0.74, y_top, bw+0.07, bh, 'Retrieved Nodes\n+ Graph Entities\n→ LLM 生成答案\n→ 合成最终回答\n\n期望: TCP/IP协议', '#27AE60', bold_title='⑤ 答案生成')

    # 箭头
    gap = 0.025
    for i, x in enumerate([0.02, 0.20, 0.38, 0.56]):
        draw_arrow(x + bw + gap*0.3, y_top + bh/2, x + bw + gap + 0.005, y_top + bh/2)

    # 下面一行: 离线索引 (3 个)
    y_bot = 0.05
    bw2, bh2 = 0.28, 0.38

    draw_box(0.03, y_bot, bw2, bh2,
             '180 个节点\n19 章节 · 128 段落\n30 图片 · 2 表格\n\n层次: ROOT → 章 → 节 → 段',
             '#3498DB', fontsize=10, bold_title='文档树 (tree.pkl)')

    draw_box(0.36, y_bot, bw2, bh2,
             '175 个实体 · 65 条关系\n94 个树节点有实体映射\n\n核心实体: MQTT, TCP,\nMosquitto, Eclipse Broker',
             '#E74C3C', fontsize=10, bold_title='知识图谱 (graph_data.json)')

    draw_box(0.69, y_bot, bw2, bh2,
             'Tree VDB: 143 文本 + 28 图片\n  模型: gme-Qwen2-VL-2B\n\nKG VDB: 175 实体向量\n  模型: Qwen3-Embedding-0.6B',
             '#27AE60', fontsize=10, bold_title='向量数据库 (ChromaDB)')

    # 从下方索引指向上方流程的虚线箭头
    for bx, tx in [(0.17, 0.455), (0.50, 0.455), (0.83, 0.455)]:
        ax.annotate('', xy=(tx, y_top - 0.01), xytext=(bx, y_bot + bh2 + 0.01),
                    arrowprops=dict(arrowstyle='->', color='#AAA', lw=1.5, linestyle='dashed'))

    ax.text(0.17, 0.465, '加载', ha='center', fontsize=7, color='#999')
    ax.text(0.50, 0.465, '加载', ha='center', fontsize=7, color='#999')
    ax.text(0.83, 0.465, '加载', ha='center', fontsize=7, color='#999')

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title('BookRAG GBC 策略 — RAG 检索全流程', fontsize=16, fontweight='bold', pad=15)
    ax.axis('off')
    plt.tight_layout()
    plt.savefig(f'{OUT}/vis_3_rag_flow.png', dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print("图3 done")


if __name__ == '__main__':
    plot_tree()
    plot_kg()
    plot_rag_flow()
    print("全部完成")
