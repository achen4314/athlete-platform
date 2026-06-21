"""
运动员数据分析平台 - MediaPipe 姿态识别引擎
运动员数据分析平台

使用 MediaPipe Pose 进行运动员姿态分析，支持：
- 跑步分析（步频、步幅、着地时间）
- 纵跳分析（腾空高度、起跳角度、腾空时间）
- 力量举/深蹲分析（杠铃速度、膝关节角度、髋关节角度、对称性）
- 降采样处理（每2帧取1帧，最大30FPS）
- 标注视频生成（叠加骨架线 + 关节角）
"""
import json
import logging
import math
import os
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# MediaPipe 姿态关键点索引（33点）
POSE_LANDMARKS = {
    0:  "nose",
    1:  "left_eye_inner",
    2:  "left_eye",
    3:  "left_eye_outer",
    4:  "right_eye_inner",
    5:  "right_eye",
    6:  "right_eye_outer",
    7:  "left_ear",
    8:  "right_ear",
    9:  "mouth_left",
    10: "mouth_right",
    11: "left_shoulder",
    12: "right_shoulder",
    13: "left_elbow",
    14: "right_elbow",
    15: "left_wrist",
    16: "right_wrist",
    17: "left_pinky",
    18: "right_pinky",
    19: "left_index",
    20: "right_index",
    21: "left_thumb",
    22: "right_thumb",
    23: "left_hip",
    24: "right_hip",
    25: "left_knee",
    26: "right_knee",
    27: "left_ankle",
    28: "right_ankle",
    29: "left_heel",
    30: "right_heel",
    31: "left_foot_index",
    32: "right_foot_index",
}

# 关键连线（用于绘制骨架）
POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (25, 27), (27, 29), (27, 31),
    (24, 26), (26, 28), (28, 30), (28, 32),
]

# 关节角度计算定义：(顶点, 一端, 另一端, 角度名称)
JOINT_ANGLE_DEFS = [
    ("right_knee", 24, 26, 28),
    ("left_knee", 23, 25, 27),
    ("right_hip", 12, 24, 26),
    ("left_hip", 11, 23, 25),
    ("right_elbow", 14, 12, 16),
    ("left_elbow", 13, 11, 15),
    ("right_shoulder", 12, 24, 14),
    ("left_shoulder", 11, 23, 13),
]

# 骨架绘制颜色（BGR）
SKELETON_COLOR = (160, 192, 64)        # 品牌绿色
JOINT_COLOR = (0, 255, 100)            # 关键点绿色
ANGLE_COLOR = (192, 192, 96)           # 角度标注金色
RIGHT_SIDE_COLOR = (64, 160, 192)      # 右侧蓝色
LEFT_SIDE_COLOR = (192, 64, 160)       # 左侧紫色


class PoseAnalyzer:
    """使用 MediaPipe Pose 进行运动员姿态分析"""

    def __init__(self):
        self.mp_pose = None
        self.mp_drawing = None
        self.pose = None
        self._initialized = False

    def _init_mediapipe(self):
        """延迟导入并初始化 MediaPipe Pose"""
        if self._initialized:
            return True
        try:
            import mediapipe as mp
            self.mp_pose = mp.solutions.pose
            self.mp_drawing = mp.solutions.drawing_utils
            self.pose = self.mp_pose.Pose(
                static_image_mode=False,
                model_complexity=1,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
                enable_segmentation=False,
            )
            self._initialized = True
            logger.info("MediaPipe Pose 初始化成功")
            return True
        except ImportError:
            logger.warning("MediaPipe 未安装，将使用模拟分析结果")
            return False
        except Exception as e:
            logger.error("MediaPipe 初始化失败: %s", e)
            return False

    def analyze_video(self, video_path: str, test_type: Optional[str] = None,
                      generate_annotated: bool = False) -> dict:
        """
        分析视频，返回关键指标

        Args:
            video_path: 视频文件路径
            test_type: 测试类型（sprint/jump/squat/general），None 则自动检测
            generate_annotated: 是否生成标注视频

        Returns:
            {
                'status': 'done' | 'error',
                'video_path': str,
                'duration_seconds': float,
                'total_frames': int,
                'fps': float,
                'metrics': {...},
                'keyframe_data': [...],
                'annotated_video_path': str | None,
                'error': str,
            }
        """
        # 尝试初始化 MediaPipe
        mp_available = self._init_mediapipe()

        if not mp_available:
            return self._mock_analysis(video_path, test_type)

        # 打开视频
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {
                'status': 'error',
                'video_path': video_path,
                'error': '无法打开视频文件',
            }

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # 降采样策略：每2帧取1帧，目标FPS不超过30
        target_fps = min(fps, 30.0)
        frame_step = max(1, int(fps / target_fps))
        # 额外每2帧取1帧
        frame_step = max(2, frame_step * 2)
        effective_fps = fps / frame_step

        logger.info("视频信息: %dx%d, %.1fFPS, %d帧, 采样步长=%d, 有效FPS=%.1f",
                     width, height, fps, total_frames, frame_step, effective_fps)

        # 收集所有帧的姿态数据
        landmarks_sequence = []
        keyframe_data = []
        frame_idx = 0
        processed_frames = 0

        # 标注视频写入器（如果需要）
        annotated_writer = None
        annotated_video_path = None
        if generate_annotated:
            annotated_video_path = video_path.rsplit('.', 1)[0] + '_annotated.mp4'
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            annotated_writer = cv2.VideoWriter(
                annotated_video_path, fourcc, effective_fps, (width, height))
            logger.info("标注视频输出: %s", annotated_video_path)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_idx += 1
            if frame_idx % frame_step != 0:
                continue

            processed_frames += 1

            # 转换颜色空间 BGR → RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.pose.process(rgb_frame)

            if results.pose_landmarks:
                # 提取33个关键点
                landmarks = []
                for lm in results.pose_landmarks.landmark:
                    landmarks.append({
                        'x': round(lm.x, 4),
                        'y': round(lm.y, 4),
                        'z': round(lm.z, 4),
                        'visibility': round(lm.visibility, 4),
                    })
                
                time_sec = round(frame_idx / fps, 2)
                landmarks_sequence.append({
                    'frame': frame_idx,
                    'time_sec': time_sec,
                    'landmarks': landmarks,
                })

                # 保存关键帧用于展示（均匀选取最多30帧）
                keyframe_interval = max(1, total_frames // 30)
                if len(keyframe_data) < 30 and frame_idx % keyframe_interval == 0:
                    keyframe_data.append({
                        'frame': frame_idx,
                        'time_sec': time_sec,
                        'landmarks': landmarks,
                    })

                # 绘制标注视频
                if annotated_writer is not None:
                    annotated_frame = self._draw_annotated_frame(frame, landmarks)
                    annotated_writer.write(annotated_frame)
            elif annotated_writer is not None:
                # 没有检测到姿态，写入原帧
                annotated_writer.write(frame)

        cap.release()
        if annotated_writer is not None:
            annotated_writer.release()

        logger.info("视频分析完成: %d帧 → %d个有效姿态 (采样%d帧)",
                     frame_idx, len(landmarks_sequence), processed_frames)

        # 根据测试类型计算指标
        if test_type is None:
            test_type = self._detect_test_type(landmarks_sequence, effective_fps)

        metrics = {}
        if test_type == 'sprint':
            metrics = self._analyze_sprint(landmarks_sequence, effective_fps, duration)
        elif test_type == 'jump':
            metrics = self._analyze_jump(landmarks_sequence, effective_fps)
        elif test_type == 'squat':
            metrics = self._analyze_squat(landmarks_sequence, effective_fps)
        else:
            metrics = self._analyze_general(landmarks_sequence, effective_fps)

        result = {
            'status': 'done',
            'video_path': video_path,
            'duration_seconds': round(duration, 2),
            'total_frames': frame_idx,
            'fps': round(fps, 2),
            'effective_fps': round(effective_fps, 1),
            'sample_frames': len(landmarks_sequence),
            'test_type': test_type,
            'metrics': metrics,
            'keyframe_data': keyframe_data,
        }

        if generate_annotated and annotated_video_path:
            result['annotated_video_path'] = annotated_video_path

        return result

    def _draw_annotated_frame(self, frame, landmarks: list) -> np.ndarray:
        """
        在帧上绘制骨架线、关键点和关节角度

        Args:
            frame: OpenCV BGR 图像
            landmarks: [{x, y, z, visibility}, ...]

        Returns:
            带标注的帧
        """
        h, w = frame.shape[:2]
        annotated = frame.copy()

        # 绘制连线 - 按左右侧分色
        for conn in POSE_CONNECTIONS:
            idx1, idx2 = conn
            if idx1 < len(landmarks) and idx2 < len(landmarks):
                lm1 = landmarks[idx1]
                lm2 = landmarks[idx2]
                if lm1.get('visibility', 0) > 0.5 and lm2.get('visibility', 0) > 0.5:
                    pt1 = (int(lm1['x'] * w), int(lm1['y'] * h))
                    pt2 = (int(lm2['x'] * w), int(lm2['y'] * h))
                    # 判断左右侧（左=奇数索引的肩/髋/膝/踝）
                    color = LEFT_SIDE_COLOR if (idx1 in (11, 13, 15, 23, 25, 27, 29, 31) or
                                                 idx2 in (11, 13, 15, 23, 25, 27, 29, 31)) \
                        else RIGHT_SIDE_COLOR if (idx1 in (12, 14, 16, 24, 26, 28, 30, 32) or
                                                   idx2 in (12, 14, 16, 24, 26, 28, 30, 32)) \
                        else SKELETON_COLOR
                    cv2.line(annotated, pt1, pt2, color, 2)

        # 绘制关键点
        for i, lm in enumerate(landmarks):
            if lm.get('visibility', 0) > 0.5:
                cx, cy = int(lm['x'] * w), int(lm['y'] * h)
                # 大关节用大点
                if i in (11, 12, 23, 24, 25, 26, 27, 28):
                    cv2.circle(annotated, (cx, cy), 6, JOINT_COLOR, -1)
                else:
                    cv2.circle(annotated, (cx, cy), 3, JOINT_COLOR, -1)

        # 绘制关节角度标注
        for name, vertex_idx, p1_idx, p2_idx in JOINT_ANGLE_DEFS:
            if all(idx < len(landmarks) for idx in (vertex_idx, p1_idx, p2_idx)):
                v = landmarks[vertex_idx]
                p1 = landmarks[p1_idx]
                p2 = landmarks[p2_idx]
                if all(lm.get('visibility', 0) > 0.5 for lm in (v, p1, p2)):
                    angle = self._calc_angle(
                        [p1['x'], p1['y']],
                        [v['x'], v['y']],
                        [p2['x'], p2['y']]
                    )
                    vx, vy = int(v['x'] * w), int(v['y'] * h)
                    cv2.putText(annotated, f"{angle:.0f}°",
                                (vx + 10, vy - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, ANGLE_COLOR, 1)

        # 绘制帧信息和时间戳
        cv2.putText(annotated, "运动员平台 · 姿态分析",
                    (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (160, 192, 64), 1)

        return annotated

    def _detect_test_type(self, landmarks_sequence: list, fps: float) -> str:
        """根据视频内容自动判断测试类型"""
        if not landmarks_sequence:
            return 'general'

        # 检查下半身关键点的垂直运动范围
        hip_y_vals = []
        ankle_y_vals = []
        for frame_data in landmarks_sequence:
            lms = frame_data['landmarks']
            # 髋关节 (23=left_hip, 24=right_hip)
            for idx in [23, 24]:
                if idx < len(lms) and lms[idx].get('visibility', 0) > 0.5:
                    hip_y_vals.append(lms[idx]['y'])
            # 踝关节 (27=left_ankle, 28=right_ankle)
            for idx in [27, 28]:
                if idx < len(lms) and lms[idx].get('visibility', 0) > 0.5:
                    ankle_y_vals.append(lms[idx]['y'])

        if hip_y_vals and ankle_y_vals:
            hip_range = max(hip_y_vals) - min(hip_y_vals)
            ankle_range = max(ankle_y_vals) - min(ankle_y_vals)

            # 垂直移动大 → 深蹲或跳跃
            if hip_range > 0.12:
                # 踝关节也有大范围移动 → 跳跃
                if ankle_range > 0.08:
                    return 'jump'
                return 'squat'

            # 水平移动检测 → 跑步
            ankle_x_vals = []
            for frame_data in landmarks_sequence:
                lms = frame_data['landmarks']
                for idx in [27, 28]:
                    if idx < len(lms) and lms[idx].get('visibility', 0) > 0.5:
                        ankle_x_vals.append(lms[idx]['x'])
            if ankle_x_vals and (max(ankle_x_vals) - min(ankle_x_vals)) > 0.1:
                return 'sprint'

        return 'general'

    def _calc_angle(self, a: list, b: list, c: list) -> float:
        """计算三点角度（b 为顶点），返回角度（度）"""
        ba = np.array([a[0] - b[0], a[1] - b[1]])
        bc = np.array([c[0] - b[0], c[1] - b[1]])
        cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
        cosine = np.clip(cosine, -1.0, 1.0)
        return round(math.degrees(math.acos(cosine)), 1)

    def _calc_distance(self, a: dict, b: dict) -> float:
        """计算两个关键点之间的归一化距离"""
        return math.sqrt((a['x'] - b['x'])**2 + (a['y'] - b['y'])**2)

    # ═══════════════════════════════════════════════════════════════════════
    # 跑步分析（步频、步幅、着地时间）
    # ═══════════════════════════════════════════════════════════════════════

    def _analyze_sprint(self, landmarks_sequence: list, fps: float, duration: float) -> dict:
        """跑步分析：步频、步幅、着地时间、身体前倾角"""
        if not landmarks_sequence:
            return {'type': 'sprint', 'error': '未检测到有效姿态'}

        # 提取左右踝关节位置随时间变化
        ankle_data = []
        for fd in landmarks_sequence:
            lms = fd['landmarks']
            if len(lms) > 32:
                ankle_data.append({
                    'time': fd['time_sec'],
                    'frame': fd['frame'],
                    'left_x': lms[27]['x'],
                    'left_y': lms[27]['y'],
                    'right_x': lms[28]['x'],
                    'right_y': lms[28]['y'],
                })

        # 使用踝关节垂直位置检测步态周期
        # 着地→离地→着地 = 一个步态周期
        step_cycles = []
        if len(ankle_data) > 5:
            # 使用右踝 y 坐标检测峰值（着地 = y 最小，即脚尖位置最低）
            right_y = [d['right_y'] for d in ankle_data]
            # 找局部最大值（着地点）
            for i in range(2, len(right_y) - 2):
                if right_y[i] > right_y[i-1] and right_y[i] > right_y[i-2] and \
                   right_y[i] >= right_y[i+1] and right_y[i] >= right_y[i+2]:
                    step_cycles.append(i)

        estimated_step_count = len(step_cycles) if step_cycles else len(ankle_data) // 3
        step_count = max(estimated_step_count, 1)

        # 步频 = 步数 / 时间
        step_frequency = round(step_count / duration, 1) if duration > 0 else 0

        # 估算步幅（基于踝关节水平移动范围）
        stride_length_cm = 0
        if ankle_data and len(ankle_data) > 2:
            # 用髋关节宽度作为参考尺度估算步幅
            hip_widths = []
            for fd in landmarks_sequence:
                lms = fd['landmarks']
                if len(lms) > 24:
                    hip_width = self._calc_distance(lms[23], lms[24])
                    hip_widths.append(hip_width)
            avg_hip_width = sum(hip_widths) / len(hip_widths) if hip_widths else 0.05

            # 估算：步幅 ≈ 髋宽 × 系数（通常3-5倍）
            if avg_hip_width > 0:
                # 用踝关节水平位移估算
                ankle_x_range = max(d['right_x'] for d in ankle_data) - \
                                min(d['right_x'] for d in ankle_data)
                # 标准化：归一化位移 × 假设身高对应的实际距离
                stride_length_cm = round(ankle_x_range * 180, 1)  # 假设身高180cm

        # 着地时间估算（基于步频）
        ground_contact_time_ms = round(1000 / step_frequency * 0.4, 0) if step_frequency > 0 else 0

        # 身体前倾角（肩-髋连线与垂直线的夹角）
        lean_angles = []
        for fd in landmarks_sequence:
            lms = fd['landmarks']
            if len(lms) > 24:
                # 使用肩部中点 (11,12) 和髋部中点 (23,24)
                shoulder_mid_x = (lms[11]['x'] + lms[12]['x']) / 2
                shoulder_mid_y = (lms[11]['y'] + lms[12]['y']) / 2
                hip_mid_x = (lms[23]['x'] + lms[24]['x']) / 2
                hip_mid_y = (lms[23]['y'] + lms[24]['y']) / 2
                # 前倾角 = atan2(dx, dy) 转为度
                dx = shoulder_mid_x - hip_mid_x
                dy = hip_mid_y - shoulder_mid_y
                lean_angle = math.degrees(math.atan2(dx, dy))
                lean_angles.append(round(lean_angle, 1))

        avg_lean_angle = round(sum(lean_angles) / len(lean_angles), 1) if lean_angles else 0

        return {
            'type': 'sprint',
            'step_count': step_count,
            'step_frequency_hz': step_frequency,      # 步频（Hz = 步/秒）
            'step_frequency_per_min': round(step_frequency * 60, 0),  # 步频（步/分钟）
            'stride_length_cm': stride_length_cm,     # 步幅估计（cm）
            'ground_contact_time_ms': ground_contact_time_ms,  # 着地时间（ms）
            'forward_lean_angle_deg': avg_lean_angle,  # 身体前倾角（度）
            'duration_sec': round(duration, 2),
            'data_points': len(ankle_data),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # 纵跳分析（腾空高度、起跳角度、腾空时间）
    # ═══════════════════════════════════════════════════════════════════════

    def _analyze_jump(self, landmarks_sequence: list, fps: float) -> dict:
        """纵跳分析：腾空高度、起跳角度、腾空时间、起跳速度"""
        if not landmarks_sequence:
            return {'type': 'jump', 'error': '未检测到有效姿态'}

        # 提取髋关节和踝关节的垂直位置
        hip_y_values = []
        ankle_y_values = []
        for fd in landmarks_sequence:
            lms = fd['landmarks']
            if len(lms) > 28:
                avg_hip_y = (lms[23]['y'] + lms[24]['y']) / 2
                avg_ankle_y = (lms[27]['y'] + lms[28]['y']) / 2
                hip_y_values.append(avg_hip_y)
                ankle_y_values.append(avg_ankle_y)

        result = {'type': 'jump'}

        if hip_y_values:
            y_min = min(hip_y_values)  # 最高点（y 值最小）
            y_max = max(hip_y_values)  # 最低点（准备起跳）
            vertical_range = y_max - y_min

            # 腾空帧检测：髋关节高于阈值 N% 视为腾空
            threshold = y_min + vertical_range * 0.25
            airborne_frames = sum(1 for y in hip_y_values if y < threshold)
            airborne_time = airborne_frames / fps if fps > 0 else 0

            # 跳跃高度（基于腾空时间：h = g * t² / 8）
            g = 9.81
            estimated_height_cm = round(g * airborne_time**2 / 8 * 100, 1)

            # 起跳速度 v = g * t / 2
            takeoff_velocity_ms = round(g * airborne_time / 2, 2)

            # 起跳角度（髋-膝-踝连线与水平面的夹角，在起跳瞬间）
            takeoff_angle_deg = 0
            if len(landmarks_sequence) > 5:
                # 找到髋关节最低的帧（起跳瞬间）
                min_idx = hip_y_values.index(min(hip_y_values))
                if min_idx < len(landmarks_sequence):
                    lms = landmarks_sequence[min_idx]['landmarks']
                    if len(lms) > 28:
                        hip_x = (lms[23]['x'] + lms[24]['x']) / 2
                        hip_y = (lms[23]['y'] + lms[24]['y']) / 2
                        ankle_x = (lms[27]['x'] + lms[28]['x']) / 2
                        ankle_y = (lms[27]['y'] + lms[28]['y']) / 2
                        dx = ankle_x - hip_x
                        dy = ankle_y - hip_y
                        takeoff_angle_deg = round(math.degrees(math.atan2(-dy, dx)), 1)

            result.update({
                'hip_vertical_range': round(vertical_range, 4),
                'airborne_time_sec': round(airborne_time, 2),
                'airborne_frames': airborne_frames,
                'estimated_jump_height_cm': estimated_height_cm,
                'takeoff_velocity_ms': takeoff_velocity_ms,
                'takeoff_angle_deg': takeoff_angle_deg,
                'note': '跳跃高度为基于腾空时间的估算值（h = g·t²/8）',
            })

        return result

    # ═══════════════════════════════════════════════════════════════════════
    # 力量举/深蹲分析（关节角度、对称性、杠铃速度）
    # ═══════════════════════════════════════════════════════════════════════

    def _analyze_squat(self, landmarks_sequence: list, fps: float) -> dict:
        """深蹲/力量举分析：膝关节角度、髋关节角度、对称性、杠铃速度估算"""
        if not landmarks_sequence:
            return {'type': 'squat', 'error': '未检测到有效姿态'}

        right_knee_angles = []
        left_knee_angles = []
        right_hip_angles = []
        left_hip_angles = []
        # 杠铃位置追踪（用肩部中点近似）
        bar_y_positions = []

        for fd in landmarks_sequence:
            lms = fd['landmarks']
            if len(lms) < 29:
                continue

            # 右膝角度：hip(24) - knee(26) - ankle(28)
            try:
                right_knee = self._calc_angle(
                    [lms[24]['x'], lms[24]['y']],
                    [lms[26]['x'], lms[26]['y']],
                    [lms[28]['x'], lms[28]['y']],
                )
                right_knee_angles.append(right_knee)
            except (IndexError, KeyError):
                pass

            # 左膝角度：hip(23) - knee(25) - ankle(27)
            try:
                left_knee = self._calc_angle(
                    [lms[23]['x'], lms[23]['y']],
                    [lms[25]['x'], lms[25]['y']],
                    [lms[27]['x'], lms[27]['y']],
                )
                left_knee_angles.append(left_knee)
            except (IndexError, KeyError):
                pass

            # 右髋角度：shoulder(12) - hip(24) - knee(26)
            try:
                right_hip = self._calc_angle(
                    [lms[12]['x'], lms[12]['y']],
                    [lms[24]['x'], lms[24]['y']],
                    [lms[26]['x'], lms[26]['y']],
                )
                right_hip_angles.append(right_hip)
            except (IndexError, KeyError):
                pass

            # 左髋角度：shoulder(11) - hip(23) - knee(25)
            try:
                left_hip = self._calc_angle(
                    [lms[11]['x'], lms[11]['y']],
                    [lms[23]['x'], lms[23]['y']],
                    [lms[25]['x'], lms[25]['y']],
                )
                left_hip_angles.append(left_hip)
            except (IndexError, KeyError):
                pass

            # 杠铃位置（肩部中点 y 坐标近似）
            try:
                bar_y = (lms[11]['y'] + lms[12]['y']) / 2
                bar_y_positions.append({'time': fd['time_sec'], 'y': bar_y})
            except (IndexError, KeyError):
                pass

        result = {'type': 'squat'}

        # 膝关节角度统计
        if right_knee_angles:
            result['knee_angle_right_min'] = round(min(right_knee_angles), 1)
            result['knee_angle_right_max'] = round(max(right_knee_angles), 1)
            result['knee_angle_right_avg'] = round(sum(right_knee_angles) / len(right_knee_angles), 1)
        if left_knee_angles:
            result['knee_angle_left_min'] = round(min(left_knee_angles), 1)
            result['knee_angle_left_max'] = round(max(left_knee_angles), 1)
            result['knee_angle_left_avg'] = round(sum(left_knee_angles) / len(left_knee_angles), 1)

        # 双侧综合
        all_knee = right_knee_angles + left_knee_angles
        if all_knee:
            result['knee_angle_min'] = round(min(all_knee), 1)
            result['knee_angle_max'] = round(max(all_knee), 1)
            result['knee_angle_avg'] = round(sum(all_knee) / len(all_knee), 1)

        # 髋关节角度统计
        if right_hip_angles:
            result['hip_angle_right_min'] = round(min(right_hip_angles), 1)
            result['hip_angle_right_max'] = round(max(right_hip_angles), 1)
        if left_hip_angles:
            result['hip_angle_left_min'] = round(min(left_hip_angles), 1)
            result['hip_angle_left_max'] = round(max(left_hip_angles), 1)

        all_hip = right_hip_angles + left_hip_angles
        if all_hip:
            result['hip_angle_min'] = round(min(all_hip), 1)
            result['hip_angle_max'] = round(max(all_hip), 1)
            result['hip_angle_avg'] = round(sum(all_hip) / len(all_hip), 1)

        # 左右对称性评估
        if right_knee_angles and left_knee_angles:
            avg_right = sum(right_knee_angles) / len(right_knee_angles)
            avg_left = sum(left_knee_angles) / len(left_knee_angles)
            asymmetry = abs(avg_right - avg_left)
            result['knee_asymmetry_deg'] = round(asymmetry, 1)
            if asymmetry < 3:
                result['symmetry_rating'] = '优秀（对称）'
            elif asymmetry < 8:
                result['symmetry_rating'] = '良好（轻微不对称）'
            elif asymmetry < 15:
                result['symmetry_rating'] = '需关注（明显不对称）'
            else:
                result['symmetry_rating'] = '风险（严重不对称）'

        # 深蹲深度评估
        all_knee_min = min(all_knee) if all_knee else 180
        if all_knee_min < 70:
            result['squat_depth'] = '极深蹲 (ATG)'
            result['squat_depth_rating'] = '优秀'
        elif all_knee_min < 90:
            result['squat_depth'] = '全蹲 (低于平行)'
            result['squat_depth_rating'] = '优秀'
        elif all_knee_min < 110:
            result['squat_depth'] = '平行蹲'
            result['squat_depth_rating'] = '良好'
        elif all_knee_min < 130:
            result['squat_depth'] = '半蹲'
            result['squat_depth_rating'] = '一般'
        else:
            result['squat_depth'] = '浅蹲'
            result['squat_depth_rating'] = '需改进'

        # 杠铃速度估算（基于肩部 y 坐标变化率）
        if bar_y_positions and len(bar_y_positions) > 1:
            velocities = []
            for i in range(1, len(bar_y_positions)):
                dt = bar_y_positions[i]['time'] - bar_y_positions[i-1]['time']
                dy = bar_y_positions[i-1]['y'] - bar_y_positions[i]['y']  # y越小越高
                if dt > 0:
                    # 归一化速度 → 估算实际速度（假设身高对应 h 像素）
                    v_normalized = dy / dt
                    # 假设身高180cm映射到约0.8的归一化范围 → 180/0.8 = 225 cm/单位
                    v_cms = v_normalized * 225
                    velocities.append(round(v_cms, 1))

            if velocities:
                result['bar_velocity_max_cm_s'] = round(max(abs(v) for v in velocities), 1)
                result['bar_velocity_avg_cm_s'] = round(
                    sum(abs(v) for v in velocities) / len(velocities), 1)
                result['bar_velocity_peak_cm_s'] = round(
                    max(velocities, key=abs), 1)

        result['frames_analyzed'] = len(all_knee) if all_knee else 0
        return result

    # ═══════════════════════════════════════════════════════════════════════
    # 通用分析
    # ═══════════════════════════════════════════════════════════════════════

    def _analyze_general(self, landmarks_sequence: list, fps: float) -> dict:
        """通用姿态分析"""
        if not landmarks_sequence:
            return {'type': 'general', 'error': '未检测到有效姿态'}

        # 提取基本统计信息
        frame_count = len(landmarks_sequence)

        # 计算平均可见度
        avg_visibility = 0
        if landmarks_sequence:
            vis_sum = 0
            vis_count = 0
            for fd in landmarks_sequence[:min(10, len(landmarks_sequence))]:
                for lm in fd['landmarks']:
                    vis_sum += lm.get('visibility', 0)
                    vis_count += 1
            avg_visibility = round(vis_sum / max(vis_count, 1) * 100, 1)

        quality = '优秀' if avg_visibility > 90 else \
                  '良好' if avg_visibility > 75 else \
                  '一般' if avg_visibility > 50 else '较差'

        return {
            'type': 'general',
            'frames_analyzed': frame_count,
            'avg_landmark_visibility_pct': avg_visibility,
            'detection_quality': quality,
            'note': '通用姿态分析。如需专项指标（步频/跳跃高度/深蹲角度），请在视频列表中指定测试类型后重新分析。',
        }

    # ═══════════════════════════════════════════════════════════════════════
    # 模拟分析（MediaPipe 不可用时）
    # ═══════════════════════════════════════════════════════════════════════

    def _mock_analysis(self, video_path: str, test_type: Optional[str] = None) -> dict:
        """
        模拟分析结果（MediaPipe 不可用时使用）
        生成合理的假数据用于测试界面展示
        """
        logger.info("生成模拟分析数据: %s (type=%s)", video_path, test_type)

        test_type = test_type or 'squat'

        mock_metrics = {
            'sprint': {
                'type': 'sprint',
                'step_count': 42,
                'step_frequency_hz': 3.5,
                'step_frequency_per_min': 210,
                'stride_length_cm': 175.5,
                'ground_contact_time_ms': 114,
                'forward_lean_angle_deg': 8.5,
                'duration_sec': 12.0,
                'data_points': 120,
                'note': '[模拟数据] MediaPipe 未安装，此为测试示例数据',
            },
            'jump': {
                'type': 'jump',
                'hip_vertical_range': 0.085,
                'airborne_time_sec': 0.52,
                'airborne_frames': 16,
                'estimated_jump_height_cm': 33.1,
                'takeoff_velocity_ms': 2.55,
                'takeoff_angle_deg': 72.5,
                'note': '[模拟数据] MediaPipe 未安装，此为测试示例数据',
            },
            'squat': {
                'type': 'squat',
                'knee_angle_right_min': 78.5,
                'knee_angle_right_max': 175.3,
                'knee_angle_left_min': 82.1,
                'knee_angle_left_max': 173.8,
                'knee_angle_min': 78.5,
                'knee_angle_max': 175.3,
                'knee_angle_avg': 128.7,
                'hip_angle_right_min': 62.3,
                'hip_angle_right_max': 168.9,
                'hip_angle_left_min': 65.1,
                'hip_angle_left_max': 167.2,
                'hip_angle_min': 62.3,
                'hip_angle_max': 168.9,
                'hip_angle_avg': 115.4,
                'knee_asymmetry_deg': 3.6,
                'symmetry_rating': '良好（轻微不对称）',
                'squat_depth': '全蹲 (低于平行)',
                'squat_depth_rating': '优秀',
                'bar_velocity_max_cm_s': 85.2,
                'bar_velocity_avg_cm_s': 52.3,
                'bar_velocity_peak_cm_s': 85.2,
                'frames_analyzed': 150,
                'note': '[模拟数据] MediaPipe 未安装，此为测试示例数据',
            },
            'general': {
                'type': 'general',
                'frames_analyzed': 200,
                'avg_landmark_visibility_pct': 85.3,
                'detection_quality': '良好',
                'note': '[模拟数据] MediaPipe 未安装，此为测试示例数据',
            },
        }

        # 生成模拟关键帧数据
        mock_keyframes = []
        for i in range(10):
            mock_keyframes.append({
                'frame': i * 15,
                'time_sec': round(i * 15 / 30.0, 2),
                'landmarks': [],
            })

        return {
            'status': 'done',
            'video_path': video_path,
            'duration_seconds': 5.0,
            'total_frames': 150,
            'fps': 30.0,
            'effective_fps': 15.0,
            'sample_frames': 75,
            'test_type': test_type,
            'metrics': mock_metrics.get(test_type, mock_metrics['general']),
            'keyframe_data': mock_keyframes,
            'is_mock': True,
        }

    def draw_pose_landmarks(self, frame, landmarks_data: list) -> np.ndarray:
        """
        在帧上绘制姿态关键点连线

        Args:
            frame: OpenCV BGR 图像 (numpy array)
            landmarks_data: [{x, y, z, visibility}, ...]

        Returns:
            带标注的帧
        """
        return self._draw_annotated_frame(frame, landmarks_data)
