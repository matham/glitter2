.. _install-glitter2:

*************
Installation
*************

Dependencies
-------------

* Python 3.6+
* Kivy Master `E.g. Windows nightly wheels <https://kivy.org/docs/installation/installation-windows.html#nightly-wheel-installation>`_
* Dependencies are automatically installed with pip and listed in ``setup.py``.
* Optional dependencies that should be installed depending on the cameras to be used:
  * Thor camera: :mod:`thorcam`.
  * RTV analog camera board: :mod:`pybarst`.
  * Point Gray camera: :mod:`pyflycap2`.

Installing Filers2
---------------------
After installing the dependencies filers2 can be installed using::

    pip install filers2

to get the last release from pypi, or to get filers2 master for the most current filers2 version do::

    pip install https://github.com/matham/filers2/archive/master.zip
