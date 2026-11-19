# chitchat

Claude Code replies, spoken aloud in a voice cloned locally from a short WAV sample. Speech runs on your machine with [Chatterbox Turbo](https://huggingface.co/mlx-community/chatterbox-turbo-fp16) through mlx-audio; nothing is sent to a speech service.

While speech is on, Claude is asked to write one reply that reads well on screen and aloud, since the listener reads along. Code blocks, tables, URLs, and inline code that looks like a path or command are skipped when spoken, so Claude puts a one-sentence description before each code block or table. If a reply wraps text in `<speak>...</speak>`, only that text is spoken, and the plugin hides the tags in the drawn reply.

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

Put the command on your PATH so you can turn speech on from a session:

```
ln -s ~/code/chitchat/scripts/chitchat ~/.local/bin/chitchat
```

## Voices

A voice is a WAV file in `${XDG_DATA_HOME:-~/.local/share}/chitchat/voices`, named for the file: `voices/narrator.wav` is the voice `narrator`. The sample needs more than 5 seconds of clear speech; only the first 15 are used. `default.wav` is used when no voice is chosen, and `CHITCHAT_VOICE` names a different default. Only clone a voice you have the right to use.

## Use

Run these from a Claude Code session with the `!` prefix:

| Command | Effect |
|---|---|
| `! chitchat on` / `off` / `toggle` / `status` | Turn speech on or off for this session |
| `chitchat on tagged` | Speak only text in `<speak>` tags. Meant for an agent you supervise rather than read along with: it runs this itself and tags only important updates |
| `! chitchat voice [NAME]` | List voices, or choose this session's voice |
| `! chitchat speed [RATE]` | Show or set playback rate, 0.5 to 2 (default 1.1, or `CHITCHAT_SPEED`) |
| `! chitchat stop` | Stop this session's speech |

Each session speaks its messages in order. Sessions that speak at the same time take turns, and a new prompt silences whatever its session had left to say. Text written between tool calls is spoken as the turn goes on.

## Music

While any session speaks, chitchat lowers Spotify's volume and puts it back once no session has anything left to say, so the music stays low between sentences and between sessions taking turns. Speech that is cut off, by a new prompt, `chitchat stop`, `chitchat off`, or the session ending, restores it as well. The volume from before is kept in `${XDG_STATE_HOME:-~/.local/state}/chitchat/ducked`, so if a run is killed before restoring, the next chitchat command restores it. If you change Spotify's volume by hand while it is lowered, chitchat leaves it alone and restores the earlier level when speech ends.

| Variable | Effect |
|---|---|
| `CHITCHAT_DUCK` | Spotify's volume while speaking, 0 to 100 (default 30), or `off` to leave Spotify alone |

Spotify is only touched while it is running; chitchat never launches it. The first time, macOS asks once for permission to let your terminal control Spotify.

## How it fits together

- `scripts/chitchat`: the speech engine and command line
- `hooks/hooks.json`: Stop, PreToolUse, UserPromptSubmit, and SessionEnd hooks that call the script; each returns at once while no session has speech on
- `hooks/register.ts`: a hooks module that strips `<speak>` tags from drawn replies, leaving the stored transcript, which the script reads, unchanged

## License

MIT
