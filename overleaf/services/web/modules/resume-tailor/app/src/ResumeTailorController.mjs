import logger from '@overleaf/logger'
import SessionManager from '../../../../app/src/Features/Authentication/SessionManager.mjs'
import ProjectGetter from '../../../../app/src/Features/Project/ProjectGetter.mjs'
import EditorController from '../../../../app/src/Features/Editor/EditorController.mjs'

// The agent (FastAPI) service that does extraction / ranking / generation.
// Overleaf runs in Docker, so the host service is reachable via host.docker.internal.
const AGENT_URL =
  process.env.RESUME_TAILOR_AGENT_URL || 'http://host.docker.internal:8000'

async function callAgent(path, payload) {
  let res
  try {
    res = await fetch(`${AGENT_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch (err) {
    throw new Error(
      `cannot reach resume-tailor agent at ${AGENT_URL} (${err.message})`
    )
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`agent ${path} failed (${res.status}): ${text.slice(0, 300)}`)
  }
  return res.json()
}

async function buildProfile(req, res) {
  const userId = SessionManager.getLoggedInUserId(req.session)
  const resumeText = (req.body && req.body.resumeText) || ''
  if (!resumeText.trim()) {
    return res.status(400).json({ error: 'resumeText is required' })
  }
  try {
    const data = await callAgent('/chat', {
      user_id: userId,
      resume_text: resumeText,
    })
    res.json(data)
  } catch (err) {
    logger.err({ err, userId }, 'resume-tailor: buildProfile failed')
    res.status(502).json({ error: err.message })
  }
}

async function generate(req, res) {
  const projectId = req.params.Project_id
  const userId = SessionManager.getLoggedInUserId(req.session)
  const jobDescription = (req.body && req.body.jobDescription) || ''
  if (!jobDescription.trim()) {
    return res.status(400).json({ error: 'jobDescription is required' })
  }

  try {
    const out = await callAgent('/tailor/tex', {
      user_id: userId,
      job_description: jobDescription,
    })
    const tex = (out && out.tex) || ''
    if (!tex.trim()) {
      return res.status(502).json({ error: 'agent returned no LaTeX' })
    }

    const project = await ProjectGetter.promises.getProject(projectId, {
      rootFolder: true,
    })
    const rootFolderId =
      project && project.rootFolder && project.rootFolder[0]
        ? project.rootFolder[0]._id
        : null
    if (!rootFolderId) {
      return res.status(500).json({ error: 'project root folder not found' })
    }

    const docName = `tailored-resume-${Date.now().toString(36)}.tex`
    const doc = await EditorController.promises.addDoc(
      projectId,
      rootFolderId,
      docName,
      tex.split('\n'),
      'resume-tailor',
      userId
    )

    res.json({
      docName,
      docId: doc && doc._id,
      analysis: out.analysis || {},
      ats: out.ats || {},
    })
  } catch (err) {
    logger.err({ err, projectId, userId }, 'resume-tailor: generate failed')
    res.status(502).json({ error: err.message })
  }
}

export default { buildProfile, generate }
