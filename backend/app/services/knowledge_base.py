"""知识库构建引擎 — 从文本中提取角色、世界观、情节和主题"""

import asyncio
import json
from collections.abc import Callable
from anthropic import Anthropic
from app.config import settings
from app.services.model_policy import anthropic_client_options
from app.models.schemas import (
    Chapter,
    KnowledgeBase,
    CharacterProfile,
    WorldSetting,
    PlotNode,
    Theme,
)
from app.services.project_profile import get_project_profile

# ── 每批最大处理字数 ──
_BATCH_MAX_CHARS = 15000


class KnowledgeBaseExtractor:
    """知识库构建引擎 — 从小说文本中提取角色、世界观、情节和主题"""

    def __init__(self, model: str | None = None, max_tokens: int | None = None, thinking_budget: int | None = None):
        self._api_key = settings.anthropic_api_key
        base_url = settings.anthropic_base_url or None
        self._client = (
            Anthropic(
                api_key=self._api_key,
                base_url=base_url,
                **anthropic_client_options("knowledge_build"),
            )
            if self._api_key
            else None
        )
        self._model = model or settings.anthropic_model
        self._max_tokens = max_tokens or settings.anthropic_max_tokens
        self._thinking_budget = thinking_budget or settings.anthropic_thinking_budget

    async def extract(
        self,
        chapters: list[Chapter],
        selected_chapter_id: str | None = None,
        summary_only: bool = False,
        progress_callback: Callable[[float, str, str], None] | None = None,
        diagnostics: dict | None = None,
    ) -> KnowledgeBase:
        """分章分析风格并保留现有规则知识库。"""
        if not chapters:
            return KnowledgeBase()

        ordered, sample = self._select_sample(chapters, selected_chapter_id)
        if progress_callback:
            progress_callback(
                5,
                "读取章节",
                f"已读取 {len(ordered)} 章，按现有规则选取 {len(sample)} 章",
            )
        sample_text = "\n\n".join(
            f"## {chapter.volume_display_name} / {chapter.title}\n"
            f"{chapter.content[:2500]}"
            for chapter in sample
        )[:32_000]
        fallback = self._fallback_extract_all(sample_text, sample)
        if progress_callback:
            progress_callback(
                15,
                "提取规则",
                "角色、设定、情节和主题规则提取已完成",
            )

        from app.services.style_analyzer import (
            StyleAnalyzer,
            analyze_chapter_styles,
            summarize_global_style,
        )

        style_analyzer = StyleAnalyzer(
            model=self._model,
            max_tokens=settings.style_model_max_tokens,
            client=self._client,
        )
        entries, local_fallbacks, warnings, skipped = await analyze_chapter_styles(
            sample,
            analyzer=style_analyzer,
            summary_only=summary_only,
            progress_callback=progress_callback,
            diagnostics=diagnostics,
        )
        style_knowledge, summary_error = await summarize_global_style(
            entries,
            fallback_styles=local_fallbacks,
            analyzer=style_analyzer,
            warnings=warnings,
            skipped=skipped,
            progress_callback=progress_callback,
            diagnostics=diagnostics,
        )
        if progress_callback:
            progress_callback(
                94,
                "合并知识库",
                (
                    "章节缓存已保留，最终汇总失败，规则知识库仍可用"
                    if summary_error
                    else "正在合并章节风格与规则知识库"
                ),
            )

        return KnowledgeBase(
            characters=self._deduplicate_characters(fallback["characters"]),
            world_settings=self._deduplicate_world_settings(
                fallback["world_settings"]
            ),
            plot_nodes=self._deduplicate_plots(fallback["plots"]),
            themes=self._deduplicate_themes(fallback["themes"]),
            style_knowledge=style_knowledge,
        )

    def _select_sample(
        self,
        chapters: list[Chapter],
        selected_chapter_id: str | None,
    ) -> tuple[list[Chapter], list[Chapter]]:
        """保持原有按卷抽样与所选章节邻近抽样逻辑。"""
        ordered = sorted(
            chapters,
            key=lambda chapter: (
                chapter.series_order,
                chapter.sub_order or "",
                chapter.chapter_order,
            ),
        )
        by_volume: dict[str, list[Chapter]] = {}
        for chapter in ordered:
            by_volume.setdefault(chapter.volume_key, []).append(chapter)
        sample: list[Chapter] = []
        for volume_chapters in by_volume.values():
            sample.extend(volume_chapters[:2])
            sample.append(volume_chapters[-1])
        if selected_chapter_id:
            selected_index = next(
                (
                    index
                    for index, chapter in enumerate(ordered)
                    if chapter.chapter_id == selected_chapter_id
                ),
                None,
            )
            if selected_index is not None:
                start = max(0, selected_index - 1)
                sample.extend(ordered[start : start + 3])
        sample = list({chapter.chapter_id: chapter for chapter in sample}.values())
        return ordered, sample

    def _batch_chapters(self, chapters: list[Chapter]) -> list[str]:
        """将章节列表分批，每批不超过 _BATCH_MAX_CHARS 字"""
        batches: list[str] = []
        current_batch = ""
        for ch in chapters:
            text = ch.content
            if len(text) > settings.max_chapter_length:
                text = text[: settings.max_chapter_length]
            if len(current_batch) + len(text) > _BATCH_MAX_CHARS and current_batch:
                batches.append(current_batch)
                current_batch = text
            else:
                current_batch += "\n\n" + text if current_batch else text
        if current_batch:
            batches.append(current_batch)
        return batches

    async def _extract_batch(self, text: str, diagnostics: dict | None = None) -> dict:
        """Use one bounded model call to enrich all four KB sections."""
        if not self._client:
            return {}
        prompt = f"""
请从给定小说样本中提取知识库，只输出 JSON 对象：
{{
  "characters": [{{"name":"","aliases":[],"personality":"","speech_style":"","character_arc":"","key_quotes":[],"relationships":{{}}}}],
  "world_settings": [{{"category":"","name":"","description":"","related_characters":[]}}],
  "plots": [{{"volume":"","chapter_range":"","title":"","summary":"","is_foreshadowing":false,"is_resolved":true,"related_nodes":[]}}],
  "themes": [{{"name":"","description":"","typical_scenes":[],"key_passages":[]}}]
}}
没有可靠信息的字段使用空字符串或空数组，不要虚构。

小说样本：
{text}
"""
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.messages.create,
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system="你是文学知识库抽取助手，只输出有效 JSON。",
                    messages=[{"role": "user", "content": prompt}],
                    timeout=settings.model_timeout_seconds,
                ),
                timeout=settings.model_timeout_seconds,
            )
            parsed = _parse_json_object_response(_response_text(response))
            if not parsed and diagnostics is not None:
                diagnostics["last_error"] = ValueError("模型返回 JSON 解析失败")
            return parsed
        except Exception as exc:
            if diagnostics is not None:
                diagnostics["last_error"] = exc
            return {}

    async def _extract_with_prompt(self, text: str, prompt: str) -> list[dict]:
        """用指定提示词调用 Claude 提取结构化数据"""
        system_prompt = (
            "你是一位专业的文学分析专家。请严格按照要求的 JSON 格式输出提取结果。"
            "只输出 JSON，不要有其他内容。如果文本中没有相关信息，输出空数组 []。"
        )
        if not self._client:
            return []  # 无 API key，将使用回退提取
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.messages.create,
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": f"{prompt}\n\n{text}"}],
                    timeout=settings.model_timeout_seconds,
                ),
                timeout=settings.model_timeout_seconds,
            )
            content = _response_text(response)
            return _parse_json_response(content)
        except Exception:
            return []

    # ── 回退提取（无 API 时基于规则的提取） ──

    def _fallback_extract_all(
        self,
        combined_text: str,
        chapters: list[Chapter],
    ) -> dict:
        """基于规则的回退提取，不依赖 Claude API"""
        return {
            "characters": self._fallback_characters(combined_text),
            "world_settings": self._fallback_world_settings(combined_text),
            "plots": self._fallback_plots_from_chapters(chapters),
            "themes": self._fallback_themes(combined_text),
        }

    def _fallback_characters(self, text: str) -> list[dict]:
        """基于规则提取角色名"""
        import re
        if not get_project_profile().legacy:
            return []
        # 龙族已知角色（关键词匹配）
        known_names = [
            "路明非", "楚子航", "凯撒", "陈墨瞳", "诺诺", "夏弥", "苏茜",
            "昂热", "副校长", "曼斯", "施耐德", "古德里安",
            "源稚生", "源稚女", "矢吹樱", "绘梨衣", "上杉越",
            "路鸣泽", "芬格尔", "帕西", "酒德麻衣", "苏恩曦",
            "零", "兰斯洛特", "守夜人",
        ]
        found: list[dict] = []
        for name in known_names:
            count = text.count(name)
            if count >= 3:  # 至少出现3次
                found.append({"name": name, "aliases": [], "personality": "", "speech_style": "", "character_arc": "", "key_quotes": [], "relationships": {}, "mention_count": count})
        # 按出现次数降序
        found.sort(key=lambda x: x.get("mention_count", 0), reverse=True)
        return found

    def _fallback_world_settings(self, text: str) -> list[dict]:
        """基于规则提取世界观设定"""
        import re
        if not get_project_profile().legacy:
            return []
        settings_list = [
            ("organization", "卡塞尔学院", "培养混血种的精英学院"),
            ("organization", "密党", "管理混血种的古老组织"),
            ("organization", "执行部", "卡塞尔学院的行动部门"),
            ("organization", "装备部", "卡塞尔学院的技术研发部门"),
            ("organization", "蛇岐八家", "日本混血种八大家族"),
            ("organization", "猛鬼众", "日本混血种反派组织"),
            ("power_system", "言灵", "混血种的天赋能力体系"),
            ("power_system", "炼金术", "龙族古代科技"),
            ("species", "混血种", "人类与龙族的混血后代"),
            ("species", "龙族", "远古的神秘种族"),
            ("species", "死侍", "失去理智的混血种"),
            ("location", "卡塞尔学院", "位于美国的混血种学院"),
            ("location", "东京", "龙族III主要舞台"),
            ("location", "北京", "龙族故事起点之一"),
            ("rule", "血之哀", "混血种与生俱来的孤独感"),
        ]
        found = []
        for cat, name, desc in settings_list:
            if name in text:
                found.append({"category": cat, "name": name, "description": desc, "related_characters": []})
        return found

    def _fallback_plots(self, text: str) -> list[dict]:
        """基于规则提取情节节点（从章节标题）"""
        import re
        # 提取以"第X章"开头的行作为情节节点
        chapter_pattern = re.compile(r'^第[一二三四五六七八九十百千\d]+[章节幕](.+)', re.MULTILINE)
        matches = chapter_pattern.findall(text)
        plots = []
        for i, title in enumerate(matches[:50]):
            title = title.strip()
            if title:
                plots.append({
                    "volume": "",
                    "chapter_range": str(i + 1),
                    "title": title[:50],
                    "summary": title,
                    "is_foreshadowing": False,
                    "is_resolved": True,
                    "related_nodes": [],
                })
        return plots

    def _fallback_plots_from_chapters(self, chapters: list[Chapter]) -> list[dict]:
        return [
            {
                "volume": chapter.volume_display_name,
                "chapter_range": str(chapter.chapter_order),
                "title": chapter.title[:50],
                "summary": f"{chapter.volume_display_name}中的章节：{chapter.title}",
                "is_foreshadowing": False,
                "is_resolved": True,
                "related_nodes": [],
            }
            for chapter in chapters[:50]
            if chapter.title
        ]

    def _fallback_themes(self, text: str) -> list[dict]:
        """基于规则提取主题关键词"""
        themes_map = {
            "孤独": ["孤独", "寂寞", "一个人", "空荡", "无人"],
            "命运": ["命运", "宿命", "注定", "被选中", "使命"],
            "热血": ["战斗", "爆发", "守护", "为了", "决不"],
            "牺牲": ["牺牲", "死亡", "消失", "离开", "付出生命"],
            "成长": ["成长", "改变", "不再是", "学会", "懂得"],
            "羁绊": ["朋友", "同伴", "兄弟", "队友", "约定"],
            "悲剧": ["悲伤", "眼泪", "失去", "无法挽回", "遗憾"],
            "复仇": ["复仇", "报仇", "仇恨", "报复"],
            "救赎": ["拯救", "救赎", "赎罪", "弥补"],
            "衰仔逆袭": ["废物", "没用", "我不是", "原来我", "我也可以"],
        }
        if not get_project_profile().legacy:
            themes_map.pop("衰仔逆袭", None)
        found = []
        for theme_name, keywords in themes_map.items():
            score = sum(text.count(kw) for kw in keywords)
            if score >= 5:
                found.append({
                    "name": theme_name,
                    "description": f"通过关键词频率检测到，匹配度: {score}",
                    "typical_scenes": [],
                    "key_passages": [],
                })
        found.sort(key=lambda x: sum(text.count(kw) for kw in themes_map.get(x["name"], [])), reverse=True)
        return found

    # ── 去重与合并 ──

    def _deduplicate_characters(self, raw_list: list[dict]) -> list[CharacterProfile]:
        """按 name 去重合并角色信息"""
        merged: dict[str, CharacterProfile] = {}
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            if not name:
                continue
            if name in merged:
                existing = merged[name]
                existing.aliases = list(set(existing.aliases + item.get("aliases", [])))
                if item.get("personality") and len(item["personality"]) > len(existing.personality or ""):
                    existing.personality = item["personality"]
                if item.get("speech_style") and len(item["speech_style"]) > len(existing.speech_style or ""):
                    existing.speech_style = item["speech_style"]
                if item.get("character_arc"):
                    existing.character_arc = item["character_arc"]
                existing.key_quotes = list(set(existing.key_quotes + item.get("key_quotes", [])))
                existing.relationships.update(item.get("relationships", {}))
            else:
                merged[name] = CharacterProfile(
                    name=name,
                    aliases=item.get("aliases", []),
                    personality=item.get("personality", ""),
                    speech_style=item.get("speech_style", ""),
                    character_arc=item.get("character_arc", ""),
                    key_quotes=item.get("key_quotes", []),
                    relationships=item.get("relationships", {}),
                )
        return list(merged.values())

    def _deduplicate_world_settings(self, raw_list: list[dict]) -> list[WorldSetting]:
        """按 name + category 去重合并世界观设定"""
        seen: set[tuple[str, str]] = set()
        result: list[WorldSetting] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            key = (item.get("name", ""), item.get("category", ""))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            result.append(WorldSetting(
                category=item.get("category", ""),
                name=item.get("name", ""),
                description=item.get("description", ""),
                related_characters=item.get("related_characters", []),
            ))
        return result

    def _deduplicate_plots(self, raw_list: list[dict]) -> list[PlotNode]:
        """按 title 去重合并情节节点"""
        seen: set[str] = set()
        result: list[PlotNode] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "")
            if not title or title in seen:
                continue
            seen.add(title)
            result.append(PlotNode(
                volume=item.get("volume", ""),
                chapter_range=item.get("chapter_range", ""),
                title=title,
                summary=item.get("summary", ""),
                is_foreshadowing=item.get("is_foreshadowing", False),
                is_resolved=item.get("is_resolved", True),
                related_nodes=item.get("related_nodes", []),
            ))
        return result

    def _deduplicate_themes(self, raw_list: list[dict]) -> list[Theme]:
        """按 name 去重合并主题"""
        merged: dict[str, Theme] = {}
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            if not name:
                continue
            if name in merged:
                existing = merged[name]
                existing.typical_scenes = list(set(existing.typical_scenes + item.get("typical_scenes", [])))
                existing.key_passages = list(set(existing.key_passages + item.get("key_passages", [])))
                if item.get("description") and len(item["description"]) > len(existing.description):
                    existing.description = item["description"]
            else:
                merged[name] = Theme(
                    name=name,
                    description=item.get("description", ""),
                    typical_scenes=item.get("typical_scenes", []),
                    key_passages=item.get("key_passages", []),
                )
        return list(merged.values())


def _parse_json_response(content: str) -> list[dict]:
    """从 Claude 响应中解析 JSON 数组"""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        content = "\n".join(lines)
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return parsed
        return []
    except json.JSONDecodeError:
        return []


def _parse_json_object_response(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        lines = [line for line in content.splitlines() if not line.startswith("```")]
        content = "\n".join(lines)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        key: value if isinstance(value, list) else []
        for key, value in parsed.items()
        if key in {"characters", "world_settings", "plots", "themes"}
    }


def _response_text(response) -> str:
    text = "\n".join(
        block.text
        for block in getattr(response, "content", [])
        if isinstance(getattr(block, "text", None), str)
        and block.text.strip()
    ).strip()
    if not text:
        raise ValueError("模型返回无文本内容")
    return text


# ── 模块级包装函数（兼容 router 现有 import） ──

async def build_kb(
    chapters: list[Chapter],
    selected_chapter_id: str | None = None,
    summary_only: bool = False,
    progress_callback: Callable[[float, str, str], None] | None = None,
    diagnostics: dict | None = None,
) -> KnowledgeBase:
    """从章节列表构建知识库"""
    extractor = KnowledgeBaseExtractor()
    return await extractor.extract(
        chapters,
        selected_chapter_id=selected_chapter_id,
        summary_only=summary_only,
        progress_callback=progress_callback,
        diagnostics=diagnostics,
    )
