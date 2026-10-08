"""
Proxy Support Module - 代理支持模块

参考 feiqingqiWechatMP 的 proxy.js 实现
支持配置 HTTP/HTTPS 代理来解决网络问题
"""
import os
import asyncio
from typing import Dict, Optional, Any
from urllib.parse import urlparse
from dataclasses import dataclass

from src.logger import get_logger


logger = get_logger(__name__)


@dataclass
class ProxyConfig:
    """代理配置"""
    http: str = ""
    https: str = ""
    enabled: bool = False
    
    @classmethod
    def from_env(cls) -> 'ProxyConfig':
        """从环境变量创建配置"""
        http_proxy = os.environ.get("HTTP_PROXY", "") or os.environ.get("http_proxy", "")
        https_proxy = os.environ.get("HTTPS_PROXY", "") or os.environ.get("https_proxy", "")
        
        return cls(
            http=http_proxy,
            https=https_proxy,
            enabled=bool(http_proxy or https_proxy)
        )


class ProxyManager:
    """代理管理器"""
    
    def __init__(self, config: Optional[ProxyConfig] = None):
        self.config = config or ProxyConfig.from_env()
        self._validate_config()
    
    def _validate_config(self):
        """验证代理配置"""
        if not self.config.enabled:
            return
        
        # 验证 HTTP 代理
        if self.config.http:
            self._validate_proxy_url(self.config.http, "HTTP_PROXY")
        
        # 验证 HTTPS 代理
        if self.config.https:
            self._validate_proxy_url(self.config.https, "HTTPS_PROXY")
    
    def _validate_proxy_url(self, url: str, name: str):
        """验证代理 URL 格式"""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                logger.warning(f"{name} 格式不正确: {url}")
                return False
            
            # 检查是否为支持的协议
            if parsed.scheme not in ["http", "https", "socks4", "socks5"]:
                logger.warning(f"{name} 不支持的协议: {parsed.scheme}")
                return False
            
            return True
        except Exception as e:
            logger.warning(f"{name} 解析失败: {e}")
            return False
    
    def get_requests_proxy(self) -> Dict[str, str]:
        """获取 requests 库的代理配置"""
        if not self.config.enabled:
            return {}
        
        proxy_dict = {}
        
        if self.config.http:
            proxy_dict["http"] = self.config.http
        
        if self.config.https:
            proxy_dict["https"] = self.config.https
        
        return proxy_dict
    
    def get_aiohttp_proxy(self) -> Optional[str]:
        """获取 aiohttp 的代理配置"""
        if not self.config.enabled:
            return None
        
        # aiohttp 只支持单个代理 URL
        return self.config.https or self.config.http
    
    def get_httpx_proxy(self) -> Dict[str, str]:
        """获取 httpx 的代理配置"""
        if not self.config.enabled:
            return {}
        
        proxy_dict = {}
        
        if self.config.http:
            proxy_dict["http://"] = self.config.http
        
        if self.config.https:
            proxy_dict["https://"] = self.config.https
        
        return proxy_dict
    
    async def test_connection(self, test_url: str = "https://www.baidu.com", timeout: int = 10) -> bool:
        """测试代理连接"""
        if not self.config.enabled:
            logger.info("代理未配置，跳过连接测试")
            return True
        
        try:
            import aiohttp
            
            proxy = self.get_aiohttp_proxy()
            if not proxy:
                logger.warning("代理 URL 无效")
                return False
            
            logger.info(f"测试代理连接: {test_url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(test_url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                    if response.status == 200:
                        logger.info("代理连接测试成功")
                        return True
                    else:
                        logger.warning(f"代理连接测试失败: HTTP {response.status}")
                        return False
        
        except asyncio.TimeoutError:
            logger.error("代理连接测试超时")
            return False
        except Exception as e:
            logger.error(f"代理连接测试异常: {e}")
            return False
    
    def print_status(self):
        """打印代理状态"""
        print("\n🔍 代理配置检测")
        print("─" * 40)
        
        if not self.config.enabled:
            print("❌ 未配置代理")
            print("\n配置方法:")
            print("在 .env 文件中添加:")
            print("  HTTP_PROXY=http://127.0.0.1:7890")
            print("  HTTPS_PROXY=http://127.0.0.1:7890")
            return
        
        print("✅ 代理已配置")
        print(f"   HTTP:  {self.config.http or '(未配置)'}")
        print(f"   HTTPS: {self.config.https or '(未配置)'}")
        
        # 验证代理 URL 格式
        if self.config.http:
            if self._validate_proxy_url(self.config.http, "HTTP_PROXY"):
                print("   ✅ HTTP 代理格式正确")
            else:
                print("   ❌ HTTP 代理格式错误")
        
        if self.config.https:
            if self._validate_proxy_url(self.config.https, "HTTPS_PROXY"):
                print("   ✅ HTTPS 代理格式正确")
            else:
                print("   ❌ HTTPS 代理格式错误")


# 全局代理管理器实例
_proxy_manager: Optional[ProxyManager] = None


def get_proxy_manager() -> ProxyManager:
    """获取全局代理管理器"""
    global _proxy_manager
    if _proxy_manager is None:
        _proxy_manager = ProxyManager()
    return _proxy_manager


def get_requests_proxy() -> Dict[str, str]:
    """获取 requests 库的代理配置"""
    return get_proxy_manager().get_requests_proxy()


def get_aiohttp_proxy() -> Optional[str]:
    """获取 aiohttp 的代理配置"""
    return get_proxy_manager().get_aiohttp_proxy()


def get_httpx_proxy() -> Dict[str, str]:
    """获取 httpx 的代理配置"""
    return get_proxy_manager().get_httpx_proxy()


def is_proxy_enabled() -> bool:
    """检查代理是否启用"""
    return get_proxy_manager().config.enabled


def print_proxy_status():
    """打印代理状态"""
    get_proxy_manager().print_status()


# 便捷函数
def configure_requests_session(session):
    """配置 requests Session 的代理"""
    if not is_proxy_enabled():
        return session
    
    proxy_dict = get_requests_proxy()
    session.proxies.update(proxy_dict)
    
    logger.info(f"已配置代理: {proxy_dict}")
    return session


def configure_aiohttp_client_session(session):
    """配置 aiohttp ClientSession 的代理"""
    if not is_proxy_enabled():
        return session
    
    # aiohttp 的代理配置在请求时指定
    logger.info("aiohttp 代理将在请求时配置")
    return session


if __name__ == "__main__":
    print_proxy_status()
    
    # 测试代理连接
    async def test():
        manager = get_proxy_manager()
        if manager.config.enabled:
            await manager.test_connection()
    
    asyncio.run(test())
