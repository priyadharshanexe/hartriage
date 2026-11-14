"""`hartriage`: analyse and redact HAR files offline. Nothing leaves the machine.

hartriage analyze file.har --format markdown --redacted-out clean.har
hartriage redact file.har -o clean.har
hartriage rules
"""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from hartriage import ENGINE_VERSION, __version__
from hartriage.har.stream_reader import NO_LIMITS, HarFormatError, InputTooLarge, Limits
from hartriage.pipeline import ProcessResult, process
from hartriage.rules import RULE_CLASSES, RuleConfig, Severity
from hartriage.summary import summarise, to_json, to_markdown, to_text

app = typer.Typer(
    name="hartriage",
    help="Redact HAR files and find the failing request. Works offline.",
    no_args_is_help=True,
    add_completion=False,
)


class Format(StrEnum):
    markdown = "markdown"
    text = "text"
    json = "json"


class FailOn(StrEnum):
    never = "never"
    critical = "critical"
    high = "high"
    medium = "medium"
    info = "info"


def _run(
    path: Path, out_path: Path | None, *, rules: list[str] | None, slow_ms: float, no_limits: bool
) -> ProcessResult:
    if out_path is not None and out_path.resolve() == path.resolve():
        raise typer.BadParameter("the redacted output must not overwrite the input")
    limits = NO_LIMITS if no_limits else Limits()
    tmp = out_path.with_name(out_path.name + ".tmp") if out_path else None
    with path.open("rb") as source:
        if tmp is None:
            return process(source, rules=rules, config=RuleConfig(slow_ms=slow_ms), limits=limits)
        try:
            with tmp.open("wb") as out:
                result = process(
                    source, out=out, rules=rules, config=RuleConfig(slow_ms=slow_ms), limits=limits
                )
            tmp.replace(out_path)  # type: ignore[arg-type]
        finally:
            tmp.unlink(missing_ok=True)
        return result


def _fail(message: str) -> None:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2)


@app.command()
def analyze(
    path: Annotated[
        Path,
        typer.Argument(
            exists=True, dir_okay=False, readable=True, help="A .har file (or .har.gz / .zip)."
        ),
    ],
    fmt: Annotated[Format, typer.Option("--format", "-f", help="Output format.")] = Format.markdown,
    redacted_out: Annotated[
        Path | None, typer.Option("--redacted-out", "-o", help="Also write the redacted HAR here.")
    ] = None,
    rules: Annotated[str | None, typer.Option(help="Only these rules, e.g. R001,R002.")] = None,
    slow_ms: Annotated[float, typer.Option(help="Threshold for the slow-request rule.")] = 3000,
    fail_on: Annotated[
        FailOn, typer.Option(help="Exit 1 if a finding is at least this severe.")
    ] = FailOn.never,
    no_limits: Annotated[
        bool, typer.Option(help="Lift the 100 MB / 50,000 request limits.")
    ] = False,
) -> None:
    """Analyse a HAR file and print a ticket-ready summary."""
    try:
        result = _run(
            path,
            redacted_out,
            rules=rules.split(",") if rules else None,
            slow_ms=slow_ms,
            no_limits=no_limits,
        )
    except (HarFormatError, InputTooLarge, ValueError) as exc:
        _fail(str(exc))
        return
    summary = summarise(result)
    if fmt is Format.json:
        output = to_json(
            summary,
            result.findings,
            {
                "stats": result.stats.to_dict(),
                "redaction": result.report.to_dict(),
                "engine_version": ENGINE_VERSION,
                "truncated": result.truncated,
            },
        )
    elif fmt is Format.text:
        output = to_text(summary)
    else:
        output = to_markdown(summary)
    _write_stdout(output)
    if redacted_out is not None:
        typer.secho(f"Redacted copy written to {redacted_out}", err=True, fg=typer.colors.GREEN)
    if fail_on is not FailOn.never:
        limit = Severity(fail_on.value).rank
        if any(f.severity.rank <= limit for f in result.findings):
            raise typer.Exit(code=1)


@app.command()
def redact(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Where to write the redacted HAR.")
    ],
    no_limits: Annotated[bool, typer.Option(help="Lift the size limits.")] = False,
) -> None:
    """Write a redacted copy of a HAR file, safe to attach to a ticket."""
    try:
        result = _run(path, output, rules=["R001"], slow_ms=3000, no_limits=no_limits)
    except (HarFormatError, InputTooLarge, ValueError) as exc:
        _fail(str(exc))
        return
    typer.echo(result.report.sentence())
    typer.secho(f"Redacted copy written to {output}", err=True, fg=typer.colors.GREEN)


@app.command(name="rules")
def list_rules() -> None:
    """List the rules this version runs."""
    for cls in RULE_CLASSES:
        typer.echo(f"{cls.id}  {cls.slug:<15} {cls.summary}")


@app.command()
def version() -> None:
    """Print the tool and rule-engine versions."""
    typer.echo(f"hartriage {__version__} (rule engine {ENGINE_VERSION})")


def _write_stdout(text: str) -> None:
    # Windows consoles default to a legacy code page; findings contain arrows and quotes.
    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        stream.write(text.encode("utf-8"))
        stream.flush()
    else:  # pragma: no cover - captured output in tests
        sys.stdout.write(text)


if __name__ == "__main__":  # pragma: no cover
    app()
