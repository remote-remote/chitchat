---
name: chitchat
description: Turn chitchat speech on or off for this Claude Code session, set its voice, speed, or spoken name, or stop it. Use when the user asks for spoken replies, to silence speech, or to change the voice, speed, or the name said before the session's speech, or when an agent should speak only tagged updates.
argument-hint: "[on [tagged] | off | toggle | status | voice [NAME] | speed [RATE] | name [NAME | --clear] | stop]"
---

This skill only runs the chitchat script. Requested: `$ARGUMENTS`

Run the script with the one command below that matches the request, written exactly as listed, then report its output in one line. With nothing requested, use `toggle`.

```
"${CLAUDE_PLUGIN_ROOT}/scripts/chitchat" COMMAND
```

- `on`, `off`, `toggle`, `status`: turn speech on or off for this session
- `on tagged`: speak only text in `<speak>` or `<announce>` tags, for an agent the listener supervises
- `voice` lists voices; `voice NAME` chooses this session's voice
- `speed` shows the playback rate; `speed RATE` sets it, 0.5 to 2
- `name` shows the name said before this session's speech while it is not focused; `name NAME` sets it; `name --clear` goes back to the tmux window name
- `stop`: stop this session's speech
