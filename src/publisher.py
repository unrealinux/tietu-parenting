"""
WeChat Publisher - 微信公众号发布模块

支持 Markdown 转 HTML、草稿创建、自动发布
参考 feiqingqiWechatMP 优化，集成代理支持和配置验证
"""

import os
import json
import re
import logging
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from src.config import load_config, get_wechat_config, get_publish_config
from src.proxy import get_requests_proxy, is_proxy_enabled
from src.validate_config import validate_config, ValidationErrorType
from src.errors import with_retry, AppError, ErrorType
from src.health import inc_published, inc_publish_failure

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class LiveWriteBlockedInTest(RuntimeError):
    """测试进程里尝试写线上账号（建/删草稿、群发）时抛出。"""


def _assert_not_in_test_context(action: str) -> None:
    """测试进程绝不允许写线上账号。

    AGENTS.md 红线：“不要把公众号草稿箱当测试场”。
    历史上 tests/test_main.py::TestScheduler::test_run_once_returns_bool
    直接调用了真实的 run_once()，而 run_once() 会一路走到 create_draft()——
    结果是每跑一次 pytest 就往草稿箱里塞一篇真实草稿（已证实：
    01:33:13 / 01:42:48 / 14:44 的草稿均与 pytest 运行时刻一一对应）。

    pytest 在每个用例执行期间会设置 PYTEST_CURRENT_TEST，据此直接拒绝，
    避免以后任何人再写出“顺手就发了”的测试。生产链路（定时任务 / CLI）
    不带该变量，行为完全不变。
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("ALLOW_LIVE_WECHAT_IN_TEST"):
        raise LiveWriteBlockedInTest(
            f"拒绝在测试进程中执行线上写操作：{action}。"
            "测试请 mock 掉发布层；确需联调请显式设 ALLOW_LIVE_WECHAT_IN_TEST=1。"
        )


class WeChatPublisher:
    """微信公众号发布器"""
    
    def __init__(self):
        config = load_config()
        wechat_config = get_wechat_config(config)
        publish_config = get_publish_config(config)
        
        self.app_id = wechat_config.get("app_id", "")
        self.app_secret = wechat_config.get("app_secret", "")
        self.author = publish_config.get("author", "育儿观察")
        self.default_cover = publish_config.get("default_cover", "")
        self.default_digest = publish_config.get("default_digest", "")
        
        self.access_token = None
        self.token_expires_at = 0
        # 命中权限类错误时记下 errcode，本轮不再逐张重试
        self._last_permanent_error = 0
        
        # 代理配置
        self.proxies = get_requests_proxy()
        self.use_proxy = is_proxy_enabled()
        
        # 配置验证
        self._validate_config()
        
        # 健康监控
        self._health_checker = None
        try:
            import src.health as health_module
            self._health_checker = health_module.get_health_checker()
        except (ImportError, AttributeError):
            pass
    
    def _validate_config(self):
        """验证配置"""
        validation_result = validate_config(load_config())
        
        if not validation_result["valid"]:
            logger.warning(f"配置验证失败: {validation_result['error_count']} 个错误")
            for error in validation_result["errors"]:
                if error.field.startswith("wechat"):
                    logger.error(f"微信配置错误: {error.message}")
        
        if validation_result["warnings"]:
            for warning in validation_result["warnings"]:
                logger.info(f"配置警告: {warning.message}")
    
    def get_access_token(self) -> Optional[str]:
        """获取访问令牌（带缓存和重试）"""
        if self.access_token and time.time() < self.token_expires_at:
            return self.access_token
        
        url = "https://api.weixin.qq.com/cgi-bin/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret
        }
        
        @with_retry(max_retries=2, delay=1.0)
        def _fetch_token():
            proxies = self.proxies if self.use_proxy else {}
            
            response = requests.get(url, params=params, timeout=10, proxies=proxies)
            data = response.json()
            
            if "access_token" in data:
                return data
            else:
                error_msg = data.get("errmsg", "Unknown error")
                error_code = data.get("errcode", -1)
                raise AppError(
                    f"获取 access_token 失败: {error_msg}",
                    error_type=ErrorType.AUTH,
                    context={"error_code": error_code}
                )
        
        try:
            data = _fetch_token()
            self.access_token = data["access_token"]
            expires_in = data.get("expires_in", 7200)
            self.token_expires_at = time.time() + expires_in - 300
            logger.info("Access token refreshed")
            return self.access_token
        except AppError as e:
            logger.error(f"获取 access_token 失败: {e}")
            return None
        except Exception as e:
            logger.error(f"获取 access_token 异常: {e}")
            return None
    
    def _clean_emoji(self, text: str) -> str:
        """移除emoji和特殊Unicode字符，避免微信API编码问题"""
        import re
        # 简单可靠方法：只保留安全字符
        safe = []
        for c in text:
            code = ord(c)
            # 保留ASCII打印字符(32-126)
            if 32 <= code <= 126:
                safe.append(c)
            # 保留中文字符(0x4e00-0x9fff)
            elif 0x4e00 <= code <= 0x9fff:
                safe.append(c)
            # 保留换行回车
            elif code in (10, 13):
                safe.append(c)
            # 保留基本标点
            elif c in '，。！？、；：「」『』…—"\'()[]{}，.! ':
                safe.append(c)
            # 其他字符（emoji等）用空格替换
            else:
                if not safe or safe[-1] != ' ':
                    safe.append(' ')
        
        result = ''.join(safe)
        # 清理多余空格
        return re.sub(r' +', ' ', result).strip()
    
    def create_draft(self, title: str, content: str, author: str = "", 
                    digest: str = "", cover_path: str = "",
                    cover_media_id: str = "") -> Optional[str]:
        """创建草稿（带代理支持和重试）
        
        Args:
            cover_media_id: 预上传的封面media_id（优先于cover_path）
        """
        _assert_not_in_test_context("create_draft（创建草稿）")
        token = self.get_access_token()
        if not token:
            logger.error("Failed to get access token")
            return None
        
        # 清理emoji和特殊字符，避免微信API编码问题
        title = self._clean_emoji(title)
        content = self._clean_emoji(content)
        
        # 移除表格图片标记（不应该出现在最终内容中）
        content = content.replace('@table_image@', '').strip()
        # 清理可能产生的多余空行
        import re
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        # 记录标题和作者长度，用于调试
        final_author = author or self.author
        logger.info(f"Creating draft with title: '{title}' (length: {len(title)})")
        logger.info(f"Creating draft with author: '{final_author}' (length: {len(final_author)})")
        
        article = {
            "title": title,
            "author": final_author,
            "content": content,
            "digest": self._clean_emoji(digest or self.default_digest),
            "content_source_url": "",
            "need_open_comment": 0,
            "only_fans_can_comment": 0
        }
        
        # 处理封面图（可选，失败不阻断）
        thumb_media_id = None
        if cover_media_id:
            thumb_media_id = cover_media_id
            logger.info(f"使用预上传封面: {cover_media_id}")
        elif cover_path and os.path.exists(cover_path):
            try:
                media_id = self._upload_media(cover_path, "image")
                if media_id:
                    thumb_media_id = media_id
                    logger.info(f"封面图已上传: {media_id}")
                else:
                    logger.warning("封面图上传失败，将使用默认封面")
            except Exception as e:
                logger.warning(f"封面图上传异常: {e}，将使用默认封面")
        
        # 如果没有封面图，尝试上传一个默认封面（1x1像素PNG）
        if not thumb_media_id:
            try:
                import io
                from PIL import Image
                img = Image.new('RGB', (900, 500), color='#4a90d9')
                img_io = io.BytesIO()
                img.save(img_io, 'PNG')
                img_io.seek(0)
                
                # 临时保存并上传
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    tmp.write(img_io.getvalue())
                    tmp_path = tmp.name
                
                default_media_id = self._upload_media(tmp_path, "image")
                os.unlink(tmp_path)  # 删除临时文件
                
                if default_media_id:
                    thumb_media_id = default_media_id
                    logger.info(f"默认封面已上传: {default_media_id}")
                else:
                    logger.error("无法上传默认封面，草稿创建可能失败")
            except ImportError:
                logger.warning("未安装Pillow，无法生成默认封面")
            except Exception as e:
                logger.error(f"生成默认封面失败: {e}")
        
        # 设置封面图（如果有）
        if thumb_media_id:
            article["thumb_media_id"] = thumb_media_id
            article["thumb_media"] = thumb_media_id
        
        url = "https://api.weixin.qq.com/cgi-bin/draft/add"
        params = {"access_token": token}
        
        try:
            media_id = self._post_draft_with_guard(url, params, article)
            if media_id:
                logger.info(f"Draft created: {media_id}")
                if self._health_checker:
                    self._health_checker.inc_published()
                return media_id
            else:
                if self._health_checker:
                    self._health_checker.inc_publish_failure()
                return None
        except AppError as e:
            logger.error(f"创建草稿失败: {e}")
            if self._health_checker:
                self._health_checker.inc_publish_failure()
            return None
        except Exception as e:
            logger.error(f"创建草稿异常: {e}")
            if self._health_checker:
                self._health_checker.inc_publish_failure()
            return None
    
    def find_draft_by_title(self, title: str, pages: int = 2) -> Optional[str]:
        """按标题在草稿箱里找 media_id（draft/add 重试防重复用）。

        draft/add 不是幂等接口：服务端已经建成功、但响应超时，盲目重试就会
        再建一条同标题重复草稿。线上出现过两次（其中一条正文图全无），
        所以重试前必须先查一次草稿箱。
        """
        want = (title or "").strip()
        if not want:
            return None
        for i in range(max(1, pages)):
            for t, mid in self.list_drafts(offset=i * 20, count=20):
                if t.strip() == want:
                    return mid
        return None

    def _post_draft_with_guard(self, url: str, params: dict, article: dict) -> str:
        """POST 建草稿；每次重试前先查草稿箱，避免超时重试造成重复草稿。"""
        body = json.dumps({"articles": [article]}, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=utf-8"}
        proxies = self.proxies if self.use_proxy else {}
        delay = 2.0

        for attempt in range(3):
            try:
                response = requests.post(url, params=params, data=body,
                                         headers=headers, timeout=30, proxies=proxies)
                data = response.json()
                if "media_id" in data:
                    return data["media_id"]
                raise AppError(
                    f"创建草稿失败: {data.get('errmsg', data)}",
                    error_type=ErrorType.SYSTEM,
                    context={"error_code": data.get("errcode", -1)},
                )
            except Exception as e:
                if attempt == 2:
                    raise
                existing = self.find_draft_by_title(article.get("title", ""))
                if existing:
                    logger.warning(f"上次请求可能已建成功，复用现有草稿 {existing}，不再重发")
                    return existing
                logger.warning(f"建草稿失败，{delay:.0f}s 后重试: {e}")
                time.sleep(delay)
                delay *= 2
        raise AppError("创建草稿失败", error_type=ErrorType.SYSTEM)

    def create_image_draft(self, title: str, content: str, image_paths: List[str],
                           need_open_comment: int = 1,
                           only_fans_can_comment: int = 0) -> Optional[str]:
        """创建「图片消息」草稿（贴图号形式，不群发）。

        贴图号 = 微信图片消息（article_type=newspic）：多张图 + 一段短文案。
        每张图先传永久素材拿 media_id，再整体建草稿。
        上限 20 张图；title 最长 64 字。
        """
        _assert_not_in_test_context("create_image_draft（创建图片消息草稿）")
        token = self.get_access_token()
        if not token:
            logger.error("无法获取 access_token，图片草稿中止")
            return None
        if not image_paths:
            logger.error("图片消息至少需要 1 张图")
            return None
        if len(image_paths) > 20:
            logger.error(f"图片消息最多 20 张图，当前 {len(image_paths)} 张")
            return None

        image_list = []
        for p in image_paths:
            if not os.path.exists(p):
                logger.error(f"图片不存在，草稿中止: {p}")
                return None
            mid = self._upload_media_with_backoff(p)
            if not mid:
                logger.error(f"图片上传失败，草稿中止: {p}")
                return None
            image_list.append({"image_media_id": mid})
            # 永久素材接口有频控，连传多张会被断链（RemoteDisconnected）
            time.sleep(2)

        article = {
            "article_type": "newspic",
            "title": self._clean_emoji(title)[:64],
            "content": self._clean_emoji(content),
            "need_open_comment": need_open_comment,
            "only_fans_can_comment": only_fans_can_comment,
            "image_info": {"image_list": image_list},
        }

        url = "https://api.weixin.qq.com/cgi-bin/draft/add"
        params = {"access_token": token}

        try:
            media_id = self._post_draft_with_guard(url, params, article)
            logger.info(f"图片草稿已创建: {media_id}")
            if self._health_checker:
                self._health_checker.inc_published()
            return media_id
        except Exception as e:
            logger.error(f"创建图片草稿异常: {e}")
            if self._health_checker:
                self._health_checker.inc_publish_failure()
            return None

    # 权限类错误重试没意义（每次失败还要等退避），命中就直接放弃这一轮
    _PERMANENT_ERRCODES = (48001, 40164, 40007, 45003, 45009)

    def _upload_media_with_backoff(self, file_path: str, attempts: int = 4) -> Optional[str]:
        """上传单张永久素材，对 ConnectError / RemoteDisconnected 退避重试。

        微信「新增永久素材」有频控，连续快速上传会被服务端直接断开连接。
        但 48001/40164 属于账号权限问题，重试只会白白等三次退避。
        """
        if self._last_permanent_error:
            logger.error(
                f"账号权限错误已确认（{self._last_permanent_error}），本批上传中止，不再逐张重试"
            )
            return None
        delay = 3.0
        for i in range(1, attempts + 1):
            mid = self._upload_media(file_path, "image")
            if mid:
                return mid
            if self._last_permanent_error:
                return None
            if i < attempts:
                logger.warning(f"第 {i} 次上传失败，{delay:.0f}s 后重试: {file_path}")
                time.sleep(delay)
                delay *= 2
        return None

    def update_draft_cover(self, media_id: str, thumb_media_id: str) -> bool:
        """更新草稿封面图"""
        _assert_not_in_test_context("update_draft_cover（改草稿）")
        token = self.get_access_token()
        if not token:
            return False
        url = "https://api.weixin.qq.com/cgi-bin/draft/update"
        params = {"access_token": token}
        payload = {
            "media_id": media_id,
            "index": 0,
            "articles": {
                "thumb_media_id": thumb_media_id,
            }
        }
        try:
            proxies = self.proxies if self.use_proxy else {}
            resp = requests.post(url, params=params, json=payload,
                               timeout=15, proxies=proxies)
            data = resp.json()
            if data.get("errcode", -1) == 0:
                logger.info(f"Draft cover updated: {media_id}")
                return True
            else:
                logger.error(f"Update draft cover failed: {data}")
                return False
        except Exception as e:
            logger.error(f"Error updating draft cover: {e}")
            return False

    def _upload_media(self, file_path: str, media_type: str = "image") -> Optional[str]:
        """上传媒体文件到永久素材（带重试）

        注意：这会向账号永久素材库真实写入，测试进程内一并拒绝。
        """
        _assert_not_in_test_context("_upload_media（上传永久素材）")
        token = self.get_access_token()
        if not token:
            return None
        
        # 微信草稿箱需要永久素材的media_id，使用material/add_material接口
        url = f"https://api.weixin.qq.com/cgi-bin/material/add_material"
        params = {"access_token": token, "type": media_type}
        
        @with_retry(max_retries=2, delay=1.0)
        def _upload():
            proxies = self.proxies if self.use_proxy else {}
            with open(file_path, 'rb') as f:
                files = {'media': f}
                response = requests.post(url, params=params, files=files, 
                                 timeout=30, proxies=proxies)
            data = response.json()
            if "media_id" in data:
                logger.info(f"永久素材上传成功: {data['media_id']}")
                return data["media_id"]
            else:
                code = data.get("errcode", -1)
                error_msg = data.get("errmsg", "Unknown error")
                if code == 48001:
                    self._last_permanent_error = 48001
                    error_msg += (
                        "（该账号无素材接口权限。多为未完成微信认证："
                        "认证后才有 material/add_material、draft/add、发布接口。"
                        "去后台「设置与开发 → 接口权限」核对。）"
                    )
                elif code == 40164:
                    self._last_permanent_error = 40164
                    error_msg += "（IP 不在白名单，去后台「基本配置 → IP 白名单」加本机公网 IP）"
                raise AppError(f"上传永久素材失败: {error_msg}")
        
        try:
            return _upload()
        except Exception as e:
            logger.error(f"Error uploading media: {e}")
            return None
    
    def _upload_article_image(self, file_path: str) -> Optional[str]:
        """上传文章配图，返回可嵌入内容的URL"""
        token = self.get_access_token()
        if not token:
            return None
        
        url = "https://api.weixin.qq.com/cgi-bin/media/uploadimg"
        params = {"access_token": token}
        
        @with_retry(max_retries=2, delay=1.0)
        def _upload():
            proxies = self.proxies if self.use_proxy else {}
            with open(file_path, 'rb') as f:
                files = {'media': f}
                response = requests.post(url, params=params, files=files,
                                 timeout=60, proxies=proxies)
            data = response.json()
            if "url" in data:
                return data["url"]
            else:
                error_msg = data.get("errmsg", "Unknown error")
                raise AppError(f"上传文章图片失败: {error_msg}")
        
        try:
            return _upload()
        except Exception as e:
            logger.error(f"Error uploading article image: {e}")
            return None

    def markdown_to_html(self, markdown_text: str) -> str:
        """Markdown 转 HTML（微信公众号兼容，增强排版）"""
        html = markdown_text
        
        # ===== 处理特殊元素：提示框 =====
        def convert_info_boxes(html_text):
            patterns = {
                r':::info\s*\n(.*?):::': r'<div style="background: #e8f4fd; border-left: 4px solid #3498db; padding: 15px 20px; margin: 20px 0; border-radius: 0 8px 8px 0; line-height: 1.8;"><div style="font-weight: 600; color: #3498db; margin-bottom: 8px;">💡 提示</div>\1</div>',
                r':::warning\s*\n(.*?):::': r'<div style="background: #fff3cd; border-left: 4px solid #f39c12; padding: 15px 20px; margin: 20px 0; border-radius: 0 8px 8px 0; line-height: 1.8;"><div style="font-weight: 600; color: #f39c12; margin-bottom: 8px;">⚠️ 注意</div>\1</div>',
                r':::tip\s*\n(.*?):::': r'<div style="background: #d4edda; border-left: 4px solid #28a745; padding: 15px 20px; margin: 20px 0; border-radius: 0 8px 8px 0; line-height: 1.8;"><div style="font-weight: 600; color: #28a745; margin-bottom: 8px;">💎 技巧</div>\1</div>',
                r':::success\s*\n(.*?):::': r'<div style="background: #d1ecf1; border-left: 4px solid #17a2b8; padding: 15px 20px; margin: 20px 0; border-radius: 0 8px 8px 0; line-height: 1.8;"><div style="font-weight: 600; color: #17a2b8; margin-bottom: 8px;">✅ 成功</div>\1</div>'
            }
            for pattern, replacement in patterns.items():
                html_text = re.sub(pattern, replacement, html_text, flags=re.DOTALL)
            return html_text
        
        html = convert_info_boxes(html)
        
        # ===== 处理评分星级 =====
        html = re.sub(r'\[rating:\s*([\d.]+)\]', 
                      lambda m: f'<span style="color: #f39c12;">{"★" * int(float(m.group(1))) + "☆" * (5 - int(float(m.group(1))))}</span>', 
                      html)
        html = re.sub(r'\[评分:\s*([★☆]+)\]', r'<span style="color: #f39c12;">\1</span>', html)
        
        # ===== 标题样式（更好的视觉层次）=====
        # h3: 小标题
        html = re.sub(r'^### (.*?)$', 
                      r'<h3 style="font-size: 18px; color: #2c3e50; margin: 28px 0 18px; font-weight: 600; line-height: 1.6; display: flex; align-items: center;"><span style="background: #3498db; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 14px; margin-right: 10px;">→</span>\1</h3>', 
                      html, flags=re.MULTILINE)
        
        # h2: 中标题 - 带渐变左边框和背景
        html = re.sub(r'^## (.*?)$', 
                      r'<h2 style="font-size: 22px; color: #2c3e50; margin: 40px 0 22px; padding: 12px 18px; border-left: 5px solid #3498db; background: linear-gradient(to right, #ebf5fb, transparent); line-height: 1.6; border-radius: 0 8px 8px 0;">\1</h2>', 
                      html, flags=re.MULTILINE)
        
        # h1: 大标题 - 居中显示
        html = re.sub(r'^# (.*?)$', 
                      r'<h1 style="font-size: 26px; color: #1a1a1a; margin: 45px 0 30px; text-align: center; font-weight: 700; line-height: 1.4; padding-bottom: 15px; border-bottom: 3px solid #3498db;">\1</h1>', 
                      html, flags=re.MULTILINE)
        
        # ===== 加粗和斜体 =====
        html = re.sub(r'\*\*(.*?)\*\*', r'<strong style="font-weight: 600; color: #2c3e50;">\1</strong>', html)
        html = re.sub(r'\*(.*?)\*', r'<em style="color: #7f8c8d; font-style: italic;">\1</em>', html)
        
        # ===== 链接（微信友好的样式）=====
        html = re.sub(r'\[(.*?)\]\((.*?)\)', 
                      r'<a href="\2" style="color: #3498db; text-decoration: none; border-bottom: 2px solid #3498db; padding-bottom: 2px;">\1</a>', 
                      html)
        
        # ===== 引用块（更美观的样式）=====
        html = re.sub(r'^> (.*?)$', 
                      r'<blockquote style="background: #f8f9fa; border-left: 4px solid #3498db; padding: 18px 22px; margin: 25px 0; color: #555; font-style: normal; line-height: 1.9; border-radius: 0 10px 10px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.05);">\1</blockquote>', 
                      html, flags=re.MULTILINE)
        
        # ===== 分隔线（更精致的样式）=====
        html = re.sub(r'^---$', 
                      r'<hr style="border: none; height: 2px; background: linear-gradient(to right, transparent, #3498db, transparent); margin: 45px 0;">', 
                      html, flags=re.MULTILINE)
        
        # ===== 列表项（更好的样式）=====
        # 无序列表
        html = re.sub(r'^[-*] (.*?)$', 
                      r'<div style="margin: 10px 0; padding-left: 28px; position: relative; line-height: 1.8;"><span style="position: absolute; left: 0; color: #3498db; font-size: 18px;">•</span>\1</div>', 
                      html, flags=re.MULTILINE)
        
        # 有序列表 (数字)
        html = re.sub(r'^(\d+)\. (.*?)$', 
                      r'<div style="margin: 10px 0; padding-left: 28px; position: relative; line-height: 1.8;"><span style="position: absolute; left: 0; background: #3498db; color: #fff; width: 20px; height: 20px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600;">\1</span>\2</div>', 
                      html, flags=re.MULTILINE)
        
        # ===== 表格处理：极简版 - 微信兼容 =====
        def convert_tables(html_text):
            lines = html_text.split('\n')
            result = []
            table_rows = []
            in_table = False
            
            for line in lines:
                stripped = line.strip()
                
                # 检测表格行
                if stripped.startswith('|') and stripped.endswith('|') and stripped.count('|') >= 3:
                    table_rows.append(stripped)
                    in_table = True
                else:
                    if in_table and table_rows:
                        # 处理表格
                        if len(table_rows) >= 2:
                            table_html = build_html_table(table_rows)
                            result.append(table_html)
                        else:
                            result.append('\n'.join(table_rows))
                        table_rows = []
                        in_table = False
                    result.append(line)
            
            # 处理末尾的表格
            if table_rows:
                if len(table_rows) >= 2:
                    table_html = build_html_table(table_rows)
                    result.append(table_html)
                else:
                    result.append('\n'.join(table_rows))
            
            return '\n'.join(result)
        
        def build_html_table(rows):
            if len(rows) < 2:
                return '\n'.join(rows)
            
            # 解析表头（第一行）
            first_row = rows[0].strip()
            if not (first_row.startswith('|') and first_row.endswith('|')):
                return '\n'.join(rows)
            
            headers = [c.strip() for c in first_row.split('|')[1:-1]]
            col_count = len(headers)
            
            if col_count == 0:
                return '\n'.join(rows)
            
            # 生成HTML表格 - 极简版，微信兼容
            html = ['<table style="width:100%;border-collapse:collapse;border:1px solid #4a90d9;font-size:14px;">']
            html.append('<thead style="background:#4a90d9;color:#fff;">')
            html.append('<tr>')
            for h in headers:
                html.append(f'<th style="padding:10px 8px;text-align:center;font-weight:600;border:1px solid #ddd;">{h}</th>')
            html.append('</tr>')
            html.append('</thead>')
            html.append('<tbody>')
            
            # 数据行（从第二行开始，跳过分隔线）
            for row_idx, row in enumerate(rows[1:], 1):
                stripped = row.strip()
                if not (stripped.startswith('|') and stripped.endswith('|')):
                    continue
                # 跳过分隔线
                content = stripped.replace('|', ' ').strip()
                is_sep = False
                if content:
                    clean = content.replace('-', '').replace(':', '').replace(' ', '')
                    if clean == '' and len(content) >= 2:
                        is_sep = True
                if is_sep:
                    continue
                
                cells = [c.strip() for c in stripped.split('|')[1:-1]]
                if len(cells) != col_count:
                    continue
                
                bg = '#f9f9f9' if row_idx % 2 == 0 else '#fff'
                html.append(f'<tr style="background:{bg};">')
                for cell in cells:
                    html.append(f'<td style="padding:8px 6px;text-align:center;border:1px solid #ddd;font-size:13px;">{cell}</td>')
                html.append('</tr>')
            
            html.append('</tbody>')
            html.append('</table>')
            
            return '\n'.join(html)
        
        html = convert_tables(html)
        
        # ===== 段落处理 =====
        html = re.sub(r'\n\n', r'</p><p style="margin: 20px 0; line-height: 2; font-size: 16px; color: #333;">', html)
        html = '<p style="margin: 20px 0; line-height: 2; font-size: 16px; color: #333;">' + html + '</p>'
        
        # ===== 清理空段落 =====
        html = re.sub(r'<p style="[^"]*"></p>', r'', html)
        html = re.sub(r'<p style="[^"]*">(\s*<h[123])', r'\1', html)
        html = re.sub(r'(</h[123]>)\s*</p>', r'\1', html)
        html = re.sub(r'<p style="[^"]*">(\s*<hr)', r'\1', html)
        html = re.sub(r'(</hr>)\s*</p>', r'\1', html)
        html = re.sub(r'<p style="[^"]*">(\s*<blockquote)', r'\1', html)
        html = re.sub(r'(</blockquote>)\s*</p>', r'\1', html)
        html = re.sub(r'<p style="[^"]*">(\s*<div)', r'\1', html)
        html = re.sub(r'(</div>)\s*</p>', r'\1', html)
        
        return html
    
    def export_html(self, content: str, title: str, output_dir: str = "output",
                    content_is_html: bool = False) -> str:
        """导出为完整的 HTML 文件（预览用）。

        content_is_html=True 时 content 已是渲染好的微信 HTML（如 editorial_template
        的产出），不再做 Markdown 转换，直接包一层预览外壳。
        """
        import os
        os.makedirs(output_dir, exist_ok=True)
        
        today = datetime.now().strftime("%Y%m%d")
        filename = f"{output_dir}/article_{today}.html"
        
        html_content = content if content_is_html else self.markdown_to_html(content)
        
        full_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif; max-width: 677px; margin: 0 auto; padding: 20px; color: #333; background-color: #f5f7fa; }}
        h1, h2, h3 {{ margin: 20px 0; }}
        p {{ line-height: 1.8; margin: 15px 0; }}
        a {{ color: #1a73e8; }}
        blockquote {{ border-left: 3px solid #ddd; padding-left: 15px; color: #666; }}
        hr {{ border: none; border-top: 1px solid #eee; margin: 30px 0; }}
    </style>
</head>
<body>
<div style="background: #fff; border-radius: 12px; padding: 25px 30px; box-shadow: 0 2px 15px rgba(0,0,0,0.08); margin: 20px 0;">
{html_content}
</div>
</body>
</html>"""
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(full_html)
        
        logger.info(f"HTML exported: {filename}")
        return filename
    
    def list_drafts(self, offset: int = 0, count: int = 20) -> list:
        """获取草稿列表，返回 [(title, media_id), ...]

        注意：draft/batchget 的标题在 content.news_item[0].title，不在 content.title
        （后者恒为缺失，早期版本读错键导致所有草稿都显示“(无标题)”）。
        """
        token = self.get_access_token()
        if not token:
            return []
        url = "https://api.weixin.qq.com/cgi-bin/draft/batchget"
        params = {"access_token": token}
        try:
            proxies = self.proxies if self.use_proxy else {}
            response = requests.post(
                url, params=params,
                json={"offset": offset, "count": count, "no_content": 0},
                timeout=30, proxies=proxies
            )
            # 微信此接口返回 text/plain 且不带 charset，requests 会按 ISO-8859-1
            # 解码，中文标题会变乱码；显式按 UTF-8 解码。
            response.encoding = "utf-8"
            data = response.json()
            items = data.get("item", [])
            result = []
            for it in items:
                m = it.get("media_id", "")
                c = it.get("content", {}) or {}
                news = c.get("news_item") or []
                first = news[0] if news else {}
                t = (first.get("title") or c.get("title") or "(无标题)").strip()
                result.append((t, m))
            return result
        except Exception as e:
            logger.error(f"列举草稿失败: {e}")
            return []

    def delete_draft(self, media_id: str) -> bool:
        """删除指定草稿"""
        _assert_not_in_test_context("delete_draft（删除草稿）")
        token = self.get_access_token()
        if not token or not media_id:
            return False
        url = "https://api.weixin.qq.com/cgi-bin/draft/delete"
        params = {"access_token": token}
        try:
            proxies = self.proxies if self.use_proxy else {}
            response = requests.post(
                url, params=params,
                json={"media_id": media_id},
                timeout=30, proxies=proxies
            )
            data = response.json()
            if data.get("errcode", 0) == 0:
                return True
            logger.error(f"删除草稿失败: {data.get('errmsg')}")
            return False
        except Exception as e:
            logger.error(f"删除草稿异常: {e}")
            return False

    # 「发布」≠「群发」：
    #   - 发布(cgi-bin/draft/publish 或 freepublish/submit)：进公众号主页 + 推荐流，
    #     不推通知给粉丝，**不占群发次数**。贴图号走这条。
    #   - 群发(cgi-bin/message/mass/sendall)：推通知给粉丝，服务号每月 4 次。
    # 两者都必须是账号已认证、且 IP 在白名单，否则报 48001 / 40164。

    def probe_publish_permission(self) -> tuple[bool, str]:
        """只读探测「发布」接口权限，不发任何东西。

        用 freepublish/batchget（拉已发布列表）判断：返回 48001 = 无权限。
        返回 (是否有权限, 说明文本)。
        """
        token = self.get_access_token()
        if not token:
            return False, "拿不到 access_token，先查 app_id/app_secret 与 IP 白名单"
        try:
            response = requests.post(
                "https://api.weixin.qq.com/cgi-bin/freepublish/batchget",
                params={"access_token": token},
                json={"offset": 0, "count": 1, "no_content": 1},
                timeout=30,
                proxies=self.proxies if self.use_proxy else {},
            )
            data = response.json()
        except Exception as e:
            return False, f"请求异常: {e}"

        code = data.get("errcode", 0)
        if code == 0:
            return True, f"有发布权限，线上已发布 {data.get('total_count', 0)} 条"
        if code == 48001:
            return False, "48001 该账号无发布接口权限（服务号需完成认证）"
        if code == 40164:
            return False, "40164 IP 不在白名单，去后台「基本配置 → IP 白名单」加本机公网 IP"
        return False, f"errcode={code} {data.get('errmsg', '')}"

    def list_published(self, offset: int = 0, count: int = 20) -> list:
        """拉已发布列表，返回 [(标题, article_id, 发布时间戳)]。"""
        token = self.get_access_token()
        if not token:
            return []
        try:
            response = requests.post(
                "https://api.weixin.qq.com/cgi-bin/freepublish/batchget",
                params={"access_token": token},
                json={"offset": offset, "count": count, "no_content": 1},
                timeout=30,
                proxies=self.proxies if self.use_proxy else {},
            )
            data = response.json()
        except Exception as e:
            logger.error(f"拉取已发布列表异常: {e}")
            return []
        if data.get("errcode", 0) != 0:
            logger.error(f"拉取已发布列表失败: {data.get('errmsg')}")
            return []
        out = []
        for item in data.get("item", []):
            news = (item.get("content") or {}).get("news_item") or [{}]
            out.append((news[0].get("title", ""), item.get("article_id", ""), item.get("update_time", 0)))
        return out

    def get_publish_status(self, publish_id: str) -> dict:
        """查发布任务状态（发布是异步的，publish_id 需要轮询）。"""
        token = self.get_access_token()
        if not token:
            return {}
        try:
            response = requests.post(
                "https://api.weixin.qq.com/cgi-bin/freepublish/get",
                params={"access_token": token},
                json={"publish_id": publish_id},
                timeout=30,
                proxies=self.proxies if self.use_proxy else {},
            )
            return response.json()
        except Exception as e:
            logger.error(f"查询发布状态异常: {e}")
            return {}

    def publish_draft(self, media_id: str) -> Optional[str]:
        """发布草稿（强操作，需用户逐次明确授权）。

        先试 cgi-bin/draft/publish，48001/接口不存在时回退 freepublish/submit。
        成功后返回 publish_id（发布是异步的，状态用 get_publish_status 查）。
        """
        _assert_not_in_test_context("publish_draft（发布）")
        token = self.get_access_token()
        if not token:
            logger.error("无法获取 access_token，发布中止")
            return None

        endpoints = [
            ("https://api.weixin.qq.com/cgi-bin/draft/publish", "draft/publish"),
            ("https://api.weixin.qq.com/cgi-bin/freepublish/submit", "freepublish/submit"),
        ]
        proxies = self.proxies if self.use_proxy else {}
        last_error = ""

        for url, name in endpoints:
            try:
                response = requests.post(
                    url, params={"access_token": token},
                    json={"media_id": media_id}, timeout=30, proxies=proxies,
                )
                data = response.json()
            except Exception as e:
                last_error = f"{name} 请求异常: {e}"
                logger.error(last_error)
                continue

            code = data.get("errcode", 0)
            if code == 0:
                publish_id = data.get("publish_id") or data.get("msg_data", {}).get("publish_id", "")
                logger.info(f"已发布（{name}）publish_id={publish_id}")
                return publish_id

            last_error = f"{name} 失败 errcode={code} {data.get('errmsg', '')}"
            logger.error(last_error)
            # 只有「接口不可用」才回退；其他错误（40164 IP 白名单等）换个接口也一样
            if code not in (48001, -1):
                break

        logger.error(f"发布失败，最后错误: {last_error}")
        return None


def publish_article(title: str, content: str, author: str = "", 
                    digest: str = "", cover_path: str = "",
                    auto_publish: bool = False, 
                    export_html: bool = True,
                    content_is_html: bool = False) -> bool:
    """发布文章

    Args:
        content_is_html: content 是否已是渲染好的微信 HTML（如 editorial_template 产出），
            为 True 时跳过 Markdown 转换。
    """
    publisher = WeChatPublisher()
    html_content = content if content_is_html else publisher.markdown_to_html(content)
    
    if export_html:
        publisher.export_html(content, title, content_is_html=content_is_html)
    
    if not publisher.app_id or publisher.app_id == "your_app_id_here":
        logger.warning("WeChat not configured, skipping publish")
        today = datetime.now().strftime("%Y%m%d")
        with open(f"output/article_{today}.md", "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Article saved to output/article_{today}.md")
        return True
    
    media_id = publisher.create_draft(
        title=title,
        content=html_content,
        author=author,
        digest=digest,
        cover_path=cover_path
    )
    
    if not media_id:
        logger.error("Failed to create draft")
        return False
    
    if auto_publish:
        publish_id = publisher.publish_draft(media_id)
        if publish_id:
            logger.info(f"Article published! ID: {publish_id}")
            return True
        return False
    
    logger.info(f"Draft created: {media_id}")
    logger.info("Login to mp.weixin.qq.com to publish")
    return True
