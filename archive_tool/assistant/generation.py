"""Conservative extractive answers and source-anchored field suggestions."""
import re
from datetime import datetime
from langchain_core.runnables import RunnableLambda
from .retrieval import ArchiveRetriever, tokens, ALIASES


def citation(doc, quote=None):
    return dict(doc.metadata, quote=quote or doc.page_content)


def evidence_answer(query, docs):
    # A search hit is not proof of an answer: require topical overlap after stop words.
    meaningful = tokens(query, True)
    normalized = query
    for alias, canonical in ALIASES.items():
        normalized = normalized.replace(alias, canonical)
    topics = [t for t in ('题名', '日期', '责任者', '保管期限', '密级', '件号', '页数', '导出', '保存') if t in normalized]
    evidence = []
    for doc in docs:
        matching = set(meaningful) & set(tokens(doc.page_content, True))
        text = doc.page_content
        for alias, canonical in ALIASES.items():
            text = text.replace(alias, canonical)
        if len(matching) >= 2 and topics and any(t in text for t in topics):
            for line in doc.page_content.splitlines():
                normalized_line = line
                for alias, canonical in ALIASES.items():
                    normalized_line = normalized_line.replace(alias, canonical)
                if not any(t in normalized_line for t in topics):
                    continue
                if '缺失' in query and not any(t in normalized_line for t in ('缺失', '不详', '未注明')):
                    continue
                evidence.append(citation(doc, line))
    return {'answer': '以下为相关规则的原文摘录；未写明的情况仍属证据不足，不据此推断。请核对适用性。' if evidence
            else '证据不足，未找到可支持答案的规范，请补充资料或缩小问题范围。',
            'citations': evidence}


def ask(index, query, scope='通用', mode='hybrid', embeddings=None):
    retriever = ArchiveRetriever(index=index, scope=scope, mode=mode, embeddings=embeddings)
    # Both retrieval and answer assembly execute as actual LangChain chain stages.
    chain = retriever | RunnableLambda(lambda docs: evidence_answer(query, docs))
    from langsmith import tracing_context
    # Even a developer's tracing environment must not upload archive-related content.
    with tracing_context(enabled=False):
        return chain.invoke(query)


def suggest(documents, fields):
    """Only explicit labeled values; ambiguity and OCR uncertainty cause abstention."""
    results = []
    for field in fields:
        name = field['name']
        # A file's formation date is not evidence of receipt/filing dates.
        # Likewise file title must not be silently repurposed as a volume title.
        label = next((canonical for canonical, names in {
            '题名': {'题名', '文件题名', '标题'},
            '日期': {'日期', '文件日期', '形成日期'},
            '责任者': {'责任者'},
        }.items() if name in names), None)
        if label is None:
            continue
        labels = {'题名': '(?:文件题名|题名|标题)', '日期': '(?:文件日期|日期|形成日期)',
                  '责任者': '(?:责任者|发文单位)'}[label]
        candidates = []
        for doc in documents:
            for match in re.finditer(rf'(?m)^[ \t]*{labels}[ \t]*[:：][ \t]*([^\n]+)', doc.page_content):
                raw = match.group(1).strip()
                value = raw
                if label == '日期':
                    digits = re.sub(r'[年月日/\- .]', '', raw)
                    try:
                        datetime.strptime(digits, '%Y%m%d')
                        if len(digits) != 8:
                            continue
                    except ValueError:
                        continue
                    value = digits
                candidates.append((value, doc, match.group(0).strip()))
        values = {c[0] for c in candidates}
        if len(values) == 1:
            value, doc, quote = candidates[0]
            results.append({'key': field['key'], 'name': name, 'value': value,
                            'citation': citation(doc, quote),
                            'warning': 'OCR 原文可能有误，请对照扫描件核实' if doc.metadata.get('ocr') else ''})
        else:
            results.append({'key': field['key'], 'name': name, 'value': None,
                            'reason': '证据不足或存在多个不同值，请人工核实'})
    return results
