from app.core.answer_generation import GeneratedCitation

def validate_citations(
    citations: list[GeneratedCitation],
    excerpts: list[str],
):
    """检查引用编号有效，其引用文字确实存在于对应片段中。"""
    if not citations:
        return False

    for citation in citations:
        if not 1 <= citation.source_id <= len(excerpts):
            return False

        quote = citation.quote.strip()
        source_text = excerpts[citation.source_id - 1]

        if not quote or quote not in source_text:
            return False

    return True




