from pydantic import BaseModel

class TextChunk(BaseModel):
    index: int
    start: int
    end: int
    text: str


def split_text(
        text: str, chunk_size: int = 300, overlap: int = 50
) -> list[TextChunk]:
    if not 0 <= overlap < chunk_size:
        raise ValueError('overlap must be smaller than chunk_size')

    if not text.strip():
        return []


    chunks: list[TextChunk] = []
    step = chunk_size - overlap

    for start in range(0, len(text), step):
        end = min(start + chunk_size, len(text))
        chunks.append(
            TextChunk(
                index=len(chunks),
                start=start,
                end=end,
                text=text[start:end],
            )
        )
        if end == len(text):
            break

    return chunks

