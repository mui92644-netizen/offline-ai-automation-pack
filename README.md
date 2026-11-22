# 1Min AI Agent Automation 🚀
AI-powered browser automation for scraping, creating, saving & editing files via a live browser UI. Driven by config, backed by FreeLLMAPI.

## 🔑 Features
- Observe → Decide → Act → Verify feedback loop
- Config-driven routing, fallback chains & file policies
- FreeLLMAPI `/v1` compatible LLM proxy integration
- Secure download/upload filtering (ext whitelist + size limit)
- Deterministic reference tracking (`@e0`, `@e1…`) to prevent UI-breakage

## 🛠 Quick Setup
```bash
git clone https://github.com/mui92644-netizen/1min-ai-agent-automation.git
cd 1min-ai-agent-automation
pip install -r requirements.txt
playwright install chromium
cp .env.example .env  # fill FREEAPI_AGENT_KEY
python main.py "https://example.com" "Download latest report" "scrape"
