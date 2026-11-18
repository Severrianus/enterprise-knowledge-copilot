from app.core.answer_generation import GeneratedCitation
from app.core.citation_validation import validate_citations


sources = ["员工申请年假，须至少提前三个工作日提交申请。"]

# 正常引用。
assert validate_citations(
    [GeneratedCitation(source_id=1, quote="至少提前三个工作日")],
    sources,
)

# 编造原文中没有的内容。
assert not validate_citations(
    [GeneratedCitation(source_id=1, quote="提前十个工作日")],
    sources,
)

# 引用不存在的片段。
assert not validate_citations(
    [GeneratedCitation(source_id=2, quote="至少提前三个工作日")],
    sources,
)

# 0 不能作为引用编号。
assert not validate_citations(
    [GeneratedCitation(source_id=0, quote="至少提前三个工作日")],
    sources,
)

# 空引用和空白引用文字均不接受。
assert not validate_citations([], sources)

assert not validate_citations(
    [GeneratedCitation(source_id=1, quote="   ")],
    sources,
)

print("引用校验检查全部通过")