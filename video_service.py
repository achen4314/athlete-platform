"""
运动员数据分析平台 - 视频上传服务
运动员数据分析平台
"""
import os
import uuid
import logging
from datetime import datetime
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads', 'videos')
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'webm', 'mkv'}
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB


def _ensure_upload_folder():
    """确保上传目录存在"""
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename: str) -> bool:
    """检查文件扩展名是否允许"""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def get_video_id() -> str:
    """生成唯一视频 ID"""
    return uuid.uuid4().hex[:12]


def save_video(file, athlete_id: int) -> dict:
    """
    保存上传的视频文件

    Args:
        file: Flask FileStorage 对象
        athlete_id: 运动员 ID

    Returns:
        {
            'video_id': str,
            'filename': str,        # 服务端文件名
            'original_filename': str, # 原始文件名
            'filepath': str,         # 完整路径
            'size_mb': float,        # 文件大小 MB
            'size_bytes': int,       # 文件大小 bytes
        }
    """
    _ensure_upload_folder()
    
    if not file or not file.filename:
        raise ValueError("未选择文件")
    
    if not allowed_file(file.filename):
        raise ValueError(f"不支持的文件格式。允许: {', '.join(ALLOWED_EXTENSIONS)}")
    
    # 生成唯一文件名：athlete_id_video_id_原始名
    original_filename = file.filename
    ext = original_filename.rsplit('.', 1)[1].lower()
    video_id = get_video_id()
    safe_original = secure_filename(original_filename.rsplit('.', 1)[0])[:80]
    filename = f"{athlete_id}_{video_id}_{safe_original}.{ext}"
    
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    
    # 检查文件大小
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"文件过大。最大允许 {MAX_FILE_SIZE // 1024 // 1024}MB")
    
    # 保存文件
    file.save(filepath)
    
    size_mb = round(file_size / (1024 * 1024), 2)
    
    logger.info("视频已保存: video_id=%s, file=%s, size=%.2fMB", video_id, filename, size_mb)
    
    return {
        'video_id': video_id,
        'filename': filename,
        'original_filename': original_filename,
        'filepath': filepath,
        'size_mb': size_mb,
        'size_bytes': file_size,
    }


def get_video_path(video_id: str) -> str | None:
    """
    根据 video_id 获取视频文件路径

    Args:
        video_id: 视频唯一标识

    Returns:
        文件完整路径，未找到返回 None
    """
    _ensure_upload_folder()
    
    if not os.path.isdir(UPLOAD_FOLDER):
        return None
    
    for fname in os.listdir(UPLOAD_FOLDER):
        if video_id in fname:
            return os.path.join(UPLOAD_FOLDER, fname)
    
    return None


def delete_video(video_id: str) -> bool:
    """
    删除视频文件

    Args:
        video_id: 视频唯一标识

    Returns:
        是否删除成功
    """
    filepath = get_video_path(video_id)
    if filepath and os.path.exists(filepath):
        os.remove(filepath)
        logger.info("视频已删除: video_id=%s", video_id)
        return True
    return False


def get_video_duration(filepath: str) -> float:
    """
    获取视频时长（秒）
    优先使用 cv2，否则返回 0
    """
    try:
        import cv2
        cap = cv2.VideoCapture(filepath)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            cap.release()
            if fps > 0:
                return round(frame_count / fps, 2)
    except Exception as e:
        logger.warning("无法获取视频时长: %s", e)
    return 0.0
