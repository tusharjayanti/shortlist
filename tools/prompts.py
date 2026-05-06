from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a system prompt from prompts/<name>.md."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        available = [p.stem for p in PROMPTS_DIR.glob("*.md")]
        raise FileNotFoundError(
            f"Prompt file not found: {path}. "
            f"Available: {available}"
        )
    return path.read_text()
