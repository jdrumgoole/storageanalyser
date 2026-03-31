"""Sphinx configuration for storageanalyser documentation."""

import importlib.metadata

project = "storageanalyser"
copyright = "2026, Joe Drumgoole"
author = "Joe Drumgoole"

try:
    release = importlib.metadata.version("storageanalyser")
except importlib.metadata.PackageNotFoundError:
    release = "dev"
version = release

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

# MyST-Parser settings
myst_heading_anchors = 3
