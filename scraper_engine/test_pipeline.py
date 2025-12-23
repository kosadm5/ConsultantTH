# scraper_engine/test_pipeline.py
import asyncio
from scraper_engine.sources.ratchakitcha import Source
from scraper_engine.base_client import BaseClient
from scraper_engine.cleaner import TextCleaner
from scraper_engine.vectorizer import OptimizedVectorizer
from scraper_engine.qdrant_writer import QdrantWriter

async def test_pipeline():
    client = BaseClient()  # вместо PlaywrightClient
    vectorizer = OptimizedVectorizer()
    cleaner = TextCleaner()
    writer = QdrantWriter(client=vectorizer.client)

    src = Source()
    items = await src.fetch(client)
    print("Fetched items:", len(items))

    item = items[0]

    # ВРЕМЕННО: используем URL как текст, потому что Source пока не возвращает HTML/текст
    #clean_text = cleaner.clean_html(item["url"])
    clean_text = cleaner.clean_html(item["html"])

    vector = vectorizer.embed(clean_text)
    writer.ensure_collection(len(vector))
    doc_id = writer.insert(
        text=clean_text,
        vector=vector,
        metadata={
            "title": item["url"],
            "url": item["url"],
            "source": "ratchakitcha",
        },
    )
    print("Inserted document:", doc_id)

if __name__ == "__main__":
    asyncio.run(test_pipeline())
