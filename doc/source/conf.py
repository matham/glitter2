# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# http://www.sphinx-doc.org/en/master/config

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
from functools import partial
import sphinx_rtd_theme
import kivy  # this adds KIVY_DOC_INCLUDE to env
import glitter2
from glitter2.main import Glitter2App
from more_kivy_app.config import create_doc_listener, write_config_props_rst


# -- Project information -----------------------------------------------------

project = 'Glitter2'
copyright = '2020, Matthew Einhorn'
author = 'Matthew Einhorn'


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.todo',
    'sphinx.ext.coverage',
    'sphinx.ext.intersphinx',
    "sphinx_rtd_theme",
]

intersphinx_mapping = {
    'kivy': ('https://kivy.org/doc/stable/', None),
    'ffpyplayer': ('https://matham.github.io/ffpyplayer/', None),
    'base_kivy_app': ('https://matham.github.io/pyflycap2/', None),
}

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = 'sphinx_rtd_theme'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

html_logo = 'images/glitter2_logo.png'


def setup(app):
    yaml_filename = os.environ.get(
        'TREE_CONFIG_DOC_YAML_PATH', 'config_prop_docs.yaml')
    rst_filename = os.environ.get('TREE_CONFIG_DOC_RST_PATH', 'config.rst')
    create_doc_listener(app, 'glitter2', yaml_filename)

    app.connect(
        'build-finished', partial(
            write_config_props_rst, Glitter2App, 'Glitter2',
            filename=yaml_filename, rst_filename=rst_filename)
    )
