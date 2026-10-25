import React, { useEffect, useRef, useState } from 'react'
import { marked } from 'marked'
import { api } from '../api.js'

const Chevron = ({ open }) => (
  <span style={{ display: 'inline-block', width: 12, color: 'var(--muted)' }}>{open ? '▾' : '▸'}</span>
)

export default function Knowledge() {
  const [tree, setTree] = useState([])
  const [openD, setOpenD] = useState({})      // domain expansion
  const [openF, setOpenF] = useState({})      // folder expansion
  const [note, setNote] = useState(null)      // currently open note {id,folder_id,title,content_md}
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ title: '', content_md: '' })
  const [msg, setMsg] = useState('')
  const [mode, setMode] = useState('edit')    // edit | preview | split
  const [modal, setModal] = useState(null)    // 页内弹窗: {kind:'input'|'confirm', ...}
  const [modalValue, setModalValue] = useState('')
  const taRef = useRef(null)

  const askInput = (title, onOk, placeholder = '') => {
    setModalValue('')
    setModal({ kind: 'input', title, okText: '确定', onOk, placeholder })
  }
  const askConfirm = (message, onOk) => {
    setModal({ kind: 'confirm', title: '确认删除', message, okText: '删除', onOk })
  }
  const submitModal = async () => {
    const m = modal
    if (!m) return
    if (m.kind === 'input' && !modalValue.trim()) { setMsg('名称不能为空'); return }
    setModal(null)
    try { await m.onOk(modalValue.trim()) } catch (ex) { setMsg(ex.message) }
  }

  const load = async () => setTree(await api.get('/api/knowledge/tree'))
  useEffect(() => { load().catch((e) => setMsg(e.message)) }, [])

  const openNote = async (id) => {
    const n = await api.get(`/api/knowledge/notes/${id}`)
    setNote(n)
    setDraft({ title: n.title, content_md: n.content_md })
    setEditing(false)
    setMode('edit')
  }

  const saveNote = async () => {
    if (!draft.title.trim()) return setMsg('标题不能为空')
    await api.put(`/api/knowledge/notes/${note.id}`, {
      title: draft.title, content_md: draft.content_md,
    })
    setEditing(false)
    setNote({ ...note, title: draft.title, content_md: draft.content_md })
    await load()
    setMsg('✅ 已保存')
  }

  const addDomain = () =>
    askInput('新建领域', async (name) => {
      await api.post('/api/knowledge/domains', { name }); await load()
    }, '如:前端开发 / 健康 / 读书笔记')

  const addFolder = (domainId) =>
    askInput('新建笔记本', async (name) => {
      await api.post(`/api/knowledge/domains/${domainId}/folders`, { name }); await load()
    }, '笔记本名称')

  const addNote = (folderId) =>
    askInput('新建笔记', async (title) => {
      const r = await api.post('/api/knowledge/notes', { folder_id: folderId, title, content_md: '# ' + title + '\n\n' })
      await load()
      await openNote(r.id)
    }, '笔记标题')

  const del = (kind, id, label) =>
    askConfirm(`确认删除${label}?(级联删除其下所有内容,不可恢复)`, async () => {
      await api.del(`/api/knowledge/${kind}/${id}`)
      if (note && kind === 'notes' && note.id === id) setNote(null)
      await load()
    })

  // 图片上传:插入 markdown 语法到光标处
  const insertImage = async (e) => {
    const file = e.target.files[0]
    e.target.value = ''
    if (!file) return
    setMsg('图片上传中…')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await api.postForm('/api/knowledge/upload-image', fd)
      const md = `![${file.name}](${r.url})`
      const ta = taRef.current
      if (ta) {
        const s = ta.selectionStart, epos = ta.selectionEnd
        const text = draft.content_md
        setDraft({ ...draft, content_md: text.slice(0, s) + md + '\n' + text.slice(epos) })
      } else {
        setDraft({ ...draft, content_md: draft.content_md + '\n' + md })
      }
      setMsg('✅ 图片已插入(保存后生效)')
    } catch (ex) { setMsg(ex.message) }
  }

  const preview = (md) => {
    return { __html: marked.parse(md || '', { breaks: true }) }
  }

  const Editor = () => (
    <textarea
      ref={taRef}
      className="kb-editor"
      value={draft.content_md}
      onChange={(e) => setDraft({ ...draft, content_md: e.target.value })}
    />
  )
  const Preview = () => <div className="kb-preview md" dangerouslySetInnerHTML={preview(draft.content_md)} />

  return (
    <div>
      <h2 className="page-title">📚 个人知识库</h2>
      {msg && <p className="muted">{msg}</p>}

      <div className="kb-layout">
        {/* left: tree */}
        <div className="card kb-tree">
          <div className="spread" style={{ marginBottom: 6 }}>
            <b>领域 / 笔记本 / 笔记</b>
            <button className="ghost" onClick={addDomain}>＋ 领域</button>
          </div>
          {tree.length === 0 && <p className="muted">还没有领域,点"＋ 领域"创建</p>}
          {tree.map((d) => (
            <div key={d.id} style={{ marginBottom: 4 }}>
              <div className="spread" style={{ cursor: 'pointer', padding: '2px 0' }}
                onClick={() => setOpenD((o) => ({ ...o, [d.id]: !o[d.id] }))}>
                <span><Chevron open={!!openD[d.id]} /><b>🗂 {d.name}</b>{' '}
                  <span className="muted">({d.folders.length})</span></span>
                <span className="row">
                  <button className="ghost" style={{ padding: '2px 8px', fontSize: 12 }}
                        onClick={(e) => { e.stopPropagation(); addFolder(d.id) }}>＋笔记本</button>
                  <button className="danger" style={{ padding: '2px 8px', fontSize: 12 }}
                    onClick={(e) => { e.stopPropagation(); del('domains', d.id, `领域「${d.name}」`) }}>删</button>
                </span>
              </div>
              {openD[d.id] && d.folders.map((f) => (
                <div key={f.id} style={{ marginLeft: 16 }}>
                  <div className="spread" style={{ cursor: 'pointer', padding: '2px 0' }}
                    onClick={() => setOpenF((o) => ({ ...o, [f.id]: !o[f.id] }))}>
                    <span><Chevron open={!!openF[f.id]} />📁 {f.name}{' '}
                      <span className="muted">({f.notes.length})</span></span>
                    <span className="row">
                      <button className="ghost" style={{ padding: '2px 8px', fontSize: 12 }}
                        onClick={(e) => { e.stopPropagation(); addNote(f.id) }}>＋笔记</button>
                      <button className="danger" style={{ padding: '2px 8px', fontSize: 12 }}
                        onClick={(e) => { e.stopPropagation(); del('folders', f.id, `笔记本「${f.name}」`) }}>删</button>
                    </span>
                  </div>
                  {openF[f.id] && f.notes.map((n) => (
                    <div className="list-item" key={n.id} style={{ marginLeft: 16, padding: '3px 0' }}>
                      <span style={{ cursor: 'pointer', color: note?.id === n.id ? 'var(--primary)' : 'inherit', fontWeight: note?.id === n.id ? 600 : 400 }}
                        onClick={() => openNote(n.id)}>📄 {n.title}</span>
                      <button className="tl-del" onClick={() => del('notes', n.id, `笔记「${n.title}」`)}>×</button>
                    </div>
                  ))}
                  {openF[f.id] && f.notes.length === 0 && (
                    <p className="muted" style={{ marginLeft: 28, fontSize: 12 }}>(空,点"＋笔记"创建)</p>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>

        {/* right: note editor / preview */}
        <div className="kb-main">
          {!note && (
            <div className="card"><p className="muted">← 在左侧选择或创建一篇笔记</p></div>
          )}
          {note && (
            <div className="card" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
              <div className="spread" style={{ marginBottom: 8 }}>
                {editing ? (
                  <input value={draft.title} style={{ flex: 1, fontWeight: 600 }}
                    onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
                ) : (
                  <b style={{ fontSize: 16 }}>{note.title}</b>
                )}
                <div className="row">
                  {editing ? (
                    <>
                      <label className="btn ghost" style={{ cursor: 'pointer' }}>🖼 插入图片
                        <input type="file" accept="image/*" style={{ display: 'none' }} onChange={insertImage} />
                      </label>
                      <select value={mode} onChange={(e) => setMode(e.target.value)}>
                        <option value="edit">编辑</option>
                        <option value="split">分屏</option>
                        <option value="preview">预览</option>
                      </select>
                      <button onClick={saveNote}>保存</button>
                      <button className="ghost" onClick={() => { setEditing(false); setDraft({ title: note.title, content_md: note.content_md }) }}>取消</button>
                    </>
                  ) : (
                    <>
                      <span className="muted">更新于 {new Date(note.updated_at).toLocaleString('zh-CN')}</span>
                      <button onClick={() => setEditing(true)}>✏️ 编辑</button>
                    </>
                  )}
                </div>
              </div>
              {editing ? (
                <div style={{ flex: 1, display: 'flex', gap: 10, minHeight: 400 }}>
                  {mode !== 'preview' && <Editor />}
                  {mode !== 'edit' && <div style={{ flex: 1, overflow: 'auto' }}><Preview /></div>}
                </div>
              ) : (
                <div className="md" style={{ overflow: 'auto' }} dangerouslySetInnerHTML={preview(note.content_md)} />
              )}
            </div>
          )}
        </div>
      </div>

      {modal && (
        <div className="kb-modal-mask" onClick={() => setModal(null)}>
          <div className="card kb-modal" onClick={(e) => e.stopPropagation()}>
            <b>{modal.title}</b>
            {modal.kind === 'input' ? (
              <input autoFocus value={modalValue} placeholder={modal.placeholder}
                onChange={(e) => setModalValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && submitModal()} />
            ) : (
              <p className="muted" style={{ margin: 0 }}>{modal.message}</p>
            )}
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              <button className="ghost" onClick={() => setModal(null)}>取消</button>
              <button className={modal.kind === 'confirm' ? 'danger' : ''}
                onClick={submitModal}>{modal.okText}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
