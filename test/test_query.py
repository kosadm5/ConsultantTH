# test/test_query.py
import os
import argparse
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

# --- КОНФИГУРАЦИЯ ---
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6433")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "thai_law")
MODEL_NAME = os.getenv("EMBED_MODEL", "VISAI-AI/nitibench-ccl-human-finetuned-bge-m3")

def search(query: str, top_k: int = 5):
    """
    Выполняет поиск в Qdrant по текстовому запросу.
    """
    print(f"Инициализация модели '{MODEL_NAME}'... (может занять время при первом запуске)")
    model = SentenceTransformer(MODEL_NAME)

    print(f"Подключение к Qdrant по адресу {QDRANT_URL}...")
    client = QdrantClient(url=QDRANT_URL)

    print(f"Кодирование запроса: '{query}'")
    query_vector = model.encode(query).tolist()

    print(f"Поиск в коллекции '{COLLECTION_NAME}'...")
    search_result = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        limit=top_k,
        with_payload=True,  # Включаем метаданные в результат
    )

    print("\n--- РЕЗУЛЬТАТЫ ПОИСКА ---\n")
    if not search_result:
        print("Ничего не найдено.")
        return

    for i, hit in enumerate(search_result):
        print(f"Результат #{i + 1} (Score: {hit.score:.4f})")
        payload = hit.payload
        text = payload.get("text", "N/A")
        
        # Убираем лишние переносы строк для лучшей читаемости
        cleaned_text = ' '.join(text.split())
        
        print(f"  Источник: {payload.get('source_url', 'N/A')}")
        print(f"  ID документа: {payload.get('doc_id', 'N/A')}")
        print(f"  Текст: \"{cleaned_text[:500]}...\"")
        print("-" * 20)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Тестовый скрипт для проверки запросов к Qdrant.")
    parser.add_argument(
        "query", 
        type=str, 
        nargs='?', 
        default="какой налог на покупку автомобиля", 
        help="Текстовый запрос для поиска. (Например: 'какой налог на покупку автомобиля')"
    )
    parser.add_argument(
        "--top-k", 
        type=int, 
        default=5,
        help="Количество возвращаемых результатов."
    )
    args = parser.parse_args()

    search(query=args.query, top_k=args.top_k)
