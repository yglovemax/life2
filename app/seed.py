from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models import AdminUser, FieldContract, ModelConfig, Module, Page, PromptTemplate
from app.services import hash_password


BIRTH_CHART_MODULES = [
    "用户基础星盘信息",
    "出生星盘图",
    "星盘表格数据",
    "星盘详解",
    "占星主导模式",
    "占星主导元素",
    "各宫位解读",
    "星座特征",
    "星座符号",
    "其他占星术",
    "占星肯定语",
]

DAILY_HOROSCOPE_MODULES = [
    "用户星座基础信息",
    "日运势天气分值",
    "占星日运",
    "事业运势",
    "爱情运势",
    "健康运势",
    "家庭运势",
    "财富运势",
    "学习运势",
    "每日寄语",
    "今日宜忌",
    "今日塔罗",
    "塔罗问答",
    "生物节律",
    "月相历",
    "关键星象事件",
    "每日占星 Tips",
    "周运势",
    "月运势",
    "年运势",
]


def slugify_name(name: str) -> str:
    mapping = {
        "用户基础星盘信息": "birth-basic-chart-info",
        "出生星盘图": "birth-chart-wheel",
        "星盘表格数据": "birth-chart-table",
        "星盘详解": "birth-chart-detail",
        "占星主导模式": "birth-dominant-mode",
        "占星主导元素": "birth-dominant-element",
        "各宫位解读": "birth-house-reading",
        "星座特征": "birth-zodiac-traits",
        "星座符号": "birth-zodiac-symbols",
        "其他占星术": "birth-other-astrology",
        "占星肯定语": "birth-affirmations",
        "用户星座基础信息": "daily-zodiac-basic-info",
        "日运势天气分值": "daily-weather-score",
        "占星日运": "daily-astrology-reading",
        "事业运势": "daily-career",
        "爱情运势": "daily-love",
        "健康运势": "daily-health",
        "家庭运势": "daily-family",
        "财富运势": "daily-wealth",
        "学习运势": "daily-study",
        "每日寄语": "daily-message",
        "今日宜忌": "daily-do-dont",
        "今日塔罗": "daily-tarot",
        "塔罗问答": "daily-tarot-qa",
        "生物节律": "daily-biorhythm",
        "月相历": "daily-moon-phase",
        "关键星象事件": "daily-key-transits",
        "每日占星 Tips": "daily-astrology-tips",
        "周运势": "daily-weekly-reading",
        "月运势": "daily-monthly-reading",
        "年运势": "daily-yearly-reading",
    }
    return mapping[name]


def ensure_seed_data(session: Session) -> None:
    ensure_admin_user(session)

    if session.scalar(select(Page).limit(1)):
        return

    mini_model = ModelConfig(
        provider="openai",
        name="gpt-5.4-mini",
        display_name="GPT-5.4 Mini",
        quality_tier="standard",
        input_cost_per_1m=75,
        output_cost_per_1m=450,
    )
    premium_model = ModelConfig(
        provider="openai",
        name="gpt-5.5",
        display_name="GPT-5.5",
        quality_tier="premium",
        input_cost_per_1m=500,
        output_cost_per_1m=3000,
    )
    session.add_all([mini_model, premium_model])
    session.flush()

    birth_page = Page(
        slug="birth-chart-reading",
        name="出生星盘解读页",
        description="基于用户出生资料生成个人星盘事实数据和模块解读。",
    )
    daily_page = Page(
        slug="daily-horoscope",
        name="每日星座运势页",
        description="按日期生成每日运势内容，支持缓存、并行和 Fallback。",
    )
    session.add_all([birth_page, daily_page])
    session.flush()

    for page, names in [(birth_page, BIRTH_CHART_MODULES), (daily_page, DAILY_HOROSCOPE_MODULES)]:
        for index, name in enumerate(names, start=1):
            module = Module(
                page_id=page.id,
                model_id=mini_model.id if index % 4 else premium_model.id,
                slug=slugify_name(name),
                name=name,
                owner="产品 / Prompt",
                status="draft",
                fallback_content=f"{name}暂时使用备用内容，请稍后重试。",
                algorithm_fields={"required": ["user_profile", "date", "astrology_facts"]},
                knowledge_tags=["占星", page.name, name],
            )
            session.add(module)
            session.flush()

            session.add(
                PromptTemplate(
                    module_id=module.id,
                    shared_prefix="你是 Nexa 占卜 APP 的 AI 内容模块。保持温暖、清晰、克制，不做医疗、法律、投资等高风险承诺。",
                    module_rules=f"为「{page.name} / {name}」生成结构化内容，必须遵守字段契约，避免绝对化表达。",
                    algorithm_data_template="使用后端提供的星盘事实、日期、星象、用户基础资料，不自行编造缺失事实。",
                    user_preferences_template="结合用户昵称、语气偏好、信息密度偏好，但只使用当前模块必要信息。",
                    final_request_template="请输出合法 JSON，不要 Markdown，不要额外解释。",
                )
            )
            session.add_all(
                [
                    FieldContract(
                        module_id=module.id,
                        field_name="title",
                        purpose="模块标题或前端展示标题",
                        display_position=f"{page.name} / {name}",
                        example=name,
                        source="fixed_config",
                        is_ai_generated=False,
                        owner="产品",
                    ),
                    FieldContract(
                        module_id=module.id,
                        field_name="summary",
                        purpose="模块核心解读内容",
                        display_position=f"{page.name} / {name}",
                        example=f"这里展示{name}的核心解释。",
                        source="ai",
                        is_ai_generated=True,
                        owner="Prompt",
                    ),
                ]
            )

    session.commit()


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
