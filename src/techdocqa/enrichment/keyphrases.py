"""FR-08 keyphrases: short technical n-grams (the default since 2026-11-12) or RAKE through rake-nltk (P9-5; YAKE
failed the license gate, see DECISIONS).

Both policies get this module's stop words, the stored P0 sentence spans and the technical tokenizer, so NLTK needs no
data download. Scores are higher-is-better within one document and one policy only.

`technical-ngrams-v1` lists every 1- and 2-word run of content words, so a short term inside a longer run still counts,
which RAKE's whole-run phrases never allow. A candidate scores its frequency, with a fixed bonus for two words and for a
gazetteer term; singular and plural forms count as one term, shown in the form used most often. The document's own
technology name and generic words are not candidates, and a single word is dropped when it occurs mostly inside a
two-word term already listed. Ties go to the earlier first occurrence, then to the text.
"""

from collections import Counter, defaultdict
import hashlib
import json
import re
import unicodedata

from techdocqa.enrichment.entities import TOKEN

RAKE_POLICY = "rake-nltk-technical-v2"
NGRAM_POLICY = "technical-ngrams-v1"
POLICIES = {"rake": RAKE_POLICY, "ngram": NGRAM_POLICY}
# technical-ngrams-v1 constants, chosen on the round-1 key-term gold set (development data) and then frozen.
NGRAM_MAX_WORDS = 2
TWO_WORD_BONUS = 1.5
GAZETTEER_BOOST = 3.0
NESTED_SHARE = 0.5
# SHA-256 of the round-1 key-term gold set those constants were chosen on, so eval --enrichment reports a score on it
# as tuned rather than held out.
NGRAM_DEVELOPMENT_SETS = frozenset({"320534b487f0c12bff22f2fbe050d13016de6c5e7609e1a8df1bbebdab7ed88d"})
# Words that never start or end a candidate: documentation filler ("Prefer the document's main subjects over incidental
# words", GUIDELINES.md).
FILLER = frozenset("""
above also below case cases chapter default detail details different end example examples first following information
kind lot many more most much new note notes number numbers old order page part parts same second section sections see set
sets several start thing things time times type types value values various way ways
""".split())
# Generic words that are not a key term on their own (the guidelines' examples for entities, plus license boilerplate),
# though they may be part of one ("user account", "storage system").
GENERIC = frozenset("copyright data file files license licensed system systems user users".split())
DELIMITER = ","
# A word with an English clitic (don't, we're, Kafka's) is one token, so the apostrophe never leaves a stray "t" or "s".
CONTRACTION = re.compile(r"[^\W\d_]+['’][^\W\d_]{1,2}(?![\w'’])")
WORDS = re.compile(CONTRACTION.pattern + "|" + TOKEN.pattern + r"|[^\w\s]")
# Single underscores around a word are Markdown emphasis (_without_), not part of a name such as __init__ or retry_after.
EMPHASIS = re.compile(r"^_(?=[^\W_])|(?<=[^\W_])_$")
METRICS = ("degree_to_frequency", "word_degree", "word_frequency")
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


def available(enrichment) -> bool:
    """The n-gram policy needs nothing beyond the package; RAKE needs the nlp extra."""
    return enrichment.keyphrase_policy == "ngram" or rake_version() is not None


def word_list_sha256(words) -> str:
    return hashlib.sha256(" ".join(sorted(words)).encode()).hexdigest()


def config_id(enrichment, gazetteer_sha256: str | None = None) -> str:
    values = {"policy": POLICIES[enrichment.keyphrase_policy], "per_document": enrichment.keyphrases_per_document,
              "per_chunk": enrichment.keyphrases_per_chunk, "min_words": enrichment.keyphrase_min_words,
              "include_code": enrichment.keyphrases_include_code, "emphasis": EMPHASIS.pattern,
              "stopwords_sha256": word_list_sha256(STOPWORDS), "words": WORDS.pattern}
    if enrichment.keyphrase_policy == "rake":
        values |= {"rake_nltk": rake_version(), "max_words": enrichment.keyphrase_max_words, "metric": enrichment.keyphrase_metric}
    else:
        # The gazetteer boost reads the gazetteer, so a gazetteer change makes stored keyphrases stale too.
        values |= {"max_words": NGRAM_MAX_WORDS, "two_word_bonus": TWO_WORD_BONUS, "gazetteer_boost": GAZETTEER_BOOST,
                   "nested_share": NESTED_SHARE, "filler_sha256": word_list_sha256(FILLER),
                   "generic_sha256": word_list_sha256(GENERIC), "gazetteer_sha256": gazetteer_sha256}
    return "kc_" + hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def fold(text: str) -> str:
    """The comparison form: NFKC, case-folded, whitespace collapsed (as the gold sets compare)."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def domain_terms(gazetteer) -> frozenset:
    """Every gazetteer alias in comparison form: the n-gram policy's domain prior."""
    return frozenset(fold(alias) for entry in gazetteer.file.entities for alias in entry.aliases)


def technology_names(gazetteer, technology: str | None) -> frozenset:
    """The document's own technology in comparison form, with every alias of its gazetteer entry ("Do not list the
    technology name alone", GUIDELINES.md)."""
    if not technology:
        return frozenset()
    entry = gazetteer.by_key.get(gazetteer.filter_key(technology))
    return frozenset(fold(alias) for alias in entry.aliases) if entry else frozenset({fold(technology)})


def word(token: str) -> str:
    """One token as RAKE sees it. A contraction is a function word, so it splits phrases like a stop word does; a
    possessive keeps its noun (Kafka's is Kafka). Emphasis underscores are dropped."""
    if CONTRACTION.fullmatch(token):
        stem, clitic = re.split(r"['’]", token, maxsplit=1)
        # it's, that's and let's are function words; Kafka's is a noun.
        return stem if clitic.casefold() == "s" and stem.casefold() not in STOPWORDS else DELIMITER
    token = EMPHASIS.sub("", token)
    if not token:
        return DELIMITER
    return token if token[0].isalnum() or token[0] == "_" or (token[0] == "-" and len(token) > 1) else DELIMITER


def tokens(sentence: str) -> list[str]:
    """Technical tokens stay whole; every other punctuation mark becomes the one phrase delimiter."""
    return [word(token) for token in WORDS.findall(sentence)]


def singular(word: str) -> str:
    """A plain English plural folded to its singular, for counting only; names and short words stay as they are."""
    if not word.isalpha() or len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("sses", "shes", "ches", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def content_runs(sentences: list[str]):
    """Runs of content words between stop words and punctuation, in text order, with their surface forms."""
    for sentence in sentences:
        run = []
        for token in tokens(sentence):
            if token == DELIMITER or token.casefold() in STOPWORDS:
                if run:
                    yield run
                run = []
            else:
                run.append(token)
        if run:
            yield run


def ngram_ranked(sentences: list[str], limit: int, exclude: frozenset, domain: frozenset) -> list[tuple[str, float]]:
    counts, surfaces, first = Counter(), defaultdict(Counter), {}
    position = 0
    for run in content_runs(sentences):
        for size in range(1, NGRAM_MAX_WORDS + 1):
            for start in range(len(run) - size + 1):
                words = run[start:start + size]
                text = " ".join(words)
                folded = [token.casefold() for token in words]
                # A candidate needs a letter, and a single word at least two characters.
                if not re.search(r"[^\W\d_]", text) or (size == 1 and len(text) < 2):
                    continue
                if folded[0] in FILLER or folded[-1] in FILLER or fold(text) in exclude:
                    continue
                key = tuple(folded[:-1] + [singular(folded[-1])])
                counts[key] += 1
                surfaces[key][text] += 1
                first.setdefault(key, position)
                position += 1
    scores = {}
    for key, frequency in counts.items():
        if len(key) == 1 and key[0] in GENERIC:
            continue
        score = frequency * (1 + TWO_WORD_BONUS * (len(key) - 1))
        text = " ".join(key)
        if fold(text) in domain or fold(text + "s") in domain:
            score *= GAZETTEER_BOOST
        scores[key] = score
    kept = []
    for key in sorted(scores, key=lambda item: (-scores[item], first[item], item)):
        # A word that occurs mostly inside a two-word term already listed adds nothing ("bundle" after "dag bundle").
        if len(key) == 1 and any(len(other) == 2 and key[0] in other and counts[other] >= NESTED_SHARE * counts[key]
                                 for other, _ in kept):
            continue
        # The form used most often, then the first in text order among equals.
        shown = sorted(surfaces[key].items(), key=lambda item: (-item[1], item[0]))[0][0]
        kept.append((key, (shown, round(float(scores[key]), 6))))
        if len(kept) == limit:
            break
    return [phrase for _, phrase in kept]


def ranked(sentences: list[str], enrichment, limit: int, *, exclude: frozenset = frozenset(),
           domain: frozenset = frozenset()) -> list[tuple[str, float]]:
    """Top phrases as (phrase, score), best first. Very short text gives an empty list, never an error (FR-08.3).
    exclude and domain apply to the n-gram policy: the document's technology names and the gazetteer's terms."""
    if sum(1 for sentence in sentences for token in tokens(sentence) if token != DELIMITER) < enrichment.keyphrase_min_words:
        return []
    if enrichment.keyphrase_policy == "ngram":
        return ngram_ranked(sentences, limit, exclude, domain)
    from rake_nltk import Metric, Rake
    metric = {"degree_to_frequency": Metric.DEGREE_TO_FREQUENCY_RATIO, "word_degree": Metric.WORD_DEGREE,
              "word_frequency": Metric.WORD_FREQUENCY}[enrichment.keyphrase_metric]
    rake = Rake(stopwords=set(STOPWORDS), punctuations={DELIMITER}, max_length=enrichment.keyphrase_max_words,
                ranking_metric=metric, word_tokenizer=tokens)
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
