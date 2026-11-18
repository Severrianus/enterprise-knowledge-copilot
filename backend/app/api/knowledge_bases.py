import logging
from datetime import datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from minio.error import MinioException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select
from urllib3.exceptions import HTTPError

from app.api.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.core.storage import minio_client
from app.db.models import Document, KnowledgeBase, User

from app.core.text_chunking import TextChunk, split_text


from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException
from openai import APIError, APIStatusError
from pydantic import BaseModel, Field
from pymilvus.exceptions import MilvusException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.embeddings import embed_texts
from app.core.text_chunking import split_text
from app.core.vector_store import COLLECTION_NAME, open_milvus
from app.db.models import Document, User
from app.db.session import engine

from app.core.answer_generation import (
    GenerationNotConfiguredError,
    generate_answer,
)

from app.core.citation_validation import validate_citations

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


class KnowledgeBaseSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    department_id: UUID | None


def knowledge_base_visibility(current_user: CurrentUser):
    return (
        KnowledgeBase.tenant_id == current_user.tenant_id,
        KnowledgeBase.status == "ACTIVE",
        or_(
            KnowledgeBase.department_id.is_(None),
            KnowledgeBase.department_id == current_user.department_id,
        ),
    )


@router.get("")
def list_knowledge_bases(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[KnowledgeBaseSummary]:
    statement = (
        select(KnowledgeBase)
        .where(*knowledge_base_visibility(current_user))
        .order_by(KnowledgeBase.name, KnowledgeBase.id)
    )

    with Session(engine) as session:
        return [
            KnowledgeBaseSummary.model_validate(row)
            for row in session.scalars(statement)
        ]


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime


@router.get("/{kb_id}/documents")
def list_documents(
    kb_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[DocumentSummary]:
    statement = (
        select(KnowledgeBase.id, Document)
        .outerjoin(
            Document,
            and_(
                Document.tenant_id == KnowledgeBase.tenant_id,
                Document.knowledge_base_id == KnowledgeBase.id,
                Document.upload_state.in_(("METADATA_ONLY", "STORED")),
            ),
        )
        .where(
            KnowledgeBase.id == kb_id,
            *knowledge_base_visibility(current_user),
        )
        .order_by(Document.created_at, Document.id)
    )

    with Session(engine) as session:
        rows = session.execute(statement).all()
        if not rows:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        return [
            DocumentSummary.model_validate(document)
            for _, document in rows
            if document is not None
        ]

logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 1024 * 1024


class UploadedDocument(DocumentSummary):
    file_size_bytes: int


@router.post("/{kb_id}/documents", status_code=201)
def upload_document(
    kb_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
) -> UploadedDocument:
    with Session(engine) as session, session.begin():
        kb = session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
                *knowledge_base_visibility(current_user),
            )
        )
        if kb is None:
            raise HTTPException(404, "Knowledge base not found")

        can_upload = session.scalar(
            select(User.can_upload_documents).where(User.id == current_user.id)
        )
        if not can_upload or kb.department_id is None:
            raise HTTPException(403, "Upload permission required")

        filename = PurePosixPath(
            (file.filename or "").replace("\\", "/")
        ).name
        if not filename.lower().endswith(".txt"):
            raise HTTPException(415, "Only .txt files are supported")
        if len(filename) > 255 or not filename.isprintable():
            raise HTTPException(400, "Invalid filename")

        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File exceeds 1 MiB")
        if not data:
            raise HTTPException(400, "File is empty")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(415, "File must be UTF-8 text") from exc

        document_id = uuid4()
        object_key = f"{kb.tenant_id}/{kb.id}/{document_id}.txt"
        session.add(
            Document(
                id=document_id,
                tenant_id=kb.tenant_id,
                knowledge_base_id=kb.id,
                title=filename,
                object_key=object_key,
                file_size_bytes=len(data),
                upload_state="PENDING",
            )
        )

    try:
        minio_client.put_object(
            settings.minio_bucket,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type="text/plain; charset=utf-8",
        )
    except (MinioException, HTTPError, OSError) as exc:
        logger.exception("Object upload failed for document %s", document_id)
        raise HTTPException(503, "Object storage unavailable") from exc

    with Session(engine) as session, session.begin():
        document = session.get_one(Document, document_id)
        document.upload_state = "STORED"
        result = UploadedDocument.model_validate(document)

    return result


class DocumentContent(BaseModel):
    id: UUID
    title: str
    text: str


@router.get("/{kb_id}/documents/{document_id}/content")
def read_document_content(
        kb_id: UUID,
        document_id: UUID,
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    statement = (
        select(Document.title, Document.object_key)
        .select_from(KnowledgeBase)
        .join(Document)
        .where(
            KnowledgeBase.id == kb_id,
            *knowledge_base_visibility(current_user),
            Document.id == document_id,
            Document.upload_state == "STORED",
            Document.object_key.is_not(None),
        )
    )

    with Session(engine) as session:
        row = session.execute(statement).one_or_none()

    if row is None:
        raise HTTPException(404, "Document content not found")

    title, object_key = row

    try:
        response = minio_client.get_object(settings.minio_bucket, object_key)
        try:
            data = response.read(MAX_UPLOAD_BYTES + 1)
        finally:
            response.close()
            response.release_conn()
    except (MinioException, HTTPError, OSError) as exc:
        logger.exception("Object read failed for document %s", document_id)
        raise HTTPException(503, "Object storage unavailable") from exc

    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(502, "Stored file exceeds 1 MiB")

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(502, "Stored file is not valid UTF-8") from exc

    return DocumentContent(id=document_id, title=title, text=text)

@router.get("/{kb_id}/documents/{document_id}/chunks")
def preview_document_chunks(
    kb_id: UUID,
    document_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[TextChunk]:
    document = read_document_content(
        kb_id=kb_id,
        document_id=document_id,
        current_user=current_user,
    )
    return split_text(document.text)


class KnowledgeSearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)

class KnowledgeSearchHit(BaseModel):
    document_id: UUID
    title: str
    chunk_index: int
    text: str
    score: float


@router.post("/{kb_id}/documents/{document_id}/index")
def index_document(
        kb_id: UUID,
        document_id: UUID,
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    with Session(engine) as session:
        can_upload = session.scalar(
            select(User.can_upload_documents).where(
                User.id == current_user.id,
                User.tenant_id == current_user.tenant_id,
                User.status == "ACTIVE",
            )
        )
    content = read_document_content(kb_id, document_id, current_user)
    chunks = split_text(content.text)

    if not chunks:
        raise HTTPException(
            status_code=422,
            detail="Document has no text to index",
        )

    vectors = []
    try:
        for start in range(0, len(chunks), 10):
            batch = chunks[start:start+10]
            vectors.extend(embed_texts([chunk.text for chunk in batch]))
    except APIError as exc:
        raise HTTPException(status_code=502, detail="Embedding provider failed") from exc

    rows = [
        {
            "id": f"{current_user.tenant_id}:{kb_id}:{document_id}:{chunk.index}",
            "tenant_id": str(current_user.tenant_id),
            "knowledge_base_id": str(kb_id),
            "document_id": str(document_id),
            "chunk_index": chunk.index,
            "text": chunk.text,
            "embedding": vector,
        }
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]

    try:
        with open_milvus() as client:
            client.upsert(collection_name=COLLECTION_NAME, data=rows)
    except MilvusException as exc:
        raise HTTPException(status_code=503, detail="Vector store unavailable") from exc

    return {"indexed_chunks": len(rows)}


@router.post("/{kb_id}/search")
def search_knowledge_base(
        kb_id: UUID,
        body: KnowledgeSearchRequest,
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    visible_kb_ids = {kb.id for kb in list_knowledge_bases(current_user)}
    if kb_id not in visible_kb_ids:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Question is empty")

    try:
        query_vector = embed_texts([question])[0]
    except APIError as exc:
        raise HTTPException(status_code=502, detail="Embedding provider failed") from exc

    scope = (
        f'tenant_id == "{current_user.tenant_id}"'
        f'and knowledge_base_id == "{kb_id}"'
    )
    try:
        with open_milvus() as client:
            hits = client.search(
                collection_name=COLLECTION_NAME,
                data=[query_vector],
                anns_field="embedding",
                filter=scope,
                output_fields=["document_id", "chunk_index", "text"],
                search_params={"metric_type": "COSINE", "params":{}},
                limit=body.limit,
                consistency_level="Strong",
            )[0]
    except MilvusException as exc:
        raise HTTPException(status_code=503, detail="Vector store unavailable") from exc

    if not hits:
        return []


    document_ids = {UUID(hit["entity"]["document_id"]) for hit in hits}
    with Session(engine) as session:
        documents = session.execute(
            select(Document.id, Document.title).where(
                Document.id.in_(document_ids),
                Document.tenant_id ==current_user.tenant_id,
                Document.knowledge_base_id == kb_id,
                Document.upload_state == "STORED",
            )
        ).all()

    titles = {document_id: title for document_id, title in documents}

    results = []
    for hit in hits:
        entity = hit["entity"]
        document_id = UUID(entity["document_id"])
        if document_id in titles:
            results.append(
                KnowledgeSearchHit(
                    document_id=document_id,
                    title=titles[document_id],
                    chunk_index=entity["chunk_index"],
                    text=entity["text"],
                    score=hit["distance"],
                )
            )

    return results


class KnowledgeAnswerCitation(BaseModel):
    document_id: UUID
    title: str
    chunk_index: int
    quote: str

class KnowledgeAnswerResponse(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    citations: list[KnowledgeAnswerCitation]


@router.post("/{kb_id}/ask")
def ask_knowledge_base(
    kb_id: UUID,
    body: KnowledgeSearchRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> KnowledgeAnswerResponse:
    hits = search_knowledge_base(kb_id, body, current_user)
    fallback = KnowledgeAnswerResponse(
        status="insufficient_evidence",
        answer="现有知识库资料不足，无法回答这个问题。",
        citations=[],
    )

    if not hits:
        return fallback

    try:
        generated = generate_answer(
            body.question.strip(),
            [hit.text for hit in hits],
        )
    except GenerationNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="Generation model is not configured") from exc
    except APIStatusError as exc:
        if exc.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="Generation provider rate or quota limit reached",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=f"Generation provider returned HTTP {exc.status_code}",
        ) from exc
    except (APIError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Could not generate an answer") from exc

    if not generated.answer.strip() or not generated.citations:
        return fallback

    if not validate_citations(
        generated.citations,
        [hit.text for hit in hits],
    ):
        return fallback

    citations = []
    for citation in generated.citations:
        hit = hits[citation.source_id - 1]

        citations.append(
            KnowledgeAnswerCitation(
                document_id = hit.document_id,
                title = hit.title,
                chunk_index = hit.chunk_index,
                quote = citation.quote.strip(),
            )
        )

    citations = []
    for citation in generated.citations:
        if not 1 <= citation.source_id <= len(hits):
            return fallback

        hit = hits[citation.source_id - 1]
        quote = citation.quote.strip()
        if not quote or quote not in hit.text:
            return fallback

        citations.append(
            KnowledgeAnswerCitation(
                document_id=hit.document_id,
                title=hit.title,
                chunk_index=hit.chunk_index,
                quote=quote,
            )
        )

    return KnowledgeAnswerResponse(
        status="answered",
        answer=generated.answer.strip(),
        citations=citations,
    )