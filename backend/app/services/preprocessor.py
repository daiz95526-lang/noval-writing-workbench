"""文本预处理 — 清洗、分章、对话标注"""

import hashlib
import re
from pathlib import Path
from app.models.schemas import Chapter, ChapterMeta, CorpusStatus
from app.services.project_profile import get_project_profile


class TextPreprocessor:
    """文本预处理器 — 清洗网页噪声、按章节分割、标注对话"""

    # 常见章节标题模式
    CHAPTER_PATTERNS = [
        re.compile(r"^第[一二三四五六七八九十百千\d]+章\s+.+"),  # 第X章 标题（先匹配更具体的）
        re.compile(r"^第[一二三四五六七八九十百千\d]+[卷章节回]"),  # 第X卷/章/节/回
        re.compile(r"第[一二三四五六七八九十百千\d]+幕"),  # 第X幕，可出现在行内
        re.compile(r"^(序\s*幕|开\s*篇)(?:\s+.*)?$"),
        re.compile(r"^[Vv]olume\s*\d+"),  # Volume 1
        re.compile(r"^[第]?[一二三四五六七八九十\d]+\s*[卷幕]"),  # 第X卷/幕
        re.compile(r"^Chapter\s*\d+", re.IGNORECASE),  # Chapter 1
        re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩]"),  # ①
        re.compile(r"^[（(][一二三四五六七八九十\d]+[）)]"),  # （一）
    ]

    # HTML/噪声模式
    NOISE_PATTERNS = [
        re.compile(r"<[^>]+>"),  # HTML tags
        re.compile(r"&[a-z]+;"),  # HTML entities
        re.compile(r"请[记收]住[^。\n]*"),  # 请记住/请收藏本站域名
        re.compile(r"一秒记住[^。\n]*"),  # 一秒记住
        re.compile(r"天才一秒记住[^。\n]*"),  # 天才一秒记住
        re.compile(r"https?://\S+"),  # URLs
        re.compile(r"本章[共]?\d+字"),  # 本章XXX字
        re.compile(r"手机用户[^\n]*"),  # 手机用户请浏览
        re.compile(r"最新网址[^\n]*"),  # 最新网址
        re.compile(r"永久[地址域名][^\n]*"),  # 永久地址/域名
        re.compile(r"全本小说[^\n]*"),  # 全本小说
        re.compile(r"无弹窗[^\n]*"),  # 无弹窗
        re.compile(r"begins+(.*?)ends+", re.DOTALL),  # 广告标记区域
        re.compile(r"─{3,}"),  # 分隔线
        re.compile(r"={3,}"),  # 等号分隔
        re.compile(r"\*{3,}"),  # 星号分隔
        re.compile(r"^[　\s]*(广告|推广|推荐|更新|通知)[:：].*$", re.MULTILINE),  # 广告/推荐行
    ]

    # 过短无效段落最小长度
    MIN_PARAGRAPH_LENGTH = 5  # 少于5字的段落视为无效

    def clean_text(self, raw: str) -> str:
        """清洗文本：去HTML、广告、URL、无关噪声"""
        text = raw.strip()
        for pattern in self.NOISE_PATTERNS:
            text = pattern.sub("", text)
        # 规范化空白
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 去除首尾空白行
        text = text.strip()
        return text

    @staticmethod
    def _heading_number(line: str) -> str:
        match = re.search(r"第([一二三四五六七八九十百千\d]+)[章节幕回]", line)
        return match.group(1) if match else ""

    def _strip_toc_front_matter(self, text: str) -> str:
        """跳过目录页，避免把目录中的短标题当成正文标题。"""
        lines = text.splitlines()
        toc_index = next(
            (i for i, line in enumerate(lines[:500]) if re.fullmatch(r"\s*目\s*录\s*", line)),
            None,
        )
        if toc_index is None:
            return text

        for i in range(toc_index + 1, len(lines)):
            if re.fullmatch(r"\s*序\s*幕\s*", lines[i]):
                return "\n".join(lines[i:])

        first_heading_indexes = [
            i
            for i in range(toc_index + 1, len(lines))
            if self._heading_number(lines[i].strip()) in {"一", "1"}
        ]
        if len(first_heading_indexes) >= 2:
            return "\n".join(lines[first_heading_indexes[1]:])
        return text

    def split_chapters(self, text: str, volume_name: str = "") -> list[tuple[str, str]]:
        """将全文按章节标题分割，返回 [(章节标题, 章节正文), ...]"""
        text = self._strip_toc_front_matter(text)
        lines = text.split("\n")
        chapters: list[tuple[str, str]] = []
        current_title = ""
        current_lines: list[str] = []
        preamble_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_title:
                    current_lines.append("")
                continue

            is_heading = any(p.search(stripped) for p in self.CHAPTER_PATTERNS)
            if is_heading and (not current_title or len(stripped) < 40):
                if current_title and current_lines:
                    content = "\n".join(current_lines).strip()
                    if content:
                        chapters.append((current_title, content))
                elif not current_title:
                    preamble_lines = current_lines
                current_title = stripped
                current_lines = preamble_lines
                preamble_lines = []
            else:
                current_lines.append(stripped)

        if current_title and current_lines:
            content = "\n".join(current_lines).strip()
            if content:
                chapters.append((current_title, content))

        if not chapters and text.strip():
            chapters.append((volume_name or "未识别章节", text.strip()))
        return chapters

    def tag_dialogue(self, text: str) -> dict:
        """标注对话和叙述的比例和分布"""
        # 中文引号对话检测
        dialogue_pattern = re.compile(r'[“「"][^”」"]+[”」"]')
        dialogues = dialogue_pattern.findall(text)
        dialogue_chars = sum(len(d) for d in dialogues)
        total_chars = len(text.replace("\n", "").replace(" ", ""))

        # 检测内心独白（括号内的第一人称表达）
        inner_pattern = re.compile(r"[（(](?:我|他|她|路明非|楚子航)[^）)]*[）)]")
        inner_monologues = inner_pattern.findall(text)

        return {
            "dialogue_ratio": round(dialogue_chars / max(total_chars, 1), 4),
            "narration_ratio": round((total_chars - dialogue_chars) / max(total_chars, 1), 4),
            "dialogue_count": len(dialogues),
            "inner_monologue_count": len(inner_monologues),
            "avg_dialogue_length": round(dialogue_chars / max(len(dialogues), 1), 1),
        }

    # 卷名 → (display_name, series_order, sub_order) 映射
    VOLUME_DISPLAY_MAP: dict[str, tuple[str, int, str]] = {
        "00_前传_哀悼之翼": ("前传：哀悼之翼", 0, ""),
        "01_火之晨曦": ("龙族 I：火之晨曦", 1, ""),
        "02_悼亡者之瞳": ("龙族 II：悼亡者之瞳", 2, ""),
        "03A_黑月之潮_上": ("龙族 III：黑月之潮（上）", 3, "A"),
        "03B_黑月之潮_中": ("龙族 III：黑月之潮（中）", 3, "B"),
        "03C_黑月之潮_下": ("龙族 III：黑月之潮（下）", 3, "C"),
        "04_奥丁之渊": ("龙族 IV：奥丁之渊", 4, ""),
        "05_悼亡者的归来": ("龙族 V：悼亡者的归来", 5, ""),
    }

    def process(self, raw_text: str, volume_name: str = "") -> list[Chapter]:
        """完整预处理流水线：清洗 → 分章 → 标注"""
        cleaned = self.clean_text(raw_text)
        chapter_tuples = self.split_chapters(cleaned, volume_name)

        volume_map = self.VOLUME_DISPLAY_MAP if get_project_profile().legacy else {}
        display_name, series_order, sub_order = volume_map.get(
            volume_name,
            (volume_name, 0, ""),
        )

        result: list[Chapter] = []
        source_file = f"{volume_name}.txt" if volume_name else ""
        for idx, (title, content) in enumerate(chapter_tuples, start=1):
            dialogue_info = self.tag_dialogue(content)
            cid = f"{volume_name}-{idx:03d}" if volume_name else f"ch-{idx:03d}"
            content_hash = hashlib.sha256(
                re.sub(r"\s+", "", content).encode("utf-8")
            ).hexdigest()
            result.append(Chapter(
                chapter_id=cid,
                volume_key=volume_name,
                volume_display_name=display_name,
                series_order=series_order,
                sub_order=sub_order or None,
                chapter_order=idx,
                title=title,
                word_count=len(re.sub(r"\s+", "", content)),
                dialogue_ratio=dialogue_info["dialogue_ratio"],
                source_file=source_file,
                content_hash=content_hash,
                content=content,
                status=CorpusStatus.PROCESSED,
            ))
        return result


def preprocess_file(file_path: Path, volume_name: str = "") -> list[Chapter]:
    """便捷函数：从文件路径预处理文本"""
    raw = file_path.read_text(encoding="utf-8")
    preprocessor = TextPreprocessor()
    return preprocessor.process(raw, volume_name)
