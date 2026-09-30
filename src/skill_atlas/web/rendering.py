"""Render repository Markdown as inert HTML with commit-pinned relative links."""

import posixpath
import re
from dataclasses import dataclass
from html import escape
from urllib.parse import quote, unquote, urljoin, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

from skill_atlas.application.documents import Document


@dataclass(frozen=True)
class RenderedDocument:
    frontmatter: str
    html: str


def render(document: Document) -> RenderedDocument:
    markdown = MarkdownIt("commonmark", {"html": False})
    match = re.match(r"\A---\r?\n.*?\r?\n---(?:\r?\n|\Z)", document.source, re.DOTALL)
    frontmatter = match[0] if match else ""
    body = document.source[len(frontmatter) :]
    tokens = markdown.parse(body)

    def links(items: list[Token]) -> None:
        for token in items:
            if token.type in ("link_open", "image"):
                value = str(token.attrGet("src" if token.type == "image" else "href") or "")
                href = urljoin(document.skill.url, value)
                parts = urlsplit(value)
                if parts.path and not parts.scheme and not parts.netloc:
                    directory = posixpath.dirname(document.skill.path)
                    path = posixpath.normpath(posixpath.join("/", directory, unquote(parts.path)))
                    href = (
                        f"{document.skill.repository.url}/blob/{document.skill.commit_sha}"
                        + quote(path, safe="/")
                        + (f"?{parts.query}" if parts.query else "")
                        + (f"#{parts.fragment}" if parts.fragment else "")
                    )
                # Fragment-only links stay within the rendered document.
                if value.startswith("#"):
                    href = value
                safe = urlsplit(href).scheme in ("http", "https", "mailto") or href.startswith("#")
                if token.type == "image":
                    label = escape(token.content or "Image")
                    token.type = "html_inline"
                    token.content = (
                        f'<a href="{escape(href, quote=True)}" rel="noreferrer">{label} (image)</a>'
                        if safe
                        else label
                    )
                    token.children = None
                else:
                    token.attrSet("href", href if safe else "#")
                    token.attrSet("rel", "noreferrer")
            if token.children:
                links(token.children)

    links(tokens)
    return RenderedDocument(frontmatter, markdown.renderer.render(tokens, markdown.options, {}))
