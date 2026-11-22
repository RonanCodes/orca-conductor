"""The pure sleep and wake core: comment segments, org chart cells, matching and guards."""
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import coordinator_sleep as cs  # noqa: E402

TABLE = ("Intro line\n\n| Coordinator | Owns | Wiki | Session id |\n| --- | --- | --- | --- |\n"
         "| 🎖️ 🧠 Search • ranking | Ranking models | [`search/`](x/index.md) | `sid-search` |\n"
         "| 🎖️ 📝 Docs • handbook | Handbook and tutorials | `conductor/wiki/docs/` | `sid-docs` (note) |\n"
         "\n| Other | table |\n| --- | --- |\n| a | b |\n")


class Comment(unittest.TestCase):
    def test_add_keeps_other_text_and_is_idempotent(self):
        c = cs.add_marker("child of X • role text", "Search", "2026-11-22", "owns ranking; idle")
        self.assertTrue(c.startswith("child of X • role text "))
        self.assertIn("💤 Search asleep since 2026-11-22: owns ranking; idle", c)
        self.assertEqual(cs.add_marker(c, "Search", "2026-12-01", "other"), c)

    def test_several_share_one_comment(self):
        c = cs.add_marker(cs.add_marker("", "Search", "2026-11-22", "a"), "Docs", "2026-11-23", "b")
        self.assertEqual(cs.asleep_in_comment(c), {"Search": ("2026-11-22", "a"), "Docs": ("2026-11-23", "b")})
        self.assertEqual(cs.asleep_in_comment(cs.remove_marker(c, "Search")), {"Docs": ("2026-11-23", "b")})

    def test_remove_keeps_other_text_and_is_idempotent(self):
        c = cs.add_marker("role text", "Search", "2026-11-22", "a")
        self.assertEqual(cs.remove_marker(c, "Search"), "role text")
        self.assertEqual(cs.remove_marker("role text", "Search"), "role text")

    def test_text_on_a_later_line_survives(self):
        c = cs.add_marker("", "Search", "2026-11-22", "a") + "\nlater text"
        self.assertEqual(cs.remove_marker(c, "Search"), "later text")

    def test_note_is_one_line_without_sleep_emoji_or_pipes(self):
        self.assertEqual(cs.clean_note("a\n b | c 💤 d"), "a b / c d")


class Table(unittest.TestCase):
    def test_add_state_column_only_in_the_org_chart(self):
        t = cs.add_state_column(TABLE)
        self.assertIn("| Coordinator | Owns | Wiki | Asleep/Awake | Session id |", t)
        self.assertIn("| [`search/`](x/index.md) | 🟢 awake | `sid-search` |", t)
        self.assertIn("| a | b |", t)
        self.assertTrue(t.startswith("Intro line\n\n"))
        self.assertEqual(cs.add_state_column(t), t)

    def test_rows_and_set_state(self):
        t = cs.add_state_column(TABLE)
        self.assertEqual([r["session"] for r in cs.table_rows(t)], ["sid-search", "sid-docs"])
        t2 = cs.set_state(t, "sid-docs", cs.asleep_cell("2026-11-22", "idle | done"))
        self.assertEqual(cs.asleep_sessions(t2), {"sid-docs": "💤 asleep since 2026-11-22: idle / done"})
        self.assertEqual(len(t2.splitlines()), len(t.splitlines()))
        self.assertEqual(cs.asleep_sessions(cs.set_state(t2, "sid-docs", cs.AWAKE_CELL)), {})
        with self.assertRaises(KeyError):
            cs.set_state(t, "nope", cs.AWAKE_CELL)
        with self.assertRaises(ValueError):
            cs.set_state(TABLE, "sid-search", cs.AWAKE_CELL)

    def test_match_by_shared_words(self):
        t = cs.set_state(cs.add_state_column(TABLE), "sid-docs", cs.asleep_cell("2026-11-22", "owns tutorials; why parked"))
        rows = cs.table_rows(t)
        self.assertEqual([r["session"] for r, _ in cs.match_asleep("Tutorials round two", rows)], ["sid-docs"])
        self.assertEqual(cs.match_asleep("Ranking models", rows), [])  # awake
        self.assertEqual(cs.match_asleep("why owns notes 2026 new coordinator", rows), [])  # stop words and a year


class Guards(unittest.TestCase):
    def test_every_ending_word_is_refused(self):
        for word in sorted(cs.FORBIDDEN_WORDS):
            self.assertEqual(cs.forbidden([word]), word)
            self.assertEqual(cs.forbidden(["orchestration", f"worker-{word}"]), word)

    def test_option_values_and_safe_commands_pass(self):
        self.assertIsNone(cs.forbidden(["worktree", "set", "--comment", "close the rm stop"]))
        self.assertIsNone(cs.forbidden(["orchestration", "send", "--to", "run:x"]))

    def test_native_seams_do_nothing_today(self):
        self.assertFalse(cs.native_sleep("path:/x"))
        self.assertFalse(cs.native_wake("path:/x"))


if __name__ == "__main__":
    unittest.main()
