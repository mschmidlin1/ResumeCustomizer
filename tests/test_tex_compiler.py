"""Tests for :mod:`resume_customizer.tex_workspace`."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from resume_customizer.tex_workspace import TexCompileError, TexCompiler


def _successful_pdflatex_run(
    cmd: list[str],
    **kwargs: object,
) -> subprocess.CompletedProcess[str]:
    """Simulate pdfLaTeX by creating the expected ``.pdf`` in the temp ``cwd``.

    Args:
        cmd: Invoked command list (first element is the TeX engine).
        kwargs: Must include ``cwd`` pointing at the temp directory.

    Returns:
        A successful :class:`subprocess.CompletedProcess`.
    """
    cwd = Path(str(kwargs["cwd"]))
    job = "document"
    for part in cmd:
        if isinstance(part, str) and part.startswith("-jobname="):
            job = part.split("=", 1)[1]
    pdf = cwd / f"{job}.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


class TestTexCompiler(unittest.TestCase):
    """Tests for :class:`TexCompiler`."""

    @patch("resume_customizer.tex_workspace.subprocess.run")
    @patch("resume_customizer.tex_workspace.shutil.which")
    def test_compile_returns_pdf_bytes(
        self,
        mock_which: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """On success, returns bytes read from the generated PDF."""
        mock_which.return_value = "/usr/bin/pdflatex"
        mock_run.side_effect = _successful_pdflatex_run

        compiler = TexCompiler(pdflatex_command="pdflatex", passes=1)
        pdf_bytes = compiler.compile_to_pdf("\\documentclass{article}\\begin{document}X\\end{document}")

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(mock_run.call_count, 0)

    @patch("resume_customizer.tex_workspace.shutil.which")
    def test_missing_engine_raises(self, mock_which: MagicMock) -> None:
        """If ``pdflatex`` is not on PATH, raises :class:`TexCompileError`."""
        mock_which.return_value = None
        compiler = TexCompiler()
        with self.assertRaises(TexCompileError) as ctx:
            compiler.compile_to_pdf("\\documentclass{article}")
        self.assertIn("PATH", str(ctx.exception))

    @patch("resume_customizer.tex_workspace.subprocess.run")
    @patch("resume_customizer.tex_workspace.shutil.which")
    def test_nonzero_exit_raises(
        self,
        mock_which: MagicMock,
        mock_run: MagicMock,
    ) -> None:
        """A failing pdfLaTeX exit code raises :class:`TexCompileError` with a log excerpt."""
        mock_which.return_value = "/bin/pdflatex"
        mock_run.return_value = subprocess.CompletedProcess(
            ["pdflatex"],
            1,
            stdout="",
            stderr="! LaTeX Error: boom",
        )

        compiler = TexCompiler(passes=1)
        with self.assertRaises(TexCompileError) as ctx:
            compiler.compile_to_pdf("bad")
        self.assertIn("log excerpt", str(ctx.exception).lower() or "pdfLaTeX")
        self.assertIn("boom", ctx.exception.log_excerpt)


@unittest.skipUnless(shutil.which("pdflatex"), "pdflatex not installed")
class TestTexCompilerIntegration(unittest.TestCase):
    """Optional integration test requiring a real ``pdflatex`` on PATH."""

    def test_minimal_document_compiles(self) -> None:
        """A tiny valid LaTeX document produces non-empty PDF bytes."""
        src = "\\documentclass{article}\\begin{document}Hi\\end{document}"
        compiler = TexCompiler(passes=1)
        pdf = compiler.compile_to_pdf(src)
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
