# indexer/service.py
from fastapi import FastAPI
from pydantic import BaseModel
from pathlib import Path
import os, json

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

PROCESSED_DIR = os.getenv("PROCESSED_DIR", "/app/data/processed")
QDRANT_HOST = os.getenv("QDRANT_HOST", "thai-qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION = os.getenv("QDRANT_COLLECTION", "thai_law")

app = FastAPI()

model = SentenceTransformer("VISAI-AI/nitibench-ccl-human-finetuned-bge-m3")
#model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

# коллекцию можно создать один раз при старте
client.recreate_collection(
    collection_name=COLLECTION,
    vectors_config=qmodels.VectorParams(size=model.get_sentence_embedding_dimension(), distance="Cosine"),
)

class IndexRequest(BaseModel):
    filenames: list[str] | None = None  # относительные пути в PROCESSED_DIR; если None — индексируем все

@app.post("/index")
def index_files(req: IndexRequest):
    if req.filenames:
        files = [Path(PROCESSED_DIR) / f for f in req.filenames]
    else:
        files = sorted(Path(PROCESSED_DIR).glob("*.processed.json"))

    total = 0
    for fn in files:
        if not fn.exists():
            continue
        with open(fn, "r", encoding="utf-8") as f:
            doc = json.load(f)
        meta = doc.get("meta", {})
        chunks = doc.get("chunks", [])
        texts = [c["text"] for c in chunks]
        if not texts:
            continue

        vectors = model.encode(texts, convert_to_numpy=True)
        doc_id = Path(fn).stem

        points = []
        for i, (vec, chunk) in enumerate(zip(vectors, chunks)):
            chunk_id = chunk.get("chunk_id", i)
            # целочисленный ID — просто порядковый номер
            point_id = i
            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=vec.tolist(),
                    payload={
                        "text": chunk["text"],
                        "chunk_id": chunk_id,
                        "url": meta.get("url"),
                        "source": meta.get("source", "ocs"),
                        "title": chunk.get("title"),
                        "doc_id": doc_id,
                        "fetched_at": meta.get("fetched_at"),
                    },
                )
            )

        if points:
            client.upsert(collection_name=COLLECTION, points=points)
            total += len(points)

    return {"indexed_points": total}
