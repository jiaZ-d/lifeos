import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

const HORIZONS = [1, 3, 5, 10, 20]

const DIMENSION_CN = { growth: '成长', career: '职业', health: '健康', finance: '财务', relationship: '关系' }

function Radar({ report }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!ref.current || !report?.radar || Object.keys(report.radar).length === 0) return
    let chart
    import('echarts').then((echarts) => {
      chart = echarts.init(ref.current)
      const dims = Object.keys(report.radar)
      chart.setOption({
        radar: { indicator: dims.map((d) => ({ name: DIMENSION_CN[d] || d, max: 10 })) },
        series: [{
          type: 'radar',
          data: [
            { name: '现状', value: dims.map((d) => report.radar[d]?.[0] ?? 0), areaStyle: { opacity: 0.2 } },
            { name: `推演后`, value: dims.map((d) => report.radar[d]?.[1] ?? 0), areaStyle: { opacity: 0.2 } },
          ],
        }],
        legend: {},
      })
    })
    return () => chart?.dispose()
  }, [report])
  return <div ref={ref} className="chart" />
}

export default function Projections() {
  const [history, setHistory] = useState([])
  const [latest, setLatest] = useState(null)
  const [form, setForm] = useState({
    horizon_years: 10,
    health: 5, finance: 5, career: 5, relationship: 5, growth: 5,
    society_trend: '', industry: '', role: '', industry_years: '', use_personal_data: true,
  })
  const [busy, setBusy] = useState(false)
  const [suggestions, setSuggestions] = useState(null)
  const [suggBusy, setSuggBusy] = useState(false)
  const [applied, setApplied] = useState([])
  const [applying, setApplying] = useState(null) // title currently being applied
  const [existingGoalTitles, setExistingGoalTitles] = useState(new Set())

  const load = async () => {
    const h = await api.get('/api/projections')
    setHistory(h)
    setLatest(h[0] || null)
    // restore persisted suggestions + applied state after refresh
    if (h[0]?.suggestions?.length) {
      setSuggestions({ suggestions: h[0].suggestions, degraded: false, persisted: true })
    }
    try {
      const goals = await api.get('/api/goals')
      setExistingGoalTitles(new Set(goals.map((g) => g.title)))
    } catch {}
    return h[0] || null
  }
  useEffect(() => { load().catch(console.error) }, [])

  const gen = async () => {
    setBusy(true)
    setSuggestions(null)
    setApplied([])
    try {
      const body = {
        horizon_years: +form.horizon_years,
        questionnaire: {
          health: +form.health, finance: +form.finance, career: +form.career,
          relationship: +form.relationship, growth: +form.growth,
        },
        society_trend: form.society_trend || null,
        industry: form.industry || null,
        role: form.role || null,
        industry_years: form.industry_years ? +form.industry_years : null,
        use_personal_data: form.use_personal_data,
      }
      const p = await api.post('/api/projections', body)
      await load()
      setLatest((prev) => p.report ? { ...prev, ...p, report: p.report } : prev)
      // 推演完成后自动拉取目标建议(需求 #2)
      const s = await api.post(`/api/projections/${p.id}/suggest-goals`, { horizon_years: +form.horizon_years })
      setSuggestions(s)
    } catch (ex) {
      alert(ex.message)
    }
    setBusy(false)
  }

  const loadSuggestions = async () => {
    if (!latest) return
    setSuggBusy(true)
    try {
      const s = await api.post(`/api/projections/${latest.id}/suggest-goals`, {
        horizon_years: latest.horizon_years || +form.horizon_years,
      })
      setSuggestions(s)
    } catch (ex) {
      alert(ex.message)
    }
    setSuggBusy(false)
  }

  const applySuggestion = async (s) => {
    setApplying(s.title)
    try {
      const r = await api.post('/api/projections/apply-suggestion', {
        title: s.title, description: s.description, dimension: s.dimension, with_tasks: true,
      })
      setApplied([...applied, s.title])
      setExistingGoalTitles(new Set([...existingGoalTitles, s.title]))
      alert(
        r.degraded
          ? `⚠️ 目标「${s.title}」已创建(AI 不可用,仅生成年度任务模板,可在目标页手动/逐级拆解)`
          : `✅ 目标「${s.title}」已创建,并逐级生成 ${r.tasks_created} 个任务(年→月→周)`
      )
    } catch (ex) {
      alert(ex.message)
    }
    setApplying(null)
  }

  const h = latest?.horizon_years || +form.horizon_years
  const rangeLabel = latest ? `${h} 年` : ''

  return (
    <div>
      <h2 className="page-title">🔮 未来推演</h2>
      <div className="disclaimer">⚠️ AI 生成内容,仅供参考,不构成任何投资、职业或医疗建议。</div>

      <div className="card">
        <b>推演输入</b>
        <div className="row" style={{ marginTop: 10 }}>
          <span className="muted">推演年数:</span>
          <div className="tl-tabs" style={{ marginBottom: 0 }}>
            {HORIZONS.map((y) => (
              <button key={y} className={+form.horizon_years === y ? 'active' : ''}
                onClick={() => setForm({ ...form, horizon_years: y })}>{y} 年</button>
            ))}
          </div>
          <label className="row" style={{ gap: 4 }}>
            <input type="checkbox" checked={form.use_personal_data}
              onChange={(e) => setForm({ ...form, use_personal_data: e.target.checked })} />
            参考我的记录与目标
          </label>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          {['health', 'finance', 'career', 'relationship', 'growth'].map((d) => (
            <label key={d} className="row" style={{ gap: 4 }}>
              {DIMENSION_CN[d]}
              <select value={form[d]} onChange={(e) => setForm({ ...form, [d]: e.target.value })}>
                {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => <option key={n}>{n}</option>)}
              </select>
            </label>
          ))}
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <input placeholder="所在行业,如:互联网" value={form.industry} style={{ width: 150 }}
            onChange={(e) => setForm({ ...form, industry: e.target.value })} />
          <input placeholder="岗位" value={form.role} style={{ width: 120 }}
            onChange={(e) => setForm({ ...form, role: e.target.value })} />
          <input placeholder="工作年限" type="number" value={form.industry_years} style={{ width: 100 }}
            onChange={(e) => setForm({ ...form, industry_years: e.target.value })} />
          <input placeholder="社会趋势假设(留空则由 AI 判断)" value={form.society_trend} style={{ flex: 1 }}
            onChange={(e) => setForm({ ...form, society_trend: e.target.value })} />
          <button onClick={gen} disabled={busy}>{busy ? '推演中…' : `生成 ${form.horizon_years} 年推演`}</button>
        </div>
        <p className="muted" style={{ marginTop: 6 }}>✅ 已勾选"参考我的记录与目标"时,你在 🎯 目标页设定的目标会作为推演参考项,评估其现状与可达性。</p>
      </div>

      {latest && (
        <div className="card">
          <div className="spread">
            <b>{rangeLabel}推演 · {new Date(latest.created_at).toLocaleString('zh-CN')}</b>
            <span className={`badge ${latest.confidence === 'low' ? 'red' : 'green'}`}>
              置信度:{latest.confidence || 'medium'}{latest.cold_start ? '(数据不足)' : ''}
            </span>
          </div>
          <Radar report={latest.report} />
          {latest.input?.referenced_goals?.length > 0 && (
            <p className="muted">本次推演参考的目标:{latest.input.referenced_goals.join('、')}</p>
          )}
          <div style={{ marginTop: 10 }}>
            <b>维持现状的{rangeLabel}后</b>
            <p style={{ whiteSpace: 'pre-wrap' }}>{latest.report.maintained}</p>
            <b>坚持目标的{rangeLabel}后</b>
            <p style={{ whiteSpace: 'pre-wrap' }}>{latest.report.improved}</p>
            {latest.report.milestones?.length > 0 && (
              <>
                <b>里程碑</b>
                <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse', marginTop: 6 }}>
                  <thead><tr className="muted"><th style={{ textAlign: 'left' }}>时间</th><th style={{ textAlign: 'left' }}>个人线</th><th style={{ textAlign: 'left' }}>行业线</th></tr></thead>
                  <tbody>
                    {latest.report.milestones.map((m, i) => (
                      <tr key={i} style={{ borderTop: '1px solid #e3e7f0' }}>
                        <td style={{ padding: 6 }}>{m.year}</td><td>{m.personal}</td><td>{m.industry}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            {latest.report.key_variables?.length > 0 && (
              <>
                <b>关键变量</b>
                <div className="row" style={{ margin: '6px 0' }}>
                  {latest.report.key_variables.map((v, i) => <span className="badge" key={i}>{v}</span>)}
                </div>
              </>
            )}
            <b>外部趋势假设</b>
            <p className="muted" style={{ whiteSpace: 'pre-wrap' }}>
              社会:{latest.report.external_trends?.society}{'\n'}行业:{latest.report.external_trends?.industry}
            </p>
          </div>
        </div>
      )}

      {/* 目标建议(需求 #2) */}
      {latest && (
        <div className="card">
          <div className="spread">
            <b>💡 建议你设定的目标</b>
            <button className="ghost" onClick={loadSuggestions} disabled={suggBusy}>
              {suggBusy ? '生成建议中…' : suggestions ? '重新生成建议' : '基于本次推演生成建议'}
            </button>
          </div>
          {!suggestions && <p className="muted">点击右上角,AI 会基于推演结果建议你应当设定哪些目标;确认后自动创建目标并逐级生成任务计划。</p>}
          {suggestions?.degraded && <p className="muted">⚠️ AI 不可用,以下为基于关键变量的模板建议</p>}
          {suggestions && suggestions.suggestions?.length === 0 && <p className="muted">未生成建议,请重试。</p>}
          {suggestions?.suggestions?.map((s, i) => (
            <div className="list-item" key={i}>
              <div style={{ flex: 1 }}>
                <b>{s.title}</b> <span className="badge">{s.dimension}</span>
                <div className="muted">{s.description}</div>
              </div>
              <div className="row">
                {applied.includes(s.title) || existingGoalTitles.has(s.title)
                  ? <span className="badge green">已创建 ✓</span>
                  : <button disabled={applying !== null}
                      onClick={() => applySuggestion(s)}>
                      {applying === s.title ? '⏳ 生成中…(创建目标并逐级拆分任务,约需十几秒)' : '采纳并生成计划'}
                    </button>}
              </div>
            </div>
          ))}
        </div>
      )}

      {history.length > 0 && (
        <div className="card">
          <b>历史推演对比({history.length} 份)</b>
          {history.map((h2) => (
            <div className="list-item" key={h2.id}>
              <span className="muted">{new Date(h2.created_at).toLocaleString('zh-CN')}</span>
              <span className="badge gray">{h2.horizon_years || 10} 年</span>
              <span className={`badge ${h2.confidence === 'low' ? 'red' : 'green'}`}>{h2.confidence || 'medium'}</span>
              <button className="ghost" onClick={() => setLatest(h2)}>查看</button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
