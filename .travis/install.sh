
#!/bin/bash

# Based on: https://github.com/simplejson/simplejson/blob/master/.travis/install.sh

set -e
set -x

if [[ $TRAVIS_OS_NAME == 'osx' ]]; then
    if [ ! -e "$HOME/.pyenv-socketmatrix/.git" ]; then
      if [ -e "$HOME/.pyenv-socketmatrix" ]; then
        rm -rf ~/.pyenv-socketmatrix
      fi
      git clone https://github.com/pyenv/pyenv.git ~/.pyenv-socketmatrix
    else
      (cd ~/.pyenv-socketmatrix; git pull)
    fi
    PYENV_ROOT="$HOME/.pyenv-socketmatrix"
    PATH="$PYENV_ROOT/bin:$PATH"
    hash -r
    eval "$(pyenv init -)"
    hash -r
    pyenv install --list
    pyenv install -s $PYENV_VERSION
    pip install wheel
fi

# See more aboit cibuildwheel: https://cibuildwheel.readthedocs.io/en/stable/
if [[ $BUILD_WHEEL == 'true' ]]; then
    pip install wheel cibuildwheel==1.4.1
fi