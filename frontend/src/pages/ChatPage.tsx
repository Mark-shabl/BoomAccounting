import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API_BASE_URL, apiRequest } from '../lib/api'

function splitByThinkTags(text: string): { type: 'normal' | 'think'; text: string }[] {
  const parts: { type: 'normal' | 'think'; text: string }[] = []
  const regex = /<think>([\s\S]*?)<\/think>/gi
  let lastIndex = 0
  let match
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'normal', text: text.slice(lastIndex, match.index) })
    }
    parts.push({ type: 'think', text: match[1] })
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) {
    parts.push({ type: 'normal', text: text.slice(lastIndex) })
  }
  if (parts.length === 0) {
    parts.push({ type: 'normal', text })
  }
  return parts
}
import type { ApiError } from '../lib/api'
import { fetchSse } from '../lib/sse'
import type { ChatDetail, ChatOut, MessageOut, ModelOut } from '../types'

export function ChatPage({
  auth,
}: {
  auth: { token: string | null; fetchMe: () => Promise<void> }
}) {
  const token = auth.token!
  const [models, setModels] = useState<ModelOut[]>([])
  const [chats, setChats] = useState<ChatOut[]>([])
  const [activeChatId, setActiveChatId] = useState<number | null>(null)
  const [detail, setDetail] = useState<ChatDetail | null>(null)

  const [newChatModelId, setNewChatModelId] = useState<number | ''>('')
  const [newChatTitle, setNewChatTitle] = useState('')

  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  const [temperature, setTemperature] = useState(0.7)
  const [maxTokens, setMaxTokens] = useState(512)
  const [topP, setTopP] = useState(0.95)
  const [topK, setTopK] = useState(40)
  const [repeatPenalty, setRepeatPenalty] = useState(1.1)
  const [systemPrompt, setSystemPrompt] = useState('')

  const modelsById = useMemo(() => new Map(models.map((m) => [m.id, m])), [models])

  async function refreshSidebar() {
    setLoadErr(null)
    try {
      const [m, c] = await Promise.all([
        apiRequest<ModelOut[]>('/models', { token }),
        apiRequest<ChatOut[]>('/chats', { token }),
      ])
      setModels(m)
      setChats(c)
      if (newChatModelId === '' && m.length > 0) setNewChatModelId(m[0].id)
    } catch (e: any) {
      const msg = e?.message ?? String(e)
      setLoadErr(msg.includes('Failed to fetch') ? 'Backend недоступен. Запустите docker compose up.' : msg)
    } finally {
      setLoading(false)
    }
  }

  async function loadChat(chatId: number) {
    setErr(null)
    try {
      const d = await apiRequest<ChatDetail>(`/chats/${chatId}`, { token })
      setDetail(d)
      setActiveChatId(chatId)
      queueMicrotask(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }))
    } catch (e: any) {
      const ae = e as ApiError
      setErr(ae?.message ?? String(e))
    }
  }

  useEffect(() => {
    auth.fetchMe().catch(() => {})
    refreshSidebar()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function onDeleteChat(e: React.MouseEvent, chatId: number) {
    e.stopPropagation()
    if (!confirm('Удалить этот чат?')) return
    setErr(null)
    try {
      await apiRequest('/chats/remove', {
        method: 'POST',
        token,
        body: JSON.stringify({ chat_id: chatId }),
      })
      if (activeChatId === chatId) {
        setDetail(null)
        setActiveChatId(null)
      }
      await refreshSidebar()
    } catch (e: any) {
      const ae = e as ApiError
      setErr(ae?.message ?? String(e))
    }
  }

  async function onCreateChat(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    if (newChatModelId === '') {
      setErr('Pick a model first (download a GGUF in Models page).')
      return
    }
    try {
      const chat = await apiRequest<ChatOut>('/chats', {
        method: 'POST',
        token,
        body: JSON.stringify({ model_id: newChatModelId, title: newChatTitle || undefined }),
      })
      await refreshSidebar()
      await loadChat(chat.id)
      setNewChatTitle('')
    } catch (e: any) {
      const ae = e as ApiError
      setErr(ae?.message ?? String(e))
    }
  }

  async function onSend(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    if (!activeChatId) return
    if (!input.trim()) return
    setBusy(true)
    try {
      const userMsg = await apiRequest<MessageOut>(`/chats/${activeChatId}/messages`, {
        method: 'POST',
        token,
        body: JSON.stringify({ content: input }),
      })
      setInput('')

      // optimistic UI: add user message and streaming assistant placeholder
      setDetail((d) => {
        if (!d) return d
        return { ...d, messages: [...d.messages, userMsg, { ...userMsg, id: -Date.now(), role: 'assistant', content: '' }] }
      })

      const params = new URLSearchParams({
        after_message_id: String(userMsg.id),
        temperature: String(temperature),
        max_tokens: String(maxTokens),
        top_p: String(topP),
        top_k: String(topK),
        repeat_penalty: String(repeatPenalty),
      })
      if (systemPrompt.trim()) params.set('system_prompt', systemPrompt.trim())
      const streamUrl = `${API_BASE_URL}/chats/${activeChatId}/stream?${params}`
      const streamOpts: RequestInit = {
        method: 'GET',
        headers: { authorization: `Bearer ${token}` },
      }
      let assistantText = ''
      let tokensUsed: number | null = null

      for await (const evt of fetchSse(streamUrl, streamOpts)) {
        if (evt.event === 'token') {
          assistantText += evt.data
          setDetail((d) => {
            if (!d) return d
            const msgs = [...d.messages]
            for (let i = msgs.length - 1; i >= 0; i--) {
              if (msgs[i].role === 'assistant') {
                msgs[i] = { ...msgs[i], content: assistantText }
                break
              }
            }
            return { ...d, messages: msgs }
          })
          queueMicrotask(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }))
        } else if (evt.event === 'error') {
          throw new Error(evt.data || 'generation failed')
        } else if (evt.event === 'done') {
          tokensUsed = evt.data ? parseInt(evt.data, 10) : null
          if (!isNaN(tokensUsed as number)) {
            setDetail((d) => {
              if (!d) return d
              const msgs = [...d.messages]
              for (let i = msgs.length - 1; i >= 0; i--) {
                if (msgs[i].role === 'assistant') {
                  msgs[i] = { ...msgs[i], tokens_used: tokensUsed ?? undefined }
                  break
                }
              }
              return { ...d, messages: msgs }
            })
          }
          break
        }
      }

      await loadChat(activeChatId)
      await refreshSidebar()
    } catch (e: any) {
      const ae = e as ApiError
      setErr(ae?.message ?? String(e))
    } finally {
      setBusy(false)
    }
  }

  if (loadErr) {
    return (
      <div className="card" style={{ maxWidth: 500, margin: '40px auto' }}>
        <h3 style={{ marginTop: 0, color: 'tomato' }}>Ошибка загрузки</h3>
        <p>{loadErr}</p>
        <button onClick={() => { setLoading(true); setLoadErr(null); refreshSidebar(); }}>
          Повторить
        </button>
      </div>
    )
  }

  return (
    <div className="split">
      <div className="card" style={{ minHeight: 0 }}>
        <h3 style={{ marginTop: 0 }}>Chats</h3>
        <form onSubmit={onCreateChat} className="list">
          <div className="row">
            <select
              aria-label="Model selector"
              value={newChatModelId}
              onChange={(e) => setNewChatModelId(e.target.value ? Number(e.target.value) : '')}
            >
              <option value="">Pick model…</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  #{m.id} {m.hf_filename}
                </option>
              ))}
            </select>
            <button type="submit">New</button>
          </div>
          <input
            value={newChatTitle}
            onChange={(e) => setNewChatTitle(e.target.value)}
            placeholder="Optional title"
          />
          {newChatModelId !== '' ? (
            <div className="muted" style={{ fontSize: 12 }}>
              {modelsById.get(Number(newChatModelId))?.hf_repo}
            </div>
          ) : null}
        </form>

        <div style={{ height: 12 }} />

        {loading ? (
          <div className="muted">Загрузка…</div>
        ) : (
        <div className="list" style={{ maxHeight: '60vh', overflow: 'auto' }}>
          {chats.map((c) => (
            <div
              key={c.id}
              className="row"
              style={{
                border: '1px solid rgba(255,255,255,0.14)',
                borderRadius: 10,
                padding: 10,
                cursor: 'pointer',
                borderColor: activeChatId === c.id ? 'rgba(99,102,241,0.6)' : undefined,
                justifyContent: 'space-between',
                alignItems: 'flex-start',
              }}
              onClick={() => loadChat(c.id)}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>{c.title}</div>
                <div className="muted" style={{ fontSize: 12 }}>
                  chat #{c.id} • model #{c.model_id}
                </div>
              </div>
              <button
                type="button"
                onClick={(e) => onDeleteChat(e, c.id)}
                title="Удалить чат"
                style={{ flexShrink: 0, padding: '4px 8px', fontSize: 12 }}
              >
                ✕
              </button>
            </div>
          ))}
          {chats.length === 0 ? <div className="muted">No chats yet.</div> : null}
        </div>
        )}
      </div>

      <div className="chatBox">
        <div className="messages">
          {!detail ? (
            <div className="muted">Pick a chat or create a new one.</div>
          ) : (
            <>
              {detail.messages.map((m) => (
                <div key={m.id} className={`msg ${m.role}`}>
                  <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                    {m.role}
                  </div>
                  <div className="msg-content">
                    {splitByThinkTags(m.content).map((part, i) =>
                    part.type === 'think' ? (
                      <span key={i} className="msg-think">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.text}</ReactMarkdown>
                      </span>
                    ) : (
                      <ReactMarkdown key={i} remarkPlugins={[remarkGfm]}>
                        {part.text}
                      </ReactMarkdown>
                    )
                  )}
                  </div>
                  {m.role === 'assistant' && (m.tokens_used != null) ? (
                    <div className="muted msg-tokens" style={{ fontSize: 11, marginTop: 6 }}>
                      Токенов: {m.tokens_used}
                    </div>
                  ) : null}
                </div>
              ))}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        <form onSubmit={onSend} className="card">
          <div className="row">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={detail ? 'Type a message…' : 'Create/select a chat first…'}
              disabled={!detail || busy}
            />
            <button disabled={!detail || busy || !input.trim()}>{busy ? 'Sending…' : 'Send'}</button>
          </div>
          {err ? (
            <div style={{ marginTop: 10, color: 'tomato' }}>
              {err}
            </div>
          ) : null}
          {detail ? (
            <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
              SSE stream, model #{detail.chat.model_id}
            </div>
          ) : null}
        </form>
      </div>

      <div className="card" style={{ minHeight: 0, overflow: 'auto' }}>
        <h3 style={{ marginTop: 0 }}>Настройки</h3>
        <div className="list">
          <label>
            <span className="muted" style={{ fontSize: 12 }}>Модель</span>
            <div style={{ marginTop: 4 }}>
              {detail ? modelsById.get(detail.chat.model_id)?.hf_filename ?? `#${detail.chat.model_id}` : '—'}
            </div>
          </label>
          <label>
            <span className="muted" style={{ fontSize: 12 }}>Temperature</span>
            <input
              type="number"
              min={0}
              max={2}
              step={0.1}
              value={temperature}
              onChange={(e) => setTemperature(Number(e.target.value))}
            />
          </label>
          <label>
            <span className="muted" style={{ fontSize: 12 }}>Max tokens</span>
            <input
              type="number"
              min={1}
              max={4096}
              value={maxTokens}
              onChange={(e) => setMaxTokens(Number(e.target.value))}
            />
          </label>
          <label>
            <span className="muted" style={{ fontSize: 12 }}>Top P</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={topP}
              onChange={(e) => setTopP(Number(e.target.value))}
            />
          </label>
          <label>
            <span className="muted" style={{ fontSize: 12 }}>Top K</span>
            <input
              type="number"
              min={1}
              max={100}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
            />
          </label>
          <label>
            <span className="muted" style={{ fontSize: 12 }}>Repeat penalty</span>
            <input
              type="number"
              min={1}
              max={2}
              step={0.1}
              value={repeatPenalty}
              onChange={(e) => setRepeatPenalty(Number(e.target.value))}
            />
          </label>
          <label>
            <span className="muted" style={{ fontSize: 12 }}>System prompt</span>
            <textarea
              rows={4}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="Опционально: инструкции для модели"
              style={{ marginTop: 4 }}
            />
          </label>
        </div>
      </div>
    </div>
  )
}

