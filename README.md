# Crawler Agent — AgentCore Runtime + Code Interpreter

A Strands agent that generates web crawler Python code based on customizable
skills, executes it in AgentCore Code Interpreter (PUBLIC network mode),
and returns structured JSON results with full CJK/Unicode support.

## Architecture

![architecture](architecture.drawio)

```
User prompt ──▶ crawler_cli.py ──▶ AgentCore Runtime (main.py)
                                        │
                                   ① Skill Selector (LLM picks best skill)
                                        │
                                   ② Load SKILL.md → system prompt
                                        │
                                   ③ Strands Agent generates Python crawler
                                        │
                                   ④ Code Interpreter executes script
                                        │         │
                                        │    HTTP requests → Target Website
                                        │
                                   ⑤ Extract output (unwrap CI format, decode base64/JSON)
                                        │
                                   ⑥ ASCII-safe encode → transport → CLI
                                        │
                                   ⑦ CLI decodes unicode, displays & saves JSON
```

> Open `architecture.drawio` in draw.io or VS Code draw.io extension for the full diagram.

## Skills

Six built-in crawl skills under `skills/`:

| Skill | Description |
|-------|-------------|
| `default-crawl` | General-purpose — extracts title, links, text content |
| `ecommerce-crawl` | Product listings — names, prices, images, availability |
| `news-crawl` | News & articles — headlines, authors, dates, body text |
| `api-crawl` | REST API / JSON endpoints — pagination, nested resources |
| `docs-crawl` | Documentation / Wiki — headings, code blocks, hierarchy |
| `social-crawl` | Forums & social media — posts, timestamps, engagement |

Each skill is a directory with `SKILL.md` (frontmatter + instructions), optional
`reference.md`, and `examples/sample-output.json`. Drop a new directory in
`skills/` with a `SKILL.md` to add your own crawl style.

## Quick Start

```bash
cd crawler-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Deploy & Run

```bash
# Deploy to AgentCore
agentcore deploy

# Run via CLI (auto-selects skill)
python crawler_cli.py --output movies.json "爬取豆瓣电影TOP250"

# Specify language
python crawler_cli.py --lang en "Scrape https://books.toscrape.com for book prices"

# Force a specific skill
python crawler_cli.py --skill news-crawl "Fetch headlines from https://news.ycombinator.com"

# Interactive mode
python crawler_cli.py
```

### Direct agentcore invoke

```bash
# Default skill
agentcore invoke '{"prompt": "Crawl https://example.com"}'

# Specific skill + positional args
agentcore invoke '{"prompt": "Crawl product listings", "skill": "ecommerce-crawl", "args": "https://books.toscrape.com 3"}'
```

### Local Development

```bash
agentcore dev
# In another terminal:
agentcore invoke --dev '{"prompt": "Crawl https://example.com"}'
# Or via CLI:
python crawler_cli.py --dev "Crawl https://example.com"
```

## Example Output

```
$ python crawler_cli.py --output movies.json "爬取豆瓣电影TOP250前10部电影的名称和评分"

🕷️  爬虫智能体 — 用自然语言创建爬虫
────────────────────────────────────────────────────────────
⏳ 正在分析请求并执行爬虫...
🎯 使用技能: ecommerce-crawl (自动选择)

🤖 Agent 回复:
爬取成功！已获取豆瓣电影TOP250前10部电影...

📊 爬取结果:
────────────────────────────────────────────────────────────
success: True
total_count: 10
movies:
  [0]
    rank: 1
    name: 肖申克的救赎
    rating: 9.7
    english_name: The Shawshank Redemption
    year: 1994
  [1]
    rank: 2
    name: 霸王别姬
    rating: 9.6
    english_name: Farewell My Concubine
    year: 1993
  ...

💾 结果已保存到 movies.json
```

## Encoding Pipeline

The AgentCore transport layer corrupts non-ASCII bytes (C1 control range 0x80–0x9F).
The agent uses a multi-layer encoding pipeline to preserve CJK characters:

1. **SKILL.md** instructs the LLM to use `_safe_output()` — base64-encodes JSON before printing
2. **`_extract_crawler_output()`** unwraps the Code Interpreter's `[{'type':'text','text':'...'}]` wrapper, then decodes base64 or parses bare JSON
3. **`_ensure_ascii_safe()`** escapes all non-ASCII to `\uXXXX` before returning to the runtime
4. **`crawler_cli.py`** decodes `\uXXXX` back to real characters for display and file output

## Tests

73 unit tests covering skills, payload routing, output extraction, encoding round-trips, and mojibake detection.

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test files
python -m pytest tests/test_agent_wiring.py -v      # Agent wiring + encoding tests
python -m pytest tests/test_customer_inputs.py -v    # Skill routing + extraction
python -m pytest tests/test_skills.py -v             # Skill loading + frontmatter
```

### Test Examples

```bash
$ python -m pytest tests/ -v

tests/test_agent_wiring.py::test_system_prompt_includes_skill PASSED
tests/test_agent_wiring.py::test_payload_parsing PASSED
tests/test_agent_wiring.py::test_skill_metadata_in_response PASSED
tests/test_agent_wiring.py::test_extract_crawler_output PASSED
tests/test_agent_wiring.py::test_base64_extraction PASSED
tests/test_agent_wiring.py::test_ensure_ascii_safe_roundtrip PASSED
tests/test_agent_wiring.py::test_mojibake_detection PASSED
tests/test_customer_inputs.py::TestSkillDiscovery::test_all_skills_listed PASSED
tests/test_customer_inputs.py::TestSkillDiscovery::test_skill_count PASSED
tests/test_customer_inputs.py::TestDefaultCrawlCustomerInputs::test_simple_url PASSED
tests/test_customer_inputs.py::TestEcommerceCrawlCustomerInputs::test_product_page_with_pagination PASSED
tests/test_customer_inputs.py::TestNewsCrawlCustomerInputs::test_news_homepage PASSED
tests/test_customer_inputs.py::TestApiCrawlCustomerInputs::test_rest_api_endpoint PASSED
tests/test_customer_inputs.py::TestDocsCrawlCustomerInputs::test_readthedocs_url PASSED
tests/test_customer_inputs.py::TestSocialCrawlCustomerInputs::test_forum_thread PASSED
tests/test_customer_inputs.py::TestPayloadRouting::test_explicit_ecommerce_skill PASSED
tests/test_customer_inputs.py::TestOutputExtraction::test_ecommerce_output PASSED
tests/test_customer_inputs.py::TestEdgeCases::test_unicode_in_arguments PASSED
tests/test_skills.py::test_list_skills PASSED
tests/test_skills.py::test_load_default_skill PASSED
tests/test_skills.py::test_frontmatter_parsing PASSED
...
============================== 73 passed in 0.04s ==============================
```

## Project Structure

```
crawler-agent/
├── src/
│   ├── main.py              # Agent entrypoint — invoke(), extraction, encoding
│   └── skills.py            # Skill loader (frontmatter, $ARGUMENTS substitution)
├── crawler_cli.py           # Interactive CLI client
├── skills/
│   ├── default-crawl/       # Each skill: SKILL.md + examples/ + optional reference.md
│   ├── ecommerce-crawl/
│   ├── news-crawl/
│   ├── api-crawl/
│   ├── docs-crawl/
│   └── social-crawl/
├── tests/
│   ├── test_agent_wiring.py     # Agent wiring, encoding, extraction tests
│   ├── test_customer_inputs.py  # Skill routing, payload, edge cases
│   └── test_skills.py           # Skill loading, frontmatter parsing
├── architecture.drawio      # Architecture diagram (open in draw.io)
├── pyproject.toml
└── requirements.txt
```
