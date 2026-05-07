# Contributing

Thanks for considering a contribution. This is primarily a
personal portfolio project, but I welcome PRs in these areas:

## Areas for contribution

- **New ATS providers** — add a scanner in `tools/ats_scanner.py`
- **New LLM providers** — add a class in `tools/llm.py`
  following the AnthropicProvider pattern
- **Improved prompts** — system prompts in `prompts/*.md`
  are designed to be edited
- **Corpus parser improvements** — `tools/corpus.py` handles
  most Markdown but could be more robust

## Development workflow

1. Fork the repo
2. Create a branch from `main`
3. Make changes with tests
4. Run the full suite: `uv run pytest -v`
5. Make sure `./shortlist` still boots cleanly
6. Open a PR with a clear description

## What stays personal

Per the [data contract](DATA_CONTRACT.md), never modify:
- `config.yaml`, `experience.md`, `resume/resume.tex`
  (user data)
- `.env` (API keys)

These are gitignored. Only edit the `*.example.*` versions
if you're improving the templates themselves.

## Code style

- Type hints on public functions
- Pydantic for all agent input/output schemas
- `@audited` decorator on every LLM-calling method
- No raw SQL outside `tracker/`
