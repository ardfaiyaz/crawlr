"""DOM simplifier: reduce a raw HTML page to a compact representation.

Sending full HTML to an LLM is wasteful (scripts, styles, SVGs, tracking
markup). We strip noise and emit a compact outline that preserves the tags,
key attributes (id/class), and text needed to reason about selectors. This
typically cuts token count by 80-95% while keeping selector-relevant signal.
"""

from __future__ import annotations

from selectolax.parser import HTMLParser, Node

# Tags that never contain user-facing content worth extracting.
_NOISE_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "path",
    "iframe",
    "link",
    "meta",
    "head",
    "template",
}

# Attributes worth keeping to help identify selectors.
_KEEP_ATTRS = ("id", "class", "itemprop", "data-testid", "role")


def strip_noise(html: str) -> HTMLParser:
    tree = HTMLParser(html)
    for tag in _NOISE_TAGS:
        for node in tree.css(tag):
            node.decompose()
    return tree


def _attrs_repr(node: Node) -> str:
    parts: list[str] = []
    for attr in _KEEP_ATTRS:
        val = node.attributes.get(attr)
        if val:
            # Truncate very long class lists to keep it compact.
            val = val if len(val) <= 80 else val[:77] + "..."
            parts.append(f'{attr}="{val}"')
    return (" " + " ".join(parts)) if parts else ""


def to_outline(html: str, max_chars: int = 12000) -> str:
    """Produce a compact indented outline of the page structure + text.

    This is what we feed to the LLM for selector generation.
    """
    tree = strip_noise(html)
    body = tree.body or tree.root
    lines: list[str] = []

    def walk(node: Node, depth: int) -> None:
        if node.tag is None or node.tag == "-text":
            return
        indent = "  " * depth
        own_text = _direct_text(node)
        text_part = f" :: {own_text}" if own_text else ""
        lines.append(f"{indent}<{node.tag}{_attrs_repr(node)}>{text_part}")
        for child in node.iter(include_text=False):
            walk(child, depth + 1)

    if body is not None:
        for child in body.iter(include_text=False):
            walk(child, 0)

    outline = "\n".join(lines)
    if len(outline) > max_chars:
        outline = outline[:max_chars] + "\n... [truncated]"
    return outline


def _direct_text(node: Node) -> str:
    """Text belonging directly to this node (not descendants), trimmed."""
    chunks: list[str] = []
    for child in node.iter(include_text=True):
        if child.tag == "-text":
            t = (child.text() or "").strip()
            if t:
                chunks.append(t)
    text = " ".join(chunks)
    text = " ".join(text.split())  # collapse whitespace
    return text if len(text) <= 120 else text[:117] + "..."
