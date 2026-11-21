"""Speech server tests, with tmux replaced by a stub of tmux_pane and no model loaded.

The scheduler runs for real, with generation and playback, Spotify, and its wait
replaced, and each test checks the log of what it said and when it waited.
ServerTest runs real servers on threads, listening on the socket, to cover
starting, idling out, and replacing an older server.
Run with: python3 scripts/chitchat_test.py -v
"""

import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

HOME = tempfile.mkdtemp(prefix="chitchat-test-")
os.environ["XDG_STATE_HOME"] = HOME
os.environ["XDG_DATA_HOME"] = HOME
for var in ("CHITCHAT_FOCUS", "CHITCHAT_DUCK", "CHITCHAT_VOICE", "CHITCHAT_IDLE_SECONDS"):
    os.environ.pop(var, None)

SCRIPT = Path(__file__).with_name("chitchat")
loader = importlib.machinery.SourceFileLoader("chitchat", str(SCRIPT))
chitchat = importlib.util.module_from_spec(importlib.util.spec_from_loader("chitchat", loader))
loader.exec_module(chitchat)

SESSION = "session-a"
OTHER = "session-b"
# Focus states as tmux 3.7b reports them: pane_active and window_active, then
# client_flags for each attached client. The stub adds a tab and the window name
# to the first line, as tmux_pane's format asks.
FOCUSED = "11\nattached,focused,UTF-8\n"
OTHER_PANE = "01\nattached,focused,UTF-8\n"
OTHER_WINDOW = "10\nattached,focused,UTF-8\n"
OTHER_APP = "11\nattached,UTF-8\n"
DETACHED = "11\n"
VERBOSE = "-v" in sys.argv


class FakeModel:
    def __init__(self):
        self.prepared = []
        self._conds = None

    def prepare_conditionals(self, path):
        self.prepared.append(Path(path).stem)
        self._conds = Path(path).stem

    def generate(self, text):
        for word in text.split():
            yield types.SimpleNamespace(audio=word, sample_rate=24000)


class Base(unittest.TestCase):
    """Fresh state, and tmux, Spotify, and the model replaced."""

    def setUp(self):
        for d in (chitchat.PANES, chitchat.NAMES, chitchat.CHOSEN, chitchat.QUEUES, chitchat.LOGS, chitchat.VOICES):
            d.mkdir(parents=True, exist_ok=True)
        for f in [*chitchat.PANES.iterdir(), *chitchat.NAMES.iterdir(), *chitchat.CHOSEN.iterdir(), chitchat.DUCKED]:
            f.unlink(missing_ok=True)
        chitchat.drop(None)
        for v in ("default", "narrator"):
            (chitchat.VOICES / f"{v}.wav").touch()
        self.tmux = FOCUSED
        # A pane's own focus state and window, where a test gives one; self.tmux and
        # self.window otherwise.
        self.panes = {}
        self.windows = {}
        self.window = "chitchat"
        self.calls = []
        self.log = []
        self.volume = 80
        patches = [
            mock.patch.object(chitchat, "tmux_pane", self.fake_tmux),
            mock.patch.object(chitchat, "spotify_volume", self.fake_spotify),
            mock.patch.object(chitchat, "load", FakeModel),
            mock.patch.object(chitchat, "launch", lambda: self.fail("started a server")),
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
        state = self.panes.get(pane, self.tmux)
        if state is None:
            return None
        active, *clients = state.splitlines()
        return "\n".join([f"{active}\t{self.windows.get(pane, self.window)}", *clients]) + "\n"

    def fake_spotify(self, level=None):
        if level is not None:
            self.volume = level
            self.log.append(f"spotify volume {level}")
        return self.volume

    def focus(self, state):
        self.tmux = state
        self.log.append(f"tmux: {state.splitlines()}")

    def reply(self, md, tagged=False, session=SESSION, pane="%7"):
        with mock.patch.dict(os.environ, {"TMUX_PANE": pane}):
            chitchat.remember_pane(session)
        chitchat.enqueue(session, *chitchat.speakable(md, tagged))


class SchedulerTest(Base):
    """One server, driven on the test's thread, with requests handed straight to it."""

    def setUp(self):
        super().setUp()
        self.server = chitchat.Server("1.0.0")
        self.server.wait = self.fake_wait
        self.waits = 0
        self.on_wait = lambda waits: None
        self.on_say = lambda text: None
        self.voices_used = []
        patches = [
            mock.patch.object(chitchat.Server, "speak", self.fake_speak),
            mock.patch.object(chitchat, "send", lambda request: self.server.handle({**request, "version": "1.0.0"})),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fake_speak(self, text, session):
        chitchat.duck()  # as play() does before the first clip
        self.voices_used.append(self.server.model._conds)
        self.log.append(f"{session} says {text!r}")
        self.on_say(text)

    def fake_wait(self, seconds):
        """Waiting with nothing queued would wait for a ring, so the test ends there."""
        if seconds is None:
            return False
        self.waits += 1
        self.log.append(f"{SESSION} waits")
        self.assertLess(self.waits, 10, "held speech never resumed")
        self.on_wait(self.waits)
        return True

    def run_server(self):
        self.server.schedule()

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

    def tool_call(self, text):
        """A step that writes text, then calls a tool: the hooks module hands the text
        to pretool as the call starts, and it reaches the transcript once the call has run."""
        self.log.append("tool call starts")
        chitchat.pretool(SESSION, [text])
        self.write(text)

    def stop_hook(self, reply):
        self.log.append("Stop hook")
        event = {"session_id": SESSION, "transcript_path": str(self.transcript), "last_assistant_message": reply}
        chitchat.hook(event)

    def said(self):
        return [line for line in self.log if " says " in line]

    def unspotified(self):
        return [line for line in self.log if "spotify" not in line]

    def test_reads_client_flags(self):
        self.assertTrue(chitchat.read_pane(FOCUSED).focused)
        self.assertTrue(chitchat.read_pane("11\nattached,UTF-8\nattached,focused,UTF-8\n").focused)
        self.assertTrue(chitchat.read_pane("11\nfocused\n").focused)
        for out in (OTHER_PANE, OTHER_WINDOW, OTHER_APP, DETACHED, "", "11\n\n", "11\nattached,unfocused,UTF-8\n"):
            with self.subTest(out=out):
                self.assertFalse(chitchat.read_pane(out).focused)

    def test_reads_window(self):
        # A detached session's answer, as tmux 3.7b gives it for a background window.
        self.assertEqual(
            chitchat.read_pane("10\tfm-buckets-search-fix\n"),
            chitchat.Pane(False, "fm-buckets-search-fix"),
        )
        self.assertEqual(chitchat.read_pane("11\tmy\twindow\n").window, "my\twindow")

    def test_name_comes_from_the_window(self):
        self.assertEqual(chitchat.name(SESSION, "fm-buckets-search-fix"), "buckets search fix")
        self.assertEqual(chitchat.name(SESSION, "chitchat"), "chitchat")
        self.assertEqual(chitchat.name(SESSION, ""), "")

    def test_focused_speaks_whole_reply(self):
        self.reply("Fixed the parser. <announce>Merged the fix.</announce> Tests pass.")
        self.run_server()
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
                self.run_server()
                self.assertEqual(self.log[1:], [
                    f"{SESSION} waits",
                    f"{SESSION} waits",
                    "tmux: ['11', 'attached,focused,UTF-8']",
                    "spotify volume 30",
                    f"{SESSION} says 'Fixed the parser.'",
                    "spotify volume 80",
                ])
                self.assertEqual(chitchat.queued(), [])

    def test_not_in_tmux_speaks(self):
        self.tmux = OTHER_PANE
        self.reply("Fixed the parser.", pane="")
        self.run_server()
        self.assertEqual(self.said(), [f"{SESSION} says 'Fixed the parser.'"])
        self.assertEqual(self.calls, [])

    def test_no_tmux_announcement_has_no_name(self):
        for case in ("not in tmux", "tmux fails"):
            with self.subTest(case=case):
                self.log.clear()
                if case == "tmux fails":
                    self.tmux = None
                self.reply("<announce>The pull request merged.</announce>", pane="" if case == "not in tmux" else "%7")
                self.run_server()
                self.assertEqual(self.unspotified(), [f"{SESSION} says 'The pull request merged.'"])

    def test_tmux_failure_speaks(self):
        self.tmux = None
        self.reply("Fixed the parser.")
        self.run_server()
        self.assertEqual(self.said(), [f"{SESSION} says 'Fixed the parser.'"])

    def test_switch_away_mid_queue_holds_the_rest_in_order(self):
        for md in ("First step done.", "Second step done.", "Third step done."):
            self.reply(md)
        self.on_say = lambda text: text == "First step done." and self.focus(OTHER_WINDOW)
        self.on_wait = lambda waits: self.focus(FOCUSED)
        self.run_server()
        self.assertEqual(self.unspotified(), [
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
        self.run_server()
        self.assertEqual(self.unspotified(), [
            "tmux: ['11', 'attached,UTF-8']",
            f"{SESSION} says 'chitchat.\\nPR 12 merged.'",
            f"{SESSION} says 'chitchat.\\nThe build failed.'",
            f"{SESSION} waits",
            f"{SESSION} says 'chitchat.\\nWaiting on your decision.'",
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
            # The waiting session has given the music back.
            self.assertFalse(chitchat.DUCKED.exists())
            if waits == 1:
                self.reply("Other session reply.", session=OTHER, pane="")
            if waits == 2:
                self.focus(FOCUSED)

        self.on_wait = on_wait
        self.run_server()
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

    def test_unfocused_announcements_go_first_then_oldest_focused(self):
        """Across sessions: announcements from sessions not focused jump the queue,
        then focused sessions take turns in the order they queued."""
        self.panes["%8"] = OTHER_WINDOW
        self.windows["%8"] = "fm-deploy"
        self.reply("First from A.")
        self.reply("Second from A.")
        self.reply("Checked CI. <announce>Deploy finished.</announce>", session=OTHER, pane="%8")
        self.reply("Third from A.")
        self.reply("From the manual session.", session="manual", pane="")
        self.reply("Fourth from A.")
        self.on_wait = lambda waits: self.panes.update({"%7": OTHER_WINDOW, "%8": FOCUSED})
        self.run_server()
        self.assertEqual(self.said(), [
            f"{OTHER} says 'deploy.\\nDeploy finished.'",
            f"{SESSION} says 'First from A.'",
            f"{SESSION} says 'Second from A.'",
            f"{SESSION} says 'Third from A.'",
            "manual says 'From the manual session.'",
            f"{SESSION} says 'Fourth from A.'",
            f"{OTHER} says 'Checked CI.'",
        ])

    def test_announcement_from_another_session_cuts_in_between_items(self):
        self.panes["%8"] = OTHER_APP
        self.reply("First from A.")
        self.reply("Second from A.")

        def on_say(text):
            if text == "First from A.":
                self.reply("<announce>Build failed.</announce>", session=OTHER, pane="%8")

        self.on_say = on_say
        self.run_server()
        self.assertEqual(self.said(), [
            f"{SESSION} says 'First from A.'",
            f"{OTHER} says 'chitchat.\\nBuild failed.'",
            f"{SESSION} says 'Second from A.'",
        ])

    def test_picks_up_queues_left_on_disk(self):
        """A server that crashed leaves its queues; the next speaks them, and an
        announcement the crashed one said is not said again."""
        self.focus(OTHER_APP)
        self.reply("Fixed the parser. <announce>PR 12 merged.</announce> Tests pass.")
        self.reply("Second reply.", session=OTHER, pane="")
        crashed = chitchat.Server("1.0.0")
        # The crashed server said the announcement, then died before anything else.
        with mock.patch.object(chitchat.Server, "say", lambda server, session, text: None):
            crashed.step()
        self.focus(FOCUSED)
        self.run_server()
        self.assertEqual(self.said(), [
            f"{SESSION} says 'Fixed the parser. Tests pass.'",
            f"{OTHER} says 'Second reply.'",
        ])

    def test_new_prompt_clears_held_speech(self):
        self.focus(OTHER_PANE)
        self.reply("Held reply.")
        self.reply("Another held reply.")
        self.on_wait = lambda waits: (chitchat.stop(SESSION), self.log.append("new prompt: stop"))
        self.run_server()
        self.assertEqual(self.log[1:], [f"{SESSION} waits", "new prompt: stop"])
        self.assertEqual(chitchat.queued(), [])

    def test_stop_cuts_its_session_and_leaves_the_others(self):
        self.reply("First from A.")
        self.reply("Second from A.")
        self.reply("From B.", session=OTHER, pane="")

        def on_say(text):
            if text == "First from A.":
                chitchat.stop(SESSION)
                self.assertTrue(self.server.cancel.is_set())

        self.on_say = on_say
        self.run_server()
        self.assertEqual(self.said(), [f"{SESSION} says 'First from A.'", f"{OTHER} says 'From B.'"])

    def test_stop_of_another_session_does_not_cut_this_one(self):
        self.reply("From A.")
        self.reply("From B.", session=OTHER, pane="")
        self.on_say = lambda text: text == "From A." and chitchat.stop(OTHER)
        self.run_server()
        self.assertFalse(self.server.cancel.is_set())
        self.assertEqual(self.said(), [f"{SESSION} says 'From A.'"])

    def test_stop_outside_a_session_stops_all(self):
        self.reply("From A.")
        self.reply("Second from A.")
        self.reply("From B.", session=OTHER, pane="")
        self.on_say = lambda text: chitchat.stop(None)
        self.run_server()
        self.assertTrue(self.server.cancel.is_set())
        self.assertEqual(self.said(), [f"{SESSION} says 'From A.'"])

    def test_stop_with_no_server_drops_the_queue(self):
        self.reply("Held.")
        with mock.patch.object(chitchat, "send", lambda request: None):
            chitchat.stop(SESSION)
        self.assertEqual(chitchat.queued(), [])

    def test_each_voice_is_prepared_once(self):
        (chitchat.CHOSEN / OTHER).write_text("narrator")
        self.reply("From A.")
        self.reply("From B.", session=OTHER, pane="")
        self.reply("A again.")
        self.reply("B again.", session=OTHER, pane="")
        self.run_server()
        self.assertEqual(self.voices_used, ["default", "narrator", "default", "narrator"])
        self.assertEqual(self.server.model.prepared, ["default", "narrator"])
        # A sample that changes is prepared again.
        voice = chitchat.VOICES / "default.wav"
        os.utime(voice, ns=(voice.stat().st_mtime_ns + 10**9,) * 2)
        self.reply("A once more.")
        self.run_server()
        self.assertEqual(self.server.model.prepared, ["default", "narrator", "default"])

    def test_missing_voice_falls_back_to_the_default(self):
        (chitchat.CHOSEN / SESSION).write_text("nobody")
        self.reply("Still spoken.")
        with mock.patch.object(chitchat, "warn") as warn:
            self.run_server()
        self.assertEqual(self.said(), [f"{SESSION} says 'Still spoken.'"])
        self.assertEqual(self.voices_used, ["default"])
        self.assertIn("no voice 'nobody'", warn.call_args.args[0])
        self.assertIn("default voice", warn.call_args.args[0])

    def test_missing_default_voice_skips_the_message_and_keeps_serving(self):
        (chitchat.VOICES / "default.wav").unlink()
        (chitchat.CHOSEN / OTHER).write_text("narrator")
        self.reply("Lost.")
        self.reply("From B.", session=OTHER, pane="")
        (chitchat.CHOSEN / "session-c").write_text("nobody")
        self.reply("Lost too.", session="session-c", pane="")
        with mock.patch.object(chitchat, "warn") as warn:
            self.run_server()
        self.assertEqual(self.said(), [f"{OTHER} says 'From B.'"])
        self.assertEqual(chitchat.queued(), [])
        self.assertEqual([c.args[0].split(";")[0] for c in warn.call_args_list], [
            "no voice 'default' in " + str(chitchat.VOICES),
            "no voice 'nobody' or the default, 'default' in " + str(chitchat.VOICES),
        ])
        # Speech goes on once the sample is back.
        (chitchat.VOICES / "default.wav").touch()
        self.reply("Back.")
        self.run_server()
        self.assertEqual(self.said()[-1], f"{SESSION} says 'Back.'")

    def test_pre_tool_text_speaks_while_unfocused_and_is_not_repeated(self):
        self.focus(OTHER_APP)
        self.start_turn()
        self.tool_call("Reading the config.")
        self.tool_call("Running the tests.")
        self.write("All twelve tests pass.")
        self.stop_hook("All twelve tests pass.")
        self.on_wait = lambda waits: self.focus(FOCUSED)
        self.run_server()
        self.assertEqual(self.unspotified(), [
            "tmux: ['11', 'attached,UTF-8']",
            "tool call starts",
            "tool call starts",
            "Stop hook",
            f"{SESSION} says 'chitchat.\\nReading the config.'",
            f"{SESSION} says 'chitchat.\\nRunning the tests.'",
            f"{SESSION} waits",
            "tmux: ['11', 'attached,focused,UTF-8']",
            f"{SESSION} says 'All twelve tests pass.'",
        ])

    def test_pre_tool_text_focused_speaks_once(self):
        self.start_turn()
        self.tool_call("Reading the config.")
        self.write("Done.")
        self.stop_hook("Done.")
        self.run_server()
        self.assertEqual(self.said(), [f"{SESSION} says 'Reading the config.'", f"{SESSION} says 'Done.'"])

    def test_pre_tool_text_is_not_repeated_when_the_last_message_has_none(self):
        self.start_turn()
        self.tool_call("Reading the config.")
        # With no text in the last message, the Stop hook falls back to the last that had some.
        self.stop_hook("")
        self.run_server()
        self.assertEqual(self.said(), [f"{SESSION} says 'Reading the config.'"])

    def test_text_the_module_missed_speaks_at_the_end(self):
        self.start_turn()
        self.write("Reading the config.")
        self.write("Done.")
        self.stop_hook("Done.")
        self.run_server()
        self.assertEqual(self.said(), [f"{SESSION} says 'Reading the config.'", f"{SESSION} says 'Done.'"])

    def test_pre_tool_text_in_tagged_mode_is_still_gated(self):
        self.focus(OTHER_PANE)
        self.start_turn(tagged=True)
        self.tool_call("Looking around. <speak>Halfway there.</speak>")
        self.tool_call("Untagged step.")
        self.tool_call("<announce>Need your decision.</announce>")
        self.on_wait = lambda waits: self.focus(FOCUSED)
        self.run_server()
        self.assertEqual(self.said(), [
            f"{SESSION} says 'chitchat.\\nNeed your decision.'",
            f"{SESSION} says 'Halfway there.'",
        ])

    def test_announcement_spoken_once_in_tagged_mode(self):
        self.reply("<speak>Step done.</speak> Details. <announce>Waiting on you.</announce>", tagged=True)
        self.run_server()
        self.assertEqual(self.said(), [f"{SESSION} says 'Step done.\\nWaiting on you.'"])

    def test_unfocused_announcement_says_the_name(self):
        self.window = "fm-buckets-search-fix"
        self.focus(OTHER_WINDOW)
        self.reply("Checked CI. <announce>The pull request merged.</announce>")
        self.on_wait = lambda waits: self.focus(FOCUSED)
        self.run_server()
        self.assertEqual(self.unspotified(), [
            "tmux: ['10', 'attached,focused,UTF-8']",
            f"{SESSION} says 'buckets search fix.\\nThe pull request merged.'",
            f"{SESSION} waits",
            "tmux: ['11', 'attached,focused,UTF-8']",
            f"{SESSION} says 'Checked CI.'",
        ])

    def test_focused_announcement_has_no_name(self):
        self.window = "fm-buckets-search-fix"
        self.reply("<announce>The pull request merged.</announce>")
        self.run_server()
        self.assertEqual(self.unspotified(), [f"{SESSION} says 'The pull request merged.'"])

    def test_unfocused_pre_tool_text_says_the_name(self):
        self.window = "fm-buckets-search-fix"
        self.focus(OTHER_APP)
        self.start_turn()
        self.tool_call("Running the tests.")
        self.on_wait = lambda waits: self.focus(FOCUSED)
        self.run_server()
        self.assertEqual(self.said(), [f"{SESSION} says 'buckets search fix.\\nRunning the tests.'"])

    def test_chosen_name_overrides_the_window(self):
        self.window = "fm-buckets-search-fix"
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": SESSION}), mock.patch("builtins.print"):
            chitchat.choose_name("buckets")
            self.on_wait = lambda waits: self.focus(FOCUSED)
            self.focus(OTHER_PANE)
            self.reply("<announce>Done.</announce>")
            self.run_server()
            self.assertEqual(self.said(), [f"{SESSION} says 'buckets.\\nDone.'"])
            self.log.clear()
            chitchat.choose_name("--clear")
            self.focus(OTHER_PANE)
            self.reply("<announce>Done again.</announce>")
            self.run_server()
            self.assertEqual(self.said(), [f"{SESSION} says 'buckets search fix.\\nDone again.'"])

    def test_name_command_shows_the_name(self):
        self.window = "fm-buckets-search-fix"
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": SESSION}), \
                mock.patch("builtins.print") as printed:
            chitchat.choose_name(None)
            chitchat.choose_name("Buckets")
            chitchat.choose_name("--clear")
            del os.environ["TMUX_PANE"]
            chitchat.choose_name(None)
        self.assertEqual([c.args[0] for c in printed.call_args_list], [
            "name buckets search fix",
            "name Buckets",
            "name buckets search fix",
            "no name; outside tmux, nothing is said first",
        ])

    def test_gate_off(self):
        self.tmux = OTHER_PANE
        self.reply("Fixed the parser.")
        with mock.patch.object(chitchat, "FOCUS_GATE", False):
            self.run_server()
        self.assertEqual(self.said(), [f"{SESSION} says 'Fixed the parser.'"])

    def test_newer_client_closes_the_server_after_the_current_item(self):
        self.reply("First.")
        self.reply("Second.")

        def on_say(text):
            reply = self.server.handle({"op": "ring", "version": "1.0.1"})
            self.assertTrue(reply["restart"])

        self.on_say = on_say
        self.run_server()
        self.assertEqual(self.said(), [f"{SESSION} says 'First.'"])
        self.assertEqual(len(chitchat.queued()), 1)

    def test_older_or_same_client_keeps_the_server(self):
        for version in ("1.0.0", "0.9.9", "0.10.0"):
            with self.subTest(version=version):
                self.assertFalse(self.server.handle({"op": "ring", "version": version})["restart"])
        self.assertFalse(self.server.closing)
        self.assertTrue(chitchat.newer("0.10.0", "0.9.9"))

    def test_version_comes_from_the_plugin_manifest(self):
        manifest = json.loads((SCRIPT.parent.parent / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(chitchat.VERSION, manifest["version"])
        self.assertEqual(chitchat.Server().version, manifest["version"])


class PlaybackTest(Base):
    """speak() and play() for real, with soundfile and afplay replaced."""

    def test_stop_cuts_the_clip_playing_and_the_rest(self):
        server = chitchat.Server("1.0.0")
        server.wait = lambda seconds: False
        played, killed = [], []
        test = self

        class FakeAfplay:
            def __init__(self, cmd):
                self.clip = Path(cmd[-1]).read_text()
                played.append(self.clip)

            def wait(self):
                if self.clip == "One":
                    # The prompt hook's stop arrives while the first clip plays.
                    server.handle({"op": "stop", "session": SESSION, "version": "1.0.0"})
                    test.assertEqual(killed, ["One"])

            def terminate(self):
                killed.append(self.clip)

        soundfile = types.SimpleNamespace(write=lambda path, audio, rate: Path(path).write_text(audio))
        with mock.patch.dict(sys.modules, {"soundfile": soundfile}), \
                mock.patch.object(chitchat.subprocess, "Popen", FakeAfplay), \
                mock.patch.object(chitchat, "send", lambda request: server.handle({**request, "version": "1.0.0"})):
            self.reply("One two three.\nFour five.")
            # The stop drops the next item too, so only the first clip plays.
            self.reply("Next item.")
            server.schedule()
        self.assertEqual(played, ["One"])
        self.assertEqual(killed, ["One"])
        self.assertEqual(chitchat.queued(), [])
        self.assertEqual(self.log, ["spotify volume 30", "spotify volume 80"])


class ServerTest(Base):
    """Real servers on threads, listening on the socket."""

    def setUp(self):
        super().setUp()
        self.spoken = []
        self.servers = []
        self.hold = threading.Event()
        self.hold.set()
        test = self

        def fake_speak(server, text, session):
            test.spoken.append((server.version, text))
            test.assertTrue(test.hold.wait(5), "held speech was never released")

        self.launches = 0
        patches = [
            mock.patch.object(chitchat.Server, "speak", fake_speak),
            mock.patch.object(chitchat, "launch", self.fake_launch),
            mock.patch.object(chitchat, "POLL_SECONDS", 0.02),
            mock.patch.object(chitchat, "IDLE_CHECK_SECONDS", 0.02),
            mock.patch.object(chitchat, "IDLE_SECONDS", 60),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.close_all)

    def start(self, version=None):
        server = chitchat.Server(version or chitchat.VERSION)
        self.assertTrue(server.listen())
        threads = [threading.Thread(target=server.run), threading.Thread(target=server.accept)]
        for t in threads:
            t.start()
        self.servers.append((server, threads))
        return server, threads

    def fake_launch(self):
        self.launches += 1
        self.start()

    def close_all(self):
        self.hold.set()
        for server, threads in self.servers:
            server.closing = True
            server.wake.set()
            for t in threads:
                t.join(5)
        chitchat.SOCKET.unlink(missing_ok=True)

    def until(self, check, seconds=3):
        deadline = time.monotonic() + seconds
        while not check():
            self.assertLess(time.monotonic(), deadline, "timed out")
            time.sleep(0.01)

    def test_first_ring_starts_one_server(self):
        threads = [threading.Thread(target=chitchat.enqueue, args=(f"s{i}", f"Reply {i}.")) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.until(lambda: len(self.spoken) == 4)
        self.assertEqual(self.launches, 1)
        self.assertEqual(sorted(text for _, text in self.spoken), [f"Reply {i}." for i in range(4)])

    def test_stop_with_no_server_starts_none(self):
        chitchat.stop(SESSION)
        chitchat.stop(None)
        self.assertEqual(self.launches, 0)

    def test_exits_when_idle_with_nothing_queued(self):
        with mock.patch.object(chitchat, "IDLE_SECONDS", 0.2):
            self.focus(OTHER_PANE)
            self.reply("Held until focused.")
            server, threads = self.servers[0]
            time.sleep(0.4)
            # Held speech keeps the server, so it can play once the session is focused.
            self.assertTrue(all(t.is_alive() for t in threads))
            chitchat.stop(SESSION)
            for t in threads:
                t.join(3)
            self.assertFalse(any(t.is_alive() for t in threads))
        self.assertFalse(chitchat.SOCKET.exists())
        self.assertIsNone(chitchat.send({"op": "ring"}))
        # The next message starts a new one.
        self.focus(FOCUSED)
        self.reply("Back again.")
        self.until(lambda: len(self.spoken) == 1)
        self.assertEqual(self.launches, 2)

    def test_newer_client_replaces_the_server(self):
        old, old_threads = self.start("0.0.1")
        self.hold.clear()
        with mock.patch.object(chitchat, "VERSION", "0.0.1"):
            self.reply("First.")
            self.reply("Second.")
        self.assertEqual(self.launches, 0)
        self.until(lambda: self.spoken == [("0.0.1", "First.")])
        # A session on a newer plugin rings while the old server is mid-sentence.
        self.reply("From the new plugin.", session=OTHER, pane="")
        self.assertEqual(self.launches, 1)
        new, _ = self.servers[-1]
        self.assertEqual(new.version, chitchat.VERSION)
        self.assertFalse(chitchat.send({"op": "ring"})["restart"])
        # The new server waits for the old one to finish what it is saying.
        time.sleep(0.1)
        self.assertEqual(len(self.spoken), 1)
        self.hold.set()
        for t in old_threads:
            t.join(3)
        self.until(lambda: len(self.spoken) == 3)
        self.assertEqual(self.spoken, [
            ("0.0.1", "First."),
            (chitchat.VERSION, "Second."),
            (chitchat.VERSION, "From the new plugin."),
        ])

    def test_restores_spotify_left_lowered_by_a_dead_server(self):
        chitchat.DUCKED.write_text("70")
        chitchat.restore_unowned()
        self.assertEqual(self.volume, 70)
        self.assertFalse(chitchat.DUCKED.exists())
        # A live server owns the volume.
        self.start()
        # Once the server holds the audio lock and has found nothing to say.
        time.sleep(0.1)
        chitchat.DUCKED.write_text("70")
        self.volume = 30
        chitchat.restore_unowned()
        self.assertEqual(self.volume, 30)
        self.assertTrue(chitchat.DUCKED.exists())


if __name__ == "__main__":
    unittest.main()
