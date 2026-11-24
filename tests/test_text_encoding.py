"""No double-encoded UTF-8 ("mojibake") in user-visible source text.

UTF-8 text read as Windows-1252 and saved again turns an ellipsis into three
characters (shown as "Browse" followed by garbage in the interface).  Any run
of non-ASCII characters that is itself valid UTF-8 once encoded as
Windows-1252 is reported.  This file is ASCII-only on purpose.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = re.compile("[\u0080-\uffff]{2,}")
ELLIPSIS = "\u2026"
DOUBLE_ENCODED_ELLIPSIS = "\u00e2\u20ac\u00a6"


def double_encoded(text):
    found = []
    for match in RUN.finditer(text):
        try:
            repaired = match.group(0).encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if repaired != match.group(0):
            found.append((match.group(0), repaired))
    return found


class TextEncodingTests(unittest.TestCase):
    def test_detector_recognises_double_encoding(self):
        self.assertEqual(double_encoded("Browse" + DOUBLE_ENCODED_ELLIPSIS),
                         [(DOUBLE_ENCODED_ELLIPSIS, ELLIPSIS)])
        correct = "Browse\u2026 \u2014 2\u00d7 \u00b11 \u00b7 \u2192 \u2212"
        self.assertEqual(double_encoded(correct), [])

    def test_source_and_docs_have_no_double_encoded_text(self):
        paths = (sorted(ROOT.glob("vector1a/**/*.py")) + sorted(ROOT.glob("vector1a/**/*.yml"))
                 + sorted(ROOT.glob("*.md")) + sorted(ROOT.glob("docs/**/*.md")))
        problems = {}
        for path in paths:
            found = double_encoded(path.read_text(encoding="utf-8"))
            if found:
                problems[path.relative_to(ROOT).as_posix()] = len(found)
        self.assertEqual(problems, {})


if __name__ == "__main__":
    unittest.main()
