import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

const VIEWS = [['day', '日'], ['week', '周'], ['month', '月'], ['year', '年']]
const REPORT_VIEWS = { week: '周报', month: '月报', year: '年报' }

const CAT_META = {
  work: { icon: '💼', label: '工作', dot: '●' },
  routine: { icon: '🛏', label: '作息', dot: '●' },
  diet: { icon: '🍚', label: '饮食', dot: '●' },
  study: { icon: '📚', label: '学习', dot: '●' },
  exercise: { icon: '🏃', label: '锻炼', dot: '●' },
  social: { icon: '👥', label: '社交', dot: '●' },
}
const MOOD_FACES = { 1: '😞', 2: '😕', 3: '😐', 4: '🙂', 5: '😄' }

function periodKeyOf(k, view) {
  // convert anchor date -> period key for jump (server also returns keys; we use labels)
  return k
}

function isoWeekDate(year, week) {
  const jan4 = new Date(Date.UTC(year, 0, 4))
  const day = jan4.getUTCDay() || 7
  const monday = new Date(jan4)
  monday.setUTCDate(jan4.getUTCDate() - day + 1 + (week - 1) * 7)
  return monday.toISOString().slice(0, 10)
}

function jumpAnchor(key, view) {
  if (view === 'day') return key
  if (view === 'week') return isoWeekDate(+key.slice(0, 4), +key.split('W')[1])
  if (view === 'month') return `${key}-01`
  return `${key}-06-01`
}

export default function Timeline() {
  const [view, setView] = useState('day')
  const [anchor, setAnchor] = useState(new Date().toISOString().slice(0, 10))
  const [data, setData] = useState(null)
  const [report, setReport] = useState({ exists: false, content_md: '', ai_generated: true })
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [msg, setMsg] = useState('')

  const [collapsed, setCollapsed] = useState({ todos: true, entries: true })
  const toggleSection = (k) => setCollapsed((c) => ({ ...c, [k]: !c[k] }))

  const canReport = view in REPORT_VIEWS

  const load = async () => {
    const d = await api.get(`/api/timeline?view=${view}&date=${anchor}`)
    setData(d)
    if (canReport) {
      setReport(await api.get(`/api/timeline/reports/${view}/${encodeURIComponent(d.period_key)}`))
    } else {
      setReport({ exists: false, content_md: '', ai_generated: true })
    }
    setEditing(false)
    setMsg('')
  }
  useEffect(() => { load().catch(console.error) }, [view, anchor])

  const shift = (dir) => setAnchor(dir < 0 ? data.prev : data.next)

  const genReport = async () => {
    setMsg('AI 生成中…')
    try {
      const r = await api.post('/api/timeline/reports/generate', {
        period_type: view, period_key: data.period_key,
      })
      setReport({ exists: true, content_md: r.content_md, ai_generated: true })
      setMsg(r.degraded ? '⚠️ AI 不可用,已用模板生成' : '✅ 已生成,可直接编辑')
    } catch (ex) {
      setMsg(ex.message)
    }
  }

  const saveEdit = async () => {
    await api.put(`/api/timeline/reports/${view}/${encodeURIComponent(data.period_key)}`, { content_md: draft })
    setReport({ exists: true, content_md: draft, ai_generated: false })
    setEditing(false)
    setMsg('✅ 修改已保存')
  }

  if (!data) return <p className="muted">加载中…</p>

  const moodCount = data.entries.filter((e) => e.mood).length
  const avgMood = moodCount
    ? (data.entries.filter((e) => e.mood).reduce((s, e) => s + e.mood, 0) / moodCount).toFixed(1)
    : '—'

  return (
    <div>
      <h2 className="page-title">🕐 时间轴</h2>

      {/* controls */}
      <div className="row spread" style={{ marginBottom: 16 }}>
        <div className="tl-tabs">
          {VIEWS.map(([k, label]) => (
            <button key={k} className={view === k ? 'active' : ''}
              onClick={() => { setView(k); setAnchor(new Date().toISOString().slice(0, 10)) }}>
              {label}
            </button>
          ))}
        </div>
        <div className="tl-nav">
          <button onClick={() => shift(-1)} title="上一期">←</button>
          <span className="tl-range">{data.range[0]} ~ {data.range[1]}</span>
          <button onClick={() => shift(1)} title="下一期">→</button>
        </div>
      </div>

      {/* hero period card */}
      <div className="card tl-hero">
        <div className="tl-key">{data.period_key}</div>
        <div className="tl-sub">这一{VIEWS.find(([k]) => k === view)[1]}你共留下 {data.entries.length} 条记录</div>
        <div className="tl-stats">
          <div className="tl-stat"><div className="n">{data.entries.length}</div><div className="l">记录</div></div>
          <div className="tl-stat"><div className="n">{new Set(data.entries.filter(e => !e.is_private).map(e => e.primary_category)).size}</div><div className="l">覆盖分类</div></div>
          <div className="tl-stat"><div className="n">{avgMood}</div><div className="l">平均心情</div></div>
        </div>
      </div>

      {/* period strip */}
      <div className="tl-strip">
        {data.periods.map((p) => (
          <div
            key={p.key}
            className={`tl-chip ${p.current ? 'current' : ''} ${p.count === 0 ? 'has-none' : ''}`}
            onClick={() => setAnchor(jumpAnchor(p.key, view))}
            title={p.count > 0 ? `${p.count} 条记录` : '无记录'}
          >
            <span className="tl-chip-count">{p.count}</span>
            {p.label}
          </div>
        ))}
      </div>

      {/* day view: summary on top */}
      {view === 'day' && (
        <div className="card tl-report" style={{ marginBottom: 14 }}>
          <div className="tl-report-head">
            <span className="t">🌙 每日小结 · {data.period_key}</span>
            {data.summary && (
              <span className={`ai-flag ${data.summary.ai_generated ? '' : 'edited'}`}>
                {data.summary.ai_generated ? 'AI 生成' : '已人工修改'}
              </span>
            )}
          </div>
          <div className="tl-report-body">
            {data.summary
              ? <div className="md">{data.summary.content_md}</div>
              : <p className="muted">该日没有小结(每天 01:00 会自动生成前一日的;也可在今日页手动生成)</p>}
          </div>
        </div>
      )}

      {/* day view: todos and records in separate sections */}
      {view === 'day' ? (
        <>
          <div className="card" style={{ minHeight: 60 }}>
            <div className="spread" style={{ cursor: 'pointer' }} onClick={() => toggleSection('todos')}>
              <b>✅ 待办({data.todos.length})</b>
              <span className="muted">{collapsed.todos ? '▸ 展开' : '▾ 收起'}</span>
            </div>
            {!collapsed.todos && (
            <div className="tl-list" style={{ marginTop: 8 }}>
              {data.todos.map((t) => (
                <div className="tl-item" key={'t' + t.id}>
                  <div className="tl-dot" style={{ borderColor: t.status === 'done' ? '#2f9e6e' : '#c9cfe4', color: t.status === 'done' ? '#2f9e6e' : 'var(--muted)', fontWeight: 700 }}>
                    {t.status === 'done' ? '✓' : '○'}
                  </div>
                  <div className="tl-title" style={t.status === 'done' ? { textDecoration: 'line-through', color: 'var(--muted)' } : {}}>
                    {t.title}{t.status === 'debt' && <span className="badge red" style={{ marginLeft: 8 }}>欠账</span>}
                  </div>
                </div>
              ))}
              {data.todos.length === 0 && <p className="muted">当天没有待办</p>}
            </div>
            )}
          </div>
          <div className="card" style={{ minHeight: 60 }}>
            <div className="spread" style={{ cursor: 'pointer' }} onClick={() => toggleSection('entries')}>
              <b>📝 记录({data.entries.length})</b>
              <span className="muted">{collapsed.entries ? '▸ 展开' : '▾ 收起'}</span>
            </div>
            {!collapsed.entries && (
            <div className="tl-list" style={{ marginTop: 8 }}>
              {data.entries.map((e) => {
                const cat = CAT_META[e.primary_category] || { icon: '📌' }
                return (
                  <div className={`tl-item cat-${e.primary_category}`} key={e.id}>
                    <div className="tl-dot">{cat.icon}</div>
                    <div className="tl-time">{new Date(e.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      {e.mood != null && !e.is_private && <span className="tl-mood" style={{ marginLeft: 8 }}>{MOOD_FACES[e.mood] || ''} {e.mood}/5</span>}
                    </div>
                    {e.is_private ? (
                      <div className="tl-title tl-lock">🔒 私密记录 · 解锁后可见</div>
                    ) : (
                      <div className="tl-title">{e.title}</div>
                    )}
                  </div>
                )
              })}
              {data.entries.length === 0 && <p className="muted">当天没有记录</p>}
            </div>
            )}
          </div>
        </>
      ) : null}

      {/* vertical timeline entries (week/month/year views) */}
      {view !== 'day' && (
      <div className="card" style={{ minHeight: 120 }}>
        <div className="tl-list">
          {data.entries.map((e) => {
            const cat = CAT_META[e.primary_category] || { icon: '📌', label: e.primary_category }
            return (
              <div className={`tl-item cat-${e.primary_category}`} key={e.id}>
                <div className="tl-dot">{cat.icon}</div>
                <div className="tl-time">{new Date(e.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                  {e.mood != null && !e.is_private && <span className="tl-mood" style={{ marginLeft: 8 }}>{MOOD_FACES[e.mood] || ''} {e.mood}/5</span>}
                </div>
                {e.is_private ? (
                  <div className="tl-title tl-lock">🔒 私密记录 · 解锁后可见</div>
                ) : (
                  <>
                    <div className="tl-title">{e.title}</div>
                    {(e.categories || []).length > 0 && (
                      <div className="tl-cats">
                        {e.categories.map((c) => (
                          <span key={c} className={`c-${c}`}>{CAT_META[c]?.label || c}</span>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            )
          })}
          {data.entries.length === 0 && (
            <div style={{ padding: '20px 0', color: 'var(--muted)', fontSize: 14 }}>
              这段时期还没有记录,去 📝 记录页写点什么吧
            </div>
          )}
        </div>
      </div>
      )}

      {/* periodic report */}
      {canReport && (
        <div className="card tl-report" style={{ marginTop: 4 }}>
          <div className="tl-report-head">
            <div>
              <span className="t">📄 {REPORT_VIEWS[view]} · {data.period_key}</span>
              {report.exists && (
                <span className={`ai-flag ${report.ai_generated ? '' : 'edited'}`} style={{ marginLeft: 10 }}>
                  {report.ai_generated ? 'AI 生成' : '已人工修改'}
                </span>
              )}
            </div>
            <div className="row">
              {!editing && (
                <>
                  <button className="ghost" onClick={genReport}>{report.exists ? '重新生成' : '✨ AI 生成'}</button>
                  {report.exists && <button onClick={() => { setDraft(report.content_md); setEditing(true) }}>编辑</button>}
                </>
              )}
            </div>
          </div>
          <div className="tl-report-body">
            {editing ? (
              <>
                <textarea value={draft} onChange={(e) => setDraft(e.target.value)} />
                <div className="row" style={{ marginTop: 10 }}>
                  <button onClick={saveEdit}>保存修改</button>
                  <button className="ghost" onClick={() => setEditing(false)}>取消</button>
                  <span className="muted">保存后标记为"已人工修改",重新生成会覆盖</span>
                </div>
              </>
            ) : report.exists ? (
              <div className="md">{report.content_md}</div>
            ) : (
              <p className="muted">还没有{REPORT_VIEWS[view]},点击右上角「✨ AI 生成」基于这段时间的记录自动撰写,生成后可自由编辑。</p>
            )}
            {msg && <p className="muted" style={{ marginTop: 8 }}>{msg}</p>}
          </div>
        </div>
      )}
    </div>
  )
}
