"""
运动员数据分析平台 - 种子数据脚本
运行方式:  python seed_data.py
基于 models.py 的数据模型填充本地 SQLite 数据库。
"""
import sys
import os
import random
from datetime import date, timedelta

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import app, db
from models import (
    User, Athlete, FitnessTest, TestRecord,
    TrainingLog, BodyMetric, InjuryRecord,
    FITNESS_TESTS,
)


# ── 工具函数 ──────────────────────────────────────────────────────────────

def _clear_all():
    """清空所有数据（保留表结构）"""
    for model in [BodyMetric, InjuryRecord, TrainingLog, TestRecord,
                  FitnessTest, Athlete, User]:
        model.query.delete()
    db.session.commit()
    print("  [OK] 已清空所有数据")


def _seed_users():
    """创建测试用户，返回 {role: User} 字典"""
    users = {}

    admin = User(username="admin", role="admin", display_name="超级管理员")
    admin.set_password("admin123")
    db.session.add(admin)
    users["admin"] = admin

    coach = User(username="coach1", role="coach", display_name="陈教练")
    coach.set_password("coach123")
    db.session.add(coach)
    users["coach"] = coach

    a1 = User(username="athlete1", role="athlete", display_name="张三")
    a1.set_password("athlete123")
    db.session.add(a1)
    users["athlete1"] = a1

    a2 = User(username="athlete2", role="athlete", display_name="李四")
    a2.set_password("athlete123")
    db.session.add(a2)
    users["athlete2"] = a2

    db.session.commit()
    print("  [OK] 创建用户: admin, coach1, athlete1, athlete2")
    return users


def _seed_athletes(users):
    """创建运动员档案，返回 {key: Athlete} 字典"""
    athletes = {}

    # 张三：篮球 / 前锋
    a1 = Athlete(
        user_id=users["athlete1"].id,
        name="张三",
        gender="男",
        birth_date=date(2002, 3, 15),
        height_cm=198.0,
        weight_kg=95.0,
        sport_type="篮球",
        position="前锋",
        level="省级",
        training_years=6,
        notes="爆发力突出，篮下终结能力强",
    )
    db.session.add(a1)
    athletes["athlete1"] = a1

    # 李四：篮球 / 后卫
    a2 = Athlete(
        user_id=users["athlete2"].id,
        name="李四",
        gender="男",
        birth_date=date(2003, 7, 22),
        height_cm=185.0,
        weight_kg=78.0,
        sport_type="篮球",
        position="后卫",
        level="市级",
        training_years=4,
        notes="速度快，擅长外线投射与组织",
    )
    db.session.add(a2)
    athletes["athlete2"] = a2

    db.session.commit()
    print("  [OK] 创建运动员档案: 张三(篮球/前锋), 李四(篮球/后卫)")
    return athletes


def _seed_fitness_tests():
    """填充测试项目（幂等）"""
    FitnessTest.seed_defaults()
    print(f"  [OK] 已填充 {len(FITNESS_TESTS)} 个测试项目")


# ── 模拟数据生成器 ───────────────────────────────────────────────────────

# 每种测试的基准值（张三-前锋, 李四-后卫）
TEST_BASELINE = {
    "30米冲刺":      (4.1,  3.9),
    "立定跳远":      (280,  260),
    "T型跑":         (9.8,  9.2),
    "坐位体前屈":    (12,   18),
    "卧推1RM":       (100,  75),
    "深蹲1RM":       (150,  120),
    "垂直纵跳":      (75,   65),
    "YoYo间歇恢复":  (17.5, 18.5),
    "20米折返跑":    (12,   14),
    "引体向上":      (15,   18),
    "体脂率":        (12.0, 10.0),
    "FMS总分":       (16,   18),
}

TEST_VARIANCE = {
    "30米冲刺":      0.08,
    "立定跳远":      8,
    "T型跑":         0.20,
    "坐位体前屈":    3,
    "卧推1RM":       5,
    "深蹲1RM":       7.5,
    "垂直纵跳":      4,
    "YoYo间歇恢复":  0.5,
    "20米折返跑":    1,
    "引体向上":      2,
    "体脂率":        0.8,
    "FMS总分":       1,
}


def _generate_test_records(athlete_obj, athlete_idx: int):
    """
    为一位运动员生成过去 6 个月、每月 1 次、全部 12 项测试的记录。
    带轻微上升趋势模拟体能进步。
    """
    tests = FitnessTest.query.all()
    today = date.today()
    records_created = 0

    for month_offset in range(6):
        test_date = today.replace(day=1) - timedelta(days=month_offset * 30 + 15)
        test_date = test_date.replace(day=min(test_date.day, 28))

        progress = 1.0 + (5 - month_offset) * 0.008  # 微小的月度进步

        for ft in tests:
            base_pair = TEST_BASELINE.get(ft.name)
            if base_pair is None:
                continue
            base_val = base_pair[athlete_idx]
            variance = TEST_VARIANCE.get(ft.name, 5)

            smaller_better = ft.unit in ("秒", "%")
            trend = 1.0 / progress if smaller_better else progress

            value = round(base_val * trend + random.gauss(0, variance), 2)
            if value < 0:
                value = abs(value)

            record = TestRecord(
                athlete_id=athlete_obj.id,
                test_id=ft.id,
                raw_value=value,
                test_date=test_date,
                notes=f"第{6 - month_offset}次月度测试",
            )
            db.session.add(record)
            records_created += 1

    db.session.commit()
    return records_created


def _seed_training_logs(athlete_obj, athlete_idx: int):
    """
    为一位运动员生成最近 30 天的训练日志（每天 1 条）。
    """
    today = date.today()
    log_count = 0

    if athlete_idx == 0:
        workouts = [
            "下肢力量日：深蹲 5x5 @120kg + 弓步走 4x12 + 腿弯举 3x15",
            "上肢力量日：卧推 5x5 @90kg + 引体向上 4x至力竭 + 哑铃推举 3x10",
            "爆发力训练：跳箱 5x5 @100cm + 药球投掷 4x8 + 短距离冲刺 6x30m",
            "敏捷性训练：T型跑 5组 + 绳梯步伐 + 锥桶变向",
            "有氧恢复日：慢跑 30min + 动态拉伸 + 泡沫轴放松",
            "篮球专项：对抗上篮 + 篮板卡位 + 半场攻防演练",
            "核心训练：平板支撑 5x60s + 俄罗斯转体 4x20 + 悬垂举腿 3x15",
        ]
    else:
        workouts = [
            "速度耐力日：20米折返跑 10组 + 间歇冲刺 8x60m",
            "投篮专项：定点投篮 200次 + 移动投篮 100次 + 罚球 50次",
            "敏捷性训练：T型跑 5组 + 锥桶滑步 + 反应起跑",
            "有氧耐力：YoYo间歇跑 + 400m间歇 x6",
            "核心与稳定：瑜伽球训练 + 单腿平衡 + 抗旋转核心",
            "篮球专项：挡拆配合 + 三分战术 + 全场快攻",
            "恢复日：游泳 45min + 拉伸 + 按摩枪放松",
        ]

    for day_offset in range(30):
        log_date = today - timedelta(days=day_offset)

        if random.random() < 0.12:
            content = "休息日"
            duration = 0
            intensity = "low"
            rpe = 0
            distance = None
            calories = None
            hr_avg = None
            hr_max = None
        else:
            content = random.choice(workouts)
            duration = random.randint(45, 120)
            intensity = random.choice(["low", "medium", "medium", "high"])
            rpe = {"low": random.randint(2, 4), "medium": random.randint(5, 7), "high": random.randint(7, 9)}[intensity]
            distance = round(random.uniform(1.0, 5.0), 1) if random.random() > 0.3 else None
            calories = random.randint(200, 800) if random.random() > 0.3 else None
            hr_avg = random.randint(110, 150) if random.random() > 0.3 else None
            hr_max = random.randint(150, 190) if random.random() > 0.3 else None

        log = TrainingLog(
            athlete_id=athlete_obj.id,
            session_date=log_date,
            duration_min=duration,
            intensity=intensity,
            rpe=rpe,
            content=content,
            total_distance_km=distance,
            calories_burned=calories,
            hr_avg=hr_avg,
            hr_max=hr_max,
        )
        db.session.add(log)
        log_count += 1

    db.session.commit()
    return log_count


def _seed_body_metrics(athlete_obj, athlete_idx: int):
    """为一位运动员生成最近 6 个月的身体指标记录（每月 1 次）"""
    today = date.today()
    metrics_count = 0

    # 基准值 (张三, 李四)
    if athlete_idx == 0:
        base = {"weight": 95.0, "fat": 12.0, "muscle": 78.0, "hr": 55, "vo2": 52.0}
    else:
        base = {"weight": 78.0, "fat": 10.0, "muscle": 66.0, "hr": 50, "vo2": 55.0}

    for month_offset in range(6):
        record_date = today.replace(day=1) - timedelta(days=month_offset * 30 + 10)
        record_date = record_date.replace(day=min(record_date.day, 28))

        metric = BodyMetric(
            athlete_id=athlete_obj.id,
            record_date=record_date,
            weight_kg=round(base["weight"] + random.gauss(0, 0.5), 1),
            body_fat_pct=round(base["fat"] + random.gauss(0, 0.3), 1),
            muscle_mass_kg=round(base["muscle"] + random.gauss(0, 0.4), 1),
            resting_hr=base["hr"] + random.randint(-3, 3),
            blood_pressure_sys=random.randint(110, 125),
            blood_pressure_dia=random.randint(65, 80),
            vo2_max=round(base["vo2"] + random.gauss(0, 1.0), 1),
            notes="",
        )
        db.session.add(metric)
        metrics_count += 1

    db.session.commit()
    return metrics_count


# ── 主流程 ────────────────────────────────────────────────────────────────

def main():
    print("=" * 56)
    print("  运动员数据分析平台 - 种子数据脚本")
    print("=" * 56)
    print()

    with app.app_context():
        # 1. 清空旧数据
        print("[1/6] 清空旧数据...")
        _clear_all()

        # 2. 创建用户
        print("[2/6] 创建测试用户...")
        users = _seed_users()

        # 3. 运动员档案
        print("[3/6] 创建运动员档案...")
        athletes = _seed_athletes(users)

        # 4. 测试项目
        print("[4/6] 填充测试项目...")
        _seed_fitness_tests()

        # 5. 模拟数据
        print("[5/6] 生成模拟数据...")
        r1 = _generate_test_records(athletes["athlete1"], 0)
        r2 = _generate_test_records(athletes["athlete2"], 1)
        print(f"  [OK] 张三: {r1} 条测试记录")
        print(f"  [OK] 李四: {r2} 条测试记录")

        l1 = _seed_training_logs(athletes["athlete1"], 0)
        l2 = _seed_training_logs(athletes["athlete2"], 1)
        print(f"  [OK] 张三: {l1} 条训练日志")
        print(f"  [OK] 李四: {l2} 条训练日志")

        m1 = _seed_body_metrics(athletes["athlete1"], 0)
        m2 = _seed_body_metrics(athletes["athlete2"], 1)
        print(f"  [OK] 张三: {m1} 条身体指标")
        print(f"  [OK] 李四: {m2} 条身体指标")

        # 6. 伤病记录（李四有一条历史伤病）
        print("[6/6] 生成伤病记录...")
        injury = InjuryRecord(
            athlete_id=athletes["athlete2"].id,
            injury_date=date.today() - timedelta(days=45),
            body_part="左脚踝",
            injury_type="扭伤",
            severity="mild",
            description="训练中落地踩到队友脚导致轻度扭伤",
            recovery_date=date.today() - timedelta(days=25),
            status="recovered",
            notes="已完全恢复，注意踝关节稳定性训练",
        )
        db.session.add(injury)
        db.session.commit()
        print("  [OK] 李四: 1 条伤病记录 (已恢复)")

    print()
    print("=" * 56)
    print("  种子数据创建完成!")
    print()
    print("  登录账号:")
    print("    管理员  admin    / admin123")
    print("    教练    coach1   / coach123")
    print("    运动员  athlete1 / athlete123  (张三)")
    print("    运动员  athlete2 / athlete123  (李四)")
    print("=" * 56)


if __name__ == "__main__":
    main()
