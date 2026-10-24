import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function Users() {
  const [users, setUsers] = useState(null)
  const [me, setMe] = useState(null)
  const [msg, setMsg] = useState('')

  const load = async () => {
    const meData = await api.get('/api/auth/me')
    setMe(meData)
    if (meData.is_admin) setUsers(await api.get('/api/auth/users'))
  }
  useEffect(() => { load().catch((ex) => setMsg(ex.message)) }, [])

  const del = async (u) => {
    if (!confirm(`确认删除用户「${u.username}」及其全部数据(记录/目标/待办/推演/小结/加密凭据)?此操作不可恢复!`)) return
    try {
      const r = await api.del(`/api/auth/users/${u.id}`)
      setMsg(`✅ 已删除用户 ${r.deleted}`)
      await load()
    } catch (ex) {
      setMsg(ex.message)
    }
  }

  const toggleAdmin = async (u) => {
    if (!confirm(`确认${u.is_admin ? '收回' : '授予'}「${u.username}」的管理员权限?`)) return
    try {
      await api.put(`/api/auth/users/${u.id}/admin`, { is_admin: !u.is_admin })
      setMsg(`✅ 已${u.is_admin ? '收回' : '授予'}「${u.username}」管理员权限`)
      await load()
    } catch (ex) {
      setMsg(ex.message)
    }
  }

  if (msg && !users) return <p className="err">{msg}</p>
  if (!users) return <p className="muted">加载中…</p>

  return (
    <div>
      <h2 className="page-title">👑 用户管理</h2>
      <p className="muted">删除用户会同时删除其全部数据(记录/目标/任务/待办/推演/小结/加密凭据),不可恢复。不能删除自己和最后一个管理员。</p>
      {msg && <p className="muted">{msg}</p>}
      <div className="card">
        {users.map((u) => (
          <div className="list-item" key={u.id}>
            <span>
              {u.username}{' '}
              {u.is_admin && <span className="badge">管理员</span>}
              {me && u.id === me.user_id && <span className="badge gray">(当前登录)</span>}
              <span className="muted" style={{ marginLeft: 8 }}>
                注册于 {u.created_at ? new Date(u.created_at).toLocaleDateString('zh-CN') : '—'}
              </span>
            </span>
            <div className="row">
              {u.id !== me?.user_id && (
                <>
                  <button className="ghost" onClick={() => toggleAdmin(u)}>
                    {u.is_admin ? '收回管理员' : '设为管理员'}
                  </button>
                  <button className="danger" onClick={() => del(u)}>删除</button>
                </>
              )}
            </div>
          </div>
        ))}
        {users.length === 0 && <p className="muted">暂无用户</p>}
      </div>
    </div>
  )
}
