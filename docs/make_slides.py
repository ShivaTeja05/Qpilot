"""Build docs/slides.pdf (4 slides) and docs/threshold.gif from the engine's own output.

Every study number on the slides is read from a results.json (``qpilot run --out``; the demo
study by default) or from validation/validation.json and rendered with the fact's own format.
Engineering claims are printed only when the flag that backs them is given. Usage:

    python docs/make_slides.py [--results PATH] [--ci-green] [--codeql] [--signed-tag TAG]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.animation import FuncAnimation, PillowWriter  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from qpilot.ai.profile import autonomy_policy  # noqa: E402
from qpilot.core.facts import render_fact  # noqa: E402
from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir  # noqa: E402
from qpilot.qpcr.validation import ValidationReport  # noqa: E402
from qpilot.schemas import DecisionCard, StudyResult  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/ShivaTeja05/Qpilot"
VIDEO_URL = f"{REPO_URL}/blob/main/demo/demo.mp4"
ORANGE, INK, GREY, RED = "#ea580c", "#111827", "#6b7280", "#dc2626"
SIZE = (13.333, 7.5)  # 16:9


def fact(result: StudyResult, fid: str) -> str:
    """A fact's value rendered with its own format (raises if it is missing)."""
    return render_fact(result.facts[fid])


def load_study(path: Path | None) -> tuple[StudyResult, list[DecisionCard]]:
    """The study result and cards: from a results.json, else the demo study."""
    if path is not None:
        result = StudyResult.model_validate_json(path.read_text())
        cards_path = path.with_name("cards.json")
        cards = [DecisionCard.model_validate(c) for c in json.loads(cards_path.read_text())]
        return result, cards
    from qpilot.qpcr.study import run_study

    result, cards, _ = run_study(default_cache_dir() / VERMEULEN_FILENAME)
    return result, cards


def demo_curve() -> tuple[np.ndarray, np.ndarray]:
    """One real ODC1 amplification curve (raw fluorescence) from the demo study."""
    from qpilot.io.rdml_io import load, runs

    doc = load(default_cache_dir() / VERMEULEN_FILENAME)
    run = next(r for r in runs(doc, "biomarker_set") if r["id"].startswith("ODC1"))
    raw = run.linRegPCR(updateRDML=False, saveRaw=True)["rawData"]
    values = np.array([float(x) for x in raw[5][5:]])
    return np.arange(1, len(values) + 1), values - values[:8].mean()


def crossing(cycles: np.ndarray, values: np.ndarray, level: float) -> float:
    """The (interpolated) cycle where the curve first reaches ``level``."""
    above = np.nonzero(values >= level)[0][0]
    x0, x1, y0, y1 = cycles[above - 1], cycles[above], values[above - 1], values[above]
    return float(x0 + (level - y0) * (x1 - x0) / (y1 - y0))


def count_tests() -> int:
    """How many tests pytest collects in the repository."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only"],
        cwd=REPO,
        capture_output=True,
        text=True,
    ).stdout
    return int(re.search(r"(\d+) tests? collected", out).group(1))


def wrap(text: str, width: int) -> str:
    """Wrap ``text`` to ``width`` characters per line."""
    return "\n".join(textwrap.wrap(text, width))


def new_slide(title: str, number: int):
    """A blank 16:9 slide with its title and page number."""
    fig = plt.figure(figsize=SIZE)
    fig.patch.set_facecolor("white")
    fig.text(0.04, 0.92, title, fontsize=30, weight="bold", color=INK, va="top")
    fig.text(0.96, 0.03, f"qPilot · {number}/4", fontsize=10, color=GREY, ha="right")
    return fig


def slide_title(pdf, curve):
    """Slide 1: the line that is drawn, on a real curve."""
    cycles, values = curve
    fig = plt.figure(figsize=SIZE)
    fig.text(0.05, 0.86, "qPilot", fontsize=56, weight="bold", color=ORANGE, va="top")
    fig.text(0.05, 0.70, wrap("Every qPCR result rests on where one line is drawn.", 26),
             fontsize=26, color=INK, va="top")  # fmt: skip
    fig.text(0.05, 0.52, "Nobody writes down where.", fontsize=26, color=INK, va="top",
             weight="bold")  # fmt: skip
    fig.text(0.05, 0.18, "Open source · runs on your laptop · research use only",
             fontsize=14, color=GREY)  # fmt: skip
    ax = fig.add_axes([0.52, 0.16, 0.44, 0.68])
    ax.plot(cycles, values, color=INK, lw=2.2)
    peak = values.max()
    for level, colour in ((0.04 * peak, "#16a34a"), (0.12 * peak, ORANGE), (0.30 * peak, RED)):
        cq = crossing(cycles, values, level)
        ax.axhline(level, color=colour, ls="--", lw=1.4)
        ax.plot([cq], [level], "o", color=colour, ms=9)
        ax.annotate(f"Cq {cq:.1f}", (cq, level), xytext=(8, -14), textcoords="offset points",
                    color=colour, fontsize=12, weight="bold")  # fmt: skip
    ax.set_xlabel("PCR cycle", fontsize=12)
    ax.set_ylabel("fluorescence", fontsize=12)
    ax.set_title("One real ODC1 well from the demo study: three lines, three answers",
                 fontsize=12, color=GREY)  # fmt: skip
    ax.spines[["top", "right"]].set_visible(False)
    pdf.savefig(fig)
    plt.close(fig)


def slide_problem(pdf, curve):
    """Slide 2: what was not working (callouts and the audit numbers)."""
    cycles, values = curve
    fig = new_slide("What wasn't working", 2)
    ax = fig.add_axes([0.05, 0.12, 0.50, 0.66])
    ax.plot(cycles, values, color=INK, lw=2)
    ax.axhline(0.12 * values.max(), color=ORANGE, ls="--", lw=1.4)
    ax.set_xlabel("PCR cycle")
    ax.set_ylabel("fluorescence")
    ax.spines[["top", "right"]].set_visible(False)
    callouts = [
        "Each plate gets its own hidden threshold and baseline, and every number moves with them.",
        "No record of the choices: which reference genes, which wells dropped, which cut-off.",
        "No way for a script or an AI agent to ask: would the answer survive a different choice?",
    ]
    for i, text in enumerate(callouts):
        box = {"boxstyle": "round,pad=0.5", "fc": "white", "ec": RED, "lw": 1.5}
        fig.text(0.08, 0.70 - i * 0.17, f"{i + 1}. " + wrap(text, 44), fontsize=13, color=RED,
                 va="top", bbox=box)  # fmt: skip
    stats = [("5 %", "of papers validate their reference genes"),
             ("1 %", "report amplification efficiency"),
             ("#4", "lab-instrument software, on this hackathon's own survey")]  # fmt: skip
    for i, (big, small) in enumerate(stats):
        y = 0.74 - i * 0.19
        fig.text(0.62, y, big, fontsize=44, weight="bold", color=ORANGE, va="top")
        fig.text(0.75, y - 0.02, wrap(small, 30), fontsize=15, color=INK, va="top")
    fig.text(0.62, 0.12, wrap("Bustin & Wittwer, Clinical Chemistry, 28 Jan 2026, "
                              "doi:10.1093/clinchem/hvaf176 (355 papers)", 60),
             fontsize=10, color=GREY)  # fmt: skip
    pdf.savefig(fig)
    plt.close(fig)


def slide_solution(pdf, result, cards):
    """Slide 3: the three things qPilot does, with the card-1 numbers."""
    fig = new_slide("What qPilot does", 3)
    flipping = sum(1 for c in cards if c.impact.get("flips"))
    lines = [
        ("One", f"Reads the raw curves of all {fact(result, 'f_n_plates')} plates "
                f"({fact(result, 'f_n_reactions')} reactions) and analyses every plate with the "
                "same published method and settings, written down."),
        ("Two", f"Finds the {flipping} choices that could change a conclusion. A person decides "
                "each one, and the reason goes in the record."),
        ("Three", f"Tests every conclusion under {fact(result, 'f_n_cells')} reasonable analyses: "
                  f"ODC1 holds in {fact(result, 'f_holds_odc1')}, NM23A in "
                  f"{fact(result, 'f_holds_nm23a')}. Any AI can ask, with numbers it cannot "
                  "invent."),
    ]  # fmt: skip
    for i, (head, text) in enumerate(lines):
        y = 0.76 - i * 0.18
        fig.text(0.05, y, head, fontsize=22, weight="bold", color=ORANGE, va="top")
        fig.text(0.16, y, wrap(text, 70), fontsize=17, color=INK, va="top")
    card1 = (
        f"Card 1, the reference genes: {fact(result, 'f_n_flipped_refset')} of "
        f"{fact(result, 'f_n_genes')} conclusions change; "
        f"{fact(result, 'f_n_flipped_refset_min3')} even between sets of three or more genes. "
        f"The {fact(result, 'f_ref_pair_top')} ratio itself shifts "
        f"{fact(result, 'f_ref_ratio_top')} between the groups (p = "
        f"{fact(result, 'f_ref_ratio_top_p')})."
    )
    fig.text(0.05, 0.22, wrap(card1, 110), fontsize=14, color=INK, va="top",
             bbox={"boxstyle": "round,pad=0.6", "fc": "#fff7ed", "ec": ORANGE})  # fmt: skip
    fig.text(0.05, 0.07, f"Agent clip: qpilot serve (MCP), shown live · Backup video: {VIDEO_URL}",
             fontsize=11, color=GREY)  # fmt: skip
    pdf.savefig(fig)
    plt.close(fig)


def slide_proof(pdf, result, report, engineering):
    """Slide 4: validation, engineering, security, cost; policy and links."""
    fig = new_slide("Proof", 4)
    n0, bias, cq = report.n0, report.bias, report.cq
    strips = [
        ("Validation", f"Reproduces the RDML consortium's published benchmark on {n0.wells} "
                       f"standard wells: {n0.share_identical:.1%} identical, "
                       f"{n0.share_within:.0%} within 5 %; per-gene bias matches to a median "
                       f"{bias.median_abs_diff:.2f}; a {cq.mean_offset:+.2f}-cycle Cq shift is "
                       "disclosed. Data: Vermeulen 2009 / Ruijter 2013, CC BY 4.0; groups by "
                       "MYCN expression."),
        ("Engineering", engineering),
        ("Security", "Offline by test: the whole analysis runs with the network switched off. "
                     "The app binds 127.0.0.1, telemetry off. An AI sees the facts and the card "
                     "labels, never the raw data; the app shows exactly what it was sent."),
        ("Cost", "Today: €2.4–6k/yr per academic lab for the analysis-and-stats step (Clarida "
                 "Lab €4,800–9,600 as listed; Prism $260–520/seat). qPilot: Apache-2.0, laptop. "
                 "(Does not replace the instrument software, Part 11 editions, or Prism for "
                 "non-qPCR work.)"),
    ]  # fmt: skip
    for i, (head, text) in enumerate(strips):
        y = 0.80 - i * 0.135
        fig.text(0.05, y, head, fontsize=16, weight="bold", color=ORANGE, va="top")
        fig.text(0.19, y, wrap(text.replace("%", " %").replace("  %", " %"), 106),
                 fontsize=12, color=INK, va="top")  # fmt: skip
    policy = "\n".join(autonomy_policy())
    fig.text(0.05, 0.25, "For research use only. Not for clinical or diagnostic use.",
             fontsize=13, weight="bold", color=INK)  # fmt: skip
    fig.text(0.05, 0.215, policy, fontsize=11, color=INK, va="top", linespacing=1.6)
    fig.text(0.05, 0.07, "Built: the decision space, robustness grid, cards, record, app, MCP, "
             "model harness. Borrowed: LinRegPCR (rdmlpython, MIT), geNorm, RDML, the demo data.",
             fontsize=10, color=GREY)  # fmt: skip
    fig.text(0.96, 0.25, REPO_URL.replace("https://", ""), fontsize=16, weight="bold",
             color=ORANGE, ha="right")  # fmt: skip
    pdf.savefig(fig)
    plt.close(fig)


def threshold_gif(curve, target: Path) -> None:
    """The title slide's idea, moving: the line slides and the crossing cycle follows."""
    cycles, values = curve
    peak = values.max()
    levels = np.concatenate([np.linspace(0.03, 0.35, 30), np.linspace(0.35, 0.03, 30)]) * peak
    fig, ax = plt.subplots(figsize=(6, 3.6), dpi=100)
    ax.plot(cycles, values, color=INK, lw=2)
    line = ax.axhline(levels[0], color=ORANGE, ls="--", lw=1.5)
    (dot,) = ax.plot([], [], "o", color=ORANGE, ms=9)
    label = ax.text(0.02, 0.92, "", transform=ax.transAxes, fontsize=13, color=ORANGE,
                    weight="bold")  # fmt: skip
    ax.set_xlabel("PCR cycle")
    ax.set_ylabel("fluorescence")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()

    def frame(i):
        level = levels[i]
        cq = crossing(cycles, values, level)
        line.set_ydata([level, level])
        dot.set_data([cq], [level])
        label.set_text(f"Cq {cq:.1f}")
        return line, dot, label

    FuncAnimation(fig, frame, frames=len(levels), blit=True).save(
        target, writer=PillowWriter(fps=12)
    )
    plt.close(fig)


class _Recorder:
    """Saves each slide to the PDF and, when asked, as a PNG preview."""

    def __init__(self, pdf: PdfPages, preview: Path | None) -> None:
        self.pdf, self.preview, self.n = pdf, preview, 0

    def savefig(self, fig) -> None:
        """Add one slide."""
        self.pdf.savefig(fig)
        self.n += 1
        if self.preview is not None:
            self.preview.mkdir(parents=True, exist_ok=True)
            fig.savefig(self.preview / f"slide_{self.n}.png", dpi=100)


def main(argv: list[str] | None = None) -> int:
    """Build the slides and the GIF."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results", type=Path, default=None, help="results.json (cards.json beside it)"
    )
    parser.add_argument("--ci-green", action="store_true", help="CI is green on main")
    parser.add_argument("--codeql", action="store_true", help="CodeQL is on for the repository")
    parser.add_argument("--signed-tag", default=None, help="the signed release tag, if made")
    parser.add_argument("--out", type=Path, default=REPO / "docs")
    parser.add_argument(
        "--preview", type=Path, default=None, help="also write each slide as PNG here"
    )
    args = parser.parse_args(argv)

    result, cards = load_study(args.results)
    report = ValidationReport.from_dict(
        json.loads((REPO / "validation" / "validation.json").read_text())
    )
    parts = [f"{count_tests()} tests"]
    if args.ci_green:
        parts.append("CI green, pip-audit clean")
    if args.codeql:
        parts.append("CodeQL on")
    parts += ["one-command install", "byte-identical re-run (tested)"]
    if args.signed_tag:
        parts.append(f"signed tag {args.signed_tag} + SBOM")
    parts.append("THREAT_MODEL.md")
    engineering = " · ".join(parts)

    curve = demo_curve()
    args.out.mkdir(parents=True, exist_ok=True)
    with PdfPages(args.out / "slides.pdf") as pdf:
        pages = _Recorder(pdf, args.preview)
        slide_title(pages, curve)
        slide_problem(pages, curve)
        slide_solution(pages, result, cards)
        slide_proof(pages, result, report, engineering)
    threshold_gif(curve, args.out / "threshold.gif")
    print(f"wrote {args.out / 'slides.pdf'} and {args.out / 'threshold.gif'}")
    print(f"engineering strip: {engineering}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
