"""Compile LaTeX sources to PDF using a temporary directory and ``pdflatex``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


class TexCompileError(RuntimeError):
    """Raised when ``pdflatex`` fails or the PDF output is missing."""

    def __init__(self, message: str, *, log_excerpt: str) -> None:
        """Initialize a compile error with a short log excerpt for UI or logging.

        Args:
            message: Human-readable summary of the failure.
            log_excerpt: Trailing portion of stderr/stdout from the TeX run.
        """
        super().__init__(message)
        self.log_excerpt: str = log_excerpt


class TexCompiler:
    """Run ``pdflatex`` on a single ``.tex`` document inside a temporary working directory."""

    def __init__(
        self,
        *,
        pdflatex_command: str = "pdflatex",
        passes: int = 2,
    ) -> None:
        """Configure the compiler executable and number of LaTeX passes.

        Args:
            pdflatex_command: Executable name or path for pdfLaTeX.
            passes: How many times to invoke pdfLaTeX (some documents need two passes).
        """
        self._pdflatex_command: str = pdflatex_command
        self._passes: int = max(1, passes)

    def compile_to_pdf(self, latex_source: str, *, jobname: str = "document") -> bytes:
        """Write ``latex_source`` to a temp ``.tex`` file and compile it to PDF.

        Args:
            latex_source: Full LaTeX document source.
            jobname: Basename (no extension) for the ``.tex`` / ``.pdf`` files in the temp dir.

        Returns:
            Raw PDF file bytes.

        Raises:
            TexCompileError: If the engine is missing, the process fails, or PDF is not produced.
        """
        if shutil.which(self._pdflatex_command) is None:
            raise TexCompileError(
                f"Executable not found on PATH: {self._pdflatex_command!r}. "
                "Install MiKTeX or TeX Live and ensure pdflatex is available.",
                log_excerpt="",
            )

        safe_job = Path(jobname).name
        if not safe_job or safe_job.strip(".") == "":
            safe_job = "document"

        tex_path: Path | None = None
        pdf_path: Path | None = None
        combined_log: list[str] = []

        with TemporaryDirectory(prefix="resume_customizer_tex_") as tmp:
            root = Path(tmp)
            tex_path = root / f"{safe_job}.tex"
            # Normalize newlines so CRLF / odd uploads match what most TeX setups expect; avoids rare
            # ``\par''/titlesec failures when a blank line appears inside a braced argument.
            normalized = latex_source.replace("\r\n", "\n").replace("\r", "\n")
            if normalized.startswith("\ufeff"):
                normalized = normalized[1:]
            tex_path.write_text(normalized, encoding="utf-8", newline="\n")
            pdf_path = root / f"{safe_job}.pdf"

            for _ in range(self._passes):
                proc = subprocess.run(
                    [
                        self._pdflatex_command,
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        f"-jobname={safe_job}",
                        str(tex_path.name),
                    ],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                chunk = _format_process_output(proc)
                if chunk:
                    combined_log.append(chunk)

                if proc.returncode != 0:
                    excerpt = _tail("\n\n".join(combined_log), limit=6000)
                    raise TexCompileError(
                        "pdfLaTeX reported an error (see log excerpt).",
                        log_excerpt=excerpt,
                    )

            if not pdf_path.is_file():
                excerpt = _tail("\n\n".join(combined_log), limit=6000)
                raise TexCompileError(
                    "pdfLaTeX finished but the PDF file was not created.",
                    log_excerpt=excerpt,
                )

            return pdf_path.read_bytes()


def _format_process_output(proc: subprocess.CompletedProcess[str]) -> str:
    """Combine stdout and stderr from a completed process into one string.

    Args:
        proc: Completed process with optional captured ``stdout`` / ``stderr``.

    Returns:
        Non-empty string if either stream has content; otherwise empty string.
    """
    parts: list[str] = []
    if proc.stdout:
        parts.append(proc.stdout.strip())
    if proc.stderr:
        parts.append(proc.stderr.strip())
    return "\n".join(p for p in parts if p)


def _tail(text: str, *, limit: int) -> str:
    """Return the last ``limit`` characters of ``text``.

    Args:
        text: Arbitrary log text.
        limit: Maximum number of characters to keep from the end.

    Returns:
        Possibly truncated string (never longer than ``limit``).
    """
    if len(text) <= limit:
        return text
    return text[-limit:]
