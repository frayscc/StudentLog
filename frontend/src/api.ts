export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  let response: Response
  try {
    response = await fetch(`/api${path}`, { ...init, headers, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, '无法连接 StudentLog 服务，请检查容器是否正在运行后重试')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: '操作失败，请重试' }))
    throw new ApiError(response.status, body.detail || '操作失败，请重试')
  }
  return response.json()
}
