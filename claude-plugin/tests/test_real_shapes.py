"""Who am I, the question gate and compact-check, on the shapes real Orca gives (see support.py)."""
import json
import unittest

from support import CHAT_ENV, CHAT_ID, TERM_ENV, TERM_ID, TERM_PANE, HomeCase, agent


class ResolveSelf(HomeCase):
    def test_a_terminal_worker_is_found_by_its_pane_key(self):
        self.set_orca(agents=[agent("terminal", TERM_ID, TERM_PANE, "🤖 fix the index")])
        self.assertFalse(self.asks(TERM_ENV))

    def test_the_scrub_safe_pane_variable_works_too(self):
        self.set_orca(agents=[agent("terminal", TERM_ID, TERM_PANE, "🤖 fix the index")])
        self.assertFalse(self.asks({"ORCA_AGENT_PANE": TERM_PANE}))

    def test_a_terminal_agent_without_an_orca_id_yet_is_still_found(self):
        self.set_orca(agents=[agent("terminal", None, TERM_PANE, "🤖 just started")])
        self.assertFalse(self.asks(TERM_ENV))

    def test_a_chat_is_found_by_its_session_id(self):
        self.set_orca(agents=[agent("chat", CHAT_ID, "chat-tab:leaf", "🤖 task")])
        self.assertFalse(self.asks(CHAT_ENV))

    def test_a_terminal_coordinators_wiki_is_found_by_its_pane_key(self):
        out = self.run_script("wiki", "where", env=TERM_ENV)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.strip().endswith("conductor/wiki/search"))

    def test_no_identity_is_no_coordinator(self):
        self.assertEqual(self.run_script("wiki", "where").returncode, 1)

    def test_a_slow_agent_list_does_not_open_the_gate(self):
        # A chat, so this fails on the wait alone. The real list once took over 2 s.
        self.set_orca(agents=[agent("chat", CHAT_ID, "chat-tab:leaf", "🤖 task")], delay=3.2)
        self.assertFalse(self.asks(CHAT_ENV))


class Gate(HomeCase):
    def test_a_child_is_a_worker_by_its_workspace_name(self):
        # A worker's title is often null or the conversation's own name; the display name stays.
        for title in (None, "Fix the index"):
            self.set_orca(agents=[agent("terminal", TERM_ID, TERM_PANE, title, workspace="🤖 fix-index")])
            self.assertFalse(self.asks(TERM_ENV))

    def test_a_workspace_name_never_makes_a_coordinator(self):
        self.set_orca(agents=[agent("terminal", TERM_ID, TERM_PANE, "🤖 task", workspace="🎖️ Search")])
        self.assertFalse(self.asks(TERM_ENV))

    def test_the_gate_setting_reaches_the_claude_hook(self):
        self.set_orca(agents=[agent("terminal", TERM_ID, TERM_PANE, "🤖 task")])
        self.assertTrue(self.asks({**TERM_ENV, "CONDUCTOR_GATE": "off"}))

    def test_a_role_set_by_hand_beats_the_title(self):
        self.set_orca(agents=[agent("terminal", TERM_ID, TERM_PANE, "🤖 promoted")])
        env = {**TERM_ENV, "CONDUCTOR_ROLE": "coordinator"}
        self.assertTrue(self.asks({**env, "CONDUCTOR_ROLE_SOURCE": "agent"}))
        self.assertFalse(self.asks({**env, "CONDUCTOR_ROLE_SOURCE": "workspace"}))

    def test_custom_markers_may_hold_commas_and_equals_signs(self):
        self.set_orca(agents=[agent("terminal", TERM_ID, TERM_PANE, "[w,=] task")])
        self.assertFalse(self.asks({**TERM_ENV, "CONDUCTOR_MARKERS": json.dumps({"worker": "[w,=]"})}))

    def test_no_role_may_ask_when_the_list_is_none(self):
        self.assertFalse(self.asks({**TERM_ENV, "CONDUCTOR_ASK_ROLES": "none"}))


class CompactCheck(HomeCase):
    def transcript(self, name, tokens):
        # Named by the Claude session id, which is not the Orca session id.
        path = self.top / f"{name}.jsonl"
        path.write_text(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": tokens}}}) + "\n")
        return path

    def start(self, env, session, path, event="SessionStart"):
        self.fire(event, {"hook_event_name": event, "session_id": session, "source": "startup",
                          "transcript_path": str(path)}, env)

    def rows(self):
        out = self.run_script("compact-check", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        return {r["session"]: r for r in json.loads(out.stdout)["rows"]}

    def test_a_terminal_agents_transcript_is_recorded_under_its_pane_key(self):
        self.start(TERM_ENV, "claude-session-a", self.transcript("claude-session-a", 400000))
        row = self.rows()[TERM_ID]
        self.assertEqual((row["tokens"], row["why"]), (400000, "due"))

    def test_a_chats_transcript_is_recorded_under_its_session_id(self):
        self.start(CHAT_ENV, "claude-session-b", self.transcript("claude-session-b", 350000))
        row = self.rows()[CHAT_ID]
        self.assertEqual((row["tokens"], row["why"]), (350000, "due"))

    def test_no_count_until_the_session_has_started_with_the_plugin(self):
        for row in self.rows().values():
            self.assertIsNone(row["tokens"])
            self.assertEqual(row["why"], "no count until the session has started with the plugin")

    def test_a_new_session_in_the_pane_replaces_the_old_transcript(self):
        self.start(TERM_ENV, "claude-old", self.transcript("claude-old", 400000))
        self.start(TERM_ENV, "claude-new", self.transcript("claude-new", 1000))
        self.assertEqual(self.rows()[TERM_ID]["tokens"], 1000)

    def test_the_next_prompt_takes_the_record_back_from_a_nested_claude(self):
        outer = self.transcript("claude-outer", 400000)
        self.start(TERM_ENV, "claude-outer", outer)
        self.start(TERM_ENV, "claude-nested", self.transcript("claude-nested", 10))
        self.start(TERM_ENV, "claude-outer", outer, event="UserPromptSubmit")
        self.assertEqual(self.rows()[TERM_ID]["tokens"], 400000)

    def test_a_missing_transcript_says_so(self):
        self.start(TERM_ENV, "claude-gone", self.top / "gone.jsonl")
        self.assertEqual(self.rows()[TERM_ID]["why"], "its recorded transcript has no count yet")

    def test_outside_orca_nothing_is_recorded(self):
        self.start({}, "claude-session-c", self.transcript("claude-session-c", 9))
        self.assertFalse((self.top / "state" / "agents").exists())

    def test_ask_wiki_mails_a_chat_by_id_and_a_terminal_by_handle(self):
        self.start(TERM_ENV, "claude-a", self.transcript("claude-a", 400000))
        self.start(CHAT_ENV, "claude-b", self.transcript("claude-b", 400000))
        self.assertEqual(self.run_script("compact-check", "--ask-wiki").returncode, 0)
        to = {c["args"][c["args"].index("--to") + 1] for c in self.calls("orchestration send")}
        self.assertEqual(to, {"term_search", f"orca_session_id:{CHAT_ID}"})


if __name__ == "__main__":
    unittest.main()
