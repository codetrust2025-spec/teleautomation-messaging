import { unzipSync } from 'fflate'

// Upload hardening limits. Groups Upload only ever needs the text tokens of the
// first worksheet, so every limit here is far above real group lists and far
// below anything that could exhaust the tab.
export const MAX_FILE_BYTES = 10 * 1024 * 1024
export const MAX_ENTRY_BYTES = 64 * 1024 * 1024
export const MAX_TOTAL_BYTES = 128 * 1024 * 1024
export const MAX_ENTRIES = 512
export const MAX_CELLS = 500_000

const REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const ZIP_MAGIC = [0x50, 0x4b, 0x03, 0x04]

export class WorkbookError extends Error {}

function decode(bytes) {
  return new TextDecoder('utf-8').decode(bytes)
}

function parseXml(bytes, label) {
  const doc = new DOMParser().parseFromString(decode(bytes), 'application/xml')
  if (doc.getElementsByTagName('parsererror').length) {
    throw new WorkbookError(`Damaged workbook: ${label} is not valid XML.`)
  }
  return doc
}

function looksLikeZip(bytes) {
  return ZIP_MAGIC.every((b, i) => bytes[i] === b)
}

// Only the entries needed to read sheet 1. Refusing everything else keeps
// embedded media, VBA projects and other sheets out of memory entirely.
function isWanted(name) {
  return (
    name === 'xl/workbook.xml' ||
    name === 'xl/_rels/workbook.xml.rels' ||
    name === 'xl/sharedStrings.xml' ||
    (name.startsWith('xl/worksheets/') && name.endsWith('.xml'))
  )
}

function unzipWorkbook(bytes) {
  let entries = 0
  let total = 0
  try {
    return unzipSync(bytes, {
      filter: (file) => {
        if (!isWanted(file.name)) return false
        // fflate reports the declared uncompressed size before inflating, so a
        // zip bomb is rejected rather than expanded.
        if (file.size > MAX_ENTRY_BYTES) {
          throw new WorkbookError('Workbook rejected: an internal part is unreasonably large.')
        }
        entries += 1
        total += file.size
        if (entries > MAX_ENTRIES) {
          throw new WorkbookError('Workbook rejected: too many internal parts.')
        }
        if (total > MAX_TOTAL_BYTES) {
          throw new WorkbookError('Workbook rejected: uncompressed contents are unreasonably large.')
        }
        return true
      },
    })
  } catch (err) {
    if (err instanceof WorkbookError) throw err
    throw new WorkbookError('Could not read the workbook. It may be corrupt or password-protected.')
  }
}

// <si> may hold a single <t> or rich-text <r><t> runs; concatenate either way.
function readSharedStrings(files) {
  const part = files['xl/sharedStrings.xml']
  if (!part) return []
  const doc = parseXml(part, 'sharedStrings.xml')
  return Array.from(doc.getElementsByTagName('si')).map((si) =>
    Array.from(si.getElementsByTagName('t'))
      .map((t) => t.textContent || '')
      .join(''),
  )
}

function relAttr(el, name) {
  return el.getAttribute(`r:${name}`) || el.getAttributeNS(REL_NS, name) || ''
}

function lowestNumberedSheet(files) {
  const names = Object.keys(files)
    .filter((n) => n.startsWith('xl/worksheets/') && n.endsWith('.xml'))
    .sort((a, b) => {
      const num = (s) => Number((s.match(/(\d+)\.xml$/) || [])[1] ?? Number.MAX_SAFE_INTEGER)
      return num(a) - num(b) || a.localeCompare(b)
    })
  return names[0]
}

// Resolve the *first* sheet via workbook.xml + its relationships, because sheet
// order in the archive does not have to match sheet order in the workbook.
function firstSheetPath(files) {
  const workbook = files['xl/workbook.xml']
  const rels = files['xl/_rels/workbook.xml.rels']
  if (workbook && rels) {
    const sheet = parseXml(workbook, 'workbook.xml').getElementsByTagName('sheet')[0]
    const rid = sheet ? relAttr(sheet, 'id') : ''
    if (rid) {
      const match = Array.from(
        parseXml(rels, 'workbook.xml.rels').getElementsByTagName('Relationship'),
      ).find((rel) => rel.getAttribute('Id') === rid)
      const target = match ? match.getAttribute('Target') || '' : ''
      if (target) {
        const path = `xl/${target.replace(/^\/?(xl\/)?/, '')}`
        if (files[path]) return path
      }
    }
  }
  return lowestNumberedSheet(files)
}

function readSheetText(files, path, shared) {
  const doc = parseXml(files[path], path)
  const cells = doc.getElementsByTagName('c')
  const out = []
  const limit = Math.min(cells.length, MAX_CELLS)
  for (let i = 0; i < limit; i += 1) {
    const cell = cells[i]
    const type = cell.getAttribute('t')
    if (type === 's') {
      // Shared string: <v> holds an index into the shared string table.
      const idx = Number(cell.getElementsByTagName('v')[0]?.textContent)
      const value = Number.isInteger(idx) ? shared[idx] : undefined
      if (value) out.push(value)
      continue
    }
    if (type === 'inlineStr') {
      const text = Array.from(cell.getElementsByTagName('t'))
        .map((t) => t.textContent || '')
        .join('')
      if (text) out.push(text)
      continue
    }
    // Numbers, booleans and cached formula results all surface through <v>.
    const raw = cell.getElementsByTagName('v')[0]?.textContent
    if (raw) out.push(raw)
  }
  return out
}

/**
 * Extract the text of the first worksheet of an .xlsx workbook.
 *
 * Returns newline-separated cell text. Groups Upload only tokenises this and
 * applies a strict `[a-zA-Z0-9_]{3,}` allow-list, so cell geometry is
 * intentionally discarded. Nothing here evaluates formulas, follows external
 * references, or builds objects from workbook-controlled keys.
 *
 * @param {ArrayBuffer|Uint8Array} buffer raw .xlsx bytes
 * @returns {string} newline-separated text of sheet 1
 */
export function extractXlsxText(buffer) {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer)
  if (bytes.byteLength > MAX_FILE_BYTES) {
    throw new WorkbookError(
      `File is too large. The limit is ${Math.round(MAX_FILE_BYTES / (1024 * 1024))} MB.`,
    )
  }
  if (bytes.byteLength < 4 || !looksLikeZip(bytes)) {
    // Catches a legacy .xls (BIFF) or any non-workbook renamed to .xlsx.
    throw new WorkbookError(
      'This is not a valid .xlsx workbook. If it is an older .xls file, re-save it as .xlsx or .csv.',
    )
  }
  const files = unzipWorkbook(bytes)
  const path = firstSheetPath(files)
  if (!path || !files[path]) {
    throw new WorkbookError('Workbook contains no readable worksheet.')
  }
  return readSheetText(files, path, readSharedStrings(files)).join('\n')
}
