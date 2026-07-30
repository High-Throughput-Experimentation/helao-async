"""Deployment package root for HELAO instrument families.

Each subpackage under :mod:`helao.deploy` contains the configs, servers,
drivers, experiments and sequences for a single HELAO deployment. This
repository tracks ``hte`` (production stations) and ``test`` (sims and demos);
the remaining subpackages are separate git repositories nested in-tree and are
gitignored here, so they are not named in tracked sources.
"""
