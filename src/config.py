import os
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = PROJECT_ROOT / ".env"
_ENV_LOADED = False


# 环境变量 → (yaml 段, 键)。仅当环境变量非空时覆盖 yaml 值。
# 优先级: 进程环境变量 > .env > config.yaml
_ENV_OVERRIDES = {
    # 微信公众号
    "WECHAT_APP_ID": ("wechat", "app_id"),
    "WECHAT_APP_SECRET": ("wechat", "app_secret"),
    # LLM 提供商（密钥一律外置，yaml 中只留占位）
    "OPENAI_API_KEY": ("openai", "api_key"),
    "OPENAI_MODEL": ("openai", "model"),
    "OPENROUTER_API_KEY": ("openrouter", "api_key"),
    "OPENROUTER_MODEL": ("openrouter", "model"),
    "DEEPSEEK_API_KEY": ("deepseek", "api_key"),
    "ZHIPU_API_KEY": ("zhipu", "api_key"),
    "SILICONFLOW_API_KEY": ("siliconflow", "api_key"),
    "AGNES_API_KEY": ("agnes", "api_key"),
    # 图片 API
    "PEXELS_API_KEY": ("free_image", "pexels"),
    "ZIMAGE_API_KEY": ("zimage", "api_key"),
    # 搜索（EXA 在 fetcher/validate_config 中直接读 os.environ，此处仅保证 .env 能生效）
    "EXA_API_KEY": None,
    "DASHSCOPE_API_KEY": None,
}


def _load_env_file():
    """加载项目根目录的 .env 到 os.environ（不覆盖已存在的进程环境变量）。"""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    if not _ENV_FILE.is_file():
        return

    # 优先使用 python-dotenv；缺失时退化为简易解析（仅 KEY=VALUE 行）
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_FILE, override=False)
        return
    except ImportError:
        pass

    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _apply_env_overrides(config: dict) -> dict:
    """将环境变量合并进 config，避免在 yaml 里存放明文密钥。"""
    if not isinstance(config, dict):
        return {}
    for env_var, mapping in _ENV_OVERRIDES.items():
        value = os.environ.get(env_var, "").strip()
        if not value:
            continue
        if mapping is None:
            continue  # 该变量没有 yaml 映射，仅供直接读 env 的模块使用
        section, key = mapping
        config.setdefault(section, {})[key] = value
    return config


def load_config(config_path: str = "config.yaml") -> dict:
    _load_env_file()

    if config_path is None:
        config_path = str(PROJECT_ROOT / "config.yaml")

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    return _apply_env_overrides(config)


def get_wechat_config(config: dict) -> dict:
    return config.get("wechat", {})

def get_openai_config(config: dict) -> dict:
    return config.get("openai", {})

def get_openrouter_config(config: dict) -> dict:
    """获取OpenRouter配置"""
    return config.get("openrouter", {})


def get_news_config(config: dict) -> dict:
    return config.get("news", {})


def get_publish_config(config: dict) -> dict:
    return config.get("publish", {})


def get_scheduler_config(config: dict) -> dict:
    return config.get("scheduler", {})


def get_llm_config(config: dict) -> dict:
    """获取LLM配置"""
    return config.get("llm", {})


def get_deepseek_config(config: dict) -> dict:
    """获取DeepSeek配置"""
    return config.get("deepseek", {})


def get_zhipu_config(config: dict) -> dict:
    """获取智谱AI配置"""
    return config.get("zhipu", {})


def get_siliconflow_config(config: dict) -> dict:
    """获取SiliconFlow配置"""
    return config.get("siliconflow", {})


def get_agnes_config(config: dict) -> dict:
    """获取 Agnes (Sapiens AI) 配置"""
    return config.get("agnes", {})


def get_free_image_config(config: dict) -> dict:
    """获取免费图片 API 配置"""
    return config.get("free_image", {})
