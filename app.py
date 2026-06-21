""""
运动员数据分析平台 - Flask 主应用
运动员数据分析平台
"""

import json
import logging
import os
from datetime import datetime, date, timedelta
from functools import wraps

from dotenv import load_dotenv
load_dotenv()

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, Response, g
)
from werkzeug.security import generate_password_hash, check_password_hash

# 导入配置
from config import Config, BrandConfig, AIPrompt

# 导入模型
from models import (
    db, User, Athlete, BodyMetric, FitnessTest,
    TestRecord, TrainingLog, InjuryRecord, ChatMessage,
    Video, TrainingPlan, PlanDay, AthletePlan
)

# 导入视频服务
from video_service import save_video as vs_save_video, get_video_path

# 导入 DeepSeek 客户端
from deepseek_client import create_deepseek_client

# ==================== 应用初始化 ====================

# 创建 Flask 应用
app = Flask(__name__)
app.config.from_object(Config)

# 初始化数据库
db.init_app(app)

# 初始化 DeepSeek 客户端
deepseek_client = create_deepseek_client(app.config)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==================== 认证工具 ====================

def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        # 将当前用户存入 Flask g 对象
        g.current_user = User.query.get(session["user_id"])
        return f(*args, **kwargs)
    return decorated_function


def role_required(*allowed_roles):
    """角色验证装饰器 — 用法: @role_required('coach', 'admin')"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            g.current_user = User.query.get(session["user_id"])
            if g.current_user.role not in allowed_roles:
                return jsonify({"error": "权限不足，需要角色: " + ", ".join(allowed_roles)}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==================== 数据库初始化 ====================

def init_db():
    """初始化数据库：建表 + 预填充测试项目"""
    db.create_all()
    FitnessTest.seed_defaults()
    # 创建管理员（密码优先从环境变量读取）
    admin_user = app.config.get("ADMIN_USERNAME", "admin")
    admin_pass = app.config.get("ADMIN_PASSWORD", "admin123")
    if not User.query.filter_by(username=admin_user).first():
        admin = User(
            username=admin_user,
            password_hash=generate_password_hash(admin_pass),
            role="admin",
            display_name="系统管理员",
        )
        db.session.add(admin)
        db.session.commit()
        logger.info("已创建管理员账户")
    logger.info("数据库初始化完成")


# ==================== 页面路由 ====================

@app.route("/")
def index():
    """首页 - 根据登录状态跳转到仪表盘或登录页"""
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/health")
def health():
    """健康检查端点（供部署平台使用）"""
    return jsonify({"status": "ok", "db": "connected"}), 200


@app.route("/login", methods=["GET", "POST"])
def login():
    """登录页面"""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return render_template("index.html", error="请输入用户名和密码",
                                   brand=BrandConfig)

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session["username"] = user.username
            session["role"] = user.role
            session["display_name"] = user.display_name
            session.permanent = True
            logger.info("用户 %s 登录成功", username)
            return redirect(url_for("dashboard"))
        else:
            logger.warning("用户 %s 登录失败", username)
            return render_template("index.html", error="用户名或密码错误",
                                   brand=BrandConfig)

    return render_template("index.html", brand=BrandConfig)


@app.route("/logout")
def logout():
    """登出"""
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    """仪表盘 — 根据角色跳转"""
    user = g.current_user
    if user.role in ("coach", "doctor", "analyst", "admin"):
        return redirect(url_for("coach_dashboard"))
    athlete = Athlete.query.filter_by(user_id=user.id).first()

    # 获取最近的身体指标
    recent_metrics = []
    latest_metric = None
    if athlete:
        recent_metrics = BodyMetric.query.filter_by(athlete_id=athlete.id) \
            .order_by(BodyMetric.record_date.desc()).limit(10).all()
        latest_metric = recent_metrics[0] if recent_metrics else None

    # 获取最近的测试记录
    recent_tests = []
    if athlete:
        recent_tests = TestRecord.query.filter_by(athlete_id=athlete.id) \
            .order_by(TestRecord.test_date.desc()).limit(10).all()

    # 获取最近的训练日志
    recent_training = []
    if athlete:
        recent_training = TrainingLog.query.filter_by(athlete_id=athlete.id) \
            .order_by(TrainingLog.session_date.desc()).limit(5).all()

    # === 新增：本周训练负荷数据（柱状图用） ===
    weekly_training = []
    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # 周一
    day_labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    if athlete:
        week_logs = TrainingLog.query.filter_by(athlete_id=athlete.id) \
            .filter(TrainingLog.session_date >= week_start) \
            .filter(TrainingLog.session_date <= week_start + timedelta(days=6)) \
            .all()
        day_map = {}
        for log in week_logs:
            if log.session_date and log.duration_min:
                idx = (log.session_date - week_start).days
                day_map[idx] = day_map.get(idx, 0) + log.duration_min
        max_dur = max(day_map.values()) if day_map else 60
        for i in range(7):
            d = week_start + timedelta(days=i)
            dur = day_map.get(i, 0)
            weekly_training.append({
                "day": day_labels[i],
                "date": d.isoformat(),
                "duration": dur,
                "height_pct": round((dur / max(max_dur, 1)) * 100, 1),
                "is_today": d == today,
            })

    # === 新增：体脂/体重趋势（最近10条，用于迷你折线） ===
    body_trend = []
    if athlete:
        all_metrics = BodyMetric.query.filter_by(athlete_id=athlete.id) \
            .order_by(BodyMetric.record_date.asc()).all()
        if len(all_metrics) >= 2:
            # 体重趋势
            weight_points = []
            for m in all_metrics:
                if m.weight_kg:
                    weight_points.append({"date": m.record_date.isoformat(), "value": m.weight_kg})
            if weight_points:
                weight_vals = [p["value"] for p in weight_points]
                w_min, w_max = min(weight_vals), max(weight_vals)
                w_range = max(w_max - w_min, 1)
                weight_delta = weight_vals[-1] - weight_vals[0]
                body_trend.append({
                    "label": "体重",
                    "unit": "kg",
                    "points": weight_points,
                    "current": weight_vals[-1],
                    "delta": round(weight_delta, 1),
                    "direction": "up" if weight_delta > 0.5 else ("down" if weight_delta < -0.5 else "flat"),
                    "dot_heights": [round((v - w_min) / w_range * 100, 1) for v in weight_vals],
                })
            # 体脂趋势
            bf_points = []
            for m in all_metrics:
                if m.body_fat_pct:
                    bf_points.append({"date": m.record_date.isoformat(), "value": m.body_fat_pct})
            if bf_points:
                bf_vals = [p["value"] for p in bf_points]
                bf_min, bf_max = min(bf_vals), max(bf_vals)
                bf_range = max(bf_max - bf_min, 1)
                bf_delta = bf_vals[-1] - bf_vals[0]
                body_trend.append({
                    "label": "体脂率",
                    "unit": "%",
                    "points": bf_points,
                    "current": bf_vals[-1],
                    "delta": round(bf_delta, 1),
                    "direction": "up" if bf_delta > 0.5 else ("down" if bf_delta < -0.5 else "flat"),
                    "dot_heights": [round((v - bf_min) / bf_range * 100, 1) for v in bf_vals],
                })

    # === 新增：测试对比（最近两次对比） ===
    test_comparisons = []
    if athlete:
        # 按 test_id 分组，取最近两次记录
        from collections import defaultdict
        by_test = defaultdict(list)
        for tr in TestRecord.query.filter_by(athlete_id=athlete.id) \
                .order_by(TestRecord.test_date.desc()).all():
            by_test[tr.test_id].append(tr)
        for test_id, records in by_test.items():
            if len(records) >= 2:
                latest = records[0]
                prev = records[1]
                diff = latest.raw_value - prev.raw_value
                test_name = latest.test.name if latest.test else f"测试#{test_id}"
                unit = latest.test.unit if latest.test else ""
                test_comparisons.append({
                    "name": test_name,
                    "unit": unit,
                    "prev_value": prev.raw_value,
                    "latest_value": latest.raw_value,
                    "prev_date": prev.test_date.isoformat() if prev.test_date else "",
                    "latest_date": latest.test_date.isoformat() if latest.test_date else "",
                    "diff": round(diff, 2),
                    "diff_str": f"{'+' if diff > 0 else ''}{round(diff, 2)}",
                    "direction": "positive" if diff > 0 else ("negative" if diff < 0 else "neutral"),
                })

    return render_template(
        "dashboard.html",
        user=user,
        athlete=athlete,
        latest_metric=latest_metric,
        recent_metrics=recent_metrics,
        recent_tests=recent_tests,
        recent_training=recent_training,
        weekly_training=weekly_training,
        body_trend=body_trend,
        test_comparisons=test_comparisons,
        brand=BrandConfig,
    )


@app.route("/data-entry")
@login_required
def data_entry():
    """数据录入页面"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()

    if not athlete:
        return render_template("data_entry.html", error="请先完善运动员档案",
                               athlete=None, tests=[], brand=BrandConfig)

    tests = FitnessTest.query.order_by(FitnessTest.name).all()
    return render_template("data_entry.html", athlete=athlete,
                           tests=tests, brand=BrandConfig)


@app.route("/csv-import")
@login_required
def csv_import_page():
    """CSV 批量导入页面"""
    return render_template("csv_import.html", brand=BrandConfig)


@app.route("/ai-chat")
@login_required
def ai_chat():
    """AI 对话页面"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    return render_template("ai_chat.html", user=user, athlete=athlete,
                           brand=BrandConfig)


# ==================== 教练端路由 ====================

def _compute_zt_scores(athlete):
    """计算运动员的 Z/T-score（基于团队均值），返回字典"""
    from statistics import mean, stdev
    
    # 收集全队每项测试的数据，计算均值和标准差
    all_records = TestRecord.query.join(Athlete).all()
    team_by_test = {}
    for r in all_records:
        team_by_test.setdefault(r.test_id, []).append(r.raw_value)
    
    # 对每个测试项目计算 Z-scoring 的参考值
    test_stats = {}
    for test_id, vals in team_by_test.items():
        if len(vals) >= 2:
            try:
                test_stats[test_id] = {"mean": mean(vals), "stdev": stdev(vals)}
            except:
                test_stats[test_id] = {"mean": mean(vals), "stdev": 1.0}
    
    # 取该运动员每个测试项目最近一次的成绩
    athlete_tests = TestRecord.query.filter_by(athlete_id=athlete.id).order_by(
        TestRecord.test_date.desc()).all()
    
    latest = {}
    for r in athlete_tests:
        if r.test_id not in latest:
            latest[r.test_id] = r
    
    results = []
    for test_id, record in latest.items():
        stats = test_stats.get(test_id)
        z_score = None
        t_score = None
        if stats and stats["stdev"] > 0:
            z_score = (record.raw_value - stats["mean"]) / stats["stdev"]
            t_score = 50 + 10 * z_score
        
        results.append({
            "test_name": record.test.name,
            "category": record.test.category,
            "unit": record.test.unit,
            "raw_value": record.raw_value,
            "z_score": round(z_score, 2) if z_score is not None else None,
            "t_score": round(t_score, 1) if t_score is not None else None,
            "test_date": record.test_date.isoformat() if record.test_date else None,
            "team_mean": round(stats["mean"], 2) if stats else None,
        })
    
    return results


@app.route("/coach")
@login_required
def coach_dashboard():
    """教练仪表盘 — 全队总览"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return render_template("error.html", error="权限不足", brand=BrandConfig), 403
    
    athletes = Athlete.query.all()
    total_athletes = len(athletes)
    
    # 全队统计
    all_zt = []
    for a in athletes:
        all_zt.extend(_compute_zt_scores(a))
    
    avg_t = sum(r["t_score"] for r in all_zt if r["t_score"] is not None) / max(
        len([r for r in all_zt if r["t_score"] is not None]), 1)
    
    # 风险人数（T-score < 35 的项目 >= 2 项）
    risk_count = 0
    risk_athletes = []
    for a in athletes:
        zt = _compute_zt_scores(a)
        low_count = sum(1 for r in zt if r["t_score"] is not None and r["t_score"] < 35)
        if low_count >= 2:
            risk_count += 1
            risk_athletes.append({
                "id": a.id,
                "name": a.name,
                "low_items": [r["test_name"] for r in zt if r["t_score"] is not None and r["t_score"] < 35],
            })
    
    # 活跃率：最近 7 天有训练日志的比例
    week_ago = date.today() - timedelta(days=7)
    active_count = 0
    for a in athletes:
        recent_train = TrainingLog.query.filter_by(athlete_id=a.id).filter(
            TrainingLog.session_date >= week_ago).first()
        if recent_train:
            active_count += 1
    active_rate = round(active_count / max(total_athletes, 1) * 100, 0)
    
    return render_template(
        "coach_dashboard.html",
        user=g.current_user,
        athletes=athletes,
        total_athletes=total_athletes,
        avg_t_score=round(avg_t, 1),
        risk_count=risk_count,
        risk_athletes=risk_athletes,
        active_rate=int(active_rate),
        brand=BrandConfig,
    )


@app.route("/coach/athletes")
@login_required
def coach_athletes():
    """教练端 — 运动员列表"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return render_template("error.html", error="权限不足", brand=BrandConfig), 403
    
    athletes = Athlete.query.all()
    athlete_data = []
    for a in athletes:
        zt = _compute_zt_scores(a)
        avg_t = sum(r["t_score"] for r in zt if r["t_score"] is not None) / max(
            len([r for r in zt if r["t_score"] is not None]), 1)
        athlete_data.append({
            "athlete": a,
            "avg_t_score": round(avg_t, 1),
            "test_count": len(zt),
        })
    
    return render_template(
        "coach_athletes.html",
        user=g.current_user,
        athlete_data=athlete_data,
        brand=BrandConfig,
    )


@app.route("/coach/athlete/<int:athlete_id>")
@login_required
def coach_athlete_detail(athlete_id):
    """教练端 — 运动员详情（含 Z/T-score + AI 诊断建议）"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return render_template("error.html", error="权限不足", brand=BrandConfig), 403
    
    athlete = Athlete.query.get(athlete_id)
    if not athlete:
        return render_template("error.html", error="运动员不存在", brand=BrandConfig), 404
    
    zt_scores = _compute_zt_scores(athlete)
    
    # 雷达图数据：按 8 维度聚合
    radar_categories = {
        "力量": ["上肢力量", "下肢力量"],
        "速度": ["速度"],
        "耐力": ["有氧耐力", "速度耐力", "上肢耐力"],
        "爆发力": ["爆发力"],
        "敏捷": ["敏捷性"],
        "柔韧": ["柔韧性"],
        "体成分": ["身体成分"],
        "功能性": ["功能性筛查"],
    }
    
    radar_data = {}
    for dim, cats in radar_categories.items():
        matches = [r for r in zt_scores if r["category"] in cats and r["t_score"] is not None]
        if matches:
            radar_data[dim] = round(sum(r["t_score"] for r in matches) / len(matches), 1)
        else:
            radar_data[dim] = 50  # 默认中位数
    
    # 趋势数据：取测试记录最多的项目
    from collections import Counter
    all_records = TestRecord.query.filter_by(athlete_id=athlete.id).order_by(
        TestRecord.test_date.asc()).all()
    test_counter = Counter(r.test_id for r in all_records)
    top_test_id = test_counter.most_common(1)[0][0] if test_counter else None
    
    trend_data = []
    if top_test_id:
        trend_records = [r for r in all_records if r.test_id == top_test_id]
        test_info = FitnessTest.query.get(top_test_id)
        trend_data = [{
            "date": r.test_date.isoformat() if r.test_date else None,
            "value": r.raw_value,
        } for r in trend_records]
        trend_test_name = test_info.name if test_info else "未知"
        trend_unit = test_info.unit if test_info else ""
    else:
        trend_test_name = ""
        trend_unit = ""
    
    # 身体指标
    metrics = BodyMetric.query.filter_by(athlete_id=athlete.id).order_by(
        BodyMetric.record_date.desc()).limit(6).all()
    
    # 训练日志
    training_logs = TrainingLog.query.filter_by(athlete_id=athlete.id).order_by(
        TrainingLog.session_date.desc()).limit(10).all()
    
    return render_template(
        "coach_athlete_detail.html",
        user=g.current_user,
        athlete=athlete,
        zt_scores=zt_scores,
        radar_data=radar_data,
        trend_data=trend_data,
        trend_test_name=trend_test_name,
        trend_unit=trend_unit,
        metrics=metrics,
        training_logs=training_logs,
        brand=BrandConfig,
    )


@app.route("/coach/team/compare")
@login_required
def coach_team_compare():
    """教练端 — 队内横向对比"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return render_template("error.html", error="权限不足", brand=BrandConfig), 403
    
    athletes = Athlete.query.all()
    tests = FitnessTest.query.order_by(FitnessTest.name).all()
    
    return render_template(
        "coach_team_compare.html",
        user=g.current_user,
        athletes=athletes,
        tests=tests,
        brand=BrandConfig,
    )


# ==================== API 路由 ====================

@app.route("/api/metrics", methods=["POST"])
@login_required
def api_create_metric():
    """录入身体指标"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    if not athlete:
        return jsonify({"error": "请先完善运动员档案"}), 400

    data = request.get_json() if request.is_json else request.form
    try:
        metric = BodyMetric(
            athlete_id=athlete.id,
            record_date=datetime.strptime(data.get("record_date", str(date.today())), "%Y-%m-%d").date(),
            weight_kg=float(data["weight_kg"]) if data.get("weight_kg") else None,
            body_fat_pct=float(data["body_fat_pct"]) if data.get("body_fat_pct") else None,
            muscle_mass_kg=float(data["muscle_mass_kg"]) if data.get("muscle_mass_kg") else None,
            resting_hr=int(data["resting_hr"]) if data.get("resting_hr") else None,
            blood_pressure_sys=int(data["blood_pressure_sys"]) if data.get("blood_pressure_sys") else None,
            blood_pressure_dia=int(data["blood_pressure_dia"]) if data.get("blood_pressure_dia") else None,
            vo2_max=float(data["vo2_max"]) if data.get("vo2_max") else None,
            notes=data.get("notes", "").strip() or None,
        )
        db.session.add(metric)
        db.session.commit()
        logger.info("运动员 %s 录入身体指标，日期=%s", athlete.name, metric.record_date)
        return jsonify({"success": True, "metric": metric.to_dict()}), 201

    except (ValueError, TypeError) as e:
        return jsonify({"error": f"数据格式错误: {str(e)}"}), 400


@app.route("/api/tests", methods=["POST"])
@login_required
def api_create_test_record():
    """录入测试记录"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    if not athlete:
        return jsonify({"error": "请先完善运动员档案"}), 400

    data = request.get_json() if request.is_json else request.form
    try:
        test_record = TestRecord(
            athlete_id=athlete.id,
            test_id=int(data["test_id"]),
            test_date=datetime.strptime(data.get("test_date", str(date.today())), "%Y-%m-%d").date(),
            raw_value=float(data["raw_value"]),
            notes=data.get("notes", "").strip() or None,
        )
        db.session.add(test_record)
        db.session.commit()
        logger.info("运动员 %s 录入测试记录，测试ID=%s，值=%s",
                     athlete.name, test_record.test_id, test_record.raw_value)
        return jsonify({"success": True, "test_record": test_record.to_dict()}), 201

    except (ValueError, TypeError, KeyError) as e:
        return jsonify({"error": f"数据格式错误: {str(e)}"}), 400


@app.route("/api/training", methods=["POST"])
@login_required
def api_create_training():
    """录入训练日志"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    if not athlete:
        return jsonify({"error": "请先完善运动员档案"}), 400

    data = request.get_json() if request.is_json else request.form
    try:
        training = TrainingLog(
            athlete_id=athlete.id,
            session_date=datetime.strptime(data.get("session_date", str(date.today())), "%Y-%m-%d").date(),
            duration_min=int(data["duration_min"]) if data.get("duration_min") else None,
            intensity=data.get("intensity", "").strip() or None,
            rpe=int(data["rpe"]) if data.get("rpe") else None,
            content=data.get("content", "").strip() or None,
            total_distance_km=float(data["total_distance_km"]) if data.get("total_distance_km") else None,
            calories_burned=int(data["calories_burned"]) if data.get("calories_burned") else None,
            hr_avg=int(data["hr_avg"]) if data.get("hr_avg") else None,
            hr_max=int(data["hr_max"]) if data.get("hr_max") else None,
        )
        db.session.add(training)
        db.session.commit()
        logger.info("运动员 %s 录入训练日志，日期=%s", athlete.name, training.session_date)
        return jsonify({"success": True, "training": training.to_dict()}), 201

    except (ValueError, TypeError) as e:
        return jsonify({"error": f"数据格式错误: {str(e)}"}), 400


@app.route("/api/athlete/<int:athlete_id>/data")
@login_required
def api_get_athlete_data(athlete_id):
    """获取运动员完整数据（JSON）"""
    athlete = Athlete.query.get(athlete_id)
    if not athlete:
        return jsonify({"error": "运动员不存在"}), 404

    # 权限检查：运动员只能看自己的数据
    if g.current_user.role == "athlete" and athlete.user_id != g.current_user.id:
        return jsonify({"error": "权限不足"}), 403

    return jsonify({
        "athlete": athlete.to_dict(),
        "body_metrics": [m.to_dict() for m in athlete.body_metrics],
        "test_records": [r.to_dict() for r in athlete.test_records],
        "training_logs": [t.to_dict() for t in athlete.training_logs],
        "injury_records": [i.to_dict() for i in athlete.injury_records],
    })


@app.route("/api/athlete/profile", methods=["POST", "PUT"])
@login_required
def api_create_or_update_athlete():
    """创建或更新运动员档案"""
    user = g.current_user
    data = request.get_json() if request.is_json else request.form

    athlete = Athlete.query.filter_by(user_id=user.id).first()

    if request.method == "POST" and athlete:
        return jsonify({"error": "运动员档案已存在，请使用 PUT 更新"}), 409

    if request.method == "PUT" and not athlete:
        return jsonify({"error": "运动员档案不存在，请使用 POST 创建"}), 404

    try:
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "姓名不能为空"}), 400

        if athlete is None:
            athlete = Athlete(user_id=user.id)
            db.session.add(athlete)

        athlete.name = name
        athlete.gender = data.get("gender", athlete.gender if athlete else "")
        athlete.sport_type = data.get("sport_type", athlete.sport_type if athlete else "")
        athlete.position = data.get("position", athlete.position if athlete else "")
        athlete.level = data.get("level", athlete.level if athlete else "")
        athlete.training_years = int(data["training_years"]) if data.get("training_years") else (athlete.training_years if athlete else 0)
        athlete.notes = data.get("notes", athlete.notes if athlete else "")

        # 身高体重
        if data.get("height_cm"):
            athlete.height_cm = float(data["height_cm"])
        if data.get("weight_kg"):
            athlete.weight_kg = float(data["weight_kg"])

        # 出生日期
        if data.get("birth_date"):
            athlete.birth_date = datetime.strptime(data["birth_date"], "%Y-%m-%d").date()

        db.session.commit()
        logger.info("运动员档案已%s: %s", "创建" if request.method == "POST" else "更新", athlete.name)

        return jsonify({
            "success": True,
            "athlete": athlete.to_dict(),
        })
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"数据格式错误: {str(e)}"}), 400


@app.route("/api/tests/list")
@login_required
def api_list_tests():
    """获取所有测试项目列表"""
    tests = FitnessTest.query.order_by(FitnessTest.name).all()
    return jsonify([t.to_dict() for t in tests])


# ==================== CSV 批量导入 API ====================

import csv
import io

_csv_uploaded_file = None  # 临时存储上传的 CSV 内容


def _normalize_header(h):
    """标准化 CSV 列名用于匹配"""
    return h.strip().lower().replace(" ", "_").replace("-", "_")


def _suggest_mapping(headers):
    """根据列名自动建议映射"""
    suggestions = {}
    for idx, h in enumerate(headers):
        nh = _normalize_header(h)
        # 运动员姓名
        if nh in ("athlete_name", "name", "athlete", "player", "运动员", "姓名", "运动员姓名", "选手"):
            if "athlete_name" not in suggestions:
                suggestions["athlete_name"] = idx
        # 测试项目
        elif nh in ("test_name", "test", "item", "event", "测试项目", "项目", "测试名称"):
            if "test_name" not in suggestions:
                suggestions["test_name"] = idx
        # 测试日期
        elif nh in ("test_date", "date", "测试日期", "日期", "时间"):
            if "test_date" not in suggestions:
                suggestions["test_date"] = idx
        # 测试值
        elif nh in ("raw_value", "value", "result", "score", "数值", "测试值", "成绩", "结果"):
            if "raw_value" not in suggestions:
                suggestions["raw_value"] = idx
        # 单位
        elif nh in ("unit", "单位"):
            if "unit" not in suggestions:
                suggestions["unit"] = idx
        # 备注
        elif nh in ("notes", "note", "remark", "备注", "说明"):
            if "notes" not in suggestions:
                suggestions["notes"] = idx
    return suggestions


@app.route("/api/import/csv", methods=["POST"])
@login_required
def api_import_csv_preview():
    """上传 CSV 并返回预览和列映射建议"""
    if "file" not in request.files:
        return jsonify({"error": "未上传文件"}), 400
    
    file = request.files["file"]
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return jsonify({"error": "仅支持 .csv 格式文件"}), 400
    
    try:
        content = file.read()
        # 尝试多种编码解码
        text = None
        for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"):
            try:
                text = content.decode(encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        
        if text is None:
            return jsonify({"error": "无法解析文件编码"}), 400
        
        # 存储原始内容供后续导入使用
        global _csv_uploaded_file
        _csv_uploaded_file = content
        
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        
        if len(rows) < 2:
            return jsonify({"error": "CSV 文件至少需要包含表头和一行数据"}), 400
        
        headers = [h.strip() for h in rows[0]]
        data_rows = rows[1:]
        
        # 过滤空行
        data_rows = [r for r in data_rows if any(c.strip() for c in r)]
        
        if not data_rows:
            return jsonify({"error": "CSV 文件没有有效数据行"}), 400
        
        total_rows = len(data_rows)
        preview_rows = data_rows[:5]
        mapping_suggestions = _suggest_mapping(headers)
        
        # 预验证数据行
        errors = []
        valid_count = total_rows
        tests_map = {t.name: t.id for t in FitnessTest.query.all()}
        athletes_map = {a.name: a.id for a in Athlete.query.all()}
        
        for i, row in enumerate(data_rows, start=2):  # 从第2行开始（第1行是表头）
            row_dict = {}
            for j, header in enumerate(headers):
                if j < len(row):
                    row_dict[_normalize_header(header)] = row[j].strip()
            
            # 检查运动员
            athlete_name = row_dict.get("athlete_name", "") or row_dict.get("name", "") or row_dict.get("athlete", "")
            if not athlete_name:
                errors.append({"row": i, "field": "athlete_name", "message": "运动员姓名为空"})
                valid_count -= 1
                continue
            
            # 检查测试项目
            test_name = row_dict.get("test_name", "") or row_dict.get("test", "") or row_dict.get("item", "")
            if not test_name:
                errors.append({"row": i, "field": "test_name", "message": "测试项目名称为空"})
                valid_count -= 1
                continue
            if test_name not in tests_map:
                errors.append({"row": i, "field": "test_name", "message": f"测试项目「{test_name}」未找到，请检查名称"})
                valid_count -= 1
            
            # 检查日期
            test_date = row_dict.get("test_date", "") or row_dict.get("date", "")
            if not test_date:
                errors.append({"row": i, "field": "test_date", "message": "测试日期为空"})
                valid_count -= 1
            else:
                try:
                    datetime.strptime(test_date, "%Y-%m-%d")
                except ValueError:
                    try:
                        datetime.strptime(test_date, "%Y/%m/%d")
                    except ValueError:
                        errors.append({"row": i, "field": "test_date", "message": f"日期格式无效: {test_date}，期望 YYYY-MM-DD"})
                        valid_count -= 1
            
            # 检查数值
            raw_value = row_dict.get("raw_value", "") or row_dict.get("value", "")
            if not raw_value:
                errors.append({"row": i, "field": "raw_value", "message": "测试值为空"})
                valid_count -= 1
            else:
                try:
                    float(raw_value)
                except ValueError:
                    errors.append({"row": i, "field": "raw_value", "message": f"无效数值: {raw_value}"})
                    valid_count -= 1
        
        return jsonify({
            "headers": headers,
            "preview_rows": preview_rows,
            "total_rows": total_rows,
            "valid_rows": max(valid_count, 0),
            "mapping_suggestions": mapping_suggestions,
            "errors": errors[:20],  # 最多返回20条错误
        })
    
    except csv.Error as e:
        return jsonify({"error": f"CSV 解析错误: {str(e)}"}), 400
    except Exception as e:
        logger.error("CSV 上传处理失败: %s", e)
        return jsonify({"error": f"处理失败: {str(e)}"}), 500


@app.route("/api/import/csv/confirm", methods=["POST"])
@login_required
def api_import_csv_confirm():
    """确认列映射并执行导入"""
    global _csv_uploaded_file
    
    if _csv_uploaded_file is None:
        return jsonify({"error": "未找到上传的文件，请重新上传"}), 400
    
    data = request.get_json()
    if not data or "mapping" not in data:
        return jsonify({"error": "缺少列映射"}), 400
    
    mapping = data["mapping"]  # {"athlete_name": 0, "test_name": 1, ...}
    skip_duplicates = data.get("skip_duplicates", True)
    
    # 检查必填字段
    required = ["athlete_name", "test_name", "test_date", "raw_value"]
    for field in required:
        if field not in mapping or mapping[field] is None:
            return jsonify({"error": f"缺少必填字段映射: {field}"}), 400
    
    try:
        # 解码文件
        text = None
        for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"):
            try:
                text = _csv_uploaded_file.decode(encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        
        if len(rows) < 2:
            return jsonify({"error": "CSV 文件数据不足"}), 400
        
        headers = [h.strip() for h in rows[0]]
        data_rows = rows[1:]
        data_rows = [r for r in data_rows if any(c.strip() for c in r)]
        
        # 构建测试项目和运动员的查找表
        tests_map = {t.name: t.id for t in FitnessTest.query.all()}
        athletes_map = {a.name: a.id for a in Athlete.query.all()}
        
        # 当前用户信息（运动员只能导入自己的数据）
        user = g.current_user
        
        imported = 0
        skipped = 0
        error_details = []
        
        for i, row in enumerate(data_rows, start=2):
            try:
                # 根据映射提取字段
                def _get_val(field):
                    idx = mapping.get(field)
                    if idx is not None and idx < len(row):
                        return row[idx].strip()
                    return ""
                
                athlete_name = _get_val("athlete_name")
                test_name = _get_val("test_name")
                test_date_str = _get_val("test_date")
                raw_value_str = _get_val("raw_value")
                unit_str = _get_val("unit")
                notes_str = _get_val("notes")
                
                # 验证运动员
                athlete_id = athletes_map.get(athlete_name)
                if not athlete_id:
                    error_details.append({"row": i, "message": f"运动员「{athlete_name}」不存在"})
                    continue
                
                # 运动员只能导入自己的数据
                if user.role == "athlete":
                    athlete = Athlete.query.get(athlete_id)
                    if not athlete or athlete.user_id != user.id:
                        error_details.append({"row": i, "message": f"无权限导入运动员「{athlete_name}」的数据"})
                        continue
                
                # 验证测试项目
                test_id = tests_map.get(test_name)
                if not test_id:
                    error_details.append({"row": i, "message": f"测试项目「{test_name}」未找到"})
                    continue
                
                # 验证日期
                try:
                    test_date = datetime.strptime(test_date_str, "%Y-%m-%d").date()
                except ValueError:
                    try:
                        test_date = datetime.strptime(test_date_str, "%Y/%m/%d").date()
                    except ValueError:
                        error_details.append({"row": i, "message": f"日期格式无效: {test_date_str}"})
                        continue
                
                # 验证数值
                try:
                    raw_value = float(raw_value_str)
                except ValueError:
                    error_details.append({"row": i, "message": f"无效数值: {raw_value_str}"})
                    continue
                
                # 检查重复
                if skip_duplicates:
                    existing = TestRecord.query.filter_by(
                        athlete_id=athlete_id,
                        test_id=test_id,
                        test_date=test_date,
                    ).first()
                    if existing:
                        skipped += 1
                        continue
                
                # 创建记录
                record = TestRecord(
                    athlete_id=athlete_id,
                    test_id=test_id,
                    test_date=test_date,
                    raw_value=raw_value,
                    notes=notes_str or None,
                )
                db.session.add(record)
                imported += 1
            
            except Exception as e:
                error_details.append({"row": i, "message": str(e)})
        
        db.session.commit()
        logger.info("CSV 批量导入完成: 成功=%d, 跳过=%d, 错误=%d", imported, skipped, len(error_details))
        
        # 清除临时文件
        _csv_uploaded_file = None
        
        return jsonify({
            "imported": imported,
            "skipped": skipped,
            "errors": len(error_details),
            "error_details": error_details[:50],
        })
    
    except Exception as e:
        logger.error("CSV 导入失败: %s", e)
        return jsonify({"error": f"导入失败: {str(e)}"}), 500


@app.route("/api/import/template")
@login_required
def api_import_template():
    """下载 CSV 模板文件"""
    from flask import Response
    
    template_csv = (
        "athlete_name,test_name,test_date,raw_value,unit,notes\n"
        + "张三,30米冲刺,2024-06-15,4.32,秒,晴天\n"
        + "张三,立定跳远,2024-06-15,245,厘米,\n"
        + "张三,卧推1RM,2024-06-22,85,公斤,进步明显\n"
        + "李四,垂直纵跳,2024-06-15,65,厘米,\n"
        + "李四,YoYo间歇恢复,2024-06-15,16.5,级,疲劳\n"
    )
    
    return Response(
        template_csv,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=import_template.csv",
            "Content-Type": "text/csv; charset=utf-8-sig",
        }
    )


# ==================== 教练端 API ====================

@app.route("/api/coach/athletes")
@login_required
def api_coach_athletes():
    """JSON 运动员列表"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return jsonify({"error": "权限不足"}), 403
    
    athletes = Athlete.query.all()
    result = []
    for a in athletes:
        zt = _compute_zt_scores(a)
        avg_t = sum(r["t_score"] for r in zt if r["t_score"] is not None) / max(
            len([r for r in zt if r["t_score"] is not None]), 1)
        result.append({
            "id": a.id,
            "name": a.name,
            "sport_type": a.sport_type,
            "position": a.position,
            "avg_t_score": round(avg_t, 1),
            "test_count": len(zt),
        })
    return jsonify(result)


@app.route("/api/coach/team/stats")
@login_required
def api_coach_team_stats():
    """全队统计摘要"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return jsonify({"error": "权限不足"}), 403
    
    athletes = Athlete.query.all()
    total = len(athletes)
    
    all_zt = []
    risk_count = 0
    for a in athletes:
        zt = _compute_zt_scores(a)
        all_zt.extend(zt)
        low_count = sum(1 for r in zt if r["t_score"] is not None and r["t_score"] < 35)
        if low_count >= 2:
            risk_count += 1
    
    avg_t = sum(r["t_score"] for r in all_zt if r["t_score"] is not None) / max(
        len([r for r in all_zt if r["t_score"] is not None]), 1)
    
    return jsonify({
        "total_athletes": total,
        "avg_t_score": round(avg_t, 1),
        "risk_count": risk_count,
    })


@app.route("/api/coach/team/compare_data")
@login_required
def api_coach_team_compare_data():
    """横向对比数据 JSON"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return jsonify({"error": "权限不足"}), 403
    
    athlete_ids = request.args.get("ids", "")
    test_ids = request.args.get("test_ids", "")
    
    if athlete_ids:
        athlete_id_list = [int(x) for x in athlete_ids.split(",") if x.strip()]
    else:
        athlete_id_list = [a.id for a in Athlete.query.all()]
    
    if test_ids:
        test_id_list = [int(x) for x in test_ids.split(",") if x.strip()]
    else:
        test_id_list = [t.id for t in FitnessTest.query.all()]
    
    athletes = Athlete.query.filter(Athlete.id.in_(athlete_id_list)).all()
    tests = FitnessTest.query.filter(FitnessTest.id.in_(test_id_list)).all()
    
    result = {"athletes": [], "tests": [], "data": {}}
    
    for a in athletes:
        result["athletes"].append({"id": a.id, "name": a.name})
    
    for t in tests:
        result["tests"].append({"id": t.id, "name": t.name, "unit": t.unit, "category": t.category})
    
    for a in athletes:
        result["data"][str(a.id)] = {}
        for t in tests:
            record = TestRecord.query.filter_by(athlete_id=a.id, test_id=t.id).order_by(
                TestRecord.test_date.desc()).first()
            result["data"][str(a.id)][str(t.id)] = {
                "value": record.raw_value if record else None,
                "date": record.test_date.isoformat() if record and record.test_date else None,
            }
    
    return jsonify(result)


# ==================== AI 对话 API ====================

@app.route("/api/injury", methods=["POST"])
@login_required
def api_create_injury():
    """录入伤病记录"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    if not athlete:
        return jsonify({"error": "请先完善运动员档案"}), 400

    data = request.get_json() if request.is_json else request.form
    try:
        injury = InjuryRecord(
            athlete_id=athlete.id,
            injury_date=datetime.strptime(data.get("injury_date", str(date.today())), "%Y-%m-%d").date(),
            body_part=data.get("body_part", "").strip(),
            injury_type=data.get("injury_type", "").strip(),
            severity=data.get("severity", "mild"),
            description=data.get("description", "").strip(),
            status=data.get("status", "active"),
            recovery_date=datetime.strptime(data["recovery_date"], "%Y-%m-%d").date() if data.get("recovery_date") else None,
            notes=data.get("notes", "").strip() or None,
        )
        db.session.add(injury)
        db.session.commit()
        return jsonify({"success": True, "injury": injury.to_dict()}), 201
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"数据格式错误: {str(e)}"}), 400


@app.route("/api/injuries")
@login_required
def api_list_injuries():
    """获取当前运动员的伤病列表"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    if not athlete:
        return jsonify({"injuries": []})

    injuries = InjuryRecord.query.filter_by(athlete_id=athlete.id) \
        .order_by(InjuryRecord.injury_date.desc()).all()
    return jsonify({"injuries": [i.to_dict() for i in injuries]})


@app.route("/api/chat/send", methods=["POST"])
@login_required
def api_chat_send():
    """
    发送消息给 AI，返回 SSE 流式响应
    请求体: {"message": "用户消息"}
    """
    user = g.current_user
    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "消息不能为空"}), 400

    return _chat_stream_response(user, user_message)


@app.route("/api/chat/stream")
@login_required
def api_chat_stream():
    """
    SSE 流式 AI 对话（GET 版本，供 EventSource 使用）
    查询参数: ?message=用户消息
    """
    user = g.current_user
    user_message = request.args.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "消息不能为空"}), 400

    return _chat_stream_response(user, user_message)


@app.route("/api/ai/diagnose", methods=["POST"])
@login_required
def api_ai_diagnose():
    """
    AI 诊断报告 — 基于视频分析结果 + 运动员数据深度分析
    请求体: {"video_id": "...", "analysis_results": {...}}
    返回 SSE 流式诊断报告
    """
    user = g.current_user
    data = request.get_json()
    video_id = data.get("video_id", "")
    analysis_results = data.get("analysis_results", {})

    athlete = Athlete.query.filter_by(user_id=user.id).first()
    metrics = analysis_results.get("metrics", {})
    test_type = analysis_results.get("test_type", "未知")

    prompt = f"""你是一名资深运动生物力学专家，服务于运动员训练平台。请基于以下视频姿态分析数据进行专业诊断：

## 视频分析数据
- 测试类型: {test_type}
- 分析指标: {json.dumps(metrics, ensure_ascii=False)}

## 运动员信息
{athlete.name if athlete else '未知'} | {athlete.sport_type if athlete else '未知'} | {athlete.training_years if athlete else '?'}年训练经验

## 请执行以下分析：
1. **姿态评估**: 对关键指标给出专业评分（优秀/良好/需改进/风险）
2. **技术缺陷**: 识别可能存在的技术问题
3. **改进建议**: 提供3条具体可行的训练建议
4. **伤病风险**: 评估是否存在潜在的伤病风险
5. **训练重点**: 给出本周训练调整建议

请用中文，专业但易懂，以结构化报告形式输出。"""

    return _chat_stream_response(user, prompt)


def _chat_stream_response(user, user_message):
    """统一的 SSE 流式 AI 响应"""
    import flask
    # 获取运动员信息作为上下文
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    athlete_context = "暂无运动员档案"
    if athlete:
        athlete_context = f"""
姓名: {athlete.name}
性别: {athlete.gender}
年龄: {athlete.age}岁
身高: {athlete.height_cm}cm
体重: {athlete.weight_kg}kg
运动项目: {athlete.sport_type or '未设置'}
位置: {athlete.position or '未设置'}
"""

    # 获取最近对话历史（最多 20 条）
    recent_messages = ChatMessage.query.filter_by(user_id=user.id) \
        .order_by(ChatMessage.created_at.asc()).limit(20).all()

    # 构建消息列表
    messages = [{"role": "system", "content": AIPrompt.SYSTEM_PROMPT}]

    # 添加运动员上下文（如果存在）
    if athlete:
        messages.append({
            "role": "system",
            "content": f"当前服务的运动员信息：\n{athlete_context}"
        })

    # 添加历史对话
    for msg in recent_messages:
        messages.append({"role": msg.role, "content": msg.content})

    # 添加当前用户消息
    messages.append({"role": "user", "content": user_message})

    # 保存用户消息到数据库
    user_msg = ChatMessage(user_id=user.id, role="user", content=user_message)
    db.session.add(user_msg)
    db.session.commit()

    # 检查 API 密钥是否配置
    if not app.config.get("DEEPSEEK_API_KEY"):
        def error_generator():
            error_msg = "AI 服务未配置 API 密钥，请在环境变量中设置 DEEPSEEK_API_KEY"
            yield f"data: {json.dumps({'error': error_msg})}\n\n"
        return Response(error_generator(), mimetype="text/event-stream")

    # SSE 流式响应生成器
    def generate():
        full_response = ""
        try:
            for token in deepseek_client.chat_stream(messages=messages):
                full_response += token
                yield f"data: {json.dumps({'token': token})}\n\n"

            # 保存 AI 回复到数据库
            if full_response.strip():
                assistant_msg = ChatMessage(
                    user_id=user.id, role="assistant", content=full_response
                )
                db.session.add(assistant_msg)
                db.session.commit()

            # 发送结束信号
            yield f"data: {json.dumps({'done': True})}\n\n"

        except Exception as e:
            logger.error("AI 对话出错: %s", str(e))
            error_data = json.dumps({"error": str(e), "done": True})
            yield f"data: {error_data}\n\n"

    return Response(generate(), mimetype="text/event-stream")

@app.route("/api/chat/history")
@login_required
def api_chat_history():
    """获取当前用户的对话历史"""
    user = g.current_user
    messages = ChatMessage.query.filter_by(user_id=user.id) \
        .order_by(ChatMessage.created_at.asc()).all()
    return jsonify([m.to_dict() for m in messages])


@app.route("/api/chat/clear", methods=["POST"])
@login_required
def api_chat_clear():
    """清空当前用户的对话历史"""
    user = g.current_user
    ChatMessage.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    logger.info("用户 %s 清空了对话历史", user.username)
    return jsonify({"success": True, "message": "对话历史已清空"})


# ==================== 视频管理 API ====================

@app.route("/api/videos/upload", methods=["POST"])
@login_required
def api_upload_video():
    """上传视频文件"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    if not athlete:
        return jsonify({"error": "请先完善运动员档案"}), 400

    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400

    file = request.files["file"]
    test_type = request.form.get("test_type", "")
    notes = request.form.get("notes", "")

    try:
        result = vs_save_video(file, athlete.id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # 获取视频时长
    from video_service import get_video_duration
    duration = get_video_duration(result["filepath"])

    # 保存到数据库
    video = Video(
        video_id=result["video_id"],
        athlete_id=athlete.id,
        filename=result["filename"],
        original_filename=result["original_filename"],
        file_size=result["size_bytes"],
        status="uploaded",
        test_type=test_type,
        duration_seconds=duration,
        notes=notes,
    )
    db.session.add(video)
    db.session.commit()

    logger.info("视频记录已创建: id=%d, video_id=%s", video.id, video.video_id)

    # 上传成功后自动触发姿态分析
    from video_worker import process_single_video
    try:
        process_single_video(video.id, app, generate_annotated=True)
        db.session.refresh(video)
        logger.info("视频自动分析完成: id=%d, status=%s", video.id, video.status)
    except Exception as e:
        logger.warning("视频自动分析失败（不影响上传）: %s", e)

    return jsonify({
        "success": True,
        "video": video.to_dict(),
    }), 201


@app.route("/api/videos/<video_id>")
@login_required
def api_get_video(video_id):
    """获取视频文件（流式传输）"""
    filepath = get_video_path(video_id)
    if not filepath:
        return jsonify({"error": "视频文件不存在"}), 404

    import os
    import mimetypes
    
    mime_type, _ = mimetypes.guess_type(filepath)
    if mime_type is None:
        mime_type = "video/mp4"

    # 支持 Range 请求（用于视频 seek）
    range_header = request.headers.get("Range")
    if not range_header:
        return send_file(filepath, mimetype=mime_type)

    size = os.path.getsize(filepath)
    byte_range = range_header.replace("bytes=", "").split("-")
    start = int(byte_range[0])
    end = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else size - 1
    length = end - start + 1

    with open(filepath, "rb") as f:
        f.seek(start)
        data = f.read(length)

    response = Response(data, 206, mimetype=mime_type, direct_passthrough=True)
    response.headers.add(
        "Content-Range", f"bytes {start}-{end}/{size}"
    )
    response.headers.add("Accept-Ranges", "bytes")
    response.headers.add("Content-Length", str(length))
    return response


@app.route("/api/videos/list")
@login_required
def api_video_list():
    """获取当前运动员的视频列表"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    if not athlete:
        return jsonify({"videos": []})

    videos = Video.query.filter_by(athlete_id=athlete.id) \
        .order_by(Video.created_at.desc()).all()

    return jsonify({
        "videos": [v.to_dict() for v in videos],
    })


@app.route("/api/videos/<video_id>/status")
@login_required
def api_video_status(video_id):
    """获取视频处理状态"""
    video = Video.query.filter_by(video_id=video_id).first()
    if not video:
        return jsonify({"error": "视频不存在"}), 404

    return jsonify({
        "video_id": video.video_id,
        "status": video.status,
        "status_label": video.status_label,
        "duration_seconds": video.duration_seconds,
        "test_type": video.test_type,
        "analysis_results": video.parsed_results,
    })


@app.route("/api/videos/<video_id>/analyze", methods=["POST"])
@login_required
def api_analyze_video(video_id):
    """触发视频姿态分析任务"""
    video = Video.query.filter_by(video_id=video_id).first()
    if not video:
        return jsonify({"error": "视频不存在"}), 404

    # 权限检查：运动员只能分析自己的视频
    user = g.current_user
    if user.role == "athlete":
        athlete = Athlete.query.filter_by(user_id=user.id).first()
        if not athlete or video.athlete_id != athlete.id:
            return jsonify({"error": "权限不足"}), 403

    if video.status == 'processing':
        return jsonify({
            "success": False,
            "message": "视频正在分析中，请稍候...",
            "status": video.status,
        }), 409

    # 发起后台分析
    from video_worker import process_single_video

    # 重置状态
    video.status = "uploaded"
    video.analysis_results = ""
    db.session.commit()

    # 同步处理（生产环境建议改为后台任务）
    try:
        success = process_single_video(video.id, app, generate_annotated=True)
        
        # 重新加载视频记录以获取最新状态
        db.session.refresh(video)
        
        return jsonify({
            "success": success,
            "status": video.status,
            "status_label": video.status_label,
            "message": "分析完成" if success else "分析失败",
        })
    except Exception as e:
        logger.exception("视频分析异常: %s", video_id)
        return jsonify({
            "success": False,
            "error": str(e),
            "status": video.status,
        }), 500


@app.route("/api/videos/<video_id>/result")
@login_required
def api_video_result(video_id):
    """获取视频分析结果（完整 JSON）"""
    video = Video.query.filter_by(video_id=video_id).first()
    if not video:
        return jsonify({"error": "视频不存在"}), 404

    # 权限检查
    user = g.current_user
    if user.role == "athlete":
        athlete = Athlete.query.filter_by(user_id=user.id).first()
        if not athlete or video.athlete_id != athlete.id:
            return jsonify({"error": "权限不足"}), 403

    parsed = video.parsed_results
    return jsonify({
        "video_id": video.video_id,
        "athlete_id": video.athlete_id,
        "status": video.status,
        "status_label": video.status_label,
        "test_type": video.test_type,
        "duration_seconds": video.duration_seconds,
        "original_filename": video.original_filename,
        "created_at": video.created_at.isoformat() if video.created_at else None,
        "analysis_results": parsed,
        "metrics": parsed.get("metrics", {}),
        "keyframe_data": parsed.get("keyframe_data", []),
        "is_mock": parsed.get("is_mock", False),
    })


@app.route("/api/videos/<video_id>/reprocess", methods=["POST"])
@login_required
def api_reprocess_video(video_id):
    """重新处理视频"""
    video = Video.query.filter_by(video_id=video_id).first()
    if not video:
        return jsonify({"error": "视频不存在"}), 404

    from video_worker import process_single_video

    video.status = "uploaded"
    video.analysis_results = ""
    db.session.commit()

    # 同步处理（简单场景）
    success = process_single_video(video.id, app, generate_annotated=True)

    return jsonify({
        "success": success,
        "status": video.status,
        "status_label": video.status_label,
    })


# ==================== 视频页面路由 ====================

@app.route("/profile")
@login_required
def athlete_profile_page():
    """运动员档案编辑页面"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    return render_template("athlete_profile.html", athlete=athlete,
                           user=user, brand=BrandConfig)


@app.route("/videos")
@login_required
def video_list_page():
    """视频列表页面"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    
    if not athlete:
        return render_template("video_list.html", athlete=None,
                               videos=[], brand=BrandConfig)

    videos = Video.query.filter_by(athlete_id=athlete.id) \
        .order_by(Video.created_at.desc()).all()

    return render_template("video_list.html", athlete=athlete,
                           videos=videos, brand=BrandConfig)


@app.route("/videos/<video_id>")
@login_required
def video_player_page(video_id):
    """视频播放页面"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    
    video = Video.query.filter_by(video_id=video_id).first()
    if not video:
        return render_template("video_player.html", error="视频不存在",
                               video=None, athlete=athlete, brand=BrandConfig), 404

    return render_template("video_player.html", video=video,
                           athlete=athlete, brand=BrandConfig)


@app.route("/videos/compare")
@login_required
def video_compare_page():
    """视频对比页面 — 并排对比两段视频的分析指标"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    
    if not athlete:
        return render_template("video_compare.html", athlete=None,
                               videos=[], brand=BrandConfig)
    
    videos = Video.query.filter_by(athlete_id=athlete.id) \
        .order_by(Video.created_at.desc()).all()
    
    return render_template("video_compare.html", athlete=athlete,
                           videos=videos, brand=BrandConfig)


@app.route("/api/videos/compare_data")
@login_required
def api_video_compare_data():
    """获取两个视频的对比分析数据
    
    Query params:
        ids: 逗号分隔的视频ID列表（最多2个），如 ids=abc123,def456
    """
    ids_str = request.args.get("ids", "")
    video_ids = [x.strip() for x in ids_str.split(",") if x.strip()]
    
    if len(video_ids) < 2:
        return jsonify({"error": "请提供至少2个视频ID（ids=id1,id2）"}), 400
    
    # 取前两个
    video_ids = video_ids[:2]
    
    results = []
    for vid in video_ids:
        video = Video.query.filter_by(video_id=vid).first()
        if not video:
            results.append({"video_id": vid, "error": "视频不存在", "metrics": {}})
            continue
        
        user = g.current_user
        if user.role == "athlete":
            athlete = Athlete.query.filter_by(user_id=user.id).first()
            if not athlete or video.athlete_id != athlete.id:
                results.append({"video_id": vid, "error": "权限不足", "metrics": {}})
                continue
        
        parsed = video.parsed_results
        results.append({
            "video_id": vid,
            "original_filename": video.original_filename,
            "test_type": video.test_type,
            "duration_seconds": video.duration_seconds,
            "status": video.status,
            "status_label": video.status_label,
            "created_at": video.created_at.isoformat() if video.created_at else None,
            "metrics": parsed.get("metrics", {}),
            "keyframe_data": parsed.get("keyframe_data", []),
        })
    
    return jsonify({
        "videos": results,
        "comparison": _build_comparison(results),
    })


def _build_comparison(results):
    """构建两个视频指标的差异对比
    
    Returns:
        list of dict: [{metric, value_a, value_b, diff, direction, unit}, ...]
    """
    if len(results) < 2:
        return []
    
    a = results[0].get("metrics", {})
    b = results[1].get("metrics", {})
    
    all_keys = set(list(a.keys()) + list(b.keys()))
    
    # Metric display config
    metric_config = {
        'step_frequency': ('步频', '步/分', False),
        'cadence': ('步频', '步/分', False),
        'stride_length': ('步幅', 'm', False),
        'step_length': ('步幅', 'm', False),
        'jump_height': ('纵跳高度', 'cm', False),
        'vertical_jump': ('纵跳高度', 'cm', False),
        'speed': ('速度', 'm/s', False),
        'avg_speed': ('平均速度', 'm/s', False),
        'max_speed': ('最大速度', 'm/s', False),
        'acceleration': ('加速度', 'm/s²', False),
        'knee_angle': ('膝角', '°', False),
        'hip_angle': ('髋角', '°', False),
        'ankle_angle': ('踝角', '°', False),
        'elbow_angle': ('肘角', '°', False),
        'trunk_angle': ('躯干角', '°', False),
        'ground_contact': ('触地时间', 'ms', True),
        'contact_time': ('触地时间', 'ms', True),
        'flight_time': ('腾空时间', 'ms', False),
        'power': ('功率', 'W', False),
        'force': ('力量', 'N', False),
        'symmetry': ('对称性', '%', False),
        'balance': ('平衡', '%', False),
    }
    
    comparison = []
    for key in sorted(all_keys):
        config = metric_config.get(key, (key.replace('_', ' '), '', False))
        name, unit, lower_is_better = config
        
        val_a = a.get(key)
        val_b = b.get(key)
        
        item = {
            "metric": key,
            "name": name,
            "unit": unit,
            "value_a": val_a,
            "value_b": val_b,
            "diff": None,
            "direction": "neutral",  # improved / declined / neutral
        }
        
        if (val_a is not None and val_b is not None 
            and isinstance(val_a, (int, float)) and isinstance(val_b, (int, float))):
            diff = val_b - val_a
            item["diff"] = round(diff, 2) if abs(diff) >= 0.01 else 0.0
            if lower_is_better:
                if diff < -0.001:
                    item["direction"] = "improved"
                elif diff > 0.001:
                    item["direction"] = "declined"
            else:
                if diff > 0.001:
                    item["direction"] = "improved"
                elif diff < -0.001:
                    item["direction"] = "declined"
        
        comparison.append(item)
    
    return comparison


@app.errorhandler(404)
def not_found(error):
    """404 页面"""
    return """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>404</title>
<style>body{background:#1a1a2e;color:#e0e0e0;display:flex;align-items:center;justify-content:center;
height:100vh;font-family:sans-serif;text-align:center}.e404{font-size:6rem;color:#a0c040}
p{font-size:1.2rem}a{color:#a0c040;text-decoration:none}</style></head>
<body><div><div class="e404">404</div><p>页面未找到</p><p><a href="/">返回首页</a></p></div></body></html>""", 404


@app.errorhandler(500)
def internal_error(error):
    """500 页面"""
    return """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>500</title>
<style>body{background:#1a1a2e;color:#e0e0e0;display:flex;align-items:center;justify-content:center;
height:100vh;font-family:sans-serif;text-align:center}.e500{font-size:6rem;color:#a0c040}
p{font-size:1.2rem}a{color:#a0c040;text-decoration:none}</style></head>
<body><div><div class="e500">500</div><p>服务器内部错误</p><p><a href="/">返回首页</a></p></div></body></html>""", 500


# ==================== 伤病追踪看板 ====================

@app.route("/injuries")
@login_required
def injury_tracker():
    """伤病追踪看板 — 人体图 + 时间线"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    return render_template("injury_tracker.html", user=user, athlete=athlete, brand=BrandConfig)


@app.route("/api/injuries/timeline")
@login_required
def api_injuries_timeline():
    """伤病时间线 JSON（当前运动员）"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    if not athlete:
        return jsonify({"injuries": []})
    injuries = InjuryRecord.query.filter_by(athlete_id=athlete.id) \
        .order_by(InjuryRecord.injury_date.desc()).all()
    return jsonify({"injuries": [i.to_dict() for i in injuries]})


# ==================== 队内排行榜 ====================

@app.route("/coach/leaderboard")
@login_required
def coach_leaderboard():
    """队内排行榜页面"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return render_template("error.html", error="权限不足", brand=BrandConfig), 403
    tests = FitnessTest.query.order_by(FitnessTest.name).all()
    return render_template("coach_leaderboard.html", user=g.current_user, tests=tests, brand=BrandConfig)


# ==================== ACWR 训练负荷预警 ====================

@app.route("/api/athlete/<int:athlete_id>/acwr")
@login_required
def api_athlete_acwr(athlete_id):
    """计算运动员 ACWR (急性:慢性工作负荷比)"""
    athlete = Athlete.query.get(athlete_id)
    if not athlete:
        return jsonify({"error": "运动员不存在"}), 404
    if g.current_user.role == "athlete" and athlete.user_id != g.current_user.id:
        return jsonify({"error": "权限不足"}), 403

    today = date.today()

    # 取最近28天的训练日志
    logs = TrainingLog.query.filter_by(athlete_id=athlete_id) \
        .filter(TrainingLog.session_date <= today) \
        .order_by(TrainingLog.session_date.desc()).all()

    if not logs:
        return jsonify({
            "acwr": None,
            "acute_load_7d": 0,
            "chronic_load_28d": 0,
            "zone": "nodata",
            "zone_label": "无数据",
            "message": "暂无训练数据，无法计算 ACWR",
        })

    # sRPE 负荷 = 训练时长(分钟) × RPE
    def sRPE(log):
        if log.duration_min and log.rpe:
            return log.duration_min * log.rpe
        return 0

    loads = [{"date": log.session_date, "load": sRPE(log)} for log in logs]

    # 急性负荷：最近7天日均 sRPE
    cutoff_7d = today - timedelta(days=7)
    acute_loads = [l["load"] for l in loads if l["date"] >= cutoff_7d]
    acute_load = sum(acute_loads) / max(len(acute_loads), 1)

    # 慢性负荷：最近28天日均 sRPE
    cutoff_28d = today - timedelta(days=28)
    chronic_loads = [l["load"] for l in loads if l["date"] >= cutoff_28d]
    chronic_load = sum(chronic_loads) / max(len(chronic_loads), 1)

    # ACWR
    if chronic_load > 0:
        acwr = round(acute_load / chronic_load, 2)
    else:
        acwr = None

    # 风险区间判定
    if acwr is None:
        zone, zone_label, zone_color = "nodata", "无数据", "#606878"
        message = "慢性负荷为0，无法计算 ACWR"
    elif acwr < 0.8:
        zone, zone_label, zone_color = "low", "负荷偏低", "#2196f3"
        message = "训练负荷偏低，可能处于减量期"
    elif acwr <= 1.3:
        zone, zone_label, zone_color = "safe", "安全区", "#4caf50"
        message = "训练负荷处于安全范围"
    elif acwr <= 1.5:
        zone, zone_label, zone_color = "caution", "注意", "#ff9800"
        message = "训练负荷偏高，需关注恢复状态"
    else:
        zone, zone_label, zone_color = "danger", "高风险", "#e53935"
        message = "训练负荷过高，伤病风险显著增加！建议减量"

    return jsonify({
        "acwr": acwr,
        "acute_load_7d": round(acute_load, 1),
        "chronic_load_28d": round(chronic_load, 1),
        "zone": zone,
        "zone_label": zone_label,
        "zone_color": zone_color,
        "message": message,
        "total_sessions_7d": len(acute_loads),
        "total_sessions_28d": len(chronic_loads),
    })


# ==================== 统计分析 API ====================

# 初始化分析引擎（全局单例）
from analysis_engine import ScoreAnalyzer
score_analyzer = ScoreAnalyzer()


@app.route("/api/athlete/<int:athlete_id>/profile")
@login_required
def api_athlete_profile(athlete_id):
    """
    获取运动员完整 Z/T-score 画像 JSON

    返回每项测试的原始值、Z-score、T-score、百分位排名，
    以及综合 T-score 和按类别汇总的评分。
    """
    # 权限检查
    athlete = Athlete.query.get(athlete_id)
    if not athlete:
        return jsonify({"error": "运动员不存在"}), 404
    if g.current_user.role == "athlete" and athlete.user_id != g.current_user.id:
        return jsonify({"error": "权限不足"}), 403

    try:
        profile = score_analyzer.athlete_profile(athlete_id, db.session)
        return jsonify(profile)
    except Exception as e:
        logger.error("生成运动员画像失败: %s", str(e))
        return jsonify({"error": f"分析失败: {str(e)}"}), 500


@app.route("/api/athlete/<int:athlete_id>/trends/<int:test_id>")
@login_required
def api_athlete_trends(athlete_id, test_id):
    """
    获取运动员某项测试的趋势分析 JSON

    使用线性回归分析历史测试数据的变化趋势，
    返回斜率、R²、趋势方向和数据点列表。
    """
    athlete = Athlete.query.get(athlete_id)
    if not athlete:
        return jsonify({"error": "运动员不存在"}), 404
    if g.current_user.role == "athlete" and athlete.user_id != g.current_user.id:
        return jsonify({"error": "权限不足"}), 403

    test = FitnessTest.query.get(test_id)
    if not test:
        return jsonify({"error": "测试项目不存在"}), 404

    try:
        trends = score_analyzer.analyze_trends(athlete_id, test_id, db.session)
        return jsonify(trends)
    except Exception as e:
        logger.error("趋势分析失败: %s", str(e))
        return jsonify({"error": f"分析失败: {str(e)}"}), 500


@app.route("/api/athlete/<int:athlete_id>/radar")
@login_required
def api_athlete_radar(athlete_id):
    """
    获取运动员 8 大维度雷达图数据 JSON

    返回类别列表及对应的平均 T-score，
    供前端 Chart.js 绘制雷达图。
    """
    athlete = Athlete.query.get(athlete_id)
    if not athlete:
        return jsonify({"error": "运动员不存在"}), 404
    if g.current_user.role == "athlete" and athlete.user_id != g.current_user.id:
        return jsonify({"error": "权限不足"}), 403

    try:
        radar = score_analyzer.radar_data(athlete_id, db.session)
        return jsonify(radar)
    except Exception as e:
        logger.error("雷达图数据生成失败: %s", str(e))
        return jsonify({"error": f"分析失败: {str(e)}"}), 500


# ==================== 参考人群管理 API ====================

@app.route("/api/references")
@login_required
def api_get_references():
    """获取所有测试项目的参考人群参数"""
    return jsonify(score_analyzer.get_all_references())


@app.route("/api/references/<test_name>", methods=["PUT"])
@role_required("admin", "coach")
def api_update_reference(test_name):
    """
    更新某个测试项目的参考人群参数（限管理员/教练）

    请求体 JSON: {"mean": 85.0, "std": 18.0, "higher_is_better": true}
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "请求体不能为空"}), 400

    # 只允许更新 mean, std, higher_is_better 字段
    params = {}
    if "mean" in data:
        params["mean"] = float(data["mean"])
    if "std" in data:
        params["std"] = float(data["std"])
    if "higher_is_better" in data:
        params["higher_is_better"] = bool(data["higher_is_better"])

    if not params:
        return jsonify({"error": "没有提供有效的更新参数"}), 400

    success = score_analyzer.update_reference(test_name, params)
    if not success:
        return jsonify({"error": f"测试项目 '{test_name}' 不在参考列表中"}), 404

    logger.info("参考参数已更新: %s → %s", test_name, params)
    return jsonify({
        "success": True,
        "test_name": test_name,
        "updated": params,
        "reference": score_analyzer.references[test_name],
    })


# ==================== PDF 报告导出 API ====================

@app.route("/api/coach/athlete/<int:athlete_id>/report/pdf")
@role_required("coach", "doctor", "analyst", "admin")
def api_coach_athlete_report_pdf(athlete_id):
    """教练端专用 — 导出运动员 PDF 报告（需教练角色）"""
    return api_athlete_report_pdf(athlete_id)


@app.route("/api/athlete/<int:athlete_id>/report/pdf")
@login_required
def api_athlete_report_pdf(athlete_id):
    """
    生成并下载运动员综合报告 PDF

    返回一个包含运动员基本信息、综合 T 分数、能力雷达图、
    测试明细表、趋势摘要和 AI 建议的 PDF 文件。
    """
    athlete = Athlete.query.get(athlete_id)
    if not athlete:
        return jsonify({"error": "运动员不存在"}), 404
    if g.current_user.role == "athlete" and athlete.user_id != g.current_user.id:
        return jsonify({"error": "权限不足"}), 403

    try:
        from pdf_export import PDFReport
        pdf_gen = PDFReport()
        pdf_bytes = pdf_gen.generate_athlete_report(athlete_id, db.session)

        response = Response(pdf_bytes, mimetype="application/pdf")
        # 设置下载文件名
        filename = f"运动员报告_{athlete.name}_{date.today().isoformat()}.pdf"
        # URL-encode 中文字符
        from urllib.parse import quote
        response.headers["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(filename)}"
        )
        return response
    except Exception as e:
        logger.error("PDF 报告生成失败: %s", str(e))
        return jsonify({"error": f"PDF 生成失败: {str(e)}"}), 500


# ==================== 训练计划模块 — 教练端页面路由 ====================

@app.route("/coach/plans")
@login_required
def coach_plans():
    """教练端 — 训练计划管理页面"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return render_template("error.html", error="权限不足", brand=BrandConfig), 403

    plans = TrainingPlan.query.filter_by(coach_id=g.current_user.id).order_by(
        TrainingPlan.created_at.desc()).all()
    athletes = Athlete.query.all()

    return render_template(
        "coach_plans.html",
        user=g.current_user,
        plans=plans,
        athletes=athletes,
        brand=BrandConfig,
    )


@app.route("/coach/plans/<int:plan_id>/edit")
@login_required
def plan_editor(plan_id):
    """教练端 — 训练计划编辑页（周×天网格）"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return render_template("error.html", error="权限不足", brand=BrandConfig), 403

    plan = TrainingPlan.query.get(plan_id)
    if not plan:
        return render_template("error.html", error="计划不存在", brand=BrandConfig), 404
    if plan.coach_id != g.current_user.id and g.current_user.role != "admin":
        return render_template("error.html", error="权限不足", brand=BrandConfig), 403

    days = PlanDay.query.filter_by(plan_id=plan_id).order_by(
        PlanDay.week_number, PlanDay.day_number).all()

    return render_template(
        "plan_editor.html",
        user=g.current_user,
        plan=plan,
        days=days,
        brand=BrandConfig,
    )


@app.route("/coach/plans/<int:plan_id>/assign")
@login_required
def coach_plan_assign(plan_id):
    """教练端 — 分配计划页面"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return render_template("error.html", error="权限不足", brand=BrandConfig), 403

    plan = TrainingPlan.query.get(plan_id)
    if not plan:
        return render_template("error.html", error="计划不存在", brand=BrandConfig), 404

    athletes = Athlete.query.all()
    # 获取已分配此计划的运动员
    assigned = AthletePlan.query.filter_by(plan_id=plan_id).all()
    assigned_ids = [ap.athlete_id for ap in assigned]

    return render_template(
        "coach_plan_assign.html",
        user=g.current_user,
        plan=plan,
        athletes=athletes,
        assigned=assigned,
        assigned_ids=assigned_ids,
        brand=BrandConfig,
    )


# ==================== 训练计划模块 — 运动员端页面路由 ====================

@app.route("/athlete/my-plan")
@login_required
def athlete_my_plan():
    """运动员端 — 查看我的训练计划"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    if not athlete:
        return render_template("error.html", error="请先完善运动员档案", brand=BrandConfig), 400

    # 查找当前激活的训练计划
    athlete_plan = AthletePlan.query.filter_by(
        athlete_id=athlete.id, status="active"
    ).first()

    plan = None
    days = []
    plan_days = []
    completed_ids = []

    if athlete_plan:
        plan = athlete_plan.plan
        plan_days = PlanDay.query.filter_by(plan_id=plan.id).order_by(
            PlanDay.week_number, PlanDay.day_number).all()
        completed_ids = athlete_plan.get_completed_day_ids()

        # 按周分组
        days_by_week = {}
        for d in plan_days:
            days_by_week.setdefault(d.week_number, []).append(d)
    else:
        days_by_week = {}

    # 找出今天的训练
    import datetime as dt
    today_weekday = dt.date.today().isoweekday()  # 1=Monday, 7=Sunday
    today_days = [d for d in plan_days if d.day_number == today_weekday] if athlete_plan else []

    return render_template(
        "athlete_my_plan.html",
        user=user,
        athlete=athlete,
        athlete_plan=athlete_plan,
        plan=plan,
        plan_days=plan_days,
        completed_ids=completed_ids,
        days_by_week=days_by_week,
        today_days=today_days,
        today_weekday=today_weekday,
        brand=BrandConfig,
    )


# ==================== 训练计划模块 — API 路由 ====================

@app.route("/api/plans", methods=["GET", "POST"])
@login_required
def api_plans():
    """获取或创建训练计划"""
    # GET: 列表
    if request.method == "GET":
        plans = TrainingPlan.query.filter_by(
            coach_id=g.current_user.id
        ).order_by(TrainingPlan.created_at.desc()).all()
        return jsonify([p.to_dict() for p in plans])

    # POST: 创建
    data = request.get_json()
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "计划标题不能为空"}), 400

    plan = TrainingPlan(
        coach_id=g.current_user.id,
        title=title,
        description=data.get("description", "").strip(),
        sport_type=data.get("sport_type", "").strip(),
        duration_weeks=int(data.get("duration_weeks", 4)),
    )
    db.session.add(plan)
    db.session.commit()

    # 自动生成空的周×天结构
    _init_plan_days(plan)

    logger.info("训练计划已创建: %s (教练=%s)", plan.title, g.current_user.username)
    return jsonify({"success": True, "plan": plan.to_dict()}), 201


@app.route("/api/plans/<int:plan_id>", methods=["GET", "PUT", "DELETE"])
@login_required
def api_plan_detail(plan_id):
    """获取/更新/删除单个训练计划"""
    plan = TrainingPlan.query.get(plan_id)
    if not plan:
        return jsonify({"error": "计划不存在"}), 404

    # 权限检查
    if plan.coach_id != g.current_user.id and g.current_user.role != "admin":
        return jsonify({"error": "权限不足"}), 403

    if request.method == "GET":
        days = PlanDay.query.filter_by(plan_id=plan_id).order_by(
            PlanDay.week_number, PlanDay.day_number).all()
        return jsonify({
            "plan": plan.to_dict(),
            "days": [d.to_dict() for d in days],
        })

    if request.method == "PUT":
        data = request.get_json()
        if "title" in data:
            plan.title = data["title"].strip()
        if "description" in data:
            plan.description = data["description"].strip()
        if "sport_type" in data:
            plan.sport_type = data["sport_type"].strip()
        if "duration_weeks" in data:
            plan.duration_weeks = int(data["duration_weeks"])
        if "is_active" in data:
            plan.is_active = bool(data["is_active"])
        db.session.commit()
        return jsonify({"success": True, "plan": plan.to_dict()})

    if request.method == "DELETE":
        db.session.delete(plan)
        db.session.commit()
        logger.info("训练计划已删除: %s", plan.title)
        return jsonify({"success": True})


@app.route("/api/plans/<int:plan_id>/days", methods=["GET", "PUT"])
@login_required
def api_plan_days(plan_id):
    """获取或批量更新计划的天内容"""
    plan = TrainingPlan.query.get(plan_id)
    if not plan:
        return jsonify({"error": "计划不存在"}), 404

    if plan.coach_id != g.current_user.id and g.current_user.role != "admin":
        return jsonify({"error": "权限不足"}), 403

    if request.method == "GET":
        days = PlanDay.query.filter_by(plan_id=plan_id).order_by(
            PlanDay.week_number, PlanDay.day_number).all()
        return jsonify([d.to_dict() for d in days])

    if request.method == "PUT":
        data = request.get_json()
        updated = []
        for day_data in data:
            day_id = day_data.get("id")
            if day_id:
                # 更新已有天
                day = PlanDay.query.get(day_id)
                if day and day.plan_id == plan_id:
                    _update_day_from_dict(day, day_data)
                    updated.append(day)
            else:
                # 新建天
                day = PlanDay(plan_id=plan_id)
                _update_day_from_dict(day, day_data)
                db.session.add(day)
                updated.append(day)
        db.session.commit()
        return jsonify({"success": True, "days": [d.to_dict() for d in updated]})


def _update_day_from_dict(day, data):
    """辅助: 从字典更新 PlanDay 字段"""
    if "week_number" in data:
        day.week_number = int(data["week_number"])
    if "day_number" in data:
        day.day_number = int(data["day_number"])
    if "focus_area" in data:
        day.focus_area = data["focus_area"]
    if "warmup" in data:
        day.warmup = data["warmup"]
    if "main_workout" in data:
        day.main_workout = data["main_workout"]
    if "cool_down" in data:
        day.cool_down = data["cool_down"]
    if "duration_min" in data:
        day.duration_min = int(data["duration_min"]) if data["duration_min"] else None
    if "notes" in data:
        day.notes = data["notes"]


def _init_plan_days(plan):
    """为计划初始化周×天的空表格"""
    DAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for w in range(1, plan.duration_weeks + 1):
        for d in range(1, 8):
            day = PlanDay(
                plan_id=plan.id,
                week_number=w,
                day_number=d,
                focus_area="",
                warmup="",
                main_workout="",
                cool_down="",
                duration_min=60,
                notes="",
            )
            db.session.add(day)
    db.session.commit()


@app.route("/api/plans/<int:plan_id>/assign", methods=["POST"])
@login_required
def api_plan_assign(plan_id):
    """分配训练计划给运动员"""
    plan = TrainingPlan.query.get(plan_id)
    if not plan:
        return jsonify({"error": "计划不存在"}), 404

    if plan.coach_id != g.current_user.id and g.current_user.role != "admin":
        return jsonify({"error": "权限不足"}), 403

    data = request.get_json()
    athlete_id = int(data.get("athlete_id", 0))
    if not athlete_id:
        return jsonify({"error": "请选择运动员"}), 400

    athlete = Athlete.query.get(athlete_id)
    if not athlete:
        return jsonify({"error": "运动员不存在"}), 404

    # 检查是否已分配
    existing = AthletePlan.query.filter_by(athlete_id=athlete_id, plan_id=plan_id).first()
    if existing:
        return jsonify({"error": "该运动员已被分配此计划"}), 409

    ap = AthletePlan(
        athlete_id=athlete_id,
        plan_id=plan_id,
        assigned_date=date.today(),
        status="active",
        coach_notes=data.get("coach_notes", "").strip(),
    )
    db.session.add(ap)
    db.session.commit()

    logger.info("训练计划已分配: 计划=%s → 运动员=%s", plan.title, athlete.name)
    return jsonify({"success": True, "athlete_plan": ap.to_dict()}), 201


@app.route("/api/athlete/me/plan")
@login_required
def api_athlete_my_plan():
    """运动员端 — 获取我的训练计划"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    if not athlete:
        return jsonify({"error": "请先完善运动员档案"}), 400

    athlete_plan = AthletePlan.query.filter_by(
        athlete_id=athlete.id, status="active"
    ).first()

    if not athlete_plan:
        return jsonify({"plan": None, "days": [], "athlete_plan": None})

    plan = athlete_plan.plan
    days = PlanDay.query.filter_by(plan_id=plan.id).order_by(
        PlanDay.week_number, PlanDay.day_number).all()

    return jsonify({
        "plan": plan.to_dict() if plan else None,
        "athlete_plan": athlete_plan.to_dict(),
        "days": [d.to_dict() for d in days],
    })


@app.route("/api/athlete/me/plan/progress", methods=["POST"])
@login_required
def api_athlete_plan_progress():
    """运动员端 — 标记某天已完成"""
    user = g.current_user
    athlete = Athlete.query.filter_by(user_id=user.id).first()
    if not athlete:
        return jsonify({"error": "请先完善运动员档案"}), 400

    athlete_plan = AthletePlan.query.filter_by(
        athlete_id=athlete.id, status="active"
    ).first()
    if not athlete_plan:
        return jsonify({"error": "当前没有激活的训练计划"}), 400

    data = request.get_json()
    day_id = int(data.get("day_id", 0))
    action = data.get("action", "toggle")  # toggle / mark / unmark

    if not day_id:
        return jsonify({"error": "请指定训练日"}), 400

    # 验证 day_id 属于当前计划
    day = PlanDay.query.get(day_id)
    if not day or day.plan_id != athlete_plan.plan_id:
        return jsonify({"error": "训练日不属于当前计划"}), 400

    completed = athlete_plan.get_completed_day_ids()

    if action == "mark" or (action == "toggle" and day_id not in completed):
        if day_id not in completed:
            completed.append(day_id)
    elif action == "unmark" or (action == "toggle" and day_id in completed):
        completed = [d for d in completed if d != day_id]

    athlete_plan.set_completed_day_ids(completed)
    db.session.commit()

    return jsonify({
        "success": True,
        "progress_pct": athlete_plan.progress_pct,
        "completed_days": completed,
    })


@app.route("/api/coach/plans/<int:plan_id>/progress")
@login_required
def api_coach_plan_progress(plan_id):
    """教练端 — 查看计划的各运动员执行进度"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return jsonify({"error": "权限不足"}), 403

    plan = TrainingPlan.query.get(plan_id)
    if not plan:
        return jsonify({"error": "计划不存在"}), 404

    assigned = AthletePlan.query.filter_by(plan_id=plan_id).all()
    return jsonify([ap.to_dict() for ap in assigned])


@app.route("/api/athlete/plans/unassign/<int:athlete_plan_id>", methods=["DELETE"])
@login_required
def api_unassign_plan(athlete_plan_id):
    """教练端 — 取消分配"""
    if g.current_user.role not in ("coach", "doctor", "analyst", "admin"):
        return jsonify({"error": "权限不足"}), 403

    ap = AthletePlan.query.get(athlete_plan_id)
    if not ap:
        return jsonify({"error": "分配记录不存在"}), 404

    db.session.delete(ap)
    db.session.commit()
    return jsonify({"success": True})


# ==================== 上下文处理器 ====================

@app.context_processor
def inject_brand():
    """在所有模板中注入品牌配置"""
    return {"brand": BrandConfig, "config": Config}


# ==================== 应用入口 ====================

# 数据库初始化（兼容 gunicorn 和直接运行）
_db_initialized = False

def _ensure_db():
    """确保数据库已初始化（幂等，首次请求时自动调用）"""
    global _db_initialized
    if _db_initialized:
        return
    try:
        db.create_all()
        FitnessTest.seed_defaults()
        # 创建管理员
        admin_user = app.config.get("ADMIN_USERNAME", "admin")
        admin_pass = app.config.get("ADMIN_PASSWORD", "admin123")
        if not User.query.filter_by(username=admin_user).first():
            admin = User(
                username=admin_user,
                password_hash=generate_password_hash(admin_pass),
                role="admin",
                display_name="系统管理员",
            )
            db.session.add(admin)
        # 创建演示用户（如果不存在）
        demo_users = [
            ("coach1", generate_password_hash("coach123"), "coach", "王教练"),
            ("athlete1", generate_password_hash("athlete123"), "athlete", "张三"),
            ("athlete2", generate_password_hash("athlete123"), "athlete", "李四"),
        ]
        for uname, phash, role, dname in demo_users:
            if not User.query.filter_by(username=uname).first():
                db.session.add(User(username=uname, password_hash=phash, role=role, display_name=dname))
        db.session.commit()
        # 如果运动员档案不存在，创建默认档案
        if not Athlete.query.first():
            a1 = Athlete(user_id=User.query.filter_by(username="athlete1").first().id,
                         name="张三", gender="男", sport_type="篮球", position="前锋",
                         height_cm=198.0, weight_kg=95.0, level="省级", training_years=8)
            a2 = Athlete(user_id=User.query.filter_by(username="athlete2").first().id,
                         name="李四", gender="男", sport_type="篮球", position="后卫",
                         height_cm=185.0, weight_kg=78.0, level="省级", training_years=6)
            db.session.add_all([a1, a2])
            db.session.commit()
        # 如果没有任何测试记录，生成演示数据
        if not TestRecord.query.first():
            _seed_demo_data()
        _db_initialized = True
        logger.info("数据库初始化完成（含演示用户+数据）")
    except Exception as e:
        import traceback as _tb
        logger.warning("数据库初始化失败（将重试）: %s\n%s", e, _tb.format_exc())


def _seed_demo_data():
    """生成演示用的测试记录和训练日志"""
    import random
    from datetime import timedelta
    
    athletes = Athlete.query.all()
    tests = FitnessTest.query.all()
    if not athletes or not tests:
        return
    
    today = date.today()
    # 为每个运动员生成最近6个月的数据
    for athlete in athletes:
        for month_offset in range(6):
            test_date = today - timedelta(days=30 * month_offset + random.randint(0, 14))
            # 每个运动员每月测4-8个项目
            for test in random.sample(tests, min(len(tests), random.randint(4, 8))):
                # 模拟递进进步趋势
                base = random.uniform(0.7, 1.3)  # 基础值
                progress = 1 + (6 - month_offset) * random.uniform(-0.03, 0.05)  # 进步因子
                # 根据测试类型生成合理值
                if test.unit == "秒":
                    val = round(base * 5 * progress, 2)
                elif test.unit == "厘米":
                    val = round(base * 60 * progress, 1)
                elif test.unit == "公斤":
                    val = round(base * 80 * progress, 1) if athlete.name == "张三" else round(base * 65 * progress, 1)
                elif test.unit == "次":
                    val = round(base * 15 * progress)
                elif test.unit == "级":
                    val = round(base * 12 * progress, 1)
                elif test.unit == "%":
                    val = round(base * 15 * progress, 1)
                elif test.unit == "分":
                    val = round(base * 14 * progress)
                else:
                    val = round(base * 10 * progress, 1)
                
                db.session.add(TestRecord(
                    athlete_id=athlete.id, test_id=test.id,
                    test_date=test_date, raw_value=val
                ))
        
        # 每月一条身体指标
        for month_offset in range(6):
            m_date = today - timedelta(days=30 * month_offset + 15)
            db.session.add(BodyMetric(
                athlete_id=athlete.id, record_date=m_date,
                weight_kg=athlete.weight_kg + random.uniform(-2, 2),
                body_fat_pct=round(12 + random.uniform(-3, 3), 1),
                resting_hr=random.randint(48, 65),
            ))
        
        # 每周2-3条训练日志
        for week_offset in range(24):
            t_date = today - timedelta(days=week_offset * 3 + random.randint(0, 2))
            if t_date > today:
                continue
            intensities = ["low", "medium", "high"]
            workouts = ["力量训练-深蹲+卧推", "速度训练-冲刺跑", "有氧耐力-5km跑",
                       "爆发力训练-跳箱", "敏捷训练-折返跑", "恢复训练-拉伸"]
            db.session.add(TrainingLog(
                athlete_id=athlete.id, session_date=t_date,
                duration_min=random.randint(45, 120),
                intensity=random.choice(intensities),
                rpe=random.randint(4, 9),
                content=random.choice(workouts),
                hr_avg=random.randint(110, 160),
            ))
    
    db.session.commit()
    logger.info("演示数据已生成: %d名运动员, %d个测试项目", len(athletes), len(tests))

# 立即尝试初始化（在应用上下文中执行，确保 gunicorn 启动时即完成初始化）
try:
    with app.app_context():
        _ensure_db()
except Exception as _init_err:
    import traceback as _tb2
    logger.warning("启动时数据库初始化失败（将在首次请求时重试）: %s\n%s", _init_err, _tb2.format_exc())

@app.before_request
def _init_db_on_first_request():
    """首次请求时确保数据库已初始化"""
    _ensure_db()


if __name__ == "__main__":
    with app.app_context():
        _ensure_db()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", True))
