import { describe, expect, it } from 'vitest'
import { OWNED_DOMAINS, FORBIDDEN_DOMAINS, PROJECT_ID } from './ownership.js'

describe('Messaging frontend boundary', () => {
  it('contains Marketing domains and excludes Operations domains', () => {
    expect(PROJECT_ID).toBe('teleautomation-messaging')
    expect(OWNED_DOMAINS).toContain('inbox')
    expect(OWNED_DOMAINS.filter(item => FORBIDDEN_DOMAINS.includes(item))).toEqual([])
  })
})
