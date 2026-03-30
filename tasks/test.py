"""Test tasks."""

from invoke import task, Context


@task
def run(ctx: Context, verbose: bool = False) -> None:
    """Run the test suite."""
    cmd = "uv run python -m pytest"
    if verbose:
        cmd += " -v"
    ctx.run(cmd, pty=True)


@task
def coverage(ctx: Context) -> None:
    """Run tests with coverage report."""
    ctx.run("uv run python -m pytest --cov=storageanalyser --cov-report=term-missing", pty=True)
