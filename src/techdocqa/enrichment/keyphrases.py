"""FR-08 keyphrases with RAKE through rake-nltk (P9-5; YAKE failed the license gate, see DECISIONS).

RAKE gets this module's stop words, the stored P0 sentence spans and the technical tokenizer, so NLTK needs no data
download. Scores are RAKE's degree-to-frequency ratio, higher is better; ties are broken by phrase text.
"""

import hashlib
import json
import re

from techdocqa.enrichment.entities import TOKEN

KEYPHRASE_POLICY = "rake-nltk-technical-v1"
DELIMITER = ","
WORDS = re.compile(TOKEN.pattern + r"|[^\w\s]")
# A standard English function-word list, fixed here so results never depend on downloaded data.
STOPWORDS = frozenset("""
a about above after again against all also am an and any are as at be because been before being below between both but
by can cannot could did do does doing done down during each either else etc even every few for from further had has
have having he her here hers herself him himself his how however i if in into is it its itself just least less let like
may me might more most much must my myself neither no nor not now of off often on once one only or other others otherwise
our ours ourselves out over own per perhaps rather same see seen several shall she should since so some such than that
the their theirs them themselves then there therefore these they this those though through thus to too toward towards
under unless until up upon us use used uses using very via was we well were what whatever when whenever where whereas
whether which while who whom whose why will with within without would yet you your yours yourself yourselves
""".split())


def rake_version() -> str | None:
    try:
        from importlib.metadata import version
        import rake_nltk  # noqa: F401
        return version("rake-nltk")
    except Exception:
        return None


def config_id(enrichment) -> str:
    values = {"policy": KEYPHRASE_POLICY, "rake_nltk": rake_version(), "per_document": enrichment.keyphrases_per_document,
              "per_chunk": enrichment.keyphrases_per_chunk, "min_words": enrichment.keyphrase_min_words,
              "max_words": enrichment.keyphrase_max_words, "include_code": enrichment.keyphrases_include_code,
              "stopwords_sha256": hashlib.sha256(" ".join(sorted(STOPWORDS)).encode()).hexdigest(), "words": WORDS.pattern}
    return "kc_" + hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def tokens(sentence: str) -> list[str]:
    """Technical tokens stay whole; every other punctuation mark becomes the one phrase delimiter."""
    return [token if token[0].isalnum() or token[0] == "_" or (token[0] == "-" and len(token) > 1) else DELIMITER
            for token in WORDS.findall(sentence)]


def ranked(sentences: list[str], enrichment, limit: int) -> list[tuple[str, float]]:
    """Top phrases as (phrase, score), best first. Very short text gives an empty list, never an error (FR-08.3)."""
    if sum(1 for sentence in sentences for token in tokens(sentence) if token != DELIMITER) < enrichment.keyphrase_min_words:
        return []
    from rake_nltk import Rake
    rake = Rake(stopwords=set(STOPWORDS), punctuations={DELIMITER}, max_length=enrichment.keyphrase_max_words,
                word_tokenizer=tokens)
    rake.extract_keywords_from_sentences(sentences)
    best = {}
    for score, phrase in rake.get_ranked_phrases_with_scores():
        # A phrase needs a letter; bare numbers and versions are not key terms.
        if re.search(r"[^\W\d_]", phrase):
            best[phrase] = max(score, best.get(phrase, score))
    return sorted(((phrase, round(float(score), 6)) for phrase, score in best.items()), key=lambda item: (-item[1], item[0]))[:limit]


def masked(text: str, code_spans: list) -> str:
    """Code replaced by a delimiter and spaces, so sentence offsets still line up."""
    chars = list(text)
    for span in code_spans:
        start, end = span["start"], span["end"]
        if start < end:
            chars[start:end] = [DELIMITER] + [" "] * (end - start - 1)
    return "".join(chars)


def document_sentences(documents, sentence_spans, include_code: bool) -> list[str]:
    sentences = []
    for document, page in zip(documents, sentence_spans, strict=True):
        text = document.page_content if include_code else masked(document.page_content, document.metadata.get("code_spans") or [])
        sentences += [text[span["start"]:span["end"]] for span in page["spans"] if text[span["start"]:span["end"]].strip()]
    return sentences


def chunk_sentences(chunk: dict, documents, sentence_spans, include_code: bool) -> list[str]:
    document = documents[chunk["document_index"]]
    text = document.page_content if include_code else masked(document.page_content, document.metadata.get("code_spans") or [])
    found = []
    for span in sentence_spans[chunk["document_index"]]["spans"]:
        start, end = max(span["start"], chunk["start"]), min(span["end"], chunk["end"])
        if start < end and text[start:end].strip():
            found.append(text[start:end])
    return found
