"""
运动员数据分析平台 - DeepSeek API 客户端
支持流式(SSE)和非流式调用
"""

import requests
import json
import logging
from typing import Generator, Dict, List, Optional, Any

# 配置日志
logger = logging.getLogger(__name__)


class DeepSeekClient:
    """DeepSeek API 客户端，封装对话请求逻辑"""

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com/v1",
                 model: str = "deepseek-chat", timeout: int = 60):
        """
        初始化 DeepSeek 客户端

        Args:
            api_key: API 密钥
            base_url: API 基础地址
            model: 模型名称
            timeout: 请求超时（秒）
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    @property
    def endpoint(self) -> str:
        """获取完整的聊天补全端点 URL"""
        return f"{self.base_url}/chat/completions"

    @property
    def headers(self) -> Dict[str, str]:
        """构建请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        非流式对话请求

        Args:
            messages: 消息列表，格式 [{"role": "system/user/assistant", "content": "..."}]
            temperature: 采样温度 (0-2)
            max_tokens: 最大生成 token 数
            stream: 是否流式（非流式模式下应为 False）

        Returns:
            API 返回的完整 JSON 响应

        Raises:
            requests.exceptions.RequestException: 网络请求异常
            ValueError: API 返回错误
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        try:
            response = requests.post(
                self.endpoint,
                headers=self.headers,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            logger.error("DeepSeek API 请求超时（%d秒）", self.timeout)
            raise Exception(f"AI 服务响应超时，请稍后重试（超时限制：{self.timeout}秒）")
        except requests.exceptions.ConnectionError as e:
            logger.error("DeepSeek API 连接失败: %s", str(e))
            raise Exception("无法连接到 AI 服务，请检查网络连接")
        except requests.exceptions.HTTPError as e:
            logger.error("DeepSeek API HTTP 错误: %s", str(e))
            if e.response is not None:
                status_code = e.response.status_code
                try:
                    error_data = e.response.json()
                    error_msg = error_data.get("error", {}).get("message", str(e))
                except Exception:
                    error_msg = str(e)
                if status_code == 401:
                    raise Exception("API 密钥无效，请联系管理员")
                elif status_code == 429:
                    raise Exception("AI 服务请求过于频繁，请稍后重试")
                elif status_code == 500:
                    raise Exception("AI 服务内部错误，请稍后重试")
                else:
                    raise Exception(f"AI 服务返回错误 ({status_code}): {error_msg}")
            raise Exception(f"AI 服务请求失败: {str(e)}")
        except Exception as e:
            logger.error("DeepSeek API 未知错误: %s", str(e))
            raise

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Generator[str, None, None]:
        """
        流式对话请求，通过 generator 逐字返回

        Args:
            messages: 消息列表
            temperature: 采样温度
            max_tokens: 最大生成 token 数

        Yields:
            每个 SSE chunk 中的文本内容

        Raises:
            Exception: 请求失败时抛出
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            response = requests.post(
                self.endpoint,
                headers=self.headers,
                json=payload,
                timeout=self.timeout,
                stream=True,
            )
            response.raise_for_status()

            # 逐行读取 SSE 流
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue

                # SSE 格式: "data: {json}"
                if line.startswith("data: "):
                    data_str = line[6:]  # 去掉 "data: " 前缀

                    # 检查是否为流结束信号
                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        logger.warning("SSE 解析失败: %s", data_str)
                        continue

        except requests.exceptions.Timeout:
            logger.error("DeepSeek API 流式请求超时")
            yield "\n\n[AI 服务响应超时，请稍后重试]"
        except requests.exceptions.ConnectionError as e:
            logger.error("DeepSeek API 流式连接失败: %s", str(e))
            yield "\n\n[无法连接到 AI 服务，请检查网络连接]"
        except Exception as e:
            logger.error("DeepSeek API 流式错误: %s", str(e))
            yield f"\n\n[AI 服务出错: {str(e)}]"


def create_deepseek_client(app_config) -> DeepSeekClient:
    """
    从 Flask 配置创建 DeepSeekClient 实例的工厂函数

    Args:
        app_config: Flask app.config 对象

    Returns:
        配置好的 DeepSeekClient 实例
    """
    return DeepSeekClient(
        api_key=app_config.get("DEEPSEEK_API_KEY", ""),
        base_url=app_config.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        model=app_config.get("DEEPSEEK_MODEL", "deepseek-chat"),
        timeout=60,
    )
