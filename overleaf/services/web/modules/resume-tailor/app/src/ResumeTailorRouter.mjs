import logger from '@overleaf/logger'
import ResumeTailorController from './ResumeTailorController.mjs'
import AuthorizationMiddleware from '../../../../app/src/Features/Authorization/AuthorizationMiddleware.mjs'

export default {
  apply(webRouter) {
    logger.debug({}, 'Init resume-tailor router')

    // Build/extend the user's career profile from pasted resume text.
    webRouter.post(
      '/project/:Project_id/resume-tailor/profile',
      AuthorizationMiddleware.ensureUserCanWriteProjectContent,
      ResumeTailorController.buildProfile
    )

    // Tailor the resume to a JD and add the generated .tex to the project.
    webRouter.post(
      '/project/:Project_id/resume-tailor/generate',
      AuthorizationMiddleware.ensureUserCanWriteProjectContent,
      ResumeTailorController.generate
    )
  },
}
