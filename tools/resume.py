from __future__ import annotations

from pathlib import Path


def read_resume(path: str = "resume/resume.tex") -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Resume not found at '{path}'. "
            "Place your LaTeX resume at resume/resume.tex (or pass a custom path)."
        )
    return p.read_text()


def write_tailored_resume(original_tex: str, tailored_tex: str, output_path: str) -> str:
    if len(tailored_tex) < len(original_tex) * 0.70:
        raise ValueError(
            f"Tailored resume ({len(tailored_tex)} chars) is less than 70% of the "
            f"original ({len(original_tex)} chars). Refusing to write a truncated resume."
        )
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(tailored_tex)
    return str(out)
