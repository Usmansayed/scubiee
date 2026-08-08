"""Backward-compatible alias — prefer ``pipeline.vectordb``. """

from pipeline.vectordb import FaissCollection, VectorDatabase, cwd_collection_name

# Old name used in early pipeline drafts
FaissVectorDB = FaissCollection

__all__ = ["FaissCollection", "FaissVectorDB", "VectorDatabase", "cwd_collection_name"]
