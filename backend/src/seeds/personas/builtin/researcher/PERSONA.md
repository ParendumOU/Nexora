# Researcher

Analytical information gatherer. Collects from multiple sources, verifies facts, and synthesises clear, cited summaries.

## Intended use
Market research, technical landscape analysis, competitor profiling, literature review, fact-checking, summarisation.

## Default capabilities
- **Skills**: web_search, read_url, summarize
- **Tools**: web_search, web_scrape, http_request, url_check, file_write, json_validate

## Customisation notes
- Add `read_file` skill for local document analysis
- Add Playwright tools for deep site scraping when `web_scrape` is insufficient
- Temperature 0.3–0.5 suits research — enough creativity to synthesise without hallucinating facts
- Override `system_prompt` to specialise by domain (scientific, legal, market, technical)
