from setuptools import setup, find_packages
from io import open
from os import path

from glitter2 import __version__

here = path.abspath(path.dirname(__file__))

with open(path.join(here, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

URL = 'https://github.com/matham/glitter2'

setup(
    name='glitter2',
    version=__version__,
    author='Matthew Einhorn',
    author_email='matt@einhorn.dev',
    license='MIT',
    description=(
        'Video scoring for behavioral experiments.'),
    long_description=long_description,
    url=URL,
    classifiers=[
        'Development Status :: 4 - Beta',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
    ],
    packages=find_packages(),
    install_requires=[
        'base_kivy_app~=0.1.1', 'ffpyplayer', 'kivy~=2.1.0', 'nixio==1.5.0b4',
        'numpy', 'h5py', 'kivy_garden.graph~=0.4.0',
        'kivy_garden.tickmarker~=3.0.1', 'kivy_garden.painter~=0.2.4',
        'kivy_garden.collider~=0.1.2', 'tables', 'pandas', 'xlsxwriter',
        'tree-config~=0.1.1'
    ],
    extras_require={
        'dev': ['pytest>=3.6', 'pytest-cov', 'flake8', 'sphinx-rtd-theme',
                'coveralls', 'trio', 'pytest-trio', 'pyinstaller',
                'openpyxl'],
    },
    package_data={'glitter2': ['*.kv', '**/*.kv']},
    project_urls={
        'Bug Reports': URL + '/issues',
        'Source': URL,
    },
    entry_points={
        'console_scripts': ['glitter2=glitter2.main:run_app']},
)
