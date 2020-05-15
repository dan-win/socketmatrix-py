# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

requirements = ["python>=3.6"]

description='Socket Apps Microframework with server and client tools'
try:
    with open("README.md", "r") as fh:
        long_description = fh.read()
except:
    long_description = description

setup(name='sockmatrix',
    use_scm_version={
        'version_scheme': 'python-simplified-semver',
        'local_scheme': 'no-local-version',
    },
    setup_requires=[
        'setuptools_scm',
        # 'timeout-decorator==0.4.1',
    ],
    description=description,
    long_description=long_description,
    long_description_content_type="text/markdown",
    author='Dmitry Zimoglyadov',
    author_email='dmitry.zimoglyadov@gmail.com',
    license='Apache 2.0 / MIT',
    packages=find_packages(),
    python_requires='>=3.6',
    install_requires=[
        'uvloop==0.14.0',
        # 'python-dotenv>=0.10.3',
    ],
    extras_require={
    },
    zip_safe=False)