import { useCallback, useMemo, useState } from 'react'
import { Link, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { apiRequest } from './lib/api'
import type { TokenOut, UserOut } from './types'
import { ChatPage } from './pages/ChatPage'
import { LoginPage } from './pages/LoginPage'
import { ModelsPage } from './pages/ModelsPage'
import { RegisterPage } from './pages/RegisterPage'

const TOKEN_KEY = 'boom_token'

function App() {
  const navigate = useNavigate()
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY))
  const [me, setMe] = useState<UserOut | null>(null)

  const isAuthed = !!token

  const setAuthedToken = useCallback((t: string | null) => {
    setToken(t)
    if (t) localStorage.setItem(TOKEN_KEY, t)
    else localStorage.removeItem(TOKEN_KEY)
    setMe(null)
  }, [])

  const fetchMe = useCallback(async () => {
    if (!token) return
    try {
      const user = await apiRequest<UserOut>('/auth/me', { token })
      setMe(user)
    } catch (e: any) {
      const msg = String(e?.message ?? e)
      if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
        setMe(null)
        return
      }
      setAuthedToken(null)
      navigate('/login')
    }
  }, [navigate, setAuthedToken, token])

  const authApi = useMemo(
    () => ({
      token,
      me,
      isAuthed,
      fetchMe,
      async login(email: string, password: string) {
        const out = await apiRequest<TokenOut>('/auth/login', {
          method: 'POST',
          body: JSON.stringify({ email, password }),
        })
        setAuthedToken(out.access_token)
        navigate('/models')
      },
      async register(email: string, password: string) {
        await apiRequest<UserOut>('/auth/register', {
          method: 'POST',
          body: JSON.stringify({ email, password }),
        })
        await this.login(email, password)
      },
      logout() {
        setAuthedToken(null)
        navigate('/login')
      },
    }),
    [fetchMe, isAuthed, me, navigate, setAuthedToken, token]
  )

  return (
    <div className="layout">
      <div className="topbar">
        <div className="topbar-inner">
          <div className="row" style={{ gap: 10 }}>
            <strong>Boom WebUI</strong>
            {isAuthed ? (
              <span className="muted" style={{ fontSize: 13 }}>
                {me ? me.email : '...'}
              </span>
            ) : null}
          </div>
          <div className="row" style={{ gap: 10 }}>
            {isAuthed ? (
              <>
                <Link to="/models">Models</Link>
                <Link to="/chat">Chat</Link>
                <button onClick={authApi.logout}>Logout</button>
              </>
            ) : (
              <>
                <Link to="/login">Login</Link>
                <Link to="/register">Register</Link>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="app">
        <div className="app-content" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <Routes>
          <Route path="/" element={<Navigate to={isAuthed ? '/models' : '/login'} replace />} />
          <Route path="/login" element={<LoginPage auth={authApi} />} />
          <Route path="/register" element={<RegisterPage auth={authApi} />} />
          <Route
            path="/models"
            element={isAuthed ? <ModelsPage auth={authApi} /> : <Navigate to="/login" replace />}
          />
          <Route
            path="/chat"
            element={isAuthed ? <ChatPage auth={authApi} /> : <Navigate to="/login" replace />}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}

export default App
