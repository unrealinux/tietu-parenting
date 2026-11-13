# 育儿贴图号（微信图片消息）

按「微信贴图号」SOP 生产育儿主题的对比型贴图，走独立服务号，与 `feiyingqi-wechat-ainews` 账号完全隔离。

## 和旧项目的区别

| | feiyingqi-wechat-ainews | 本项目 |
|---|---|---|
| 账号 | 订阅号（wx9d3f***3843） | 新服务号（待填 .env） |
| 主题 | AI / 程序员 | 育儿 |
| 发布权限 | 无 `freepublish`（48001），只能后台手动发 | 已有发布接口权限（实测 `perm` 返回 OK），可脚本发布 |

两个项目各有自己的 `.env`，凭证不共享。跑任何脚本前先确认当前目录。

## 目录

```
posts/          选题 JSON（slug + title + content + cards）
output/tietu/   出图结果 + _queue.json 状态（media_id、时间戳）
scripts/        出图 / 建草稿 / 队列管理
src/            微信 API 封装（draft/add、素材上传）
references/     平台规则与红线
```

## 常用命令

```bash
cd E:/Project/tietu-parenting
PY="C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe"

"$PY" scripts/tietu_queue.py                    # 只出图+校验，不联网（默认，先跑这个）
"$PY" scripts/tietu_queue.py status             # 看本地队列
"$PY" scripts/tietu_queue.py copy               # 汇总所有标题 + 文案 → output/tietu/文案.txt（不联网）
"$PY" scripts/tietu_queue.py list               # 拉线上草稿箱对照
"$PY" scripts/tietu_queue.py sync               # 线上草稿回填本地，防重建
"$PY" scripts/tietu_queue.py --slug xxx --commit # 真建草稿
"$PY" scripts/tietu_queue.py perm                    # 只读探测发布权限（不发任何东西）
"$PY" scripts/tietu_queue.py publish                 # 先看会发哪几条（不联网）
"$PY" scripts/tietu_queue.py publish --yes           # 真发布（不可撤销）
"$PY" scripts/tietu_queue.py list --published        # 看线上已发布列表
"$PY" scripts/daily_pair.py --dry-run             # 一轮：贴图+图文只出图/自检
"$PY" scripts/daily_pair.py                       # 一轮：建贴图草稿 + 图文草稿
"$PY" scripts/gen_topics.py --dry-run           # 生成新选题只看不写（池子 < 4 条时才调接口）
"$PY" scripts/gen_topics.py                   # 真写 posts/，至少留 4 条未用素材
#    默认模型 deepseek-flash（复用本机 pi 登录态）；换回 Agnes：TEXT_MODEL=agnes-2.5-flash
```

单条出图：`"$PY" scripts/publish_tietu.py posts/xxx.json --images-only`

## 三种图风

| | `--style text` | `--style anime` | `--style comic`（默认，搞笑） |
|---|---|---|---|
| 底图 | 无，米白纸色 | Agnes 日系动漫插画 | Agnes 极简搞笑贴纸（纯白底） |
| 文字 | 楷体居中 | 雅黑粗体 + 描边，压底部渐隐 | 黑字压底部留白区，主句大、副句小，不画渐隐 |
| 耗时 | 1 秒/条 | 约 75–90 秒/条（25 秒/张） | 同 anime |
| 输出 | `output/tietu/<slug>/` | `output/tietu/<slug>/anime/` | `output/tietu/<slug>/comic/` |
| 版权 | 零风险 | AI 生成，见下方红线 | 同 anime |
| 适合 | 素材够、不想配图 | 温情、细腻、共情 | 吐槽、自嘲、反差，越夸张越好 |

```bash
"$PY" scripts/tietu_queue.py --style anime                       # 全量出插画版，不联网
"$PY" scripts/tietu_queue.py --style comic                       # 全量出搞笑版
"$PY" scripts/tietu_queue.py --slug xxx --style comic --commit    # 出图 + 建草稿
"$PY" scripts/make_anime_images.py posts/tietu_012_xxx.json --style comic --force  # 单条重生成
```

出图模型两选一，靠 `.env` 的 `IMAGE_PROVIDER` 切换：

| `IMAGE_PROVIDER` | 模型 | 需要的 key |
|---|---|---|
| 不填（默认） | `agnes-image-2.5-flash` | `AGNES_API_KEY` |
| `seedream` | `doubao-seedream-4-0-250828`（火山引擎 Ark） | `SEEDREAM_API_KEY` |

`comic` 和 `output/story/` 的漫画故事**共用同一份画风描述**（`make_anime_images.COMIC_STYLE`），
改画风只改那一处，两个流程一起生效。

插画版/搞笑版怎么配画面：在 post JSON 每张卡上加 `scene` 字段（中文场景描述）。
搞笑版建议在 `scene` 里写夸张表情和动作（打哈欠、翻白眼、扶额、扒栏杆），出图会明显更好笑。
底图会缓存为 `anime/_base_0N.png`，重跑只重新叠字，不重复花生成额度。

```json
{
  "a": "生娃前：周末睡到自然醒",
  "b": "生娃后：周末醒得比闹钟早",
  "scene": "清晨六点卧室，年轻妈妈被婴儿的小手拍醒，头发乱，床头闹钟指着六点，窗帘缝透进冷光"
}
```

依赖：`bun` + `.env` 里的 `AGNES_API_KEY` + `~/.claude/skills/baoyu-image-gen`（已加 Agnes provider）。
可选 `AGNES_API_URL` / `AGNES_MODEL` 覆盖端点和模型。

插画风格的额外红线：

1. 只能生成虚构角色，**不得**是真人明星脸或受版权保护的动漫角色
2. 不生成可识别身份的真实孩子
3. `scene` 里不要让真实孩子出镜：底图只能是纯 AI 虚构角色，不要把真实孩子的照片投进生成
4. AI 图仍按 SOP 排在「实拍 > 授权 > 图库」之后，同一条内容优先用能拍到的素材

## 数据源与选题

四层数据源见 `references/DATA-SOURCES.md`：

- 素材：`materials/<slug>/` 放实拍图，post 里写 `"photos": [...]`，`--style photo` 出图
- 选题：截图/评论/一句话丢 `references/intake/`，沉淀到根目录 `topics.md` 选题池
- 数据：`output/stats/articles.json`（单篇，截图或 `log_stats.py` 记）、`user_summary.json`（粉丝，`fetch_stats.py`）
- 风格：`references/` 两份规则 + 已发文案作为口吻基线

写新内容先看 `topics.md`，从「待写」取，不凭空想。

## 图片故事 + 每日定时任务

```bash
"$PY" scripts/make_comic_story.py posts/story_006_own-bed-night.json          # 只出图
"$PY" scripts/publish_story.py posts/story_006_own-bed-night.json --dry-run   # 本地自检
"$PY" scripts/publish_story.py posts/story_006_own-bed-night.json --commit    # 真建草稿
"$PY" scripts/publish_story.py --next                                          # 看下一轮会建哪篇
```

Windows 计划任务 `tietu-daily`（每天 8:30）跑 `scripts/daily_drafts.cmd`，一次做两件事：

1. `publish_story.py --next --commit` —— 挑 `posts/story_*.json` 里第一篇本地没记录、线上没同标题的 story，图不全先出图，再建图文草稿；已建的记在 `output/story/_state.json`
2. `tietu_queue.py --style comic --limit 3 --commit` —— 建 3 篇最近编号的贴图草稿（`TIETU_COUNT` 可改），最新优先，积压的排到后面

只建草稿，永不发布；重复跑安全。发布仍然手动：`tietu_queue.py publish --slug <slug> --yes`。

## 发布：先 `perm` 再 `publish`

**「发布」和「群发」不是一回事：**

| | 接口 | 推通知给粉丝 | 占群发次数 | 去哪 |
|---|---|---|---|---|
| 发布 | `draft/publish` → 回退 `freepublish/submit` | 否 | 否 | 公众号主页 + 推荐流 |
| 群发 | `message/mass/sendall` | 是 | 服务号每月 4 次 | 消息列表 |

贴图号靠推荐流分发，走「发布」。流程：

1. `perm` —— 只读探测权限。本号当前返回 `[OK] 有发布权限`；若返回 `48001`，说明服务号还没认证，或该接口没开
2. `publish` —— 不带 `--yes` 只列出待发条目，确认清单没错
3. `publish --yes` —— 真发。发布是**异步**的，`publish_id` 会写回 `_queue.json`

脚本已做接口回退（`draft/publish` 不可用时自动试 `freepublish/submit`），但 `40164`（IP 白名单）这类错误换个接口也一样失败，不会反复重试。

## 每天两次自动建草稿

`scripts/daily_pair.py` 一轮做两件事：建 1 篇贴图草稿 + 1 篇图文草稿，**不发布**。
贴图去 `output/tietu/_queue.json` 查重，文章去 `output/story/_queue.json` 查重；
两篇各自独立，一篇失败不影响另一篇。文章缺图时会先调用 `make_comic_story.py` 生成，
所以文章侧仍需要 `bun` + `AGNES_API_KEY`；贴图侧没有 Agnes 时显式加 `--style text`（默认是 comic，会调 Agnes）。

```bash
"$PY" scripts/daily_pair.py --style text --dry-run   # 本机没有 Agnes 时先这样看
"$PY" scripts/daily_pair.py --style text             # 建两条草稿
```

Linux cron（每天 08:00 / 20:00）：

```cron
0 8,20 * * * cd /home/xieyingfei/文档/tietu-parenting && mkdir -p logs && python3 scripts/daily_pair.py >> logs/daily-pair.log 2>&1
```

Windows 任务计划程序：建两个每日触发器 08:00、20:00，操作选 `python.exe`，
参数 `scripts\daily_pair.py`，起始目录设为项目根目录。

`daily_pair.py` 只建草稿。贴图发布走 `tietu_queue.py publish --yes`；
图文草稿在公众号后台「草稿箱」人工点发布。

## post JSON 结构

```json
{
  "slug": "kid-one-vs-two",
  "title": "草稿标题（自控 ≤20 字，微信硬上限 64）",
  "content": "发布文案，不重复图上文字",
  "cards": [
    {"a": "一胎：照书养", "b": "二胎：照猪养"},
    {"label": "我妈说的是", "lines": ["多穿点", "多吃一口"]},
    {"text": "你家谁说了算？", "sub": "评论区留一句"}
  ]
}
```

三种卡：对比卡 `{a,b}` · 清单卡 `{label,lines[]}` · 单句卡 `{text,sub}`。**cards 只能 1–3 张。**

## 排版硬限制（踩过的坑）

- 单句卡主文案 **≤8 个汉字**，否则会在第 8 字折行、末尾留 2 字孤行。9–12 字和 13 字以上都会出孤行。
- **标题控制在 20 字以内**（自己的要求；超过脚本报警告，微信硬上限是 64 字）。改完标题不用重出图，标题不在图上。
- 对比卡 a/b 各自 **≤12 字**一行；超过 12 字折行，末尾少于 4 字同样难看。
- 搞笑版（comic）主文案固定压成一行：a 侧 12 字自动降到 84px，超过 12 字继续缩字保持一行（最小 40px，仍放不下才会折行）；b 侧是小字，按 16 字折行。
  `tietu_queue.py` 已按画风分别校验：对比卡 `comic (a≤12, b≤16)`、`anime/text (a≤12, b≤12)`；单句卡 `comic ≤12`、`anime/text ≤8`；副文案 ≤20。超了会报警告。
- 单句卡副文案按 20 字折行，控制在 20 字内一行最好看。
- 改完 JSON 必须重出图，脚本不会自动比对。

## 育儿主题的 3 条既有内容

`posts/` 里已有 3 条（都是「对比」结构，已验证）：
- `baby-before-after` 生娃前 VS 生娃后
- `one-vs-two-kids` 一胎照书养 VS 二胎照猪养
- `mom-vs-me` 我妈带娃 VS 我带娃

## 红线

1. 不搬原图、原文、他人经历；不保存对标账号的图当素材
2. 不制造广告点击、不刷数据、不用恐吓/擦边/夸大标题
3. 儿童照片谨慎：**不发可识别身份的孩子照片**，优先拍物件、手部、场景
4. 只用两个发布入口：公众号助手 App、微信公众平台官网（或本项目经 API 的发布能力）
5. 同方向连续发 3–5 条再复盘，不要一条数据定方向

## 报错码

| errcode | 含义 | 处理 |
|---|---|---|
| 40164 | IP 不在白名单 | 服务号后台「基本配置 → IP 白名单」加本机公网 IP |
| 41001 | token 失效 | 重跑，脚本会重取 |
| 40007 | media_id 无效 | 素材没传成功，重传 |
| 45003 | 标题或正文超长 | 标题 ≤64 字 |
| 48001 | 该账号无此接口权限 | 服务号需认证；或该接口本身不可用 |
