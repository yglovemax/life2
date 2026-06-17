from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import AdminUser, FieldContract, ModelConfig, Module, Page, PromptTemplate
from app.services import hash_password


PAGE_SPECS = [
    {
        "slug": "birth-chart-reading",
        "name": "出生星盘解读页",
        "description": "基于用户出生资料生成个人星盘事实数据和模块解读。",
        "system_tags": ["占星", "本命", "星盘"],
        "algorithm_fields": {"required": ["user_profile", "birth_profile", "astrology_facts"]},
        "algorithm_data_template": "使用后端提供的星盘事实、出生资料和用户基础资料，不自行编造缺失事实。",
        "modules": [
            ("用户基础星盘信息", "birth-basic-chart-info"),
            ("出生星盘图", "birth-chart-wheel"),
            ("星盘表格数据", "birth-chart-table"),
            ("星盘详解", "birth-chart-detail"),
            ("占星主导模式", "birth-dominant-mode"),
            ("占星主导元素", "birth-dominant-element"),
            ("各宫位解读", "birth-house-reading"),
            ("星座特征", "birth-zodiac-traits"),
            ("星座符号", "birth-zodiac-symbols"),
            ("其他占星术", "birth-other-astrology"),
            ("占星肯定语", "birth-affirmations"),
        ],
    },
    {
        "slug": "daily-horoscope",
        "name": "每日星座运势页",
        "description": "按日期生成每日运势内容，支持缓存、并行和 Fallback。",
        "system_tags": ["占星", "日运", "星座"],
        "algorithm_fields": {"required": ["user_profile", "date", "astrology_facts"]},
        "algorithm_data_template": "使用后端提供的日期、星象和用户基础资料，不自行编造缺失事实。",
        "modules": [
            ("用户星座基础信息", "daily-zodiac-basic-info"),
            ("日运势天气分值", "daily-weather-score"),
            ("占星日运", "daily-astrology-reading"),
            ("事业运势", "daily-career"),
            ("爱情运势", "daily-love"),
            ("健康运势", "daily-health"),
            ("家庭运势", "daily-family"),
            ("财富运势", "daily-wealth"),
            ("学习运势", "daily-study"),
            ("每日寄语", "daily-message"),
            ("今日宜忌", "daily-do-dont"),
            ("今日塔罗", "daily-tarot"),
            ("塔罗问答", "daily-tarot-qa"),
            ("生物节律", "daily-biorhythm"),
            ("月相历", "daily-moon-phase"),
            ("关键星象事件", "daily-key-transits"),
            ("每日占星 Tips", "daily-astrology-tips"),
            ("周运势", "daily-weekly-reading"),
            ("月运势", "daily-monthly-reading"),
            ("年运势", "daily-yearly-reading"),
        ],
    },
    {
        "slug": "bazi-birth-reading",
        "name": "八字命盘解读页",
        "description": "基于四柱、日主、五行和十神等事实生成八字本命解读。",
        "system_tags": ["八字", "本命", "四柱"],
        "algorithm_fields": {"required": ["user_profile", "birth_profile", "bazi_facts"]},
        "algorithm_data_template": "使用后端提供的四柱、日主、五行、十神和命盘事实，不自行编造缺失八字信息。",
        "modules": [
            ("用户基础八字信息", "bazi-basic-profile"),
            ("八字排盘结果", "bazi-chart-pillars"),
            ("日主与格局", "bazi-day-master-pattern"),
            ("五行能量分布", "bazi-five-elements-balance"),
            ("十神关系解读", "bazi-ten-gods-reading"),
            ("事业财运主题", "bazi-career-wealth-reading"),
            ("感情关系主题", "bazi-relationship-reading"),
            ("大运流年提示", "bazi-luck-cycle-reading"),
        ],
    },
    {
        "slug": "bazi-daily-reading",
        "name": "八字每日运势页",
        "description": "结合日期和八字基础事实生成每日提醒、节奏建议和行动提示。",
        "system_tags": ["八字", "日运", "流日"],
        "algorithm_fields": {"required": ["user_profile", "date", "bazi_facts", "daily_transit"]},
        "algorithm_data_template": "使用后端提供的日期、八字基础事实和流日/流月数据，不自行编造缺失运势事实。",
        "modules": [
            ("今日八字总览", "bazi-daily-overview"),
            ("今日事业节奏", "bazi-daily-career"),
            ("今日感情提醒", "bazi-daily-love"),
            ("今日财富提醒", "bazi-daily-wealth"),
            ("今日行动建议", "bazi-daily-action"),
            ("今日避坑提醒", "bazi-daily-caution"),
            ("今日贵人协作", "bazi-daily-support"),
            ("今日能量提示", "bazi-daily-energy"),
        ],
    },
]


def prompt_payload_for(page_spec: dict, module_name: str, module_slug: str) -> dict:
    shared_prefix = "你是 Nexa 占卜 APP 的 AI 内容模块。保持温暖、清晰、克制，不做医疗、法律、投资等高风险承诺。"
    module_rules = f"为「{page_spec['name']} / {module_name}」生成结构化内容，必须遵守字段契约，避免绝对化表达。"
    if module_slug.startswith("bazi-"):
        module_rules = (
            f"为「{page_spec['name']} / {module_name}」生成结构化八字内容。"
            "必须优先使用后端提供的八字、四柱、日主、五行、十神和流日事实；"
            "缺失的盘面事实要明确标注为缺失，不要自行补造。"
        )
    return {
        "shared_prefix": shared_prefix,
        "module_rules": module_rules,
        "algorithm_data_template": page_spec["algorithm_data_template"],
        "user_preferences_template": "结合用户昵称、语气偏好、信息密度偏好，但只使用当前模块必要信息。",
        "final_request_template": "请输出合法 JSON，不要 Markdown，不要额外解释。",
    }


def field_specs_for(page_spec: dict, module_name: str, module_slug: str) -> list[dict]:
    specs = [
        {
            "field_name": "title",
            "purpose": "模块标题或前端展示标题",
            "display_position": f"{page_spec['name']} / {module_name}",
            "example": module_name,
            "source": "fixed_config",
            "is_ai_generated": False,
            "owner": "产品",
        },
        {
            "field_name": "summary",
            "purpose": "模块核心解读内容",
            "display_position": f"{page_spec['name']} / {module_name}",
            "example": f"这里展示{module_name}的核心解释。",
            "source": "ai",
            "is_ai_generated": True,
            "owner": "Prompt",
        },
    ]
    if module_slug == "bazi-day-master-pattern":
        specs.extend(
            [
                {
                    "field_name": "day_master",
                    "purpose": "用户八字日主，来自后端盘面事实。",
                    "display_position": f"{page_spec['name']} / {module_name}",
                    "example": "乙木",
                    "source": "algorithm",
                    "is_ai_generated": False,
                    "owner": "算法",
                },
                {
                    "field_name": "pattern_summary",
                    "purpose": "围绕日主、四柱和格局给出的核心判断。",
                    "display_position": f"{page_spec['name']} / {module_name}",
                    "example": "乙木日主重视生长、协作和持续调整，需要结合四柱旺衰判断表达方式。",
                    "source": "ai",
                    "is_ai_generated": True,
                    "owner": "Prompt",
                },
                {
                    "field_name": "strength_hint",
                    "purpose": "日主强弱或当前可判断范围的提示。",
                    "display_position": f"{page_spec['name']} / {module_name}",
                    "example": "当前只提供四柱基础信息，旺衰判断需要大运、藏干和月令细化后确认。",
                    "source": "ai",
                    "is_ai_generated": True,
                    "owner": "Prompt",
                },
                {
                    "field_name": "action_advice",
                    "purpose": "给用户的低风险行动建议。",
                    "display_position": f"{page_spec['name']} / {module_name}",
                    "example": "先把重点放在稳定节奏和持续输出上，避免一次性承担过多承诺。",
                    "source": "ai",
                    "is_ai_generated": True,
                    "owner": "Prompt",
                },
            ]
        )
    elif module_slug.startswith("bazi-"):
        specs.append(
            {
                "field_name": "action_advice",
                "purpose": "基于八字事实生成的低风险行动建议。",
                "display_position": f"{page_spec['name']} / {module_name}",
                "example": "用一个小行动验证今天的节奏，不做重大承诺。",
                "source": "ai",
                "is_ai_generated": True,
                "owner": "Prompt",
            }
        )
    return specs


def ensure_module_prompt(session: Session, module: Module, page_spec: dict, module_name: str, module_slug: str) -> None:
    payload = prompt_payload_for(page_spec, module_name, module_slug)
    if module.prompt is None:
        session.add(PromptTemplate(module_id=module.id, **payload))
        return
    if module_slug.startswith("bazi-") and (
        "八字" not in (module.prompt.module_rules or "") or "四柱" not in (module.prompt.algorithm_data_template or "")
    ):
        module.prompt.shared_prefix = payload["shared_prefix"]
        module.prompt.module_rules = payload["module_rules"]
        module.prompt.algorithm_data_template = payload["algorithm_data_template"]
        module.prompt.user_preferences_template = payload["user_preferences_template"]
        module.prompt.final_request_template = payload["final_request_template"]
        module.prompt.version = (module.prompt.version or 1) + 1


def ensure_field_contracts(session: Session, module: Module, page_spec: dict, module_name: str, module_slug: str) -> None:
    existing_fields = {field.field_name for field in module.fields}
    for spec in field_specs_for(page_spec, module_name, module_slug):
        if spec["field_name"] in existing_fields:
            continue
        session.add(FieldContract(module_id=module.id, **spec))


def ensure_seed_data(session: Session) -> None:
    ensure_admin_user(session)
    mini_model = ensure_model_config(
        session,
        provider="openai",
        name="gpt-5.4-mini",
        display_name="GPT-5.4 Mini",
        quality_tier="standard",
        input_cost_per_1m=75,
        output_cost_per_1m=450,
    )
    premium_model = ensure_model_config(
        session,
        provider="openai",
        name="gpt-5.5",
        display_name="GPT-5.5",
        quality_tier="premium",
        input_cost_per_1m=500,
        output_cost_per_1m=3000,
    )

    pages_by_slug = {page.slug: page for page in session.scalars(select(Page)).all()}
    modules_by_slug = {module.slug: module for module in session.scalars(select(Module)).all()}

    for page_spec in PAGE_SPECS:
        page = pages_by_slug.get(page_spec["slug"])
        if page is None:
            page = Page(slug=page_spec["slug"], name=page_spec["name"], description=page_spec["description"])
            session.add(page)
            session.flush()
            pages_by_slug[page.slug] = page
        elif not page.description:
            page.description = page_spec["description"]

        for index, (module_name, module_slug) in enumerate(page_spec["modules"], start=1):
            module = modules_by_slug.get(module_slug)
            if module is None:
                module = Module(
                    page_id=page.id,
                    model_id=mini_model.id if index % 4 else premium_model.id,
                    slug=module_slug,
                    name=module_name,
                    owner="产品 / Prompt",
                    status="draft",
                    fallback_content=f"{module_name}暂时使用备用内容，请稍后重试。",
                    algorithm_fields=page_spec["algorithm_fields"],
                    knowledge_tags=unique_tags([*page_spec["system_tags"], page.name, module_name]),
                )
                session.add(module)
                session.flush()
                modules_by_slug[module.slug] = module
            else:
                if not module.algorithm_fields or module_slug.startswith("bazi-"):
                    module.algorithm_fields = page_spec["algorithm_fields"]
                if not module.knowledge_tags:
                    module.knowledge_tags = unique_tags([*page_spec["system_tags"], page.name, module_name])
                if not module.fallback_content:
                    module.fallback_content = f"{module_name}暂时使用备用内容，请稍后重试。"

            ensure_module_prompt(session, module, page_spec, module_name, module_slug)
            ensure_field_contracts(session, module, page_spec, module_name, module_slug)

    session.commit()


def ensure_model_config(
    session: Session,
    *,
    provider: str,
    name: str,
    display_name: str,
    quality_tier: str,
    input_cost_per_1m: int,
    output_cost_per_1m: int,
) -> ModelConfig:
    model = session.scalar(select(ModelConfig).where(ModelConfig.name == name))
    if model is not None:
        return model
    model = ModelConfig(
        provider=provider,
        name=name,
        display_name=display_name,
        quality_tier=quality_tier,
        input_cost_per_1m=input_cost_per_1m,
        output_cost_per_1m=output_cost_per_1m,
    )
    session.add(model)
    session.flush()
    return model


def unique_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for tag in tags:
        clean = str(tag or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        rows.append(clean)
    return rows


def ensure_admin_user(session: Session) -> None:
    settings = get_settings()
    username = settings.admin_username.strip() or "admin"
    existing = session.scalar(select(AdminUser).where(AdminUser.username == username))
    if existing is not None:
        return
    session.add(
        AdminUser(
            username=username,
            password_hash=hash_password(settings.admin_password),
            role="owner",
            status="active",
        )
    )
    session.commit()
