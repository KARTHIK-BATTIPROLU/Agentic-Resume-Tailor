import ResumeTailorPanel from './components/resume-tailor-panel'
import { RailElement } from '@/features/ide-react/util/rail-types'

const resumeTailorRailElement: RailElement = {
  key: 'resume-tailor',
  // Cast: the icon name is a valid Material symbol but not in the curated union.
  icon: 'auto_awesome' as RailElement['icon'],
  title: 'Resume Tailor',
  component: <ResumeTailorPanel />,
}

export default resumeTailorRailElement
