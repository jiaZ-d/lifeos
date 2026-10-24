import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setToken } from '../api.js'

export default function Login() {
  const nav = useNavigate()
  const [mode, setMode] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    try {
      const url = mode === 'login' ? '/api/auth/login' : '/api/auth/register'
      const data = await api.post(url, { username, password })
      setToken(data.token)
      nav('/')
    } catch (ex) {
      setErr(ex.message)
    }
  }

  return (
    <div className="auth-wrap">
      <div className="card">
        <h1>LifeOS</h1>
        <p className="muted" style={{ textAlign: 'center' }}>个人生活与目标管理系统</p>
        <form onSubmit={submit}>
          <div style={{ marginBottom: 10 }}>
            <input style={{ width: '100%' }} placeholder="用户名" value={username}
              onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div style={{ marginBottom: 10 }}>
            <input style={{ width: '100%' }} type="password" placeholder="密码(≥6位)" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {err && <div className="err">{err}</div>}
          <button style={{ width: '100%' }} type="submit">{mode === 'login' ? '登录' : '注册并登录'}</button>
        </form>
        <p className="muted" style={{ textAlign: 'center', marginTop: 14, cursor: 'pointer' }}
          onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
          {mode === 'login' ? '没有账号?注册新用户' : '已有账号?去登录'}
        </p>
      </div>
    </div>
  )
}
