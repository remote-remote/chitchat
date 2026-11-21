"""Time from handing chitchat a message to its first clip starting to play.

Compares two copies of scripts/chitchat, such as main's and a branch's, each run
with its own state directory and real voices and model. An afplay on PATH ahead
of the real one notes when each clip starts and ends, then plays it at volume 0,
so playback takes its real time without sound. Spotify ducking and focus gating
are off. A message is handed over by running `chitchat say SESSION`, as a hook
runs the script, and timed from just before that command starts.

  python3 scripts/chitchat_bench.py OUT_DIR NAME=SCRIPT [NAME=SCRIPT ...] [--runs N]

Each SCRIPT is copied into OUT_DIR/NAME along with the plugin.json beside it, so
processes are found by path and killed for cold starts without touching any other
chitchat. Results are printed as a table and written to OUT_DIR/results.json.
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

TEXT = "The build passed, and the pull request is ready for review."
VOICE, SWITCH_VOICE = "default", "picard"
# Speeds tell the two sessions' clips apart in the afplay log.
SPEED_A, SPEED_B = "1.1", "1.15"

AFPLAY = """#!/bin/sh
# Note each clip's start and end with its rate, then play it silently.
now() { /usr/bin/perl -MTime::HiRes=time -e 'printf "%.6f", time'; }
echo "start $(now) $2" >> "$CHITCHAT_BENCH_LOG"
/usr/bin/afplay -v 0 "$@"
echo "end $(now) $2" >> "$CHITCHAT_BENCH_LOG"
"""


class Impl:
    def __init__(self, out: Path, name: str, source: str):
        source = Path(source)
        self.name = name
        self.root = out / name
        shutil.rmtree(self.root, ignore_errors=True)
        (self.root / "scripts").mkdir(parents=True)
        self.script = self.root / "scripts" / "chitchat"
        shutil.copy2(source, self.script)
        plugin = source.resolve().parent.parent / ".claude-plugin"
        if plugin.exists():
            shutil.copytree(plugin, self.root / ".claude-plugin")
        voices = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "chitchat" / "voices"
        mine = self.root / "data" / "chitchat" / "voices"
        mine.mkdir(parents=True)
        for v in (VOICE, SWITCH_VOICE):
            (mine / f"{v}.wav").symlink_to(voices / f"{v}.wav")
        stub = self.root / "bin"
        stub.mkdir()
        (stub / "afplay").write_text(AFPLAY)
        (stub / "afplay").chmod(0o755)
        self.log = self.root / "afplay.log"
        self.state = self.root / "state" / "chitchat"
        uv_python = subprocess.run(["uv", "python", "dir"], capture_output=True, text=True).stdout.strip()
        self.env = {
            **{k: v for k, v in os.environ.items() if not k.startswith(("CHITCHAT_", "TMUX", "CLAUDE_CODE_SESSION"))},
            "PATH": f"{stub}:{os.environ['PATH']}",
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_DATA_HOME": str(self.root / "data"),
            # uv keeps its Pythons under XDG_DATA_HOME; keep using the installed ones.
            "UV_PYTHON_INSTALL_DIR": uv_python,
            "CHITCHAT_DUCK": "off",
            "CHITCHAT_FOCUS": "off",
            "CHITCHAT_VOICE": VOICE,
            "CHITCHAT_BENCH_LOG": str(self.log),
        }

    def set(self, kind: str, session: str, value: str) -> None:
        d = self.state / kind
        d.mkdir(parents=True, exist_ok=True)
        (d / session).write_text(value)

    def say(self, session: str, text: str = TEXT) -> tuple[float, float]:
        """Hand a message over; return when the command started and when it returned."""
        start = time.time()
        subprocess.run([str(self.script), "say", session], input=text, text=True, env=self.env, check=True)
        return start, time.time()

    def clips(self) -> list[tuple[str, float, str]]:
        if not self.log.exists():
            return []
        return [(k, float(t), r) for k, t, r in (line.split() for line in self.log.read_text().splitlines())]

    def wait_clips(self, ends: int, timeout: float = 120) -> list[tuple[str, float, str]]:
        deadline = time.time() + timeout
        while sum(k == "end" for k, _, _ in self.clips()) < ends:
            if time.time() > deadline:
                raise TimeoutError(f"{self.name}: waited for {ends} clips to end")
            time.sleep(0.02)
        return self.clips()

    def wait_starts(self, starts: int, timeout: float = 120) -> None:
        deadline = time.time() + timeout
        while sum(k == "start" for k, _, _ in self.clips()) < starts:
            if time.time() > deadline:
                raise TimeoutError(f"{self.name}: waited for {starts} clips to start")
            time.sleep(0.02)

    def first(self, kind: str, rate: str, after: float = 0) -> float:
        return next(t for k, t, r in self.clips() if k == kind and r == rate and t >= after)

    def last(self, kind: str, rate: str) -> float:
        return [t for k, t, r in self.clips() if k == kind and r == rate][-1]

    def processes(self) -> list[str]:
        ps = subprocess.run(["pgrep", "-f", str(self.script)], capture_output=True, text=True)
        return ps.stdout.split()

    def kill(self) -> None:
        """No worker or server left, for a cold start."""
        subprocess.run(["pkill", "-f", str(self.script)])
        deadline = time.time() + 10
        while self.processes() and time.time() < deadline:
            time.sleep(0.05)

    def settle(self) -> None:
        """Let whatever is speaking finish, and old per-session workers exit."""
        time.sleep(0.5)

    def reset(self) -> None:
        self.log.unlink(missing_ok=True)
        for s in ("a", "b"):
            self.set("speeds", s, SPEED_A if s == "a" else SPEED_B)
            self.set("chosen-voices", s, VOICE)


def cold(impl: Impl) -> dict:
    impl.kill()
    impl.reset()
    start, returned = impl.say("a")
    impl.wait_clips(1)
    return {"latency": impl.first("start", SPEED_A) - start, "say returns": returned - start}


def warm(impl: Impl) -> dict:
    """A message after the last one finished, with nothing speaking."""
    impl.reset()
    start, returned = impl.say("a")
    impl.wait_clips(1)
    return {"latency": impl.first("start", SPEED_A) - start, "say returns": returned - start}


def back_to_back(impl: Impl, switch: bool = False) -> dict:
    """A second message in the same session, handed over while the first plays:
    the gap from the first message's clip ending to the second's starting. Each
    message is one sentence, which Turbo generates as one clip. With switch, the
    second message is in another voice, chosen once the first has started."""
    impl.reset()
    impl.say("a")
    impl.wait_starts(1)
    if switch:
        impl.set("chosen-voices", "a", SWITCH_VOICE)
    start, _ = impl.say("a", "Second message: " + TEXT)
    clips = impl.wait_clips(2)
    starts = [t for k, t, _ in clips if k == "start"]
    ends = [t for k, t, _ in clips if k == "end"]
    assert len(starts) == 2, f"expected one clip per message, got {clips}"
    return {"gap": starts[1] - ends[0], "latency": starts[1] - start}


def voice_switch(impl: Impl) -> dict:
    return back_to_back(impl, switch=True)


def two_sessions(impl: Impl) -> dict:
    """Two sessions hand over a message at the same moment."""
    impl.reset()
    starts = {}
    threads = [threading.Thread(target=lambda s=s: starts.setdefault(s, impl.say(s)[0])) for s in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    deadline = time.time() + 120
    while not (any(r == SPEED_A and k == "end" for k, _, r in impl.clips())
               and any(r == SPEED_B and k == "end" for k, _, r in impl.clips())):
        if time.time() > deadline:
            raise TimeoutError("both sessions never played")
        time.sleep(0.02)
    time.sleep(1)  # any remaining clips of the later speaker
    a = impl.first("start", SPEED_A) - starts["a"]
    b = impl.first("start", SPEED_B) - starts["b"]
    done = max(impl.last("end", SPEED_A), impl.last("end", SPEED_B)) - min(starts.values())
    return {"first": min(a, b), "second": max(a, b), "both done": done}


CASES = [("cold start", cold), ("warm", warm), ("back to back", back_to_back), ("voice switch", voice_switch), ("two sessions", two_sessions)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path)
    parser.add_argument("impls", nargs="+", help="NAME=SCRIPT")
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    impls = [Impl(args.out, *spec.split("=", 1)) for spec in args.impls]
    results: dict = {}
    for impl in impls:
        # Builds the script's uv environment and warms the model files in the OS cache,
        # so cold starts time loading the model rather than installing it.
        impl.reset()
        impl.say("a")
        impl.wait_clips(1, timeout=600)
        impl.settle()
        for case, run in CASES:
            samples = []
            for _ in range(args.runs):
                samples.append(run(impl))
                impl.settle()
                print(f"{impl.name} {case}: {samples[-1]}", file=sys.stderr, flush=True)
            results.setdefault(case, {})[impl.name] = samples
        impl.kill()
    (args.out / "results.json").write_text(json.dumps(results, indent=2))
    print(table(results, [i.name for i in impls]))


def table(results: dict, names: list[str]) -> str:
    rows = ["| Case | Measure | " + " | ".join(f"{n}: median (range), s" for n in names) + " |",
            "|---|---|" + "---|" * len(names)]
    for case, by_impl in results.items():
        for measure in by_impl[names[0]][0]:
            cells = []
            for n in names:
                values = [s[measure] for s in by_impl[n]]
                cells.append(f"{statistics.median(values):.2f} ({min(values):.2f}–{max(values):.2f})")
            rows.append(f"| {case} | {measure} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


if __name__ == "__main__":
    main()
