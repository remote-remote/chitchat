import type { TurnStepChunk } from 'claude-code'

/**
 * The text blocks of a model response as they stream in, handed over when a
 * tool call begins, so text written before a call is spoken as the call starts.
 */
export class PreToolText {
  private blocks = new Map<number, string>()

  /** Reads a chunk; at the start of a tool call, returns the text written since the last one. */
  read(chunk: TurnStepChunk): string[] {
    if (chunk.kind === 'text') {
      this.blocks.set(chunk.index, (this.blocks.get(chunk.index) ?? '') + chunk.text)
    }
    return chunk.kind === 'tool' ? this.take() : []
  }

  /** Returns the text not yet handed over, and forgets it. */
  take(): string[] {
    const texts = [...this.blocks.values()].filter(text => text.trim())
    this.blocks.clear()
    return texts
  }
}
