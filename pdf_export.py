"""
运动员数据分析平台 - 报告导出
生成可打印的 HTML 报告（浏览器 Ctrl+P → 另存为 PDF）
纯 Python 实现，无需外部依赖
"""
from datetime import date, datetime

from models import Athlete, BodyMetric, TestRecord, ChatMessage, FitnessTest
from analysis_engine import ScoreAnalyzer, RADAR_CATEGORIES

score_analyzer = ScoreAnalyzer()


def generate_report_html(athlete_id, db_session):
    """生成运动员综合分析报告 HTML"""
    athlete = Athlete.query.get(athlete_id)
    if not athlete:
        return "<h1>运动员不存在</h1>"

    profile = score_analyzer.athlete_profile(athlete_id, db_session)
    radar = score_analyzer.radar_data(athlete_id, db_session)
    body_metric = BodyMetric.query.filter_by(athlete_id=athlete_id)\
        .order_by(BodyMetric.record_date.desc()).first()

    # 颜色标记
    def t_color(t):
        if t is None: return "#888"
        if t >= 60: return "#a0c040"
        if t >= 45: return "#c0c060"
        return "#e05555"

    def t_label(t):
        if t is None: return "—"
        if t >= 65: return "优秀"
        if t >= 55: return "良好"
        if t >= 45: return "平均水平"
        if t >= 35: return "需提升"
        return "亟待改善"

    # 构建测试明细表行
    score_rows = ""
    for s in profile.get("scores", [])[:20]:
        score_rows += f"""<tr>
            <td>{s['test_name']}</td>
            <td>{s['raw_value']}{' ' + s.get('unit', '') if s.get('unit') else ''}</td>
            <td style="color:{t_color(s.get('z_score'))}">{s.get('z_score', '—')}</td>
            <td style="color:{t_color(s.get('t_score'))};font-weight:bold">{s.get('t_score', '—')}</td>
            <td>{s.get('percentile', '—')}%</td>
            <td>{t_label(s.get('t_score'))}</td>
        </tr>"""

    # 雷达维度 HTML
    radar_html = ""
    if radar.get("categories"):
        for i, cat in enumerate(radar["categories"]):
            val = radar["t_scores"][i] if i < len(radar["t_scores"]) else 50
            pct = min(100, max(0, (val - 30) / 40 * 100))
            radar_html += f"""<div class="bar-row">
                <span class="bar-label">{cat}</span>
                <div class="bar-track"><div class="bar-fill" style="width:{pct:.0f}%;background:{t_color(val)}"></div></div>
                <span class="bar-val" style="color:{t_color(val)}">{val:.1f}</span>
            </div>"""

    # AI 建议
    last_chat = ChatMessage.query.filter_by(user_id=athlete.user_id, role="assistant")\
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
    <p>运动员数据分析平台 | 生成日期：{date.today().isoformat()}</p>
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
        <div class="info-card"><div class="label">综合T分</div><div class="value" style="color:{t_color(profile.get('composite_t_score'))}">{profile.get('composite_t_score', '—')}</div></div>
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


def generate_athlete_report(athlete_id, db_session):
    """生成并返回 HTML 报告内容（供下载）"""
    return generate_report_html(athlete_id, db_session)
