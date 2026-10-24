import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function Today() {
  const [data, setData] = useState(null)
  const [title, setTitle] = useState('')
  const [minutes, setMinutes] = useState(0) // 默认不限时
  const [summary, setSummary] = useState('')
  const [msg, setMsg] = useState('')

  const load = async () => {
    setData(await api.get('/api/today'))
    // default-show the stored summary if one exists (no LLM call)
    const s = await api.get('/api/llm/daily-summary')
    if (s.exists) setSummary(s.summary)
  }
  useEffect(() => { load().catch(console.error) }, [])

  // P2-4: 20:00 待办提醒(Web Notification)
  useEffect(() => {
    const tick = () => {
      const now = new Date()
      if (now.getHours() === 20 && now.getMinutes() === 0 && 'Notification' in window) {
        if (Notification.permission === 'granted') {
          const undone = (data?.summary?.total || 0) - (data?.summary?.done || 0)
          if (undone > 0) new Notification('LifeOS 待办提醒', { body: `今天还有 ${undone} 条待办未完成` })
        }
      }
    }
    const timer = setInterval(tick, 60 * 1000)
    return () => clearInterval(timer)
  }, [data])

  const complete = async (id) => { await api.post(`/api/actions/${id}/complete`); await load() }
  const reopen = async (id) => { await api.post(`/api/actions/${id}/reopen`); await load() }
  const debtOp = async (id, op) => { await api.post(`/api/actions/${id}/debt/${op}`); await load() }
  const del = async (id) => {
    if (!confirm('删除这条待办?')) return
    await api.del(`/api/actions/${id}`)
    await load()
  }

  const add = async () => {
    if (!title.trim()) return
    await api.post('/api/actions', { title, minutes, date: new Date().toISOString().slice(0, 10) })
    setTitle('')
    await load()
  }

  const genSummary = async () => {
    setSummary('生成中…')
    const r = await api.post('/api/llm/daily-summary', { force_refresh: true })
    setSummary(r.summary)
  }

  const askNotify = async () => {
    if (!('Notification' in window)) return setMsg('浏览器不支持通知')
    const p = await Notification.requestPermission()
    setMsg(p === 'granted' ? '✅ 已开启待办提醒(每天 20:00)' : '未授权通知')
  }

  const autoPlan = async () => {
    setMsg('正在根据任务生成今日待办…')
    try {
      const r = await api.post('/api/today/auto-plan')
      setMsg(
        r.created.length === 0
          ? '没有可生成的任务(可能都已有今日待办,或还没有未完成任务)'
          : `✅ 已从任务生成 ${r.created.length} 个今日待办${r.degraded ? '(AI 不可用,模板生成)' : ''}`
      )
      await load()
    } catch (ex) {
      setMsg(ex.message)
    }
  }

  if (!data) return <p className="muted">加载中…</p>
  const { actions, debts, summary: sum } = data

  return (
    <div>
      <h2 className="page-title">✅ 今日 · {data.date}</h2>
      <div className="summary-grid">
        <div className="card"><div className="num">{sum.done}/{sum.total}</div><div className="muted">今日完成</div></div>
        <div className="card"><div className="num">{sum.focus_minutes}</div><div className="l muted">待办分钟</div></div>
        <div className="card"><div className="num">{debts.length}</div><div className="muted">欠账</div></div>
      </div>

      <div className="card">
        <div className="spread">
          <b>来自目标任务的今日待办</b>
          <button className="ghost" onClick={autoPlan}>⚡ 从任务生成今日待办</button>
        </div>
        <p className="muted">根据你的任务自动拆解生成(优先周任务、进行中、临近截止),也可手动添加;勾选即完成。</p>
        <button className="ghost" onClick={askNotify} style={{ marginBottom: 6 }}>🔔 开启 20:00 待办提醒</button>
        {msg && <p className="muted">{msg}</p>}
        <div className="row">
          <input placeholder="手动添加待办,如:读书30分钟 / 7点起床" value={title} style={{ flex: 1 }}
            onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
          <select value={minutes} onChange={(e) => setMinutes(+e.target.value)}>
            <option value={0}>不限时</option>
            {[15, 30, 45, 60].map((m) => <option key={m} value={m}>{m}分钟</option>)}
          </select>
          <button onClick={add}>添加</button>
        </div>
        {actions.map((a) => (
          <div className={`action-item ${a.status === 'done' ? 'done' : ''}`} key={a.id}>
            <input type="checkbox" checked={a.status === 'done'}
              onChange={() => (a.status === 'done' ? reopen(a.id) : complete(a.id))} />
            <span className="title" style={{ flex: 1 }}>{a.title}</span>
            {a.minutes > 0 && <span className="muted">{a.minutes}分钟</span>}
            {a.status === 'debt' && <span className="badge red">欠账</span>}
            <button className="tl-del" onClick={() => del(a.id)} title="删除">×</button>
          </div>
        ))}
        {actions.length === 0 && <p className="muted">今天还没有待办,添加一个吧</p>}
      </div>

      {debts.length > 0 && (
        <div className="card">
          <b>⏰ 欠账区</b> <span className="muted">顺延 3 次自动进入,请处理</span>
          {debts.map((d) => (
            <div className="list-item" key={d.id}>
              <span>{d.title} <span className="muted">(已顺延 {d.postpone_count} 次)</span></span>
              <div className="row">
                <button className="ghost" onClick={() => debtOp(d.id, 'do')}>今天做</button>
                <button className="danger" onClick={() => debtOp(d.id, 'giveup')}>放弃</button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <div className="spread">
          <b>🌙 今日小结</b>
          <button className="ghost" onClick={genSummary}>AI 生成小结</button>
        </div>
        <p className="muted" style={{ whiteSpace: 'pre-wrap' }}>{summary || '点击右上角生成(每日 21:30 也会自动生成)'}</p>
      </div>
    </div>
  )
}
