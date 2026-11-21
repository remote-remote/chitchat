import { test, expect } from 'claude-code/testing'
import { chitchatArgs, commandText } from './command'

test('no arguments toggle speech', () => {
  expect(chitchatArgs('')).toEqual(['toggle'])
  expect(chitchatArgs('   ')).toEqual(['toggle'])
})

test('arguments pass through as words', () => {
  expect(chitchatArgs('on')).toEqual(['on'])
  expect(chitchatArgs(' on   tagged ')).toEqual(['on', 'tagged'])
  expect(chitchatArgs('voice narrator')).toEqual(['voice', 'narrator'])
  expect(chitchatArgs('speed 1.3')).toEqual(['speed', '1.3'])
  expect(chitchatArgs('name buckets search')).toEqual(['name', 'buckets', 'search'])
  expect(chitchatArgs('name --clear')).toEqual(['name', '--clear'])
  expect(chitchatArgs('server')).toEqual(['server'])
})

test('shows the output, or why the script failed', () => {
  expect(commandText({ exitCode: 0, stdout: 'chitchat: on\n', stderr: '' })).toBe('chitchat: on')
  expect(commandText({ exitCode: 0, stdout: '', stderr: '' })).toBe('Done.')
  expect(commandText({ exitCode: 1, stdout: '', stderr: 'usage\n' })).toBe('chitchat failed: usage')
  expect(commandText({ exitCode: 127, stdout: '', stderr: '' })).toBe('chitchat failed with exit code 127')
})
