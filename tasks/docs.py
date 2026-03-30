"""Documentation tasks."""

from invoke import task, Context


@task
def build(ctx: Context) -> None:
    """Build Sphinx documentation."""
    ctx.run("uv run sphinx-build -b html docs docs/_build/html", pty=True)


@task
def clean(ctx: Context) -> None:
    """Clean built documentation."""
    ctx.run("rm -rf docs/_build", pty=True)


@task(pre=[clean, build])
def rebuild(ctx: Context) -> None:
    """Clean and rebuild documentation."""
    pass
