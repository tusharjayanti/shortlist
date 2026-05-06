# Data Contract

Shortlist separates user data from system code. This means
you can pull updates from upstream without losing your
personalization, and your personal data never leaves your
machine.

## User Layer (NEVER auto-updated)

These files contain your personal data and customization.
They are gitignored. Pull requests should never modify them.

- `config.yaml` — your candidate profile, archetypes, company
  tiers, ATS slugs
- `experience.md` — your career corpus (richer than any resume)
- `resume/resume.tex` — your LaTeX resume with current content.
  The tailor uses this as both the template (structure,
  formatting) and as a source of existing bullets to keep,
  reword, or replace
- `.env` — your API keys

For each there is a corresponding `*.example.*` file that IS
committed and shows the format.

## System Layer (can be updated from upstream)

These files are system code and templates. They should not
contain personal information.

- `agents/*.py` — agent logic
- `tools/*.py` — utilities
- `tracker/*.py` — database layer
- `coordinator/*.py` — feedback loop
- `flows/*.py` — orchestration
- `prompts/*.md` — system prompts (shared across all users)
- `tests/` — test suite

## When personalizing

1. Edit user-layer files only
2. To customize prompts, fork the repo and edit prompts/*.md
3. Never edit agents/*.py to add personal information
