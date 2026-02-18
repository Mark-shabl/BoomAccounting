export type TokenOut = { access_token: string; token_type: 'bearer' }

export type UserOut = { id: number; email: string; created_at: string }

export type ModelOut = {
  id: number
  hf_repo: string
  hf_filename: string
  local_path: string | null
  size_bytes: number | null
  created_at: string
}

export type LoadedModelsResponse = {
  model_ids: number[]
  models: { id: number; hf_repo: string; hf_filename: string }[]
}

export type ModelDownloadJobOut = {
  id: number
  model_id: number
  status: 'pending' | 'running' | 'done' | 'failed' | string
  progress_bytes: number
  error: string | null
  started_at: string | null
  finished_at: string | null
}

export type ModelCatalogItem = {
  id: string
  label: string
  hf_repo: string
  hf_filename: string
  description: string | null
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

