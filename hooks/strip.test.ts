import { test, expect } from 'claude-code/testing'
import { stripSpeakTags } from './strip'

test('removes tags and keeps their text', () => {
  expect(stripSpeakTags('<speak>Merged the fix.</speak>\n\n| a | b |')).toBe('Merged the fix.\n\n| a | b |')
})

test('leaves tags inside code alone', () => {
  const md = 'Wrap it as `<speak>x</speak>`.\n\n```\n<speak>y</speak>\n```'
  expect(stripSpeakTags(md)).toBe(md)
})

test('hides a tag still streaming in', () => {
  expect(stripSpeakTags('<speak>Done.</spe')).toBe('Done.')
  expect(stripSpeakTags('Done. <')).toBe('Done. ')
})

test('leaves other angle brackets alone', () => {
  expect(stripSpeakTags('a <b> and <span>')).toBe('a <b> and <span>')
})
