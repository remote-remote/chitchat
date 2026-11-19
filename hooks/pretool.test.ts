import { test, expect } from 'claude-code/testing'
import { PreToolText } from './pretool'

test('hands over the text written before a tool call when the call begins', () => {
  const text = new PreToolText()
  expect(text.read({ kind: 'text', index: 0, text: 'Running the ' })).toEqual([])
  expect(text.read({ kind: 'text', index: 0, text: 'tests.' })).toEqual([])
  expect(text.read({ kind: 'tool', index: 1, id: 'toolu_1', name: 'Bash' })).toEqual(['Running the tests.'])
  expect(text.read({ kind: 'input', index: 1, json: '{"command":"make test"}' })).toEqual([])
})

test('hands over each piece of text once', () => {
  const text = new PreToolText()
  text.read({ kind: 'text', index: 0, text: 'Reading both files.' })
  expect(text.read({ kind: 'tool', index: 1, id: 'toolu_1', name: 'Read' })).toEqual(['Reading both files.'])
  expect(text.read({ kind: 'tool', index: 2, id: 'toolu_2', name: 'Read' })).toEqual([])
  text.read({ kind: 'text', index: 3, text: 'And one more.' })
  expect(text.take()).toEqual(['And one more.'])
  expect(text.take()).toEqual([])
})

test('keeps separate blocks apart and skips blank ones', () => {
  const text = new PreToolText()
  text.read({ kind: 'text', index: 0, text: 'First.' })
  text.read({ kind: 'text', index: 1, text: '\n\n' })
  text.read({ kind: 'text', index: 2, text: 'Second.' })
  expect(text.read({ kind: 'tool', index: 3, id: 'toolu_1', name: 'Bash' })).toEqual(['First.', 'Second.'])
})

test('ignores thinking', () => {
  const text = new PreToolText()
  text.read({ kind: 'thinking', index: 0, text: 'Maybe the config.' })
  expect(text.read({ kind: 'tool', index: 1, id: 'toolu_1', name: 'Read' })).toEqual([])
})
