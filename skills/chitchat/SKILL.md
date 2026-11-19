---
name: chitchat
description: Turn chitchat speech on or off for this Claude Code session, set its voice or speed, or stop it. Use when the user asks for spoken replies, to silence speech, or to change the voice or speed, or when an agent should speak only tagged updates.
argument-hint: "[on [tagged] | off | toggle | status | voice [NAME] | speed [RATE] | stop]"
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
- `stop`: stop this session's speech
