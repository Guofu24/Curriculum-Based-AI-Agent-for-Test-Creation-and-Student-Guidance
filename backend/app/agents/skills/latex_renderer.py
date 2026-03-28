"""LaTeX renderer skill for formula display."""

import re
import html


class LatexRendererSkill:
    """
    Renders formulas to LaTeX with display and unicode fallbacks.
    """

    def render(self, raw_formula: str, context: str = "") -> dict:
        """
        Convert raw formula to LaTeX, display LaTeX, and unicode fallback.

        Returns:
            {
                "latex": "F = ma",
                "display_latex": "\\[F = ma\\]",
                "unicode_fallback": "F = m·a",
            }
        """
        # Clean the formula
        latex = self._clean_latex(raw_formula)

        # Create display version
        display_latex = f"\\[ {latex} \\]"

        # Create unicode fallback
        unicode_fallback = self._to_unicode(latex)

        return {
            "latex": latex,
            "display_latex": display_latex,
            "unicode_fallback": unicode_fallback,
        }

    def _clean_latex(self, formula: str) -> str:
        """Clean and normalize LaTeX formula."""
        formula = formula.strip()

        # Remove display delimiters if present
        formula = re.sub(r"^\$\$|\$$", "", formula)
        formula = re.sub(r"^\$|\$$", "", formula)

        # Common LaTeX replacements
        replacements = [
            ("\\cdot", "·"),
            ("\\times", "×"),
            ("\\div", "÷"),
            ("\\pm", "±"),
            ("\\leq", "≤"),
            ("\\geq", "≥"),
            ("\\neq", "≠"),
            ("\\approx", "≈"),
            ("\\alpha", "α"),
            ("\\beta", "β"),
            ("\\gamma", "γ"),
            ("\\theta", "θ"),
            ("\\lambda", "λ"),
            ("\\mu", "μ"),
            ("\\rho", "ρ"),
            ("\\omega", "ω"),
            ("\\Delta", "Δ"),
            ("\\Omega", "Ω"),
            ("\\sin", "sin"),
            ("\\cos", "cos"),
            ("\\tan", "tan"),
            ("\\frac", "/"),
            ("\\sqrt", "√"),
        ]

        cleaned = formula
        for latex_sym, unicode_sym in replacements:
            cleaned = cleaned.replace(latex_sym, unicode_sym)

        # Clean extra braces
        cleaned = re.sub(r"\{([^{}]*)\}", r"\1", cleaned)

        return cleaned.strip()

    def _to_unicode(self, latex: str) -> str:
        """Convert LaTeX to unicode representation."""
        return latex

    def to_html(self, formula: str, display: bool = True) -> str:
        """
        Convert LaTeX to HTML with KaTeX-style rendering.
        For use in web rendering.
        """
        latex = self._clean_latex(formula)

        if display:
            return f'<div class="math-display">{latex}</div>'
        else:
            return f'<span class="math-inline">{latex}</span>'
