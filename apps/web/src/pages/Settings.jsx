import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { CATEGORIES } from './Records.jsx'

export default function Settings() {
  const [privacy, setPrivacy] = useState([])
  const [pin, setPin] = useState({ old: '', new1: '', new2: '' })
  const [recovery, setRecovery] = useState('')
  const [pinStatus, setPinStatus] = useState({ exists: false, recovery_enabled: false, is_admin: false })
  const [apiKey, setApiKey] = useState('')
  const [keyMasked, setKeyMasked] = useState('')
  const [keyRevealed, setKeyRevealed] = useState(false)
  const [llmCfg, setLlmCfg] = useState({ base_url: '', model: '', thinking: 'default' })
  const [models, setModels] = useState([])
  const [modelSource, setModelSource] = useState('preset')
  const [customModel, setCustomModel] = useState(false)
  const [msg, setMsg] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)
  const [currentUserId, setCurrentUserId] = useState(null)
  const [users, setUsers] = useState(null)

  const load = async () => {
    setPrivacy(await api.get('/api/entries/privacy'))
    setPinStatus(await api.get('/api/auth/pin/status'))
    const me = await api.get('/api/auth/me')
    setIsAdmin(me.is_admin)
    setCurrentUserId(me.user_id)
    if (me.is_admin) setUsers(await api.get('/api/auth/users'))
    const cfg = await api.get('/api/llm/config')
    setLlmCfg({ base_url: cfg.base_url, model: cfg.model, thinking: cfg.thinking || 'default' })
    setKeyMasked(cfg.api_key_masked || '')
    if (cfg.has_api_key) setMsg('已配置 API Key')
    // model list: provider listing if available, else presets
    try {
      const m = await api.get('/api/llm/models')
      setModels(m.models || [])
      setModelSource(m.source || 'preset')
      if (cfg.model && !(m.models || []).includes(cfg.model)) setCustomModel(true)
    } catch {
      setModels(['glm-5.3-flash'])
    }
  }
  useEffect(() => { load().catch(console.error) }, [])

  const setupPin = async () => {
    if (pin.new1 !== pin.new2) return setMsg('两次新 PIN 不一致')
    if (pin.new1.length < 6) return setMsg('PIN 至少 6 位')
    try {
      if (pinStatus.exists) {
        if (!pin.old) return setMsg('请输入当前 PIN')
        await api.put('/api/auth/pin', { old_pin: pin.old, new_pin: pin.new1 })
      } else {
        await api.post('/api/auth/pin/setup', { pin: pin.new1 })
      }
      const usedRecovery = !!recovery
      if (usedRecovery) {
        await api.post('/api/auth/pin/recovery-wrap', { pin: pin.new1, recovery_passphrase: recovery })
        setMsg('✅ PIN 已保存,且已启用管理员恢复(请记好恢复口令)')
      } else {
        setMsg('✅ PIN 已保存')
      }
      setPin({ old: '', new1: '', new2: '' })
      setRecovery('')
      await load()
    } catch (ex) {
      setMsg(ex.message)
    }
  }

  const setPrivacyOpt = async (category, field, value) => {
    await api.put('/api/entries/privacy', { category, [field]: value })
    await load()
  }

  const revealKey = async () => {
    if (keyRevealed) { setKeyRevealed(false); setApiKey(''); return }
    try {
      const r = await api.get('/api/llm/config/reveal')
      setApiKey(r.api_key)
      setKeyRevealed(true)
    } catch (ex) {
      setMsg(ex.message)
    }
  }

  const saveKey = async () => {
    await api.put('/api/llm/config', {
      api_key: apiKey || null,
      base_url: llmCfg.base_url || null,
      model: llmCfg.model || null,
      thinking: llmCfg.thinking || 'default',
    })
    setMsg('✅ LLM 配置已保存(持久化到本机 config/llm_config.json)')
    await load()
  }

  const testLlm = async () => {
    setMsg('连通性测试中…')
    const r = await api.post('/api/llm/test')
    setMsg(r.ok ? '✅ 连接成功,AI 服务可用!' : `❌ 连接失败:${r.error}`)
  }

  const reloadModels = async () => {
    setMsg('获取模型列表中…')
    try {
      const m = await api.get('/api/llm/models')
      setModels(m.models || [])
      setModelSource(m.source || 'preset')
      setCustomModel(false)
      setMsg(m.source === 'provider' ? `✅ 已从服务商获取 ${m.models.length} 个模型` : '使用预设模型列表(未配置 Key 或服务商不支持列表接口)')
    } catch (ex) {
      setMsg(ex.message)
    }
  }

  const exportData = async () => {
    const r = await api.post('/api/stats/export')
    setMsg(`✅ 备份已生成:${r.file}`)
  }

  const importData = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    const conflict = prompt('冲突策略:skip / overwrite / duplicate', 'skip')
    const fd = new FormData()
    fd.append('file', file)
    const r = await api.postForm(`/api/stats/import?conflict=${conflict}`, fd)
    setMsg(`✅ 导入 ${r.imported} 条,跳过 ${r.skipped} 条`)
  }

  return (
    <div>
      <h2 className="page-title">⚙️ 设置</h2>

      <div className="card">
        <b>🔒 PIN 与私密数据加密</b>
        <p className="muted">
          {pinStatus.exists
            ? 'PIN 已设置。修改需输入当前 PIN;私密数据在改 PIN 后依然可解密。'
            : 'PIN 用于加密私密记录。'}
          {pinStatus.recovery_enabled
            ? ' 管理员恢复已启用:忘记 PIN 可联系管理员找回。'
            : ' 请牢记 PIN:未启用管理员恢复时,忘记将无法解密私密记录。'}
        </p>
        <div className="row" style={{ marginTop: 8 }}>
          {pinStatus.exists && (
            <input type="password" placeholder="当前 PIN" value={pin.old} style={{ width: 150 }}
              onChange={(e) => setPin({ ...pin, old: e.target.value })} />
          )}
          <input type="password" placeholder={pinStatus.exists ? '新 PIN(≥6位)' : '设置 PIN(≥6位)'} value={pin.new1} style={{ width: 150 }}
            onChange={(e) => setPin({ ...pin, new1: e.target.value })} />
          <input type="password" placeholder="确认新 PIN" value={pin.new2} style={{ width: 150 }}
            onChange={(e) => setPin({ ...pin, new2: e.target.value })} />
          <button onClick={setupPin}>保存</button>
          {pinStatus.recovery_enabled && <span className="badge green">管理员恢复已启用</span>}
        </div>
        {isAdmin && (
          <div className="row" style={{ marginTop: 8 }}>
            <span className="muted">👑 管理员恢复(仅管理员可见):</span>
            <input type="password"
              placeholder={pinStatus.recovery_enabled ? '新的恢复口令(重新设置)' : '恢复口令(可选,≥8位)'}
              value={recovery} style={{ width: 220 }}
              onChange={(e) => setRecovery(e.target.value)} />
            {pinStatus.recovery_enabled ? (
              <button className="danger" onClick={async () => {
                if (!confirm('确认退出管理员恢复?退出后忘记 PIN 将无法找回私密数据!')) return
                await api.del('/api/auth/pin/recovery-wrap')
                setMsg('已退出管理员恢复(恢复包装已删除)')
                await load()
              }}>关闭管理员恢复</button>
            ) : (
              <span className="muted">填写恢复口令并保存即启用;启用后可帮助任何用户找回忘记的 PIN</span>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <b>🙈 分类隐私与 AI 参与范围</b>
        <p className="muted">未勾选"AI 可用"的分类不会进入任何 LLM 推演/总结(两级授权取交集)。</p>
        {CATEGORIES.map(([k, label]) => {
          const p = privacy.find((x) => x.category === k) || {}
          return (
            <div className="list-item" key={k}>
              <span>{label}</span>
              <div className="row">
                <label className="row" style={{ gap: 4 }}>
                  <input type="checkbox" checked={p.ai_allowed ?? (k !== 'social')}
                    onChange={(e) => setPrivacyOpt(k, 'ai_allowed', e.target.checked)} /> AI 可用
                </label>
                <label className="row" style={{ gap: 4 }}>
                  <input type="checkbox" checked={p.visible ?? true}
                    onChange={(e) => setPrivacyOpt(k, 'visible', e.target.checked)} /> 可见
                </label>
                <label className="row" style={{ gap: 4 }}>
                  <input type="checkbox" checked={p.pin_required ?? false}
                    onChange={(e) => setPrivacyOpt(k, 'pin_required', e.target.checked)} /> 需 PIN
                </label>
              </div>
            </div>
          )
        })}
      </div>

      <div className="card">
        <b>🤖 LLM 配置(默认智谱 GLM){!isAdmin && <span className="badge gray" style={{ marginLeft: 8 }}>仅管理员可修改</span>}</b>
        {isAdmin ? (
        <>
        <p className="muted">端点为 OpenAI 兼容协议,可切换 DeepSeek 等其他服务;配置持久化在本机 data/llm_config.json。建议先填 API Key 后点"↻ 刷新模型"获取该账号可用的模型列表。</p>
        <div className="row" style={{ marginTop: 8 }}>
          {keyMasked && !apiKey ? (
            <>
              <input value={keyMasked} readOnly type="password" style={{ flex: 1, minWidth: 200, color: 'var(--muted)' }} />
              <button className="ghost" onClick={revealKey}>👁 查看</button>
            </>
          ) : (
            <input
              placeholder={keyMasked ? '输入新 API Key(留空保持不变)' : '粘贴 API Key'}
              value={apiKey} style={{ flex: 1, minWidth: 200 }}
              type={keyRevealed ? 'text' : 'password'}
              onChange={(e) => setApiKey(e.target.value)} />
          )}
          {apiKey && <button className="ghost" onClick={() => { setApiKey(''); setKeyRevealed(false) }}>清空</button>}
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <input placeholder="端点 URL" value={llmCfg.base_url} style={{ flex: 1, minWidth: 260 }}
            onChange={(e) => setLlmCfg({ ...llmCfg, base_url: e.target.value })} />
          <button className="ghost" onClick={reloadModels} title="从服务商刷新可选模型列表">↻ 刷新模型</button>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          {!customModel ? (
            <>
              <select value={llmCfg.model} style={{ width: 220 }}
                onChange={(e) => {
                  if (e.target.value === '__custom__') { setCustomModel(true); return }
                  setLlmCfg({ ...llmCfg, model: e.target.value })
                }}>
                {models.map((m) => <option key={m} value={m}>{m}</option>)}
                <option value="__custom__">自定义模型…</option>
              </select>
              <span className="muted">模型来源:{modelSource === 'provider' ? '服务商实时列表' : '预设列表'}</span>
            </>
          ) : (
            <>
              <input placeholder="输入模型代码,如 glm-5.3-flash" value={llmCfg.model} style={{ width: 220 }}
                onChange={(e) => setLlmCfg({ ...llmCfg, model: e.target.value })} />
              <button className="ghost" onClick={() => setCustomModel(false)}>改用列表选择</button>
            </>
          )}
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <span className="muted" style={{ width: 86 }}>🧠 思考强度</span>
          <select value={llmCfg.thinking || 'default'} style={{ width: 220 }}
            onChange={(e) => setLlmCfg({ ...llmCfg, thinking: e.target.value })}>
            <option value="default">默认(跟随服务商)</option>
            <option value="off">关闭(响应最快)</option>
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高(更强推理)</option>
          </select>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button onClick={saveKey}>保存配置</button>
          <button className="ghost" onClick={testLlm}>测试连接</button>
        </div>
        </>
        ) : (
          <>
          <p className="muted">当前端点:{llmCfg.base_url} · 模型:{llmCfg.model}{keyMasked ? ` · API Key:${keyMasked}` : ' · 未配置 API Key'} · 思考强度:{({ default: '默认', off: '关闭', low: '低', medium: '中', high: '高' })[llmCfg.thinking || 'default']}</p>
          <p className="muted">修改 LLM 配置请联系管理员。</p>
          </>
        )}
      </div>

      <div className="card">
        <b>💾 数据备份</b>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="ghost" onClick={exportData}>导出备份(VACUUM INTO 一致性快照)</button>
          <label className="btn ghost" style={{ cursor: 'pointer' }}>
            导入备份
            <input type="file" accept=".db" style={{ display: 'none' }} onChange={importData} />
          </label>
        </div>
      </div>

      <p className="muted">用户管理已移至独立页面:侧边栏「👑 用户管理」(仅管理员可见)。</p>

      {msg && <div className="card">{msg}</div>}
    </div>
  )
}
