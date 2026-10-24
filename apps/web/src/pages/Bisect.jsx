import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export const DIMENSION_CN = { growth: '成长', career: '职业', health: '健康', finance: '财务', relationship: '关系' }

const Chevron = ({ open }) => (
  <span style={{ display: 'inline-block', width: 14, color: 'var(--muted)' }}>{open ? '▾' : '▸'}</span>
)

const GRAIN = { year: '年', month: '月', week: '周' }

export default function Goals() {
  const [goals, setGoals] = useState([])
  const [tasks, setTasks] = useState([])
  const [goalForm, setGoalForm] = useState({ title: '', description: '', dimension: 'growth', deadline: '' })
  const [taskForms, setTaskForms] = useState({})
  const [msg, setMsg] = useState('')
  const [genMsg, setGenMsg] = useState({})
  const [busy, setBusy] = useState(null)
  const [open, setOpen] = useState({}) // 默认全部收起
  const toggle = (k) => setOpen((o) => ({ ...o, [k]: !o[k] }))
  const isOpen = (k) => !!open[k]
  const Chevron = ({ k, label }) => (
    <span className="muted" style={{ cursor: 'pointer' }} onClick={() => toggle(k)}>
      {collapsed[k] ? '▸ ' : '▾ '}{label}
    </span>
  )

  const load = async () => {
    setGoals(await api.get('/api/goals'))
    setTasks(await api.get('/api/tasks'))
  }
  useEffect(() => { load().catch((e) => setMsg(e.message)) }, [])

  const addGoal = async (e) => {
    e.preventDefault()
    await api.post('/api/goals', { ...goalForm, deadline: goalForm.deadline || null })
    setGoalForm({ title: '', description: '', dimension: 'growth', deadline: '' })
    await load()
  }

  const addTask = async (goalId, parentId, granularity) => {
    const key = `${parentId || goalId}-${granularity}`
    const title = taskForms[key]
    if (!title) return
    await api.post('/api/tasks', { goal_id: goalId, parent_task_id: parentId || null, granularity, title })
    setTaskForms({ ...taskForms, [key]: '' })
    await load()
  }

  const genYearTasks = async (goalId) => {
    setGenMsg({ ...genMsg, [goalId]: 'AI 生成子目标中…' })
    try {
      const r = await api.post('/api/llm/generate-tasks', { goal_id: goalId, granularity: 'year' })
      for (const t of r.tasks) {
        await api.post('/api/tasks', {
          goal_id: goalId, granularity: 'year', title: t.title,
          priority: t.priority || 2, estimate_hours: t.estimate_hours || null,
        })
      }
      setGenMsg({ ...genMsg, [goalId]: r.degraded ? '⚠️ AI 不可用,已用模板生成子目标' : '✅ 子目标已生成,下一步:拆解为月度进度规划' })
      await load()
    } catch (ex) {
      setGenMsg({ ...genMsg, [goalId]: ex.message })
    }
  }

  const decompose = async (t) => {
    setBusy(t.id)
    setMsg('拆解中…')
    try {
      const r = await api.post(`/api/tasks/${t.id}/decompose`)
      const label = t.granularity === 'year' ? '月度进度规划' : '周任务'
      setMsg(r.degraded
        ? `⚠️ AI 不可用,已按模板生成 ${r.children.length} 条${label}`
        : `✅ 已生成 ${r.children.length} 条${label}`)
      await load()
    } catch (ex) {
      setMsg(ex.message)
    }
    setBusy(null)
  }

  const setStatus = async (taskId, status) => {
    await api.put(`/api/tasks/${taskId}`, { status })
    await load()
  }

  const delTask = async (taskId) => {
    if (!confirm('删除该任务(含其子任务)?')) return
    await api.del(`/api/tasks/${taskId}`)
    await load()
  }

  const childrenOf = (parentId) =>
    tasks
      .filter((t) => t.parent_task_id === parentId)
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || (a.due_date || '').localeCompare(b.due_date || ''))
  const yearTasksOf = (goalId) => tasks.filter((t) => t.goal_id === goalId && t.granularity === 'year' && !t.parent_task_id)

  const TaskRow = ({ t, indent = 0, canDecomposeTo, decomposeLabel, statusLabels }) => {
    const labels = statusLabels || { backlog: '待办', doing: '进行中', done: '完成' }
    return (
    <div className="list-item" style={{ marginLeft: indent }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="row">
          <span className={`badge ${t.status === 'done' ? 'green' : t.status === 'doing' ? '' : 'gray'}`}>
            {labels[t.status]}
          </span>
          <span>{t.title}</span>
          <span className="muted">完成度 {(t.progress * 100).toFixed(0)}%</span>
        </div>
        <div className="progress" style={{ margin: '6px 0', maxWidth: 420 }}><div style={{ width: `${t.progress * 100}%` }} /></div>
      </div>
      <div className="row">
        {t.status !== 'done' && (
          <button className="ghost" onClick={() => setStatus(t.id, t.status === 'backlog' ? 'doing' : 'done')}>
            {t.status === 'backlog' ? '开始' : '完成'}
          </button>
        )}
        {canDecomposeTo && (
          <button className="ghost" disabled={busy === t.id}
            onClick={() => decompose(t)}>
            {busy === t.id ? `⏳ 生成${decomposeLabel}…` : `拆解为${decomposeLabel}`}
          </button>
        )}
        <button className="danger" onClick={() => delTask(t.id)}>删</button>
      </div>
    </div>
  )
  }
  return (
    <div>
      <h2 className="page-title">🎯 目标</h2>

      <div className="card">
        <b>操作流程</b>
        <p className="muted" style={{ margin: '6px 0 0' }}>
          ① 创建目标 → ② AI 生成子目标 → ③ 子目标 <b>拆解为月度进度规划</b>(按月列出阶段成果与累计进度)→ ④ 每月规划 <b>拆解为周任务</b> → ⑤ 周任务在看板"AI 拆解待办"生成每日待办
        </p>
      </div>

      <form className="card row" onSubmit={addGoal}>
        <input placeholder="新目标,如:通过 PMP 认证" value={goalForm.title} required style={{ flex: 1, minWidth: 180 }}
          onChange={(e) => setGoalForm({ ...goalForm, title: e.target.value })} />
        <select value={goalForm.dimension} onChange={(e) => setGoalForm({ ...goalForm, dimension: e.target.value })}>
          {['growth', 'career', 'health', 'finance', 'relationship'].map((d) => <option key={d} value={d}>{DIMENSION_CN[d]}</option>)}
        </select>
        <input type="date" value={goalForm.deadline} onChange={(e) => setGoalForm({ ...goalForm, deadline: e.target.value })} />
        <button>添加目标</button>
      </form>
      {msg && <p className="muted">{msg}</p>}

      {goals.map((g) => {
        const gKey = `g-${g.id}`
        const years = yearTasksOf(g.id)
        return (
        <div className="card" key={g.id}>
          <div className="spread">
            <div style={{ cursor: 'pointer' }} onClick={() => toggle(gKey)}>
              <Chevron open={isOpen(gKey)} />
              <b style={{ fontSize: 15 }}>🎯 {g.title}</b>{' '}
              <span className="badge">{DIMENSION_CN[g.dimension] || g.dimension}</span>{' '}
              <span className="badge green">进度 {(g.progress * 100).toFixed(0)}%</span>{' '}
              <span className="muted">{years.length} 个子目标</span>
</div>
  )
}
