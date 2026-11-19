import { test, expect } from 'claude-code/testing'
import { stripVoiceTags } from './strip'

test('removes tags and keeps their text', () => {
  expect(stripVoiceTags('<speak>Merged the fix.</speak>\n\n| a | b |')).toBe('Merged the fix.\n\n| a | b |')
})

test('removes announce tags and keeps their text', () => {
  expect(stripVoiceTags('Done. <announce>PR merged.</announce>')).toBe('Done. PR merged.')
})

test('leaves tags inside code alone', () => {
  const md = 'Wrap it as `<speak>x</speak>`.\n\n```\n<speak>y</speak>\n```'
  expect(stripVoiceTags(md)).toBe(md)
})

test('hides a tag still streaming in', () => {
  expect(stripVoiceTags('<speak>Done.</spe')).toBe('Done.')
  expect(stripVoiceTags('Done. <')).toBe('Done. ')
  expect(stripVoiceTags('<announce>Merged.</annou')).toBe('Merged.')
})

test('leaves other angle brackets alone', () => {
  expect(stripVoiceTags('a <b> and <span>')).toBe('a <b> and <span>')
})
