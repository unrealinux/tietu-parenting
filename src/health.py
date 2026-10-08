"""
Health Check Module - 健康检查与系统监控

参考 feiqingqiWechatMP 的 health.js 实现
提供系统健康指标与业务指标跟踪
"""
import os
import sys
import time
import psutil
import platform
from datetime import datetime
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock

from src.logger import get_logger


logger = get_logger(__name__)


class HealthStatus(Enum):
    """健康状态枚举"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    status: HealthStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0


@dataclass
class BusinessCounters:
    """业务计数器"""
    fetched: int = 0              # 获取的新闻数量
    fetch_failures: int = 0       # 获取失败次数
    aggregated: int = 0           # 聚合的新闻数量
    generated: int = 0            # 生成的文章数量
    published: int = 0            # 发布的文章数量
    publish_failures: int = 0     # 发布失败次数


@dataclass
class BusinessTimestamps:
    """业务时间戳"""
    fetch: Optional[float] = None
    aggregate: Optional[float] = None
    generate: Optional[float] = None
    publish: Optional[float] = None


class HealthChecker:
    """健康检查器"""
    
    def __init__(self):
        self._checks: Dict[str, Callable] = {}
        self._last_results: Dict[str, HealthCheckResult] = {}
        self._started_at = time.time()
        self._business_counters = BusinessCounters()
        self._business_timestamps = BusinessTimestamps()
        self._lock = Lock()
        self._register_default_checks()
    
    def _register_default_checks(self):
        """注册默认检查项"""
        self.register_check("system", self._check_system)
        self.register_check("disk", self._check_disk)
        self.register_check("memory", self._check_memory)
        self.register_check("network", self._check_network)
    
    def register_check(self, name: str, check_func: Callable[[], HealthCheckResult]):
        """注册健康检查项
        
        Args:
            name: 检查项名称
            check_func: 检查函数，返回HealthCheckResult
        """
        self._checks[name] = check_func
        logger.info(f"Registered health check: {name}")
    
    def _check_system(self) -> HealthCheckResult:
        """检查系统信息"""
        try:
            details = {
                "platform": platform.system(),
                "platform_version": platform.version(),
                "python_version": platform.python_version(),
                "cpu_count": psutil.cpu_count(),
                "load_average": os.getloadavg() if hasattr(os, 'getloadavg') else None,
            }
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="System is running",
                details=details
            )
        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.UNKNOWN,
                message=f"Failed to check system: {e}",
            )
    
    def _check_disk(self) -> HealthCheckResult:
        """检查磁盘空间"""
        try:
            usage = psutil.disk_usage('/')
            percent = usage.percent
            
            if percent > 95:
                status = HealthStatus.UNHEALTHY
                message = "Disk almost full"
            elif percent > 85:
                status = HealthStatus.DEGRADED
                message = "Disk space running low"
            else:
                status = HealthStatus.HEALTHY
                message = "Disk space OK"
            
            return HealthCheckResult(
                status=status,
                message=message,
                details={
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "percent": percent
                }
            )
        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.UNKNOWN,
                message=f"Failed to check disk: {e}",
            )
    
    def _check_memory(self) -> HealthCheckResult:
        """检查内存使用"""
        try:
            mem = psutil.virtual_memory()
            percent = mem.percent
            
            if percent > 90:
                status = HealthStatus.UNHEALTHY
                message = "Memory critical"
            elif percent > 75:
                status = HealthStatus.DEGRADED
                message = "Memory high"
            else:
                status = HealthStatus.HEALTHY
                message = "Memory OK"
            
            return HealthCheckResult(
                status=status,
                message=message,
                details={
                    "total_gb": round(mem.total / (1024**3), 2),
                    "available_gb": round(mem.available / (1024**3), 2),
                    "percent": percent
                }
            )
        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.UNKNOWN,
                message=f"Failed to check memory: {e}",
            )
    
    def _check_network(self) -> HealthCheckResult:
        """检查网络连接"""
        try:
            # 检查DNS解析
            import socket
            socket.setdefaulttimeout(5)
            socket.gethostbyname("www.baidu.com")
            
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                message="Network is reachable",
                details={"dns": "ok"}
            )
        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.DEGRADED,
                message=f"Network issue: {e}",
            )
    
    def check_all(self) -> Dict[str, HealthCheckResult]:
        """执行所有健康检查
        
        Returns:
            检查结果字典
        """
        results = {}
        
        for name, check_func in self._checks.items():
            start_time = time.time()
            try:
                result = check_func()
                result.duration_ms = (time.time() - start_time) * 1000
                results[name] = result
                self._last_results[name] = result
                
                status_emoji = {
                    HealthStatus.HEALTHY: "✅",
                    HealthStatus.DEGRADED: "⚠️",
                    HealthStatus.UNHEALTHY: "❌",
                    HealthStatus.UNKNOWN: "❓"
                }
                logger.info(f"Health check [{name}]: {status_emoji[result.status]} {result.message}")
                
            except Exception as e:
                logger.error(f"Health check [{name}] failed: {e}")
                results[name] = HealthCheckResult(
                    status=HealthStatus.UNKNOWN,
                    message=f"Check failed: {e}",
                    duration_ms=(time.time() - start_time) * 1000
                )
        
        return results
    
    def get_overall_status(self) -> HealthStatus:
        """获取整体健康状态
        
        Returns:
            整体健康状态
        """
        if not self._last_results:
            return HealthStatus.UNKNOWN
        
        statuses = [r.status for r in self._last_results.values()]
        
        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            return HealthStatus.UNHEALTHY
        if any(s == HealthStatus.DEGRADED for s in statuses):
            return HealthStatus.DEGRADED
        if any(s == HealthStatus.UNKNOWN for s in statuses):
            return HealthStatus.UNKNOWN
        return HealthStatus.HEALTHY
    
    def get_status_report(self) -> Dict[str, Any]:
        """获取状态报告
        
        Returns:
            状态报告字典
        """
        overall = self.get_overall_status()
        results = self.check_all()
        
        return {
            "status": overall.value,
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": time.time() - self._started_at,
            "checks": {
                name: {
                    "status": result.status.value,
                    "message": result.message,
                    "duration_ms": round(result.duration_ms, 2),
                    "details": result.details
                }
                for name, result in results.items()
            },
            "business_metrics": self.get_business_metrics()
        }
    
    def inc_fetched(self, n: int = 1):
        """增加获取计数"""
        with self._lock:
            self._business_counters.fetched += n
            self._business_timestamps.fetch = time.time()
    
    def inc_fetch_failure(self, n: int = 1):
        """增加获取失败计数"""
        with self._lock:
            self._business_counters.fetch_failures += n
            self._business_timestamps.fetch = time.time()
    
    def inc_aggregated(self, n: int = 1):
        """增加聚合计数"""
        with self._lock:
            self._business_counters.aggregated += n
            self._business_timestamps.aggregate = time.time()
    
    def inc_generated(self, n: int = 1):
        """增加生成计数"""
        with self._lock:
            self._business_counters.generated += n
            self._business_timestamps.generate = time.time()
    
    def inc_published(self, n: int = 1):
        """增加发布计数"""
        with self._lock:
            self._business_counters.published += n
            self._business_timestamps.publish = time.time()
    
    def inc_publish_failure(self, n: int = 1):
        """增加发布失败计数"""
        with self._lock:
            self._business_counters.publish_failures += n
            self._business_timestamps.publish = time.time()
    
    def get_business_metrics(self) -> Dict[str, Any]:
        """获取业务指标"""
        with self._lock:
            counters = self._business_counters
            timestamps = self._business_timestamps
            
            # 计算失败率
            total_fetch = counters.fetched + counters.fetch_failures
            fetch_failure_rate = counters.fetch_failures / total_fetch if total_fetch > 0 else 0
            
            total_publish = counters.published + counters.publish_failures
            publish_failure_rate = counters.publish_failures / total_publish if total_publish > 0 else 0
            
            # 格式化时间戳
            def format_timestamp(ts: Optional[float]) -> Optional[str]:
                if ts is None:
                    return None
                return datetime.fromtimestamp(ts).isoformat()
            
            return {
                "counters": {
                    "fetched": counters.fetched,
                    "fetch_failures": counters.fetch_failures,
                    "aggregated": counters.aggregated,
                    "generated": counters.generated,
                    "published": counters.published,
                    "publish_failures": counters.publish_failures
                },
                "failure_rates": {
                    "fetch": round(fetch_failure_rate, 4),
                    "publish": round(publish_failure_rate, 4)
                },
                "last_activity": {
                    "fetch": format_timestamp(timestamps.fetch),
                    "aggregate": format_timestamp(timestamps.aggregate),
                    "generate": format_timestamp(timestamps.generate),
                    "publish": format_timestamp(timestamps.publish)
                }
            }
    
    def is_business_healthy(self) -> bool:
        """检查业务是否健康"""
        with self._lock:
            counters = self._business_counters
            
            # 检查获取失败率
            total_fetch = counters.fetched + counters.fetch_failures
            if total_fetch > 10:  # 至少有一定量的数据才有意义
                fetch_failure_rate = counters.fetch_failures / total_fetch
                if fetch_failure_rate > 0.5:  # 失败率超过 50%
                    return False
            
            # 检查发布失败率
            total_publish = counters.published + counters.publish_failures
            if total_publish > 0:
                publish_failure_rate = counters.publish_failures / total_publish
                if publish_failure_rate > 0.5:  # 失败率超过 50%
                    return False
            
            return True
    
    def reset_business_metrics(self):
        """重置业务指标"""
        with self._lock:
            self._business_counters = BusinessCounters()
            self._business_timestamps = BusinessTimestamps()
    
    def print_business_report(self):
        """打印业务报告"""
        metrics = self.get_business_metrics()
        
        print("\n" + "="*50)
        print("📊 业务指标报告")
        print("="*50)
        
        print(f"业务健康: {'✅ 健康' if self.is_business_healthy() else '❌ 异常'}")
        
        print("\n📈 计数器:")
        counters = metrics['counters']
        print(f"  获取新闻: {counters['fetched']} 次")
        print(f"  获取失败: {counters['fetch_failures']} 次")
        print(f"  聚合新闻: {counters['aggregated']} 次")
        print(f"  生成文章: {counters['generated']} 次")
        print(f"  发布文章: {counters['published']} 次")
        print(f"  发布失败: {counters['publish_failures']} 次")
        
        print("\n📉 失败率:")
        failure_rates = metrics['failure_rates']
        print(f"  获取失败率: {failure_rates['fetch']*100:.1f}%")
        print(f"  发布失败率: {failure_rates['publish']*100:.1f}%")
        
        print("\n⏰ 最后活动时间:")
        last_activity = metrics['last_activity']
        for key, value in last_activity.items():
            if value:
                print(f"  {key}: {value}")
            else:
                print(f"  {key}: 无记录")
        
        print()


# 全局健康检查器实例
_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """获取全局健康检查器"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


def register_health_check(name: str, check_func: Callable[[], HealthCheckResult]):
    """注册自定义健康检查"""
    get_health_checker().register_check(name, check_func)


def check_health() -> Dict[str, Any]:
    """快速健康检查"""
    return get_health_checker().get_status_report()


# 业务指标便捷函数
def inc_fetched(n: int = 1):
    """增加获取计数"""
    get_health_checker().inc_fetched(n)


def inc_fetch_failure(n: int = 1):
    """增加获取失败计数"""
    get_health_checker().inc_fetch_failure(n)


def inc_aggregated(n: int = 1):
    """增加聚合计数"""
    get_health_checker().inc_aggregated(n)


def inc_generated(n: int = 1):
    """增加生成计数"""
    get_health_checker().inc_generated(n)


def inc_published(n: int = 1):
    """增加发布计数"""
    get_health_checker().inc_published(n)


def inc_publish_failure(n: int = 1):
    """增加发布失败计数"""
    get_health_checker().inc_publish_failure(n)


def get_business_metrics() -> Dict[str, Any]:
    """获取业务指标"""
    return get_health_checker().get_business_metrics()


def is_business_healthy() -> bool:
    """检查业务是否健康"""
    return get_health_checker().is_business_healthy()


def print_business_report():
    """打印业务报告"""
    get_health_checker().print_business_report()


def create_health_endpoint():
    """创建健康检查端点（用于 Web 框架集成）"""
    def health_check():
        report = check_health()
        business_healthy = is_business_healthy()
        system_healthy = get_health_checker().get_overall_status() == HealthStatus.HEALTHY
        
        return {
            "status": "ok" if (business_healthy and system_healthy) else "error",
            "timestamp": datetime.now().isoformat(),
            "data": report
        }
    
    return health_check
