"""FR-07 rule-based technical entities: a configurable gazetteer plus fixed regex patterns (P9-3, P9-12).

Confidence is a level fixed by the rule that matched, not a probability; the gold set measures precision.
Every pattern repeats only over disjoint character classes, so matching time is linear in the input.
"""

import bisect
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import tomllib
from typing import Literal

from pydantic import Field, model_validator

from techdocqa.errors import TechDocQAError
from techdocqa.settings import StrictModel

ENTITY_POLICY = "techdocqa-entity-rules-v1"
EntityType = Literal["TECHNOLOGY", "COMPONENT", "CONCEPT", "PROTOCOL", "IDENTIFIER"]

# Fixed confidences per rule. Exact gazetteer matches are 1.0 (FR-07.2); an ambiguous alias without its context
# rule falls below the 0.5 verification threshold, so it is stored but never filters.
CONFIDENCE = {"gazetteer": 1.0, "gazetteer-ambiguous": 0.4, "protocol": 0.9, "identifier": 0.8, "identifier-camel": 0.6}
# Longer matches win; at equal length the gazetteer beats a pattern, and a protocol beats an identifier.
PRIORITY = {"gazetteer": 0, "gazetteer-ambiguous": 0, "protocol": 1, "identifier": 2, "identifier-camel": 2}

# Case-sensitive protocol names; HTTP versions are whole matches.
PROTOCOL = re.compile(r"(?<![\w/.-])(?:HTTPS?(?:/[1-3](?:\.[01])?)?|TCP|UDP|mTLS|TLS(?:v1\.[0-3])?|SSL|gRPC|REST|SASL|"
                      r"Kerberos|OAuth(?: ?2(?:\.0)?)?|JDBC|ODBC|SSH|SFTP|FTP|SMTP|DNS|WebSockets?|AMQP|MQTT|IPv[46]|LDAP|"
                      r"SCRAM|GSSAPI)(?![\w])")
# The BM25 technical token (lexical.TECHNICAL): word runs joined by separators, or a --flag. Alternation of the
# disjoint classes \w and [./:#+-] keeps it linear.
TOKEN = re.compile(r"-{1,2}[^\W\d_][\w-]*|\w+(?:[./:#+-]+\w+)*(?:\+\+|#)?")
CAMEL = re.compile(r"[a-z0-9][A-Z]|[A-Z]{2}[a-z]")
NUMERIC = re.compile(r"[\d.,:/+#-]+")


class GazetteerEntry(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    type: Literal["TECHNOLOGY", "COMPONENT", "CONCEPT", "PROTOCOL"]
    aliases: list[str] = Field(min_length=1, max_length=20)
    # Aliases that are also ordinary words or names; exact only with context (P9-3).
    ambiguous: list[str] = Field(default_factory=list)
    case_sensitive: bool = True
    # The technology a component or concept belongs to; its ambiguous aliases hold in that technology's documents.
    technology: str | None = None
    category: str | None = None

    @model_validator(mode="after")
    def check_aliases(self) -> "GazetteerEntry":
        if any(not alias.strip() or alias != alias.strip() or len(alias) > 100 for alias in self.aliases):
            raise ValueError("aliases must be trimmed and nonblank")
        if not set(self.ambiguous) <= set(self.aliases):
            raise ValueError("every ambiguous alias must be an alias")
        if self.name not in self.aliases:
            raise ValueError("the canonical name must be one of its aliases")
        return self


class GazetteerFile(StrictModel):
    version: str = Field(min_length=1, max_length=100)
    entities: list[GazetteerEntry] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def unique(self) -> "GazetteerFile":
        names = [entry.name.casefold() for entry in self.entities]
        aliases = [alias.casefold() for entry in self.entities for alias in entry.aliases]
        if len(set(names)) != len(names) or len(set(aliases)) != len(aliases):
            raise ValueError("names and aliases must be unique across the gazetteer")
        return self


@dataclass(frozen=True)
class Mention:
    text: str
    canonical: str
    type: str
    rule_id: str
    confidence: float
    start: int
    end: int

    @property
    def key(self) -> str:
        """The filter key: canonical names compare without case (Q-16)."""
        return self.canonical.casefold()


class Gazetteer:
    def __init__(self, path: Path):
        try:
            raw = Path(path).read_bytes()
            self.file = GazetteerFile.model_validate(tomllib.loads(raw.decode("utf-8")))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError):
            raise TechDocQAError("INVALID_CONFIGURATION", "The gazetteer is unreadable or invalid.", stage="configuration") from None
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.lookup = {}
        sensitive, insensitive = [], []
        for entry in self.file.entities:
            for alias in entry.aliases:
                ambiguous = alias in entry.ambiguous
                if entry.case_sensitive:
                    self.lookup[("cs", alias)] = (entry, ambiguous)
                    sensitive.append(alias)
                else:
                    self.lookup[("ci", alias.casefold())] = (entry, ambiguous)
                    insensitive.append(alias)
        # Escaped literals, longest first, so the longer alias wins at a shared start ("Apache Kafka" over "Kafka").
        ordered = sorted([(alias, True) for alias in sensitive] + [(alias, False) for alias in insensitive],
                         key=lambda item: (-len(item[0]), item[0]))
        parts = [re.escape(alias) if exact else f"(?i:{re.escape(alias)})" for alias, exact in ordered]
        self.pattern = re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)")
        self.by_key = {entry.name.casefold(): entry for entry in self.file.entities}
        self.alias_key = {alias.casefold(): entry.name.casefold() for entry in self.file.entities for alias in entry.aliases}

    def resolve(self, text: str):
        found = self.lookup.get(("cs", text)) or self.lookup.get(("ci", text.casefold()))
        if found is None:
            raise KeyError(text)
        return found

    def filter_key(self, text: str) -> str:
        """A known alias resolves to its canonical name; any other text is its own key."""
        return self.alias_key.get(text.casefold(), text.casefold())


def config_id(gazetteer: Gazetteer, threshold: float) -> str:
    values = {"policy": ENTITY_POLICY, "gazetteer_sha256": gazetteer.sha256, "threshold": threshold,
              "confidence": CONFIDENCE, "protocol": PROTOCOL.pattern, "token": TOKEN.pattern}
    return "ec_" + hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def identifier_rule(token: str) -> str | None:
    """Which identifier rule a technical token meets, if any (dotted, snake_case, ::, a --flag, or camelCase)."""
    if "://" in token or NUMERIC.fullmatch(token):
        return None
    if token.startswith("-"):
        return "identifier"
    if "." in token or "_" in token or "::" in token:
        # Abbreviations such as e.g and i.e have no segment longer than one character.
        if max(len(part) for part in re.split(r"[._:]+", token)) < 2:
            return None
        return "identifier"
    if CAMEL.search(token) and token[0].isalpha():
        return "identifier-camel"
    return None


def candidates(text: str, gazetteer: Gazetteer, context: set[str]) -> list[Mention]:
    """Every rule's matches, before overlaps are resolved. context holds the canonical keys whose context rule holds."""
    found = []
    for match in gazetteer.pattern.finditer(text):
        entry, ambiguous = gazetteer.resolve(match.group())
        rule = "gazetteer-ambiguous" if ambiguous and entry.name.casefold() not in context else "gazetteer"
        found.append(Mention(match.group(), entry.name, entry.type, rule, CONFIDENCE[rule], match.start(), match.end()))
    for match in PROTOCOL.finditer(text):
        found.append(Mention(match.group(), match.group(), "PROTOCOL", "protocol", CONFIDENCE["protocol"], match.start(), match.end()))
    for match in TOKEN.finditer(text):
        rule = identifier_rule(match.group())
        if rule:
            found.append(Mention(match.group(), match.group(), "IDENTIFIER", rule, CONFIDENCE[rule], match.start(), match.end()))
    return found


def resolve_overlaps(found: list[Mention]) -> list[Mention]:
    """Longest match first, then rule priority; a mention inside a longer one is dropped (kafka in kafka-topics.sh)."""
    kept, starts, ends = [], [], []
    for mention in sorted(found, key=lambda m: (-(m.end - m.start), PRIORITY[m.rule_id], m.start)):
        # Kept spans never overlap, so only the neighbours on either side of the insertion point can collide.
        index = bisect.bisect_right(starts, mention.start)
        if (index and ends[index - 1] > mention.start) or (index < len(starts) and starts[index] < mention.end):
            continue
        kept.append(mention)
        starts.insert(index, mention.start)
        ends.insert(index, mention.end)
    return sorted(kept, key=lambda m: (m.start, m.end))


def context_keys(texts: list[str], gazetteer: Gazetteer, technology: str | None) -> set[str]:
    """Canonical keys whose ambiguous aliases count as exact in this document. An entry holds when the document's user
    technology names it, or an unambiguous alias of it (such as Apache Spark) occurs in the document; a component or
    concept also holds when its technology holds."""
    keys = {gazetteer.filter_key(technology)} if technology else set()
    for text in texts:
        for match in gazetteer.pattern.finditer(text):
            entry, ambiguous = gazetteer.resolve(match.group())
            if not ambiguous:
                keys.add(entry.name.casefold())
    keys |= {entry.name.casefold() for entry in gazetteer.file.entities
             if entry.technology and gazetteer.filter_key(entry.technology) in keys}
    return keys


def extract(text: str, gazetteer: Gazetteer, context: set[str]) -> list[Mention]:
    return resolve_overlaps(candidates(text, gazetteer, context))
