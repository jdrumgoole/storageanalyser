"""Invoke tasks for storageanalyser project."""

from invoke import Collection

from tasks import test, docs, web

ns = Collection()
ns.add_collection(Collection.from_module(test))
ns.add_collection(Collection.from_module(docs))
ns.add_collection(Collection.from_module(web))
