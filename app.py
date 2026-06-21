""""
运动员数据分析平台 - Flask 主应用
运动员数据分析平台
"""

import json
import logging
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
    Video
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
    # 如果没有管理员用户，创建默认管理员
    if not User.query.filter_by(username="admin").first():
        admin = User(
            username="admin",
            password_hash=generate_password_hash("admin123"),
            role="admin",
            display_name="系统管理员",
        )
        db.session.add(admin)
        db.session.commit()
        logger.info("已创建默认管理员账户 (admin / admin123)")
    logger.info("数据库初始化完成")


# ==================== 页面路由 ====================

@app.route("/")
def index():
    """首页 - 根据登录状态跳转到仪表盘或登录页"""
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


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
            .order_by(BodyMetric.record_date.desc()).limit(5).all()
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

    return render_template(
        "dashboard.html",
        user=user,
        athlete=athlete,
        latest_metric=latest_metric,
        recent_metrics=recent_metrics,
        recent_tests=recent_tests,
        recent_training=recent_training,
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
    success = process_single_video(video.id, app)

    return jsonify({
        "success": success,
        "status": video.status,
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


# ==================== 错误处理 ====================

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


# ==================== 上下文处理器 ====================

@app.context_processor
def inject_brand():
    """在所有模板中注入品牌配置"""
    return {"brand": BrandConfig, "config": Config}


# ==================== 应用入口 ====================

if __name__ == "__main__":
    # 初始化数据库
    with app.app_context():
        init_db()

    # 启动应用
    app.run(host="0.0.0.0", port=5000, debug=app.config.get("DEBUG", True))
