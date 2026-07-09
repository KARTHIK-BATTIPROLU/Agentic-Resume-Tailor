import logger from '@overleaf/logger'
import multer from 'multer'
import ResumeTailorController from './ResumeTailorController.mjs'
import AuthorizationMiddleware from '../../../../app/src/Features/Authorization/AuthorizationMiddleware.mjs'

const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 10 * 1024 * 1024 } })
const auth = AuthorizationMiddleware.ensureUserCanWriteProjectContent

export default {
  apply(webRouter) {
    logger.debug({}, 'Init resume-tailor router')

    // 1. Tailor — start / answer / confirm
    webRouter.post(
      '/project/:Project_id/resume-tailor/session/start',
      auth,
      ResumeTailorController.sessionStart
    )
    webRouter.post(
      '/project/:Project_id/resume-tailor/session/answer',
      auth,
      ResumeTailorController.sessionAnswer
    )
    webRouter.post(
      '/project/:Project_id/resume-tailor/session/confirm',
      auth,
      ResumeTailorController.sessionConfirm
    )

    // 2. Profile — one-shot init / guided interview / file upload / GET
    webRouter.post(
      '/project/:Project_id/resume-tailor/profile/init',
      auth,
      ResumeTailorController.profileInit
    )
    webRouter.post(
      '/project/:Project_id/resume-tailor/profile/start',
      auth,
      ResumeTailorController.profileStart
    )
    webRouter.post(
      '/project/:Project_id/resume-tailor/profile/answer',
      auth,
      ResumeTailorController.profileAnswer
    )
    webRouter.post(
      '/project/:Project_id/resume-tailor/profile/upload',
      auth,
      upload.single('file'),
      ResumeTailorController.uploadResume
    )
    webRouter.get(
      '/project/:Project_id/resume-tailor/profile',
      auth,
      ResumeTailorController.getProfile
    )
  },
}
