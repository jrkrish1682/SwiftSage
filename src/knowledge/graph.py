"""
Graphviz rendering of a knowledge neighbourhood.

Emits DOT text for `st.graphviz_chart`, which renders it natively — no extra
dependency and nothing to install for a demo laptop. Only a neighbourhood is
ever drawn: the full graph becomes an unreadable hairball as soon as it holds
anything useful, and the question a BA actually asks is "what does *this* rule
touch?".

Node kind drives the shape, status drives the colour — an unconfirmed candidate
is visibly dashed and amber wherever it appears, including here.
"""
from __future__ import annotations

from src.knowledge import store as ks

_SHAPES = {
    ks.RULE: "box",
    ks.ISO_ELEMENT: "ellipse",
    ks.INTERNAL_FIELD: "ellipse",
    ks.MAPPING: "parallelogram",
    ks.DEFECT: "octagon",
    ks.TEST_SCENARIO: "note",
    ks.SYSTEM: "cylinder",
    ks.MESSAGE_TYPE: "folder",
}

_FILLS = {
    ks.SEEDED: "#DDE9FB",
    ks.CONFIRMED: "#D6F2E3",
    ks.CANDIDATE: "#FDF0D5",
    ks.RETIRED: "#ECEFF3",
}

_BORDERS = {
    ks.SEEDED: "#3A6FD8",
    ks.CONFIRMED: "#1E8E5A",
    ks.CANDIDATE: "#C88A1A",
    ks.RETIRED: "#9AA3AE",
}

_MAX_LABEL = 34


def _label(node: ks.Node) -> str:
    name = node.name if len(node.name) <= _MAX_LABEL else node.name[: _MAX_LABEL - 1] + "…"
    lines = [node.id, name]
    if node.kind == ks.ISO_ELEMENT:
        message_type = str(node.detail.get("message_type", ""))
        if message_type:
            lines.append(message_type)
    if node.status == ks.CANDIDATE:
        lines.append("(candidate)")
    return "\\n".join(line.replace('"', "'") for line in lines)


def to_dot(neighbourhood: ks.Neighbourhood) -> str:
    """DOT source for one neighbourhood, centre node emphasised."""
    lines = [
        "digraph knowledge {",
        '  rankdir=LR;',
        '  bgcolor="transparent";',
        '  node [style="filled,rounded", fontname="Helvetica", fontsize=10];',
        '  edge [fontname="Helvetica", fontsize=9, color="#6B7A90"];',
    ]
    for node in neighbourhood.nodes:
        centre = node.id == neighbourhood.centre.id
        lines.append(
            f'  "{node.id}" [label="{_label(node)}", '
            f'shape={_SHAPES.get(node.kind, "box")}, '
            f'fillcolor="{_FILLS.get(node.status, "#FFFFFF")}", '
            f'color="{_BORDERS.get(node.status, "#6B7A90")}", '
            f'penwidth={3 if centre else 1}];'
        )
    for edge in neighbourhood.edges:
        style = "dashed" if edge.relation == ks.CONTRADICTS else "solid"
        lines.append(
            f'  "{edge.src}" -> "{edge.dst}" '
            f'[label="{edge.relation}", style={style}];'
        )
    lines.append("}")
    return "\n".join(lines)
