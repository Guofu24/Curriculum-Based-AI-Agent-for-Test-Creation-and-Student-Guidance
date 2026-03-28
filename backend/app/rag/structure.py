"""Structure detection: heading tree building from markdown."""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HeadingNode:
    """A node in the heading tree."""
    id: str
    title: str
    level: int  # 1 = chapter, 2 = section, 3 = subsection
    children: list["HeadingNode"] = field(default_factory=list)
    page_number: int | None = None
    content_chunks: list[str] = field(default_factory=list)


def detect_heading_tree(markdown_content: str) -> dict:
    """
    Detect heading tree from markdown content.
    Returns a nested dictionary representing the document structure.
    """
    lines = markdown_content.split("\n")
    root = HeadingNode(id="root", title="Document", level=0, children=[])
    stack: list[HeadingNode] = [root]

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Match markdown headings (# heading)
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            node_id = _generate_node_id(title, level)

            node = HeadingNode(
                id=node_id,
                title=title,
                level=level,
                children=[],
            )

            # Find parent
            while stack and stack[-1].level >= level:
                stack.pop()

            if stack:
                stack[-1].children.append(node)

            stack.append(node)
            continue

        # Page separator: <!-- Page N -->
        page_match = re.search(r"<!--\s*Page\s*(\d+)\s*-->", line)
        if page_match:
            page_num = int(page_match.group(1))
            if stack:
                stack[-1].page_number = page_num
            continue

        # Content: add to current node
        if stack and stack[-1].level > 0:
            stack[-1].content_chunks.append(line)

    return _heading_node_to_dict(root)


def _generate_node_id(title: str, level: int) -> str:
    """Generate a unique ID for a heading node."""
    # Normalize title for ID
    normalized = re.sub(r"[^\w\s\u00C0-\u024F]", "", title)
    normalized = re.sub(r"\s+", "_", normalized.strip().lower())
    prefix = {1: "ch", 2: "sec", 3: "sub", 4: "para", 5: "para", 6: "para"}.get(level, "node")
    return f"{prefix}_{normalized}"


def _heading_node_to_dict(node: HeadingNode) -> dict:
    """Convert HeadingNode tree to dictionary."""
    return {
        "id": node.id,
        "title": node.title,
        "level": node.level,
        "page_number": node.page_number,
        "children": [_heading_node_to_dict(child) for child in node.children],
        # Store content preview (first 3 chunks)
        "content_preview": " ".join(node.content_chunks[:3]) if node.content_chunks else "",
    }


def flatten_heading_tree(tree: dict, max_chapters: int = 20) -> list[dict]:
    """Flatten heading tree to a list of chapters/sections for scope selection."""
    chapters = []

    def traverse(node: dict, parent_path: list[str] = None):
        parent_path = parent_path or []

        if node["level"] >= 1 and node["level"] <= 3:
            path = parent_path + [node["title"]]
            chapters.append({
                "id": node["id"],
                "title": node["title"],
                "level": node["level"],
                "path": " > ".join(path),
                "parent_id": parent_path[-1]["id"] if len(parent_path) > 1 else None,
                "children_count": len(node["children"]),
            })

        for child in node.get("children", []):
            traverse(child, parent_path + [node])

    traverse(tree)
    return chapters[:max_chapters]
