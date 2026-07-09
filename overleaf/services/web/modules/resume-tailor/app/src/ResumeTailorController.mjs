import logger from '@overleaf/logger'
import SessionManager from '../../../../app/src/Features/Authentication/SessionManager.mjs'
import ProjectGetter from '../../../../app/src/Features/Project/ProjectGetter.mjs'
import EditorController from '../../../../app/src/Features/Editor/EditorController.mjs'

const AGENT_URL =
  process.env.RESUME_TAILOR_AGENT_URL || 'http://resume-tailor-agent:8000'
const SERVICE_TOKEN = process.env.RESUME_TAILOR_SERVICE_TOKEN || ''

// ── Agent HTTP helpers ────────────────────────────────────────────────────────
function _headers(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra }
  if (SERVICE_TOKEN) h['X-Service-Token'] = SERVICE_TOKEN
  return h
}

async function _post(path, payload) {
  let res
  try {
    res = await fetch(`${AGENT_URL}${path}`, {
      method: 'POST',
      headers: _headers(),
      body: JSON.stringify(payload),
    })
  } catch (err) {
    throw new Error(`cannot reach agent at ${AGENT_URL} (${err.message})`)
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`agent ${path} ${res.status}: ${text.slice(0, 300)}`)
  }
  return res.json()
}

async function _get(path) {
  let res
  try {
    res = await fetch(`${AGENT_URL}${path}`, {
      method: 'GET',
      headers: _headers({ 'Content-Type': undefined }),
    })
  } catch (err) {
    throw new Error(`cannot reach agent at ${AGENT_URL} (${err.message})`)
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`agent GET ${path} ${res.status}: ${text.slice(0, 300)}`)
  }
  return res.json()
}

// ── 1. Tailor session — start ────────────────────────────────────────────────
async function sessionStart(req, res) {
  const userId = SessionManager.getLoggedInUserId(req.session)
  const { jobDescription, resumeText } = req.body || {}
  if (!jobDescription?.trim()) {
    return res.status(400).json({ error: 'jobDescription is required' })
  }
  try {
    const data = await _post('/session/tailor/start', {
      user_id: userId,
      job_description: jobDescription,
      resume_text: resumeText || null,
    })
    res.json(data)
  } catch (err) {
    logger.err({ err, userId }, 'resume-tailor: sessionStart failed')
    res.status(502).json({ error: err.message })
  }
}

// ── 2. Tailor session — answer ────────────────────────────────────────────────
async function sessionAnswer(req, res) {
  const userId = SessionManager.getLoggedInUserId(req.session)
  const { sessionId, message } = req.body || {}
  if (!sessionId || !message) {
    return res.status(400).json({ error: 'sessionId and message are required' })
  }
  try {
    const data = await _post('/session/tailor/answer', {
      user_id: userId,
      thread_id: sessionId,
      message,
    })
    res.json(data)
  } catch (err) {
    logger.err({ err, userId }, 'resume-tailor: sessionAnswer failed')
    res.status(502).json({ error: err.message })
  }
}

// ── 3. Tailor session — confirm (writes .tex into Overleaf project) ───────────
async function sessionConfirm(req, res) {
  const projectId = req.params.Project_id
  const userId = SessionManager.getLoggedInUserId(req.session)
  const { resumeId, variantLabel } = req.body || {}
  if (!resumeId || !variantLabel) {
    return res.status(400).json({ error: 'resumeId and variantLabel are required' })
  }
  try {
    const out = await _post('/session/tailor/confirm', {
      user_id: userId,
      resume_id: resumeId,
      variant_label: variantLabel,
    })
    const tex = (out && out.tex) || ''
    if (!tex.trim()) {
      return res.status(502).json({ error: 'agent returned no LaTeX' })
    }
    const project = await ProjectGetter.promises.getProject(projectId, {
      rootFolder: true,
    })
    const rootFolderId = project?.rootFolder?.[0]?._id ?? null
    if (!rootFolderId) {
      return res.status(500).json({ error: 'project root folder not found' })
    }
    const docName = `tailored-resume-${variantLabel}-${Date.now().toString(36)}.tex`
    const doc = await EditorController.promises.addDoc(
      projectId,
      rootFolderId,
      docName,
      tex.split('\n'),
      'resume-tailor',
      userId
    )
    res.json({ docName, docId: doc?._id, ats: out.ats || {} })
  } catch (err) {
    logger.err({ err, projectId, userId }, 'resume-tailor: sessionConfirm failed')
    res.status(502).json({ error: err.message })
  }
}

// ── 4. Profile one-shot init ──────────────────────────────────────────────────
async function profileInit(req, res) {
  const userId = SessionManager.getLoggedInUserId(req.session)
  const text = req.body?.text || req.body?.resumeText || ''
  if (!text.trim()) {
    return res.status(400).json({ error: 'text is required' })
  }
  try {
    const data = await _post('/session/profile/init', { user_id: userId, text })
    res.json(data)
  } catch (err) {
    logger.err({ err, userId }, 'resume-tailor: profileInit failed')
    res.status(502).json({ error: err.message })
  }
}

// ── 5. Profile interview — start ──────────────────────────────────────────────
async function profileStart(req, res) {
  const userId = SessionManager.getLoggedInUserId(req.session)
  try {
    const data = await _post('/session/profile/start', { user_id: userId })
    res.json(data)
  } catch (err) {
    logger.err({ err, userId }, 'resume-tailor: profileStart failed')
    res.status(502).json({ error: err.message })
  }
}

// ── 6. Profile interview — answer ─────────────────────────────────────────────
async function profileAnswer(req, res) {
  const userId = SessionManager.getLoggedInUserId(req.session)
  const { threadId, message } = req.body || {}
  if (!threadId || !message) {
    return res.status(400).json({ error: 'threadId and message are required' })
  }
  try {
    const data = await _post('/session/profile/answer', {
      user_id: userId,
      thread_id: threadId,
      message,
    })
    res.json(data)
  } catch (err) {
    logger.err({ err, userId }, 'resume-tailor: profileAnswer failed')
    res.status(502).json({ error: err.message })
  }
}

// ── 7. Upload resume file ──────────────────────────────────────────────────────
async function uploadResume(req, res) {
  const userId = SessionManager.getLoggedInUserId(req.session)
  if (!req.file) {
    return res.status(400).json({ error: 'file is required' })
  }
  // Proxy the file as multipart/form-data to the agent
  const FormData = (await import('node:buffer')).Blob
    ? globalThis.FormData
    : (await import('form-data')).default
  const form = new FormData()
  form.append('file', new Blob([req.file.buffer], { type: req.file.mimetype }), req.file.originalname)

  let agentRes
  try {
    agentRes = await fetch(`${AGENT_URL}/upload/${encodeURIComponent(userId)}`, {
      method: 'POST',
      headers: SERVICE_TOKEN ? { 'X-Service-Token': SERVICE_TOKEN } : {},
      body: form,
    })
  } catch (err) {
    logger.err({ err, userId }, 'resume-tailor: uploadResume network error')
    return res.status(502).json({ error: err.message })
  }
  const json = await agentRes.json().catch(() => ({}))
  if (!agentRes.ok) {
    return res.status(agentRes.status).json(json)
  }
  res.json(json)
}

// ── 8. Get profile ─────────────────────────────────────────────────────────────
async function getProfile(req, res) {
  const userId = SessionManager.getLoggedInUserId(req.session)
  try {
    const data = await _get(`/profile/${encodeURIComponent(userId)}`)
    res.json(data)
  } catch (err) {
    logger.err({ err, userId }, 'resume-tailor: getProfile failed')
    res.status(502).json({ error: err.message })
  }
}

export default {
  sessionStart,
  sessionAnswer,
  sessionConfirm,
  profileInit,
  profileStart,
  profileAnswer,
  uploadResume,
  getProfile,
}
