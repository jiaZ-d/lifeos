import React, { useEffect, useRef, useState } from 'react'
import { marked } from 'marked'
import Vditor from 'vditor'
import 'vditor/dist/index.css'
import { api } from '../api.js'

const Chevron = ({ open }) => (
  <span style={{ display: 'inline-block', width: 12, color: 'var(--muted)' }}>{open ? '▾' : '▸'}</span>
)

const ModeSwitch = ({ mode, setMode }) => (
  <div className="kb-mode-switch" role="group" aria-label="编辑模式">
    <button type="button" className={mode === 'edit' ? 'on' : ''} title="编辑(即时渲染,图片就地显示)" onClick={() => setMode('edit')}>
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>编辑
    </button>
    <button type="button" className={mode === 'split' ? 'on' : ''} title="分屏(边编辑边预览)" onClick={() => setMode('split')}>
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="16" rx="1"/><path d="M12 4v16"/></svg>分屏
    </button>
    <button type="button" className={mode === 'preview' ? 'on' : ''} title="预览" onClick={() => setMode('preview')}>
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z"/><circle cx="12" cy="12" r="3"/></svg>预览
    </button>
  </div>
)

const fmtTime = (iso) => {
  const d = new Date(iso)
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  if (d.toDateString() === now.toDateString()) return `${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}-${pad(d.getDate())}`
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export default function Knowledge() {
  const [tree, setTree] = useState([])
  const [recent, setRecent] = useState([])    // 最近更新的笔记
  const [openD, setOpenD] = useState({})      // domain expansion
  const [openF, setOpenF] = useState({})      // folder expansion
  const [note, setNote] = useState(null)      // currently open note {id,folder_id,title,content_md}
  const [editing, setEditing] = useState(false)
  const [newFolderId, setNewFolderId] = useState(null) // 新建模式:目标笔记本 id(null=非新建)
  const [draft, setDraft] = useState({ title: '', content_md: '' })
  const [msg, setMsg] = useState('')
  const [mode, setMode] = useState('edit')    // edit | split | preview
  const [modal, setModal] = useState(null)    // 页内弹窗: {kind:'input'|'confirm', ...}
  const [modalValue, setModalValue] = useState('')
  const editorRef = useRef(null)              // vditor 容器
  const vdInst = useRef(null)                 // vditor 实例
  const draftRef = useRef(draft)
  draftRef.current = draft

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

  const load = async () => {
    setTree(await api.get('/api/knowledge/tree'))
    api.get('/api/knowledge/recent').then(setRecent).catch(() => {})
  }
  useEffect(() => { load().catch((e) => setMsg(e.message)) }, [])

  const openNote = async (id) => {
    const n = await api.get(`/api/knowledge/notes/${id}`)
    setNewFolderId(null)
    setNote(n)
    setDraft({ title: n.title, content_md: n.content_md })
    setEditing(false)
    setMode('edit')
  }

  const saveNote = async () => {
    if (!draft.title.trim()) return setMsg('标题不能为空')
    // 编辑态优先取 vditor 实例当前值;初始化窗口期 getValue 可能抛错,回落到 input 回调同步的 draft
    let contentMd = draft.content_md
    try {
      if (vdInst.current && typeof vdInst.current.getValue === 'function') {
        contentMd = vdInst.current.getValue() || contentMd
      }
    } catch { /* vditor 未就绪,用 draft */ }
    try {
      if (newFolderId != null) {
        // 新建:直接在右侧编辑后保存创建
        const r = await api.post('/api/knowledge/notes', {
          folder_id: newFolderId, title: draft.title, content_md: contentMd,
        })
        setNewFolderId(null)
        await load()
        await openNote(r.id)
        setMsg('✅ 已创建')
      } else {
        await api.put(`/api/knowledge/notes/${note.id}`, {
          title: draft.title, content_md: contentMd,
        })
        setEditing(false)
        setNote({ ...note, title: draft.title, content_md: contentMd })
        await load()
        setMsg('✅ 已保存')
      }
    } catch (ex) { setMsg(ex.message) }
  }

  const addDomain = () =>
    askInput('新建领域', async (name) => {
      await api.post('/api/knowledge/domains', { name }); await load()
    }, '如:前端开发 / 健康 / 读书笔记')

  const addFolder = (domainId) =>
    askInput('新建笔记本', async (name) => {
      await api.post(`/api/knowledge/domains/${domainId}/folders`, { name }); await load()
    }, '笔记本名称')

  const addNote = (folderId) => {
    // 不弹窗:右侧直接进入新建编辑态
    setNewFolderId(folderId)
    setNote(null)
    setDraft({ title: '', content_md: '' })
    setEditing(true)
    setMode('edit')
    setMsg('')
  }

  const del = (kind, id, label) =>
    askConfirm(`确认删除${label}?(级联删除其下所有内容,不可恢复)`, async () => {
      await api.del(`/api/knowledge/${kind}/${id}`)
      if (note && kind === 'notes' && note.id === id) setNote(null)
      await load()
    })

  // 图片上传:vditor 工具栏 / 粘贴 / 拖拽统一入口,上传后返回 Markdown 文本
  const uploadImagesToMarkdown = async (files) => {
    const imgs = (files || []).filter((f) => f.type.startsWith('image/'))
    if (!imgs.length) return null
    setMsg('图片上传中…')
    const parts = []
    for (const f of imgs) {
      const ext = (f.type.split('/')[1] || 'png').replace('jpeg', 'jpg')
      const name = /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(f.name || '') ? f.name : `pasted.${ext}`
      const fd = new FormData()
      fd.append('file', f, name)
      try {
        const r = await api.postForm('/api/knowledge/upload-image', fd)
        parts.push(`![${r.url.split('/').pop()}](${r.url})`)
      } catch (ex) { setMsg(ex.message); return null }
    }
    setMsg(`✅ 已插入 ${parts.length} 张图片`)
    return parts.join('\n')
  }

  // 编辑态挂载 vditor:IR 即时渲染,编辑时图片/格式就地显示;切换模式重建
  useEffect(() => {
    const host = editorRef.current
    if (!editing || mode === 'preview' || !host) return
    const vd = new Vditor(host, {
      cdn: 'vditor',
      lang: 'zh_CN',
      mode: mode === 'split' ? 'sv' : 'ir',
      height: '100%',
      value: draftRef.current.content_md || '',
      cache: { enable: false },
      // sv(分屏)模式必须显式开启 both,否则只有编辑区没有实时预览
      preview: { mode: 'both', delay: 300 },
      upload: {
        handler: async (files) => {
          const md = await uploadImagesToMarkdown(files)
          if (md) vdInst.current?.insertValue(md + '\n')
          return null
        },
      },
      input: (v) => setDraft((d) => ({ ...d, content_md: v })),
    })
    vdInst.current = vd
    return () => {
      // vditor 4.x 无 destroy():清空挂载容器并复位样式(容器随 key 重建)
      vdInst.current = null
      host.innerHTML = ''
      host.className = 'kb-vditor'
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, mode])

  const preview = (md) => {
    return { __html: marked.parse(md || '', { breaks: true }) }
  }

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
          {recent.length > 0 && (
            <div className="kb-recent">
              <div className="muted" style={{ fontSize: 12, marginBottom: 2 }}>🕘 最近笔记</div>
              {recent.slice(0, 6).map((n) => (
                <div key={n.id} className="kb-recent-item" title={`${n.domain} / ${n.folder}`}
                  style={{ color: note?.id === n.id ? 'var(--primary)' : 'inherit' }}
                  onClick={() => openNote(n.id)}>
                  <span className="kb-recent-title">📄 {n.title}</span>
                  <span className="muted" style={{ fontSize: 11, flexShrink: 0 }}>{fmtTime(n.updated_at)}</span>
                </div>
              ))}
            </div>
          )}
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
          {!note && newFolderId == null && (
            <div className="card"><p className="muted">← 在左侧选择或创建一篇笔记</p></div>
          )}
          {(note || newFolderId != null) && (
            <div className="card" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
              <div className="spread" style={{ marginBottom: 8 }}>
                {editing ? (
                  <input value={draft.title} placeholder="笔记标题" style={{ flex: 1, fontWeight: 600 }}
                    onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
                ) : (
                  <b style={{ fontSize: 16 }}>{note.title}</b>
                )}
                <div className="row">
                  {editing ? (
                    <>
                      <ModeSwitch mode={mode} setMode={setMode} />
                      <button onClick={saveNote}>保存</button>
                      <button className="ghost" onClick={() => {
                        if (newFolderId != null) {
                          setNewFolderId(null); setEditing(false); setDraft({ title: '', content_md: '' })
                        } else {
                          setEditing(false); setDraft({ title: note.title, content_md: note.content_md })
                        }
                      }}>取消</button>
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
                mode === 'preview' ? (
                  <div className="md" style={{ flex: 1, overflow: 'auto' }} dangerouslySetInnerHTML={preview(draft.content_md)} />
                ) : (
                  <div key={mode} ref={editorRef} className="kb-vditor" style={{ flex: 1, minHeight: 420 }} />
                )
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
