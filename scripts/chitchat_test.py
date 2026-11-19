"""Focus gating tests, with tmux replaced by a stub of tmux_focus.

The worker runs for real, with generation and playback, Spotify, and the poll's
sleep replaced, and each test checks the log of what it said and when it waited.
Run with: python3 scripts/chitchat_test.py -v
"""

import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HOME = tempfile.mkdtemp(prefix="chitchat-test-")
os.environ["XDG_STATE_HOME"] = HOME
os.environ["XDG_DATA_HOME"] = HOME
os.environ.pop("CHITCHAT_FOCUS", None)
os.environ.pop("CHITCHAT_DUCK", None)

loader = importlib.machinery.SourceFileLoader("chitchat", str(Path(__file__).with_name("chitchat")))
chitchat = importlib.util.module_from_spec(importlib.util.spec_from_loader("chitchat", loader))
loader.exec_module(chitchat)

SESSION = "session-a"
OTHER = "session-b"
# tmux_focus answers in tmux 3.7b's shape: pane_active and window_active, then
# client_flags for each attached client.
FOCUSED = "11\nattached,focused,UTF-8\n"
OTHER_PANE = "01\nattached,focused,UTF-8\n"
OTHER_WINDOW = "10\nattached,focused,UTF-8\n"
OTHER_APP = "11\nattached,UTF-8\n"
DETACHED = "11\n"
VERBOSE = "-v" in sys.argv


class FakeModel:
    def prepare_conditionals(self, path):
        pass


class FocusTest(unittest.TestCase):
    def setUp(self):
        for d in (chitchat.PANES, chitchat.QUEUES, chitchat.PIDS, chitchat.LOGS, chitchat.WORKERS, chitchat.HELD):
            d.mkdir(parents=True, exist_ok=True)
        for f in [*chitchat.PANES.iterdir(), *chitchat.HELD.iterdir(), chitchat.DUCKED]:
            f.unlink(missing_ok=True)
        self.tmux = FOCUSED
        self.calls = []
        self.log = []
        self.waits = 0
        self.on_wait = lambda waits: None
        self.on_say = lambda text: None
        self.volume = 80
        patches = [
            mock.patch.object(chitchat, "tmux_focus", self.fake_tmux),
            mock.patch.object(chitchat, "spotify_volume", self.fake_spotify),
            mock.patch.object(chitchat, "load", FakeModel),
            mock.patch.object(chitchat, "speak", self.fake_speak),
            mock.patch.object(chitchat.time, "sleep", self.fake_sleep),
            mock.patch.object(chitchat.os, "dup2"),
            mock.patch.object(chitchat.subprocess, "Popen"),
            # Workers run in this process, so a pidfile naming it is a live worker.
            mock.patch.object(chitchat, "is_chitchat", lambda pid: pid == os.getpid()),
            mock.patch.dict(os.environ, {"TMUX": "/tmp/tmux-test/default,1,0", "TMUX_PANE": "%7"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        if VERBOSE:
            print(f"\n  {self._testMethodName}:", *(f"    {line}" for line in self.log), sep="\n", file=sys.stderr)

    def fake_tmux(self, pane, socket):
        self.calls.append((pane, socket))
        return self.tmux

    def fake_spotify(self, level=None):
        if level is not None:
            self.volume = level
            self.log.append(f"spotify volume {level}")
        return self.volume

    def fake_speak(self, model, text, session):
        chitchat.duck()  # as play() does before the first clip
        self.log.append(f"{session} says {text!r}")
        self.on_say(text)

    def fake_sleep(self, seconds):
        self.waits += 1
        self.log.append(f"{SESSION} waits")
        self.assertLess(self.waits, 10, "worker never resumed")
        self.on_wait(self.waits)

    def focus(self, state):
        self.tmux = state
        self.log.append(f"tmux: {state.splitlines()}")

    def reply(self, md, tagged=False, session=SESSION):
        chitchat.remember_pane(session)
        chitchat.enqueue(session, *chitchat.speakable(md, tagged))

    def start_turn(self, tagged=False):
        """Turn speech on and start a transcript, as the prompt hook would."""
        for d in (chitchat.ENABLED, chitchat.OFFSETS):
            d.mkdir(parents=True, exist_ok=True)
        (chitchat.ENABLED / SESSION).write_text("tagged" if tagged else "")
        (chitchat.OFFSETS / SESSION).unlink(missing_ok=True)
        self.transcript = Path(HOME) / f"{self._testMethodName}.jsonl"
        self.transcript.write_text("")
        chitchat.remember_pane(SESSION)
        chitchat.skip_to_end(SESSION, str(self.transcript))

    def write(self, text):
        """Add an assistant message to the transcript."""
        entry = {"type": "assistant", "message": {"id": text, "content": [{"type": "text", "text": text}]}}
        with self.transcript.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def tool_call(self):
        self.log.append("PreToolUse hook")
        chitchat.progress({"session_id": SESSION, "transcript_path": str(self.transcript)})

    def stop_hook(self, reply):
        self.log.append("Stop hook")
        event = {"session_id": SESSION, "transcript_path": str(self.transcript), "last_assistant_message": reply}
        chitchat.hook(event)

    def said(self):
        return [line for line in self.log if " says " in line]

    def test_reads_client_flags(self):
        self.assertTrue(chitchat.focused_in(FOCUSED))
        self.assertTrue(chitchat.focused_in("11\nattached,UTF-8\nattached,focused,UTF-8\n"))
        self.assertTrue(chitchat.focused_in("11\nfocused\n"))
        for out in (OTHER_PANE, OTHER_WINDOW, OTHER_APP, DETACHED, "", "11\n\n", "11\nattached,unfocused,UTF-8\n"):
            with self.subTest(out=out):
                self.assertFalse(chitchat.focused_in(out))

    def test_focused_speaks_whole_reply(self):
        self.reply("Fixed the parser. <announce>Merged the fix.</announce> Tests pass.")
        chitchat.worker(SESSION)
        self.assertEqual(self.said(), [f"{SESSION} says 'Fixed the parser. Merged the fix. Tests pass.'"])
        self.assertEqual(self.calls, [("%7", "/tmp/tmux-test/default")])

    def test_unfocused_holds_then_resumes(self):
        for state in (OTHER_PANE, OTHER_WINDOW, OTHER_APP, DETACHED):
            with self.subTest(tmux=state):
                self.log.clear()
                self.waits = 0
                self.focus(state)
                self.reply("Fixed the parser.")
                self.on_wait = lambda waits: waits == 2 and self.focus(FOCUSED)
                chitchat.worker(SESSION)
                self.assertEqual(self.log[1:], [
                    f"{SESSION} waits",
                    f"{SESSION} waits",
                    "tmux: ['11', 'attached,focused,UTF-8']",
                    "spotify volume 30",
                    f"{SESSION} says 'Fixed the parser.'",
                    "spotify volume 80",
                ])
                self.assertIsNone(chitchat.next_item(chitchat.QUEUES / SESSION))

    def test_not_in_tmux_speaks(self):
        del os.environ["TMUX_PANE"]
        self.tmux = OTHER_PANE
        self.reply("Fixed the parser.")
        chitchat.worker(SESSION)
        self.assertEqual(self.said(), [f"{SESSION} says 'Fixed the parser.'"])
        self.assertEqual(self.calls, [])

    def test_tmux_failure_speaks(self):
        self.tmux = None
        self.reply("Fixed the parser.")
        chitchat.worker(SESSION)
        self.assertEqual(self.said(), [f"{SESSION} says 'Fixed the parser.'"])

    def test_switch_away_mid_queue_holds_the_rest_in_order(self):
        for md in ("First step done.", "Second step done.", "Third step done."):
            self.reply(md)
        self.on_say = lambda text: text == "First step done." and self.focus(OTHER_WINDOW)
        self.on_wait = lambda waits: self.focus(FOCUSED)
        chitchat.worker(SESSION)
        self.assertEqual([line for line in self.log if "spotify" not in line], [
            f"{SESSION} says 'First step done.'",
            "tmux: ['10', 'attached,focused,UTF-8']",
            f"{SESSION} waits",
            "tmux: ['11', 'attached,focused,UTF-8']",
            f"{SESSION} says 'Second step done.'",
            f"{SESSION} says 'Third step done.'",
        ])

    def test_announcements_play_while_the_rest_is_held(self):
        self.focus(OTHER_APP)
        self.reply("Fixed the parser. <announce>PR 12 merged.</announce> Tests pass.")
        self.reply("<announce>The build failed.</announce>", tagged=True)
        self.reply("<speak>Ordinary tagged update.</speak>", tagged=True)

        def on_wait(waits):
            if waits == 1:
                self.reply("Retrying. <announce>Waiting on your decision.</announce>")
            if waits == 2:
                self.focus(FOCUSED)

        self.on_wait = on_wait
        chitchat.worker(SESSION)
        self.assertEqual([line for line in self.log if "spotify" not in line], [
            "tmux: ['11', 'attached,UTF-8']",
            f"{SESSION} says 'PR 12 merged.'",
            f"{SESSION} says 'The build failed.'",
            f"{SESSION} waits",
            f"{SESSION} says 'Waiting on your decision.'",
            f"{SESSION} waits",
            "tmux: ['11', 'attached,focused,UTF-8']",
            f"{SESSION} says 'Fixed the parser. Tests pass.'",
            f"{SESSION} says 'Ordinary tagged update.'",
            f"{SESSION} says 'Retrying.'",
        ])

    def test_another_session_speaks_while_one_waits(self):
        self.focus(OTHER_PANE)
        self.reply("Held reply.")

        def on_wait(waits):
            # The waiting session has given the music back and counts as silent.
            self.assertFalse(chitchat.speaking())
            self.assertFalse(chitchat.DUCKED.exists())
            if waits == 1:
                with mock.patch.dict(os.environ, {"TMUX_PANE": ""}):
                    self.reply("Other session reply.", session=OTHER)
                chitchat.worker(OTHER)
            if waits == 2:
                self.focus(FOCUSED)

        self.on_wait = on_wait
        chitchat.worker(SESSION)
        self.assertEqual(self.log[1:], [
            f"{SESSION} waits",
            "spotify volume 30",
            f"{OTHER} says 'Other session reply.'",
            "spotify volume 80",
            f"{SESSION} waits",
            "tmux: ['11', 'attached,focused,UTF-8']",
            "spotify volume 30",
            f"{SESSION} says 'Held reply.'",
            "spotify volume 80",
        ])

    def test_new_prompt_clears_held_speech(self):
        self.focus(OTHER_PANE)
        self.reply("Held reply.")
        self.reply("Another held reply.")
        # A typed prompt calls stop(), which drops the queue and kills the worker;
        # here the worker is this process, so stop() leaves it to find the queue empty.
        self.on_wait = lambda waits: (chitchat.stop(SESSION), self.log.append("new prompt: stop"))
        chitchat.worker(SESSION)
        self.assertEqual(self.log[1:], [f"{SESSION} waits", "new prompt: stop"])
        self.assertIsNone(chitchat.next_item(chitchat.QUEUES / SESSION))
        self.assertFalse((chitchat.HELD / SESSION).exists())

    def test_pre_tool_text_speaks_while_unfocused_and_is_not_repeated(self):
        self.focus(OTHER_APP)
        self.start_turn()
        self.write("Reading the config.")
        self.tool_call()
        self.write("Running the tests.")
        # The last step reaches the Stop hook unspoken, and is pre-tool text too.
        self.write("All twelve tests pass.")
        self.stop_hook("All twelve tests pass.")
        self.on_wait = lambda waits: self.focus(FOCUSED)
        chitchat.worker(SESSION)
        self.tool_call()  # a later tool call finds nothing new to say
        chitchat.worker(SESSION)
        self.assertEqual([line for line in self.log if "spotify" not in line], [
            "tmux: ['11', 'attached,UTF-8']",
            "PreToolUse hook",
            "Stop hook",
            f"{SESSION} says 'Reading the config.'",
            f"{SESSION} says 'Running the tests.'",
            f"{SESSION} waits",
            "tmux: ['11', 'attached,focused,UTF-8']",
            f"{SESSION} says 'All twelve tests pass.'",
            "PreToolUse hook",
        ])

    def test_pre_tool_text_focused_speaks_once(self):
        self.start_turn()
        self.write("Reading the config.")
        self.tool_call()
        self.write("Done.")
        self.stop_hook("Done.")
        chitchat.worker(SESSION)
        self.assertEqual(self.said(), [f"{SESSION} says 'Reading the config.'", f"{SESSION} says 'Done.'"])

    def test_pre_tool_text_in_tagged_mode_is_still_gated(self):
        self.focus(OTHER_PANE)
        self.start_turn(tagged=True)
        self.write("Looking around. <speak>Halfway there.</speak>")
        self.tool_call()
        self.write("Untagged step.")
        self.tool_call()
        self.write("<announce>Need your decision.</announce>")
        self.tool_call()
        self.on_wait = lambda waits: self.focus(FOCUSED)
        chitchat.worker(SESSION)
        self.assertEqual(self.said(), [
            f"{SESSION} says 'Need your decision.'",
            f"{SESSION} says 'Halfway there.'",
        ])

    def test_announcement_spoken_once_in_tagged_mode(self):
        self.reply("<speak>Step done.</speak> Details. <announce>Waiting on you.</announce>", tagged=True)
        chitchat.worker(SESSION)
        self.assertEqual(self.said(), [f"{SESSION} says 'Step done.\\nWaiting on you.'"])

    def test_gate_off(self):
        self.tmux = OTHER_PANE
        self.reply("Fixed the parser.")
        with mock.patch.object(chitchat, "FOCUS_GATE", False):
            chitchat.worker(SESSION)
        self.assertEqual(self.said(), [f"{SESSION} says 'Fixed the parser.'"])


if __name__ == "__main__":
    unittest.main()
