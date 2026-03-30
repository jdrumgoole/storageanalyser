"""Sphinx configuration for storageanalyser documentation."""

project = "storageanalyser"
copyright = "2026"
author = "Joe Drumgoole"

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
