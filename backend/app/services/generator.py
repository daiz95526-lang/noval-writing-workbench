"""续写生成引擎 — 基于风格特征和知识库生成风格一致的章节续写"""

import asyncio
import math
import re
from dataclasses import dataclass
from collections.abc import Callable
from typing import AsyncIterator
from anthropic import Anthropic
from app.config import settings
from app.models.schemas import (
    Chapter,
    KnowledgeBase,
    GenerationRequest,
    GenerationResult,
)
from app.services.chapter_quality import (
    EndingResolution,
    ensure_complete_ending,
    remove_duplicate_paragraphs,
    sentence_is_complete,
)
from app.services.model_response_parser import parse_model_json_response
from app.prompts.generation import (
    CHAPTER_GENERATION_PROMPT,
    FULL_REWRITE_PROMPT,
    LOCAL_EDIT_PROMPT,
    STYLE_SYSTEM_PROMPT,
)

# ── 未分析时使用的默认风格描述 ──

_DEFAULT_STYLE = {
    "lexical_features": "- 语言口语化，保留青年人的自嘲和少量流行文化比喻",
    "syntactic_features": "- 长短句交替\n- 段落简短，关键情绪用短句收束",
    "rhetorical_features": "- 使用游戏或电影化比喻，但避免连续堆砌",
    "narrative_features": "- 采用贴近人物的第三人称视角",
    "dialogue_features": "- 对话简短，并保持角色声音差异",
    "emotional_features": "- 悲伤与幽默形成反差\n- 紧张场景中允许一次克制的吐槽",
}

_MAX_CHAPTER_CONTEXT_CHARS = 3500
_LIGHT_GENERATION_MAX_WORDS = 800

ProgressCallback = Callable[[float, str, str], None]
SegmentCallback = Callable[[int, int, str, int], None]
EndingCallback = Callable[[EndingResolution], None]


@dataclass(frozen=True)
class RevisionDiagnostics:
    revision_mode: str
    original_word_count: int
    revised_word_count: int
    length_ratio: float
    change_level: str
    requires_confirmation: bool
    revision_failed: bool
    warning: str = ""


RevisionCallback = Callable[[RevisionDiagnostics], None]


class GenerationServiceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        partial_text: str = "",
        current_segment: int = 0,
        total_segments: int = 0,
        system_prompt: str = "",
    ) -> None:
        super().__init__(message)
        self.partial_text = partial_text
        self.current_segment = current_segment
        self.total_segments = total_segments
        self.system_prompt = system_prompt


class ContinuationGenerator:
    """续写生成引擎 — 基于风格特征和知识库生成《龙族》风格续写"""

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        progress_callback: ProgressCallback | None = None,
        segment_callback: SegmentCallback | None = None,
        ending_callback: EndingCallback | None = None,
        revision_callback: RevisionCallback | None = None,
    ):
        self._api_key = settings.anthropic_api_key
        base_url = settings.anthropic_base_url or None
        self._client = (
            Anthropic(
                api_key=self._api_key,
                base_url=base_url,
                max_retries=0,
            )
            if self._api_key
            else None
        )
        self._model = model or settings.anthropic_model
        configured_max_tokens = max_tokens or settings.generation_max_tokens
        self._max_tokens = min(
            configured_max_tokens,
            settings.generation_segment_max_tokens,
        )
        self._timeout_seconds = settings.generation_timeout_seconds
        self._prompt_max_chars = settings.generation_prompt_max_chars
        self._thinking_budget = thinking_budget or settings.anthropic_thinking_budget
        self._progress_callback = progress_callback
        self._segment_callback = segment_callback
        self._ending_callback = ending_callback
        self._revision_callback = revision_callback
        self._revision_max_tokens = max(
            self._max_tokens,
            settings.chapter_repair_max_tokens,
        )
        self._revision_prompt_max_chars = max(
            self._prompt_max_chars,
            settings.chapter_review_prompt_max_chars,
        )

    def _report(self, progress: float, stage: str, message: str) -> None:
        if self._progress_callback:
            self._progress_callback(progress, stage, message)

    def _require_api(self) -> None:
        if not self._client:
            raise GenerationServiceError(
                "未配置 API Key，请在 backend/.env 或系统环境变量中配置"
            )

    # ── 公开接口 ──

    async def generate(
        self,
        chapter: Chapter,
        kb: KnowledgeBase,
        request: GenerationRequest,
        *,
        draft_content: str = "",
        previous_draft_content: str = "",
        planning_context: str = "",
        reference_chapters: list[Chapter] | None = None,
    ) -> tuple[str, str]:
        """生成续写章节，返回 (正文, system_prompt)"""
        self._require_api()
        references = (reference_chapters or [])[:2]
        total_segments = self._segment_count(request.target_word_count)
        partial_parts: list[str] = []
        latest_system_prompt = ""
        self._report(
            32,
            "正在规划分段",
            (
                "短片段将单次生成"
                if total_segments == 1
                else f"章节草稿已拆分为 {total_segments} 段，每段独立限时"
            ),
        )

        for segment_index in range(1, total_segments + 1):
            segment_start_progress = (
                34 + (segment_index - 1) / total_segments * 54
            )
            segment_end_progress = 34 + segment_index / total_segments * 54
            generated_words = sum(_word_count(item) for item in partial_parts)
            remaining_words = max(1, request.target_word_count - generated_words)
            remaining_segments = total_segments - segment_index + 1
            segment_target = max(
                300,
                min(
                    settings.generation_segment_target_words,
                    math.ceil(remaining_words / remaining_segments),
                ),
            )
            segment_request = request.model_copy(
                update={"target_word_count": segment_target}
            )
            self._report(
                segment_start_progress,
                f"正在生成第 {segment_index}/{total_segments} 段",
                f"当前段目标约 {segment_target} 字，正在组装提示词",
            )
            system_prompt = self._build_system_prompt(kb, segment_request)
            user_prompt = self._build_segment_prompt(
                chapter=chapter,
                request=segment_request,
                segment_index=segment_index,
                total_segments=total_segments,
                draft_content=draft_content,
                previous_draft_content=previous_draft_content,
                planning_context=planning_context,
                partial_text="\n\n".join(partial_parts),
                reference_chapters=references,
            )
            system_prompt, user_prompt, prompt_truncated = self._limit_prompts(
                system_prompt,
                user_prompt,
            )
            latest_system_prompt = system_prompt
            prompt_chars = len(system_prompt) + len(user_prompt)
            truncation_note = "，已自动截断" if prompt_truncated else ""
            self._report(
                min(segment_end_progress - 2, segment_start_progress + 2),
                f"正在生成第 {segment_index}/{total_segments} 段",
                f"Prompt 字符数：{prompt_chars}{truncation_note}",
            )
            self._report(
                min(segment_end_progress - 1, segment_start_progress + 3),
                "正在调用模型",
                f"正在调用模型生成第 {segment_index}/{total_segments} 段，目标约 {segment_target} 字",
            )
            max_tokens = (
                min(self._max_tokens, 800)
                if total_segments == 1
                else min(
                    settings.generation_segment_max_tokens,
                    max(900, segment_target * 2),
                )
            )
            try:
                segment = await self._generate_draft(
                    system_prompt,
                    user_prompt,
                    "",
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                message = (
                    str(exc)
                    if isinstance(exc, GenerationServiceError)
                    else f"模型生成失败 ({type(exc).__name__}): {exc}"
                )
                raise GenerationServiceError(
                    message,
                    partial_text="\n\n".join(partial_parts),
                    current_segment=segment_index,
                    total_segments=total_segments,
                    system_prompt=latest_system_prompt,
                ) from exc
            if not segment.strip():
                raise GenerationServiceError(
                    "模型返回了空正文",
                    partial_text="\n\n".join(partial_parts),
                    current_segment=segment_index,
                    total_segments=total_segments,
                    system_prompt=latest_system_prompt,
                )
            segment_ending = await self._ensure_complete_ending(
                segment.strip(),
                system_prompt,
                final_segment=segment_index == total_segments,
                allow_model_repair=request.generation_kind == "full_chapter",
                repair_progress=max(
                    segment_start_progress + 3.5,
                    segment_end_progress - 0.5,
                ),
            )
            segment = segment_ending.text
            partial_parts.append(segment)
            partial_text = "\n\n".join(partial_parts)
            if self._segment_callback:
                self._segment_callback(
                    segment_index,
                    total_segments,
                    partial_text,
                    prompt_chars,
                )
            self._report(
                segment_end_progress,
                f"已完成第 {segment_index}/{total_segments} 段",
                f"第 {segment_index} 段已追加到临时结果，当前共 {_word_count(partial_text)} 字",
            )

        draft = remove_duplicate_paragraphs("\n\n".join(partial_parts))
        if not draft.strip():
            raise GenerationServiceError("模型返回了空正文")
        self._report(88, "正在检查断句", "正在检查最后一句和引号是否完整")
        draft_ending = await self._ensure_complete_ending(
            draft,
            latest_system_prompt,
            final_segment=True,
            allow_model_repair=request.generation_kind == "full_chapter",
            repair_progress=89,
        )
        draft = draft_ending.text
        self._report(90, "正在检查章节完整性", "正文已完整拼接，正在执行章节检查")
        return draft, latest_system_prompt

    async def generate_stream(self, chapter: Chapter, kb: KnowledgeBase, request: GenerationRequest) -> AsyncIterator[str]:
        """流式生成续写章节，逐 chunk yield"""
        self._require_api()
        system_prompt = self._build_system_prompt(kb, request)
        user_prompt = self._build_user_prompt(chapter, request)

        outline = await self._generate_outline(system_prompt, user_prompt)
        async for chunk in self._generate_draft_stream(system_prompt, user_prompt, outline):
            yield chunk

    async def iterate(
        self,
        previous_result: GenerationResult,
        feedback: str,
        target_section: str,
        kb: KnowledgeBase,
        *,
        current_text: str = "",
        revision_mode: str = "local_edit",
    ) -> tuple[str, str]:
        """根据用户反馈修改已生成章节，返回 (修改后正文, system_prompt)"""
        self._require_api()
        original_content = current_text.strip() or previous_result.content.strip()
        if not original_content:
            raise GenerationServiceError("当前没有可修改的完整章节正文")
        revision_mode = (
            revision_mode
            if revision_mode in {"local_edit", "full_rewrite"}
            else "local_edit"
        )
        system_prompt = previous_result.system_prompt_used or "你是严谨的中文小说文本编辑器。"

        additional = previous_result.request.additional_instructions or ""
        if revision_mode == "local_edit":
            content, prompt_chars, prompt_truncated = await self._iterate_local_edit(
                original_content,
                feedback,
                target_section,
                additional,
            )
            used_system_prompt = "你是严谨的中文小说文本编辑器，只执行可回填的局部编辑。"
        else:
            content, used_system_prompt, prompt_chars, prompt_truncated = (
                await self._iterate_full_rewrite(
                    original_content,
                    feedback,
                    target_section,
                    additional,
                    system_prompt,
                )
            )

        self._report(
            72,
            "提示词已组装",
            (
                f"Prompt 字符数：{prompt_chars}"
                + ("，已自动截断" if prompt_truncated else "")
            ),
        )

        if not content.strip():
            raise GenerationServiceError("模型返回了空迭代结果")
        content_ending = await self._ensure_complete_ending(
            remove_duplicate_paragraphs(content),
            used_system_prompt,
            final_segment=True,
            allow_model_repair=True,
            repair_progress=87,
        )
        content = content_ending.text
        diagnostics = _revision_diagnostics(
            original_content,
            content,
            feedback,
            revision_mode,
        )
        if self._revision_callback:
            self._revision_callback(diagnostics)
        self._report(88, "正在解析模型结果", "修改后的正文已返回")
        return content, used_system_prompt

    async def _iterate_local_edit(
        self,
        original_content: str,
        feedback: str,
        target_section: str,
        additional: str,
    ) -> tuple[str, int, bool]:
        self._report(45, "正在组装局部编辑请求", "正在准备完整原文和可回填编辑规则")
        source = _revision_source_excerpt(
            original_content,
            target_section,
            self._revision_prompt_max_chars - 3500,
        )
        user_prompt = LOCAL_EDIT_PROMPT.format(
            feedback=feedback,
            target_section=target_section or "未指定，请仅做必要的局部修改",
            original_content=source,
            additional_instructions=f"补充要求：{additional}" if additional else "",
        )
        system_prompt = "你是严谨的中文小说文本编辑器，只返回可回填的 JSON 编辑操作。"
        system_prompt, user_prompt, truncated = self._limit_revision_prompts(
            system_prompt,
            user_prompt,
        )
        self._report(60, "正在调用模型", "正在请求模型生成局部替换操作")
        raw = await self._call_revision_model(
            system_prompt,
            user_prompt,
            max_tokens=min(2400, self._revision_max_tokens),
        )
        payload, _, error = parse_model_json_response(raw)
        if payload is None:
            raise GenerationServiceError(
                error or "局部修改未返回可应用的编辑操作，原文已保留"
            )
        revised, applied = _apply_revision_edits(original_content, payload.get("edits"))
        if applied == 0:
            raise GenerationServiceError(
                "模型没有返回能在原文中精确定位的修改，原文已保留"
            )
        return revised, len(system_prompt) + len(user_prompt), truncated

    async def _iterate_full_rewrite(
        self,
        original_content: str,
        feedback: str,
        target_section: str,
        additional: str,
        system_prompt: str,
    ) -> tuple[str, str, int, bool]:
        self._report(45, "正在组装整章重写请求", "正在准备完整原文和篇幅保护规则")
        user_prompt = FULL_REWRITE_PROMPT.format(
            feedback=feedback,
            target_section=target_section or "全文",
            original_content=original_content,
            additional_instructions=f"补充要求：{additional}" if additional else "",
        )
        system_prompt, user_prompt, truncated = self._limit_revision_prompts(
            system_prompt,
            user_prompt,
        )
        self._report(60, "正在调用模型", "正在请求模型输出完整修改版章节")
        content = await self._call_revision_model(
            system_prompt,
            user_prompt,
            max_tokens=self._revision_max_tokens,
        )
        return content, system_prompt, len(system_prompt) + len(user_prompt), truncated

    async def _call_revision_model(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
    ) -> str:
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.messages.create,
                    model=self._model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    timeout=self._timeout_seconds,
                ),
                timeout=self._timeout_seconds,
            )
            return _response_text(response)
        except Exception as exc:
            raise GenerationServiceError(
                f"模型迭代失败 ({type(exc).__name__}): {exc}"
            ) from exc

    def _limit_revision_prompts(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, str, bool]:
        max_chars = self._revision_prompt_max_chars
        truncated = False
        if len(system_prompt) > 3000:
            system_prompt = _truncate_middle(system_prompt, 3000)
            truncated = True
        remaining = max(2000, max_chars - len(system_prompt))
        if len(user_prompt) > remaining:
            user_prompt = _truncate_middle(user_prompt, remaining)
            truncated = True
        return system_prompt, user_prompt, truncated

    async def _ensure_complete_ending(
        self,
        text: str,
        system_prompt: str,
        *,
        final_segment: bool,
        allow_model_repair: bool,
        repair_progress: float,
    ) -> EndingResolution:
        clean = text.rstrip()
        if sentence_is_complete(clean):
            return self._finish_ending(
                EndingResolution(clean, "ok"),
                final_segment=final_segment,
            )

        repaired = ""
        if allow_model_repair:
            self._report(
                repair_progress,
                "正在修复断句",
                "检测到末句未完成，正在请求模型只补完最后一句",
            )
            tail = clean[-700:]
            prompt = (
                "下面文字的最后一句被截断。请只输出从截断处继续所需的最短文字，"
                "补完当前句子并以正常中文结束标点收尾。不要重复已有文字，不要扩写新剧情，"
                "不要解释。\n\n"
                f"末尾文字：\n{tail}"
            )
            try:
                supplement = await self._generate_draft(
                    system_prompt,
                    prompt,
                    "",
                    max_tokens=220,
                )
                supplement = supplement.strip()
                repaired = clean + supplement
                if not supplement:
                    repaired = ""
            except Exception:
                repaired = ""

        resolution = ensure_complete_ending(clean, repaired_text=repaired)
        if resolution.status == "failed":
            if not allow_model_repair and clean:
                resolution = EndingResolution(
                    clean,
                    "partial",
                    "追加片段末句可能不完整，已保留，可继续生成或手动收束。",
                )
                return self._finish_ending(
                    resolution,
                    final_segment=final_segment,
                )
            raise GenerationServiceError(
                "模型正文过短，且自动补句和安全截断均未成功",
                partial_text=clean,
            )
        return self._finish_ending(
            resolution,
            final_segment=final_segment,
        )

    def _finish_ending(
        self,
        resolution: EndingResolution,
        *,
        final_segment: bool,
    ) -> EndingResolution:
        if final_segment and self._ending_callback:
            self._ending_callback(resolution)
        return resolution

    # ── Prompt 构建 ──

    def _build_system_prompt(self, kb: KnowledgeBase, request: GenerationRequest) -> str:
        """组装完整 system prompt，融合风格规则和知识库信息"""
        # 角色状态描述
        character_states = self._format_character_states(kb)
        if not character_states:
            character_states = "- 保持各角色性格和状态与上文一致"

        # 剧情方向
        plot_direction = request.plot_direction or "自由发挥"

        # 使用默认风格特征（后续可从 StyleProfile 动态填充）
        return STYLE_SYSTEM_PROMPT.format(
            lexical_features=_DEFAULT_STYLE["lexical_features"],
            syntactic_features=_DEFAULT_STYLE["syntactic_features"],
            rhetorical_features=_DEFAULT_STYLE["rhetorical_features"],
            narrative_features=_DEFAULT_STYLE["narrative_features"],
            dialogue_features=_DEFAULT_STYLE["dialogue_features"],
            emotional_features=_DEFAULT_STYLE["emotional_features"],
            target_words=request.target_word_count,
            character_states=character_states,
        )

    def _build_user_prompt(self, chapter: Chapter, request: GenerationRequest) -> str:
        """组装 user prompt，包含上文内容和用户指令"""
        # 构建上文摘要：取章节末尾部分作为衔接上下文
        context_text = chapter.content
        if len(context_text) > _MAX_CHAPTER_CONTEXT_CHARS:
            context_text = context_text[-_MAX_CHAPTER_CONTEXT_CHARS:]

        context = f"## 接续章节（末尾内容）\n\n{context_text}\n\n---\n请从以上内容结束处继续写下去。"

        plot_direction = ""
        if request.plot_direction:
            plot_direction = f"## 用户指定的剧情方向\n\n{request.plot_direction}"

        additional = ""
        if request.additional_instructions:
            additional = f"## 补充说明\n\n{request.additional_instructions}"

        pov = ""
        if request.pov_character:
            pov = f"本章主要视角角色：{request.pov_character}"

        return CHAPTER_GENERATION_PROMPT.format(
            context=context,
            plot_direction=plot_direction,
            additional_instructions="\n".join(filter(None, [pov, additional])),
        )

    def _build_segment_prompt(
        self,
        *,
        chapter: Chapter,
        request: GenerationRequest,
        segment_index: int,
        total_segments: int,
        draft_content: str,
        previous_draft_content: str,
        planning_context: str,
        partial_text: str,
        reference_chapters: list[Chapter],
    ) -> str:
        anchor_context = _compact_anchor(chapter.content)
        existing_tail = (draft_content + "\n\n" + partial_text).strip()
        existing_tail = existing_tail[-settings.generation_draft_tail_chars :]
        previous_draft_tail = previous_draft_content.strip()[-1600:]
        previous_summary = _compact_segment_summary(partial_text)
        reference_lines = []
        for item in reference_chapters[:2]:
            reference_lines.append(
                f"### {item.title}\n{_truncate_middle(item.content, 600)}"
            )
        sections = [
            (
                planning_context
                if planning_context
                else "## 项目规划\n（尚未填写项目总纲或章节规划）"
            ),
            f"## 起始章节摘要或截断正文\n{anchor_context}",
            (
                f"## 上一章草稿结尾\n{previous_draft_tail}"
                if previous_draft_tail
                else "## 上一章草稿结尾\n（无可用的上一章草稿）"
            ),
            (
                f"## 当前草稿末尾\n{existing_tail}"
                if existing_tail
                else "## 当前草稿末尾\n（尚无草稿正文）"
            ),
            (
                f"## 上一段摘要\n{previous_summary}"
                if previous_summary
                else "## 上一段摘要\n（这是第一段）"
            ),
        ]
        if reference_lines:
            sections.append("## 参考章节片段\n" + "\n\n".join(reference_lines))
        if request.plot_direction:
            sections.append(f"## 剧情方向\n{request.plot_direction}")
        if request.pov_character:
            sections.append(f"## 视角角色\n{request.pov_character}")
        if request.additional_instructions:
            sections.append(f"## 补充要求\n{request.additional_instructions}")
        ending_instruction = (
            "这是最后一段，请完成 ending_state，自然收束本章并明确引向 next_bridge。"
            if segment_index == total_segments
            else "这是章节中段，不要总结或仓促收尾，要用完整句自然留下下一段的衔接点。"
        )
        sections.append(
            "## 本次任务\n"
            f"生成第 {segment_index}/{total_segments} 段，约 {request.target_word_count} 字。"
            f"{ending_instruction}\n"
            "这是连续小说工程中的当前章节：必须服务于本章目标，推进情节点和章节功能；"
            "按要求埋下或回收伏笔，结尾服务于章末钩子，不要一次性解决全部冲突。"
            "\n每段必须以完整句子和正常中文标点结束，不得输出半句。"
            "\n只输出新增故事正文，不要重复已有草稿，不要输出标题或说明。"
        )
        return "\n\n".join(sections)

    @staticmethod
    def _segment_count(target_words: int) -> int:
        if target_words <= _LIGHT_GENERATION_MAX_WORDS:
            return 1
        return max(
            2,
            math.ceil(target_words / settings.generation_segment_target_words),
        )

    def _format_character_states(self, kb: KnowledgeBase) -> str:
        """将最关键的知识库信息压缩为 prompt 上下文。"""
        if not kb:
            return ""
        lines: list[str] = []
        if kb.characters:
            lines.append("核心角色：")
        for char in kb.characters[:4]:
            parts = [f"- {char.name}"]
            if char.aliases:
                parts.append(f"别称 {'/'.join(char.aliases[:2])}")
            if char.personality:
                parts.append(f"性格 {char.personality[:100]}")
            if char.speech_style:
                parts.append(f"说话 {char.speech_style[:60]}")
            lines.append("；".join(parts))
        if kb.world_settings:
            lines.append("关键设定：")
            for setting in kb.world_settings[:3]:
                lines.append(f"- {setting.name}：{setting.description[:120]}")
        if kb.themes:
            themes = "、".join(theme.name for theme in kb.themes[:3] if theme.name)
            if themes:
                lines.append(f"核心主题：{themes}")
        if kb.style_knowledge:
            style_rules = [
                *kb.style_knowledge.global_character_rules,
                *kb.style_knowledge.global_dialogue_rules,
                *kb.style_knowledge.global_worldbuilding_rules,
                *kb.style_knowledge.plot_continuity_rules,
            ][:8]
            if style_rules:
                lines.append("续写风格规则：")
                lines.extend(f"- {rule[:160]}" for rule in style_rules)
        return "\n".join(lines)

    def _limit_prompts(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, str, bool]:
        max_chars = max(1000, self._prompt_max_chars)
        truncated = False
        max_system_chars = max_chars // 2
        if len(system_prompt) > max_system_chars:
            system_prompt = _truncate_middle(system_prompt, max_system_chars)
            truncated = True
        remaining = max(500, max_chars - len(system_prompt))
        if len(user_prompt) > remaining:
            user_prompt = _truncate_middle(user_prompt, remaining)
            truncated = True
        return system_prompt, user_prompt, truncated

    # ── 生成流程：大纲 → 草稿 ──

    async def _generate_outline(self, system_prompt: str, user_prompt: str) -> str:
        """先生成章节大纲"""
        outline_prompt = (
            user_prompt
            + "\n\n---\n\n请先输出本章的大纲（200-400字），包含：\n"
            + "1. 本章核心事件（1-2个）\n"
            + "2. 场景安排（2-3个场景）\n"
            + "3. 情感走向（悲/喜/燃/虐的排布）\n"
            + "4. 开头和结尾的设计\n\n"
            + "只输出大纲，不需要标题。"
        )
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.messages.create,
                    model=self._model,
                    max_tokens=min(self._max_tokens, 400),
                    system=system_prompt,
                    messages=[{"role": "user", "content": outline_prompt}],
                    timeout=self._timeout_seconds,
                ),
                timeout=self._timeout_seconds,
            )
            return _response_text(response)
        except Exception as exc:
            self._report(
                62,
                "正在调用模型",
                f"大纲请求失败（{type(exc).__name__}），将直接生成正文",
            )
            return ""  # 大纲生成失败时直接跳过，进入草稿

    async def _generate_draft(
        self,
        system_prompt: str,
        user_prompt: str,
        outline: str,
        *,
        max_tokens: int | None = None,
    ) -> str:
        """基于大纲生成章节草稿"""
        draft_prompt = user_prompt
        if outline:
            draft_prompt += (
                "\n\n---\n\n## 本章大纲\n\n"
                + outline
                + "\n\n---\n\n请基于以上大纲，写出完整章节正文。直接输出故事正文，不需要章节标题或标记。"
            )
        system_prompt, draft_prompt, _ = self._limit_prompts(
            system_prompt,
            draft_prompt,
        )

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.messages.create,
                    model=self._model,
                    max_tokens=max_tokens or self._max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": draft_prompt}],
                    timeout=self._timeout_seconds,
                ),
                timeout=self._timeout_seconds,
            )
            return _response_text(response)
        except Exception as e:
            raise GenerationServiceError(
                f"模型生成失败 ({type(e).__name__}): {e}"
            ) from e

    async def _generate_draft_stream(self, system_prompt: str, user_prompt: str, outline: str) -> AsyncIterator[str]:
        """流式生成章节草稿"""
        draft_prompt = user_prompt
        if outline:
            draft_prompt += (
                "\n\n---\n\n## 本章大纲\n\n"
                + outline
                + "\n\n---\n\n请基于以上大纲，写出完整章节正文。直接输出故事正文，不需要章节标题或标记。"
            )

        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": draft_prompt}],
                timeout=self._timeout_seconds,
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except Exception as e:
            raise GenerationServiceError(
                f"模型流式生成失败 ({type(e).__name__}): {e}"
            ) from e


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


def _truncate_middle(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = "\n\n...[内容已自动截断]...\n\n"
    available = max(0, max_chars - len(marker))
    head = available // 2
    tail = available - head
    return f"{text[:head]}{marker}{text[-tail:] if tail else ''}"


def _word_count(text: str) -> int:
    return len("".join(text.split()))


def _apply_revision_edits(
    original_content: str,
    raw_edits,
) -> tuple[str, int]:
    if isinstance(raw_edits, dict):
        raw_edits = [raw_edits]
    if not isinstance(raw_edits, list):
        return original_content, 0

    revised = original_content
    applied = 0
    for item in raw_edits[:6]:
        if not isinstance(item, dict):
            continue
        search = str(item.get("search") or "")
        replacement = str(item.get("replacement") or "")
        if not search.strip() or search not in revised:
            continue
        revised = revised.replace(search, replacement, 1)
        applied += 1
    return revised, applied


def _revision_source_excerpt(
    original_content: str,
    target_section: str,
    max_chars: int,
) -> str:
    if len(original_content) <= max_chars:
        return original_content
    target = target_section.strip()
    if target and target in original_content:
        index = original_content.index(target)
        half = max_chars // 2
        start = max(0, index - half)
        end = min(len(original_content), start + max_chars)
        return original_content[start:end]
    return _truncate_middle(original_content, max_chars)


def _revision_diagnostics(
    original_content: str,
    revised_content: str,
    feedback: str,
    revision_mode: str,
) -> RevisionDiagnostics:
    original_words = _word_count(original_content)
    revised_words = _word_count(revised_content)
    ratio = revised_words / max(1, original_words)
    compression_requested = bool(
        re.search(r"压缩|精简|缩短|摘要|删减|改成\s*\d+\s*字", feedback)
    )
    abnormal = original_words >= 1000 and ratio < 0.25 and not compression_requested
    requires_confirmation = (
        original_words >= 1000 and ratio < 0.6 and not compression_requested
    )
    delta = abs(revised_words - original_words) / max(1, original_words)
    if abnormal:
        level = "异常缩短"
    elif delta <= 0.1:
        level = "小幅修改"
    elif delta <= 0.35:
        level = "中等修改"
    else:
        level = "大幅重写"
    warning = ""
    if abnormal:
        warning = "修改结果异常变短，已保留原文；该候选版不可直接覆盖。"
    elif requires_confirmation:
        warning = "修改结果明显短于原文，已保留为候选版，接受前请人工复核。"
    return RevisionDiagnostics(
        revision_mode=revision_mode,
        original_word_count=original_words,
        revised_word_count=revised_words,
        length_ratio=ratio,
        change_level=level,
        requires_confirmation=requires_confirmation,
        revision_failed=abnormal,
        warning=warning,
    )


def _compact_anchor(text: str) -> str:
    if len(text) <= _MAX_CHAPTER_CONTEXT_CHARS:
        return text
    head_chars = 1000
    tail_chars = _MAX_CHAPTER_CONTEXT_CHARS - head_chars
    return (
        text[:head_chars]
        + "\n\n...[起始章节正文已截断]...\n\n"
        + text[-tail_chars:]
    )


def _compact_segment_summary(text: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    if len(clean) <= 500:
        return clean
    return f"{clean[:220]} ... {clean[-260:]}"


# ── 模块级包装函数（兼容 router 现有 import） ──

async def generate_chapter(
    *,
    chapter: Chapter,
    kb: KnowledgeBase,
    request: GenerationRequest,
    progress_callback: ProgressCallback | None = None,
    segment_callback: SegmentCallback | None = None,
    ending_callback: EndingCallback | None = None,
    draft_content: str = "",
    previous_draft_content: str = "",
    planning_context: str = "",
    reference_chapters: list[Chapter] | None = None,
) -> tuple[str, str]:
    """生成续写章节"""
    generator = ContinuationGenerator(
        progress_callback=progress_callback,
        segment_callback=segment_callback,
        ending_callback=ending_callback,
    )
    return await generator.generate(
        chapter,
        kb,
        request,
        draft_content=draft_content,
        previous_draft_content=previous_draft_content,
        planning_context=planning_context,
        reference_chapters=reference_chapters,
    )


async def generate_chapter_stream(*, chapter: Chapter, kb: KnowledgeBase, request: GenerationRequest) -> AsyncIterator[str]:
    """流式生成续写章节"""
    generator = ContinuationGenerator()
    async for chunk in generator.generate_stream(chapter, kb, request):
        yield chunk


async def iterate_chapter(
    *,
    previous_result: GenerationResult,
    feedback: str,
    target_section: str,
    kb: KnowledgeBase,
    current_text: str = "",
    revision_mode: str = "local_edit",
    progress_callback: Callable[[float, str, str], None] | None = None,
    ending_callback: EndingCallback | None = None,
    revision_callback: RevisionCallback | None = None,
) -> tuple[str, str]:
    """根据反馈迭代修改章节"""
    generator = ContinuationGenerator(
        progress_callback=progress_callback,
        ending_callback=ending_callback,
        revision_callback=revision_callback,
    )
    return await generator.iterate(
        previous_result,
        feedback,
        target_section,
        kb,
        current_text=current_text,
        revision_mode=revision_mode,
    )
