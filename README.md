# AI Literature Review Pipeline

This project turns a folder of Markdown papers into a structured literature review workflow.
It is designed for Chinese academic review writing and uses an OpenAI-compatible DeepSeek API by default.

## Quick Start

1. Put paper Markdown files into `papers_md/`.
2. Copy `.env.example` to `.env` and fill in `DEEPSEEK_API_KEY`.
3. Edit `project_config/review_brief.md` for your review topic.
4. Run the pipeline step by step:

```bash
python3 scripts/01_inventory.py
python3 scripts/02_extract_cards.py
python3 scripts/03_quality_check.py
python3 scripts/04_select_core_papers.py
python3 scripts/05_synthesize_dimensions.py
python3 scripts/05_evidence_matrix.py
python3 scripts/06_generate_outline.py
python3 scripts/07_write_review.py
```

Each script is resumable by default: existing outputs are skipped unless you pass `--force`.

## Main Outputs

- `outputs/literature_cards/`: one structured card per paper, in JSON and Markdown.
- `outputs/screening/`: batch screening and final core paper selection.
- `outputs/synthesis/`: cross-paper synthesis by dimension.
- `outputs/evidence_index/`: evidence matrix for traceable claims.
- `outputs/drafts/`: review outline, section drafts, and final merged draft.

## Useful Commands

Run only the first 3 papers for testing:

```bash
python3 scripts/02_extract_cards.py --limit 3
```

Regenerate cards even if outputs already exist:

```bash
python3 scripts/02_extract_cards.py --force
```

Run only one synthesis dimension:

```bash
python3 scripts/05_synthesize_dimensions.py --dimension 研究方法
```

Write only one section:

```bash
python3 scripts/07_write_review.py --section-title "研究方法综述"
```

## API Settings

The scripts read settings from `.env` or environment variables:

```bash
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TEMPERATURE=0.2
DEEPSEEK_TIMEOUT=180
```

If your provider exposes a full chat completions URL, set `DEEPSEEK_BASE_URL` to that full URL.
