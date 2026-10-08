"""
Config Loader - 安全配置管理

支持环境变量覆盖、密钥加密、多环境配置
"""

import os
import json
import logging
from pathlib import Path
from typing import Any, Optional, Dict
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ENV_FILE = Path(".env")


def load_env():
    """加载 .env 文件"""
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
        logger.info(f"Loaded environment from {ENV_FILE}")
    else:
        logger.info("No .env file found, using system environment variables")


def get_env(key: str, default: Any = None, required: bool = False) -> Any:
    """安全获取环境变量"""
    value = os.environ.get(key, default)
    
    if required and not value:
        logger.warning(f"Required environment variable {key} is not set")
    
    return value


def get_wechat_config() -> Dict:
    """获取微信公众号配置（环境变量优先）"""
    load_env()
    
    return {
        "app_id": get_env("WECHAT_APP_ID", ""),
        "app_secret": get_env("WECHAT_APP_SECRET", "")
    }


def get_openai_config() -> Dict:
    """获取 OpenAI 配置"""
    load_env()
    
    return {
        "api_key": get_env("OPENAI_API_KEY", ""),
        "model": get_env("OPENAI_MODEL", "gpt-4o-mini"),
        "temperature": float(get_env("OPENAI_TEMPERATURE", "0.7")),
        "max_tokens": int(get_env("OPENAI_MAX_TOKENS", "4000"))
    }


def get_news_config() -> Dict:
    """获取新闻源配置"""
    load_env()
    
    keywords_str = get_env("NEWS_KEYWORDS", "")
    keywords = [k.strip() for k in keywords_str.split(",")] if keywords_str else [
        "AI 人工智能", "OpenAI GPT", "LLM 大语言模型"
    ]
    
    return {
        "search_keywords": keywords,
        "max_results_per_search": int(get_env("NEWS_MAX_RESULTS", "10")),
        "max_news": int(get_env("NEWS_MAX_NEWS", "15")),
        "exclude_keywords": get_env("NEWS_EXCLUDE_KEYWORDS", "广告,招聘").split(","),
        "sources": {
            "search": get_env("NEWS_SOURCE_SEARCH", "false").lower() == "true",
            "rss": get_env("NEWS_SOURCE_RSS", "false").lower() == "true",
            "hackernews": get_env("NEWS_SOURCE_HN", "false").lower() == "true",
            "websites": get_env("NEWS_SOURCE_WEBSITES", "false").lower() == "true"
        }
    }


def get_publish_config() -> Dict:
    """获取发布配置"""
    load_env()
    
    return {
        "author": get_env("PUBLISH_AUTHOR", "AI前沿观察"),
        "default_cover": get_env("PUBLISH_COVER", "cover.png"),
        "default_digest": get_env("PUBLISH_DIGEST", "每日AI资讯汇总"),
        "channels": get_env("PUBLISH_CHANNELS", "file,wechat").split(","),
        "auto_publish": get_env("PUBLISH_AUTO", "false").lower() == "true"
    }


def get_scheduler_config() -> Dict:
    """获取调度配置"""
    load_env()
    
    return {
        "enabled": get_env("SCHEDULER_ENABLED", "false").lower() == "true",
        "time": get_env("SCHEDULER_TIME", "08:00"),
        "timezone": get_env("SCHEDULER_TZ", "Asia/Shanghai")
    }


def get_wecom_config() -> Dict:
    """获取企业微信配置"""
    load_env()
    
    return {
        "corp_id": get_env("WECOM_CORP_ID", ""),
        "corp_secret": get_env("WECOM_CORP_SECRET", ""),
        "agent_id": get_env("WECOM_AGENT_ID", "")
    }


def get_dingtalk_config() -> Dict:
    """获取钉钉配置"""
    load_env()
    
    return {
        "webhook": get_env("DINGTALK_WEBHOOK", ""),
        "secret": get_env("DINGTALK_SECRET", "")
    }


def get_email_config() -> Dict:
    """获取邮件配置"""
    load_env()
    
    to_addrs = get_env("EMAIL_TO_ADDRS", "")
    
    return {
        "smtp_host": get_env("EMAIL_SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(get_env("EMAIL_SMTP_PORT", "587")),
        "username": get_env("EMAIL_USERNAME", ""),
        "password": get_env("EMAIL_PASSWORD", ""),
        "from_addr": get_env("EMAIL_FROM_ADDR", ""),
        "to_addrs": [a.strip() for a in to_addrs.split(",")] if to_addrs else []
    }


def get_monitoring_config() -> Dict:
    """获取监控配置"""
    load_env()
    
    return {
        "enabled": get_env("MONITOR_ENABLED", "false").lower() == "true",
        "slack_webhook": get_env("SLACK_WEBHOOK", ""),
        "feishu_webhook": get_env("FEISHU_WEBHOOK", ""),
        "notify_on_success": get_env("MONITOR_SUCCESS", "true").lower() == "true",
        "notify_on_error": get_env("MONITOR_ERROR", "true").lower() == "true"
    }


def get_rag_config() -> Dict:
    """获取 RAG 配置"""
    load_env()
    
    return {
        "enabled": get_env("RAG_ENABLED", "false").lower() == "true",
        "max_articles": int(get_env("RAG_MAX_ARTICLES", "100")),
        "context_chars": int(get_env("RAG_CONTEXT_CHARS", "2000"))
    }


def get_api_config() -> Dict:
    """获取 API 配置"""
    load_env()
    
    return {
        "enabled": get_env("API_ENABLED", "false").lower() == "true",
        "port": int(get_env("API_PORT", "5001")),
        "auth_token": get_env("API_TOKEN", ""),
        "cors_origins": get_env("API_CORS", "*").split(",")
    }


def validate_config() -> Dict:
    """验证配置完整性"""
    load_env()
    
    issues = []
    
    if not get_env("OPENAI_API_KEY", ""):
        issues.append("OPENAI_API_KEY 未设置")
    
    wechat = get_wechat_config()
    if wechat.get("app_id") == "your_app_id_here":
        issues.append("微信公众号 AppID 未配置")
    
    monitoring = get_monitoring_config()
    if monitoring.get("enabled") and not (monitoring.get("slack_webhook") or monitoring.get("feishu_webhook")):
        issues.append("监控已启用但未配置通知渠道")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues
    }


def print_config_status():
    """打印配置状态"""
    load_env()
    
    print("\n" + "="*50)
    print("📋 Configuration Status")
    print("="*50)
    
    wechat = get_wechat_config()
    print(f"\n📱 WeChat: {'✅ Configured' if wechat['app_id'] else '❌ Not configured'}")
    
    openai = get_openai_config()
    print(f"🤖 OpenAI: {'✅ Configured' if openai['api_key'] else '❌ Not configured'}")
    
    wecom = get_wecom_config()
    print(f"💼 WeCom: {'✅ Configured' if wecom['corp_id'] else '⚪ Optional'}")
    
    dingtalk = get_dingtalk_config()
    print(f"🔔 DingTalk: {'✅ Configured' if dingtalk['webhook'] else '⚪ Optional'}")
    
    email = get_email_config()
    print(f"📧 Email: {'✅ Configured' if email['username'] else '⚪ Optional'}")
    
    monitoring = get_monitoring_config()
    print(f"🔍 Monitoring: {'✅ Enabled' if monitoring['enabled'] else '⚪ Disabled'}")
    
    api = get_api_config()
    print(f"🌐 API: {'✅ Enabled' if api['enabled'] else '⚪ Disabled'}")
    
    validation = validate_config()
    print(f"\n{'✅' if validation['valid'] else '❌'} Overall: {'Ready' if validation['valid'] else 'Issues found'}")
    
    if validation['issues']:
        print("\n⚠️  Issues:")
        for issue in validation['issues']:
            print(f"  - {issue}")
    
    print("="*50 + "\n")


if __name__ == "__main__":
    print_config_status()
