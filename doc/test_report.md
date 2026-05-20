# CrawlAgentcore Test Report

**Generated:** 2026-05-20 UTC  
**Python:** 3.10.12  
**Environment:** Linux x86_64 (local dev mode)  
**Scope:** Unit tests · Integration tests · Performance benchmarks · Cloud E2E framework

---

## 1. Unit Test Summary

| Metric | Result |
|---|---|
| Total tests | **253** |
| Passed | **253** ✅ |
| Skipped | **23** (cloud E2E — env vars not set) |
| Failed | 0 |
| Duration | ~14 s |

### 1.1 Test File Distribution

| File | Tests | Coverage |
|---|---|---|
| `tests/test_agent_wiring.py` | 7 | Agent assembly, encoding pipeline, output extraction, mojibake detection |
| `tests/test_customer_inputs.py` | 58 | Skill routing, payload format, edge cases, output extraction |
| `tests/test_skills.py` | 8 | Skill loading, frontmatter parsing, argument substitution |
| `tests/test_browser_tool.py` | 31 | Browser session lifecycle, CDP eval, screenshot, navigation, error paths |
| `tests/test_cfn_handler.py` | 45 | CFN handler dispatch, all resource types, wait_status, cfn_send |
| `tests/test_encoding_advanced.py` | 62 | Deep encoding pipeline: repair/recursive/detection/unwrap/extract/roundtrip |
| `tests/test_invoke_flow.py` | 36 | Auto-select skill, payload parsing, response structure, retry logic |
| `tests/test_cloud_e2e.py` | 6 ✅ / 23 skip | Cloud E2E framework self-tests; cloud tests skip when env vars absent |

### 1.2 Pass Rate by Class

| Test Class | Pass / Total |
|---|---|
| `TestSkillDiscovery` | 4 / 4 ✅ |
| `TestDefaultCrawlCustomerInputs` | 4 / 4 ✅ |
| `TestEcommerceCrawlCustomerInputs` | 5 / 5 ✅ |
| `TestNewsCrawlCustomerInputs` | 6 / 6 ✅ |
| `TestApiCrawlCustomerInputs` | 5 / 5 ✅ |
| `TestDocsCrawlCustomerInputs` | 6 / 6 ✅ |
| `TestSocialCrawlCustomerInputs` | 6 / 6 ✅ |
| `TestPayloadRouting` | 8 / 8 ✅ |
| `TestOutputExtraction` | 7 / 7 ✅ |
| `TestEdgeCases` | 7 / 7 ✅ |
| `TestRtClient` + `TestStartSession` + `TestEnableAutomationStream` | 8 / 8 ✅ |
| `TestWaitStreamReady` + `TestScreenshotB64` + `TestCdpEval` | 9 / 9 ✅ |
| `TestNavigate` + `TestStopSession` + `TestBrowserCrawlImpl` | 10 / 10 ✅ |
| `TestBrowserCrawlTool` + `TestEnvironmentVariables` | 4 / 4 ✅ |
| `TestCfnSend` + `TestWaitStatus` | 7 / 7 ✅ |
| `TestCreateCodeInterpreter` + `TestCreateBrowser` + `TestCreateAgentRuntime` | 14 / 14 ✅ |
| `TestCreateAgentRuntimeEndpoint` + `TestSetupXrayCloudwatch` + `TestCreateCwResourcePolicy` | 14 / 14 ✅ |
| `TestHandler` (dispatch table) | 10 / 10 ✅ |
| `TestRepairMojibake` + `TestRepairMojibakeRecursive` | 12 / 12 ✅ |
| `TestLooksLikeMojibake` + `TestDecodeCandidates` + `TestUnwrapCiText` | 22 / 22 ✅ |
| `TestExtractCrawlerOutput` + `TestEnsureAsciiSafe` + `TestFullEncodingPipeline` | 28 / 28 ✅ |
| `TestAutoSelectSkill` + `TestPayloadParsing` + `TestInvokeResponseStructure` | 20 / 20 ✅ |
| `TestRetryOnNoneOutput` + `TestMojibakeRetry` | 5 / 5 ✅ |
| `TestSetupObservability` + `TestRefreshingAWS4Auth` + `TestSkillSelectionInvoke` | 11 / 11 ✅ |
| `TestCloudE2eFramework` (local self-tests) | 6 / 6 ✅ |

---

## 2. Functional Integration Tests

Real HTTP requests against public websites, verifying crawl capability per skill.

### 2.1 API Crawl — jsonplaceholder.typicode.com

| Test | Result | Status | Items | Latency |
|---|---|---|---|---|
| `GET /users` — user list | ✅ PASS | 200 | 10 items | 57.4 ms |
| `GET /posts?_limit=10` — paginated posts | ✅ PASS | 200 | 10 items | 67.1 ms |

### 2.2 E-Commerce Crawl — books.toscrape.com

| Test | Result | Status | Items | Latency |
|---|---|---|---|---|
| Homepage product listing | ✅ PASS | 200 | — | 132.7 ms |

### 2.3 News Crawl — news.ycombinator.com

| Test | Result | Status | Latency |
|---|---|---|---|
| Homepage reachability | ✅ PASS | 200 | 287.1 ms |

### 2.4 Tier Classification — 8 URLs

| URL | Expected | Actual | Result |
|---|---|---|---|
| `www.douban.com/movie/top250` | STRICT | STRICT | ✅ |
| `jd.com/product/123` | STRICT | STRICT | ✅ |
| `sub.douban.com/` | STRICT | STRICT | ✅ (subdomain handled) |
| `books.toscrape.com/` | OPEN | OPEN | ✅ |
| `jsonplaceholder.typicode.com/users` | OPEN | OPEN | ✅ |
| `api.wikipedia.org/` | OPEN | OPEN | ✅ |
| `news.ycombinator.com/` | MODERATE | MODERATE | ✅ |
| `example.com/page` | MODERATE | MODERATE | ✅ |

**8 / 8 passed** ✅

### 2.5 Encoding Round-trip — 4 Language Groups

Verifies `_ensure_ascii_safe()` → base64 transport → `_unescape_unicode_recursive()` preserves all characters.

| Input | Language | Intact |
|---|---|---|
| `肖申克的救赎` | Chinese | ✅ |
| `霸王别姬` | Chinese | ✅ |
| `こんにちは世界` | Japanese | ✅ |
| `Léon: The Professional` | French accents | ✅ |
| `© ® ™ € £ ¥` | Symbols | ✅ |
| 250-item movie dataset | Mixed CJK | ✅ |

---

## 3. New Test Coverage (this release)

### 3.1 browser_tool.py — 31 tests

| Area | Tests | Description |
|---|---|---|
| Session lifecycle | 6 | start/stop session, unique names, viewport |
| Stream management | 5 | enable stream, poll until ENABLED, timeout/failure |
| Screenshot | 3 | base64 encode, empty data, bytes/bytearray |
| CDP eval | 3 | value extraction, connection error, timeout |
| Navigation | 1 | keyboard action sequence verification |
| `_browser_crawl_impl` | 7 | happy path, error path, session always stopped, links parsing |
| `browser_crawl` tool | 2 | JSON string output, parseable |
| Environment variables | 2 | BROWSER_ID, AWS_REGION from env |

### 3.2 CloudFormation Handler — 45 tests

| Area | Tests | Description |
|---|---|---|
| `cfn_send` | 3 | HTTP PUT format, SUCCESS/FAILED, stack/request IDs |
| `wait_status` | 4 | READY/FAILED/timeout/poll-multiple-times |
| CodeInterpreter | 5 | create params, ARN returned, wait, delete not-found |
| Browser | 4 | create, ARN, wait, delete not-found |
| AgentRuntime | 5 | create, env vars, container URI, delete with endpoint cleanup |
| AgentRuntimeEndpoint | 6 | ARN, physical ID format, wait, FAILED raises, delete parse, not-found |
| XRay/CloudWatch | 3 | update destination, poll until ACTIVE, physical ID |
| CW Resource Policy | 5 | put policy, xray principal, physical ID, delete, exception swallow |
| Handler dispatch | 10 | all 6 resource types, Update noop, Delete, unknown type, exception |

### 3.3 Encoding Pipeline (Advanced) — 62 tests

| Area | Tests | Description |
|---|---|---|
| `_repair_mojibake` | 7 | 1-layer, 2-layer, clean text preserved, unrecoverable |
| `_repair_mojibake_recursive` | 5 | str/dict/list/nested/non-string values |
| `_looks_like_mojibake` | 10 | marker count, byte ratio, CJK not detected, edge cases |
| `_decode_candidates` | 6 | original included, unescaped newlines, unicode, mojibake-repaired |
| `_unwrap_ci_text` | 6 | Python repr, regex fallback, no-wrap, multiple blocks |
| `_extract_crawler_output` | 10 | B64/JSON delimiters, bare JSON, json block, assistant text, CI wrap |
| `_ensure_ascii_safe` | 13 | dict keys/values, list items, non-string, round-trip ×5 languages |
| Full pipeline | 6 | 250-item Chinese/Japanese/French/mixed/symbols dataset |

### 3.4 invoke Flow — 36 tests

| Area | Tests | Description |
|---|---|---|
| `_auto_select_skill` | 7 | JSON response, name-match fallback, invalid JSON, str message |
| Payload parsing | 6 | full/minimal/empty payload, args override, browser flag |
| Response structure | 8 | all required fields, types, auto_selected, browser_used, ASCII-safe |
| Retry on None output | 2 | retry triggered, retry result used |
| Mojibake retry | 3 | mojibake detected→retry, clean→no retry, corrupted replaced |
| Observability | 3 | silent failure, AWS error, env var defaults |
| `_RefreshingAWS4Auth` | 2 | credentials refreshed per call, correct region/service |
| Skill selection | 5 | explicit bypass, unknown fallback, system prompt, browser hint |

### 3.5 Cloud E2E Framework — 6 + 23 tests

| Area | Tests | Note |
|---|---|---|
| Framework self-tests | 6 ✅ | `_unescape` function, required vars, skip logic |
| Health check | 4 (skip) | Activated when `AGENTCORE_RUNTIME_ID` etc. set |
| Skill routing | 6 (skip) | All 6 skills + auto-select |
| Functional crawl | 4 (skip) | API / e-commerce / news / default |
| Encoding E2E | 3 (skip) | CJK round-trip through cloud transport |
| Browser stub | 2 (skip) | `browser_used=False` baseline; full test needs `BROWSER_ID` |
| Performance | 4 (skip) | Activated with `CLOUD_PERF_TEST=1` |

---

## 4. Performance Benchmarks

All benchmarks run locally (no network I/O), measuring compute overhead only.

### 4.1 Skill Loading

Baseline: 100 iterations (`list_skills`) / 50 iterations (`load_skill`)

| Operation | Avg | P95 |
|---|---|---|
| `list_skills()` — scan 6 skill directories | 0.202 ms | 0.260 ms |
| `load_skill("default-crawl")` | 0.100 ms | 0.110 ms |
| `load_skill("ecommerce-crawl")` | 0.115 ms | 0.127 ms |
| `load_skill("news-crawl")` | 0.117 ms | 0.128 ms |
| `load_skill("api-crawl")` | 0.099 ms | 0.112 ms |
| `load_skill("docs-crawl")` | 0.125 ms | 0.183 ms |
| `load_skill("social-crawl")` | 0.116 ms | 0.131 ms |

> All skill load P95 values < 0.3 ms — negligible contribution to request latency.

### 4.2 Encoding Pipeline

Baseline: 100 iterations, input = 250 movie records with CJK fields

| Operation | Avg | P95 |
|---|---|---|
| `_ensure_ascii_safe(250 items)` | 4.748 ms | 4.975 ms |
| Base64 encode + decode roundtrip (250 items) | 8.109 ms | 8.339 ms |

> Full encode/decode for 250 records < 10 ms. Not a bottleneck.

### 4.3 Tier Classification

Baseline: 10,000 iterations

| Metric | Latency |
|---|---|
| Avg | 0.0015 ms |
| P95 | 0.0016 ms |
| P99 | 0.0016 ms |

> < 0.002 ms per classification — imperceptible overhead.

### 4.4 Mojibake Detection

Baseline: 1,000 iterations, input = 250-item CJK JSON string

| Operation | Avg | P95 |
|---|---|---|
| `_looks_like_mojibake()` | 8.8 ms | 9.1 ms |

> Triggered once per response; 9 ms is acceptable at this data size.

### 4.5 Integration Network Latency (actual HTTP)

| URL | Status | Latency |
|---|---|---|
| `jsonplaceholder.typicode.com/users` | 200 | 57.4 ms |
| `jsonplaceholder.typicode.com/posts?_limit=10` | 200 | 67.1 ms |
| `books.toscrape.com` | 200 | 132.7 ms |
| `news.ycombinator.com` | 200 | 287.1 ms |

---

## 5. Performance Summary

| Stage | Typical Latency | Share of Request |
|---|---|---|
| Skill loading | < 0.3 ms | negligible |
| Tier classification | < 0.002 ms | negligible |
| Encoding pipeline (250 items) | < 10 ms | negligible |
| Mojibake detection | < 10 ms | negligible |
| HTTP crawl (OPEN sites) | 57 – 290 ms | **significant** |
| LLM inference (Claude ConverseStream) | 10 – 60 s | **dominant** |

> Local compute overhead total < 20 ms. Request latency is dominated by network I/O and LLM inference.

---

## 6. Cloud E2E Test Activation

Cloud E2E tests (23 tests) are skipped locally and activate automatically when the following environment variables are set:

```bash
export AGENTCORE_RUNTIME_ID=<runtime-id>
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=<account-id>
# Optional:
export AGENTCORE_ENDPOINT_NAME=crawlerEndpoint
export BROWSER_ID=<browser-id>        # enables browser tests
export CLOUD_PERF_TEST=1              # enables performance benchmarks

python -m pytest tests/test_cloud_e2e.py -v
```

Cloud test groups:
- **Health check** (4): Runtime reachability, response structure
- **Skill routing** (6): Explicit routing for all 6 skills + auto-select
- **Functional crawl** (4): API / e-commerce / news / default against real sites
- **Encoding E2E** (3): CJK round-trip through cloud transport layer
- **Browser stub** (2): `browser_used` flag baseline; full test requires `BROWSER_ID`
- **Performance** (4): End-to-end invoke latency benchmarks (requires `CLOUD_PERF_TEST=1`)

---

## 7. Known Limitations

| Item | Notes |
|---|---|
| Cloud E2E tests | Require AgentCore Runtime deployment; skipped in local/CI by design |
| Browser full crawl | Requires `BROWSER_ID` env var and deployed AgentCore Browser instance |
| STRICT-tier sites (Douban etc.) | Require real cloud Code Interpreter; cannot be tested locally |
| LLM-dependent auto-select | `_auto_select_skill` tested with mocked LLM; real LLM selection verified in cloud E2E |

---

---

# CrawlAgentcore 测试报告

**生成时间：** 2026-05-20 UTC  
**Python 版本：** 3.10.12  
**运行环境：** Linux x86_64（本地 dev 模式）  
**测试范围：** 单元测试 · 集成测试 · 性能基准 · 云端 E2E 框架

---

## 一、单元测试总结

| 指标 | 结果 |
|---|---|
| 总测试数 | **253** |
| 通过 | **253** ✅ |
| 跳过 | **23**（云端 E2E — 环境变量未设置） |
| 失败 | 0 |
| 耗时 | 约 14 秒 |

### 1.1 测试文件分布

| 文件 | 测试数 | 覆盖范围 |
|---|---|---|
| `tests/test_agent_wiring.py` | 7 | Agent 装配、编码管道、输出提取、Mojibake 检测 |
| `tests/test_customer_inputs.py` | 58 | 技能路由、Payload 格式、边界情况、输出提取 |
| `tests/test_skills.py` | 8 | 技能加载、frontmatter 解析、参数替换 |
| `tests/test_browser_tool.py` | 31 | Browser 会话生命周期、CDP eval、截图、导航、错误路径 |
| `tests/test_cfn_handler.py` | 45 | CFN handler 分发、所有资源类型、wait_status、cfn_send |
| `tests/test_encoding_advanced.py` | 62 | 深度编码管道：修复/递归/检测/解包/提取/往返 |
| `tests/test_invoke_flow.py` | 36 | 技能自动选择、Payload 解析、响应结构、重试逻辑 |
| `tests/test_cloud_e2e.py` | 6 ✅ / 23 跳过 | 云端 E2E 框架自测；云端测试在缺少环境变量时自动跳过 |

### 1.2 分类通过情况

| 测试类 | 通过 / 总数 |
|---|---|
| `TestSkillDiscovery` | 4 / 4 ✅ |
| `TestDefaultCrawlCustomerInputs` | 4 / 4 ✅ |
| `TestEcommerceCrawlCustomerInputs` | 5 / 5 ✅ |
| `TestNewsCrawlCustomerInputs` | 6 / 6 ✅ |
| `TestApiCrawlCustomerInputs` | 5 / 5 ✅ |
| `TestDocsCrawlCustomerInputs` | 6 / 6 ✅ |
| `TestSocialCrawlCustomerInputs` | 6 / 6 ✅ |
| `TestPayloadRouting` | 8 / 8 ✅ |
| `TestOutputExtraction` | 7 / 7 ✅ |
| `TestEdgeCases` | 7 / 7 ✅ |
| Browser 会话 / Stream / 截图 / CDP / 导航类 | 17 / 17 ✅ |
| `TestBrowserCrawlImpl` + `TestBrowserCrawlTool` + 环境变量类 | 14 / 14 ✅ |
| `TestCfnSend` + `TestWaitStatus` | 7 / 7 ✅ |
| 资源创建/删除类（CI / Browser / AgentRuntime / Endpoint / XRay / CW） | 38 / 38 ✅ |
| `TestHandler`（分发表） | 10 / 10 ✅ |
| `TestRepairMojibake` + `TestRepairMojibakeRecursive` | 12 / 12 ✅ |
| `TestLooksLikeMojibake` + `TestDecodeCandidates` + `TestUnwrapCiText` | 22 / 22 ✅ |
| `TestExtractCrawlerOutput` + `TestEnsureAsciiSafe` + `TestFullEncodingPipeline` | 28 / 28 ✅ |
| `TestAutoSelectSkill` + `TestPayloadParsing` + `TestInvokeResponseStructure` | 20 / 20 ✅ |
| `TestRetryOnNoneOutput` + `TestMojibakeRetry` | 5 / 5 ✅ |
| `TestSetupObservability` + `TestRefreshingAWS4Auth` + `TestSkillSelectionInvoke` | 11 / 11 ✅ |
| `TestCloudE2eFramework`（本地自测） | 6 / 6 ✅ |

---

## 二、功能集成测试

对真实公开网站发起 HTTP 请求，验证各技能爬取能力。

### 2.1 API 爬取 — jsonplaceholder.typicode.com

| 测试项 | 结果 | 状态码 | 条目数 | 耗时 |
|---|---|---|---|---|
| `GET /users` — 用户列表 | ✅ PASS | 200 | 10 条 | 57.4 ms |
| `GET /posts?_limit=10` — 帖子列表 | ✅ PASS | 200 | 10 条 | 67.1 ms |

### 2.2 电商爬取 — books.toscrape.com

| 测试项 | 结果 | 状态码 | 耗时 |
|---|---|---|---|
| 首页可达性 | ✅ PASS | 200 | 132.7 ms |

### 2.3 新闻爬取 — news.ycombinator.com

| 测试项 | 结果 | 状态码 | 耗时 |
|---|---|---|---|
| 首页可达性 | ✅ PASS | 200 | 287.1 ms |

### 2.4 域名 Tier 分级（8 个用例）

| URL | 预期 | 实际 | 结果 |
|---|---|---|---|
| `www.douban.com/movie/top250` | STRICT | STRICT | ✅ |
| `jd.com/product/123` | STRICT | STRICT | ✅ |
| `sub.douban.com/` | STRICT | STRICT | ✅（子域名正确识别） |
| `books.toscrape.com/` | OPEN | OPEN | ✅ |
| `jsonplaceholder.typicode.com/users` | OPEN | OPEN | ✅ |
| `api.wikipedia.org/` | OPEN | OPEN | ✅ |
| `news.ycombinator.com/` | MODERATE | MODERATE | ✅ |
| `example.com/page` | MODERATE | MODERATE | ✅ |

**8 / 8 全部通过** ✅

### 2.5 编码往返（4 语言 / 字符组）

验证 `_ensure_ascii_safe()` → base64 传输 → `_unescape_unicode_recursive()` 全链路字符完整性。

| 原始内容 | 语言 / 类别 | 还原一致 |
|---|---|---|
| `肖申克的救赎` | 中文 | ✅ |
| `霸王别姬` | 中文 | ✅ |
| `こんにちは世界` | 日文 | ✅ |
| `Léon: The Professional` | 法语重音符 | ✅ |
| `© ® ™ € £ ¥` | 特殊符号 | ✅ |
| 250 条电影数据集 | 混合 CJK | ✅ |

---

## 三、新增测试覆盖（本次版本）

### 3.1 browser_tool.py — 31 个测试

| 范围 | 测试数 | 说明 |
|---|---|---|
| 会话生命周期 | 6 | 启动/停止、唯一名称、viewport |
| Stream 管理 | 5 | 启用 stream、轮询至 ENABLED、超时/失败 |
| 截图 | 3 | base64 编码、空数据、bytes/bytearray |
| CDP eval | 3 | 值提取、连接错误、超时 |
| 导航 | 1 | 键盘操作序列验证 |
| `_browser_crawl_impl` | 7 | 正常路径、错误路径、session 必须停止、链接解析 |
| `browser_crawl` 工具 | 2 | JSON 字符串输出、可解析 |
| 环境变量 | 2 | BROWSER_ID、AWS_REGION |

### 3.2 CloudFormation Handler — 45 个测试

| 范围 | 测试数 | 说明 |
|---|---|---|
| `cfn_send` | 3 | HTTP PUT 格式、SUCCESS/FAILED、Stack/Request ID |
| `wait_status` | 4 | READY/FAILED/超时/多次轮询 |
| CodeInterpreter | 5 | 创建参数、ARN 返回、等待、删除时 not-found 处理 |
| Browser | 4 | 创建、ARN、等待、not-found |
| AgentRuntime | 5 | 创建、环境变量、容器 URI、删除时先清理 Endpoint |
| AgentRuntimeEndpoint | 6 | ARN、PhysicalResourceId 格式、等待、FAILED 抛出、删除解析、not-found |
| XRay/CloudWatch | 3 | 更新 destination、轮询至 ACTIVE、PhysicalResourceId |
| CW Resource Policy | 5 | put policy、xray 主体、PhysicalResourceId、删除、异常吞噬 |
| Handler 分发 | 10 | 全部 6 种资源类型 + Update noop + Delete + 未知类型 + 异常 |

### 3.3 编码管道（深度） — 62 个测试

| 范围 | 测试数 | 说明 |
|---|---|---|
| `_repair_mojibake` | 7 | 单层/双层修复、干净文本保留、不可修复内容 |
| `_repair_mojibake_recursive` | 5 | str/dict/list/嵌套/非字符串值 |
| `_looks_like_mojibake` | 10 | 标记计数、高字节比率、CJK 不误检、边界情况 |
| `_decode_candidates` | 6 | 原始值包含、换行 unescape、unicode、mojibake 修复候选 |
| `_unwrap_ci_text` | 6 | Python repr、正则回退、无包装、多个 text block |
| `_extract_crawler_output` | 10 | B64/JSON 定界符、裸 JSON、json block、assistant text、CI 包装 |
| `_ensure_ascii_safe` | 13 | dict key/value、list 项、非字符串、5 语言往返 |
| 完整管道 | 6 | 250 条 中文/日文/法语/混合/符号 数据集 |

### 3.4 invoke 流程 — 36 个测试

| 范围 | 测试数 | 说明 |
|---|---|---|
| `_auto_select_skill` | 7 | JSON 响应、名称匹配回退、无效 JSON、字符串消息格式 |
| Payload 解析 | 6 | 完整/最小/空 payload、args 覆盖、browser 标志 |
| 响应结构 | 8 | 全部必要字段、类型、auto_selected、browser_used、ASCII 安全 |
| output=None 重试 | 2 | 重试触发、重试结果被采用 |
| Mojibake 重试 | 3 | 检测到 mojibake→重试、干净输出→不重试、损坏内容被替换 |
| 可观测性 | 3 | 静默失败、AWS 错误、env var 默认值 |
| `_RefreshingAWS4Auth` | 2 | 每次调用刷新凭证、正确的 region/service |
| 技能选择 | 5 | 显式跳过 LLM、未知回退、system prompt、browser hint |

### 3.5 云端 E2E 框架 — 6 通过 + 23 跳过

| 范围 | 测试数 | 说明 |
|---|---|---|
| 框架自测 | 6 ✅ | `_unescape` 函数、必要变量列表、skip 逻辑 |
| 健康检查 | 4（跳过） | 设置 `AGENTCORE_RUNTIME_ID` 等后激活 |
| 技能路由 | 6（跳过） | 全部 6 个技能 + 自动选择 |
| 功能性爬取 | 4（跳过） | API / 电商 / 新闻 / default 真实站点 |
| 编码 E2E | 3（跳过） | CJK 经云端传输层往返 |
| Browser 存在性 | 2（跳过） | `browser_used=False` 基线；完整测试需要 `BROWSER_ID` |
| 性能基准 | 4（跳过） | 端到端 invoke 延迟（需 `CLOUD_PERF_TEST=1`） |

---

## 四、性能基准

所有基准在本地运行，仅测量计算开销（不含网络 I/O）。

### 4.1 技能加载

基准：100 次迭代（`list_skills`）/ 50 次迭代（`load_skill`）

| 操作 | 平均耗时 | P95 |
|---|---|---|
| `list_skills()` — 扫描 6 个技能目录 | 0.202 ms | 0.260 ms |
| `load_skill("default-crawl")` | 0.100 ms | 0.110 ms |
| `load_skill("ecommerce-crawl")` | 0.115 ms | 0.127 ms |
| `load_skill("news-crawl")` | 0.117 ms | 0.128 ms |
| `load_skill("api-crawl")` | 0.099 ms | 0.112 ms |
| `load_skill("docs-crawl")` | 0.125 ms | 0.183 ms |
| `load_skill("social-crawl")` | 0.116 ms | 0.131 ms |

> 所有技能加载 P95 均 < 0.3 ms，对请求总延迟影响可忽略。

### 4.2 编码管道

基准：100 次迭代，输入为 250 条电影数据（含 CJK 字段）

| 操作 | 平均耗时 | P95 |
|---|---|---|
| `_ensure_ascii_safe(250 items)` | 4.748 ms | 4.975 ms |
| Base64 编码 + 解码往返（250 条） | 8.109 ms | 8.339 ms |

> 250 条记录完整编码/解码耗时 < 10 ms，不是性能瓶颈。

### 4.3 Tier 分级

基准：10,000 次迭代

| 指标 | 耗时 |
|---|---|
| 平均 | 0.0015 ms |
| P95 | 0.0016 ms |
| P99 | 0.0016 ms |

> 每次请求 < 0.002 ms，完全无感知。

### 4.4 Mojibake 检测

基准：1,000 次迭代，输入为 250 条 CJK JSON 字符串

| 操作 | 平均耗时 | P95 |
|---|---|---|
| `_looks_like_mojibake()` | 8.8 ms | 9.1 ms |

> 每次响应触发一次，9 ms 在此数据量下可接受。

### 4.5 集成网络延迟（真实 HTTP）

| URL | 状态码 | 延迟 |
|---|---|---|
| `jsonplaceholder.typicode.com/users` | 200 | 57.4 ms |
| `jsonplaceholder.typicode.com/posts?_limit=10` | 200 | 67.1 ms |
| `books.toscrape.com` | 200 | 132.7 ms |
| `news.ycombinator.com` | 200 | 287.1 ms |

---

## 五、性能总结

| 环节 | 典型耗时 | 占总请求比 |
|---|---|---|
| 技能加载 | < 0.3 ms | 可忽略 |
| Tier 分级 | < 0.002 ms | 可忽略 |
| 编码管道（250 条） | < 10 ms | 可忽略 |
| Mojibake 检测 | < 10 ms | 可忽略 |
| 实际 HTTP 爬取（OPEN 站点） | 57 – 290 ms | **主要耗时** |
| LLM 推理（Claude ConverseStream） | 10 – 60 s | **主要耗时** |

> 本地计算开销合计 < 20 ms，请求总延迟由网络 I/O 和 LLM 推理决定。

---

## 六、云端 E2E 测试激活方法

云端 E2E 测试（23 个）在本地/CI 中默认跳过，设置以下环境变量后自动激活：

```bash
export AGENTCORE_RUNTIME_ID=<runtime-id>
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=<account-id>
# 可选：
export AGENTCORE_ENDPOINT_NAME=crawlerEndpoint
export BROWSER_ID=<browser-id>       # 启用 Browser 测试
export CLOUD_PERF_TEST=1             # 启用性能基准测试

python -m pytest tests/test_cloud_e2e.py -v
```

云端测试分组：
- **健康检查**（4 个）：Runtime 可达性、响应结构验证
- **技能路由**（6 个）：6 个技能显式路由 + 自动选择
- **功能性爬取**（4 个）：API / 电商 / 新闻 / default 真实站点
- **编码 E2E**（3 个）：CJK 经云端传输层往返
- **Browser 存在性**（2 个）：`browser_used=False` 基线；完整测试需要 `BROWSER_ID`
- **性能基准**（4 个）：端到端 invoke 延迟（需 `CLOUD_PERF_TEST=1`）

---

## 七、已知限制

| 项目 | 说明 |
|---|---|
| 云端 E2E 测试 | 需要 AgentCore Runtime 部署；本地/CI 按设计跳过 |
| Browser 完整爬取 | 需要 `BROWSER_ID` 环境变量和已部署的 AgentCore Browser 实例 |
| STRICT 级别站点（豆瓣等） | 需要真实云端 Code Interpreter，本地无法测试 |
| LLM 依赖的自动选择 | `_auto_select_skill` 用 mock LLM 测试；真实 LLM 选择在云端 E2E 验证 |
