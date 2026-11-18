from pymilvus import DataType, MilvusClient

from app.core.embeddings import EMBEDDING_DIMENSIONS, embed_texts


def main() -> None:
    collection = "demo_knowledge_chunks"
    milvus = MilvusClient(uri="http://127.0.0.1:19530", timeout=15.0)

    try:
        if not milvus.has_collection(collection):
            schema = milvus.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=128)
            schema.add_field("tenant_id", DataType.VARCHAR, max_length=64)
            schema.add_field("knowledge_base_id", DataType.VARCHAR, max_length=64)
            schema.add_field("document_id", DataType.VARCHAR, max_length=64)
            schema.add_field("chunk_index", DataType.INT64)
            schema.add_field("text", DataType.VARCHAR, max_length=2048)
            schema.add_field(
                "embedding", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIMENSIONS
            )

            indexes = milvus.prepare_index_params()
            indexes.add_index("embedding", index_type="FLAT", metric_type="COSINE")
            milvus.create_collection(
                collection_name=collection,
                schema=schema,
                index_params=indexes,
            )

        milvus.load_collection(collection_name=collection)

        leave = "员工申请年假，须至少提前三个工作日提交申请。"
        backup = "IT 部门每周五备份服务器日志。"
        question = "请年假要提前多久提出申请？"
        leave_vec, backup_vec, question_vec = embed_texts([leave, backup, question])

        samples = [
            ("demo-company", "it", "leave-doc", leave, leave_vec),
            ("demo-company", "it", "backup-doc", backup, backup_vec),
            ("demo-company", "hr", "hr-doc", leave, leave_vec),
            ("other-company", "it", "other-doc", leave, leave_vec),
        ]
        rows = [
            {
                "id": f"{document_id}:0",
                "tenant_id": tenant_id,
                "knowledge_base_id": kb_id,
                "document_id": document_id,
                "chunk_index": 0,
                "text": text,
                "embedding": vector,
            }
            for tenant_id, kb_id, document_id, text, vector in samples
        ]

        milvus.upsert(collection_name=collection, data=rows)

        hits = milvus.search(
            collection_name=collection,
            data=[question_vec],
            anns_field="embedding",
            filter='tenant_id == "demo-company" and knowledge_base_id == "it"',
            search_params={"metric_type": "COSINE", "params": {}},
            output_fields=["document_id", "text"],
            limit=10,
            consistency_level="Strong",
        )[0]

        document_ids = [hit["entity"]["document_id"] for hit in hits]
        print("命中文档", document_ids)
        for hit in hits:
            print(f'{hit["distance"]:.4f}  {hit["entity"]["text"]}')

        assert document_ids == ["leave-doc", "backup-doc"], "排序或筛选结果不符合预期"
        print("验收通过")
    finally:
        milvus.close()


if __name__ == "__main__":
    main()