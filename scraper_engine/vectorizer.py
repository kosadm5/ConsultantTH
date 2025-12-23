from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

class OptimizedVectorizer:
    def __init__(self, qdrant_host="thai-qdrant", qdrant_port=6333):
        self.client = QdrantClient(host=qdrant_host, port=qdrant_port)
        self.model = SentenceTransformer('VISAI-AI/nitibench-ccl-human-finetuned-bge-m3')

    def embed(self, text: str):
        vector = self.model.encode(text, convert_to_numpy=True)
        return vector
