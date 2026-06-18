"""Build and serve the Qdrant vector index from BnK WBS JSON files.

Indexing (offline, run once):
    python -m diagram_mcp.rag.indexer

Runtime:
    from diagram_mcp.rag.indexer import get_retriever
    retriever = get_retriever("bnk_projects")
    docs = retriever.invoke("fintech lending platform")
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.vectorstores import VectorStoreRetriever

logger = logging.getLogger(__name__)

QDRANT_URL_DEFAULT = "http://localhost:6333"
COLLECTION_PROJECTS = "bnk_projects"
COLLECTION_MODULES = "bnk_modules"
EMBED_MODEL = "text-embedding-3-small"


def _qdrant_url() -> str:
    return os.getenv("QDRANT_URL", QDRANT_URL_DEFAULT)


def _make_embeddings():
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(model=EMBED_MODEL)


def _collection_exists(client, name: str) -> bool:
    try:
        client.get_collection(name)
        return True
    except Exception:  # noqa: BLE001
        return False


def build_index(data_dir: str | None = None) -> None:
    """Build (or rebuild) Qdrant collections from WBS JSON files.

    Reads all WBS JSON files via ``wbs_normalizer``, creates two collections:
    - ``bnk_projects``  — one document per project (semantic overview)
    - ``bnk_modules``   — one document per module (fine-grained)

    Upserts points so re-running is safe.
    """
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import Distance, VectorParams

    from ..wbs_normalizer import load_all_projects, project_to_documents

    projects, errors = load_all_projects(data_dir)
    if errors:
        for e in errors:
            logger.warning("WBS load error: %s", e)
    logger.info("Loaded %d projects (%d errors)", len(projects), len(errors))

    embeddings = _make_embeddings()
    vector_size = 1536  # text-embedding-3-small output dim

    client = QdrantClient(url=_qdrant_url())

    project_docs: list[dict] = []
    module_docs: list[dict] = []
    for p in projects:
        docs = project_to_documents(p)
        project_docs.extend(d for d in docs if d["metadata"]["granularity"] == "project")
        module_docs.extend(d for d in docs if d["metadata"]["granularity"] == "module")

    for collection_name, docs in [
        (COLLECTION_PROJECTS, project_docs),
        (COLLECTION_MODULES, module_docs),
    ]:
        if not _collection_exists(client, collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            logger.info("Created collection %s", collection_name)

        texts = [d["page_content"] for d in docs]
        metadatas = [d["metadata"] for d in docs]

        store = QdrantVectorStore(
            client=client,
            collection_name=collection_name,
            embedding=embeddings,
        )
        store.add_texts(texts=texts, metadatas=metadatas)
        logger.info("Upserted %d docs into %s", len(docs), collection_name)

    logger.info("Index build complete.")


def get_retriever(
    collection: str = COLLECTION_PROJECTS,
    top_k: int = 5,
    search_type: str = "mmr",
) -> "VectorStoreRetriever":
    """Return a LangChain retriever backed by the Qdrant collection.

    Falls back to in-memory if Qdrant is unavailable — useful in tests /
    CI where the Docker service isn't running.
    """
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient

    embeddings = _make_embeddings()
    try:
        client = QdrantClient(url=_qdrant_url(), timeout=3)
        if not _collection_exists(client, collection):
            logger.warning(
                "Qdrant collection '%s' not found — run `python -m diagram_mcp.rag.indexer` first.",
                collection,
            )
            raise RuntimeError("collection missing")

        store = QdrantVectorStore(
            client=client,
            collection_name=collection,
            embedding=embeddings,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qdrant unavailable (%s) — falling back to in-memory index.", exc)
        store = _build_in_memory_store(embeddings)

    if search_type == "mmr":
        return store.as_retriever(
            search_type="mmr",
            search_kwargs={"k": top_k, "fetch_k": top_k * 4, "lambda_mult": 0.6},
        )
    return store.as_retriever(search_kwargs={"k": top_k})


def _build_in_memory_store(embeddings):
    """Fallback: build a FAISS in-memory store from WBS files (no Qdrant needed)."""
    try:
        from langchain_community.vectorstores import FAISS
    except ImportError:
        from langchain_qdrant import QdrantVectorStore
        from qdrant_client import QdrantClient
        client = QdrantClient(":memory:")
        # Bootstrap with empty store; normalizer may not be available either
        return QdrantVectorStore(client=client, collection_name="fallback", embedding=embeddings)

    from ..wbs_normalizer import load_all_projects, project_to_documents

    projects, _ = load_all_projects()
    docs = []
    for p in projects:
        docs.extend(d for d in project_to_documents(p) if d["metadata"]["granularity"] == "project")

    if not docs:
        # Absolute last resort: empty FAISS index (retriever will return nothing)
        return FAISS.from_texts(["placeholder"], embeddings)

    return FAISS.from_texts(
        texts=[d["page_content"] for d in docs],
        embedding=embeddings,
        metadatas=[d["metadata"] for d in docs],
    )


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    data_dir_arg = sys.argv[1] if len(sys.argv) > 1 else None
    build_index(data_dir_arg)
