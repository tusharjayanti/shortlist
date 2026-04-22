from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class CompilationError(Exception):
    pass


def check_pdflatex_available() -> bool:
    return shutil.which("pdflatex") is not None


def compile_pdf(tex_path: str, output_dir: str = "output") -> str:
    if not check_pdflatex_available():
        raise FileNotFoundError(
            "pdflatex not found. Install TeX Live or MacTeX:\n"
            "  macOS:  brew install --cask mactex-no-gui\n"
            "  Ubuntu: sudo apt install texlive-latex-base"
        )

    tex = Path(tex_path).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-output-directory", str(out_dir),
        str(tex),
    ]

    result = subprocess.run(cmd, cwd=str(out_dir), timeout=60, capture_output=True, text=True)
    # Run twice so cross-references resolve
    result = subprocess.run(cmd, cwd=str(out_dir), timeout=60, capture_output=True, text=True)

    pdf_path = out_dir / (tex.stem + ".pdf")
    if not pdf_path.exists() or result.returncode != 0:
        log_snippet = (result.stdout + result.stderr)[-2000:]
        raise CompilationError(
            f"pdflatex failed for {tex_path}.\n\nLog snippet:\n{log_snippet}"
        )

    return str(pdf_path)
