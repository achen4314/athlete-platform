"""
运动员数据分析平台 - Z/T-score 统计分析引擎
提供标准化评分计算、运动员画像生成、趋势分析等功能
"""
import math
from collections import defaultdict
from datetime import date

import numpy as np
from scipy import stats as scipy_stats

from models import Athlete, TestRecord, FitnessTest


# ==============================================================================
# 默认参考人群参数
# 这些值来源于通用运动员人群统计数据，教练可在运行时通过 API 更新
# ==============================================================================

DEFAULT_REFERENCES = {
    "30米冲刺":    {"mean": 4.3,  "std": 0.3,  "higher_is_better": False},
    "立定跳远":    {"mean": 250,  "std": 25,   "higher_is_better": True},
    "T型跑":      {"mean": 9.5,  "std": 0.8,  "higher_is_better": False},
    "坐位体前屈":  {"mean": 15,   "std": 8,    "higher_is_better": True},
    "卧推1RM":    {"mean": 80,   "std": 20,   "higher_is_better": True},
    "深蹲1RM":    {"mean": 120,  "std": 30,   "higher_is_better": True},
    "垂直纵跳":    {"mean": 50,   "std": 12,   "higher_is_better": True},
    "YoYo间歇恢复": {"mean": 16,   "std": 3,    "higher_is_better": True},
    "20米折返跑":  {"mean": 55,   "std": 10,   "higher_is_better": True},
    "引体向上":    {"mean": 12,   "std": 6,    "higher_is_better": True},
    "体脂率":      {"mean": 15,   "std": 5,    "higher_is_better": False},
    "FMS总分":    {"mean": 14,   "std": 3,    "higher_is_better": True},
}

# 8大维度分类 → 对应的测试项目
RADAR_CATEGORIES = {
    "速度":     ["30米冲刺"],
    "爆发力":   ["立定跳远", "垂直纵跳"],
    "敏捷性":   ["T型跑"],
    "柔韧性":   ["坐位体前屈"],
    "上肢力量": ["卧推1RM", "引体向上"],
    "下肢力量": ["深蹲1RM"],
    "有氧耐力": ["YoYo间歇恢复", "20米折返跑"],
    "身体成分": ["体脂率", "FMS总分"],
}


class ScoreAnalyzer:
    """
    Z/T-score 统计分析引擎

    使用参考人群的均值与标准差，将运动员原始测试成绩转换为标准化分数：
    - Z-score: 衡量偏离均值的标准差数
    - T-score: 将 Z 映射到均值为 50、标准差为 10 的量表
    - Percentile: 运动员在参考人群中的百分位排名
    """

    def __init__(self, references=None):
        """
        初始化分析器

        Args:
            references: 自定义参考人群参数字典，格式同 DEFAULT_REFERENCES
                        如果为 None 则使用内置默认值
        """
        self.references = references if references is not None else dict(DEFAULT_REFERENCES)

    # ── 核心计算方法 ──────────────────────────────────────────────────────

    def calculate_z_score(self, raw_value, ref_mean, ref_std, higher_is_better):
        """
        计算 Z-score

        公式:
            higher_is_better=True  → Z = (X - μ) / σ
            higher_is_better=False → Z = (μ - X) / σ

        Args:
            raw_value: 运动员原始测试值
            ref_mean: 参考人群均值 μ
            ref_std: 参考人群标准差 σ
            higher_is_better: 数值越大是否越好

        Returns:
            float: Z-score（标准差为零时返回 0.0）
        """
        if ref_std == 0 or ref_std is None:
            return 0.0
        z = (raw_value - ref_mean) / ref_std
        if not higher_is_better:
            z = -z
        return round(z, 2)

    def calculate_t_score(self, z_score):
        """
        将 Z-score 转换为 T-score

        公式: T = 50 + 10 × Z

        Args:
            z_score: Z-score 值

        Returns:
            float: T-score
        """
        return round(50 + 10 * z_score, 2)

    def calculate_percentile(self, z_score):
        """
        根据 Z-score 计算百分位排名

        使用标准正态分布的累积分布函数 (CDF)

        Args:
            z_score: Z-score 值

        Returns:
            float: 百分位值 (0–100)
        """
        percentile = scipy_stats.norm.cdf(z_score) * 100
        return round(percentile, 2)

    # ── 测试项目辅助方法 ──────────────────────────────────────────────────

    def _get_test_ref(self, test_name):
        """
        获取某个测试项目的参考参数

        Args:
            test_name: 测试项目名称（如 "30米冲刺"）

        Returns:
            dict 或 None: 包含 mean, std, higher_is_better 的字典
        """
        return self.references.get(test_name)

    def _compute_single_score(self, test_name, raw_value):
        """
        对单个测试值计算完整的 Z/T/percentile 评分

        Args:
            test_name: 测试项目名称
            raw_value: 原始测试值

        Returns:
            dict: {z_score, t_score, percentile}，参考参数缺失时返回 None
        """
        ref = self._get_test_ref(test_name)
        if ref is None:
            return None
        z = self.calculate_z_score(raw_value, ref["mean"], ref["std"], ref["higher_is_better"])
        return {
            "z_score": z,
            "t_score": self.calculate_t_score(z),
            "percentile": self.calculate_percentile(z),
        }

    # ── 运动员画像 ────────────────────────────────────────────────────────

    def athlete_profile(self, athlete_id, db_session):
        """
        生成运动员完整的 Z/T-score 画像

        获取该运动员所有测试记录，对每项测试计算标准化分数，
        并按类别汇总生成综合评分。

        Args:
            athlete_id: 运动员数据库 ID
            db_session: SQLAlchemy 数据库会话

        Returns:
            dict: {
                "athlete_id": int,
                "scores": [{test_name, raw_value, z_score, t_score, percentile, date, category}, ...],
                "composite_t_score": float,   # 所有测试的平均 T-score
                "category_scores": {类别名: {"mean_t_score": float, "tests": [...]}, ...},
                "test_count": int,
            }
        """
        # 获取运动员所有测试记录（按日期排序）
        records = (
            db_session.query(TestRecord)
            .filter_by(athlete_id=athlete_id)
            .order_by(TestRecord.test_date.desc())
            .all()
        )

        # 每个测试项目取最新的一条记录
        latest_by_test = {}
        for r in records:
            if r.test_id not in latest_by_test:
                latest_by_test[r.test_id] = r

        # 计算每条记录的评分
        scores = []
        test_t_scores = []  # 用于计算综合 T-score

        for test_id, record in latest_by_test.items():
            test = db_session.query(FitnessTest).get(test_id)
            if not test:
                continue

            score = self._compute_single_score(test.name, record.raw_value)
            if score is None:
                continue

            entry = {
                "test_name": test.name,
                "test_category": test.category,
                "raw_value": record.raw_value,
                "unit": test.unit,
                "z_score": score["z_score"],
                "t_score": score["t_score"],
                "percentile": score["percentile"],
                "date": record.test_date.isoformat() if record.test_date else None,
            }
            scores.append(entry)
            test_t_scores.append(score["t_score"])

        # 按类别汇总
        category_scores = defaultdict(lambda: {"t_scores": [], "tests": []})
        for s in scores:
            cat = s["test_category"]
            category_scores[cat]["t_scores"].append(s["t_score"])
            category_scores[cat]["tests"].append(s)

        category_summary = {}
        for cat, data in category_scores.items():
            mean_t = round(np.mean(data["t_scores"]), 2) if data["t_scores"] else 0
            category_summary[cat] = {
                "mean_t_score": mean_t,
                "test_count": len(data["tests"]),
                "tests": data["tests"],
            }

        # 综合 T-score
        composite_t = round(np.mean(test_t_scores), 2) if test_t_scores else 0.0

        return {
            "athlete_id": athlete_id,
            "scores": scores,
            "composite_t_score": composite_t,
            "category_scores": category_summary,
            "test_count": len(scores),
        }

    # ── 趋势分析 ──────────────────────────────────────────────────────────

    def analyze_trends(self, athlete_id, test_id, db_session):
        """
        对运动员在某一测试项目上的历史数据进行线性回归趋势分析

        使用最小二乘法拟合 y = slope * x + intercept，
        并计算 R² 判定系数。

        Args:
            athlete_id: 运动员 ID
            test_id: 测试项目 ID
            db_session: SQLAlchemy 数据库会话

        Returns:
            dict: {
                "athlete_id": int,
                "test_id": int,
                "test_name": str,
                "slope": float,          # 斜率（每单位时间的变化量）
                "intercept": float,      # 截距
                "r_squared": float,      # R² 判定系数 (0–1)
                "direction": str,        # "improving" / "stable" / "declining"
                "data_points": [{date, raw_value, z_score, t_score}, ...],
                "point_count": int,
                "reference": dict,
            }
        """
        # 查询该运动员此项目的所有测试记录，按日期升序
        records = (
            db_session.query(TestRecord)
            .filter_by(athlete_id=athlete_id, test_id=test_id)
            .order_by(TestRecord.test_date.asc())
            .all()
        )

        test = db_session.query(FitnessTest).get(test_id)
        test_name = test.name if test else "未知测试"
        ref = self._get_test_ref(test_name)

        if len(records) < 2:
            # 数据点不足，无法做趋势分析
            data_points = []
            for r in records:
                score = self._compute_single_score(test_name, r.raw_value) if ref else None
                data_points.append({
                    "date": r.test_date.isoformat() if r.test_date else None,
                    "raw_value": r.raw_value,
                    "z_score": score["z_score"] if score else None,
                    "t_score": score["t_score"] if score else None,
                })
            return {
                "athlete_id": athlete_id,
                "test_id": test_id,
                "test_name": test_name,
                "slope": None,
                "intercept": None,
                "r_squared": None,
                "direction": "insufficient_data",
                "data_points": data_points,
                "point_count": len(records),
                "reference": ref,
            }

        # 将日期转换为距今天数（数值型自变量）
        today = date.today()
        x_values = np.array([(today - r.test_date).days for r in records], dtype=float)
        y_values = np.array([r.raw_value for r in records], dtype=float)

        # 线性回归: y = slope * x + intercept
        # 使用 scipy 的 linregress
        result = scipy_stats.linregress(x_values, y_values)
        slope = round(result.slope, 4)
        intercept = round(result.intercept, 4)
        r_squared = round(result.rvalue ** 2, 4)

        # 判断趋势方向
        # 注意：x 是距今天数，所以负的 x 意味着更早的日期
        # slope > 0 表示随时间推移（从过去到现在）数值在增长
        if r_squared < 0.3:
            direction = "stable"  # 相关性太弱，视为稳定
        elif slope > 0.001:
            direction = "improving" if (ref and ref.get("higher_is_better", True)) else "declining"
        elif slope < -0.001:
            direction = "declining" if (ref and ref.get("higher_is_better", True)) else "improving"
        else:
            direction = "stable"

        # 构建数据点列表
        data_points = []
        for r in records:
            score = self._compute_single_score(test_name, r.raw_value) if ref else None
            data_points.append({
                "date": r.test_date.isoformat() if r.test_date else None,
                "raw_value": r.raw_value,
                "z_score": score["z_score"] if score else None,
                "t_score": score["t_score"] if score else None,
            })

        return {
            "athlete_id": athlete_id,
            "test_id": test_id,
            "test_name": test_name,
            "slope": slope,
            "intercept": intercept,
            "r_squared": r_squared,
            "direction": direction,
            "data_points": data_points,
            "point_count": len(records),
            "reference": ref,
        }

    # ── 雷达图数据 ────────────────────────────────────────────────────────

    def radar_data(self, athlete_id, db_session):
        """
        生成 8 大维度的雷达图数据

        将运动员各测试项的 T-score 按维度聚合，
        每个维度取该维度下所有测试 T-score 的均值。

        Args:
            athlete_id: 运动员 ID
            db_session: SQLAlchemy 数据库会话

        Returns:
            dict: {
                "athlete_id": int,
                "categories": [类别名1, 类别名2, ...],   # 8 个维度
                "t_scores": [T-score1, T-score2, ...],    # 对应的平均 T-score
                "details": {类别名: {test_name: t_score, ...}, ...},
            }
        """
        profile = self.athlete_profile(athlete_id, db_session)

        # 将测试按 RADAR_CATEGORIES 映射到 8 大维度
        dimension_t_scores = defaultdict(list)
        dimension_details = defaultdict(dict)

        for entry in profile["scores"]:
            test_name = entry["test_name"]
            t_score = entry["t_score"]
            # 找到该测试属于哪个雷达维度
            assigned = False
            for dim, tests in RADAR_CATEGORIES.items():
                if test_name in tests:
                    dimension_t_scores[dim].append(t_score)
                    dimension_details[dim][test_name] = t_score
                    assigned = True
                    break
            if not assigned:
                # 未匹配到维度的测试归入"其他"
                dimension_t_scores.setdefault("其他", []).append(t_score)
                dimension_details.setdefault("其他", {})[test_name] = t_score

        # 按固定顺序输出 8 大维度
        ordered_dims = list(RADAR_CATEGORIES.keys())
        categories = []
        t_scores = []
        for dim in ordered_dims:
            categories.append(dim)
            vals = dimension_t_scores.get(dim, [])
            t_scores.append(round(np.mean(vals), 2) if vals else 0.0)

        return {
            "athlete_id": athlete_id,
            "categories": categories,
            "t_scores": t_scores,
            "details": dict(dimension_details),
        }

    # ── 参考人群管理 ──────────────────────────────────────────────────────

    def get_all_references(self):
        """获取所有参考人群参数"""
        return dict(self.references)

    def update_reference(self, test_name, params):
        """
        更新某个测试项目的参考人群参数

        Args:
            test_name: 测试项目名称
            params: 包含 mean, std, higher_is_better 的部分或全部字段

        Returns:
            bool: 是否成功更新
        """
        if test_name not in self.references:
            return False
        self.references[test_name].update(params)
        return True

    def add_reference(self, test_name, mean, std, higher_is_better):
        """
        添加新的测试项目参考参数

        Args:
            test_name: 测试名称
            mean: 均值
            std: 标准差
            higher_is_better: 是否越高越好
        """
        self.references[test_name] = {
            "mean": mean,
            "std": std,
            "higher_is_better": higher_is_better,
        }
