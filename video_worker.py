"""
运动员数据分析平台 - 视频后台处理 Worker
运动员数据分析平台

独立脚本，处理新上传的视频：
1. 扫描 status='uploaded' 的视频
2. 调用 PoseAnalyzer 分析（支持生成标注视频）
3. 更新数据库中的 status 和 analysis_results
"""
import json
import logging
import sys
import os
import time

# 确保可以导入项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import db, Video
from pose_analyzer import PoseAnalyzer
from video_service import get_video_path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('video_worker')


def process_single_video(video_id: int, app, generate_annotated: bool = True) -> bool:
    """
    处理单个视频

    Args:
        video_id: Video 表的 id（数据库主键）
        app: Flask 应用实例
        generate_annotated: 是否生成标注视频（叠加骨架线 + 关节角）

    Returns:
        是否处理成功
    """
    with app.app_context():
        video = Video.query.get(video_id)
        if not video:
            logger.error("视频记录不存在: id=%d", video_id)
            return False

        if video.status not in ('uploaded', 'error'):
            logger.info("视频 %d 状态为 %s，跳过", video_id, video.status)
            return True

        logger.info("开始处理视频: id=%d, file=%s, type=%s",
                     video_id, video.filename, video.test_type)

        # 更新状态为处理中
        video.status = 'processing'
        db.session.commit()

        # 获取文件路径
        filepath = get_video_path(video.video_id)
        if not filepath:
            video.status = 'error'
            video.analysis_results = json.dumps(
                {'error': '视频文件不存在', 'status': 'error'},
                ensure_ascii=False
            )
            db.session.commit()
            logger.error("视频文件不存在: video_id=%s", video.video_id)
            return False

        try:
            # 执行姿态分析
            analyzer = PoseAnalyzer()
            result = analyzer.analyze_video(
                filepath,
                video.test_type or None,
                generate_annotated=generate_annotated
            )

            # 更新视频记录
            video.status = 'done'
            video.duration_seconds = result.get('duration_seconds', 0)
            video.analysis_results = json.dumps(result, ensure_ascii=False)

            # 如果生成了标注视频，记录路径
            if generate_annotated and result.get('annotated_video_path'):
                logger.info("标注视频已生成: %s", result['annotated_video_path'])

            db.session.commit()

            logger.info("视频处理完成: id=%d, type=%s, metrics=%s",
                         video_id,
                         result.get('test_type', 'unknown'),
                         list(result.get('metrics', {}).keys()))
            return True

        except Exception as e:
            logger.exception("视频处理失败: id=%d", video_id)
            video.status = 'error'
            video.analysis_results = json.dumps({
                'error': str(e),
                'status': 'error',
            }, ensure_ascii=False)
            db.session.commit()
            return False


def process_pending_videos(app, generate_annotated: bool = False):
    """
    扫描并处理所有待处理视频

    Args:
        app: Flask 应用实例
        generate_annotated: 是否生成标注视频（批量处理时建议关闭以节省空间）
    """
    with app.app_context():
        pending = Video.query.filter(Video.status == 'uploaded').all()
        logger.info("发现 %d 个待处理视频", len(pending))

        for video in pending:
            process_single_video(video.id, app, generate_annotated=generate_annotated)


def run_worker(app, interval_seconds: int = 10):
    """
    后台 Worker 主循环（阻塞）

    Args:
        app: Flask 应用实例
        interval_seconds: 轮询间隔（秒）
    """
    logger.info("视频处理 Worker 启动，轮询间隔 %ds", interval_seconds)

    while True:
        try:
            process_pending_videos(app)
        except Exception as e:
            logger.exception("Worker 循环出错: %s", e)

        time.sleep(interval_seconds)


# ==================== 入口 ====================

if __name__ == '__main__':
    # 独立运行时
    from app import app as flask_app

    # 确保数据库表存在
    with flask_app.app_context():
        db.create_all()

    run_worker(flask_app, interval_seconds=5)
