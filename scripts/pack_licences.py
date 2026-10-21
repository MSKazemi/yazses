#!/usr/bin/env python3
"""The build-time licence gate for ADR-028 feature add-on packs (owner answer Q7).

Every distribution that goes into a pack is put in one of four classes:

``permissive``  MIT, Apache-2.0, the BSD family, ISC, PSF and the like. Passes.
``LGPL``        weak copyleft: LGPL 2.0/2.1/3.0 and MPL-2.0. Passes only with a source
                offer, which the gate writes as ``LICENSES/SOURCE.md``. That needs an
                upstream source URL in the distribution's METADATA.
``GPL``         strong copyleft: GPL 2.0/3.0 and AGPL-3.0. Passes only with a recorded,
                per-pack owner approval in ``packaging/packs/licence-approvals.toml`` that
                names this exact distribution, version and licence, plus ``SOURCE.md``.
``UNKNOWN``     anything the gate cannot classify with certainty. Fails the pack.

A distribution with no licence file in its dist-info fails the pack whatever its class:
the pack has to carry the licence text, and there is none to carry.

Where the class comes from, in order:

1. ``License-Expression`` (PEP 639), parsed as an SPDX expression. ``OR`` takes the most
   permissive branch (the recipient may choose it), ``AND`` the strictest, and ``WITH``
   only ever relaxes: a known linking exception turns GPL into the LGPL class, an
   unknown exception id makes the whole expression ``UNKNOWN``.
2. Otherwise the legacy ``License`` field, if it is one line that parses as an SPDX
   expression or a small table of common spellings ("Apache 2.0", "MIT License"), and
   the ``License ::`` trove classifiers. When both are usable, the stricter one wins;
   several licence classifiers combine as ``AND``; an unrecognised one is ``UNKNOWN``.
3. Free text that parses as neither, and no licence classifier: ``UNKNOWN``.

A ``[[clarification]]`` entry in the approvals file can replace step 1-3 for one exact
``pack``/``dist``/``version`` with an SPDX expression a person read off the licence
file. The expression is then classified like any other, so a clarification to GPL still
needs an approval. A clarification never excuses a missing licence file.

A ``[[licence_text]]`` entry supplies the licence file a distribution does not ship: a
copy of the upstream text, committed under ``packaging/packs/licence-texts/`` and pinned
by SHA-256. It is used, and copied into the pack as ``LICENSES/<dist>/<file name>``,
only when its pack, distribution and exact version match, its ``spdx`` equals the
licence the distribution declares (or a clarification gives it), the committed file
exists and hashes to the recorded ``sha256``, and ``reviewed_by`` names the person who
read it. A distribution that ships its own licence file keeps it: an entry for it is
reported as redundant and never overrides the shipped text.

An approval, clarification or licence text whose dist, version or licence no longer
matches the pack is reported as stale and approves nothing. That is the point of
pinning the version: a new upstream release can change its licence, and an approval the
owner gave for 0.4.7 says nothing about 0.4.8. A clarification or licence text with an
empty ``reviewed_by`` is *prepared but unsigned*: it is reported as awaiting review and
honours nothing, so an agent can stage the entry and only a person can make it count.

Limits, stated so nobody reads more into a green gate than it checks: this reads
*declared metadata*. It cannot see a GPL binary vendored inside a wheel that declares
MIT. ADR-028 names ScanCode or a reviewed per-pack allowlist for that; neither is here.
This is engineering, not legal advice.

Standard library only. Everything above the ``I/O`` line is pure and is tested
directly by ``tests/test_pack_licences.py``; ``scripts/build-packs.py`` calls
:func:`check_pack` once per pack and adds :attr:`PackVerdict.vendored` (the reviewed
licence texts) to the archive.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
APPROVALS_TOML = ROOT / "packaging" / "packs" / "licence-approvals.toml"
#: Where the source offer goes inside a pack. The runtime accepts only ``pack.json``,
#: ``RECORD.json``, ``site``, ``stdlib`` and ``LICENSES`` at the top level
#: (``yazses.packs.archive.TOP_LEVEL``), so it cannot sit at the pack root.
SOURCE_MD = "LICENSES/SOURCE.md"
APPROVALS_FORMAT = 1
#: A ``[[licence_text]]`` ``file`` is relative to the approvals file's directory and
#: must sit under this folder (``packaging/packs/licence-texts/`` in the repository).
LICENCE_TEXTS_DIR = "licence-texts"

PERMISSIVE, LGPL, GPL, UNKNOWN = "permissive", "LGPL", "GPL", "UNKNOWN"
CLASSES = (PERMISSIVE, LGPL, GPL, UNKNOWN)
_RANK = {c: i for i, c in enumerate(CLASSES)}

_PERMISSIVE_IDS = {
    "0bsd", "apache-2.0", "bsd-1-clause", "bsd-2-clause", "bsd-3-clause",
    "bsd-3-clause-clear", "bsl-1.0", "cc0-1.0", "hpnd", "isc", "mit", "mit-0", "ncsa",
    "psf-2.0", "python-2.0", "unlicense", "x11", "zlib",
}
_LGPL_IDS = {
    "lgpl-2.0", "lgpl-2.0-only", "lgpl-2.0-or-later",
    "lgpl-2.1", "lgpl-2.1-only", "lgpl-2.1-or-later",
    "lgpl-3.0", "lgpl-3.0-only", "lgpl-3.0-or-later",
    "mpl-2.0", "mpl-2.0-no-copyleft-exception",
}
_GPL_IDS = {
    "gpl-2.0", "gpl-2.0-only", "gpl-2.0-or-later",
    "gpl-3.0", "gpl-3.0-only", "gpl-3.0-or-later",
    "agpl-3.0", "agpl-3.0-only", "agpl-3.0-or-later",
}
#: SPDX exception id -> the class it relaxes GPL to, or None for "changes nothing here".
#: An exception only ever *adds* permissions; one not listed makes the result UNKNOWN.
_EXCEPTIONS: dict[str, str | None] = {
    "llvm-exception": None,
    "classpath-exception-2.0": LGPL,
    "gcc-exception-2.0": LGPL,
    "gcc-exception-3.1": LGPL,
}
#: Common non-SPDX spellings of the legacy ``License`` field, matched whole.
_ALIASES = {
    "apache 2": "Apache-2.0", "apache 2.0": "Apache-2.0", "apache-2": "Apache-2.0",
    "apache license 2.0": "Apache-2.0", "apache license, version 2.0": "Apache-2.0",
    "apache license version 2.0": "Apache-2.0", "apache software license": "Apache-2.0",
    "apache software license 2.0": "Apache-2.0",
    "mit license": "MIT", "the mit license": "MIT", "mit licence": "MIT",
    "bsd license": "BSD-3-Clause", "new bsd": "BSD-3-Clause",
    "new bsd license": "BSD-3-Clause", "3-clause bsd": "BSD-3-Clause",
    "bsd 3-clause": "BSD-3-Clause", "bsd-3": "BSD-3-Clause", "bsd 2-clause": "BSD-2-Clause",
    "isc license": "ISC", "psf": "PSF-2.0", "psf license": "PSF-2.0",
}
_CLASSIFIERS = {
    "License :: OSI Approved :: Apache Software License": PERMISSIVE,
    "License :: OSI Approved :: BSD License": PERMISSIVE,
    "License :: OSI Approved :: Boost Software License 1.0 (BSL-1.0)": PERMISSIVE,
    "License :: OSI Approved :: ISC License (ISCL)": PERMISSIVE,
    "License :: OSI Approved :: MIT License": PERMISSIVE,
    "License :: OSI Approved :: MIT No Attribution License (MIT-0)": PERMISSIVE,
    "License :: OSI Approved :: Python Software Foundation License": PERMISSIVE,
    "License :: OSI Approved :: The Unlicense (Unlicense)": PERMISSIVE,
    "License :: OSI Approved :: zlib/libpng License": PERMISSIVE,
    "License :: OSI Approved :: Historical Permission Notice and Disclaimer (HPND)": PERMISSIVE,
    "License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication": PERMISSIVE,
    "License :: OSI Approved :: GNU Lesser General Public License v2 (LGPLv2)": LGPL,
    "License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)": LGPL,
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": LGPL,
    "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)": LGPL,
    "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)": LGPL,
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": LGPL,
    "License :: OSI Approved :: GNU General Public License (GPL)": GPL,
    "License :: OSI Approved :: GNU General Public License v2 (GPLv2)": GPL,
    "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)": GPL,
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)": GPL,
    "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)": GPL,
    "License :: OSI Approved :: GNU Affero General Public License v3": GPL,
    "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)": GPL,
}
#: Project-URL labels that name the source, best first (compared without case, spaces,
#: ``-`` or ``_``). The legacy ``Home-page`` comes after all of them.
_SOURCE_LABELS = ("source", "sourcecode", "repository", "code", "github", "homepage", "home")
_URL_RE = re.compile(r"^https?://[^\s<>\"']+$")
_TOKEN_RE = re.compile(r"\s*(\(|\)|[A-Za-z0-9.+:-]+)")
_LICENCE_FILE_PREFIXES = ("LICENSE", "LICENCE", "COPYING")


def canonical_name(name: str) -> str:
    """PEP 503 normalisation (the same rule build-packs.py uses)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def strictest(classes: Iterable[str]) -> str:
    return max(classes, key=_RANK.__getitem__, default=UNKNOWN)


def most_permissive(classes: Iterable[str]) -> str:
    return min(classes, key=_RANK.__getitem__, default=UNKNOWN)


# ======================================================================================
# Pure: SPDX expressions
# ======================================================================================


class _Unparsable(Exception):
    pass


def _id_class(token: str) -> str:
    low = token.lower()
    if low.startswith(("licenseref-", "documentref-")):
        return UNKNOWN
    if low.endswith("+"):
        low = low[:-1]
    for table, cls in ((_PERMISSIVE_IDS, PERMISSIVE), (_LGPL_IDS, LGPL), (_GPL_IDS, GPL)):
        if low in table:
            return cls
    return UNKNOWN


def _tokens(expr: str) -> list[str]:
    out: list[str] = []
    pos = 0
    text = expr.strip()
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise _Unparsable(expr)
        out.append(m.group(1))
        pos = m.end()
    return out


def _op(tok: str | None, name: str) -> bool:
    # SPDX allows the operators all upper case or all lower case, not mixed.
    return tok is not None and tok in (name, name.lower())


def classify_spdx(expr: str) -> str:
    """The class of one SPDX licence expression; ``UNKNOWN`` if it does not parse."""
    if not expr or "\n" in expr.strip():
        return UNKNOWN
    try:
        toks = _tokens(expr)
    except _Unparsable:
        return UNKNOWN
    pos = 0

    def peek() -> str | None:
        return toks[pos] if pos < len(toks) else None

    def take() -> str:
        nonlocal pos
        if pos >= len(toks):
            raise _Unparsable(expr)
        pos += 1
        return toks[pos - 1]

    def atom() -> str:
        tok = take()
        if tok == "(":
            cls = disjunction()
            if take() != ")":
                raise _Unparsable(expr)
            return cls
        if tok == ")" or any(_op(tok, o) for o in ("AND", "OR", "WITH")):
            raise _Unparsable(expr)
        cls = _id_class(tok)
        if _op(peek(), "WITH"):
            take()
            exc = take().lower()
            if exc not in _EXCEPTIONS:
                return UNKNOWN
            relaxed = _EXCEPTIONS[exc]
            if cls == GPL and relaxed is not None:
                return relaxed
        return cls

    def conjunction() -> str:
        parts = [atom()]
        while _op(peek(), "AND"):
            take()
            parts.append(atom())
        return strictest(parts)

    def disjunction() -> str:
        parts = [conjunction()]
        while _op(peek(), "OR"):
            take()
            parts.append(conjunction())
        return most_permissive(parts)

    try:
        cls = disjunction()
    except _Unparsable:
        return UNKNOWN
    return cls if pos == len(toks) else UNKNOWN


def classify_legacy_license(text: str) -> str | None:
    """The legacy ``License`` field: a class, or None for free text the gate cannot read."""
    value = text.strip()
    if not value or value.upper() == "UNKNOWN" or "\n" in value:
        return None
    alias = _ALIASES.get(re.sub(r"\s+", " ", value).lower())
    cls = classify_spdx(alias or value)
    return None if cls == UNKNOWN else cls


def classify_classifiers(classifiers: Iterable[str]) -> str | None:
    """``License ::`` trove classifiers combined as AND; None when there are none."""
    found = [c.strip() for c in classifiers if c.strip().startswith("License ::")]
    if not found:
        return None
    return strictest(_CLASSIFIERS.get(c, UNKNOWN) for c in found)


# ======================================================================================
# Pure: one distribution
# ======================================================================================


def parse_metadata(text: str) -> dict[str, list[str]]:
    """Core-metadata headers (RFC 822 style). A continued header keeps its newlines,
    so a multi-line ``License`` reads as free text, never as its first line alone."""
    out: dict[str, list[str]] = {}
    last: tuple[str, int] | None = None
    for line in text.replace("\r\n", "\n").split("\n\n", 1)[0].split("\n"):
        if line[:1] in (" ", "\t") and last is not None:
            key, i = last
            out[key][i] += "\n" + line.strip()
            continue
        if ":" not in line:
            last = None
            continue
        key, value = line.split(":", 1)
        values = out.setdefault(key.strip(), [])
        values.append(value.strip())
        last = (key.strip(), len(values) - 1)
    return out


def is_licence_file(rel_in_dist_info: str) -> bool:
    """A licence text: anything under PEP 639's ``licenses/``, or LICENSE*/LICENCE*/COPYING*.

    Narrower than build-packs' ``licence_member`` (which also copies NOTICE and AUTHORS):
    a NOTICE or an AUTHORS file alone is not the licence text a pack must carry.
    """
    parts = PurePosixPath(rel_in_dist_info).parts
    if not parts:
        return False
    if parts[0] == "licenses" and len(parts) > 1:
        return True
    return len(parts) == 1 and parts[0].upper().startswith(_LICENCE_FILE_PREFIXES)


def source_url(meta: Mapping[str, Sequence[str]]) -> str | None:
    """The upstream source location from METADATA: Project-URL by label, then Home-page."""
    labelled: dict[str, str] = {}
    for raw in meta.get("Project-URL", []):
        if "," not in raw:
            continue
        label, url = raw.split(",", 1)
        key = re.sub(r"[\s_-]+", "", label).lower()
        url = url.strip()
        if _URL_RE.match(url):
            labelled.setdefault(key, url)
    for key in _SOURCE_LABELS:
        if key in labelled:
            return labelled[key]
    for url in meta.get("Home-page", []):
        if _URL_RE.match(url.strip()):
            return url.strip()
    return None


@dataclass(frozen=True)
class Dist:
    """What the gate needs to know about one distribution in a pack."""

    name: str
    version: str
    metadata: Mapping[str, Sequence[str]]
    licence_files: tuple[str, ...] = ()


def declared_licence(meta: Mapping[str, Sequence[str]]) -> tuple[str, str, str]:
    """``(class, declared text, basis)`` from the metadata alone (rules 1-3 above)."""
    exprs = [e.strip() for e in meta.get("License-Expression", []) if e.strip()]
    if exprs:
        if len(exprs) > 1:
            return UNKNOWN, " | ".join(exprs), "License-Expression (repeated)"
        return classify_spdx(exprs[0]), exprs[0], "License-Expression"
    legacy = next((v.strip() for v in meta.get("License", []) if v.strip()), "")
    if legacy.upper() == "UNKNOWN":
        legacy = ""
    lic_cls = classify_legacy_license(legacy) if legacy else None
    licence_classifiers = [c.strip() for c in meta.get("Classifier", [])
                           if c.strip().startswith("License ::")]
    cls_cls = classify_classifiers(licence_classifiers)
    shown = legacy.split("\n", 1)[0][:120] if legacy else ""
    if lic_cls is not None and cls_cls is not None:
        return strictest((lic_cls, cls_cls)), shown, "License + classifiers"
    if lic_cls is not None:
        return lic_cls, shown, "License"
    if cls_cls is not None:
        return cls_cls, " AND ".join(c.rsplit(" :: ", 1)[-1] for c in licence_classifiers), (
            "classifiers"
        )
    if legacy:
        return UNKNOWN, shown, "License (free text, not an SPDX expression)"
    return UNKNOWN, "(not declared)", "none"


# ======================================================================================
# Pure: the approvals file
# ======================================================================================

_APPROVAL_FIELDS = ("pack", "dist", "version", "licence", "approved_by", "date", "reason")
_CLARIFY_FIELDS = ("pack", "dist", "version", "licence", "reviewed_by", "date", "reason")
_TEXT_FIELDS = ("pack", "dist", "version", "spdx", "source_url", "file", "sha256",
                "reviewed_by", "date")
#: The signature fields. In a clarification or a licence text they may be left empty,
#: which makes the entry *pending*: prepared, reported, and honoured by nothing.
_SIGNATURE = ("reviewed_by", "date")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Record:
    """One ``[[approval]]`` or ``[[clarification]]`` entry. ``by`` is approved_by /
    reviewed_by; empty only on a pending (unsigned) clarification."""

    kind: str
    pack: str
    dist: str
    version: str
    licence: str
    by: str
    date: str
    reason: str

    def describe(self) -> str:
        signed = f"by {self.by} on {self.date}" if self.by else "not yet reviewed"
        return f"{self.kind} for {self.dist} {self.version} ({self.licence}) {signed}"


@dataclass(frozen=True)
class LicenceText:
    """One ``[[licence_text]]`` entry: a reviewed copy of the licence file a distribution
    does not ship. ``file`` is relative to the approvals file's directory."""

    pack: str
    dist: str
    version: str
    spdx: str
    source_url: str
    file: str
    sha256: str
    by: str
    date: str
    kind: str = "licence_text"

    @property
    def licence(self) -> str:
        return self.spdx

    def member(self, dist_name: str) -> str:
        """Where the text goes in the pack, beside any other dist's licence files."""
        return f"LICENSES/{canonical_name(dist_name)}/{PurePosixPath(self.file).name}"

    def describe(self) -> str:
        signed = f"by {self.by} on {self.date}" if self.by else "not yet reviewed"
        return (f"{self.kind} for {self.dist} {self.version} ({self.spdx}, {self.file}) "
                f"{signed}")


@dataclass
class Approvals:
    approvals: list[Record] = field(default_factory=list)
    clarifications: list[Record] = field(default_factory=list)
    licence_texts: list[LicenceText] = field(default_factory=list)
    #: Prepared but unsigned entries (empty ``reviewed_by``). Reported, never honoured,
    #: and kept out of the lists above so no honouring path can see them.
    pending: list[Record | LicenceText] = field(default_factory=list)
    #: Entries that could not be read. They approve nothing; they are reported.
    errors: list[str] = field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _canon_spdx(text: str) -> str:
    """For comparing a licence text's ``spdx`` with the declared licence: ids without
    case, whitespace collapsed, and the legacy spellings (``Apache 2.0``) mapped."""
    flat = re.sub(r"\s+", " ", text).strip()
    return _norm(_ALIASES.get(flat.lower(), flat))


def _text_file_error(rel: str) -> str | None:
    """Why a ``[[licence_text]]`` ``file`` value is not acceptable, or None."""
    if "\\" in rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        return "file (a relative POSIX path)"
    parts = PurePosixPath(rel).parts
    if (len(parts) < 2 or parts[0] != LICENCE_TEXTS_DIR
            or any(p in ("", ".", "..") for p in parts)):
        return f"file (a path under {LICENCE_TEXTS_DIR}/, without '..')"
    return None


def parse_approvals(doc: Any) -> Approvals:
    """``licence-approvals.toml`` as loaded by tomllib. Never raises: a malformed entry
    is an error string and approves nothing, so a broken file can only withhold."""
    out = Approvals()
    if not isinstance(doc, dict) or doc.get("format") != APPROVALS_FORMAT:
        out.errors.append(f"licence-approvals.toml: missing or unknown `format` "
                          f"(expected {APPROVALS_FORMAT}); no approval is honoured")
        return out
    for table, fields_ in (("approval", _APPROVAL_FIELDS),
                           ("clarification", _CLARIFY_FIELDS),
                           ("licence_text", _TEXT_FIELDS)):
        entries = doc.get(table, [])
        if not isinstance(entries, list):
            out.errors.append(f"`{table}` is not an array of tables")
            continue
        # Only a person's review can be left for later; an owner approval cannot.
        may_pend = table != "approval"
        for i, raw in enumerate(entries):
            where = f"[[{table}]] #{i + 1}"
            if not isinstance(raw, dict):
                out.errors.append(f"{where} is not a table")
                continue
            vals: dict[str, str] = {}
            bad = []
            for k in fields_:
                v = raw.get(k)
                if isinstance(v, _dt.date) and not isinstance(v, _dt.datetime) and k == "date":
                    v = v.isoformat()
                if isinstance(v, str) and (v.strip() or (may_pend and k in _SIGNATURE)):
                    vals[k] = v.strip()
                else:
                    bad.append(k)
            by = vals.get("approved_by" if table == "approval" else "reviewed_by", "")
            pending = may_pend and not bad and not by
            if not bad and not pending and not _DATE_RE.fullmatch(vals["date"]):
                bad.append("date (YYYY-MM-DD)")
            if table == "licence_text" and not bad:
                if not _SHA256_RE.fullmatch(vals["sha256"]):
                    bad.append("sha256 (64 lower-case hex digits)")
                if not _URL_RE.match(vals["source_url"]):
                    bad.append("source_url (an http(s) URL)")
                if (err := _text_file_error(vals["file"])) is not None:
                    bad.append(err)
            if bad:
                out.errors.append(f"{where} is missing or has an empty or invalid "
                                  f"{', '.join(bad)}")
                continue
            rec: Record | LicenceText
            if table == "licence_text":
                rec = LicenceText(pack=vals["pack"], dist=vals["dist"],
                                  version=vals["version"], spdx=vals["spdx"],
                                  source_url=vals["source_url"], file=vals["file"],
                                  sha256=vals["sha256"], by=by, date=vals["date"])
            else:
                rec = Record(kind=table, pack=vals["pack"], dist=vals["dist"],
                             version=vals["version"], licence=vals["licence"], by=by,
                             date=vals["date"], reason=vals["reason"])
            if pending:
                out.pending.append(rec)
            elif isinstance(rec, LicenceText):
                out.licence_texts.append(rec)
            elif table == "approval":
                out.approvals.append(rec)
            else:
                out.clarifications.append(rec)
    return out


# ======================================================================================
# Pure: one pack
# ======================================================================================


@dataclass
class DistVerdict:
    name: str
    version: str
    licence: str
    licence_class: str
    basis: str
    licence_files: int
    source_url: str | None
    approved_by: str | None = None
    #: The ``[[licence_text]]`` that stands in for a missing licence file, if one did.
    vendored_licence: dict[str, str] | None = None
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name, "version": self.version, "licence": self.licence,
            "class": self.licence_class, "basis": self.basis,
            "licence_files": self.licence_files,
        }
        if self.source_url:
            out["source_url"] = self.source_url
        if self.approved_by:
            out["approved_by"] = self.approved_by
        if self.vendored_licence:
            out["vendored_licence"] = dict(self.vendored_licence)
        if self.problems:
            out["problems"] = list(self.problems)
        return out


@dataclass
class PackVerdict:
    pack: str
    dists: list[DistVerdict]
    problems: list[str]
    stale: list[str]
    source_md: str | None
    #: Prepared entries for this pack that nobody has signed yet. They honour nothing.
    pending: list[str] = field(default_factory=list)
    #: Reviewed licence texts to add to the pack: archive member -> the exact bytes.
    vendored: dict[str, bytes] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems

    def report(self) -> dict[str, Any]:
        """The build report's ``licence_gate`` entry."""
        return {
            "ok": self.ok,
            "distributions": [d.as_dict() for d in self.dists],
            "problems": list(self.problems),
            "stale_approvals": list(self.stale),
            "awaiting_review": list(self.pending),
            "vendored_licences": sorted(self.vendored),
            "source_offer": SOURCE_MD if self.source_md else None,
        }

    def pack_json(self) -> list[dict[str, str]]:
        """The ``licences`` key of pack.json: one row per distribution."""
        return [{"name": d.name, "version": d.version, "licence": d.licence,
                 "class": d.licence_class} for d in self.dists]


def _match(rec: Record | LicenceText, pack: str, dist: Dist) -> bool:
    return rec.pack == pack and canonical_name(rec.dist) == canonical_name(dist.name)


def _stale_reason(rec: Record | LicenceText, pack: str, dists: Sequence[Dist],
                  current: Mapping[str, DistVerdict], rejected: Mapping[int, str]) -> str:
    same = [d for d in dists if _match(rec, pack, d)]
    if not same:
        return f"{rec.describe()}: {rec.dist} is not in pack {pack!r}"
    d = same[0]
    if rec.version != d.version:
        return f"{rec.describe()}: the pack now has {d.name} {d.version}"
    if id(rec) in rejected:
        return f"{rec.describe()}: {rejected[id(rec)]}"
    v = current.get(canonical_name(d.name))
    if v is not None and rec.kind == "approval":
        if _norm(rec.licence) != _norm(v.licence):
            return f"{rec.describe()}: the licence is now {v.licence!r}"
        if v.licence_class != GPL:
            return f"{rec.describe()}: not needed, {d.name} is {v.licence_class}"
    return f"{rec.describe()}: unused"


def _pending_reason(rec: Record | LicenceText, pack: str, dists: Sequence[Dist]) -> str:
    why = (f"{rec.describe()}: awaiting review (reviewed_by is empty), so it honours "
           f"nothing until a person who has read the licence signs it")
    same = [d for d in dists if _match(rec, pack, d)]
    if not same:
        return f"{why}; and {rec.dist} is not in pack {pack!r}"
    if rec.version != same[0].version:
        return f"{why}; and the pack now has {same[0].name} {same[0].version}"
    return why


def _licence_text_problem(rec: LicenceText, dist: Dist, declared: str,
                          data: bytes | None) -> str | None:
    """Why a signed, version-matched licence text cannot stand in for ``dist``'s
    missing licence file, or None when it can."""
    if dist.licence_files:
        return (f"redundant: {dist.name} ships its own licence file "
                f"({', '.join(dist.licence_files)}); the recorded text is not used")
    if _canon_spdx(rec.spdx) != _canon_spdx(declared):
        return (f"the text is recorded as {rec.spdx!r} but {dist.name} {dist.version} "
                f"declares {declared!r}")
    if data is None:
        return f"{rec.file} is missing"
    got = hashlib.sha256(data).hexdigest()
    if got != rec.sha256:
        return f"{rec.file} has sha256 {got}, the entry records {rec.sha256}"
    return None


def evaluate_pack(pack: str, dists: Sequence[Dist], approvals: Approvals | None = None,
                  texts: Mapping[str, bytes | None] | None = None) -> PackVerdict:
    """Apply the Q7 rules to one pack. Pure; ``problems`` non-empty means withhold.

    ``texts`` maps a ``[[licence_text]]`` ``file`` to its bytes (None or absent: the file
    could not be read). Only :func:`check_pack` reads the files.
    """
    approvals = approvals or Approvals()
    texts = texts or {}
    used: set[int] = set()
    rejected: dict[int, str] = {}
    vendored: dict[str, bytes] = {}
    verdicts: dict[str, DistVerdict] = {}
    out: list[DistVerdict] = []
    for dist in sorted(dists, key=lambda d: canonical_name(d.name)):
        cls, declared, basis = declared_licence(dist.metadata)
        for rec in approvals.clarifications:
            if _match(rec, pack, dist) and rec.version == dist.version:
                cls, declared = classify_spdx(rec.licence), rec.licence
                basis = f"clarification by {rec.by} on {rec.date}"
                used.add(id(rec))
                break
        v = DistVerdict(name=dist.name, version=dist.version, licence=declared,
                        licence_class=cls, basis=basis,
                        licence_files=len(dist.licence_files),
                        source_url=source_url(dist.metadata))
        who = f"{dist.name} {dist.version}"
        unsigned = {p.kind for p in approvals.pending
                    if _match(p, pack, dist) and p.version == dist.version}
        text_why: list[str] = []
        for lt in approvals.licence_texts:
            if not (_match(lt, pack, dist) and lt.version == dist.version):
                continue
            data = texts.get(lt.file)
            why = _licence_text_problem(lt, dist, declared, data)
            if why is None and v.vendored_licence is not None:
                why = "unused: another licence text for this distribution is already used"
            if why is not None or data is None:
                rejected[id(lt)] = why or f"{lt.file} is missing"
                text_why.append(rejected[id(lt)])
                continue
            used.add(id(lt))
            vendored[lt.member(dist.name)] = data
            v.vendored_licence = {"file": lt.file, "member": lt.member(dist.name),
                                  "spdx": lt.spdx, "source_url": lt.source_url,
                                  "sha256": lt.sha256,
                                  "reviewed_by": f"{lt.by} on {lt.date}"}
        if not dist.licence_files and v.vendored_licence is None:
            msg = f"{who}: no licence file in its dist-info"
            if text_why:
                msg += f" (recorded licence text not used: {'; '.join(text_why)})"
            elif "licence_text" in unsigned:
                msg += " (a licence text is recorded but awaits review)"
            v.problems.append(msg)
        if cls == UNKNOWN:
            msg = f"{who}: licence not classifiable ({basis}: {declared!r})"
            if "clarification" in unsigned:
                msg += " (a clarification is recorded but awaits review)"
            v.problems.append(msg)
        if cls in (LGPL, GPL) and not v.source_url:
            v.problems.append(f"{who}: {cls} needs a source offer, and METADATA names no "
                              f"upstream source URL (Project-URL or Home-page)")
        if cls == GPL:
            hit = next((r for r in approvals.approvals
                        if _match(r, pack, dist) and r.version == dist.version
                        and _norm(r.licence) == _norm(declared)), None)
            if hit is None:
                v.problems.append(
                    f"{who}: GPL ({declared}) needs a recorded owner approval for pack "
                    f"{pack!r} in packaging/packs/licence-approvals.toml")
            else:
                used.add(id(hit))
                v.approved_by = f"{hit.by} on {hit.date}"
        verdicts[canonical_name(dist.name)] = v
        out.append(v)
    recorded: list[Record | LicenceText] = [
        *approvals.clarifications, *approvals.approvals, *approvals.licence_texts]
    stale = [
        _stale_reason(rec, pack, dists, verdicts, rejected)
        for rec in recorded
        if rec.pack == pack and id(rec) not in used
    ]
    stale += [f"ignored: {e}" for e in approvals.errors]
    pending = [_pending_reason(rec, pack, dists) for rec in approvals.pending
               if rec.pack == pack]
    problems = [p for v in out for p in v.problems]
    copyleft = [v for v in out if v.licence_class in (LGPL, GPL)]
    return PackVerdict(pack=pack, dists=out, problems=problems, stale=stale,
                       source_md=render_source_md(pack, copyleft) if copyleft else None,
                       pending=pending, vendored=vendored)


def render_source_md(pack: str, copyleft: Sequence[DistVerdict]) -> str:
    """``LICENSES/SOURCE.md``: where the source of every copyleft component lives."""
    lines = [
        f"# Source code offer: add-on pack `{pack}`",
        "",
        "This YazSes add-on pack contains the components below, which are distributed",
        "under copyleft licences. Each was installed unmodified from its published",
        "wheel at exactly the version listed. The complete corresponding source of",
        "that version is available from its upstream project and from its PyPI",
        "release page. The licence texts are in this pack's `LICENSES/` folder.",
        "",
        "YazSes itself is Apache-2.0: https://github.com/MSKazemi/yazses",
        "",
        "| Component | Version | Licence | Upstream source | PyPI release |",
        "|---|---|---|---|---|",
    ]
    for v in sorted(copyleft, key=lambda d: canonical_name(d.name)):
        pypi = f"https://pypi.org/project/{canonical_name(v.name)}/{v.version}/"
        lic = v.licence.replace("|", "/")
        lines.append(f"| {v.name} | {v.version} | {lic} ({v.licence_class}) | "
                     f"{v.source_url or '(none)'} | {pypi} |")
    approved = [v for v in copyleft if v.approved_by]
    if approved:
        lines += ["", "GPL components included with the maintainer's recorded approval:", ""]
        lines += [f"- {v.name} {v.version}: approved by {v.approved_by}" for v in approved]
    return "\n".join(lines) + "\n"


# ======================================================================================
# I/O below this line
# ======================================================================================


def read_dist(dist_info: Path) -> Dist:
    """One ``*.dist-info`` directory of an installed ``--target`` tree."""
    meta = parse_metadata((dist_info / "METADATA").read_text(encoding="utf-8",
                                                             errors="replace"))
    files = tuple(sorted(
        p.relative_to(dist_info).as_posix() for p in dist_info.rglob("*")
        if p.is_file() and is_licence_file(p.relative_to(dist_info).as_posix())
    ))
    name = (meta.get("Name") or [dist_info.name.split("-")[0]])[0]
    version = (meta.get("Version") or ["?"])[0]
    return Dist(name=name, version=version, metadata=meta, licence_files=files)


def load_approvals(path: Path | None = None) -> Approvals:
    """The approvals file. Missing or unreadable means *no approvals*, reported."""
    path = path or APPROVALS_TOML
    try:
        with path.open("rb") as fh:
            doc = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return Approvals(errors=[f"{path.name} could not be read ({exc}); "
                                 "no approval is honoured"])
    return parse_approvals(doc)


def read_licence_texts(approvals: Approvals, base: Path, pack: str | None = None
                       ) -> dict[str, bytes | None]:
    """The bytes of every signed ``[[licence_text]]`` file (for one pack, if given),
    relative to ``base``, the approvals file's directory. A file that is missing,
    unreadable, or resolves outside ``base/licence-texts`` (a symlink out) reads as
    None, which the gate reports as missing."""
    root = (base / LICENCE_TEXTS_DIR).resolve()
    out: dict[str, bytes | None] = {}
    for rec in approvals.licence_texts:
        if pack is not None and rec.pack != pack:
            continue
        path = (base / rec.file).resolve()
        try:
            out[rec.file] = path.read_bytes() if path.is_relative_to(root) else None
        except OSError:
            out[rec.file] = None
    return out


def check_pack(pack: str, dist_infos: Iterable[Path],
               approvals_path: Path | None = None) -> PackVerdict:
    """The gate build-packs.py calls once per pack, after the wheels are installed."""
    path = approvals_path or APPROVALS_TOML
    approvals = load_approvals(path)
    return evaluate_pack(pack, [read_dist(d) for d in dist_infos], approvals,
                         read_licence_texts(approvals, path.parent, pack))
