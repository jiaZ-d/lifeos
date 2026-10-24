import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export const CATEGORIES = [
  ['work', '💼 工作'],
  ['routine', '🛏 生活作息'],
  ['diet', '🍚 饮食'],
  ['study', '📚 学习'],
  ['exercise', '🏃 锻炼'],
  ['social', '👥 社交'],
]

const EXTRA_TEMPLATES = {
  work: { minutes: 30 },
  routine: { sleep_hours: '' },
  diet: { meal: '午餐', health: 3 },
  study: { minutes: 30, subject: '' },
  exercise: { type: '跑步', minutes: 30, intensity: '中' },
  social: { occasion: '' },
}

export default function Records() {
  const [cat, setCat] = useState('work')
  const [entries, setEntries] = useState([])
  const [form, setForm] = useState({ title: '', content: '', mood: 3, tags: '' })
  const [extra, setExtra] = useState({ ...EXTRA_TEMPLATES.work })
  const [isPrivate, setIsPrivate] = useState(false)
  const [pin, setPin] = useState('')
  const [aiAllowed, setAiAllowed] = useState(true)
  const [msg, setMsg] = useState('')
  const [searchQ, setSearchQ] = useState('')
  const [searchResult, setSearchResult] = useState(null)
  const [file, setFile] = useState(null)

  const load = async () => {
    setEntries(await api.get(`/api/entries?category=${cat}&limit=50`))
  }
  useEffect(() => { load().catch((e) => setMsg(e.message)) }, [cat])

  const pickCat = (c) => {
    setCat(c)
    setExtra({ ...EXTRA_TEMPLATES[c] })
    setSearchResult(null)
  }

  const submit = async (e) => {
    e.preventDefault()
    setMsg('')
    try {
      const created = await api.post('/api/entries', {
        categories: [cat],
        title: form.title || null,
        content: form.content || null,
        mood: form.mood,
        tags: form.tags ? form.tags.split(/[,，\s]+/).filter(Boolean) : null,
        is_private: isPrivate,
        ai_allowed: aiAllowed,
        extra_json: extra,
        pin: isPrivate ? pin : null,
      })
      // P0-1: upload attachment if selected
      if (file) {
        const fd = new FormData()
        fd.append('file', file)
        const qs = isPrivate ? `?pin=${encodeURIComponent(pin)}` : ''
        await api.postForm(`/api/entries/${created.id}/attachments${qs}`, fd)
        setFile(null)
      }
      setForm({ title: '', content: '', mood: 3, tags: '' })
      setIsPrivate(false)
      setPin('')
      await load()
      setMsg('✅ 已保存')
    } catch (ex) {
      setMsg(ex.message)
    }
  }

  const unlock = async (id) => {
    const p = prompt('输入 PIN 解锁:')
    if (!p) return
    try {
      const e = await api.get(`/api/entries/unlock/${id}?pin=${encodeURIComponent(p)}`)
      alert(`标题:${e.title || '(无)'}\n内容:${e.content || '(无)'}\n心情:${e.mood ?? '-'}\n详情:${JSON.stringify(e.extra_json || {})}`)
    } catch (ex) {
      alert(ex.message)
    }
  }

  const search = async (e) => {
    e.preventDefault()
    if (!searchQ.trim()) { setSearchResult(null); return }
    const pin2 = prompt('搜索私密内容请输入 PIN(取消则只搜公开记录):')
    const r = await api.get(`/api/entries/search?q=${encodeURIComponent(searchQ)}${pin2 ? `&pin=${encodeURIComponent(pin2)}` : ''}`)
    setSearchResult([...r.results, ...r.private_hits])
  }

  const del = async (id) => {
    if (!confirm('删除这条记录?')) return
    await api.del(`/api/entries/${id}`)
    await load()
  }

  return (
    <div>
      <h2 className="page-title">📝 记录</h2>
      <div className="tabs">
        {CATEGORIES.map(([k, label]) => (
          <button key={k} className={cat === k ? 'active' : ''} onClick={() => pickCat(k)}>{label}</button>
        ))}
      </div>

      <form className="card" onSubmit={submit}>
        <div className="row" style={{ marginBottom: 10 }}>
          <input placeholder="标题(可空)" value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })} style={{ flex: 1 }} />
          <select value={form.mood} onChange={(e) => setForm({ ...form, mood: +e.target.value })}>
            {[1, 2, 3, 4, 5].map((m) => <option key={m} value={m}>心情 {m}</option>)}
          </select>
        </div>
        <textarea placeholder="记录内容…" value={form.content}
          onChange={(e) => setForm({ ...form, content: e.target.value })} />
        <div className="row" style={{ marginTop: 10 }}>
          <input placeholder="标签(空格分隔)" value={form.tags} style={{ width: 200 }}
            onChange={(e) => setForm({ ...form, tags: e.target.value })} />
          <span className="muted">| {cat} 专属:</span>
          {Object.entries(extra).map(([k, v]) => (
            <input key={k} placeholder={k} value={v} style={{ width: 90 }}
              onChange={(e) => setExtra({ ...extra, [k]: e.target.value })} />
          ))}
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <label className="row" style={{ gap: 4 }}>
            <input type="checkbox" checked={isPrivate} onChange={(e) => setIsPrivate(e.target.checked)} /> 🔒 私密
          </label>
          {isPrivate && (
            <input type="password" placeholder="PIN(≥6位)" value={pin} style={{ width: 130 }}
              onChange={(e) => setPin(e.target.value)} />
          )}
          <label className="row" style={{ gap: 4 }}>
            <input type="checkbox" checked={aiAllowed} onChange={(e) => setAiAllowed(e.target.checked)} /> 允许 AI 使用
          </label>
          <label className="btn ghost" style={{ cursor: 'pointer', fontSize: 12 }}>
            📎 附件
            <input type="file" style={{ display: 'none' }} onChange={(e) => setFile(e.target.files[0])} />
          </label>
          {file && <span className="muted">{file.name}</span>}
          <button type="submit">保存</button>
          {msg && <span className="muted">{msg}</span>}
        </div>
      </form>

      <form className="card row" onSubmit={search}>
        <input placeholder="全文搜索(中文≥3字效果最佳)" value={searchQ} style={{ flex: 1 }}
          onChange={(e) => setSearchQ(e.target.value)} />
        <button type="submit" className="ghost">搜索</button>
      </form>

      <div className="card">
        {(searchResult || entries).map((e) => (
          <div className="list-item" key={e.id}>
            <div>
              {e.is_private ? (
                <span className="row">🔒 <b>私密记录</b>
                  <button className="ghost" onClick={() => unlock(e.id)}>解锁查看</button>
                </span>
              ) : (
                <>
                  <b>{e.title || '(无标题)'}</b>
                  <div className="muted">{e.content}</div>
                  {e.tags?.length > 0 && <div className="row">{e.tags.map((t) => <span className="badge gray" key={t}>{t}</span>)}</div>}
                </>
              )}
            </div>
            <div className="row">
              <span className="muted">{new Date(e.created_at).toLocaleString('zh-CN')}</span>
              <button className="danger" onClick={() => del(e.id)}>删</button>
            </div>
          </div>
        ))}
        {(searchResult || entries).length === 0 && <p className="muted">暂无记录</p>}
      </div>
    </div>
  )
}
