"""Deployment package root for HELAO instrument families.

Each subpackage under :mod:`helao.deploy` contains some or all of the
configs, servers, drivers, experiments and sequences for a single HELAO
deployment. This repository tracks ``base`` (framework services) and ``test``
(sims and demos); ``hte`` is its own public repository cloned in place; the
remaining subpackages are private repositories nested in-tree and are not named
in tracked sources.
"""
