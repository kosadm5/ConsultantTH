import asyncio
from importlib import import_module

from scraper_engine.base_client import BaseClient

def load_source(name: str):
    try:
        # правильный импорт
        mod = import_module(f"scraper_engine.sources.{name}")
        return mod.Source()
    except Exception as e:
        raise RuntimeError(f"Cannot load source '{name}': {e}") from e


async def run_source(name: str):
    src = load_source(name)
    client = BaseClient()

    items = await src.fetch(client)
    for item in items:
        print(item)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()

    asyncio.run(run_source(args.source))
