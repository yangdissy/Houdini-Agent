"""Build the OF/SFX workflow knowledge base from the local HTML doc center."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_SOURCE = Path(r"U:\CG_VFX\sfxLib\Tutorials\特效流程引导\SFX_List\index.html")
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "Doc" / "of_doc"
LEGACY_OUTPUT = Path(__file__).resolve().parents[1] / "Doc" / "of_doc_knowledge_base.txt"
MAX_CHUNK_CHARS = 1800


@dataclass(frozen=True)
class Card:
    category_id: str
    category_title: str
    subcategory_title: Optional[str]
    card_id: str
    pid: str
    title: str
    body_html: str


@dataclass(frozen=True)
class BuildStats:
    card_count: int
    section_count: int
    file_count: int


class HtmlTextExtractor(HTMLParser):
    """Convert compact Confluence HTML snippets to readable plain text."""

    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "caption",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._list_stack: List[str] = []

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in {"img", "video", "source"}:
            attrs_dict = dict(attrs)
            alt = attrs_dict.get("alt") or attrs_dict.get("title")
            if alt:
                self._append(f"[媒体: {alt}]")
            return
        if tag in self._BLOCK_TAGS:
            self._newline()
        if tag == "li":
            self._append("- ")
        elif tag in {"td", "th"}:
            self._append(" | ")
        elif tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith("#"):
                self._append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._BLOCK_TAGS:
            self._newline()

    def handle_data(self, data: str) -> None:
        cleaned = unescape(data)
        if cleaned.strip():
            if self._parts and self._parts[-1].endswith("- "):
                cleaned = cleaned.lstrip()
            self._append(cleaned)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        raw = raw.replace("\xa0", " ")
        lines = []
        for line in raw.splitlines():
            line = re.sub(r"[ \t]+", " ", line).strip()
            line = re.sub(r"^\|\s*", "", line)
            line = re.sub(r"\s*\|$", "", line)
            line = re.sub(r"\s*\|\s*", " | ", line)
            line = re.sub(r"^#{1,6}\s+", "标题: ", line)
            if line:
                lines.append(line)
        return "\n".join(_dedupe_adjacent(lines))

    def _append(self, text: str) -> None:
        self._parts.append(text)

    def _newline(self) -> None:
        if self._parts and self._parts[-1].endswith("- "):
            return
        if self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")


def _dedupe_adjacent(lines: Iterable[str]) -> List[str]:
    result: List[str] = []
    previous = ""
    for line in lines:
        if line != previous:
            result.append(line)
        previous = line
    return result


def _extract_assignment(text: str, name: str, next_name: str) -> Any:
    del next_name
    match = re.search(rf"var\s+{re.escape(name)}\s*=\s*\[", text)
    if not match:
        raise ValueError(f"could not find JavaScript assignment for {name}")

    start = match.end() - 1
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "\"":
                in_string = False
            continue
        if char == "\"":
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : index + 1])

    raise ValueError(f"could not find end of JavaScript assignment for {name}")


def _html_to_text(html: str) -> str:
    parser = HtmlTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.get_text()


def _iter_cards(categories: Sequence[Dict[str, Any]]) -> Iterable[Card]:
    for category in categories:
        category_id = str(category.get("id", ""))
        category_title = str(category.get("title", "未分类"))
        for raw_card in category.get("cards", []):
            yield _make_card(category_id, category_title, None, raw_card)
        for subcategory in category.get("subCategories", []):
            subcategory_title = str(subcategory.get("title", "子分类"))
            for raw_card in subcategory.get("cards", []):
                yield _make_card(category_id, category_title, subcategory_title, raw_card)


def _make_card(
    category_id: str,
    category_title: str,
    subcategory_title: Optional[str],
    raw_card: Dict[str, Any],
) -> Card:
    return Card(
        category_id=category_id,
        category_title=category_title,
        subcategory_title=subcategory_title,
        card_id=str(raw_card.get("id", "")),
        pid=str(raw_card.get("pid", "")),
        title=str(raw_card.get("title", "未命名卡片")),
        body_html=str(raw_card.get("body", "")),
    )


def _split_body(text: str, max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    lines = text.splitlines()
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for line in lines:
        addition = len(line) + 1
        if current and current_len + addition > max_chars:
            chunks.append("\n".join(current).strip())
            current = []
            current_len = 0
        if len(line) > max_chars:
            chunks.extend(_split_long_line(line, max_chars))
            continue
        current.append(line)
        current_len += addition

    if current:
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _split_long_line(line: str, max_chars: int) -> List[str]:
    return [line[index : index + max_chars] for index in range(0, len(line), max_chars)]


def _format_card(card: Card) -> List[str]:
    category_path = card.category_title
    if card.subcategory_title:
        category_path = f"{category_path} / {card.subcategory_title}"
    body = _html_to_text(card.body_html)
    metadata = [
        f"分类: {category_path}",
        f"分类ID: {card.category_id}",
        f"卡片ID: {card.card_id}",
    ]
    if card.pid:
        metadata.append(f"Confluence PID: {card.pid}")
    metadata.append(f"来源锚点: #{card.card_id}")

    reserved_chars = sum(len(line) + 1 for line in metadata) + 16
    body_chunks = _split_body(body, max(800, MAX_CHUNK_CHARS - reserved_chars))
    if not body_chunks:
        body_chunks = ["无正文。"]

    sections: List[str] = []
    for index, body_chunk in enumerate(body_chunks, start=1):
        suffix = f" - Part {index}" if len(body_chunks) > 1 else ""
        title = f"## [{category_path}] {card.title}{suffix}"
        sections.append("\n".join([title, "", *metadata, "", body_chunk]).strip())
    return sections


def _format_training(phases: Sequence[Dict[str, Any]]) -> List[str]:
    sections: List[str] = []
    for phase in phases:
        title = str(phase.get("title", "未命名阶段"))
        steps = [str(step) for step in phase.get("steps", [])]
        body = ["分类: 新人培训模式", f"阶段ID: {phase.get('id', '')}", ""]
        body.extend(f"- {step}" for step in steps)
        sections.append("\n".join([f"## [新人培训模式] {title}", "", *body]).strip())
    return sections


def _format_header(title: str, source: Path, scope: str) -> str:
    lines = [
        f"# {title}",
        f"# 来源: {source}",
        f"# 生成日期: {date.today().isoformat()}",
        f"# 收录范围: {scope}",
        "# 媒体策略: 仅保留文字内容、分类、卡片 ID 与来源锚点，不复制图片或视频",
    ]
    return "\n".join(lines)


def _write_sections(path: Path, header: str, sections: Sequence[str]) -> None:
    path.write_text("\n\n".join([header, *sections]).strip() + "\n", encoding="utf-8")


def _write_index(
    output_dir: Path,
    source: Path,
    categories: Sequence[Dict[str, Any]],
    card_count: int,
    training_count: int,
) -> None:
    sections = [
        "## OF/SFX 流程文档索引\n\n"
        f"本目录由 SFX 流程文档中心生成，共收录 {card_count} 张卡片和 {training_count} 个新人培训阶段。\n\n"
        "分类文件:\n"
        + "\n".join(
            f"- {category.get('id', '')}.txt: {category.get('title', '未分类')}"
            for category in categories
        )
        + "\n- training.txt: 新人培训模式"
    ]
    header = _format_header(
        "OF/SFX 流程文档索引",
        source,
        f"整页 {card_count} 张卡片 + 新人培训模式 {training_count} 个阶段",
    )
    _write_sections(output_dir / "index.txt", header, sections)


def build_knowledge_base(source: Path, output_dir: Path) -> BuildStats:
    text = source.read_text(encoding="utf-8")
    categories = _extract_assignment(text, "CAT", "TRN")
    training_phases = _extract_assignment(text, "TRN", "curMode")

    output_dir.mkdir(parents=True, exist_ok=True)
    if LEGACY_OUTPUT.exists():
        LEGACY_OUTPUT.unlink()
    for stale_file in output_dir.glob("*.txt"):
        stale_file.unlink()

    cards_by_category: Dict[str, List[Card]] = {}
    category_titles: Dict[str, str] = {}
    for card in _iter_cards(categories):
        cards_by_category.setdefault(card.category_id, []).append(card)
        category_titles[card.category_id] = card.category_title

    section_count = 0
    file_count = 0
    for category in categories:
        category_id = str(category.get("id", ""))
        cards = cards_by_category.get(category_id, [])
        sections: List[str] = []
        for card in cards:
            sections.extend(_format_card(card))
        section_count += len(sections)
        header = _format_header(
            f"OF/SFX 流程文档 - {category_titles.get(category_id, category_id)}",
            source,
            f"{category_titles.get(category_id, category_id)}，{len(cards)} 张卡片",
        )
        _write_sections(output_dir / f"{category_id}.txt", header, sections)
        file_count += 1

    training_sections = _format_training(training_phases)
    section_count += len(training_sections)
    _write_sections(
        output_dir / "training.txt",
        _format_header("OF/SFX 新人培训模式", source, f"新人培训模式 {len(training_phases)} 个阶段"),
        training_sections,
    )
    file_count += 1

    card_count = sum(len(cards) for cards in cards_by_category.values())
    _write_index(output_dir, source, categories, card_count, len(training_phases))
    file_count += 1
    section_count += 1
    return BuildStats(card_count=card_count, section_count=section_count, file_count=file_count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Source SFX doc center HTML file.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output knowledge base directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = build_knowledge_base(args.source, args.output_dir)
    print(f"Wrote {args.output_dir}")
    print(f"Files: {stats.file_count}")
    print(f"Cards: {stats.card_count}")
    print(f"Knowledge sections: {stats.section_count}")


if __name__ == "__main__":
    main()