"""
Configuration Validator - 配置验证模块

参考 feiqingqiWechatMP 的 validate-config.js 实现
提供完善的配置验证功能
"""
import os
import re
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse
from dataclasses import dataclass
from enum import Enum

from src.logger import get_logger


logger = get_logger(__name__)


class ValidationErrorType(Enum):
    """验证错误类型"""
    REQUIRED = "required"
    FORMAT = "format"
    RANGE = "range"
    CONNECTION = "connection"
    PERMISSION = "permission"


@dataclass
class ValidationError:
    """验证错误"""
    field: str
    error_type: ValidationErrorType
    message: str
    value: Any = None
    
    def __str__(self):
        return f"[{self.error_type.value}] {self.field}: {self.message}"


class ConfigValidator:
    """配置验证器"""
    
    def __init__(self):
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []
    
    def validate_wechat_config(self, config: Dict) -> List[ValidationError]:
        """验证微信配置"""
        errors = []
        wechat = config.get("wechat", {})
        
        # 验证 AppID
        app_id = wechat.get("app_id", "")
        if not app_id or app_id.startswith("your_"):
            errors.append(ValidationError(
                field="wechat.app_id",
                error_type=ValidationErrorType.REQUIRED,
                message="微信公众号 AppID 未配置",
                value=app_id
            ))
        elif not re.match(r"^wx[a-f0-9]{16}$", app_id):
            errors.append(ValidationError(
                field="wechat.app_id",
                error_type=ValidationErrorType.FORMAT,
                message="AppID 格式不正确，应以 'wx' 开头，后跟16位字符",
                value=app_id
            ))
        
        # 验证 AppSecret
        app_secret = wechat.get("app_secret", "")
        if not app_secret or app_secret.startswith("your_"):
            errors.append(ValidationError(
                field="wechat.app_secret",
                error_type=ValidationErrorType.REQUIRED,
                message="微信公众号 AppSecret 未配置",
                value=app_secret
            ))
        
        return errors
    
    def validate_llm_config(self, config: Dict) -> List[ValidationError]:
        """验证 LLM 配置"""
        errors = []
        
        # 验证 LLM 提供商配置
        llm_config = config.get("llm", {})
        provider = (llm_config.get("provider") or "auto").strip().lower()

        # 各提供商配置段：用于「格式体检」和「是否至少有一个可用」
        llm_sections = {
            "openai": config.get("openai", {}),
            "openrouter": config.get("openrouter", {}),
            "deepseek": config.get("deepseek", {}),
            "zhipu": config.get("zhipu", {}),
            "siliconflow": config.get("siliconflow", {}),
            "agnes": config.get("agnes", {}),
        }

        def _llm_key(name: str) -> str:
            value = (llm_sections.get(name) or {}).get("api_key", "") or ""
            return "" if value.startswith("your_") else value

        # 只给「实际会被使用」的提供商做格式检查。
        # 早前的写法硬套 OpenAI 格式 (sk-[a-zA-Z0-9]{48,})，只要 .env 里留着一把
        # 没用上的旧 key 就报警，把真正的错误派报掉了。
        checked_providers = [provider] if provider in llm_sections else list(llm_sections)
        for name in checked_providers:
            key = _llm_key(name)
            if key and (len(key) < 20 or re.search(r"\s", key)):
                errors.append(ValidationError(
                    field=f"{name}.api_key",
                    error_type=ValidationErrorType.FORMAT,
                    message=f"{name} API Key 格式可疑（长度不足或含空白字符）",
                    value=key[:10] + "..."
                ))

        if not any(_llm_key(name) for name in llm_sections):
            errors.append(ValidationError(
                field="llm",
                error_type=ValidationErrorType.REQUIRED,
                message="至少需要配置一个 LLM 提供商 (Agnes/OpenAI/DeepSeek/智谱AI/SiliconFlow/OpenRouter)"
            ))
        
        return errors
    
    def validate_news_config(self, config: Dict) -> List[ValidationError]:
        """验证新闻配置"""
        errors = []
        warnings = []
        news = config.get("news", {})
        
        # 验证搜索关键词
        keywords = news.get("search_keywords", [])
        if not keywords:
            warnings.append(ValidationError(
                field="news.search_keywords",
                error_type=ValidationErrorType.REQUIRED,
                message="未配置搜索关键词，将使用默认关键词"
            ))
        
        # 验证最大新闻数量
        max_news = news.get("max_news", 15)
        if not isinstance(max_news, int) or max_news < 1 or max_news > 100:
            errors.append(ValidationError(
                field="news.max_news",
                error_type=ValidationErrorType.RANGE,
                message="max_news 应为 1-100 之间的整数",
                value=max_news
            ))
        
        # 验证排除关键词
        exclude_keywords = news.get("exclude_keywords", [])
        if not isinstance(exclude_keywords, list):
            errors.append(ValidationError(
                field="news.exclude_keywords",
                error_type=ValidationErrorType.FORMAT,
                message="exclude_keywords 应为列表格式",
                value=exclude_keywords
            ))
        
        # 验证新闻源配置
        sources = news.get("sources", {})
        if not isinstance(sources, dict):
            errors.append(ValidationError(
                field="news.sources",
                error_type=ValidationErrorType.FORMAT,
                message="sources 应为字典格式",
                value=sources
            ))
        
        # 验证国内新闻源配置
        domestic_sources = news.get("domestic_sources", {})
        if domestic_sources.get("enabled", False):
            required_keys = ["bing_china", "baidu", "weibo", "zhihu", "36kr", "liangzi", "jiqizhixin", "huxiu"]
            for key in required_keys:
                if key not in domestic_sources:
                    warnings.append(ValidationError(
                        field=f"news.domestic_sources.{key}",
                        error_type=ValidationErrorType.REQUIRED,
                        message=f"国内新闻源 {key} 未配置"
                    ))
        
        self.warnings.extend(warnings)
        return errors
    
    def validate_publish_config(self, config: Dict) -> List[ValidationError]:
        """验证发布配置"""
        errors = []
        publish = config.get("publish", {})
        
        # 验证作者
        author = publish.get("author", "")
        if not author:
            errors.append(ValidationError(
                field="publish.author",
                error_type=ValidationErrorType.REQUIRED,
                message="发布作者未配置"
            ))
        
        # 验证默认封面
        default_cover = publish.get("default_cover", "")
        if default_cover and not os.path.exists(default_cover):
            errors.append(ValidationError(
                field="publish.default_cover",
                error_type=ValidationErrorType.PERMISSION,
                message="默认封面文件不存在",
                value=default_cover
            ))
        
        return errors
    
    def validate_scheduler_config(self, config: Dict) -> List[ValidationError]:
        """验证调度配置"""
        errors = []
        scheduler = config.get("scheduler", {})
        
        if scheduler.get("enabled", False):
            # 验证时间格式
            time_str = scheduler.get("time", "08:00")
            if not re.match(r"^\d{2}:\d{2}$", time_str):
                errors.append(ValidationError(
                    field="scheduler.time",
                    error_type=ValidationErrorType.FORMAT,
                    message="时间格式应为 HH:MM",
                    value=time_str
                ))
            else:
                # 验证时间范围
                hour, minute = map(int, time_str.split(":"))
                if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                    errors.append(ValidationError(
                        field="scheduler.time",
                        error_type=ValidationErrorType.RANGE,
                        message="时间值超出范围 (00:00-23:59)",
                        value=time_str
                    ))
            
            # 验证时区
            timezone = scheduler.get("timezone", "Asia/Shanghai")
            if not isinstance(timezone, str) or len(timezone) < 3:
                errors.append(ValidationError(
                    field="scheduler.timezone",
                    error_type=ValidationErrorType.FORMAT,
                    message="时区格式不正确",
                    value=timezone
                ))
        
        return errors
    
    def validate_environment_variables(self) -> List[ValidationError]:
        """验证环境变量"""
        errors = []
        
        # 检查 EXA_API_KEY
        exa_key = os.environ.get("EXA_API_KEY", "")
        if exa_key:
            if len(exa_key) < 20:
                errors.append(ValidationError(
                    field="EXA_API_KEY",
                    error_type=ValidationErrorType.FORMAT,
                    message="EXA_API_KEY 格式不正确",
                    value=exa_key[:10] + "..."
                ))
        
        # 检查代理配置
        http_proxy = os.environ.get("HTTP_PROXY", "")
        https_proxy = os.environ.get("HTTPS_PROXY", "")
        if http_proxy or https_proxy:
            for proxy_name, proxy_url in [("HTTP_PROXY", http_proxy), ("HTTPS_PROXY", https_proxy)]:
                if proxy_url:
                    try:
                        parsed = urlparse(proxy_url)
                        if not parsed.scheme or not parsed.netloc:
                            errors.append(ValidationError(
                                field=proxy_name,
                                error_type=ValidationErrorType.FORMAT,
                                message=f"{proxy_name} 格式不正确",
                                value=proxy_url
                            ))
                    except Exception:
                        errors.append(ValidationError(
                            field=proxy_name,
                            error_type=ValidationErrorType.FORMAT,
                            message=f"{proxy_name} 解析失败",
                            value=proxy_url
                        ))
        
        return errors
    
    def validate_all(self, config: Dict) -> Dict[str, Any]:
        """验证所有配置"""
        self.errors = []
        self.warnings = []
        
        # 验证各模块配置
        self.errors.extend(self.validate_wechat_config(config))
        self.errors.extend(self.validate_llm_config(config))
        self.errors.extend(self.validate_news_config(config))
        self.errors.extend(self.validate_publish_config(config))
        self.errors.extend(self.validate_scheduler_config(config))
        self.errors.extend(self.validate_environment_variables())
        
        # 返回验证结果
        return {
            "valid": len(self.errors) == 0,
            "errors": self.errors,
            "warnings": self.warnings,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings)
        }


def validate_config(config: Dict) -> Dict[str, Any]:
    """验证配置的便捷函数"""
    validator = ConfigValidator()
    return validator.validate_all(config)


def print_config_status(config: Dict):
    """打印配置状态"""
    result = validate_config(config)
    
    print("\n" + "="*50)
    print("📋 配置验证结果")
    print("="*50)
    
    if result["valid"]:
        print("✅ 配置验证通过")
    else:
        print(f"❌ 配置验证失败: {result['error_count']} 个错误")
    
    if result["warnings"]:
        print(f"⚠️ 警告: {result['warning_count']} 个")
    
    if result["errors"]:
        print("\n❌ 错误详情:")
        for error in result["errors"]:
            print(f"  - {error}")
    
    if result["warnings"]:
        print("\n⚠️ 警告详情:")
        for warning in result["warnings"]:
            print(f"  - {warning}")
    
    print()


if __name__ == "__main__":
    from src.config import load_config
    
    try:
        config = load_config()
        print_config_status(config)
    except Exception as e:
        print(f"配置加载失败: {e}")
