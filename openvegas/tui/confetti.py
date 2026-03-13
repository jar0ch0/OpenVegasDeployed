"""Terminal-safe confetti renderer for short win celebrations."""

from __future__ import annotations

import random
import time

from rich.console import Console, RenderableType
from rich.live import Live
from rich.panel import Panel

_ASCII_GLYPHS = ("*", "+", "x", ".")
_PANEL_MIN_WIDTH = 24


def render_confetti(console: Console, frames: int = 10, width: int = 52) -> None:
    """Render a bounded confetti burst.

    Keeps animation short to avoid blocking terminal interaction.
    """
    colors = ["red", "yellow", "green", "cyan", "magenta", "blue"]
    glyphs = ["*", "+", "x", "."]
    for _ in range(max(1, frames)):
        line = "".join(
            f"[{random.choice(colors)}]{random.choice(glyphs)}[/]" for _ in range(max(8, width))
        )
        console.print(line)
        time.sleep(0.02)


def _build_panel(content: RenderableType, title: str, panel_width: int | None = None) -> Panel:
    kwargs: dict = {"title": title, "expand": False}
    if panel_width is not None:
        kwargs["width"] = panel_width
    return Panel(content, **kwargs)


def _capture_lines(console: Console, renderable: RenderableType) -> list[str]:
    temp_console = Console(
        width=max(20, console.width),
        record=True,
        force_terminal=False,
        color_system=None,
        highlight=False,
    )
    with temp_console.capture() as capture:
        temp_console.print(renderable)
    captured = capture.get().rstrip("\n")
    return captured.splitlines() or [""]


def _fit_panel_lines(
    console: Console,
    content: RenderableType,
    title: str,
    panel_width: int | None,
    confetti_pad_x: int,
) -> tuple[list[str], int]:
    terminal_width = max(40, console.width)
    candidate_lines = _capture_lines(console, _build_panel(content, title, panel_width))
    line_width = max(len(line) for line in candidate_lines)

    for pad in range(max(0, confetti_pad_x), -1, -1):
        if line_width + (pad * 2) <= terminal_width:
            return candidate_lines, pad

    max_panel_width = max(_PANEL_MIN_WIDTH, terminal_width)
    for width in range(max_panel_width, _PANEL_MIN_WIDTH - 1, -1):
        candidate_lines = _capture_lines(console, _build_panel(content, title, width))
        line_width = max(len(line) for line in candidate_lines)
        if line_width <= terminal_width:
            return candidate_lines, 0

    return [], 0


def _random_confetti_line(width: int, rng: random.Random) -> str:
    return "".join(rng.choice(_ASCII_GLYPHS) for _ in range(max(1, width)))


def _build_confetti_frame(
    panel_lines: list[str],
    pad_x: int,
    pad_y: int,
    rng: random.Random,
) -> str:
    panel_width = max(len(line) for line in panel_lines)
    framed_width = panel_width + (pad_x * 2)
    lines: list[str] = []

    for _ in range(max(0, pad_y)):
        lines.append(_random_confetti_line(framed_width, rng))

    for panel_line in panel_lines:
        left = _random_confetti_line(pad_x, rng) if pad_x > 0 else ""
        right = _random_confetti_line(pad_x, rng) if pad_x > 0 else ""
        lines.append(f"{left}{panel_line.ljust(panel_width)}{right}")

    for _ in range(max(0, pad_y)):
        lines.append(_random_confetti_line(framed_width, rng))

    return "\n".join(lines)


def render_panel_with_confetti(
    console: Console,
    content: RenderableType,
    title: str = "Result",
    *,
    animate: bool = True,
    frames: int = 10,
    frame_delay: float = 0.06,
    confetti_pad_x: int = 4,
    confetti_pad_y: int = 1,
    panel_width: int | None = None,
    persist: bool = True,
) -> None:
    panel = _build_panel(content, title, panel_width)

    if not console.is_terminal or console.is_dumb_terminal:
        console.print(panel)
        return

    panel_lines, pad_x = _fit_panel_lines(
        console,
        content,
        title,
        panel_width,
        confetti_pad_x,
    )
    if not panel_lines:
        console.print(panel)
        return

    if animate:
        try:
            with Live("", console=console, transient=True, refresh_per_second=30) as live:
                for _ in range(max(1, frames)):
                    live.update(
                        _build_confetti_frame(
                            panel_lines,
                            pad_x,
                            confetti_pad_y,
                            random.Random(),
                        )
                    )
                    time.sleep(max(0.0, frame_delay))
        except KeyboardInterrupt:
            console.print(panel)
            return
        except Exception:
            console.print(panel)
            return

    if persist:
        final_rng = random.Random(0)
        final_frame = _build_confetti_frame(panel_lines, pad_x, confetti_pad_y, final_rng)
        console.print(final_frame)


def render_result_panel(
    console: Console,
    content: RenderableType,
    *,
    is_win: bool,
    animation_enabled: bool,
    title: str = "Result",
) -> None:
    """Render result output through a single styling path.

    Win outcomes get result-centered confetti framing; everything else stays a
    standard panel for readability and consistency.
    """
    if not is_win:
        console.print(Panel(content, title=title))
        return

    render_panel_with_confetti(
        console,
        content,
        title=title,
        animate=bool(animation_enabled),
        persist=True,
    )
