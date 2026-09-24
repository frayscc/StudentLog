export type Student = {
  id: string
  student_no: string
  name: string
  pinyin?: string | null
  aliases: string[]
  status: 'active' | 'inactive'
  avatar_url?: string | null
  event_count: number
  last_event_at?: string | null
}

export type EventItem = {
  id: string
  occurred_at: string
  recorded_at: string
  location?: string | null
  category: string
  event_description: string
  student_response?: string | null
  teacher_action?: string | null
  follow_up?: string | null
  raw_transcript?: string | null
  record_method: 'text' | 'voice'
  ai_processed: boolean
  ai_confidence?: number | null
  students: Pick<Student, 'id' | 'student_no' | 'name' | 'avatar_url'>[]
  tags: string[]
}

export type NameCandidate = {
  student_id: string
  student_no: string
  name: string
  confidence: number
  reason: string
}

export type EventDraft = {
  student_ids: string[]
  occurred_at: string
  location?: string | null
  category: string
  event_description: string
  student_response?: string | null
  teacher_action?: string | null
  follow_up?: string | null
  tags: string[]
}

export type StructureResult = {
  transcript: string
  draft: EventDraft
  candidates: NameCandidate[]
  provider: string
  requires_student_confirmation: boolean
  name_corrections: { original: string; corrected: string }[]
}
