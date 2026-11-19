# AI 题目录入工作流

把"人工逐条填表"换成"上传 PDF + 报题号 + AI 提取解题入库"。

## 工作流

```
① 你上传试卷 PDF  →  /root/uploads/
② 你告诉我题号      →  例如"录第 3、5、12 题"
③ 我提取题目         →  pdf_extract.py 按题号切出题干/选项/配图
④ 我解题             →  生成答案 + 解法 + 深度解析（我看图解题）
⑤ 我入库             →  ingest.py 写入数据库
⑥ 画布刷新即见       →  /canvas?api=1
```

## 工具用法

### 1. PDF 提取（我来跑）

```bash
# 查看 PDF 里检测到哪些题号
python3 tools/pdf_extract.py /root/uploads/试卷.pdf --dump-all

# 提取指定题号 → extracted.json
python3 tools/pdf_extract.py /root/uploads/试卷.pdf --nums 3,5,12 --out extracted.json

# 同时提取 PDF 内嵌图片
python3 tools/pdf_extract.py /root/uploads/试卷.pdf --nums 3,5 --imgdir ./pages_img
```

输出 JSON 结构：`{ "3": {q, opts, page, raw}, "5": {...} }`

### 2. 批量入库（我来跑）

先整理成 `questions.json`（数组），每题：

```json
[
  {
    "subject": "数量关系",
    "node_name": "工程问题",
    "q": "题干……",
    "src": "2026广东省考真题 第3题",
    "hit": true,
    "ans": "A",
    "opts": ["A. 96", "B. 100", "C. 104", "D. 108"],
    "solve": "解法（支持 **加粗** 和 ==高亮==）",
    "analysis": "深度解析……",
    "img": "https://... 或留空"
  }
]
```

然后：`python3 tools/ingest.py --file questions.json`

单题快速入库见 `ingest.py --help`。

## 字段说明

| 字段 | 含义 | 备注 |
|---|---|---|
| subject / node_name | 科目 + 知识点名 | 用于定位挂到哪个节点；也可直接给 node_id |
| q | 题干 | 图形推理题需配合 img |
| src | 题源 | 含"季"自动判为模考，否则真题 |
| hit | 做对/做错 | true / false / null |
| ans | 答案 | 单选"B" 或多选"ABC" |
| opts | 选项 | 字符串数组 |
| solve / analysis | 解法 / 深度解析 | 支持 markdown 加粗与高亮 |
| img | 配图 URL | 图形题必填 |

## 注意事项

- PDF 中文提取质量取决于 PDF 本身字体嵌入方式。扫描版/图片版 PDF 需要先 OCR（可用 pdf-image-text-extractor 技能）。
- 图形推理题：我从 PDF 提取配图后解题，答案准确性依赖图片清晰度。
- 目前节点结构来自示例数据（较稀疏）。若要按完整知识点分类，需先从 baseline 重建完整树。
- **图片统一走 OSS 外链**（已确认方案）：新增带图题时，先把图片上传到 OSS，再把公网 URL 填进 `img` 字段。不要把 base64 / 本地路径写进数据。

---

## 3. 图片上传阿里云 OSS（我来跑）

项目图片统一存放于阿里云 OSS。当数据里出现内嵌图片（base64 / data URI）需要转成外链，或需要批量上传图片时，用这个脚本。

**前置**：`oss2` SDK（`python3 -m pip install oss2`）；一个**公共读**的 Bucket + 有上传权限的 AccessKey。

凭证通过环境变量传入，**绝不写死在脚本或文档里**：

```bash
export OSS_ACCESS_KEY_ID="<AccessKey ID>"
export OSS_ACCESS_KEY_SECRET="<AccessKey Secret>"
export OSS_BUCKET="your-bucket"
export OSS_ENDPOINT="oss-cn-guangzhou.aliyuncs.com"   # 带地域的公网 endpoint
export OSS_PREFIX="mm5/b64/"                          # 可选，对象目录前缀
# export OSS_CUSTOM_DOMAIN="cdn.example.com"          # 可选，用了自定义域名/CDN时

python3 tools/upload_b64_to_oss.py
```

### 脚本做什么

1. 扫描 `data.json` 里所有 `examples[].img` 中的内嵌图片（支持 base64 和 URL 编码的 SVG）
2. 按 MD5 去重（相同图片只传一次，多处引用自动复用同一外链）
3. 以 `public-read` ACL 上传到 OSS，生成公网 URL：`https://{bucket}.{endpoint}/{prefix}{filename}`
4. 把 `img` 字段替换为外链，并同步写回 `data.json`、`data.js`、`mindmap.db`
5. 上传前自动备份为 `*.bak_upload`，末尾校验剩余内嵌图片数应为 0

### 先演练（不写文件、不上传）

```bash
DRY_RUN=1 OSS_ACCESS_KEY_ID=x OSS_ACCESS_KEY_SECRET=x OSS_BUCKET=x \
  python3 tools/upload_b64_to_oss.py
```

### 凭证获取位置（阿里云控制台）

| 信息 | 位置 |
|---|---|
| AccessKey ID / Secret | RAM 控制台 → 身份管理 → 用户 → 创建用户时勾选"使用永久 AccessKey 访问"；Secret 仅显示一次 |
| Bucket 名 | OSS 控制台 → Bucket 列表 |
| Endpoint | OSS 控制台 → 目标 Bucket → 概览 → 访问端口 → "外网访问"的 Endpoint |
| 读写权限 | Bucket 必须设为**公共读**，否则外链打不开 |

**安全**：建议使用 RAM 子账号 + 最小上传权限；密钥用完及时在控制台轮换/禁用，避免泄露。

### 本次迁移记录（2026-11-18）

15 张内嵌图（6 jpg + 8 png + 1 svg）上传到 `alibbxtbox/mm5/b64/`，去重后实际 8 个文件；44 张带图全部转为外链，`data.json` 由 1.1MB 瘦身到 394KB。其中 URL 编码的 SVG（`data:image/svg+xml;charset=utf-8,%3Csvg...`）需按 `unquote_to_bytes` 解码，不能当 base64 处理——脚本已兼容。
