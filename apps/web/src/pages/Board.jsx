import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

const COLUMNS = [['backlog', '未开始'], ['doing', '进行中'], ['done', '已完成']]
const DIM_LABEL = { goal: '目标', sub: '子目标', month: '月度进度规划', week: '周任务' }

export default function Board() {
  const [dimension, setDimension] = useState('week')
  const [board, setBoard] = useState(null)
  const [newTitle, setNewTitle] = useState('')
  const [busy, setBusy] = useState(null)
  const [msg, setMsg] = useState('')

  const load = async () => setBoard(await api.get(`/api/board?dimension=${dimension}`))
  useEffect(() => { load().catch(console.error) }, [dimension])

  const move = async (card, to) => {
    await api.put(`/api/tasks/${card.id}`, { status: to })
    await load()
  }

  const add = async () => {
    if (!newTitle.trim()) return
    const gran = { goal: 'year', sub: 'year', month: 'month', week: 'week' }[dimension]
    const parent = dimension === 'sub' ? null : null
    await api.post('/api/tasks', { granularity: gran, title: newTitle, parent_task_id: parent })
    setNewTitle('')
    await load()
  }

  const genActions = async (card) => {
    setBusy(card.id)
    try {
      const r = await api.post('/api/llm/generate-actions', { task_id: card.id })
      const date = new Date().toISOString().slice(0, 10)
      for (const a of r.actions) {
        await api.post('/api/actions', { task_id: card.id, title: a.title, minutes: a.minutes || 30, date })
      }
      setMsg(r.degraded ? '⚠️ AI 不可用,已用模板拆解' : `✅ 已拆解为 ${r.actions.length} 个每日待办`)
      await load()
    } catch (ex) {
      setMsg(ex.message)
    }
    setBusy(null)
  }

  const decompose = async (card, target) => {
    setBusy(card.id)
    try {
      const r = await api.post(`/api/tasks/${card.id}/decompose`)
      setMsg(r.degraded
        ? `⚠️ AI 不可用,已按模板生成 ${r.children.length} 条${target}(时间顺序、循序渐进)`
        : `✅ 已生成 ${r.children.length} 条${target}`)
      await load()
    } catch (ex) {
      setMsg(ex.message)
    }
    setBusy(null)
  }

  return (
    <div>
      <h2 className="page-title">📋 看板</h2>
      <p className="muted" style={{ marginTop: -8, marginBottom: 14 }}>
        选择维度查看对应卡片;上层(目标/子目标/月度规划)的状态由下层推导:下层全部完成 → 上层已完成,下层有进行中 → 上层进行中。
      </p>
      <div className="row" style={{ marginBottom: 14 }}>
        <div className="tabs" style={{ marginBottom: 0 }}>
          {Object.entries(DIM_LABEL).map(([k, label]) => (
            <button key={k} className={dimension === k ? 'active' : ''} onClick={() => setDimension(k)}>{label}</button>
          ))}
        </div>
        {dimension !== 'goal' && (
          <>
            <input placeholder={`新建${DIM_LABEL[dimension]}`} value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && add()} style={{ flex: 1, minWidth: 160 }} />
            <button onClick={add}>添加</button>
          </>
        )}
      </div>
      {msg && <p className="muted">{msg}</p>}

      {board && (
        <div className="kanban">
          {COLUMNS.map(([key, label]) => (
            <div className="col" key={key}>
              <h3>{label}({board.columns[key].length})</h3>
              {board.columns[key].map((c) => (
                <div className="kcard" key={c.id}>
                  <div className="spread">
                    <b>{c.title}</b>
                    <span className="badge gray">
                      {c.derived ? '由下层推导' : `P${c.priority}`}
                    </span>
                  </div>
                  {c.parent_title && <div className="muted" style={{ fontSize: 12 }}>↳ {c.parent_title}</div>}
                  <div className="progress" style={{ margin: '6px 0' }}>
                    <div style={{ width: `${(c.progress || 0) * 100}%` }} />
                  </div>
                  <div className="row" style={{ fontSize: 12 }}>
                    {c.due_date && <span className="muted">截止 {c.due_date}</span>}
                    {/* 上层状态由下层推导,不提供手动流转 */}
                    {!c.derived && dimension !== 'goal' && (
                      <>
                        {key !== 'done' && key !== 'doing' && <button className="ghost" onClick={() => move(c, 'doing')}>开始</button>}
                        {key === 'doing' && <button className="ghost" onClick={() => move(c, 'done')}>完成</button>}
                        {key === 'done' && <button className="ghost" onClick={() => move(c, 'backlog')}>退回</button>}
                      </>
                    )}
                    {dimension === 'week' && <button className="ghost" disabled={busy === c.id} onClick={() => genActions(c)}>AI 拆解待办</button>}
                    {dimension === 'month' && <button className="ghost" disabled={busy === c.id} onClick={() => decompose(c, '周任务')}>拆解为周任务</button>}
                    {dimension === 'sub' && <button className="ghost" disabled={busy === c.id} onClick={() => decompose(c, '月度进度规划')}>拆解为月度规划</button>}
                  </div>
                </div>
              ))}
              {board.columns[key].length === 0 && <p className="muted">空</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
