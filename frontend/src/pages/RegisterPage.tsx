import { useState } from 'react'
import type { ApiError } from '../lib/api'

export function RegisterPage({
  auth,
}: {
  auth: {
    register: (email: string, password: string) => Promise<void>
  }
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr(null)
    try {
      await auth.register(email, password)
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
        <h2 style={{ marginTop: 0 }}>Register</h2>
        <p className="muted" style={{ marginTop: -6 }}>
          Минимальная регистрация (email + пароль).
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
              placeholder="min 6 chars"
            />
          </label>
          {err ? (
            <div className="card" style={{ borderColor: 'rgba(239,68,68,0.35)', background: 'rgba(239,68,68,0.06)' }}>
              {err}
            </div>
          ) : null}
          <button disabled={busy || !email || password.length < 6}>{busy ? 'Creating…' : 'Create account'}</button>
        </form>
      </div>
    </div>
  )
}

