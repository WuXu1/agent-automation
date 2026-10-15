import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jv_speech as s  # noqa: E402

LONG = ("The essay is in. Tom checked it against the brief and found one thing worth fixing: the "
        "loop in question three never terminates on empty input. Everything else matches the "
        "marking scheme. The full notes are below.\n\n- Q1 fine\n- Q2 fine\n- Q3 loop\n"
        "See /data/.hermes/owner/study/essay.md and https://moodle.example.ac.uk/mod/assign/1234")


class CleanTest(unittest.TestCase):
    def test_strips_markdown_urls_and_paths(self):
        out = s.clean("**Done**. See `notes` at /data/x/y.md or https://a.b/c\n- item")
        self.assertEqual(out, "Done. See notes at or item")

    def test_short_plain_text_is_spoken_verbatim(self):
        self.assertFalse(s.needs_rewrite("The reminder is set for six."))

    def test_long_or_structured_text_is_rewritten(self):
        self.assertTrue(s.needs_rewrite(LONG))
        self.assertTrue(s.needs_rewrite("Done.\n- one\n- two"))
        self.assertTrue(s.needs_rewrite("See https://example.com"))


class FirstSentencesTest(unittest.TestCase):
    def test_keeps_whole_sentences_within_limit(self):
        out = s.first_sentences("One two. Three four. Five six.", limit=20)
        self.assertEqual(out, "One two. Three four.")

    def test_cuts_a_single_long_sentence_at_a_word(self):
        out = s.first_sentences("word " * 200, limit=30)
        self.assertLessEqual(len(out), 30)
        self.assertFalse(out.endswith(" "))


class SpokenVersionTest(unittest.TestCase):
    def test_short_text_needs_no_model(self):
        def llm(_):
            raise AssertionError("must not be called")
        self.assertEqual(s.spoken_version("Very good.", persona="Atlas", style="", llm=llm),
                         "Very good.")

    def test_long_text_uses_the_model_and_is_cleaned_and_capped(self):
        seen = {}

        def llm(messages):
            seen["messages"] = messages
            return "**The essay is in.** Tom found one loop to fix before Thursday."
        out = s.spoken_version(LONG, persona="Atlas", style="STYLE RULES", llm=llm)
        self.assertEqual(out, "The essay is in. Tom found one loop to fix before Thursday.")
        system = seen["messages"][0]["content"]
        self.assertIn("Atlas", system)
        self.assertIn("STYLE RULES", system)
        self.assertEqual(seen["messages"][1]["content"], LONG)

    def test_model_failure_falls_back_to_first_sentences(self):
        def llm(_):
            raise TimeoutError("slow")
        out = s.spoken_version(LONG, persona="Atlas", style="", llm=llm)
        self.assertTrue(out.startswith("The essay is in."))
        self.assertLessEqual(len(out), s.SPOKEN_MAX_CHARS)
        self.assertNotIn("http", out)

    def test_empty_model_reply_falls_back(self):
        out = s.spoken_version(LONG, persona="Atlas", style="", llm=lambda _: "  ")
        self.assertTrue(out.startswith("The essay is in."))


if __name__ == "__main__":
    unittest.main()
