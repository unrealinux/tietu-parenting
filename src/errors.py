"""
Error Handling Module - 错误处理增强模块

参考 feiqingqiWechatMP 的 errors.js 实现
提供错误分类、重试机制、断路器等
"""
import time
import asyncio
import functools
import logging
from typing import Callable, Any, Optional, Dict, List, Type
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

from src.logger import get_logger


logger = get_logger(__name__)


class ErrorType(Enum):
    """错误类型枚举"""
    NETWORK = "NETWORK_ERROR"           # 网络错误（可重试）
    TIMEOUT = "TIMEOUT_ERROR"           # 超时错误（可重试）
    RATE_LIMIT = "RATE_LIMIT_ERROR"     # 速率限制（可重试，需等待）
    AUTH = "AUTH_ERROR"                 # 认证错误（不可重试）
    VALIDATION = "VALIDATION_ERROR"     # 验证错误（不可重试）
    NOT_FOUND = "NOT_FOUND_ERROR"       # 资源不存在（不可重试）
    PARSE = "PARSE_ERROR"               # 解析错误（不可重试）
    SYSTEM = "SYSTEM_ERROR"             # 系统错误（视情况重试）
    UNKNOWN = "UNKNOWN_ERROR"           # 未知错误
    CIRCUIT_OPEN = "CIRCUIT_OPEN"       # 断路器开启


# 可恢复的错误类型
RECOVERABLE_ERRORS = [
    ErrorType.NETWORK,
    ErrorType.TIMEOUT,
    ErrorType.RATE_LIMIT,
    ErrorType.SYSTEM,
]


class AppError(Exception):
    """自定义应用错误类"""
    
    def __init__(
        self,
        message: str,
        error_type: ErrorType = ErrorType.UNKNOWN,
        original_error: Optional[Exception] = None,
        context: Optional[Dict] = None,
        retry_count: int = 0
    ):
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.is_recoverable = error_type in RECOVERABLE_ERRORS
        self.original_error = original_error
        self.context = context or {}
        self.timestamp = datetime.now().isoformat()
        self.retry_count = retry_count
    
    def can_retry(self, max_retries: int = 3) -> bool:
        """是否可以重试"""
        return self.is_recoverable and self.retry_count < max_retries
    
    def with_retry(self) -> 'AppError':
        """创建带重试计数的副本"""
        return AppError(
            message=self.message,
            error_type=self.error_type,
            original_error=self.original_error,
            context=self.context,
            retry_count=self.retry_count + 1
        )
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "name": self.__class__.__name__,
            "type": self.error_type.value,
            "message": self.message,
            "is_recoverable": self.is_recoverable,
            "context": self.context,
            "timestamp": self.timestamp,
            "retry_count": self.retry_count,
            "original_error": str(self.original_error) if self.original_error else None
        }
    
    def __str__(self):
        return f"[{self.error_type.value}] {self.message}"


def create_app_error(error: Exception, context: Optional[Dict] = None) -> AppError:
    """从原生错误创建 AppError"""
    # 已经是 AppError
    if isinstance(error, AppError):
        return error
    
    # 请求库错误
    if hasattr(error, 'response'):
        response = error.response
        if response is not None:
            status_code = response.status_code
            if status_code == 401:
                return AppError(
                    message=f"认证失败: {error}",
                    error_type=ErrorType.AUTH,
                    original_error=error,
                    context=context
                )
            elif status_code == 404:
                return AppError(
                    message=f"资源不存在: {error}",
                    error_type=ErrorType.NOT_FOUND,
                    original_error=error,
                    context=context
                )
            elif status_code == 429:
                return AppError(
                    message=f"请求频率限制: {error}",
                    error_type=ErrorType.RATE_LIMIT,
                    original_error=error,
                    context=context
                )
            elif status_code >= 500:
                return AppError(
                    message=f"服务器错误: {error}",
                    error_type=ErrorType.SYSTEM,
                    original_error=error,
                    context=context
                )
    
    # 超时错误
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return AppError(
            message=f"请求超时: {error}",
            error_type=ErrorType.TIMEOUT,
            original_error=error,
            context=context
        )
    
    # 连接错误
    if isinstance(error, ConnectionError):
        return AppError(
            message=f"连接错误: {error}",
            error_type=ErrorType.NETWORK,
            original_error=error,
            context=context
        )
    
    # 解析错误
    if isinstance(error, (ValueError, TypeError)) and "parse" in str(error).lower():
        return AppError(
            message=f"解析错误: {error}",
            error_type=ErrorType.PARSE,
            original_error=error,
            context=context
        )
    
    # 默认为未知错误
    return AppError(
        message=str(error),
        error_type=ErrorType.UNKNOWN,
        original_error=error,
        context=context
    )


def with_retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    max_delay: float = 60.0,
    retryable_errors: Optional[List[ErrorType]] = None
):
    """重试装饰器
    
    Args:
        max_retries: 最大重试次数
        delay: 初始延迟时间（秒）
        backoff_factor: 退避因子
        max_delay: 最大延迟时间（秒）
        retryable_errors: 可重试的错误类型列表
    """
    if retryable_errors is None:
        retryable_errors = RECOVERABLE_ERRORS
    
    def decorator(func):
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_error = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = create_app_error(e)
                    
                    # 检查是否可以重试
                    if not last_error.is_recoverable or last_error.error_type not in retryable_errors:
                        logger.error(f"不可重试的错误: {last_error}")
                        raise last_error
                    
                    if attempt < max_retries:
                        logger.warning(f"重试 {attempt + 1}/{max_retries}: {last_error}")
                        time.sleep(current_delay)
                        current_delay = min(current_delay * backoff_factor, max_delay)
                    else:
                        logger.error(f"重试次数已用尽: {last_error}")
                        raise last_error
            
            raise last_error
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_error = None
            current_delay = delay
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = create_app_error(e)
                    
                    # 检查是否可以重试
                    if not last_error.is_recoverable or last_error.error_type not in retryable_errors:
                        logger.error(f"不可重试的错误: {last_error}")
                        raise last_error
                    
                    if attempt < max_retries:
                        logger.warning(f"重试 {attempt + 1}/{max_retries}: {last_error}")
                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * backoff_factor, max_delay)
                    else:
                        logger.error(f"重试次数已用尽: {last_error}")
                        raise last_error
            
            raise last_error
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def error_handler(
    default_return: Any = None,
    log_error: bool = True,
    raise_error: bool = False
):
    """错误处理装饰器
    
    Args:
        default_return: 发生错误时的默认返回值
        log_error: 是否记录错误日志
        raise_error: 是否重新抛出错误
    """
    def decorator(func):
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                app_error = create_app_error(e)
                if log_error:
                    logger.error(f"函数 {func.__name__} 发生错误: {app_error}")
                if raise_error:
                    raise app_error
                return default_return
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                app_error = create_app_error(e)
                if log_error:
                    logger.error(f"函数 {func.__name__} 发生错误: {app_error}")
                if raise_error:
                    raise app_error
                return default_return
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


class ErrorCollector:
    """错误收集器"""
    
    def __init__(self, max_errors: int = 100):
        self.max_errors = max_errors
        self.errors: List[AppError] = []
        self.error_counts: Dict[ErrorType, int] = {}
    
    def add(self, error: AppError):
        """添加错误"""
        self.errors.append(error)
        
        # 更新计数
        error_type = error.error_type
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        
        # 限制错误数量
        if len(self.errors) > self.max_errors:
            self.errors.pop(0)
    
    def get_summary(self) -> Dict:
        """获取错误摘要"""
        return {
            "total_errors": len(self.errors),
            "error_counts": {k.value: v for k, v in self.error_counts.items()},
            "recoverable_errors": sum(1 for e in self.errors if e.is_recoverable),
            "unrecoverable_errors": sum(1 for e in self.errors if not e.is_recoverable)
        }
    
    def clear(self):
        """清空错误"""
        self.errors.clear()
        self.error_counts.clear()
    
    def has_critical_errors(self) -> bool:
        """是否有严重错误"""
        critical_types = [ErrorType.AUTH, ErrorType.VALIDATION]
        return any(e.error_type in critical_types for e in self.errors)


# 全局错误收集器
_error_collector = ErrorCollector()


def get_error_collector() -> ErrorCollector:
    """获取全局错误收集器"""
    return _error_collector


def log_error(error: Exception, context: Optional[Dict] = None):
    """记录错误"""
    app_error = create_app_error(error, context)
    _error_collector.add(app_error)
    logger.error(f"错误已记录: {app_error}")


def get_error_summary() -> Dict:
    """获取错误摘要"""
    return _error_collector.get_summary()


if __name__ == "__main__":
    # 测试代码
    @with_retry(max_retries=2, delay=0.1)
    def test_retry():
        import random
        if random.random() < 0.7:
            raise ConnectionError("模拟网络错误")
        return "成功"
    
    try:
        result = test_retry()
        print(f"结果: {result}")
    except AppError as e:
        print(f"最终错误: {e}")
        print(f"错误详情: {e.to_dict()}")
