// API client with JWT auth header
let token = localStorage.getItem('lifeos_token') || ''

// token 与 Cookie 保持同步:<img> 等资源请求无法携带 Authorization 头,
// 图片等接口用 lifeos_token Cookie 兜底鉴权
function syncCookie(t) {
  if (t) document.cookie = `lifeos_token=${t}; path=/; SameSite=Strict; max-age=${7 * 24 * 3600}`
  else document.cookie = 'lifeos_token=; path=/; SameSite=Strict; max-age=0'
}

export function setToken(t) {
  token = t || ''
  if (t) localStorage.setItem('lifeos_token', t)
  else localStorage.removeItem('lifeos_token')
  syncCookie(token)
}

if (token) syncCookie(token)

export function getToken() {
  return token
}

async function request(method, url, body, isForm = false) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (body && !isForm) headers['Content-Type'] = 'application/json'
  const res = await fetch(url, {
    method,
    headers,
    body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
  })
  if (res.status === 401 && !url.includes('/auth/')) {
    setToken('')
    window.location.href = '/login'
    throw new Error('未登录')
  }
  if (!res.ok) {
    let msg = `${res.status}`
    try {
      const data = await res.json()
      msg = data.detail || msg
    } catch {}
    throw new Error(msg)
  }
  return res.json()
}

export const api = {
  get: (url) => request('GET', url),
  post: (url, body) => request('POST', url, body),
  put: (url, body) => request('PUT', url, body),
  del: (url) => request('DELETE', url),
  postForm: (url, formData) => request('POST', url, formData, true),
}
