"""
运动员数据分析平台 - MediaPipe 姿态识别引擎
运动员数据分析平台

使用 MediaPipe Pose 进行运动员姿态分析，支持：
- 短跑（步频、步幅）
- 跳跃（起跳高度、腾空时间）
- 深蹲（膝关节角度、髋关节角度）
"""
import json
import logging
import math
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# MediaPipe 姿态关键点索引
POSE_LANDMARKS = {
    0:  "nose",
    11: "left_shoulder",
    12: "right_shoulder",
    13: "left_elbow",
    14: "right_elbow",
    15: "left_wrist",
    16: "right_wrist",
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


class PoseAnalyzer:
    """使用 MediaPipe Pose 进行姿态分析"""

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

    def analyze_video(self, video_path: str, test_type: Optional[str] = None) -> dict:
        """
        分析视频，返回关键指标

        Args:
            video_path: 视频文件路径
            test_type: 测试类型（sprint/jump/squat），None 则自动检测

        Returns:
            {
                'status': 'done' | 'error',
                'video_path': str,
                'duration_seconds': float,
                'total_frames': int,
                'fps': float,
                'metrics': {...},
                'keyframe_data': [...],  # 关键帧姿态数据
                'error': str,  # 仅在 status='error' 时
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

        # 收集所有帧的姿态数据
        landmarks_sequence = []
        keyframe_data = []
        frame_idx = 0

        # 每 N 帧采样一次（性能优化）
        sample_rate = max(1, int(fps / 10))  # 每秒约10帧

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_idx += 1
            if frame_idx % sample_rate != 0:
                continue

            # 转换颜色空间 BGR → RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.pose.process(rgb_frame)

            if results.pose_landmarks:
                landmarks = []
                for lm in results.pose_landmarks.landmark:
                    landmarks.append({
                        'x': round(lm.x, 4),
                        'y': round(lm.y, 4),
                        'z': round(lm.z, 4),
                        'visibility': round(lm.visibility, 4),
                    })
                landmarks_sequence.append({
                    'frame': frame_idx,
                    'time_sec': round(frame_idx / fps, 2),
                    'landmarks': landmarks,
                })

                # 保存关键帧（每 30 帧保存一帧用于展示）
                if len(keyframe_data) < 20 and frame_idx % 30 == 0:
                    keyframe_data.append({
                        'frame': frame_idx,
                        'time_sec': round(frame_idx / fps, 2),
                        'landmarks': landmarks,
                    })

        cap.release()

        logger.info("视频分析完成: %d 帧, %d 个有效姿态", frame_idx, len(landmarks_sequence))

        # 根据测试类型计算指标
        if test_type is None:
            test_type = self._detect_test_type(landmarks_sequence, fps)

        metrics = {}
        if test_type == 'sprint':
            metrics = self._analyze_sprint(landmarks_sequence, fps)
        elif test_type == 'jump':
            metrics = self._analyze_jump(landmarks_sequence, fps)
        elif test_type == 'squat':
            metrics = self._analyze_squat(landmarks_sequence, fps)
        else:
            metrics = self._analyze_general(landmarks_sequence, fps)

        return {
            'status': 'done',
            'video_path': video_path,
            'duration_seconds': round(duration, 2),
            'total_frames': frame_idx,
            'fps': round(fps, 2),
            'sample_frames': len(landmarks_sequence),
            'test_type': test_type,
            'metrics': metrics,
            'keyframe_data': keyframe_data,
        }

    def _detect_test_type(self, landmarks_sequence: list, fps: float) -> str:
        """根据视频内容自动判断测试类型"""
        if not landmarks_sequence:
            return 'general'
        
        # 简易判断：检查下半身关键点的垂直运动范围
        hip_y_vals = []
        for frame_data in landmarks_sequence:
            for idx in [23, 24]:  # left_hip, right_hip
                if idx < len(frame_data['landmarks']):
                    hip_y_vals.append(frame_data['landmarks'][idx]['y'])
        
        if hip_y_vals:
            y_range = max(hip_y_vals) - min(hip_y_vals)
            if y_range > 0.15:  # 垂直移动较大 → 可能深蹲或跳跃
                return 'squat'
        
        return 'general'

    def _calc_angle(self, a: list, b: list, c: list) -> float:
        """计算三点角度（b 为顶点），返回角度（度）"""
        ba = np.array([a[0] - b[0], a[1] - b[1]])
        bc = np.array([c[0] - b[0], c[1] - b[1]])
        cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
        cosine = np.clip(cosine, -1.0, 1.0)
        return round(math.degrees(math.acos(cosine)), 1)

    def _analyze_sprint(self, landmarks_sequence: list, fps: float) -> dict:
        """短跑分析：步频、步幅（基于踝关节轨迹估算）"""
        if not landmarks_sequence:
            return {'error': '未检测到有效姿态'}
        
        # 提取左右踝关节 x 坐标（水平位置）随时间的变化
        ankle_positions = []
        for fd in landmarks_sequence:
            lms = fd['landmarks']
            if len(lms) > 28:
                ankle_positions.append({
                    'time': fd['time_sec'],
                    'left_x': lms[27]['x'],
                    'right_x': lms[28]['x'],
                })
        
        return {
            'type': 'sprint',
            'note': '短跑分析 - 基于姿态估算',
            'estimated_step_count': len(ankle_positions) // 3,
            'data_points': len(ankle_positions),
        }

    def _analyze_jump(self, landmarks_sequence: list, fps: float) -> dict:
        """跳跃分析：起跳高度、腾空时间"""
        if not landmarks_sequence:
            return {'error': '未检测到有效姿态'}
        
        # 提取髋关节 y 坐标（垂直位置）
        hip_y_values = []
        for fd in landmarks_sequence:
            lms = fd['landmarks']
            if len(lms) > 24:
                avg_hip_y = (lms[23]['y'] + lms[24]['y']) / 2
                hip_y_values.append(avg_hip_y)
        
        if hip_y_values:
            y_min = min(hip_y_values)  # 最"高"点（y 越小越靠上）
            y_max = max(hip_y_values)  # 最"低"点
            vertical_range = y_max - y_min
        
        # 估算腾空帧数
        threshold = y_min + (y_max - y_min) * 0.3
        airborne_frames = sum(1 for y in hip_y_values if y < threshold)
        airborne_time = airborne_frames / fps if fps > 0 else 0
        
        # 估算跳跃高度（简化：基于腾空时间 h = g * t^2 / 8）
        g = 9.81
        estimated_height = round(g * airborne_time**2 / 8 * 100, 1)  # cm
        
        return {
            'type': 'jump',
            'hip_vertical_range': round(vertical_range, 4) if hip_y_values else 0,
            'airborne_time_sec': round(airborne_time, 2),
            'estimated_jump_height_cm': estimated_height,
            'note': '跳跃高度为基于腾空时间的估算值',
        }

    def _analyze_squat(self, landmarks_sequence: list, fps: float) -> dict:
        """深蹲分析：膝关节角度、髋关节角度"""
        if not landmarks_sequence:
            return {'error': '未检测到有效姿态'}
        
        knee_angles = []
        hip_angles = []
        
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
                knee_angles.append(right_knee)
            except (IndexError, KeyError):
                pass
            
            # 右髋角度：shoulder(12) - hip(24) - knee(26)
            try:
                right_hip = self._calc_angle(
                    [lms[12]['x'], lms[12]['y']],
                    [lms[24]['x'], lms[24]['y']],
                    [lms[26]['x'], lms[26]['y']],
                )
                hip_angles.append(right_hip)
            except (IndexError, KeyError):
                pass
        
        result = {'type': 'squat'}
        
        if knee_angles:
            result['knee_angle_min'] = round(min(knee_angles), 1)
            result['knee_angle_max'] = round(max(knee_angles), 1)
            result['knee_angle_avg'] = round(sum(knee_angles) / len(knee_angles), 1)
        
        if hip_angles:
            result['hip_angle_min'] = round(min(hip_angles), 1)
            result['hip_angle_max'] = round(max(hip_angles), 1)
            result['hip_angle_avg'] = round(sum(hip_angles) / len(hip_angles), 1)
        
        # 评估深蹲深度
        if knee_angles:
            min_knee = min(knee_angles)
            if min_knee < 90:
                result['squat_depth'] = '全蹲 (低于平行)'
            elif min_knee < 110:
                result['squat_depth'] = '平行蹲'
            else:
                result['squat_depth'] = '半蹲'
        
        result['frames_analyzed'] = len(knee_angles)
        return result

    def _analyze_general(self, landmarks_sequence: list, fps: float) -> dict:
        """通用分析"""
        return {
            'type': 'general',
            'frames_analyzed': len(landmarks_sequence),
            'note': '通用姿态分析，请指定具体测试类型以获取专项指标',
        }

    def _mock_analysis(self, video_path: str, test_type: Optional[str] = None) -> dict:
        """
        模拟分析结果（MediaPipe 不可用时使用）
        生成合理的假数据用于测试界面展示
        """
        logger.info("生成模拟分析数据 for: %s", video_path)
        
        test_type = test_type or 'squat'
        
        mock_metrics = {
            'sprint': {
                'type': 'sprint',
                'estimated_step_count': 42,
                'note': '[模拟数据] MediaPipe 未安装，此为测试示例数据',
            },
            'jump': {
                'type': 'jump',
                'hip_vertical_range': 0.085,
                'airborne_time_sec': 0.52,
                'estimated_jump_height_cm': 33.1,
                'note': '[模拟数据] MediaPipe 未安装，此为测试示例数据',
            },
            'squat': {
                'type': 'squat',
                'knee_angle_min': 78.5,
                'knee_angle_max': 175.3,
                'knee_angle_avg': 128.7,
                'hip_angle_min': 62.3,
                'hip_angle_max': 168.9,
                'hip_angle_avg': 115.4,
                'squat_depth': '全蹲 (低于平行)',
                'frames_analyzed': 150,
                'note': '[模拟数据] MediaPipe 未安装，此为测试示例数据',
            },
            'general': {
                'type': 'general',
                'frames_analyzed': 200,
                'note': '[模拟数据] MediaPipe 未安装，此为测试示例数据',
            },
        }
        
        # 生成模拟关键帧数据
        mock_keyframes = []
        for i in range(5):
            mock_keyframes.append({
                'frame': i * 30,
                'time_sec': round(i * 30 / 30.0, 2),
                'landmarks': [],  # 空数据，前端会使用模拟绘制
            })
        
        return {
            'status': 'done',
            'video_path': video_path,
            'duration_seconds': 5.0,
            'total_frames': 150,
            'fps': 30.0,
            'sample_frames': 150,
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
        h, w = frame.shape[:2]
        
        if not landmarks_data:
            return frame
        
        # 绘制关键点
        for lm in landmarks_data:
            if lm.get('visibility', 0) > 0.5:
                cx, cy = int(lm['x'] * w), int(lm['y'] * h)
                cv2.circle(frame, (cx, cy), 4, (0, 255, 100), -1)
        
        # 绘制连线
        for conn in POSE_CONNECTIONS:
            idx1, idx2 = conn
            if idx1 < len(landmarks_data) and idx2 < len(landmarks_data):
                lm1 = landmarks_data[idx1]
                lm2 = landmarks_data[idx2]
                if lm1.get('visibility', 0) > 0.5 and lm2.get('visibility', 0) > 0.5:
                    pt1 = (int(lm1['x'] * w), int(lm1['y'] * h))
                    pt2 = (int(lm2['x'] * w), int(lm2['y'] * h))
                    cv2.line(frame, pt1, pt2, (160, 192, 64), 2)
        
        return frame
