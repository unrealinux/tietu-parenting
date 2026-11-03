# 实拍 / 手绘素材

按 slug 建目录放图：`materials/<slug>/01.jpg`、`02.jpg`、`03.jpg`（3:4 最好，其他比例会居中裁切）。

post JSON 里加一行：

```json
"photos": ["01.jpg", "02.jpg", "03.jpg"]
```

然后出图：

```bash
"$PY" scripts/tietu_queue.py --slug <slug> --style photo --commit
```

规则：第 N 张卡用第 N 张图，图不够就重复最后一张。文字叠法复用 comic 那套（对比卡上白下淡）。

SOP 的优先级是「实拍 > 授权 > 图库 > AI」，有真图就别用 AI 图。
