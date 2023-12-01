# pycontrails automated tasks

SHELL := /bin/bash  # override default /bin/sh
TAG ?= $(shell git describe --tags)

# Put first so that "make" without argument is like "make help".
help:
	echo "See Makefile for recipe list"

.PHONY: help

# -----------
# Pip / Setup
# -----------

# generic pip install all dependencies
# the latest open3d and accf packages often don't support the latest
# versions of python
pip-install:
	pip install -U pip wheel
	pip install -e ".[complete]"

	# these still must be installed manually for Python < 3.10
	# -pip install -e ".[open3d]"

# development installation
dev-install: pip-install

	pip install -e ".[dev,docs]"

	# install pre-commit
	pre-commit install

clean: docs-clean
	rm -rf .mypy_cache \
		   .pytest_cache \
		   .ruff_cache \
		   build \
		   dist \
		   pycontrails.egg-info \
		   pycontrails/__pycache__ \
		   pycontrails/data/__pycache__ \
		   pycontrails/datalib/__pycache__ \
		   pycontrails/models/__pycache__ \
		   pycontrails/models/cocip/__pycache__

remove: clean
	pip uninstall pycontrails

licenses:
	deplic .

check-licenses:
	deplic -c setup.cfg .

# -----------
# Extensions
# -----------

PYCONTRAILS_BADA_DIR = ../pycontrails-bada

dev-pycontrails-bada:
	git -C $(PYCONTRAILS_BADA_DIR) pull || git clone git@github.com:contrailcirrus/pycontrails-bada.git $(PYCONTRAILS_BADA_DIR)
	cd $(PYCONTRAILS_BADA_DIR) && make dev-install

# -----------
# QC, Test
# -----------

ruff: black-check
	ruff pycontrails tests

black:
	black pycontrails tests

black-check:
	black pycontrails tests --check

# https://taplo.tamasfe.dev/
taplo:
	taplo format pyproject.toml --option indent_string='    '

# https://yamllint.readthedocs.io/en/stable/configuration.html
yamllint:
	yamllint -d "{extends: default, rules: {line-length: {max: 100}}}" .

mypy:
	mypy pycontrails

pytest:
	pytest tests/unit

pytest-regenerate-results:
	pytest tests/unit --regenerate-results

pytest-cov:
	pytest \
		-v \
		--cov=pycontrails \
		--cov-report=html:coverage \
		--cov-report=term-missing \
		--durations=10 \
		--ignore=tests/unit/test_zarr.py \
		tests/unit

test: ruff mypy black-check nb-black-check pytest doctest nb-test

profile:
	python -m cProfile -o $(script).prof $(script)

# -----------
# Release
# -----------

changelog:
	git log $(shell git describe --tags --abbrev=0)..HEAD --pretty=format:'- (%h) %s' 

main-test-status:
	curl -s https://api.github.com/repos/contrailcirrus/pycontrails/actions/workflows/test.yaml/runs?branch=main \
		| jq -e -r '.workflow_runs[0].status == "completed" and .workflow_runs[0].conclusion == "success"'

	curl -s https://api.github.com/repos/contrailcirrus/pycontrails/actions/workflows/doctest.yaml/runs?branch=main \
		| jq -e -r '.workflow_runs[0].status == "completed" and .workflow_runs[0].conclusion == "success"'

# ----
# Docs
# ----

DOCS_DIR = docs
DOCS_BUILD_DIR = docs/_build

# Common ERA5 data for nb-tests and doctests
ensure-era5-cached:
	python -c 'from pycontrails.datalib.ecmwf import ERA5; \
		time = "2022-03-01", "2022-03-01T23"; \
		lev = [300, 250, 200]; \
		met_vars = ["t", "q", "u", "v", "w", "ciwc", "z", "cc"]; \
		rad_vars = ["tsr", "ttr"]; \
		ERA5(time=time, variables=met_vars, pressure_levels=lev).download(); \
		ERA5(time=time, variables=rad_vars).download()'

cache-era5-gcp:
	python -c 'from pycontrails.datalib.ecmwf import ERA5; \
		from pycontrails import DiskCacheStore; \
		cache = DiskCacheStore(cache_dir=".doc-test-cache"); \
		time = "2022-03-01", "2022-03-01T23"; \
		lev = [300, 250, 200]; \
		met_vars = ["t", "q", "u", "v", "w", "ciwc", "z", "cc"]; \
		rad_vars = ["tsr", "ttr"]; \
		ERA5(time=time, variables=met_vars, pressure_levels=lev, cachestore=cache).download(); \
		ERA5(time=time, variables=rad_vars, cachestore=cache).download()'

	gcloud storage cp -r -n .doc-test-cache/* gs://contrails-301217-unit-test/doc-test-cache/

doctest: ensure-era5-cached
	pytest --doctest-modules \
		--ignore-glob=pycontrails/ext/* \
		pycontrails -vv

doc8:
	doc8 docs

nb-black:
	black docs/examples/*.ipynb

nb-black-check:
	black docs/examples/*.ipynb --check

nb-clean:
	nb-clean clean docs/examples/*.ipynb \
        --remove-empty-cells \
		--preserve-cell-metadata \
		--preserve-cell-outputs

nb-clean-check:
	nb-clean check docs/examples/*.ipynb \
        --remove-empty-cells \
		--preserve-cell-metadata \
		--preserve-cell-outputs

# nbval 0.10.0 uses --nbval-sanitize-with instead of --sanitize-with
# There is a bug in nbval 0.10.0 which prevents us from using it
# https://github.com/computationalmodelling/nbval/issues/194
# nb-test: ensure-era5-cached nb-black-check nb-check-links
nb-test:
	pytest --nbval docs/examples/Cache.ipynb --sanitize-with docs/nb-test.cfg
# 	pytest --nbval --ignore-glob=*/ACCF.ipynb docs/examples --sanitize-with docs/nb-test.cfg

# Check for broken links in notebooks
# https://github.com/jupyterlab/pytest-check-links
nb-check-links:
	python -m pytest --check-links \
		--check-links-ignore "https://doi.org/10.1021/acs.est.9b05608" \
		--check-links-ignore "https://doi.org/10.1021/acs.est.2c05781" \
		--check-links-ignore "https://github.com/contrailcirrus/pycontrails-bada" \
		--check-links-ignore "https://ourairports.com" \
		docs/examples docs/tutorials

# execute notebooks for docs output
nb-execute: ensure-era5-cached nb-black-check nb-check-links
	jupyter nbconvert --inplace \
		--ClearMetadataPreprocessor.enabled=True \
		--to notebook --execute docs/examples/[!ACCF]*.ipynb docs/tutorials/*.ipynb

docs-build: doc8
	sphinx-build -b html $(DOCS_DIR) $(DOCS_BUILD_DIR)/html

docs-clean:
	rm -rf $(DOCS_BUILD_DIR)
	rm -rf $(DOCS_DIR)/api/*

docs-serve: doc8
	sphinx-autobuild \
		--re-ignore .*api\/.* \
		--re-ignore CHANGELOG.md \
		--re-ignore _build\/.* \
		-b html \
		$(DOCS_DIR) $(DOCS_BUILD_DIR)/html

docs-pdf: doc8
	sphinx-build -b latex $(DOCS_DIR) $(DOCS_BUILD_DIR)/latex
	cd $(DOCS_BUILD_DIR)/latex && make
