"""项目级文风分析引擎。"""

import asyncio
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from anthropic import Anthropic
from app.config import settings
from app.services.model_policy import anthropic_client_options
from app.services.file_ops import atomic_write_text
from app.services.project_profile import get_project_profile
from app.models.schemas import (
    AnalysisDimension,
    Chapter,
    ChapterStyleCacheEntry,
    ChapterStyleJson,
    DimensionResult,
    GlobalStyleKnowledge,
)

# ── 八维度分析提示词 ──────────────────────────────────────────────

_NARRATIVE_PERSPECTIVE_PROMPT = """你是一位中国文学叙事学专家。请分析以下《龙族》小说片段的**叙事视角**特征。

分析要点：
1. **视角类型**：第一人称/第三人称/视角混合，各占比多少
2. **视角切换**：是否频繁切换视角，切换时机和触发条件（如从路明非内心切换到全知叙述）
3. **内心独白**：角色内心独白（OS/吐槽）的使用频率和方式
4. **叙事距离**：叙述者与角色的距离——是紧贴角色意识还是保持距离
5. **限制性**：叙述者知道多少（全知/有限/客观），是否刻意隐藏信息
6. **标志性手法**：江南特有的视角处理方式（如"衰仔视角"、战斗中的内心吐槽穿插）

输出 JSON：
{
  "primary_pov": "第一人称/第三人称/混合",
  "pov_distribution": {"第一人称": 百分比数字, "第三人称": 百分比数字},
  "switch_frequency": "高/中/低",
  "switch_triggers": ["触发条件1", "触发条件2"],
  "inner_monologue_ratio": 百分比数字,
  "inner_monologue_style": "内心独白的风格描述",
  "narrative_distance": "紧贴/中等/疏离",
  "limitedness": "全知/有限/客观",
  "signature_techniques": ["标志性手法1", "标志性手法2"],
  "examples": ["原文示例1", "原文示例2"],
  "summary": "叙事视角特征的简要总结"
}"""

_SENTENCE_RHYTHM_PROMPT = """你是一位中国文学语言学专家。请分析以下《龙族》小说片段的**句子长度与节奏**特征。

分析要点：
1. **句子长度分布**：短句(≤10字)、中句(11-30字)、长句(31-50字)、超长句(>50字)各占比
2. **长短句交替模式**：作者如何在长句和短句间切换，典型句式组合模式
3. **段落长度**：平均段落字数，段落长度变化模式
4. **标点节奏**：逗号密度、句号密度、省略号/破折号使用频率和语境
5. **节奏变化**：不同场景（战斗/日常/抒情/对话）中节奏如何变化
6. **标志性句式**：江南特有的句式结构（如"XX是真的，YY也是真的"、"他/她想……然后他/她……"）

输出 JSON：
{
  "sentence_length_distribution": {"短句(≤10字)": 百分比, "中句(11-30字)": 百分比, "长句(31-50字)": 百分比, "超长句(>50字)": 百分比},
  "avg_sentence_length": 数字,
  "alternation_pattern": "长短句交替模式描述",
  "avg_paragraph_length": 数字,
  "paragraph_rhythm": "段落节奏描述",
  "punctuation_density": {"逗号密度": 数字, "句号密度": 数字, "省略号频率": "高/中/低", "破折号频率": "高/中/低"},
  "scene_rhythm_variation": {"战斗": "节奏描述", "日常": "节奏描述", "抒情": "节奏描述", "对话": "节奏描述"},
  "signature_patterns": ["标志性句式模式1", "标志性句式模式2"],
  "examples": ["原文示例1", "原文示例2"],
  "summary": "句子节奏特征的简要总结"
}"""

_DIALOGUE_RATIO_PROMPT = """你是一位中国文学对话艺术专家。请分析以下《龙族》小说片段的**对话比例与特征**。

分析要点：
1. **对话占比**：对话文本占总字数的百分比
2. **对话风格**：是快节奏交锋还是慢节奏独白，对话的平均长度
3. **话轮交替**：对话中多人交替的频率和模式
4. **对话标签**：使用"说/道/问/喊/叫"等标签的偏好统计
5. **潜台词密度**：对话中未明说的隐含信息量
6. **角色声音区分**：不同角色的说话方式差异

输出 JSON：
{
  "dialogue_ratio": 百分比数字,
  "narration_ratio": 百分比数字,
  "dialogue_style": "快节奏交锋/慢节奏独白/混合",
  "avg_dialogue_turn_length": 数字,
  "turn_alternation_frequency": "高/中/低",
  "dialogue_tag_preference": {"说": 百分比, "道": 百分比, "问": 百分比, "喊": 百分比, "其他": 百分比},
  "subtext_density": "高/中/低",
  "character_voice_distinction": "明显/一般/模糊",
  "character_voice_notes": "角色声音区分的具体描述",
  "examples": ["原文示例1", "原文示例2"],
  "summary": "对话特征的简要总结"
}"""

_EMOTIONAL_ATMOSPHERE_PROMPT = """你是一位中国文学情感分析专家。请分析以下《龙族》小说片段的**情绪氛围**特征。

分析要点：
1. **主导情绪**：片段中占比最高的情绪类型（孤独/热血/悲伤/搞笑/温情/紧张/绝望/希望等）
2. **情绪混合模式**：不同情绪如何混合和切换（如"悲剧内核裹喜剧外衣"）
3. **情绪强度曲线**：文字的情绪强弱变化轨迹
4. **孤独感渲染**：如何通过文字营造孤独氛围（特定词汇、句式、场景）
5. **燃点处理**：热血/激情场景的铺垫方式和爆发模式
6. **情绪留白**：克制表达、省略、暗示带来的情绪效果

输出 JSON：
{
  "dominant_emotions": [{"情绪类型": "占比描述", "百分比": 数字}],
  "emotion_mix_pattern": "情绪混合模式描述",
  "emotion_intensity_curve": "情绪强度变化轨迹描述",
  "loneliness_rendering": {"手法": ["手法1", "手法2"], "典型词汇": ["词1", "词2"], "典型句式": "描述"},
  "climax_build_up": "燃点铺垫与爆发模式描述",
  "emotional_restraint": "情绪留白手法描述",
  "emotional_shift_speed": "快/中/慢",
  "examples": ["原文示例1", "原文示例2"],
  "summary": "情绪氛围特征的简要总结"
}"""

_IMAGERY_PROMPT = """你是一位中国文学意象分析专家。请分析以下《龙族》小说片段的**高频意象**特征。

分析要点：
1. **核心意象**：反复出现的核心意象（如龙、剑、雨、夜、火、血、月等），各自的频率
2. **意象来源**：意象的来源领域（神话/游戏/动漫/日常/军事/科技）
3. **意象功能**：意象在文中的作用（渲染氛围/暗示命运/塑造角色/推进情节）
4. **意象组合**：哪些意象常一起出现，形成怎样的意象群
5. **比喻意象**：通过比喻创造的临时意象，及其风格（游戏化/电影化/日常化）
6. **色彩意象**：颜色词的使用偏好和象征意义

输出 JSON：
{
  "core_imagery": [{"意象": "名称", "频率": "高/中/低", "功能": "作用描述", "典型出现场景": "场景描述"}],
  "imagery_sources": [{"来源领域": "占比描述"}],
  "imagery_clusters": [{"意象组合": ["意象1", "意象2"], "效果": "效果描述"}],
  "metaphor_style": {"游戏化比喻": 百分比, "电影化比喻": 百分比, "日常化比喻": 百分比, "动漫化比喻": 百分比},
  "color_preferences": [{"颜色": "频率和象征"}],
  "signature_imagery": ["江南标志性意象1", "江南标志性意象2"],
  "examples": ["原文示例1", "原文示例2"],
  "summary": "高频意象特征的简要总结"
}"""

_DESCRIPTION_RATIO_PROMPT = """你是一位中国文学描写分析专家。请分析以下《龙族》小说片段的**描写类型比例**特征。

分析要点：
1. **动作描写**：战斗动作、日常动作描写的比例和风格
2. **心理描写**：角色内心活动描写的比例和深度
3. **场景描写**：环境/场景描写（空间、氛围、细节）的比例
4. **外貌描写**：人物外貌描写的比例和特征（细致/留白/反复强调特质）
5. **对话描写**：纯粹对话（不含描述）的比例
6. **描写切换**：不同描写类型之间的切换方式和节奏
7. **留白比例**：刻意留白、不描写的比例

输出 JSON：
{
  "description_distribution": {"动作描写": 百分比, "心理描写": 百分比, "场景描写": 百分比, "外貌描写": 百分比, "纯对话": 百分比},
  "action_style": "动作描写的风格特征",
  "psychology_depth": "浅/中/深",
  "psychology_style": "心理描写的风格特征",
  "scene_description_style": "场景描写的风格特征",
  "appearance_description_style": "外貌描写的风格特征",
  "description_switch_pattern": "描写类型切换模式描述",
  "deliberate_blank_ratio": 百分比,
  "show_vs_tell": "展示vs讲述的比例偏向",
  "examples": ["原文示例1", "原文示例2"],
  "summary": "描写类型比例的简要总结"
}"""

_CHAPTER_STRUCTURE_PROMPT = """你是一位中国文学结构分析专家。请分析以下《龙族》小说片段的**章节结构**特征。

分析要点：
1. **开头方式**：章节如何开头（场景切入/对话开场/内心独白/悬念钩子/环境铺垫/时间标记）
2. **结尾方式**：章节如何结尾（悬念/情感升华/动作中断/平静收束/反转/预告）
3. **章节内部结构**：章节内部如何分段和组织（场景-场景/时间顺序/多线并进）
4. **高潮位置**：章节高潮通常出现在什么位置（开头爆发/中间/末尾/均匀分布）
5. **转折点**：章节中是否有明显的转折点，如何设置
6. **结尾句子特征**：章节最后一句的风格（短句收束/省略号留白/反问句/哲理性总结）

输出 JSON：
{
  "opening_patterns": [{"模式": "模式描述", "频率": "高/中/低"}],
  "ending_patterns": [{"模式": "模式描述", "频率": "高/中/低"}],
  "internal_structure": "章节内部结构描述",
  "climax_position": "开头/中间/末尾/均匀分布",
  "turning_point_pattern": "转折点设置模式描述",
  "final_sentence_style": "结尾句子风格描述",
  "chapter_length_pattern": "章节长度规律描述",
  "hook_techniques": ["开篇钩子手法1", "开篇钩子手法2"],
  "examples": {"开头示例": "原文", "结尾示例": "原文", "转折示例": "原文"},
  "summary": "章节结构特征的简要总结"
}"""

_CONFLICT_ADVANCEMENT_PROMPT = """你是一位中国文学叙事学专家。请分析以下《龙族》小说片段的**冲突推进方式**特征。

分析要点：
1. **冲突类型**：动作冲突/心理冲突/人际冲突/理念冲突/命运冲突，各占比
2. **冲突层级**：当前冲突的规模（个人/团队/学院/世界/命运）
3. **冲突推进节奏**：冲突如何升级和缓解，节奏模式
4. **悬念设置**：如何制造和维持悬念（信息隐藏/时间压力/多线交叉）
5. **伏笔与回收**：伏笔的埋设方式和回收节奏
6. **冲突解决方式**：如何收束冲突（武力解决/智慧解决/情感解决/外力介入/回避/牺牲）

输出 JSON：
{
  "conflict_type_distribution": {"动作冲突": 百分比, "心理冲突": 百分比, "人际冲突": 百分比, "理念冲突": 百分比, "命运冲突": 百分比},
  "conflict_level": "个人/团队/学院/世界/命运",
  "escalation_pattern": "冲突升级模式描述",
  "suspense_techniques": ["悬念手法1", "悬念手法2"],
  "foreshadowing_pattern": "伏笔埋设与回收模式描述",
  "resolution_patterns": ["解决方式1", "解决方式2"],
  "conflict_density": "高/中/低",
  "conflict_rhythm": "紧张-缓解交替模式描述",
  "examples": ["原文示例1", "原文示例2"],
  "summary": "冲突推进方式的简要总结"
}"""

_CHARACTER_VOICE_PROMPT = """你是一位中国文学人物塑造专家。请分析以下《龙族》小说片段的**人物对白特点**。

分析要点：
1. **对白个性**：每个说话角色的语言特征（用词偏好、句长、语气、口癖）
2. **对白功能**：对白在文中的作用（推进情节/塑造性格/制造笑点/渲染气氛/埋设伏笔）
3. **对白与叙述关系**：对白和叙述如何配合（叙述引出对白/对白打断叙述/叙述补充对白）
4. **对白节奏**：快速交锋 vs 长篇独白 vs 沉默留白
5. **话中有话**：对话中的潜台词、暗示、反讽、双关
6. **标志性对白模式**：江南特有的对白写法（如路明非的"内心吐槽+表面迎合"模式）

输出 JSON：
{
  "character_speech_profiles": [{"角色": "角色名", "用词偏好": "描述", "平均句长": 数字, "语气特征": "描述", "口癖": ["口癖1"]}],
  "dialogue_functions": {"推进情节": 百分比, "塑造性格": 百分比, "制造笑点": 百分比, "渲染气氛": 百分比, "埋设伏笔": 百分比},
  "dialogue_narration_interplay": "对白与叙述配合模式描述",
  "dialogue_rhythm_patterns": ["模式1", "模式2"],
  "subtext_techniques": ["潜台词手法1", "潜台词手法2"],
  "signature_dialogue_patterns": ["标志性对白模式1", "标志性对白模式2"],
  "examples": ["原文示例1", "原文示例2"],
  "summary": "人物对白特点的简要总结"
}"""

_CLIFFHANGER_STYLE_PROMPT = """你是一位中国文学叙事技巧专家。请分析以下《龙族》小说片段的**章节结尾悬念方式**特征。

分析要点：
1. **结尾类型**：悬念式/反转式/情感升华式/平静收束式/动作中断式/预告式，各占比
2. **悬念密度**：每章平均设置几个未解问题
3. **悬念层次**：单层悬念 vs 多层嵌套悬念
4. **结尾句子特征**：最后一句的长度、语气、修辞特点
5. **悬念回收周期**：悬念从设置到揭晓平均跨越多少章
6. **标志性结尾手法**：江南特有的章节结尾写法（如省略号留白、短句收束、反问句、哲理性独白）

输出 JSON：
{
  "ending_type_distribution": {"悬念式": 百分比, "反转式": 百分比, "情感升华式": 百分比, "平静收束式": 百分比, "动作中断式": 百分比, "预告式": 百分比},
  "suspense_density": 数字,
  "suspense_layers": "单层/多层嵌套",
  "final_sentence_analysis": {"平均字数": 数字, "常用标点": "描述", "语气特征": "描述"},
  "suspense_recovery_span": "短(1-2章)/中(3-5章)/长(>5章)",
  "signature_endings": ["标志性结尾手法1", "标志性结尾手法2"],
  "cliffhanger_effectiveness": "高/中/低",
  "examples": {"悬念式结尾示例": "原文", "反转式结尾示例": "原文", "情感升华式结尾示例": "原文"},
  "summary": "章节结尾悬念方式的简要总结"
}"""

_STYLE_SENSIBILITY_PROMPT = """你是一位中国文学审美研究专家。请分析以下《龙族》小说片段的**风格感知**特征——即那些构成作品独特"味道"的感性维度。

分析以下五个核心风格维度：

1. **少年感**
   - 是否通过角色视角传达出少年的热血、冲动、理想主义
   - 是否有"与世界为敌也在所不惜"的少年意气
   - 表达方式、词汇选择、场景设置中的少年气息

2. **孤独感**
   - 如何通过环境描写渲染孤独（雨、夜、空房间、城市夜景）
   - 角色内心独白中的孤独表达
   - "热闹中的孤独"——在群体场景中个体被疏离的感受

3. **热血感**
   - 燃点/高潮场景的情感强度和推进方式
   - "燃"的触发条件（守护他人/自我证明/挑战命运）
   - 热血场景中的语言特征（短句堆叠、感叹号、排比）

4. **命运感**
   - 命运/宿命主题的呈现方式
   - "被选中者"的宿命感和无力感
   - 命运转折点的叙述方式

5. **吐槽感**
   - 角色内心吐槽的频率和风格
   - 吐槽与严肃场景的穿插方式
   - 吐槽的语言特征（网络用语、夸张、自嘲、反讽）

输出 JSON：
{
  "youthful_spirit": {"强度": 数字0-100, "表达方式": ["方式1", "方式2"], "典型场景": ["场景1"], "关键文本特征": "描述"},
  "loneliness": {"强度": 数字0-100, "渲染手法": ["手法1", "手法2"], "典型意象": ["意象1"], "典型句式": "描述"},
  "passion": {"强度": 数字0-100, "触发条件": ["条件1", "条件2"], "语言特征": "描述", "爆发模式": "描述"},
  "fatality": {"强度": 数字0-100, "呈现方式": ["方式1", "方式2"], "典型场景": ["场景1"], "叙述语气": "描述"},
  "inner_commentary": {"强度": 数字0-100, "吐槽频率": "高/中/低", "吐槽风格": "描述", "与严肃场景的切换模式": "描述"},
  "sensibility_mix": "五种风格感知的混合比例和模式",
  "examples": {"少年感": "原文示例", "孤独感": "原文示例", "热血感": "原文示例", "命运感": "原文示例", "吐槽感": "原文示例"},
  "summary": "风格感知特征的整体总结"
}"""

# 维度键 → (AnalysisDimension 枚举值, 提示词) 映射
_DIMENSION_CONFIG: list[tuple[str, AnalysisDimension, str]] = [
    ("叙事视角", AnalysisDimension.NARRATIVE_PERSPECTIVE, _NARRATIVE_PERSPECTIVE_PROMPT),
    ("句子长度与节奏", AnalysisDimension.SENTENCE_RHYTHM, _SENTENCE_RHYTHM_PROMPT),
    ("对话比例与特征", AnalysisDimension.DIALOGUE_RATIO, _DIALOGUE_RATIO_PROMPT),
    ("情绪氛围", AnalysisDimension.EMOTIONAL_ATMOSPHERE, _EMOTIONAL_ATMOSPHERE_PROMPT),
    ("高频意象", AnalysisDimension.IMAGERY, _IMAGERY_PROMPT),
    ("描写类型比例", AnalysisDimension.DESCRIPTION_RATIO, _DESCRIPTION_RATIO_PROMPT),
    ("章节结构", AnalysisDimension.CHAPTER_STRUCTURE, _CHAPTER_STRUCTURE_PROMPT),
    ("冲突推进方式", AnalysisDimension.CONFLICT_ADVANCEMENT, _CONFLICT_ADVANCEMENT_PROMPT),
    ("人物对白特点", AnalysisDimension.CHARACTER_VOICE, _CHARACTER_VOICE_PROMPT),
    ("章节结尾悬念", AnalysisDimension.CLIFFHANGER_STYLE, _CLIFFHANGER_STYLE_PROMPT),
    ("风格感知", AnalysisDimension.STYLE_SENSIBILITY, _STYLE_SENSIBILITY_PROMPT),
]

_CHAPTER_STYLE_PROMPT = """分析下面单章小说的写作风格，只输出一个有效 JSON 对象。
不要复述情节，不要输出 Markdown，不要添加 schema 之外的字段。

JSON schema：
{{
  "narrative_pov": "叙事视角、叙事距离和视角切换方式",
  "language_style": "语言风格、用词和修辞特点",
  "sentence_rhythm": "句式长度、段落和节奏特点",
  "dialogue_style": "对话节奏、角色声音和潜台词特点",
  "description_focus": "动作、心理、环境、外貌等描写重点",
  "emotional_tone": "主导情绪及情绪切换方式",
  "pacing": "剧情推进、悬念和收束节奏",
  "character_portrayal": "人物塑造方式",
  "worldbuilding_style": "设定如何自然展开",
  "recurring_motifs": ["反复意象或主题"],
  "taboo_or_constraints": ["续写时应避免的风格错误"],
  "continuation_rules": ["续写时应遵守的具体规则"]
}}

章节：{chapter_title}
正文抽样：
{chapter_text}
"""

_GLOBAL_STYLE_PROMPT = """根据章节级风格 JSON 汇总全书级写作规则。
输入不含原文。只输出一个有效 JSON 对象，不要输出 Markdown。

JSON schema：
{{
  "global_narrative_style": "全局叙事风格",
  "global_language_style": "全局语言风格",
  "global_pacing_pattern": "全局节奏模式",
  "global_character_rules": ["人物塑造规则"],
  "global_dialogue_rules": ["对话规则"],
  "global_worldbuilding_rules": ["设定展开规则"],
  "plot_continuity_rules": ["情节连续性规则"],
  "do_not_write_list": ["禁止出现的写法"],
  "style_prompt_for_continuation": "可直接用于续写的精简风格提示词"
}}

章节级风格 JSON：
{style_payload}
"""


class ChapterStyleAnalysisError(RuntimeError):
    pass


class GlobalStyleSummaryError(RuntimeError):
    pass


class StyleAnalyzer:
    """文风分析引擎 — 从十一个维度分析小说文本风格"""

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int | None = None,
        thinking_budget: int | None = None,
        client=None,
    ):
        self._api_key = settings.anthropic_api_key
        base_url = settings.anthropic_base_url or None
        self._client = client
        if self._client is None and self._api_key:
            self._client = Anthropic(
                api_key=self._api_key,
                base_url=base_url,
                **anthropic_client_options("style_analysis"),
            )
        self._model = model or settings.anthropic_model
        configured_max_tokens = max_tokens or settings.style_model_max_tokens
        self._max_tokens = min(configured_max_tokens, settings.style_model_max_tokens)
        self._thinking_budget = thinking_budget or settings.anthropic_thinking_budget

    async def analyze(
        self,
        chapter: Chapter,
        progress_callback: Callable[[float, str, str], None] | None = None,
        diagnostics: dict | None = None,
    ) -> list[DimensionResult]:
        """对单章执行一次有界模型请求，并兼容现有维度报告。"""
        sampled_text = _sample_chapter_text(
            chapter.content,
            settings.style_chapter_sample_chars,
        )
        if progress_callback:
            progress_callback(25, "提取规则", "正在计算句长、段落、对话和词频")
        fallback_style = self._build_rule_style_json(chapter, sampled_text)
        warning = ""
        try:
            entry, cache_hit = await self.analyze_chapter_style(
                chapter,
                fallback_style=fallback_style,
                diagnostics=diagnostics,
            )
            style_json = entry.style_json
            if progress_callback:
                progress_callback(
                    75,
                    "保存章节缓存" if not cache_hit else "读取章节缓存",
                    (
                        f"已保存《{chapter.title}》章节级风格缓存"
                        if not cache_hit
                        else f"《{chapter.title}》内容未变化，已复用缓存"
                    ),
                )
        except ChapterStyleAnalysisError as exc:
            style_json = fallback_style
            warning = str(exc)
            if diagnostics is not None:
                diagnostics.setdefault("warnings", []).append(warning)
                diagnostics["last_error"] = exc
            if progress_callback:
                progress_callback(
                    75,
                    "使用规则结果",
                    f"章节模型分析失败，已保留规则风格结果：{warning}",
                )
        if diagnostics is not None:
            diagnostics["chapter_style_json"] = style_json.model_dump(mode="json")
            diagnostics["warning"] = warning
        if progress_callback:
            progress_callback(85, "整理章节报告", "正在转换为页面分析维度")
        return _style_json_to_dimensions(style_json)

    async def analyze_chapter_style(
        self,
        chapter: Chapter,
        *,
        fallback_style: ChapterStyleJson | None = None,
        diagnostics: dict | None = None,
        use_cache: bool = True,
    ) -> tuple[ChapterStyleCacheEntry, bool]:
        """分析单章并返回缓存记录；一次请求只包含一个章节。"""
        cached = load_chapter_style_cache(chapter) if use_cache else None
        if cached and (cached.model_name != "rule_fallback" or not self._client):
            if diagnostics is not None:
                diagnostics.update(cache_hit=True, used_model=False)
            return cached, True

        fallback_style = fallback_style or self._build_rule_style_json(
            chapter,
            _sample_chapter_text(
                chapter.content,
                settings.style_chapter_sample_chars,
            ),
        )
        if not self._client:
            entry = ChapterStyleCacheEntry(
                chapter_id=chapter.chapter_id,
                chapter_title=chapter.title,
                content_hash=_chapter_content_hash(chapter),
                model_name="rule_fallback",
                style_json=fallback_style,
            )
            if use_cache:
                save_chapter_style_cache(entry)
            if diagnostics is not None:
                diagnostics.update(cache_hit=False, used_model=False)
            return entry, False

        if diagnostics is not None:
            diagnostics.update(
                cache_hit=False,
                used_model=True,
                model_failures=0,
                timeout_failures=0,
                json_failures=0,
            )

        sampled_text = _sample_chapter_text(
            chapter.content,
            settings.style_chapter_sample_chars,
        )
        user_prompt = _CHAPTER_STYLE_PROMPT.format(
            chapter_title=chapter.title,
            chapter_text=sampled_text,
        )
        user_prompt = _limit_text(
            user_prompt,
            _prompt_char_budget(
                settings.style_prompt_max_chars,
                settings.style_prompt_max_input_tokens,
            ),
        )
        if diagnostics is not None:
            diagnostics.update(
                prompt_chars=len(user_prompt),
                estimated_input_tokens=_estimate_input_tokens(user_prompt),
            )
        last_error: Exception | None = None
        repair_used = False
        max_attempts = 1 + max(0, settings.style_chapter_retries)

        for attempt in range(1, max_attempts + 1):
            try:
                parsed, repair_used = await self._request_json_object(
                    user_prompt,
                    repair_used=repair_used,
                )
                merged = fallback_style.model_dump(mode="json")
                merged.update(parsed)
                style_json = ChapterStyleJson.model_validate(merged)
                entry = ChapterStyleCacheEntry(
                    chapter_id=chapter.chapter_id,
                    chapter_title=chapter.title,
                    content_hash=_chapter_content_hash(chapter),
                    model_name=self._model,
                    analyzed_at=datetime.now(timezone.utc),
                    style_json=style_json,
                )
                save_chapter_style_cache(entry)
                if diagnostics is not None:
                    diagnostics["attempts"] = attempt
                return entry, False
            except Exception as exc:
                last_error = exc
                if diagnostics is not None:
                    diagnostics["model_failures"] += 1
                    diagnostics["last_error"] = exc
                    if _is_timeout_error(exc):
                        diagnostics["timeout_failures"] += 1
                    if isinstance(exc, (json.JSONDecodeError, ValueError)):
                        diagnostics["json_failures"] += 1
                if attempt < max_attempts:
                    await asyncio.sleep(
                        min(0.5 * attempt, settings.model_timeout_seconds / 10)
                    )

        raise ChapterStyleAnalysisError(
            f"《{chapter.title}》分析失败，已尝试 {max_attempts} 次："
            f"{type(last_error).__name__ if last_error else 'UnknownError'}"
        ) from last_error

    async def _request_json_object(
        self,
        user_prompt: str,
        *,
        repair_used: bool,
    ) -> tuple[dict, bool]:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                self._client.messages.create,
                model=self._model,
                max_tokens=self._max_tokens,
                system="你是小说风格分析助手，只输出有效 JSON。",
                messages=[{"role": "user", "content": user_prompt}],
                timeout=settings.model_timeout_seconds,
            ),
            timeout=settings.model_timeout_seconds,
        )
        content = _response_text(response)
        parsed = _parse_json_object_lenient(content)
        if parsed:
            return parsed, repair_used
        if repair_used:
            raise ValueError("模型返回 JSON 解析失败")

        repair_prompt = _limit_text(
            "修复下面内容为有效 JSON，只输出修复后的 JSON：\n" + content,
            _prompt_char_budget(
                settings.style_prompt_max_chars,
                settings.style_prompt_max_input_tokens,
            ),
        )
        repaired = await asyncio.wait_for(
            asyncio.to_thread(
                self._client.messages.create,
                model=self._model,
                max_tokens=self._max_tokens,
                system="你只负责修复 JSON，不增加新信息。",
                messages=[{"role": "user", "content": repair_prompt}],
                timeout=settings.model_timeout_seconds,
            ),
            timeout=settings.model_timeout_seconds,
        )
        parsed = _parse_json_object_lenient(_response_text(repaired))
        if not parsed:
            raise ValueError("JSON 修复请求仍未返回有效对象")
        return parsed, True

    async def _analyze_one(
        self,
        text: str,
        label: str,
        dim_enum: AnalysisDimension,
        prompt_template: str,
        fallback: DimensionResult,
        diagnostics: dict | None,
    ) -> DimensionResult:
        """对单个维度执行分析"""
        system_prompt = (
            "你是一位专业的文学风格分析专家，擅长分析中国当代幻想小说的写作技法。"
            "请严格按照要求的 JSON 格式输出分析结果，只输出 JSON，不要有其他内容。"
            "所有百分比以数字形式给出（如 35 代表 35%），不要加 % 符号。"
        )
        user_prompt = get_project_profile().adapt_legacy_prompt(
            f"{prompt_template}\n\n待分析正文：\n{text}"
        )

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.messages.create,
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    timeout=settings.model_timeout_seconds,
                ),
                timeout=settings.model_timeout_seconds,
            )
            content = _response_text(response)
            parsed = _parse_json_response(content)
        except Exception as e:
            if diagnostics is not None:
                diagnostics["model_failures"] += 1
                diagnostics["last_error"] = e
                if isinstance(e, TimeoutError) or "timeout" in type(e).__name__.lower():
                    diagnostics["timeout_failures"] += 1
            fallback.details["fallback_reason"] = f"{label}模型分析失败: {type(e).__name__}"
            return fallback

        summary = parsed.pop("summary", "") or parsed.pop("概述", "") or ""
        examples = _normalize_examples(
            parsed.pop("examples", []) or parsed.pop("示例", []) or []
        )
        if not summary or parsed.get("parse_error"):
            if diagnostics is not None:
                diagnostics["model_failures"] += 1
                diagnostics["json_failures"] += 1
                diagnostics["last_error"] = ValueError("模型返回 JSON 解析失败")
            fallback.details["fallback_reason"] = "模型响应不是有效 JSON"
            return fallback

        return DimensionResult(
            dimension=dim_enum,
            summary=summary,
            details=parsed,
            examples=examples,
        )

    def _build_rule_fallbacks(
        self,
        chapter: Chapter,
        text: str,
    ) -> dict[AnalysisDimension, DimensionResult]:
        paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
        sentences = [
            sentence.strip()
            for sentence in re.split(r"[。！？!?；;]+", text)
            if sentence.strip()
        ]
        sentence_lengths = [len(sentence) for sentence in sentences] or [0]
        short = sum(length <= 10 for length in sentence_lengths)
        medium = sum(10 < length <= 30 for length in sentence_lengths)
        long = sum(length > 30 for length in sentence_lengths)
        emotion_keywords = {
            "孤独": ["孤独", "寂寞", "一个人", "空荡"],
            "紧张": ["危险", "恐惧", "紧张", "逃"],
            "悲伤": ["悲伤", "眼泪", "失去", "死亡"],
            "热血": ["战斗", "燃烧", "怒吼", "守护"],
            "温情": ["微笑", "拥抱", "朋友", "温暖"],
        }
        emotion_counts = {
            name: sum(text.count(keyword) for keyword in keywords)
            for name, keywords in emotion_keywords.items()
        }
        words = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
        stop_words = {"一个", "没有", "他们", "自己", "什么", "这个", "那个", "就是"}
        high_frequency = [
            {"word": word, "count": count}
            for word, count in Counter(words).most_common(30)
            if word not in stop_words
        ][:10]
        avg_sentence = round(sum(sentence_lengths) / max(len(sentence_lengths), 1), 1)
        avg_paragraph = round(
            sum(len(paragraph) for paragraph in paragraphs) / max(len(paragraphs), 1),
            1,
        )
        dominant_emotion = max(emotion_counts, key=emotion_counts.get)
        common_details = {
            "sentence_count": len(sentences),
            "paragraph_count": len(paragraphs),
            "avg_sentence_length": avg_sentence,
            "avg_paragraph_length": avg_paragraph,
            "sentence_length_distribution": {
                "short": short,
                "medium": medium,
                "long": long,
            },
            "dialogue_ratio": chapter.dialogue_ratio,
            "emotion_keywords": emotion_counts,
            "high_frequency_words": high_frequency,
            "analysis_source": "rule_fallback",
        }
        summaries = {
            AnalysisDimension.NARRATIVE_PERSPECTIVE:
                "规则分析显示正文以第三人称叙述为主，夹杂角色内心活动。",
            AnalysisDimension.SENTENCE_RHYTHM:
                f"平均句长约 {avg_sentence} 字，共 {len(paragraphs)} 个段落，长短句交替。",
            AnalysisDimension.DIALOGUE_RATIO:
                f"对话约占正文的 {chapter.dialogue_ratio:.1%}。",
            AnalysisDimension.EMOTIONAL_ATMOSPHERE:
                f"关键词统计中较突出的情绪倾向为“{dominant_emotion}”。",
            AnalysisDimension.IMAGERY:
                "高频词显示场景、人物与动作意象共同推动叙事。",
            AnalysisDimension.DESCRIPTION_RATIO:
                "正文由叙述、动作描写和对话混合构成。",
            AnalysisDimension.CHAPTER_STRUCTURE:
                f"章节包含 {len(paragraphs)} 个段落，开篇建立场景，末段承担收束或悬念。",
            AnalysisDimension.CONFLICT_ADVANCEMENT:
                "冲突主要通过动作、对话和信息揭示逐步推进。",
            AnalysisDimension.CHARACTER_VOICE:
                "人物声音主要依靠短对话、语气词和叙述中的心理反应区分。",
            AnalysisDimension.CLIFFHANGER_STYLE:
                "结尾倾向用动作中断、信息留白或情绪收束形成继续阅读动力。",
            AnalysisDimension.STYLE_SENSIBILITY:
                "初步判断为快节奏幻想叙事，兼有口语化表达、情绪反差和画面感。",
        }
        return {
            dimension: DimensionResult(
                dimension=dimension,
                summary=summaries[dimension],
                details=dict(common_details),
                examples=[],
            )
            for dimension in AnalysisDimension
        }

    def _build_rule_style_json(
        self,
        chapter: Chapter,
        text: str,
    ) -> ChapterStyleJson:
        fallbacks = self._build_rule_fallbacks(chapter, text)
        common = fallbacks[AnalysisDimension.SENTENCE_RHYTHM].details
        motifs = [
            item.get("word", "")
            for item in common.get("high_frequency_words", [])[:8]
            if item.get("word")
        ]
        return ChapterStyleJson(
            narrative_pov=fallbacks[
                AnalysisDimension.NARRATIVE_PERSPECTIVE
            ].summary,
            language_style=fallbacks[AnalysisDimension.STYLE_SENSIBILITY].summary,
            sentence_rhythm=fallbacks[AnalysisDimension.SENTENCE_RHYTHM].summary,
            dialogue_style=fallbacks[AnalysisDimension.DIALOGUE_RATIO].summary,
            description_focus=fallbacks[
                AnalysisDimension.DESCRIPTION_RATIO
            ].summary,
            emotional_tone=fallbacks[
                AnalysisDimension.EMOTIONAL_ATMOSPHERE
            ].summary,
            pacing=fallbacks[AnalysisDimension.CONFLICT_ADVANCEMENT].summary,
            character_portrayal=fallbacks[
                AnalysisDimension.CHARACTER_VOICE
            ].summary,
            worldbuilding_style="设定信息通过场景、对话和人物行动逐步展开，避免集中说明。",
            recurring_motifs=motifs,
            taboo_or_constraints=[
                "避免连续大段解释世界观",
                "避免角色说话方式趋同",
                "避免情绪与动作缺少铺垫地突然升级",
            ],
            continuation_rules=[
                "保持当前叙事视角和叙事距离",
                "延续原章节长短句与段落节奏",
                "通过人物行动和对话推进设定与冲突",
                "结尾保留克制的悬念或情绪余韵",
            ],
        )


def _chapter_content_hash(chapter: Chapter) -> str:
    if chapter.content_hash:
        return chapter.content_hash
    return hashlib.sha256(chapter.content.encode("utf-8")).hexdigest()


def _safe_cache_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(". ")
    return cleaned or hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _style_cache_path(chapter_id: str, novel_id: str | None = None) -> Path:
    from app.services.project_paths import get_project_paths

    paths = get_project_paths()
    base = settings.style_cache_dir if paths.legacy else paths.analysis_style
    cache_root = base / _safe_cache_name(
        novel_id
        or (settings.style_cache_novel_id if paths.legacy else paths.project_id)
    )
    return cache_root / f"chapter_{_safe_cache_name(chapter_id)}.json"


def load_chapter_style_cache(
    chapter: Chapter,
    novel_id: str | None = None,
) -> ChapterStyleCacheEntry | None:
    path = _style_cache_path(chapter.chapter_id, novel_id)
    if not path.exists():
        return None
    try:
        entry = ChapterStyleCacheEntry.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    if (
        entry.chapter_id != chapter.chapter_id
        or entry.content_hash != _chapter_content_hash(chapter)
    ):
        return None
    return entry


def save_chapter_style_cache(
    entry: ChapterStyleCacheEntry,
    novel_id: str | None = None,
) -> Path:
    path = _style_cache_path(entry.chapter_id, novel_id)
    atomic_write_text(path, entry.model_dump_json(indent=2))
    return path


def _sample_chapter_text(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    head_size = max(1, int(max_chars * 0.3))
    middle_size = max(1, int(max_chars * 0.4))
    tail_size = max(1, max_chars - head_size - middle_size)
    middle_start = max(0, len(text) // 2 - middle_size // 2)
    return (
        "[章节开头]\n"
        + text[:head_size]
        + "\n\n[章节中段]\n"
        + text[middle_start : middle_start + middle_size]
        + "\n\n[章节结尾]\n"
        + text[-tail_size:]
    )


def _limit_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = max_chars * 2 // 3
    tail = max_chars - head
    return text[:head] + "\n\n[内容已截断]\n\n" + text[-tail:]


def _prompt_char_budget(max_chars: int, max_input_tokens: int) -> int:
    # Chinese text can approach one token per character, so use a conservative cap.
    return max(1000, min(max_chars, max_input_tokens))


def _estimate_input_tokens(text: str) -> int:
    return len(text)


def _parse_json_object_lenient(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = "\n".join(
            line for line in content.splitlines() if not line.startswith("```")
        ).strip()
    candidates = [content]
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        candidates.append(content[start : end + 1])
    for candidate in candidates:
        for normalized in (
            candidate,
            re.sub(r",\s*([}\]])", r"\1", candidate),
        ):
            try:
                parsed = json.loads(normalized)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def _is_timeout_error(exc: Exception) -> bool:
    lowered = f"{type(exc).__name__} {exc}".lower()
    return isinstance(exc, TimeoutError) or "timeout" in lowered or "超时" in lowered


def _style_json_to_dimensions(style: ChapterStyleJson) -> list[DimensionResult]:
    return [
        DimensionResult(
            dimension=AnalysisDimension.NARRATIVE_PERSPECTIVE,
            summary=style.narrative_pov,
            details={"narrative_pov": style.narrative_pov},
        ),
        DimensionResult(
            dimension=AnalysisDimension.SENTENCE_RHYTHM,
            summary=style.sentence_rhythm,
            details={
                "sentence_rhythm": style.sentence_rhythm,
                "language_style": style.language_style,
            },
        ),
        DimensionResult(
            dimension=AnalysisDimension.DIALOGUE_RATIO,
            summary=style.dialogue_style,
            details={"dialogue_style": style.dialogue_style},
        ),
        DimensionResult(
            dimension=AnalysisDimension.EMOTIONAL_ATMOSPHERE,
            summary=style.emotional_tone,
            details={"emotional_tone": style.emotional_tone},
        ),
        DimensionResult(
            dimension=AnalysisDimension.IMAGERY,
            summary="；".join(style.recurring_motifs) or "未提取到稳定意象。",
            details={"recurring_motifs": style.recurring_motifs},
            examples=style.recurring_motifs,
        ),
        DimensionResult(
            dimension=AnalysisDimension.DESCRIPTION_RATIO,
            summary=style.description_focus,
            details={"description_focus": style.description_focus},
        ),
        DimensionResult(
            dimension=AnalysisDimension.CHAPTER_STRUCTURE,
            summary=style.pacing,
            details={"pacing": style.pacing},
        ),
        DimensionResult(
            dimension=AnalysisDimension.CONFLICT_ADVANCEMENT,
            summary=style.pacing,
            details={
                "pacing": style.pacing,
                "continuation_rules": style.continuation_rules,
            },
        ),
        DimensionResult(
            dimension=AnalysisDimension.CHARACTER_VOICE,
            summary=style.character_portrayal,
            details={
                "character_portrayal": style.character_portrayal,
                "dialogue_style": style.dialogue_style,
            },
        ),
        DimensionResult(
            dimension=AnalysisDimension.CLIFFHANGER_STYLE,
            summary=(
                style.continuation_rules[-1]
                if style.continuation_rules
                else style.pacing
            ),
            details={
                "continuation_rules": style.continuation_rules,
                "taboo_or_constraints": style.taboo_or_constraints,
            },
        ),
        DimensionResult(
            dimension=AnalysisDimension.STYLE_SENSIBILITY,
            summary=style.language_style,
            details={
                "language_style": style.language_style,
                "worldbuilding_style": style.worldbuilding_style,
                "taboo_or_constraints": style.taboo_or_constraints,
            },
        ),
    ]


async def analyze_chapter_styles(
    chapters: list[Chapter],
    *,
    analyzer: StyleAnalyzer | None = None,
    summary_only: bool = False,
    progress_callback: Callable[[float, str, str], None] | None = None,
    diagnostics: dict | None = None,
) -> tuple[
    list[ChapterStyleCacheEntry],
    list[ChapterStyleJson],
    list[str],
    list[str],
]:
    analyzer = analyzer or StyleAnalyzer()
    entries: list[ChapterStyleCacheEntry] = []
    local_fallbacks: list[ChapterStyleJson] = []
    warnings: list[str] = []
    skipped: list[str] = []
    total = len(chapters)
    cached_count = 0
    analyzed_count = 0

    for index, chapter in enumerate(chapters, start=1):
        progress = 20 + (55 * (index - 1) / max(total, 1))
        if progress_callback:
            progress_callback(
                progress,
                f"分析第 {index}/{total} 章",
                f"正在处理《{chapter.title}》",
            )
        cached = load_chapter_style_cache(chapter)
        if cached and (cached.model_name != "rule_fallback" or not analyzer._client):
            entries.append(cached)
            cached_count += 1
            if progress_callback:
                progress_callback(
                    progress + 1,
                    "读取章节缓存",
                    f"《{chapter.title}》内容未变化，已复用缓存",
                )
            continue
        if summary_only:
            warning = f"《{chapter.title}》没有可复用的章节风格缓存"
            warnings.append(warning)
            skipped.append(chapter.chapter_id)
            continue

        sampled = _sample_chapter_text(
            chapter.content,
            settings.style_chapter_sample_chars,
        )
        fallback_style = analyzer._build_rule_style_json(chapter, sampled)
        try:
            entry, _cache_hit = await analyzer.analyze_chapter_style(
                chapter,
                fallback_style=fallback_style,
                diagnostics=diagnostics,
                use_cache=False,
            )
            entries.append(entry)
            analyzed_count += 1
            if entry.model_name == "rule_fallback":
                save_chapter_style_cache(entry)
                local_fallbacks.append(entry.style_json)
            if progress_callback:
                progress_callback(
                    progress + 2,
                    "保存章节缓存",
                    (
                        f"《{chapter.title}》使用规则分析"
                        if entry.model_name == "rule_fallback"
                        else f"《{chapter.title}》章节级风格缓存已保存"
                    ),
                )
        except ChapterStyleAnalysisError as exc:
            warnings.append(str(exc))
            skipped.append(chapter.chapter_id)
            local_fallbacks.append(fallback_style)
            if progress_callback:
                progress_callback(
                    progress + 2,
                    f"跳过第 {index}/{total} 章",
                    f"{exc}；已记录 warning，继续下一章",
                )

    if diagnostics is not None:
        diagnostics.update(
            chapter_style_total=total,
            chapter_style_cached=cached_count,
            chapter_style_analyzed=analyzed_count,
            chapter_style_skipped=len(skipped),
            warnings=warnings,
            skipped_chapter_ids=skipped,
        )
    return entries, local_fallbacks, warnings, skipped


def _compact_style_entry(entry: ChapterStyleCacheEntry) -> dict:
    style = entry.style_json
    return {
        "chapter_id": entry.chapter_id,
        "narrative_pov": style.narrative_pov[:160],
        "language_style": style.language_style[:160],
        "sentence_rhythm": style.sentence_rhythm[:160],
        "dialogue_style": style.dialogue_style[:160],
        "description_focus": style.description_focus[:160],
        "emotional_tone": style.emotional_tone[:160],
        "pacing": style.pacing[:160],
        "character_portrayal": style.character_portrayal[:160],
        "worldbuilding_style": style.worldbuilding_style[:160],
        "recurring_motifs": [item[:60] for item in style.recurring_motifs[:6]],
        "taboo_or_constraints": [
            item[:100] for item in style.taboo_or_constraints[:6]
        ],
        "continuation_rules": [item[:100] for item in style.continuation_rules[:8]],
    }


def _build_style_summary_payload(
    entries: list[ChapterStyleCacheEntry],
    max_chars: int,
) -> tuple[str, int]:
    records: list[dict] = []
    for entry in entries:
        candidate = records + [_compact_style_entry(entry)]
        encoded = json.dumps(candidate, ensure_ascii=False)
        if len(encoded) > max_chars and records:
            break
        records = candidate
    return json.dumps(records, ensure_ascii=False), len(records)


def _unique_strings(values: list[str], limit: int = 12) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _local_global_style(
    styles: list[ChapterStyleJson],
    *,
    analyzed_count: int,
    skipped: list[str],
    warnings: list[str],
) -> GlobalStyleKnowledge:
    return GlobalStyleKnowledge(
        global_narrative_style="；".join(
            _unique_strings([item.narrative_pov for item in styles], 5)
        )[:1200],
        global_language_style="；".join(
            _unique_strings([item.language_style for item in styles], 5)
        )[:1200],
        global_pacing_pattern="；".join(
            _unique_strings([item.pacing for item in styles], 5)
        )[:1200],
        global_character_rules=_unique_strings(
            [item.character_portrayal for item in styles]
            + [
                rule
                for item in styles
                for rule in item.continuation_rules
                if "人物" in rule or "角色" in rule
            ]
        ),
        global_dialogue_rules=_unique_strings(
            [item.dialogue_style for item in styles]
        ),
        global_worldbuilding_rules=_unique_strings(
            [item.worldbuilding_style for item in styles]
        ),
        plot_continuity_rules=_unique_strings(
            [rule for item in styles for rule in item.continuation_rules]
        ),
        do_not_write_list=_unique_strings(
            [rule for item in styles for rule in item.taboo_or_constraints]
        ),
        style_prompt_for_continuation=(
            "保持原作叙事视角、语言节奏、角色声音和设定展开方式；"
            "通过行动与对话推进冲突，避免集中说明和角色声音趋同。"
        ),
        analyzed_chapter_count=analyzed_count,
        skipped_chapter_ids=skipped,
        warnings=warnings,
        summary_source="local_fallback",
    )


async def summarize_global_style(
    entries: list[ChapterStyleCacheEntry],
    *,
    fallback_styles: list[ChapterStyleJson] | None = None,
    analyzer: StyleAnalyzer | None = None,
    warnings: list[str] | None = None,
    skipped: list[str] | None = None,
    progress_callback: Callable[[float, str, str], None] | None = None,
    diagnostics: dict | None = None,
) -> tuple[GlobalStyleKnowledge, Exception | None]:
    analyzer = analyzer or StyleAnalyzer()
    warnings = list(warnings or [])
    skipped = list(skipped or [])
    all_styles = [entry.style_json for entry in entries] + list(
        fallback_styles or []
    )
    local_summary = _local_global_style(
        all_styles,
        analyzed_count=len(entries),
        skipped=skipped,
        warnings=warnings,
    )
    if progress_callback:
        progress_callback(
            80,
            "汇总全书风格",
            f"正在汇总 {len(entries)} 份章节缓存，不再发送章节原文",
        )

    if not entries or not analyzer._client:
        return local_summary, None

    summary_budget = _prompt_char_budget(
        settings.style_summary_prompt_max_chars,
        settings.style_summary_max_input_tokens,
    )
    schema_overhead = len(_GLOBAL_STYLE_PROMPT.format(style_payload=""))
    payload, included_count = _build_style_summary_payload(
        entries,
        max(1000, summary_budget - schema_overhead),
    )
    prompt = _GLOBAL_STYLE_PROMPT.format(style_payload=payload)
    prompt = _limit_text(prompt, summary_budget)
    if progress_callback:
        progress_callback(
            84,
            "汇总全书风格",
            (
                f"汇总 Prompt 字符数：{len(prompt)}，"
                f"估算输入 token：{_estimate_input_tokens(prompt)}，"
                f"包含 {included_count}/{len(entries)} 份章节风格 JSON"
            ),
        )

    last_error: Exception | None = None
    repair_used = False
    for attempt in range(1, 3):
        try:
            parsed, repair_used = await analyzer._request_json_object(
                prompt,
                repair_used=repair_used,
            )
            merged = local_summary.model_dump(mode="json")
            merged.update(parsed)
            summary = GlobalStyleKnowledge.model_validate(merged).model_copy(
                update={
                    "analyzed_chapter_count": len(entries),
                    "skipped_chapter_ids": skipped,
                    "warnings": warnings,
                    "summary_source": "model",
                }
            )
            if diagnostics is not None:
                diagnostics.update(
                    summary_failed=False,
                    summary_prompt_chars=len(prompt),
                    summary_included_chapters=included_count,
                )
            return summary, None
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                await asyncio.sleep(
                    min(0.5, settings.model_timeout_seconds / 10)
                )

    failure = GlobalStyleSummaryError(
        "章节级分析已完成，最终汇总失败，可稍后仅重试汇总"
    )
    if diagnostics is not None:
        diagnostics.update(
            summary_failed=True,
            summary_error=str(last_error or failure),
            last_error=failure,
            summary_prompt_chars=len(prompt),
            summary_included_chapters=included_count,
        )
    fallback = local_summary.model_copy(
        update={"warnings": warnings + [str(failure)]}
    )
    return fallback, failure


def _parse_json_response(content: str) -> dict:
    """从 Claude 响应中解析 JSON，处理可能的 markdown 代码块包裹"""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        content = "\n".join(lines)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"raw_response": content, "parse_error": True}


def _normalize_examples(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, dict):
        return [
            f"{key}：{item}"
            for key, item in value.items()
            if item is not None and str(item).strip()
        ]
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [
            str(item)
            for item in value
            if item is not None and str(item).strip()
        ]
    return [str(value)]


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

async def analyze_chapter(
    chapter: Chapter,
    progress_callback: Callable[[float, str, str], None] | None = None,
    diagnostics: dict | None = None,
) -> list[DimensionResult]:
    """对单个章节执行全维度文风分析"""
    analyzer = StyleAnalyzer()
    return await analyzer.analyze(
        chapter,
        progress_callback=progress_callback,
        diagnostics=diagnostics,
    )


async def analyzeChapterStyle(
    chapter: Chapter,
    *,
    diagnostics: dict | None = None,
    use_cache: bool = True,
) -> ChapterStyleCacheEntry:
    """Public compatibility name for chapter-level structured style analysis."""
    analyzer = StyleAnalyzer()
    entry, _cache_hit = await analyzer.analyze_chapter_style(
        chapter,
        diagnostics=diagnostics,
        use_cache=use_cache,
    )
    return entry


async def summarizeGlobalStyle(
    entries: list[ChapterStyleCacheEntry],
    *,
    diagnostics: dict | None = None,
) -> GlobalStyleKnowledge:
    """Public compatibility name for global style summarization."""
    summary, error = await summarize_global_style(
        entries,
        diagnostics=diagnostics,
    )
    if error:
        raise error
    return summary
