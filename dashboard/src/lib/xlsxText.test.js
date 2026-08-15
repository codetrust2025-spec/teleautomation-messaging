import { describe, it, expect } from 'vitest'
import { zipSync, strToU8 } from 'fflate'
import { extractXlsxText, WorkbookError, MAX_FILE_BYTES } from './xlsxText.js'

const REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

function sheet(cells) {
  return `<?xml version="1.0"?><worksheet><sheetData><row>${cells}</row></sheetData></worksheet>`
}

function build({ sheets, shared, relTarget = 'worksheets/sheet1.xml', extra = {} }) {
  const files = {
    'xl/workbook.xml':
      `<?xml version="1.0"?><workbook xmlns:r="${REL_NS}">` +
      `<sheets><sheet name="First" sheetId="1" r:id="rId1"/></sheets></workbook>`,
    'xl/_rels/workbook.xml.rels':
      `<?xml version="1.0"?><Relationships xmlns="${REL_NS}">` +
      `<Relationship Id="rId1" Target="${relTarget}"/></Relationships>`,
    ...extra,
  }
  if (shared) {
    files['xl/sharedStrings.xml'] =
      `<?xml version="1.0"?><sst>${shared.map((s) => `<si>${s}</si>`).join('')}</sst>`
  }
  for (const [name, xml] of Object.entries(sheets)) files[`xl/worksheets/${name}`] = xml
  const encoded = {}
  for (const [k, v] of Object.entries(files)) {
    encoded[k] = typeof v === 'string' ? strToU8(v) : v
  }
  return zipSync(encoded)
}

describe('extractXlsxText', () => {
  it('reads shared strings from the first sheet', () => {
    const buf = build({
      shared: ['<t>alpha_group</t>', '<t>beta_group</t>'],
      sheets: { 'sheet1.xml': sheet('<c t="s"><v>0</v></c><c t="s"><v>1</v></c>') },
    })
    expect(extractXlsxText(buf).split('\n')).toEqual(['alpha_group', 'beta_group'])
  })

  it('concatenates rich-text runs within one shared string', () => {
    const buf = build({
      shared: ['<r><t>alpha</t></r><r><t>_group</t></r>'],
      sheets: { 'sheet1.xml': sheet('<c t="s"><v>0</v></c>') },
    })
    expect(extractXlsxText(buf)).toBe('alpha_group')
  })

  it('reads inline strings', () => {
    const buf = build({
      sheets: { 'sheet1.xml': sheet('<c t="inlineStr"><is><t>inline_group</t></is></c>') },
    })
    expect(extractXlsxText(buf)).toBe('inline_group')
  })

  it('reads numeric and cached formula values', () => {
    const buf = build({ sheets: { 'sheet1.xml': sheet('<c><v>12345</v></c>') } })
    expect(extractXlsxText(buf)).toBe('12345')
  })

  it('follows workbook relationships rather than archive order', () => {
    // rId1 points at sheet2.xml, so naive "first file wins" would read the wrong sheet.
    const buf = build({
      relTarget: 'worksheets/sheet2.xml',
      shared: ['<t>wrong_sheet</t>', '<t>right_sheet</t>'],
      sheets: {
        'sheet1.xml': sheet('<c t="s"><v>0</v></c>'),
        'sheet2.xml': sheet('<c t="s"><v>1</v></c>'),
      },
    })
    expect(extractXlsxText(buf)).toBe('right_sheet')
  })

  it('falls back to the lowest-numbered sheet when relationships are unusable', () => {
    const buf = build({
      relTarget: 'worksheets/missing.xml',
      shared: ['<t>fallback_group</t>'],
      sheets: { 'sheet1.xml': sheet('<c t="s"><v>0</v></c>') },
    })
    expect(extractXlsxText(buf)).toBe('fallback_group')
  })

  it('never inflates unrelated parts such as media or VBA', () => {
    const buf = build({
      shared: ['<t>only_group</t>'],
      sheets: { 'sheet1.xml': sheet('<c t="s"><v>0</v></c>') },
      extra: {
        'xl/media/image1.png': strToU8('SECRET_MEDIA_PAYLOAD'.repeat(1000)),
        'xl/vbaProject.bin': strToU8('MACRO_PAYLOAD'.repeat(1000)),
      },
    })
    const text = extractXlsxText(buf)
    expect(text).toBe('only_group')
    expect(text).not.toContain('MEDIA')
    expect(text).not.toContain('MACRO')
  })

  it('rejects a legacy .xls (OLE2) file with actionable guidance', () => {
    const ole2 = new Uint8Array([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1, 0, 0, 0, 0])
    expect(() => extractXlsxText(ole2)).toThrow(WorkbookError)
    expect(() => extractXlsxText(ole2)).toThrow(/re-save it as \.xlsx or \.csv/)
  })

  it('rejects non-workbook bytes', () => {
    expect(() => extractXlsxText(strToU8('this is not a spreadsheet'))).toThrow(WorkbookError)
  })

  it('rejects a file above the size limit before parsing', () => {
    const oversized = new Uint8Array(MAX_FILE_BYTES + 1)
    oversized.set([0x50, 0x4b, 0x03, 0x04])
    expect(() => extractXlsxText(oversized)).toThrow(/too large/i)
  })

  it('rejects a workbook with an unreasonable number of parts', () => {
    const sheets = {}
    for (let i = 1; i <= 600; i += 1) sheets[`sheet${i}.xml`] = sheet('<c><v>1</v></c>')
    expect(() => extractXlsxText(build({ sheets }))).toThrow(/too many internal parts/i)
  })

  it('reports a damaged workbook rather than throwing a raw parser error', () => {
    const buf = build({ sheets: { 'sheet1.xml': '<worksheet><unclosed>' } })
    expect(() => extractXlsxText(buf)).toThrow(WorkbookError)
  })

  it('produces text that tokenises into valid group names', () => {
    const buf = build({
      shared: ['<t>username</t>', '<t>real_group_one</t>', '<t>https://t.me/joinchat/xx</t>'],
      sheets: {
        'sheet1.xml': sheet('<c t="s"><v>0</v></c><c t="s"><v>1</v></c><c t="s"><v>2</v></c>'),
      },
    })
    // Mirrors GroupsUpload's allow-list: header words and links must not survive.
    const tokens = extractXlsxText(buf)
      .split(/[\n,\t\r]+/)
      .map((s) => s.trim())
      .filter((s) => s && !s.includes('/') && s.length >= 3 && /^[a-zA-Z0-9_]+$/.test(s))
    expect(tokens).toEqual(['username', 'real_group_one'])
  })
})
