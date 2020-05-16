#!/bin/bash

set -e
set -x

# Default values now

if [[ $TRAVIS_OS_NAME == 'osx' ]]; then
    PYENV_ROOT="$HOME/.pyenv-socketmatrix"
    PATH="$PYENV_ROOT/bin:$PATH"
    hash -r
    eval "$(pyenv init -)"
fi
python setup.py build
python setup.py test

if [[ $TRAVIS_OS_NAME == 'osx' ]]; then
    python setup.py bdist_wheel
fi

if [[ $BUILD_WHEEL == 'true' ]]; then
    # From https://cibuildwheel.readthedocs.io/en/stable/setup/, travisci section: https://cibuildwheel.readthedocs.io/en/stable/setup/
    cibuildwheel --output-dir dist
fi

if [[ $BUILD_SDIST == 'true' ]]; then
    python setup.py sdist
fi