"""Glitter2
=================

Video scoring for behavioral experiments.
"""
import sys
import os
import pathlib

__all__ = ('get_pyinstaller_datas', )

__version__ = '0.1.1.dev5'


def get_pyinstaller_datas():
    """Returns the ``datas`` list required by PyInstaller to be able to package
    :mod:`glitter2` in a application.

    """
    root = pathlib.Path(os.path.dirname(sys.modules[__name__].__file__))
    datas = []
    for pat in ('**/*.kv', '*.kv'):
        for f in root.glob(pat):
            datas.append((str(f), str(f.relative_to(root.parent).parent)))

    return datas
