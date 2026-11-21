# chitchat

Claude Code replies, spoken aloud in a voice cloned locally from a short WAV sample. Speech runs on your machine with [Chatterbox Turbo](https://huggingface.co/mlx-community/chatterbox-turbo-fp16) through mlx-audio; nothing is sent to a speech service.

While speech is on, Claude is asked to write one reply that reads well on screen and aloud, since the listener reads along. Code blocks, tables, URLs, and inline code that looks like a path or command are skipped when spoken, so Claude puts a one-sentence description before each code block or table. If a reply wraps text in `<speak>...</speak>`, only that text is spoken, and the plugin hides the tags in the drawn reply.

## Focus

Speech plays only while its session is focused in tmux: its pane is the active pane, its window is the active window, and an attached client of its session is focused. With tmux's `focus-events` on, a client counts as focused only while the terminal app is in front. Speech for a session you are not looking at waits, in order, and plays when you come back to it. Focus is checked as each message comes up, so queued speech pauses once you switch away, and a waiting session checks twice a second for your return. A new prompt in the session clears what it had waiting, as it clears speech already playing. While a session waits, other sessions still speak and Spotify comes back up. Outside tmux, or if tmux cannot answer, a session counts as focused.

Text in `<announce>...</announce>` speaks right away, whether the session is focused or not. Claude is asked to use it rarely, for an update worth hearing from another session, such as a merge, a failure, or a decision waiting on you. An announcement is read once: in read-along mode it is read in its place in the reply when the session is focused, and when it was already announced, the rest of the reply plays without it on your return. The plugin hides these tags too.

Outside tagged mode, text Claude writes before a tool call is treated as an announcement too: it speaks as the call starts, focused or not, and is never held or repeated when held speech plays. Final replies wait as above. In tagged mode only tagged text speaks, and `<speak>` text waits for focus wherever it was written.

## Which session is speaking

When an announcement or text written before a tool call plays while its session is not focused, chitchat says the session's name first, on a line of its own so a short pause follows it, as in "buckets search fix. The pull request merged." The name is the session's tmux window name, read when the speech plays, with a leading `fm-` dropped and dashes read as spaces, so a worker window `fm-buckets-search-fix` is "buckets search fix". `/chitchat name NAME` sets a different name for the session, `/chitchat name` shows it, and `/chitchat name --clear` goes back to the window name. Speech from a focused session, and held speech that plays once you return, is said without a name. Outside tmux, or if tmux cannot answer, nothing is said first.

| Variable | Effect |
|---|---|
| `CHITCHAT_FOCUS` | `off` speaks every session, focused or not (default on) |

## Requirements

- macOS on Apple Silicon (mlx-audio, and `afplay` for playback)
- [uv](https://docs.astral.sh/uv/), which installs the script's Python dependencies on first run
- Claude Code with plugin hooks modules; the first spoken reply downloads the model

## Install

```
/plugin install chitchat --marketplace remote-remote/chitchat
```

To edit it in place instead, clone the repository and add the clone as a folder marketplace, which Claude Code reads directly; `/reload-plugins` picks up changes:

```
git clone https://github.com/remote-remote/chitchat ~/code/chitchat
claude plugin marketplace add ~/code/chitchat
claude plugin install chitchat@chitchat
```

## Voices

A voice is a WAV file in `${XDG_DATA_HOME:-~/.local/share}/chitchat/voices`, named for the file: `voices/narrator.wav` is the voice `narrator`. The sample needs more than 5 seconds of clear speech; only the first 15 are used. `default.wav` is used when no voice is chosen, and `CHITCHAT_VOICE` names a different default. Only clone a voice you have the right to use.

## Use

Control speech with the plugin's `chitchat` skill: type `/chitchat` to turn speech on or off for this session, or `/chitchat` followed by a command. If another plugin or skill is also named chitchat, use the namespaced form, `/chitchat:chitchat`. Claude can run the skill itself too, so an agent can turn on tagged mode, or you can ask for speech in plain words. The skill only runs `scripts/chitchat` from the plugin folder with the command given.

| Command | Effect |
|---|---|
| `/chitchat` | Toggle speech for this session |
| `/chitchat on` / `off` / `toggle` / `status` | Turn speech on or off for this session, or show whether it is on |
| `/chitchat on tagged` | Speak only text in `<speak>` or `<announce>` tags. Meant for an agent you supervise rather than read along with: it runs this itself and tags only important updates |
| `/chitchat voice [NAME]` | List voices, or choose this session's voice |
| `/chitchat speed [RATE]` | Show or set playback rate, 0.5 to 2 (default 1.1, or `CHITCHAT_SPEED`) |
| `/chitchat name [NAME]` | Show or set the name said before this session's speech while it is not focused; `name --clear` goes back to the tmux window name |
| `/chitchat stop` | Stop this session's speech |

The script also runs directly, as `scripts/chitchat COMMAND`, where no command means `status`. It finds its session from `CLAUDE_CODE_SESSION_ID`, which commands run by Claude in a session carry, so outside a session only `voice` (to list) and `stop` (which stops every session) work.

Each session speaks its messages in order. Sessions that speak at the same time take turns, and a new prompt silences whatever its session had left to say. Text written before a tool call is spoken as the call starts, so a turn's progress is heard as it goes on.

## Music

While any session speaks, chitchat lowers Spotify's volume and puts it back once no session has anything left to say, so the music stays low between sentences and between sessions taking turns. Speech that is cut off, by a new prompt, `stop`, `off`, or the session ending, restores it as well. The volume from before is kept in `${XDG_STATE_HOME:-~/.local/state}/chitchat/ducked`, so if a run is killed before restoring, the next chitchat command restores it. If you change Spotify's volume by hand while it is lowered, chitchat leaves it alone and restores the earlier level when speech ends.

| Variable | Effect |
|---|---|
| `CHITCHAT_DUCK` | Spotify's volume while speaking, 0 to 100 (default 30), or `off` to leave Spotify alone |

Spotify is only touched while it is running; chitchat never launches it. The first time, macOS asks once for permission to let your terminal control Spotify.

## How it fits together

- `skills/chitchat/SKILL.md`: the skill that runs the script's commands
- `scripts/chitchat`: the speech engine and command line
- `scripts/chitchat_test.py`: focus and naming tests, run with `python3 scripts/chitchat_test.py -v`
- `hooks/hooks.json`: Stop, UserPromptSubmit, and SessionEnd hooks that call the script; each returns at once while no session has speech on
- `hooks/register.ts`: a hooks module that strips `<speak>` and `<announce>` tags from drawn replies, leaving the stored transcript, which the script reads, unchanged. It also reads each response as it streams and hands the text written before a tool call to the script as the call starts, since that text reaches the transcript only after the call has run

## License

MIT
