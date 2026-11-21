# 工具脚本速查（单一入口）

> **开工第一站**：找"干什么用什么"先看这里，别猜、别试跑、别读源码。
> 所有脚本在 `mindmap-server/tools/`，命令默认在 `/workspace/mindmap-server` 下执行。
> 命令有疑问 `python3 tools/XXX.py --help` 实测——**但注意 `split_data.py` 无 `--help` 且直接运行有副作用**（见下）。
> token 经济：脚本只回摘要，不吐全量 JSON；数据不进上下文。
>
> 历史文档：原「AI 题目录入工作流 / OSS 迁移记录」已移入《行测思维导图项目-实施经验总结.md》6.19/6.20；OSS 方案欠费废弃、禁外链，`upload_b64_to_oss.py` 仅存档。

## 通用脚本（优先用，为消灭临时写代码而固化）

| 脚本 | 用途 | 关键命令 | 副作用 |
|---|---|---|---|
| `data_probe.py` | 数据勘察：统计/分支树/找同类题/查路径 | `stats` · `tree 逻辑判断 [--subject X]` · `scan --kw 反证,逆否 --subject 判断推理` · `path "题目src"` | **只读** |
| `ui_probe.py` | 前端验证脚手架：冒烟/面板专项/自定义断言 | `smoke local\|online` · `panel local --name 方法提炼` · `custom local --checks checks.json` | **只读** |

> 纪律：开工勘察用 `data_probe`，前端验证用 `ui_probe`，**不要再手写 inline python / Playwright 脚本**。

## 按 SOP 场景分组

### SOP-A 新卷入库
| 脚本 | 用途 | 关键命令 |
|---|---|---|
| `pdf_extract.py` | 按题号切题干/选项/配图 | 见《试卷错题录入工作流程.md》Step 3 |
| `ingest_v2.py` | 新卷入库核心 | `derive-answers --pdf P --out O`；`ingest --questions Q --answers A [--dry-run] [--deploy]`（derive 是**子命令**） |
| `batch_inject.py` | 按 src 批量注入 | `BATCH.json --subject 数量关系 [--allow-dup]` |
| `replace_img_urls.py` | 批量替换图片 URL | 见资产手册 |
| `build_img_map.py` | 重建图片映射表 | 图映射错乱时 |

### SOP-B 单题解析优化（最常用）
| 脚本 | 用途 | 关键命令 |
|---|---|---|
| `question_index.py` | 抽单题（免 build、免全量 JSON） | `get "题目src" [--fields oneLiner,steps]`；`build` 建轻量索引 |
| `patch_solution.py` | 单题补丁：预检+三轨写入+对账 | `--src "..." --solution /tmp/sol.json [--check]`（**无 --apply**，不带 --check 即写入） |
| `fix_underline.py` | 填空横线还原 | `[--src "题目src"] [--dry]`；不带参数全库 |
| `validate_v2.py` | 五块结构/字数校验 | `validate_v2.py FILE`；`--samples` |
| `token_audit.py` | token 归因审计 | `TOKEN [trace] [--session S] [-v] [--log]` |

### SOP-C 批量重写
`export_pending.py`（导出待写清单）、`batch_inject.py` / `validate_v2.py`（同上）。

### SOP-D 归类修正
| 脚本 | 用途 | 关键命令 |
|---|---|---|
| `regroup_examples.py` | 迁移节点归类 | `--move "src\|旧路径\|新路径" [--dry] [--subject X]`（**先 --dry 预演**） |
| `promote_examples.py` | 全库例题节点化 | DRY-RUN / `--apply`（写 server/data.json） |
| `merge_orphan_desc.py` | 补齐漏网描述句合并 | DRY-RUN / `--apply` |
| `revert_method53.py` | 方法卡回退：第53题迁回原节点 | DRY-RUN / `--apply` |
| `unify_solutions.py` | 统一 solution 结构 | 迁移时 |

### SOP-E 展示改造
`ui_probe.py`（前端验证，见上）、`build_docs.py`（构建 `data/docs.json`，归档 md 后须重建）、`build_methods.py`（构建 `data/methods.json`，改方法后重建、随部署上传）。

### SOP-F 审查 / 体检
`data_probe.py`（数据勘察，见上；`stats` 可替代手写三轨/题数统计）。

### 统一收尾
| 脚本 | 用途 | 关键命令 |
|---|---|---|
| `split_data.py` | 从 server/data.json 重拆 p1~p5 + manifest + 一致性校验 | ⚠ **无 --help，直接运行会重写分科文件**（设计如此）；**不写 demo/data.json，需手动 cp 同步** |
| `gh_upload_atomic.py` | 原子部署（一次 commit=一次 Pages） | `BASE_DIR F1 F2... [--dry-run] [--message M] [--retries N]` |
| `verify_deploy.py` | 线上验证（等部署+禁缓存） | `[--mode online\|local] [--url U] [--wait-deploy]` |

## 一次性 / 专用脚本（历史沉淀，非通用，按需才用）

`ingest.py`（旧入库）、`gh_upload_curl.py`（curl 版部署）、`fix_q71_hit.py` / `inject_q71.py` / `set_q71_img.py` / `strip_q71_material_text.py` / `upload_q71_material.py` / `verify_q71*.py`（第71题专项）、`upload_b64_to_oss.py`（OSS 已废弃，仅存档）。

> 纪律：一次性脚本用完即弃、放 artifact 目录，**不要塞进 tools/**；只有"下次还会用"的通用能力才入 tools/ 并登记本文件。

## 铁律速记

1. 开工先查本文件 → 有脚本用脚本，没有才考虑写；写的若是通用能力，固化进 tools/ 并登记。
2. 数据勘察 `data_probe`，前端验证 `ui_probe`，禁止重写 inline python / Playwright 样板。
3. 读大文件先 grep -n 定位再分片 Read（单次≤6KB）；禁整篇读大 JSON。
4. `--dry` / `--check` / `--dry-run` 先预演，再正式执行（尤其归类/迁移/补丁）。
