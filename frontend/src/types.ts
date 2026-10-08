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
  attachments: Attachment[]
}

export type Attachment = {
  id: string
  original_filename: string
  mime_type: string
  file_size: number
  url: string
  created_at: string
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

export type SummarySections = {
  learning_records: string[]
  discipline_records: string[]
  teacher_communication: string[]
  family_communication: string[]
  actions_taken: string[]
  follow_up_items: string[]
}

export type SummaryResult = {
  date_from: string
  date_to: string
  source_event_count: number
  included_event_count: number
  truncated: boolean
  provider: string
  sections: SummarySections
}
