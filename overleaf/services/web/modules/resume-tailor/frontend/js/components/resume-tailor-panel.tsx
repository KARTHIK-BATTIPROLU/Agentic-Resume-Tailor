import { useCallback, useRef, useState } from 'react'
import { postJSON } from '@/infrastructure/fetch-json'
import getMeta from '@/utils/meta'
import RailPanelHeader from '@/features/ide-react/components/rail/rail-panel-header'

// ── Types ─────────────────────────────────────────────────────────────────────

type AtsResult = {
  score?: number
  match_pct?: number
  matched?: string[]
  missing?: string[]
}

type Variant = {
  label: string
  tex: string
  ats: AtsResult
  analysis: Record<string, unknown>
}

type Step =
  | 'resume'    // 1 — paste / upload resume
  | 'jd'        // 2 — paste job description
  | 'questions' // 3 — gap-question loop
  | 'variants'  // 4 — pick from 3 variants
  | 'done'      // 5 — .tex inserted, compile

// ── Helpers ───────────────────────────────────────────────────────────────────

function scoreColor(score?: number): string {
  if (score === undefined) return '#888'
  if (score >= 75) return '#137333'
  if (score >= 50) return '#b45309'
  return '#c5221f'
}

function KeywordPills({
  keywords,
  color,
}: {
  keywords: string[]
  color: string
}) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
      {keywords.slice(0, 18).map(k => (
        <span
          key={k}
          style={{
            padding: '1px 7px',
            borderRadius: 10,
            fontSize: '0.75rem',
            background: color === 'green' ? '#e6f4ea' : '#fce8e6',
            color: color === 'green' ? '#137333' : '#c5221f',
          }}
        >
          {k}
        </span>
      ))}
    </div>
  )
}

function VariantCard({
  variant,
  selected,
  onSelect,
}: {
  variant: Variant
  selected: boolean
  onSelect: () => void
}) {
  const ats = variant.ats
  return (
    <div
      onClick={onSelect}
      style={{
        border: `2px solid ${selected ? '#4f46e5' : '#d1d5db'}`,
        borderRadius: 8,
        padding: '10px 12px',
        cursor: 'pointer',
        background: selected ? '#eef2ff' : '#fff',
        transition: 'border-color 0.15s',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontWeight: 700, textTransform: 'capitalize' }}>{variant.label}</span>
        <span
          style={{
            fontSize: '1.4rem',
            fontWeight: 800,
            color: scoreColor(ats.score),
          }}
        >
          {ats.score ?? '–'}
          <span style={{ fontSize: '0.7rem', color: '#666', fontWeight: 400 }}> /100</span>
        </span>
      </div>
      {typeof ats.match_pct === 'number' && (
        <div style={{ fontSize: '0.78rem', color: '#555', marginTop: 2 }}>
          {Math.round(ats.match_pct * 100)}% keyword match
        </div>
      )}
      {(ats.matched?.length ?? 0) > 0 && (
        <>
          <div style={{ fontSize: '0.72rem', color: '#666', marginTop: 6 }}>Matched</div>
          <KeywordPills keywords={ats.matched!} color="green" />
        </>
      )}
      {(ats.missing?.length ?? 0) > 0 && (
        <>
          <div style={{ fontSize: '0.72rem', color: '#666', marginTop: 6 }}>Missing</div>
          <KeywordPills keywords={ats.missing!} color="red" />
        </>
      )}
    </div>
  )
}

// ── Stepper indicator ─────────────────────────────────────────────────────────

const STEP_LABELS: Record<Step, string> = {
  resume: '1. Resume',
  jd: '2. Job',
  questions: '3. Q&A',
  variants: '4. Pick',
  done: '5. Done',
}
const STEP_ORDER: Step[] = ['resume', 'jd', 'questions', 'variants', 'done']

function Stepper({ current }: { current: Step }) {
  const idx = STEP_ORDER.indexOf(current)
  return (
    <div
      style={{
        display: 'flex',
        gap: 4,
        marginBottom: 14,
        fontSize: '0.7rem',
        color: '#555',
      }}
    >
      {STEP_ORDER.map((s, i) => (
        <span
          key={s}
          style={{
            flex: 1,
            textAlign: 'center',
            borderBottom: `3px solid ${i <= idx ? '#4f46e5' : '#d1d5db'}`,
            paddingBottom: 3,
            fontWeight: i === idx ? 700 : 400,
            color: i < idx ? '#4f46e5' : i === idx ? '#1a1a2e' : '#9ca3af',
          }}
        >
          {STEP_LABELS[s]}
        </span>
      ))}
    </div>
  )
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export default function ResumeTailorPanel() {
  const projectId = getMeta('ol-project_id')

  const [step, setStep] = useState<Step>('resume')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  // Step 1
  const [resumeText, setResumeText] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  // Step 2
  const [jd, setJd] = useState('')

  // Step 3 (gap questions)
  const [sessionId, setSessionId] = useState('')
  const [question, setQuestion] = useState<{ question: string; gap?: string } | null>(null)
  const [answer, setAnswer] = useState('')

  // Step 4
  const [variants, setVariants] = useState<Variant[]>([])
  const [resumeId, setResumeId] = useState('')
  const [selectedVariant, setSelectedVariant] = useState<string>('')

  // Step 5
  const [docName, setDocName] = useState('')

  const err = useCallback((msg: string) => {
    setError(msg)
    setBusy(false)
  }, [])

  // ── Step 1 → 2: save profile ────────────────────────────────────────────────
  const handleResumeNext = useCallback(async () => {
    setBusy(true)
    setError('')
    setStatus('Saving your profile…')
    try {
      if (resumeText.trim()) {
        await postJSON(`/project/${projectId}/resume-tailor/profile/init`, {
          body: { text: resumeText },
        })
      }
      setStep('jd')
      setStatus('')
    } catch (e: any) {
      err(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }, [projectId, resumeText, err])

  // ── Step 2 → 3/4: start tailoring session ──────────────────────────────────
  const handleJdNext = useCallback(async () => {
    if (!jd.trim()) { setError('Paste a job description first.'); return }
    setBusy(true)
    setError('')
    setStatus('Parsing the job description…')
    try {
      const data = await postJSON<any>(
        `/project/${projectId}/resume-tailor/session/start`,
        { body: { jobDescription: jd, resumeText: resumeText || undefined } }
      )
      if (data.status === 'question') {
        setSessionId(data.thread_id)
        setQuestion(data.question)
        setStep('questions')
        setStatus('')
      } else {
        setVariants(data.variants || [])
        setResumeId(data.resume_id || '')
        setSelectedVariant(data.variants?.[0]?.label || '')
        setStep('variants')
        setStatus('')
      }
    } catch (e: any) {
      err(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }, [projectId, jd, resumeText, err])

  // ── Step 3: submit answer ───────────────────────────────────────────────────
  const handleAnswer = useCallback(async () => {
    if (!answer.trim()) return
    setBusy(true)
    setError('')
    setStatus('Processing your answer…')
    try {
      const data = await postJSON<any>(
        `/project/${projectId}/resume-tailor/session/answer`,
        { body: { sessionId, message: answer } }
      )
      setAnswer('')
      if (data.status === 'question') {
        setQuestion(data.question)
        setStatus('')
      } else {
        setVariants(data.variants || [])
        setResumeId(data.resume_id || '')
        setSelectedVariant(data.variants?.[0]?.label || '')
        setStep('variants')
        setStatus('')
      }
    } catch (e: any) {
      err(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }, [projectId, sessionId, answer, err])

  // ── Step 4 → 5: confirm variant ─────────────────────────────────────────────
  const handleConfirm = useCallback(async () => {
    if (!selectedVariant) { setError('Select a variant first.'); return }
    setBusy(true)
    setError('')
    setStatus('Inserting .tex into project…')
    try {
      const data = await postJSON<any>(
        `/project/${projectId}/resume-tailor/session/confirm`,
        { body: { resumeId, variantLabel: selectedVariant } }
      )
      setDocName(data.docName || 'tailored-resume.tex')
      setStep('done')
      setStatus('')
    } catch (e: any) {
      err(e?.message || String(e))
    } finally {
      setBusy(false)
    }
  }, [projectId, resumeId, selectedVariant, err])

  const resetAll = useCallback(() => {
    setStep('resume')
    setResumeText('')
    setJd('')
    setSessionId('')
    setQuestion(null)
    setAnswer('')
    setVariants([])
    setResumeId('')
    setSelectedVariant('')
    setDocName('')
    setStatus('')
    setError('')
  }, [])

  // ── Render ──────────────────────────────────────────────────────────────────
  const s: React.CSSProperties = { fontSize: '0.83rem' }
  const label: React.CSSProperties = {
    fontWeight: 600,
    fontSize: '0.83rem',
    display: 'block',
    marginBottom: 4,
  }

  return (
    <div style={{ padding: '8px 12px', overflowY: 'auto', height: '100%', ...s }}>
      <RailPanelHeader title="Resume Tailor" />
      <Stepper current={step} />

      {/* ── Step 1: Resume ── */}
      {step === 'resume' && (
        <>
          <label style={label}>Paste your resume (optional — skip to use saved profile)</label>
          <textarea
            className="form-control"
            rows={8}
            value={resumeText}
            onChange={e => setResumeText(e.target.value)}
            placeholder="Paste your resume text here, or leave blank to use your saved profile…"
            disabled={busy}
          />
          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
            <button
              className="btn btn-primary btn-sm"
              onClick={handleResumeNext}
              disabled={busy}
            >
              {busy ? 'Saving…' : 'Next →'}
            </button>
          </div>
        </>
      )}

      {/* ── Step 2: Job Description ── */}
      {step === 'jd' && (
        <>
          <label style={label}>Paste the job description</label>
          <textarea
            className="form-control"
            rows={10}
            value={jd}
            onChange={e => setJd(e.target.value)}
            placeholder="Paste the full job description here…"
            disabled={busy}
            autoFocus
          />
          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary btn-sm" onClick={() => setStep('resume')} disabled={busy}>
              ← Back
            </button>
            <button className="btn btn-primary btn-sm" onClick={handleJdNext} disabled={busy}>
              {busy ? status || 'Analysing…' : 'Tailor →'}
            </button>
          </div>
        </>
      )}

      {/* ── Step 3: Gap questions ── */}
      {step === 'questions' && question && (
        <>
          <div style={{ background: '#f3f4f6', borderRadius: 6, padding: '10px 12px', marginBottom: 10 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Quick question</div>
            <p style={{ margin: 0 }}>{question.question}</p>
            {question.gap && (
              <div style={{ fontSize: '0.72rem', color: '#6b7280', marginTop: 4 }}>
                Skill gap: {question.gap}
              </div>
            )}
          </div>
          <textarea
            className="form-control"
            rows={4}
            value={answer}
            onChange={e => setAnswer(e.target.value)}
            placeholder="Your answer (type 'none' or 'skip' if not applicable)…"
            disabled={busy}
            autoFocus
            onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) handleAnswer() }}
          />
          <div style={{ fontSize: '0.72rem', color: '#9ca3af', marginTop: 2 }}>
            Ctrl+Enter to submit
          </div>
          <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
            <button className="btn btn-primary btn-sm" onClick={handleAnswer} disabled={busy || !answer.trim()}>
              {busy ? status || 'Processing…' : 'Submit answer'}
            </button>
          </div>
        </>
      )}

      {/* ── Step 4: Variants ── */}
      {step === 'variants' && (
        <>
          <label style={label}>Choose a variant to insert into your project</label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 12 }}>
            {variants.map(v => (
              <VariantCard
                key={v.label}
                variant={v}
                selected={selectedVariant === v.label}
                onSelect={() => setSelectedVariant(v.label)}
              />
            ))}
          </div>
          <button
            className="btn btn-primary btn-sm"
            onClick={handleConfirm}
            disabled={busy || !selectedVariant}
            style={{ width: '100%' }}
          >
            {busy ? 'Inserting…' : `Use "${selectedVariant}" variant →`}
          </button>
        </>
      )}

      {/* ── Step 5: Done ── */}
      {step === 'done' && (
        <div style={{ textAlign: 'center', padding: '16px 0' }}>
          <div style={{ fontSize: '2rem', marginBottom: 8 }}>✓</div>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>
            <code>{docName}</code> added to project
          </div>
          <p style={{ color: '#555', marginBottom: 14 }}>
            Open it from the file tree and click <strong>Recompile</strong> to build your PDF.
          </p>
          <button className="btn btn-secondary btn-sm" onClick={resetAll}>
            Tailor another →
          </button>
        </div>
      )}

      {/* ── Status / error ── */}
      {busy && status && (
        <p style={{ marginTop: 10, color: '#4f46e5', fontSize: '0.82rem' }}>{status}</p>
      )}
      {error && (
        <p style={{ marginTop: 10, color: '#c5221f', fontSize: '0.82rem' }}>Error: {error}</p>
      )}
    </div>
  )
}
