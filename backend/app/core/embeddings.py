from openai import OpenAI

from app.core.config import settings

EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_DIMENSIONS = 1024

def embed_texts(texts: list[str]):
    if not texts:
        return []


    if len(texts) > 10:
        raise ValueError("text-embedding-v4 单次请求最多接受10条文本")

    secret = settings.dashscope_api_key
    api_key = secret.get_secret_value().strip() if secret is not None else ""
    base_url = (settings.dashscope_base_url or "").strip().rstrip("/")

    if not api_key or not base_url:
        raise RuntimeError(
            "请在项目根目录的 .env 中配置 DASHSCOPE_API_KEY 和 DASHSCOPE_BASE_URL"
        )

    with OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=15.0,
    ) as client:
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
            dimensions=EMBEDDING_DIMENSIONS,
            encoding_format="float",
        )

    items = sorted(response.data, key=lambda item: item.index)
    if [item.index for item in items] != list(range(len(texts))):
        raise RuntimeError("Embedding 响应的序号与输入文本不匹配")

    vectors = [item.embedding for item in items]
    if any(len(vector) != EMBEDDING_DIMENSIONS for vector in vectors):
        raise RuntimeError(f"Embedding 输出维度应为 {EMBEDDING_DIMENSIONS}")

    return vectors

