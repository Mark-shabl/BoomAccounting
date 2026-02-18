import { useEffect, useState } from 'react'
import type { ApiError } from '../lib/api'

export function LoginPage({
  auth,
}: {
  auth: {
    isAuthed: boolean
    login: (email: string, password: string) => Promise<void>
    fetchMe: () => Promise<void>
  }
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (auth.isAuthed) auth.fetchMe().catch(() => {})
  }, [auth])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await auth.login(email, password)
    } catch (e: any) {
      const ae = e as ApiError
      setErr(ae?.message ?? String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="container">
      <div className="card" style={{ maxWidth: 520, margin: '0 auto' }}>
        <h2 style={{ marginTop: 0 }}>Login</h2>
        <p className="muted" style={{ marginTop: -6 }}>
          JWT auth для доступа к моделям и чатам.
        </p>
        <form onSubmit={onSubmit} className="list">
          <label className="list">
            <span className="muted">Email</span>
            <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
          </label>
          <label className="list">
            <span className="muted">Password</span>
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              placeholder="••••••••"
            />
          </label>
          {err ? (
            <div className="card" style={{ borderColor: 'rgba(239,68,68,0.35)', background: 'rgba(239,68,68,0.06)' }}>
              {err}
            </div>
          ) : null}
          <button disabled={busy || !email || !password}>{busy ? 'Logging in…' : 'Login'}</button>
        </form>
      </div>
    </div>
  )
}

