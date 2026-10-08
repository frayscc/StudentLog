import { FormEvent, useEffect, useState } from 'react'
import { api } from './api'

type LLMConfig = { provider: 'mock' | 'deepseek'; api_key_configured: boolean }

export default function LLMSettings() {
  const [config, setConfig] = useState<LLMConfig>()
  const [provider, setProvider] = useState<LLMConfig['provider']>('mock')
  const [key, setKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function load() {
    setError('')
    try { const value = await api<LLMConfig>('/settings/llm'); setConfig(value); setProvider(value.provider) }
    catch (err) { setError((err as Error).message) }
  }
  useEffect(() => { void load() }, [])

  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('')
    try {
      const value = await api<LLMConfig>('/settings/llm', {
        method: 'PUT', body: JSON.stringify({ provider, ...(key ? { api_key: key } : {}), clear_api_key: clearKey }),
      })
      setConfig(value); setKey(''); setClearKey(false)
      setMessage('设置已保存，立即生效。')
    } catch (err) { setError((err as Error).message) }
    finally { setBusy(false) }
  }

  return <section className="settings-panel">
    <div className="section-title"><div><h2>AI 整理与阶段性摘要</h2><p>启用 DeepSeek 后，仅在点击整理或摘要时发送文字内容。语音识别仍在本机运行。</p></div></div>
    {config ? <form className="form-grid" onSubmit={save}>
      <label>整理方式<select value={provider} disabled={busy} onChange={e => setProvider(e.target.value as LLMConfig['provider'])}>
        <option value="mock">离线基础整理（无云端 AI）</option><option value="deepseek">DeepSeek AI</option>
      </select></label>
      <label>DeepSeek API Key<input type="password" value={key} disabled={busy || clearKey} autoComplete="off" spellCheck={false}
        placeholder={config.api_key_configured ? '已配置；留空保留，输入可替换' : '填写 API Key'} onChange={e => setKey(e.target.value)} /></label>
      {config.api_key_configured && <label><span><input type="checkbox" checked={clearKey} disabled={busy}
        onChange={e => { setClearKey(e.target.checked); if (e.target.checked) { setKey(''); setProvider('mock') } }} /> 清除已保存的密钥并使用离线整理</span></label>}
      <p className="privacy-note">密钥只保存在本机，不会回显。完整 ZIP 备份包含本地配置，请妥善保存备份文件。</p>
      <div className="form-actions"><button className="primary" disabled={busy}>{busy ? '正在保存…' : '保存 AI 设置'}</button></div>
    </form> : <button className="secondary" onClick={() => void load()}>重新读取 AI 设置</button>}
    {error && <p className="form-error" role="alert">{error}</p>}{message && <p className="settings-message" role="status">{message}</p>}
  </section>
}
