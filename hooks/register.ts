import type { EngineInterface, Register } from 'claude-code'
import { PreToolText } from './pretool'
import { stripVoiceTags } from './strip'

// The hooks.json guard: return at once while no session has speech on.
const PRETOOL = `[ -n "$(ls -A "\${XDG_STATE_HOME:-$HOME/.local/state}/chitchat/sessions" 2>/dev/null)" ] && exec "$0" pretool || true`

export const register: Register = on => {
  on('ui.render', { component: 'AssistantMessage' }, ($, e, next) => {
    const text = stripVoiceTags(e.props.text)
    return text === e.props.text ? next(e) : next({ ...e, props: { ...e.props, text } })
  })

  // A step's text reaches the transcript only after its tool call has run, so
  // the text written before a call is taken from the response as it streams.
  on('turn.step', async function* ($, e, next) {
    const stream = next(e)
    if (e.agentId !== undefined) return yield* stream
    const text = new PreToolText()
    for await (const chunk of stream) {
      say($, text.read(chunk))
      yield chunk
    }
    const response = await stream.result
    if (response.toolUses.length > 0) say($, text.take())
    return response
  })
}

/** Queue text written before a tool call, without holding up the response. */
function say($: EngineInterface, texts: string[]): void {
  if (texts.length === 0) return
  void (async () => {
    const script = `${$.plugin.root}/scripts/chitchat`
    const env = await $.process.hookEnv()
    const run = await $.process.run(['/bin/sh', '-c', PRETOOL, script], { env, stdin: JSON.stringify(texts) })
    if (run.exitCode !== 0) $.ui.log(`chitchat pretool failed: ${run.stderr}`, { to: 'debug' })
  })().catch(err => $.ui.log(`chitchat pretool failed: ${err}`, { to: 'debug' }))
}
