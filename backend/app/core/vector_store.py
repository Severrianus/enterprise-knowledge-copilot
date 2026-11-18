from contextlib import closing

from pymilvus import DataType, MilvusClient

from app.core.config import settings
from app.core.embeddings import EMBEDDING_DIMENSIONS

COLLECTION_NAME = "knowledge_chunks"


def open_milvus():
    return closing(MilvusClient(uri=settings.milvus_uri, timeout=15.0))


def init_collection() -> None:
    with open_milvus() as client:
        if not client.has_collection(COLLECTION_NAME):
            schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
            for field in ("tenant_id", "knowledge_base_id", "document_id"):
                schema.add_field(field, DataType.VARCHAR, max_length=64)
            schema.add_field("chunk_index", DataType.INT64)
            schema.add_field("text", DataType.VARCHAR, max_length=2048)
            schema.add_field(
                "embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIMENSIONS
            )

            indexes = client.prepare_index_params()
            indexes.add_index("embedding", index_type="FLAT", metric_type="COSINE")
            client.create_collection(
                collection_name=COLLECTION_NAME,
                schema=schema,
                index_params=indexes,
            )

        client.load_collection(collection_name=COLLECTION_NAME)


if __name__ == "__main__":
    init_collection()
    print(f"Milvus 集合已就绪：{COLLECTION_NAME}")