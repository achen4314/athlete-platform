"""
运动员数据分析平台 - PDF 报告导出
使用 reportlab 生成真正的 PDF 文件，支持中文
"""
import os
import io
from datetime import date
from urllib.parse import quote

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from models import Athlete, BodyMetric, TestRecord, ChatMessage, FitnessTest
from analysis_engine import ScoreAnalyzer, RADAR_CATEGORIES


# ═══════════════════════════════════════════════════════════════════════════
# 品牌色
# ═══════════════════════════════════════════════════════════════════════════
SSP_GREEN = HexColor("#a0c040")
SSP_TEAL = HexColor("#204040")
SSP_GOLD = HexColor("#c0c060")
SSP_LIGHT_GRAY = HexColor("#e0e0e0")
SSP_CARD_BG = HexColor("#f2f4f0")
SSP_RED = HexColor("#e05555")
SSP_DARK_TEXT = HexColor("#333333")
SSP_GRAY_TEXT = HexColor("#888888")


# ═══════════════════════════════════════════════════════════════════════════
# 中文字体注册
# ═══════════════════════════════════════════════════════════════════════════

def _register_chinese_font():
    """尝试注册中文字体，返回 (regular_name, bold_name)"""
    # 候选字体路径（按优先级）
    candidates = [
        # Windows
        ("C:/Windows/Fonts/msyh.ttc", "Microsoft YaHei"),
        ("C:/Windows/Fonts/msyhbd.ttc", "Microsoft YaHei Bold"),
        ("C:/Windows/Fonts/simsun.ttc", "SimSun"),
        ("C:/Windows/Fonts/simhei.ttf", "SimHei"),
        # macOS
        ("/System/Library/Fonts/PingFang.ttc", "PingFang SC"),
        ("/System/Library/Fonts/STHeiti Light.ttc", "STHeiti"),
        ("/Library/Fonts/Arial Unicode.ttf", "Arial Unicode"),
        # Linux
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK"),
        ("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf", "DroidSansFallback"),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "WenQuanYi Zen Hei"),
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "WenQuanYi Micro Hei"),
    ]

    registered = {}
    for path, name in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                registered[name] = path
                if len(registered) >= 2:
                    break
            except Exception:
                continue

    if not registered:
        # 回退：尝试使用 reportlab 内置的 CID 字体
        try:
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
            return 'STSong-Light', 'STSong-Light'
        except Exception:
            pass
        # 最终回退到 Helvetica（不支持中文，但至少不崩溃）
        print("[WARNING] 未找到中文字体，PDF 中文将无法显示")
        return 'Helvetica', 'Helvetica-Bold'

    # 返回第一个注册的字体作为 regular，有粗体则用粗体
    names = list(registered.keys())
    regular = names[0]
    bold = names[1] if len(names) > 1 else regular
    return regular, bold


# 全局字体名
CN_FONT, CN_FONT_BOLD = _register_chinese_font()


# ═══════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════════

def t_color(t):
    """T-score 对应颜色 (返回 HexColor)"""
    if t is None:
        return SSP_GRAY_TEXT
    if t >= 60:
        return SSP_GREEN
    if t >= 45:
        return SSP_GOLD
    return SSP_RED


def t_color_hex(t):
    """T-score 对应颜色 (返回 hex 字符串, 如 #a0c040)"""
    h = t_color(t).hexval()
    return '#' + h[2:]  # 0xa0c040 → #a0c040


def t_label(t):
    """T-score 评级标签"""
    if t is None:
        return "—"
    if t >= 65:
        return "优秀"
    if t >= 55:
        return "良好"
    if t >= 45:
        return "平均水平"
    if t >= 35:
        return "需提升"
    return "亟待改善"


# ═══════════════════════════════════════════════════════════════════════════
# 段落样式
# ═══════════════════════════════════════════════════════════════════════════

STYLE_TITLE = ParagraphStyle(
    'Title_CN', fontName=CN_FONT_BOLD, fontSize=18, leading=26,
    textColor=SSP_TEAL, alignment=TA_CENTER, spaceAfter=4*mm,
)
STYLE_SUBTITLE = ParagraphStyle(
    'Subtitle_CN', fontName=CN_FONT, fontSize=9, leading=14,
    textColor=SSP_GRAY_TEXT, alignment=TA_CENTER, spaceAfter=8*mm,
)
STYLE_H2 = ParagraphStyle(
    'H2_CN', fontName=CN_FONT_BOLD, fontSize=13, leading=18,
    textColor=SSP_TEAL, spaceBefore=6*mm, spaceAfter=4*mm,
    borderPadding=(0, 0, 0, 8),
)
STYLE_BODY = ParagraphStyle(
    'Body_CN', fontName=CN_FONT, fontSize=9, leading=15,
    textColor=SSP_DARK_TEXT,
)
STYLE_BODY_SMALL = ParagraphStyle(
    'BodySmall_CN', fontName=CN_FONT, fontSize=8, leading=12,
    textColor=SSP_GRAY_TEXT,
)
STYLE_CELL = ParagraphStyle(
    'Cell_CN', fontName=CN_FONT, fontSize=8, leading=11,
    textColor=SSP_DARK_TEXT,
)
STYLE_CELL_BOLD = ParagraphStyle(
    'CellBold_CN', fontName=CN_FONT_BOLD, fontSize=8, leading=11,
    textColor=SSP_DARK_TEXT,
)
STYLE_CELL_CENTER = ParagraphStyle(
    'CellCenter_CN', fontName=CN_FONT, fontSize=8, leading=11,
    textColor=SSP_DARK_TEXT, alignment=TA_CENTER,
)
STYLE_FOOTER = ParagraphStyle(
    'Footer_CN', fontName=CN_FONT, fontSize=7, leading=10,
    textColor=SSP_GRAY_TEXT, alignment=TA_CENTER,
)


# ═══════════════════════════════════════════════════════════════════════════
# PDFReport 类
# ═══════════════════════════════════════════════════════════════════════════

class PDFReport:
    """PDF 报告生成器"""

    def __init__(self):
        self.analyzer = ScoreAnalyzer()
        self.width, self.height = A4

    # ── 页面模板 ──────────────────────────────────────────────────────────

    @staticmethod
    def _on_first_page(canvas, doc):
        """首页装饰"""
        canvas.saveState()
        # 顶部色带
        canvas.setFillColor(SSP_GREEN)
        canvas.rect(0, doc.height + doc.topMargin - 6*mm,
                     doc.width + doc.leftMargin + doc.rightMargin, 6*mm,
                     fill=1, stroke=0)
        # 底部色带
        canvas.setFillColor(SSP_TEAL)
        canvas.rect(0, doc.bottomMargin - 6*mm,
                     doc.width + doc.leftMargin + doc.rightMargin, 3*mm,
                     fill=1, stroke=0)
        canvas.restoreState()

    @staticmethod
    def _on_later_pages(canvas, doc):
        """后续页装饰"""
        canvas.saveState()
        canvas.setFillColor(SSP_TEAL)
        canvas.rect(0, doc.bottomMargin - 4*mm,
                     doc.width + doc.leftMargin + doc.rightMargin, 1.5*mm,
                     fill=1, stroke=0)
        canvas.setFont(CN_FONT, 7)
        canvas.setFillColor(SSP_GRAY_TEXT)
        canvas.drawRightString(doc.width + doc.leftMargin - 10*mm,
                                doc.bottomMargin - 8*mm,
                                f"第 {canvas.getPageNumber()} 页")
        canvas.restoreState()

    # ── 分隔线 ────────────────────────────────────────────────────────────

    def _hr(self):
        return HRFlowable(
            width="100%", thickness=0.5, color=SSP_LIGHT_GRAY,
            spaceBefore=2*mm, spaceAfter=2*mm,
        )

    # ── 报告生成主方法 ────────────────────────────────────────────────────

    def generate_athlete_report(self, athlete_id, db_session) -> bytes:
        """
        生成运动员综合分析 PDF 报告

        Args:
            athlete_id: 运动员 ID
            db_session: SQLAlchemy 会话

        Returns:
            bytes: PDF 文件的字节流
        """
        athlete = Athlete.query.get(athlete_id)
        if not athlete:
            raise ValueError("运动员不存在")

        profile = self.analyzer.athlete_profile(athlete_id, db_session)
        radar = self.analyzer.radar_data(athlete_id, db_session)
        body_metric = BodyMetric.query.filter_by(athlete_id=athlete_id) \
            .order_by(BodyMetric.record_date.desc()).first()

        # 创建 PDF 缓冲区
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=18*mm, rightMargin=18*mm,
            topMargin=20*mm, bottomMargin=20*mm,
        )

        story = []

        # ═══════════════════════════════════════════════════════════
        # 页首标题
        # ═══════════════════════════════════════════════════════════
        story.append(Paragraph("运动员数据分析平台", STYLE_TITLE))
        story.append(Paragraph("运动员综合分析报告", STYLE_TITLE))
        story.append(Paragraph(
            f"运动员数据分析平台  |  生成日期：{date.today().isoformat()}",
            STYLE_SUBTITLE,
        ))
        story.append(self._hr())

        # ═══════════════════════════════════════════════════════════
        # 1. 基本信息
        # ═══════════════════════════════════════════════════════════
        story.append(Paragraph("📋 基本信息", STYLE_H2))

        composite_t = profile.get('composite_t_score', '—')
        composite_t_str = f"{composite_t:.1f}" if isinstance(composite_t, (int, float)) else str(composite_t)

        info_data = [
            ["姓名", athlete.name or "—", "项目", athlete.sport_type or "—"],
            ["位置", athlete.position or "—", "等级", athlete.level or "—"],
            ["年龄", f"{athlete.age} 岁" if athlete.age else "—",
             "训练年限", f"{athlete.training_years} 年" if athlete.training_years else "—"],
            ["身高", f"{athlete.height_cm} cm" if athlete.height_cm else "—",
             "体重", f"{athlete.weight_kg} kg" if athlete.weight_kg else "—"],
            ["综合T分", composite_t_str,
             "最近测量", body_metric.record_date.isoformat() if body_metric else "—"],
        ]

        info_table = self._make_info_table(info_data)
        story.append(info_table)
        story.append(Spacer(1, 4*mm))

        # ═══════════════════════════════════════════════════════════
        # 2. 能力画像（雷达图文字摘要）
        # ═══════════════════════════════════════════════════════════
        story.append(Paragraph("🎯 八大维度能力画像", STYLE_H2))

        if radar.get("categories"):
            dim_data = [["维度", "T分", "评级", "进度条"]]
            for i, cat in enumerate(radar["categories"]):
                val = radar["t_scores"][i] if i < len(radar["t_scores"]) else 50
                pct = int(min(100, max(0, (val - 30) / 40 * 100)))
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                color = t_color(val)
                dim_data.append([
                    Paragraph(cat, STYLE_CELL_BOLD),
                    Paragraph(f'{val:.1f}', ParagraphStyle(
                        'Val_C', parent=STYLE_CELL_CENTER, textColor=color,
                        fontName=CN_FONT_BOLD,
                    )),
                    Paragraph(t_label(val), ParagraphStyle(
                        'Label_C', parent=STYLE_CELL_CENTER, textColor=color,
                    )),
                    Paragraph(bar, ParagraphStyle(
                        'Bar_C', parent=STYLE_CELL, fontSize=6, textColor=color,
                    )),
                ])

            dim_table = Table(dim_data, colWidths=[60, 40, 56, 260])
            dim_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), SSP_TEAL),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('FONTNAME', (0, 0), (-1, 0), CN_FONT_BOLD),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('ALIGN', (1, 0), (2, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.5, SSP_LIGHT_GRAY),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, SSP_CARD_BG]),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(dim_table)
        else:
            story.append(Paragraph("暂无数据", STYLE_BODY_SMALL))

        story.append(Spacer(1, 4*mm))

        # ═══════════════════════════════════════════════════════════
        # 3. 测试明细表
        # ═══════════════════════════════════════════════════════════
        story.append(Paragraph("📊 测试明细 Z/T-score 表", STYLE_H2))

        scores = profile.get("scores", [])[:20]
        if scores:
            table_data = [["测试项目", "原始值", "Z-score", "T-score", "百分位", "评级"]]
            for s in scores:
                zs = s.get('z_score')
                ts = s.get('t_score')
                unit = s.get('unit', '')
                raw_str = f"{s['raw_value']} {unit}" if unit else str(s['raw_value'])
                table_data.append([
                    Paragraph(s['test_name'], STYLE_CELL_BOLD),
                    Paragraph(raw_str, STYLE_CELL),
                    Paragraph(f"{zs:.2f}" if zs is not None else "—", ParagraphStyle(
                        'Z_C', parent=STYLE_CELL_CENTER, textColor=t_color(zs),
                    )),
                    Paragraph(f"{ts:.1f}" if ts is not None else "—", ParagraphStyle(
                        'T_C', parent=STYLE_CELL_CENTER, textColor=t_color(ts),
                        fontName=CN_FONT_BOLD,
                    )),
                    Paragraph(f"{s.get('percentile', '—')}%" if s.get('percentile') is not None else "—",
                              STYLE_CELL_CENTER),
                    Paragraph(t_label(ts), ParagraphStyle(
                        'R_C', parent=STYLE_CELL_CENTER, textColor=t_color(ts),
                    )),
                ])

            col_widths = [100, 68, 60, 60, 52, 60]
            test_table = Table(table_data, colWidths=col_widths)
            test_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), SSP_TEAL),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('FONTNAME', (0, 0), (-1, 0), CN_FONT_BOLD),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('ALIGN', (2, 0), (4, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.5, SSP_LIGHT_GRAY),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, SSP_CARD_BG]),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(test_table)
        else:
            story.append(Paragraph("暂无测试记录", STYLE_BODY_SMALL))

        story.append(Spacer(1, 4*mm))

        # ═══════════════════════════════════════════════════════════
        # 4. 趋势分析摘要
        # ═══════════════════════════════════════════════════════════
        story.append(Paragraph("📈 趋势分析摘要", STYLE_H2))

        # 取测试记录最多的项目做趋势
        from collections import Counter
        all_records = TestRecord.query.filter_by(athlete_id=athlete_id) \
            .order_by(TestRecord.test_date.asc()).all()
        test_counter = Counter(r.test_id for r in all_records)

        if test_counter:
            top_test_id = test_counter.most_common(1)[0][0]
            trend = self.analyzer.analyze_trends(athlete_id, top_test_id, db_session)

            direction_map = {
                "improving": "📈 上升趋势",
                "declining": "📉 下降趋势",
                "stable": "➡️ 保持稳定",
                "insufficient_data": "⚠️ 数据不足",
            }
            direction_label = direction_map.get(trend.get("direction", ""), "—")
            r2 = trend.get("r_squared")
            slope = trend.get("slope")

            trend_text = (
                f"<b>测试项目：</b>{trend.get('test_name', '—')}　"
                f"<b>数据点数：</b>{trend.get('point_count', 0)}　"
                f"<b>趋势方向：</b>{direction_label}"
            )
            if r2 is not None and slope is not None:
                trend_text += (
                    f"　<b>R²：</b>{r2:.3f}　<b>斜率：</b>{slope:+.4f}/天"
                )
            story.append(Paragraph(trend_text, STYLE_BODY))
        else:
            story.append(Paragraph("暂无趋势数据", STYLE_BODY_SMALL))

        story.append(Spacer(1, 4*mm))

        # ═══════════════════════════════════════════════════════════
        # 5. AI 诊断建议
        # ═══════════════════════════════════════════════════════════
        story.append(Paragraph("🤖 AI 诊断建议", STYLE_H2))

        last_chat = ChatMessage.query.filter_by(
            user_id=athlete.user_id, role="assistant"
        ).order_by(ChatMessage.created_at.desc()).first()

        if last_chat:
            # 截取前 800 字
            ai_text = last_chat.content[:800]
            if len(last_chat.content) > 800:
                ai_text += "……（更多内容请查看平台 AI 对话）"
            story.append(Paragraph(ai_text.replace('\n', '<br/>'), STYLE_BODY))
        else:
            # 生成自动摘要
            strengths = [s['test_name'] for s in scores
                         if s.get('t_score') is not None and s['t_score'] >= 60][:5]
            weaknesses = [s['test_name'] for s in scores
                          if s.get('t_score') is not None and s['t_score'] < 40]

            summary_parts = []
            if strengths:
                summary_parts.append(
                    f"<b>🏆 优势领域：</b>{'、'.join(strengths)}"
                    f"{'等' + str(len([s for s in scores if s.get('t_score') and s['t_score'] >= 60])) + '项' if len([s for s in scores if s.get('t_score') and s['t_score'] >= 60]) > 5 else ''}"
                    " — T分均超过60，表现优异。"
                )
            if weaknesses:
                summary_parts.append(
                    f"<b>⚠️ 需关注：</b>{'、'.join(weaknesses)}"
                    " — T分低于40，建议加强针对性训练。"
                )
            if not strengths and not weaknesses:
                summary_parts.append("📊 整体表现处于团队平均水平，各项指标稳定。")

            summary_parts.append(
                "💡 <i>提示：前往 AI 对话页面可获取更详细的个性化训练建议。</i>"
            )

            summary_html = "<br/>".join(summary_parts)
            story.append(Paragraph(summary_html, STYLE_BODY))

        story.append(Spacer(1, 4*mm))

        # ═══════════════════════════════════════════════════════════
        # 6. 训练建议
        # ═══════════════════════════════════════════════════════════
        story.append(Paragraph("🏋️ 训练建议", STYLE_H2))

        # 基于薄弱项生成建议
        weak_categories = set()
        for s in scores:
            if s.get('t_score') is not None and s['t_score'] < 40:
                weak_categories.add(s.get('test_category', ''))

        advice_items = []
        if "上肢力量" in weak_categories:
            advice_items.append("• <b>上肢力量：</b>增加卧推和引体向上的专项训练频次，建议每周2-3次，采用渐进超负荷原则。")
        if "下肢力量" in weak_categories:
            advice_items.append("• <b>下肢力量：</b>深蹲训练中加入变式（前蹲、保加利亚分腿蹲），提升下肢全面力量。")
        if "速度" in weak_categories:
            advice_items.append("• <b>速度：</b>增加短距离冲刺训练，配合起跑技术练习，改善加速度阶段表现。")
        if "爆发力" in weak_categories:
            advice_items.append("• <b>爆发力：</b>加入跳深、药球抛掷等 plyometric 训练，提升爆发力输出。")
        if "有氧耐力" in weak_categories:
            advice_items.append("• <b>有氧耐力：</b>增加间歇跑和 YoYo 测试专项训练，逐步提升有氧能力。")
        if "柔韧性" in weak_categories:
            advice_items.append("• <b>柔韧性：</b>每日训练前后增加15分钟动态/静态拉伸，重点改善后链柔韧度。")
        if "敏捷性" in weak_categories:
            advice_items.append("• <b>敏捷性：</b>加入锥桶 drill 和变向跑训练，提升多方向移动能力。")
        if "身体成分" in weak_categories:
            advice_items.append("• <b>身体成分：</b>优化营养方案，结合有氧与力量训练调整体成分。")

        if not advice_items:
            advice_items.append("• 当前各项指标表现良好，建议维持现有训练计划，定期监测关键指标变化。")
            advice_items.append("• 可在训练中加入周期性变式，避免平台期。")

        advice_html = "<br/>".join(advice_items)
        story.append(Paragraph(advice_html, STYLE_BODY))

        story.append(Spacer(1, 6*mm))

        # ═══════════════════════════════════════════════════════════
        # 页脚
        # ═══════════════════════════════════════════════════════════
        story.append(self._hr())
        story.append(Paragraph(
            "运动员数据分析平台<br/>"
            "本报告由 AI 辅助生成，仅供参考。最终训练决策请以教练判断为准。",
            STYLE_FOOTER,
        ))

        # 构建 PDF
        doc.build(
            story,
            onFirstPage=self._on_first_page,
            onLaterPages=self._on_later_pages,
        )

        pdf_bytes = buf.getvalue()
        buf.close()
        return pdf_bytes

    # ── 信息卡片表格 ──────────────────────────────────────────────────────

    def _make_info_table(self, row_data):
        """创建美观的信息表格"""
        # row_data: [[label1, value1, label2, value2], ...]
        flat = []
        for row in row_data:
            for i, cell in enumerate(row):
                if i % 2 == 0:  # label
                    flat.append(Paragraph(cell, ParagraphStyle(
                        'InfoLabel', parent=STYLE_CELL, textColor=SSP_GRAY_TEXT,
                    )))
                else:  # value
                    flat.append(Paragraph(cell, ParagraphStyle(
                        'InfoValue', parent=STYLE_CELL_BOLD, textColor=SSP_TEAL,
                    )))

        # 重塑为 4 列表格
        cols = 4
        table_data = []
        for i in range(0, len(flat), cols):
            table_data.append(flat[i:i+cols])

        col_w = (self.width - 36*mm) / cols
        table = Table(table_data, colWidths=[col_w] * cols)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), SSP_CARD_BG),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (1, 0), (1, -1), 2),
            ('LEFTPADDING', (3, 0), (3, -1), 2),
            ('GRID', (0, 0), (-1, -1), 0.5, SSP_LIGHT_GRAY),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROUNDEDCORNERS', [3, 3, 3, 3]),
        ]))
        return table


# ═══════════════════════════════════════════════════════════════════════════
# 兼容旧接口：generate_athlete_report 函数
# ═══════════════════════════════════════════════════════════════════════════

def generate_athlete_report(athlete_id, db_session):
    """生成 PDF 报告字节流（兼容旧接口）"""
    pdf_gen = PDFReport()
    return pdf_gen.generate_athlete_report(athlete_id, db_session)


def generate_report_html(athlete_id, db_session):
    """
    生成 HTML 报告（保留旧接口，供需要 HTML 的场景使用）
    如需 PDF，请使用 generate_athlete_report()
    """
    from datetime import date as dt_date

    athlete = Athlete.query.get(athlete_id)
    if not athlete:
        return "<h1>运动员不存在</h1>"

    analyzer = ScoreAnalyzer()
    profile = analyzer.athlete_profile(athlete_id, db_session)
    radar = analyzer.radar_data(athlete_id, db_session)
    body_metric = BodyMetric.query.filter_by(athlete_id=athlete_id) \
        .order_by(BodyMetric.record_date.desc()).first()

    score_rows = ""
    for s in profile.get("scores", [])[:20]:
        ts = s.get('t_score')
        score_rows += f"""<tr>
            <td>{s['test_name']}</td>
            <td>{s['raw_value']}{' ' + s.get('unit', '') if s.get('unit') else ''}</td>
            <td style="color:{t_color_hex(s.get('z_score'))}">{s.get('z_score', '—')}</td>
            <td style="color:{t_color_hex(ts)};font-weight:bold">{ts if ts is not None else '—'}</td>
            <td>{s.get('percentile', '—')}%</td>
            <td>{t_label(ts)}</td>
        </tr>"""

    radar_html = ""
    if radar.get("categories"):
        for i, cat in enumerate(radar["categories"]):
            val = radar["t_scores"][i] if i < len(radar["t_scores"]) else 50
            pct = min(100, max(0, (val - 30) / 40 * 100))
            radar_html += f"""<div class="bar-row">
                <span class="bar-label">{cat}</span>
                <div class="bar-track"><div class="bar-fill" style="width:{pct:.0f}%;background:{t_color_hex(val)}"></div></div>
                <span class="bar-val" style="color:{t_color_hex(val)}">{val:.1f}</span>
            </div>"""

    last_chat = ChatMessage.query.filter_by(user_id=athlete.user_id, role="assistant") \
        .order_by(ChatMessage.created_at.desc()).first()
    ai_advice = last_chat.content[:500] if last_chat else "暂无 AI 建议，请前往 AI 对话页面获取个性化建议。"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>运动员分析报告 — {athlete.name}</title>
<style>
    @page {{ size: A4; margin: 15mm; }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; font-size: 11pt; color: #333; line-height: 1.6; }}
    .header {{ text-align: center; border-bottom: 3px solid #a0c040; padding-bottom: 15px; margin-bottom: 20px; }}
    .header h1 {{ font-size: 24pt; color: #204040; }}
    .header p {{ color: #666; font-size: 10pt; }}
    .section {{ margin-bottom: 20px; page-break-inside: avoid; }}
    .section-title {{ font-size: 14pt; color: #204040; border-left: 4px solid #a0c040; padding-left: 10px; margin-bottom: 10px; }}
    .info-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
    .info-card {{ background: #f2f4f0; padding: 10px; border-radius: 6px; text-align: center; }}
    .info-card .label {{ font-size: 8pt; color: #888; }}
    .info-card .value {{ font-size: 16pt; font-weight: bold; color: #204040; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 9pt; }}
    th {{ background: #204040; color: #e0e0e0; padding: 6px 8px; text-align: left; }}
    td {{ padding: 5px 8px; border-bottom: 1px solid #e0e0e0; }}
    tr:nth-child(even) {{ background: #f7f9f5; }}
    .bar-row {{ display: flex; align-items: center; margin-bottom: 6px; gap: 8px; }}
    .bar-label {{ width: 60px; font-size: 9pt; text-align: right; }}
    .bar-track {{ flex: 1; height: 14px; background: #e0e0e0; border-radius: 7px; overflow: hidden; }}
    .bar-fill {{ height: 100%; border-radius: 7px; }}
    .bar-val {{ width: 40px; font-size: 9pt; font-weight: bold; text-align: left; }}
    .advice-box {{ background: #f7f9f5; border: 1px solid #a0c040; border-radius: 8px; padding: 12px; font-size: 9pt; }}
    .footer {{ text-align: center; font-size: 8pt; color: #aaa; margin-top: 25px; border-top: 1px solid #e0e0e0; padding-top: 10px; }}
</style>
</head>
<body>
<div class="header">
    <h1>🏃 运动员平台 — 运动员综合分析报告</h1>
    <p>运动员数据分析平台 | 生成日期：{dt_date.today().isoformat()}</p>
</div>
<div class="section">
    <div class="section-title">📋 基本信息</div>
    <div class="info-grid">
        <div class="info-card"><div class="label">姓名</div><div class="value">{athlete.name}</div></div>
        <div class="info-card"><div class="label">项目</div><div class="value">{athlete.sport_type or '—'}</div></div>
        <div class="info-card"><div class="label">位置</div><div class="value">{athlete.position or '—'}</div></div>
        <div class="info-card"><div class="label">年龄</div><div class="value">{athlete.age or '—'} 岁</div></div>
        <div class="info-card"><div class="label">身高</div><div class="value">{athlete.height_cm or '—'} cm</div></div>
        <div class="info-card"><div class="label">体重</div><div class="value">{athlete.weight_kg or '—'} kg</div></div>
        <div class="info-card"><div class="label">综合T分</div><div class="value" style="color:{t_color_hex(profile.get('composite_t_score'))}">{profile.get('composite_t_score', '—')}</div></div>
        <div class="info-card"><div class="label">最近测量</div><div class="value">{body_metric.record_date.isoformat() if body_metric else '—'}</div></div>
    </div>
</div>
<div class="section">
    <div class="section-title">🎯 八大维度能力画像</div>
    {radar_html or '<p style="color:#888;font-size:9pt;">暂无数据</p>'}
</div>
<div class="section">
    <div class="section-title">📊 测试明细 Z/T-score 表</div>
    <table>
        <thead><tr><th>测试项目</th><th>原始值</th><th>Z-score</th><th>T-score</th><th>百分位</th><th>评级</th></tr></thead>
        <tbody>{score_rows or '<tr><td colspan="6" style="color:#888;">暂无测试记录</td></tr>'}</tbody>
    </table>
</div>
<div class="section">
    <div class="section-title">🤖 AI 诊断建议</div>
    <div class="advice-box">{ai_advice}</div>
</div>
<div class="footer">
    运动员数据分析平台<br>
    本报告由 AI 辅助生成，仅供参考。最终训练决策请以教练判断为准。
</div>
</body>
</html>"""
    return html
