"""
运动员数据分析平台 - 数据模型
本地 MVP 版本 - SQLAlchemy ORM
"""
import json
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from config import BrandConfig

db = SQLAlchemy()


# ═══════════════════════════════════════════════════════════════════════════
# 用户
# ═══════════════════════════════════════════════════════════════════════════

class User(db.Model):
    """平台用户（运动员/教练/队医/分析师/管理员）"""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="athlete")
    display_name = db.Column(db.String(120), nullable=False)
    avatar_url = db.Column(db.String(500), default="")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    athlete = db.relationship("Athlete", back_populates="user", uselist=False)
    chat_messages = db.relationship("ChatMessage", back_populates="user", lazy="dynamic")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def role_label(self) -> str:
        return BrandConfig.ROLE_LABELS.get(self.role, self.role)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "display_name": self.display_name,
            "role_label": self.role_label,
        }

    def __repr__(self):
        return f"<User {self.username} [{self.role}]>"


# ═══════════════════════════════════════════════════════════════════════════
# 运动员档案
# ═══════════════════════════════════════════════════════════════════════════

class Athlete(db.Model):
    """运动员详细档案"""
    __tablename__ = "athletes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False, default="")
    gender = db.Column(db.String(10), default="")
    birth_date = db.Column(db.Date, nullable=True)
    height_cm = db.Column(db.Float, default=0.0)
    weight_kg = db.Column(db.Float, default=0.0)
    sport_type = db.Column(db.String(80), default="")
    position = db.Column(db.String(80), default="")
    level = db.Column(db.String(40), default="")
    training_years = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text, default="")
    avatar_url = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    user = db.relationship("User", back_populates="athlete")
    body_metrics = db.relationship("BodyMetric", back_populates="athlete", lazy="dynamic")
    test_records = db.relationship("TestRecord", back_populates="athlete", lazy="dynamic")
    training_logs = db.relationship("TrainingLog", back_populates="athlete", lazy="dynamic")
    injury_records = db.relationship("InjuryRecord", back_populates="athlete", lazy="dynamic")

    @property
    def age(self) -> int:
        if self.birth_date:
            today = date.today()
            return today.year - self.birth_date.year - (
                (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
            )
        return 0

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "gender": self.gender,
            "age": self.age,
            "height_cm": self.height_cm,
            "weight_kg": self.weight_kg,
            "sport_type": self.sport_type,
            "position": self.position,
            "level": self.level,
            "training_years": self.training_years,
            "notes": self.notes,
        }

    def __repr__(self):
        return f"<Athlete {self.name} {self.sport_type}/{self.position}>"


# ═══════════════════════════════════════════════════════════════════════════
# 身体指标
# ═══════════════════════════════════════════════════════════════════════════

class BodyMetric(db.Model):
    """运动员身体指标记录"""
    __tablename__ = "body_metrics"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("athletes.id"), nullable=False, index=True)
    record_date = db.Column(db.Date, nullable=False, default=date.today, index=True)

    weight_kg = db.Column(db.Float, nullable=True)
    body_fat_pct = db.Column(db.Float, nullable=True)
    muscle_mass_kg = db.Column(db.Float, nullable=True)
    resting_hr = db.Column(db.Integer, nullable=True)
    blood_pressure_sys = db.Column(db.Integer, nullable=True)
    blood_pressure_dia = db.Column(db.Integer, nullable=True)
    vo2_max = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, default="")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    athlete = db.relationship("Athlete", back_populates="body_metrics")

    def to_dict(self):
        return {
            "id": self.id,
            "athlete_id": self.athlete_id,
            "record_date": self.record_date.isoformat() if self.record_date else None,
            "weight_kg": self.weight_kg,
            "body_fat_pct": self.body_fat_pct,
            "muscle_mass_kg": self.muscle_mass_kg,
            "resting_hr": self.resting_hr,
            "blood_pressure_sys": self.blood_pressure_sys,
            "blood_pressure_dia": self.blood_pressure_dia,
            "vo2_max": self.vo2_max,
            "notes": self.notes,
        }

    def __repr__(self):
        return f"<BodyMetric #{self.id} date={self.record_date}>"


# ═══════════════════════════════════════════════════════════════════════════
# 体能测试项目（种子数据）
# ═══════════════════════════════════════════════════════════════════════════

FITNESS_TESTS = [
    # (name, category, unit, description)
    ("30米冲刺", "速度", "秒", "站立式起跑30米计时"),
    ("立定跳远", "爆发力", "厘米", "原地立定向前跳跃距离"),
    ("T型跑", "敏捷性", "秒", "T形路线折返跑计时"),
    ("坐位体前屈", "柔韧性", "厘米", "坐姿前屈指尖超脚尖距离"),
    ("卧推1RM", "上肢力量", "公斤", "卧推单次最大重量（估算）"),
    ("深蹲1RM", "下肢力量", "公斤", "杠铃深蹲单次最大重量（估算）"),
    ("垂直纵跳", "爆发力", "厘米", "原地纵跳摸高-站立摸高"),
    ("YoYo间歇恢复", "有氧耐力", "级", "Yo-Yo IR1 达到的级别"),
    ("20米折返跑", "速度耐力", "次", "20米多趟折返跑次数/时间"),
    ("引体向上", "上肢耐力", "次", "标准引体向上至力竭"),
    ("体脂率", "身体成分", "%", "皮褶法或生物电阻抗测定"),
    ("FMS总分", "功能性筛查", "分", "功能性动作筛查7项总分(0-21)"),
]


class FitnessTest(db.Model):
    """体能测试项目定义"""
    __tablename__ = "fitness_tests"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    category = db.Column(db.String(40), nullable=False, default="")
    unit = db.Column(db.String(20), default="")
    description = db.Column(db.Text, default="")
    is_active = db.Column(db.Boolean, default=True)

    records = db.relationship("TestRecord", back_populates="test", lazy="dynamic")

    @classmethod
    def seed_defaults(cls):
        """将 FITNESS_TESTS 同步到数据库，幂等"""
        for name, cat, unit, desc in FITNESS_TESTS:
            if not cls.query.filter_by(name=name).first():
                db.session.add(cls(name=name, category=cat, unit=unit, description=desc))
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "unit": self.unit,
            "description": self.description,
        }

    def __repr__(self):
        return f"<FitnessTest {self.name}>"


# ═══════════════════════════════════════════════════════════════════════════
# 测试记录
# ═══════════════════════════════════════════════════════════════════════════

class TestRecord(db.Model):
    """运动员单次体能测试记录"""
    __tablename__ = "test_records"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("athletes.id"), nullable=False, index=True)
    test_id = db.Column(db.Integer, db.ForeignKey("fitness_tests.id"), nullable=False)
    raw_value = db.Column(db.Float, nullable=False)
    test_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    athlete = db.relationship("Athlete", back_populates="test_records")
    test = db.relationship("FitnessTest", back_populates="records")

    def to_dict(self):
        return {
            "id": self.id,
            "athlete_id": self.athlete_id,
            "test_id": self.test_id,
            "test_name": self.test.name if self.test else None,
            "test_category": self.test.category if self.test else None,
            "test_unit": self.test.unit if self.test else None,
            "raw_value": self.raw_value,
            "test_date": self.test_date.isoformat() if self.test_date else None,
            "notes": self.notes,
        }

    def __repr__(self):
        return f"<TestRecord #{self.id} test={self.test_id} val={self.raw_value}>"


# ═══════════════════════════════════════════════════════════════════════════
# 训练日志
# ═══════════════════════════════════════════════════════════════════════════

class TrainingLog(db.Model):
    """运动员日常训练日志"""
    __tablename__ = "training_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("athletes.id"), nullable=False, index=True)
    session_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    duration_min = db.Column(db.Integer, nullable=True)
    intensity = db.Column(db.String(20), nullable=True)
    rpe = db.Column(db.Integer, nullable=True)
    content = db.Column(db.Text, default="")
    total_distance_km = db.Column(db.Float, nullable=True)
    calories_burned = db.Column(db.Integer, nullable=True)
    hr_avg = db.Column(db.Integer, nullable=True)
    hr_max = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    athlete = db.relationship("Athlete", back_populates="training_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "athlete_id": self.athlete_id,
            "session_date": self.session_date.isoformat() if self.session_date else None,
            "duration_min": self.duration_min,
            "intensity": self.intensity,
            "rpe": self.rpe,
            "content": self.content,
            "total_distance_km": self.total_distance_km,
            "calories_burned": self.calories_burned,
            "hr_avg": self.hr_avg,
            "hr_max": self.hr_max,
            "notes": self.notes,
        }

    def __repr__(self):
        return f"<TrainingLog #{self.id} {self.session_date} rpe={self.rpe}>"


# ═══════════════════════════════════════════════════════════════════════════
# 伤病记录
# ═══════════════════════════════════════════════════════════════════════════

class InjuryRecord(db.Model):
    """运动员伤病记录"""
    __tablename__ = "injury_records"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("athletes.id"), nullable=False, index=True)
    injury_date = db.Column(db.Date, nullable=False, default=date.today)
    body_part = db.Column(db.String(80), default="")
    injury_type = db.Column(db.String(80), default="")
    severity = db.Column(db.String(20), default="mild")  # mild / moderate / severe
    description = db.Column(db.Text, default="")
    recovery_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), default="active")  # active / recovering / recovered
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    athlete = db.relationship("Athlete", back_populates="injury_records")

    def to_dict(self):
        return {
            "id": self.id,
            "athlete_id": self.athlete_id,
            "injury_date": self.injury_date.isoformat() if self.injury_date else None,
            "body_part": self.body_part,
            "injury_type": self.injury_type,
            "severity": self.severity,
            "description": self.description,
            "recovery_date": self.recovery_date.isoformat() if self.recovery_date else None,
            "status": self.status,
            "notes": self.notes,
        }

    def __repr__(self):
        return f"<InjuryRecord #{self.id} {self.body_part} [{self.status}]>"


# ═══════════════════════════════════════════════════════════════════════════
# AI 对话消息
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# 视频管理
# ═══════════════════════════════════════════════════════════════════════════

class Video(db.Model):
    """运动员训练/测试视频"""
    __tablename__ = "videos"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    video_id = db.Column(db.String(32), unique=True, nullable=False, index=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("athletes.id"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), default="")
    file_size = db.Column(db.Integer, default=0)  # bytes
    status = db.Column(db.String(20), default="uploaded")  # uploaded/processing/done/error
    test_type = db.Column(db.String(50), default="")
    duration_seconds = db.Column(db.Float, default=0.0)
    analysis_results = db.Column(db.Text, default="")  # JSON
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    athlete = db.relationship("Athlete", backref="videos")

    @property
    def status_label(self) -> str:
        labels = {
            "uploaded": "已上传",
            "processing": "处理中",
            "done": "已完成",
            "error": "处理失败",
        }
        return labels.get(self.status, self.status)

    @property
    def file_size_mb(self) -> float:
        return round(self.file_size / (1024 * 1024), 2) if self.file_size else 0

    @property
    def parsed_results(self) -> dict:
        """解析 analysis_results JSON"""
        if self.analysis_results:
            try:
                return json.loads(self.analysis_results)
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    def to_dict(self):
        return {
            "id": self.id,
            "video_id": self.video_id,
            "athlete_id": self.athlete_id,
            "filename": self.filename,
            "original_filename": self.original_filename,
            "file_size": self.file_size,
            "file_size_mb": self.file_size_mb,
            "status": self.status,
            "status_label": self.status_label,
            "test_type": self.test_type,
            "duration_seconds": self.duration_seconds,
            "notes": self.notes,
            "analysis_results": self.parsed_results,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Video #{self.id} [{self.status}] {self.original_filename}>"


class ChatMessage(db.Model):
    """AI 对话消息记录"""
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # user / assistant / system
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship("User", back_populates="chat_messages")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<ChatMessage #{self.id} [{self.role}]>"


# ═══════════════════════════════════════════════════════════════════════════
# 训练计划模块
# ═══════════════════════════════════════════════════════════════════════════

class TrainingPlan(db.Model):
    """教练创建的训练计划"""
    __tablename__ = "training_plans"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    coach_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    sport_type = db.Column(db.String(80), default="")
    duration_weeks = db.Column(db.Integer, default=4)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    coach = db.relationship("User", backref="training_plans")
    plan_days = db.relationship("PlanDay", back_populates="plan", lazy="dynamic",
                                cascade="all, delete-orphan")
    athlete_plans = db.relationship("AthletePlan", back_populates="plan", lazy="dynamic",
                                    cascade="all, delete-orphan")

    @property
    def total_days(self):
        return self.plan_days.count()

    @property
    def assigned_count(self):
        return self.athlete_plans.count()

    def to_dict(self):
        return {
            "id": self.id,
            "coach_id": self.coach_id,
            "coach_name": self.coach.display_name if self.coach else "",
            "title": self.title,
            "description": self.description,
            "sport_type": self.sport_type,
            "duration_weeks": self.duration_weeks,
            "is_active": self.is_active,
            "total_days": self.total_days,
            "assigned_count": self.assigned_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<TrainingPlan #{self.id} {self.title}>"


class PlanDay(db.Model):
    """训练计划中每一天的详细内容"""
    __tablename__ = "plan_days"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("training_plans.id"), nullable=False, index=True)
    week_number = db.Column(db.Integer, nullable=False)   # 从1开始
    day_number = db.Column(db.Integer, nullable=False)    # 1-7（星期几）
    focus_area = db.Column(db.String(100), default="")    # 训练重点
    warmup = db.Column(db.Text, default="")               # 热身
    main_workout = db.Column(db.Text, default="")         # 主训练
    cool_down = db.Column(db.Text, default="")            # 放松
    duration_min = db.Column(db.Integer, nullable=True)   # 预计时长（分钟）
    notes = db.Column(db.Text, default="")                # 备注

    # 关系
    plan = db.relationship("TrainingPlan", back_populates="plan_days")

    def to_dict(self):
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "week_number": self.week_number,
            "day_number": self.day_number,
            "focus_area": self.focus_area,
            "warmup": self.warmup,
            "main_workout": self.main_workout,
            "cool_down": self.cool_down,
            "duration_min": self.duration_min,
            "notes": self.notes,
        }

    def __repr__(self):
        return f"<PlanDay W{self.week_number}D{self.day_number} plan={self.plan_id}>"


class AthletePlan(db.Model):
    """运动员与训练计划的关联（分配记录）"""
    __tablename__ = "athlete_plans"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    athlete_id = db.Column(db.Integer, db.ForeignKey("athletes.id"), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("training_plans.id"), nullable=False)
    assigned_date = db.Column(db.Date, nullable=False, default=date.today)
    start_date = db.Column(db.Date, nullable=True)  # 实际开始日期
    status = db.Column(db.String(20), default="active")  # active / completed / paused
    progress_pct = db.Column(db.Float, default=0.0)       # 完成百分比
    coach_notes = db.Column(db.Text, default="")

    # 关系
    athlete = db.relationship("Athlete", backref="athlete_plans")
    plan = db.relationship("TrainingPlan", back_populates="athlete_plans")

    # 已完成的天（JSON字符串存储已完成的plan_day_id列表）
    completed_days = db.Column(db.Text, default="[]")

    def get_completed_day_ids(self):
        """返回已完成天数的ID列表"""
        import json
        try:
            return json.loads(self.completed_days)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_completed_day_ids(self, day_ids):
        """设置已完成天数的ID列表"""
        import json
        self.completed_days = json.dumps(day_ids)
        total = self.plan.total_days
        if total > 0:
            self.progress_pct = round(len(day_ids) / total * 100, 1)
        else:
            self.progress_pct = 0.0

    def to_dict(self):
        return {
            "id": self.id,
            "athlete_id": self.athlete_id,
            "athlete_name": self.athlete.name if self.athlete else "",
            "plan_id": self.plan_id,
            "plan_title": self.plan.title if self.plan else "",
            "assigned_date": self.assigned_date.isoformat() if self.assigned_date else None,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "status": self.status,
            "progress_pct": self.progress_pct,
            "coach_notes": self.coach_notes,
            "completed_days": self.get_completed_day_ids(),
        }

    def __repr__(self):
        return f"<AthletePlan a={self.athlete_id} p={self.plan_id} [{self.status}]>"
