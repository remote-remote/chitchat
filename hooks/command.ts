/** The script's arguments for `/chitchat ARGS`: none toggles speech. */
export function chitchatArgs(args: string): string[] {
  const words = args.trim().split(/\s+/).filter(Boolean)
  return words.length > 0 ? words : ['toggle']
}

/** What `/chitchat` shows for a run of the script: its output, or why it failed. */
export function commandText(run: { exitCode: number; stdout: string; stderr: string }): string {
  if (run.exitCode === 0) return run.stdout.trim() || 'Done.'
  const why = run.stderr.trim() || run.stdout.trim()
  return why ? `chitchat failed: ${why}` : `chitchat failed with exit code ${run.exitCode}`
}
