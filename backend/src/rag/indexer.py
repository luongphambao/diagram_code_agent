"""Build and serve the Qdrant vector index from BnK WBS JSON files.

Indexing (offline, run once):
    python -m diagram_mcp.rag.indexer

With Qdrant Cloud (set in .env):
    QDRANT_URL=https://<cluster>.cloud.qdrant.io
    QDRANT_API_KEY=<token>

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
COLLECTION_ITEMS = "bnk_wbs_items"
# Unified corpus (narrative case-study + real WBS estimate/tech in one record) — see
# rag/solution_memory.py + backend/scripts/build_solution_memory.py. Prefer this collection
# for new retrieval call sites (find_similar_solutions, pick_case_study); the 3 collections
# above stay for backward-compat / finer WBS-only granularity (module/item-level MD lookup).
COLLECTION_SOLUTIONS = "bnk_solutions"
EMBED_MODEL = "text-embedding-3-small"


def _qdrant_url() -> str:
    return os.getenv("QDRANT_URL", QDRANT_URL_DEFAULT)


def _qdrant_api_key() -> str | None:
    return os.getenv("QDRANT_API_KEY") or None


def _make_client():
    from qdrant_client import QdrantClient

    url = _qdrant_url()
    api_key = _qdrant_api_key()
    return QdrantClient(url=url, api_key=api_key)


def _make_embeddings():
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=EMBED_MODEL)


def _collection_exists(client, name: str) -> bool:
    try:
        client.get_collection(name)
        return True
    except Exception:  # noqa: BLE001
        return False


def build_index(data_dir: str | None = None, *, drop: bool = False) -> None:
    """Build (or rebuild) Qdrant collections from WBS JSON files.

    Creates three collections:
    - ``bnk_projects``   — 1 doc per project (semantic overview)
    - ``bnk_modules``    — 1 doc per effort_by_module row (mid-level)
    - ``bnk_wbs_items``  — 1 doc per wbs_items task (fine-grained)

    Set ``drop=True`` to delete and recreate existing collections.
    Upserts are idempotent — safe to re-run without drop.
    """
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client.http.models import Distance, VectorParams

    from rag.solution_memory import solution_memory_to_documents
    from wbs_normalizer import load_all_projects, project_to_documents

    projects, errors = load_all_projects(data_dir)
    if errors:
        for e in errors:
            logger.warning("WBS load error: %s", e)
    logger.info("Loaded %d projects (%d errors)", len(projects), len(errors))

    embeddings = _make_embeddings()
    vector_size = 1536  # text-embedding-3-small output dim

    client = _make_client()
    logger.info("Connected to Qdrant at %s", _qdrant_url())

    # Bucket docs by granularity
    project_docs: list[dict] = []
    module_docs: list[dict] = []
    item_docs: list[dict] = []
    for p in projects:
        for doc in project_to_documents(p):
            g = doc["metadata"]["granularity"]
            if g == "project":
                project_docs.append(doc)
            elif g == "module":
                module_docs.append(doc)
            elif g == "item":
                item_docs.append(doc)

    solution_docs = solution_memory_to_documents()

    logger.info(
        "Documents — projects: %d, modules: %d, items: %d, solutions (unified): %d",
        len(project_docs),
        len(module_docs),
        len(item_docs),
        len(solution_docs),
    )

    collections = [
        (COLLECTION_PROJECTS, project_docs),
        (COLLECTION_MODULES, module_docs),
        (COLLECTION_ITEMS, item_docs),
        (COLLECTION_SOLUTIONS, solution_docs),
    ]

    for collection_name, docs in collections:
        if not docs:
            logger.info("Skipping %s — no documents", collection_name)
            continue

        if drop and _collection_exists(client, collection_name):
            client.delete_collection(collection_name)
            logger.info("Dropped collection %s", collection_name)

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
    collection: str = COLLECTION_SOLUTIONS,
    top_k: int = 5,
    search_type: str = "mmr",
) -> "VectorStoreRetriever":
    """Return a LangChain retriever backed by the Qdrant collection.

    Falls back to in-memory FAISS if Qdrant is unavailable (dev / CI).
    """
    from langchain_qdrant import QdrantVectorStore

    embeddings = _make_embeddings()
    try:
        client = _make_client()
        # Quick connectivity check (3 s timeout)
        from qdrant_client import QdrantClient as _QC

        client = _QC(url=_qdrant_url(), api_key=_qdrant_api_key(), timeout=3)

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
    """Fallback: FAISS in-memory store from project-level docs only."""
    try:
        from langchain_community.vectorstores import FAISS
    except ImportError:
        from qdrant_client import QdrantClient
        from langchain_qdrant import QdrantVectorStore

        client = QdrantClient(":memory:")
        return QdrantVectorStore(client=client, collection_name="fallback", embedding=embeddings)

    from wbs_normalizer import load_all_projects, project_to_documents

    projects, _ = load_all_projects()
    docs = [d for p in projects for d in project_to_documents(p) if d["metadata"]["granularity"] == "project"]

    if not docs:
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

    drop_flag = "--drop" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--drop"]
    data_dir_arg = args[0] if args else None

    build_index(data_dir_arg, drop=drop_flag)
