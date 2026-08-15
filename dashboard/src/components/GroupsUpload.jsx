import React, { useState, useRef, useMemo } from 'react'
import * as XLSX from 'xlsx'
import { API } from '../config.js'
import { ButtonContent, OverlayLoader } from '../Loader.jsx'
import { useConfirm } from '../context/ConfirmContext.jsx'

export function GroupsUpload({ currentTotal, onUpdated, listSummary }) {
  const [open, setOpen] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [preview, setPreview] = useState([])
  const [previewSearch, setPreviewSearch] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [parsingFile, setParsingFile] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [applying, setApplying] = useState(false)
  const [uploadMode, setUploadMode] = useState('merge')
  const fileRef = useRef()

  const HEADER_WORDS = new Set([
    'username', 'user', 'group', 'groups', 'channel', 'channels', 'name', 'telegram', 'link', 'url',
  ])

  function extractGroupsFromText(text) {
    const tokens = text.split(/[\n,\t\r]+/).map(s => s.trim()).filter(Boolean)
    const valid = []
    let skippedInvalid = 0
    for (const raw of tokens) {
      const s = raw.replace(/^@/, '').replace(/https?:\/\/t\.me\//i, '')
      if (!s || s.includes('/') || s.length < 3 || !/^[a-zA-Z0-9_]+$/.test(s) || HEADER_WORDS.has(s.toLowerCase())) {
        skippedInvalid += 1
        continue
      }
      valid.push(s)
    }
    return { valid: [...new Set(valid)], skippedInvalid, tokenCount: tokens.length }
  }

  const filteredPreview = useMemo(() => {
    const q = previewSearch.trim().toLowerCase()
    if (!q) return preview
    return preview.filter(g => g.toLowerCase().includes(q))
  }, [preview, previewSearch])

  function parseFile(file) {
    setError('')
    setPreview([])
    setStatus('')
    setParsingFile(true)
    const name = file.name.toLowerCase()
    const done = () => setParsingFile(false)

    if (name.endsWith('.xlsx') || name.endsWith('.xls') || name.endsWith('.csv')) {
      const reader = new FileReader()
      reader.onload = (e) => {
        try {
          const wb = XLSX.read(e.target.result, { type: 'array' })
          const ws = wb.Sheets[wb.SheetNames[0]]
          const rows = XLSX.utils.sheet_to_csv(ws)
          const { valid, skippedInvalid, tokenCount } = extractGroupsFromText(rows)
          setPreview(valid)
          setStatus(
            `Found ${valid.length} valid groups` +
            (skippedInvalid ? ` · skipped ${skippedInvalid} invalid (bad chars, link, too short)` : '') +
            (tokenCount > valid.length + skippedInvalid ? ` · ${tokenCount - valid.length - skippedInvalid} duplicates` : '')
          )
        } catch (err) {
          setError('Failed to parse file: ' + err.message)
        } finally {
          done()
        }
      }
      reader.onerror = () => { setError('Failed to read file'); done() }
      reader.readAsArrayBuffer(file)
    } else if (name.endsWith('.txt') || name.endsWith('.csv')) {
      const reader = new FileReader()
      reader.onload = (e) => {
        const { valid, skippedInvalid } = extractGroupsFromText(e.target.result)
        setPreview(valid)
        setStatus(
          `Found ${valid.length} valid groups` +
          (skippedInvalid ? ` · skipped ${skippedInvalid} invalid (bad chars, link, too short)` : '')
        )
        done()
      }
      reader.onerror = () => { setError('Failed to read file'); done() }
      reader.readAsText(file)
    } else {
      setError('Unsupported file type. Use .xlsx, .xls, .csv, or .txt')
      done()
    }
  }

  function handlePaste() {
    setExtracting(true)
    setError('')
    try {
      const { valid, skippedInvalid } = extractGroupsFromText(pasteText)
      setPreview(valid)
      setStatus(
        `Found ${valid.length} valid groups` +
        (skippedInvalid ? ` · skipped ${skippedInvalid} invalid (bad chars, link, too short)` : '')
      )
    } finally {
      setExtracting(false)
    }
  }

  async function applyGroups() {
    if (!preview.length) return
    const replace = uploadMode === 'replace'
    if (replace) {
      const ok = await confirm({
        title: 'Replace entire master list?',
        message: 'Groups not in this file will be removed from rotation.',
        details: [
          `Current master list: ${currentTotal} groups`,
          `New list from file: ${preview.length} groups (before server skips)`,
          'A backup of the old list is saved on the server automatically.',
        ],
        confirmLabel: 'Replace list',
        cancelLabel: 'Cancel',
        variant: 'warn',
      })
      if (!ok) return
    }
    setApplying(true)
    setStatus('')
    setError('')
    try {
      const res = await fetch(`${API}/groups/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ groups: preview, mode: uploadMode }),
      })
      const data = await res.json()
      if (data.success) {
        let msg
        if (data.mode === 'replace') {
          const parts = [
            `Replaced list: ${data.previous_total} → ${data.total}`,
            `${data.removed_from_old} removed`,
            `${data.added_new} new`,
          ]
          if (data.kept_from_old) parts.push(`${data.kept_from_old} kept from old list`)
          if (data.skipped_dead) parts.push(`${data.skipped_dead} dead/invalid skipped`)
          if (data.skipped_invalid_format) parts.push(`${data.skipped_invalid_format} invalid format skipped`)
          if (data.backup_path) parts.push('backup saved')
          msg = parts.join(' · ')
        } else {
          const parts = [`${data.total} total`, `${data.added_new} new`, `${data.already_existed} already in list`]
          if (data.skipped_invalid_format) parts.push(`${data.skipped_invalid_format} invalid format skipped`)
          if (data.skipped_dead) parts.push(`${data.skipped_dead} dead/invalid skipped`)
          msg = parts.join(' · ')
        }
        setStatus(`Updated — ${msg}.`)
        onUpdated()
        setTimeout(() => {
          setOpen(false)
          setPreview([])
          setPasteText('')
          setStatus('')
          setUploadMode('merge')
        }, 2000)
      } else {
        setError(data.error || 'Failed to update')
      }
    } catch (e) {
      setError(e.message || 'Failed to update')
    } finally {
      setApplying(false)
    }
  }

  const groupsBusy = parsingFile || extracting || applying

  return (
    <div className="panel panel--groups">
      <button type="button" className="panel-toggle" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        <div>
          <span className="panel-toggle-title">Groups list</span>
          <span className="groups-summary-badge">{currentTotal} master</span>
        </div>
        {listSummary && (
          <span className="panel-toggle-meta">
            {listSummary.active != null ? `${listSummary.active} active` : ''}
            {listSummary.dead != null ? ` · ${listSummary.dead} dead` : ''}
          </span>
        )}
        <span className="panel-toggle-chevron">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="panel-body panel-body--relative">
          {groupsBusy && (
            <OverlayLoader
              label={
                applying ? 'Updating groups on server…'
                  : parsingFile ? 'Reading file…'
                    : 'Extracting groups…'
              }
            />
          )}

          <div
            className={`drop-zone${dragging ? ' drop-zone--active' : ''}`}
            onDragOver={e => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => { e.preventDefault(); setDragging(false); parseFile(e.dataTransfer.files[0]) }}
            onClick={() => fileRef.current.click()}
            role="button"
            tabIndex={0}
          >
            <div className="drop-zone-icon">📁</div>
            <p>Drop file or <strong>browse</strong></p>
            <span className="field-hint">.xlsx, .xls, .csv, .txt</span>
            <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv,.txt" className="sr-only" onChange={e => e.target.files[0] && parseFile(e.target.files[0])} />
          </div>

          <div className="divider-label">Or paste usernames</div>
          <textarea
            className="input input--textarea"
            placeholder="One per line or comma-separated @usernames"
            value={pasteText}
            onChange={e => setPasteText(e.target.value)}
            rows={5}
          />
          <button type="button" className="btn btn--accent" onClick={handlePaste} disabled={!pasteText.trim() || extracting}>
            <ButtonContent loading={extracting} loadingLabel="Extracting…">Extract groups</ButtonContent>
          </button>

          {preview.length > 0 && (
            <div className="upload-mode" role="radiogroup" aria-label="Upload mode">
              <label className="upload-mode-option">
                <input
                  type="radio"
                  name="uploadMode"
                  value="merge"
                  checked={uploadMode === 'merge'}
                  onChange={() => setUploadMode('merge')}
                />
                <span>
                  <strong>Merge</strong> — add to current list ({currentTotal} master)
                </span>
              </label>
              <label className={`upload-mode-option${uploadMode === 'replace' ? ' upload-mode-option--warn' : ''}`}>
                <input
                  type="radio"
                  name="uploadMode"
                  value="replace"
                  checked={uploadMode === 'replace'}
                  onChange={() => setUploadMode('replace')}
                />
                <span>
                  <strong>Replace entire list</strong> — only groups from this file (removes others)
                </span>
              </label>
            </div>
          )}

          {preview.length > 0 && (
            <div className="groups-preview">
              <div className="groups-preview-header">
                <span>Preview ({preview.length})</span>
                <input
                  className="input input--search"
                  placeholder="Search preview…"
                  value={previewSearch}
                  onChange={e => setPreviewSearch(e.target.value)}
                />
              </div>
              <div className="groups-preview-list">
                {filteredPreview.map((g, i) => (
                  <div key={`${g}-${i}`} className="groups-preview-item">@{g}</div>
                ))}
              </div>
            </div>
          )}

          {error && <p className="field-error">{error}</p>}
          {status && <p className="field-success">{status}</p>}

          {preview.length > 0 && (
            <div className="btn-row">
              <button
                type="button"
                className={`btn ${uploadMode === 'replace' ? 'btn--warn' : 'btn--success'}`}
                onClick={applyGroups}
                disabled={applying}
              >
                <ButtonContent loading={applying} loadingLabel="Applying…">
                  {uploadMode === 'replace'
                    ? `Replace list (${preview.length} groups)`
                    : `Merge ${preview.length} groups`}
                </ButtonContent>
              </button>
              <button type="button" className="btn btn--ghost" onClick={() => { setPreview([]); setPasteText(''); setStatus(''); setError('') }}>
                Clear
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
