import { useEffect, useMemo, useState } from 'react'
import { apiRequest } from '../lib/api'
import type { ApiError } from '../lib/api'
import type {
  HfModelSummary,
  HfRepoFile,
  LoadedModelsResponse,
  ModelCatalogItem,
  ModelDownloadJobOut,
  ModelOut,
} from '../types'

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function statusLabel(s: string): string {
  if (s === 'pending') return 'Ожидание…'
  if (s === 'running') return 'Скачивание…'
  if (s === 'done') return 'Готово'
  if (s === 'failed') return 'Ошибка'
  return s
}

export function ModelsPage({
  auth,
}: {
  auth: { token: string | null; fetchMe: () => Promise<void> }
}) {
  const token = auth.token!
  const [catalog, setCatalog] = useState<ModelCatalogItem[]>([])
  const [selectedCatalogId, setSelectedCatalogId] = useState<string>('tinyllama-q4km')
  const [hfRepo, setHfRepo] = useState('TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF')
  const [hfFilename, setHfFilename] = useState('tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf')
  const [hfSearch, setHfSearch] = useState('gguf')
  const [hfResults, setHfResults] = useState<HfModelSummary[]>([])
  const [hfFiles, setHfFiles] = useState<HfRepoFile[]>([])
  const [hfBusy, setHfBusy] = useState(false)

  const [models, setModels] = useState<ModelOut[]>([])
  const [jobs, setJobs] = useState<ModelDownloadJobOut[]>([])
  const [loadedModels, setLoadedModels] = useState<LoadedModelsResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadUnloadBusy, setLoadUnloadBusy] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [downloadStarted, setDownloadStarted] = useState<string | null>(null)

  const hasRunningJobs = useMemo(() => jobs.some((j) => j.status === 'pending' || j.status === 'running'), [jobs])
  const runningJobs = useMemo(
    () => jobs.filter((j) => j.status === 'pending' || j.status === 'running'),
    [jobs]
  )

  const jobsByModel = useMemo(() => {
    const m = new Map<number, ModelDownloadJobOut>()
    for (const j of jobs) {
      const prev = m.get(j.model_id)
      if (!prev || j.id > prev.id) m.set(j.model_id, j)
    }
    return m
  }, [jobs])

  async function refresh() {
    const [cat, m, j, loaded] = await Promise.all([
      apiRequest<ModelCatalogItem[]>('/models/catalog', { token }),
      apiRequest<ModelOut[]>('/models', { token }),
      apiRequest<ModelDownloadJobOut[]>('/models/jobs', { token }),
      apiRequest<LoadedModelsResponse>('/models/loaded', { token }).catch(() => null),
    ])
    setCatalog(cat)
    setModels(m)
    setJobs(j)
    setLoadedModels(loaded)
  }

  async function onLoad(modelId: number) {
    setLoadUnloadBusy(modelId)
    try {
      await apiRequest(`/models/${modelId}/load`, { method: 'POST', token })
      await refresh()
    } catch (e: any) {
      setErr((e as ApiError)?.message ?? String(e))
    } finally {
      setLoadUnloadBusy(null)
    }
  }

  async function onUnload(modelId: number) {
    setLoadUnloadBusy(modelId)
    try {
      await apiRequest(`/models/${modelId}/unload`, { method: 'POST', token })
      await refresh()
    } catch (e: any) {
      setErr((e as ApiError)?.message ?? String(e))
    } finally {
      setLoadUnloadBusy(null)
    }
  }

  async function runHfSearch() {
    setHfBusy(true)
    try {
      const res = await apiRequest<HfModelSummary[]>(
        `/hf/models?q=${encodeURIComponent(hfSearch)}&limit=20`,
        { token }
      )
      setHfResults(res)
    } finally {
      setHfBusy(false)
    }
  }

  async function loadHfFiles(repoId: string) {
    setHfBusy(true)
    try {
      const files = await apiRequest<HfRepoFile[]>(
        `/hf/repo-files?repo_id=${encodeURIComponent(repoId)}&only_gguf=true`,
        { token }
      )
      setHfFiles(files)
      setHfRepo(repoId)
      setHfFilename(files[0]?.filename ?? '')
      setSelectedCatalogId('') // сброс пресета — используем выбор из Browse
    } finally {
      setHfBusy(false)
    }
  }

  useEffect(() => {
    auth.fetchMe().catch(() => {})
    refresh().catch(() => {})
    runHfSearch().catch(() => {})
    const interval = hasRunningJobs ? 1000 : 3000
    const t = setInterval(() => refresh().catch(() => {}), interval)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasRunningJobs])

  async function onDownload(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    setDownloadStarted(null)
    try {
      await apiRequest('/models/download', {
        method: 'POST',
        token,
        body: JSON.stringify({ hf_repo: hfRepo, hf_filename: hfFilename }),
      })
      setDownloadStarted(hfFilename)
      setTimeout(() => setDownloadStarted(null), 5000)
      await refresh()
    } catch (e: any) {
      const ae = e as ApiError
      setErr(ae?.message ?? String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="container">
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Models</h2>
        <span className="muted" style={{ fontSize: 13 }}>
          GGUF downloads → volume `/models`
        </span>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Download from Hugging Face</h3>
        <form onSubmit={onDownload} className="list">
          <label className="list">
            <span className="muted">Preset</span>
            <select
              aria-label="Preset model"
              value={selectedCatalogId}
              onChange={(e) => {
                const id = e.target.value
                setSelectedCatalogId(id)
                const item = catalog.find((c) => c.id === id)
                if (item) {
                  setHfRepo(item.hf_repo)
                  setHfFilename(item.hf_filename)
                }
              }}
            >
              <option value="">Custom / из выбора ниже</option>
              {catalog.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
            {catalog.find((c) => c.id === selectedCatalogId)?.description ? (
              <div className="muted" style={{ fontSize: 12 }}>
                {catalog.find((c) => c.id === selectedCatalogId)?.description}
              </div>
            ) : null}
          </label>
          <label className="list">
            <span className="muted">Repo</span>
            <input
              value={hfRepo}
              onChange={(e) => {
                setHfRepo(e.target.value)
                setSelectedCatalogId('')
              }}
            />
          </label>
          <label className="list">
            <span className="muted">Filename (.gguf)</span>
            <input
              value={hfFilename}
              onChange={(e) => {
                setHfFilename(e.target.value)
                setSelectedCatalogId('')
              }}
            />
          </label>

          <div className="card" style={{ padding: 12 }}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <strong>Browse Hugging Face</strong>
              <span className="muted" style={{ fontSize: 12 }}>
                search → pick repo → pick .gguf
              </span>
            </div>
            <div style={{ height: 10 }} />
            <div className="row">
              <input
                value={hfSearch}
                onChange={(e) => setHfSearch(e.target.value)}
                placeholder="Search models… (e.g. tinyllama gguf)"
              />
              <button type="button" disabled={hfBusy} onClick={() => runHfSearch().catch(() => {})}>
                {hfBusy ? '…' : 'Search'}
              </button>
            </div>
            <div style={{ height: 10 }} />
            <div className="row" style={{ alignItems: 'flex-start' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  Results
                </div>
                <div className="list" style={{ maxHeight: 220, overflow: 'auto' }}>
                  {hfResults.map((r) => (
                    <button
                      key={r.repo_id}
                      type="button"
                      onClick={() => loadHfFiles(r.repo_id).catch(() => {})}
                      style={{
                        borderColor: hfRepo === r.repo_id ? 'rgba(99,102,241,0.6)' : undefined,
                      }}
                    >
                      <div style={{ fontWeight: 600 }}>{r.repo_id}</div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {r.downloads ?? 0} downloads • {r.likes ?? 0} likes
                      </div>
                    </button>
                  ))}
                  {hfResults.length === 0 ? <div className="muted">No results.</div> : null}
                </div>
              </div>
              <div style={{ width: 12 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                  .gguf files
                </div>
                <div className="list" style={{ maxHeight: 220, overflow: 'auto' }}>
                  {hfFiles.map((f) => (
                    <button
                      key={f.filename}
                      type="button"
                      onClick={() => {
                        setHfFilename(f.filename)
                        setSelectedCatalogId('')
                      }}
                      style={{
                        borderColor: hfFilename === f.filename ? 'rgba(16,185,129,0.6)' : undefined,
                      }}
                    >
                      <div style={{ fontWeight: 600 }}>{f.filename}</div>
                    </button>
                  ))}
                  {hfRepo && hfFiles.length === 0 ? <div className="muted">No .gguf files.</div> : null}
                </div>
              </div>
            </div>
          </div>

          {err ? (
            <div className="card" style={{ borderColor: 'rgba(239,68,68,0.35)', background: 'rgba(239,68,68,0.06)' }}>
              {err}
            </div>
          ) : null}
          {downloadStarted ? (
            <div
              className="card"
              style={{
                borderColor: 'rgba(34,197,94,0.5)',
                background: 'rgba(34,197,94,0.1)',
              }}
            >
              Скачивание запущено: <strong>{downloadStarted}</strong> — смотри прогресс ниже.
            </div>
          ) : null}
          <button disabled={busy || !hfRepo || !hfFilename}>
            {busy ? 'Запускаю…' : 'Скачать'}
          </button>
        </form>
      </div>

      {runningJobs.length > 0 ? (
        <div className="card" style={{ marginTop: 12, borderColor: 'rgba(99,102,241,0.4)' }}>
          <h3 style={{ marginTop: 0 }}>Скачивается сейчас</h3>
          {runningJobs.map((job) => {
            const model = models.find((m) => m.id === job.model_id)
            const name = model ? `${model.hf_repo} / ${model.hf_filename}` : `#${job.model_id}`
            const progressMb = formatBytes(Math.max(0, job.progress_bytes))
            return (
              <div key={job.id} className="card" style={{ padding: 12, marginTop: 8 }}>
                <div style={{ fontWeight: 600 }}>{name}</div>
                <div className="row" style={{ marginTop: 8, alignItems: 'center', gap: 12 }}>
                  <div
                    style={{
                      flex: 1,
                      height: 8,
                      background: 'rgba(255,255,255,0.1)',
                      borderRadius: 4,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        height: '100%',
                        width:
                          job.progress_bytes > 0
                            ? `${Math.min(98, Math.round((job.progress_bytes / (200 * 1024 * 1024)) * 100))}%`
                            : '15%',
                        background: 'rgba(99,102,241,0.8)',
                        borderRadius: 4,
                        transition: 'width 0.8s ease',
                      }}
                    />
                  </div>
                  <span className="muted" style={{ fontSize: 13, whiteSpace: 'nowrap' }}>
                    {statusLabel(job.status)} {progressMb}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      ) : null}

      <div style={{ height: 12 }} />

      {loadedModels && loadedModels.models.length > 0 ? (
        <div className="card" style={{ marginBottom: 12, borderColor: 'rgba(16,185,129,0.4)' }}>
          <h3 style={{ marginTop: 0 }}>Загружено в память</h3>
          <div className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
            {loadedModels.models.length} модель(ей) в RAM
          </div>
          <div className="list">
            {loadedModels.models.map((m) => (
              <div key={m.id} className="row" style={{ alignItems: 'center', gap: 8 }}>
                <span style={{ fontWeight: 500 }}>
                  #{m.id} {m.hf_filename}
                </span>
                <button
                  type="button"
                  disabled={loadUnloadBusy === m.id}
                  onClick={() => onUnload(m.id)}
                  style={{ padding: '4px 10px', fontSize: 12 }}
                >
                  {loadUnloadBusy === m.id ? '…' : 'Выгрузить'}
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Мои модели</h3>
        {models.length === 0 ? <div className="muted">No models yet.</div> : null}
        <div className="list">
          {models.map((m) => {
            const job = jobsByModel.get(m.id)
            const isActive = job && (job.status === 'pending' || job.status === 'running')
            const isFailed = job?.status === 'failed'
            const isDone = job?.status === 'done' || m.local_path
            const isLoaded = loadedModels?.model_ids.includes(m.id) ?? false
            return (
              <div
                key={m.id}
                className="card"
                style={{
                  padding: 12,
                  borderColor: isActive ? 'rgba(99,102,241,0.5)' : isFailed ? 'rgba(239,68,68,0.4)' : isLoaded ? 'rgba(16,185,129,0.4)' : undefined,
                }}
              >
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <div style={{ fontWeight: 600 }}>
                    {m.hf_repo} / {m.hf_filename}
                  </div>
                  <div className="row" style={{ gap: 6, alignItems: 'center' }}>
                    {isLoaded ? (
                      <span style={{ fontSize: 11, padding: '2px 6px', borderRadius: 4, background: 'rgba(16,185,129,0.2)' }}>
                        В памяти
                      </span>
                    ) : null}
                    <span
                      style={{
                        fontSize: 12,
                        padding: '2px 8px',
                        borderRadius: 6,
                        background: isDone
                          ? 'rgba(34,197,94,0.2)'
                          : isFailed
                            ? 'rgba(239,68,68,0.2)'
                            : 'rgba(99,102,241,0.2)',
                      }}
                    >
                      {job ? statusLabel(job.status) : m.local_path ? 'Готово' : '—'}
                    </span>
                  </div>
                </div>
                <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>
                  {m.local_path ? `Файл: ${m.local_path}` : '(ещё не скачано)'}
                </div>
                <div className="row" style={{ marginTop: 8, justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    {job?.error ? (
                      <span style={{ color: 'tomato', fontSize: 13 }}>{job.error}</span>
                    ) : job ? (
                      <span className="muted" style={{ fontSize: 13 }}>
                        {formatBytes(Math.max(0, job.progress_bytes))}
                        {m.size_bytes ? ` / ${formatBytes(m.size_bytes)}` : ''}
                      </span>
                    ) : m.size_bytes ? (
                      <span className="muted" style={{ fontSize: 13 }}>{formatBytes(m.size_bytes)}</span>
                    ) : null}
                  </div>
                  {m.local_path && !isActive ? (
                    <div className="row" style={{ gap: 6 }}>
                      {isLoaded ? (
                        <button
                          type="button"
                          disabled={loadUnloadBusy === m.id}
                          onClick={() => onUnload(m.id)}
                          style={{ padding: '4px 10px', fontSize: 12 }}
                        >
                          {loadUnloadBusy === m.id ? '…' : 'Выгрузить'}
                        </button>
                      ) : (
                        <button
                          type="button"
                          disabled={loadUnloadBusy === m.id}
                          onClick={() => onLoad(m.id)}
                          style={{ padding: '4px 10px', fontSize: 12 }}
                        >
                          {loadUnloadBusy === m.id ? '…' : 'Загрузить'}
                        </button>
                      )}
                    </div>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

