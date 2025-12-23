from qdrant_client.models import PointStruct
import uuid

class QdrantWriter:
    def __init__(self, client, collection_name="thai_docs"):
        self.client = client
        self.collection_name = collection_name

    def ensure_collection(self, vector_size: int):
        from qdrant_client.models import VectorParams, Distance

        self.client.recreate_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
        )

    def insert(self, text: str, vector, metadata: dict):
        point_id = str(uuid.uuid4())
        point = PointStruct(
            id=point_id,
            vector=vector,
            payload={
                "text": text,
                **metadata
            }
        )
        self.client.upsert(collection_name=self.collection_name, points=[point])
        return point_id
