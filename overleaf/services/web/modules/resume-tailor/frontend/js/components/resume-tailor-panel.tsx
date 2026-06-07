import { useCallback, useState } from 'react'
import { postJSON } from '@/infrastructure/fetch-json'
import getMeta from '@/utils/meta'
import RailPanelHeader from '@/features/ide-react/components/rail/rail-panel-header'

type GenResult = {
  docName: string
  analysis: {
    ats_match_score?: number
    matched_keywords?: string[]
    missing_keywords?: string[]
  }
  ats: {
    score?: number
    match_pct?: number
    matched?: string[]
    missing?: string[]
  }
}

export default function ResumeTailorPanel() {
  const projectId = getMeta('ol-project_id')
  const [resumeText, setResumeText] = useState('')
  const [jd, setJd] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [result, setResult] = useState<GenResult | null>(null)

  const saveProfile = useCallback(async () => {
    if (!resumeText.trim()) {
      setStatus('Paste your resume first.')
      return
    }
    setBusy(true)
    setStatus('Saving your profile…')
    try {
      const data = await postJSON<{ added?: Record<string, number> }>(
        `/project/${projectId}/resume-tailor/profile`,
        { body: { resumeText } }
      )
      const added = data?.added || {}
      const total = Object.values(added).reduce(
        (a: number, b) => a + Number(b || 0),
        0
      )
      setStatus(`Saved ${total} item(s) to your profile.`)
    } catch (e: any) {
      setStatus(`Error: ${e?.message || e}`)
    } finally {
      setBusy(false)
    }
  }, [projectId, resumeText])

  const generate = useCallback(async () => {
    if (!jd.trim()) {
      setStatus('Paste a job description first.')
      return
    }
    setBusy(true)
    setStatus('Tailoring your resume and adding it to the project…')
    setResult(null)
    try {
      const data = await postJSON<GenResult>(
        `/project/${projectId}/resume-tailor/generate`,
        { body: { jobDescription: jd } }
      )
      setResult(data)
      setStatus(
        `Added ${data.docName} to your project — open it from the file tree and compile.`
      )
    } catch (e: any) {
      setStatus(`Error: ${e?.message || e}`)
    } finally {
      setBusy(false)
    }
  }, [projectId, jd])

  const ats = result?.ats || {}

  return (
    <div
      className="resume-tailor-panel"
      style={{ padding: '8px 12px', overflowY: 'auto', height: '100%' }}
    >
      <RailPanelHeader title="Resume Tailor" />

      <p className="text-muted" style={{ fontSize: '0.85rem' }}>
        Build a profile from your resume, then tailor it to a job. The result is
        added to this project as a <code>.tex</code> file you can compile here.
      </p>

      <label style={{ fontWeight: 600, fontSize: '0.85rem' }}>
        1. Your resume / experience (optional)
      </label>
      <textarea
        className="form-control"
        rows={5}
        value={resumeText}
        onChange={e => setResumeText(e.target.value)}
        placeholder="Paste your resume to build your profile…"
      />
      <button
        className="btn btn-secondary btn-sm"
        style={{ marginTop: 6 }}
        onClick={saveProfile}
        disabled={busy}
      >
        Save to profile
      </button>

      <label
        style={{
          fontWeight: 600,
          fontSize: '0.85rem',
          marginTop: 14,
          display: 'block',
        }}
      >
        2. Target job description
      </label>
      <textarea
        className="form-control"
        rows={6}
        value={jd}
        onChange={e => setJd(e.target.value)}
        placeholder="Paste the job description…"
      />
      <button
        className="btn btn-primary btn-sm"
        style={{ marginTop: 6 }}
        onClick={generate}
        disabled={busy}
      >
        Tailor &amp; add to project
      </button>

      {status && (
        <p style={{ marginTop: 10, fontSize: '0.85rem' }}>{status}</p>
      )}

      {result && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: '1.6rem', fontWeight: 700 }}>
            {ats.score ?? '–'}
            <span
              className="text-muted"
              style={{ fontSize: '0.8rem', fontWeight: 400 }}
            >
              {' '}
              ATS score
              {typeof ats.match_pct === 'number'
                ? ` · ${Math.round(ats.match_pct * 100)}% match`
                : ''}
            </span>
          </div>

          <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 6 }}>
            Matched keywords
          </div>
          <div>
            {(ats.matched || []).slice(0, 20).map((k: string) => (
              <span
                key={k}
                className="badge"
                style={{
                  margin: 2,
                  background: '#e6f4ea',
                  color: '#137333',
                }}
              >
                {k}
              </span>
            ))}
          </div>

          <div className="text-muted" style={{ fontSize: '0.8rem', marginTop: 6 }}>
            Missing keywords
          </div>
          <div>
            {(ats.missing || []).slice(0, 20).map((k: string) => (
              <span
                key={k}
                className="badge"
                style={{ margin: 2, background: '#fce8e6', color: '#c5221f' }}
              >
                {k}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
