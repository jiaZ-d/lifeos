import React, { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api, getToken, setToken } from './api.js'

const NAV = [
  ['/', '✅ 今日'],
  ['/records', '📝 记录'],
  ['/knowledge', '📚 知识库'],
  ['/timeline', '🕐 时间轴'],
  ['/goals', '🎯 目标'],
  ['/board', '📋 看板'],
  ['/projections', '🔮 未来推演'],
  ['/stats', '📊 统计'],
  ['/settings', '⚙️ 设置'],
]

export default function App() {
  const nav = useNavigate()
  const [isAdmin, setIsAdmin] = useState(false)
  useEffect(() => {
    if (!getToken()) { nav('/login'); return }
    api.get('/api/auth/me').then((me) => setIsAdmin(me.is_admin)).catch(() => {})
  }, [])
  const logout = () => {
    setToken('')
    nav('/login')
  }
  const navItems = isAdmin ? [...NAV, ['/users', '👑 用户管理']] : NAV
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="logo">LifeOS</div>
        <nav>
          {navItems.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === '/'}>
              {label}
            </NavLink>
          ))}
          <a href="#logout" onClick={(e) => { e.preventDefault(); logout() }}>🚪 退出</a>
        </nav>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
