export type TokenOut = { access_token: string; token_type: 'bearer' }

export type UserOut = { id: number; email: string; created_at: string }

export type ModelOut = {
  id: number
  hf_repo: string
  hf_filename: string
  local_path: string | null
  size_bytes: number | null
  default_temperature?: number | null
  default_max_tokens?: number | null
  default_top_p?: number | null
  default_top_k?: number | null
  default_repeat_penalty?: number | null
  created_at: string
}

export type LoadedModelsResponse = {
  model_ids: number[]
  models: { id: number; hf_repo: string; hf_filename: string }[]
}

export type ModelDownloadJobOut = {
  id: number
  model_id: number
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled' | string
  progress_bytes: number
  /** Total file size from Hugging Face metadata (when available) */
  expected_bytes?: number | null
  error: string | null
  started_at: string | null
  finished_at: string | null
}

export type HfModelSummary = {
  repo_id: string
  likes: number | null
  downloads: number | null
  pipeline_tag: string | null
  tags: string[]
}

export type HfRepoFile = {
  filename: string
}

export type ChatOut = {
  id: number
  model_id: number
  title: string
  created_at: string
}

export type MessageOut = {
  id: number
  chat_id: number
  role: 'system' | 'user' | 'assistant' | string
  content: string
  tokens_used?: number | null
  created_at: string
}

export type ChatDetail = {
  chat: ChatOut
  messages: MessageOut[]
}

export type ModelParamsOut = {
  temperature?: number | null
  num_predict?: number | null
  top_p?: number | null
  top_k?: number | null
  repeat_penalty?: number | null
  source?: string
}

