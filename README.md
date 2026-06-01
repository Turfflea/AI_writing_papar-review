# AI Literature Review Pipeline

This project turns a folder of Markdown papers into a structured literature review workflow.
It is designed for Chinese academic review writing and uses an OpenAI-compatible DeepSeek API by default.

## Quick Start

1. Double-click `start_workbench.command` on macOS, or run:

```bash
python3 scripts/launch_workbench.py
```

2. In the browser workbench, create a new project or select an old one.
3. Edit the review topic and detailed review brief for that project.
4. Upload Markdown papers into the project.
5. Run each step from the visual workflow. Before any AI step, the workbench shows the relevant prompt and output template with a plain-language explanation, so you can edit it before running.

Each project lives in its own folder under `projects/`, with independent papers, prompts, API settings, cards, screening outputs, synthesis files, evidence matrix, and drafts. Project folders are ignored by git so your paper corpus and API keys are not accidentally committed.

The workbench also supports:

- `查看进度` on step 2 to see whether each paper card is pending, successful, or failed.
- `重新生成本步` to rerun the current step with `--force` and overwrite that step's existing outputs.
- `撤回到上一步` to delete the current step and downstream outputs.
- Batch-size control for core-paper screening.

You can still run the pipeline step by step from the terminal:

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

For a specific project folder, prefix commands with `LIT_REVIEW_PROJECT_DIR`:

```bash
LIT_REVIEW_PROJECT_DIR=projects/my_project python3 scripts/01_inventory.py
```

Each script is resumable by default: existing outputs are skipped unless you pass `--force`.

## Human Review Points

You can intervene between steps in the browser workbench or by editing generated outputs directly:

- Edit any generated card in `projects/<project>/outputs/literature_cards/*.card.json` before screening.
- Edit `projects/<project>/project_config/human_overrides.json` to promote/demote core papers, add synthesis notes, outline notes, or section-specific writing instructions.
- After changing core paper overrides, run:

```bash
python3 scripts/04_select_core_papers.py --apply-overrides-only
```

Later scripts read `project_config/human_overrides.json`, so manual decisions are preserved and visible.

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

Run a local smoke test:

```bash
python3 scripts/smoke_test.py
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
