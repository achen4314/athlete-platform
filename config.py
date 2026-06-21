"""
运动员数据分析平台 - 配置文件
"""
import os

class Config:
    """应用配置"""
    SECRET_KEY = os.environ.get("SECRET_KEY", "athlete-platform-dev-secret-key")

    # SQLite 本地数据库
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DATABASE = os.path.join(BASE_DIR, "athlete_data.db")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{DATABASE}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # DeepSeek API
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.environ.get(
        "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
    )
    DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    # 会话
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = 86400 * 7  # 7天

    DEBUG = True


class BrandConfig:
    """平台品牌/视觉配置"""
    # 品牌色
    PRIMARY_GREEN = "#a0c040"
    DARK_TEAL = "#204040"
    GOLD = "#c0c060"
    LIGHT_GRAY = "#e0e0e0"
    CARD_BG = "#f2f4f0"

    # 深色主题
    DARK_BG = "#1a1a2e"
    DARK_SURFACE = "#16213e"
    DARK_CARD = "#0f3460"

    # 平台名称
    BRAND_NAME = "运动员数据分析平台"
    BRAND_SHORT = "运动员平台"

    # 角色定义
    ROLES = ["athlete", "coach", "doctor", "analyst", "admin"]
    ROLE_LABELS = {
        "athlete": "运动员",
        "coach": "教练",
        "doctor": "队医",
        "analyst": "分析师",
        "admin": "管理员",
    }


class AIPrompt:
    """AI 对话提示词模板"""

    SYSTEM_PROMPT = """你是一名资深体能教练助手，服务于运动员训练数据分析平台。
你的职责是帮助运动员和教练分析训练数据、评估运动表现、提供训练建议。

## 你的能力
1. **数据分析**：解读运动员的身体指标、测试成绩、训练日志
2. **表现评估**：基于数据判断运动员的强项和弱项
3. **训练建议**：提供科学、个性化的训练调整建议
4. **伤病预防**：识别过度训练风险信号
5. **运动科学**：解答训练学、运动生理学、营养学问题

## 回复风格
- 使用中文，专业但易懂
- 数据驱动，引用具体数值
- 结构化输出，善用表格和列表
- 语气积极鼓励，但保持客观专业
- 涉及伤病诊断时，强调需要队医确认

## 注意事项
- 你是辅助工具，不能替代专业教练和医生的判断
- 对于不确定的问题，诚实说明并建议咨询专业人士
- 保护运动员隐私，不随意泄露个人数据"""

    CONTEXT_TEMPLATE = """## 当前运动员信息
{athlete_context}

## 对话历史
{history}

## 用户问题
{question}

请基于以上信息给出专业回答："""

    DIAGNOSIS_PROMPT = """## 运动员诊断分析
请基于以下运动员数据，提供专业的训练诊断报告：

### 基本信息
{athlete_info}

### 近期数据
{recent_data}

### 分析要求
1. 识别优势领域（T-score > 60 的项目）
2. 标记需关注领域（T-score < 40 或下降趋势）
3. 评估整体负荷状态
4. 给出下周训练重点建议
5. 如有风险信号，标注风险等级（低/中/高）

请以结构化报告形式输出："""
