// Показ ошибки API — текст для пилота (ApiError.userMessage) и кнопка
// повтора. Кнопки нет при 401/403: 401 — подпись Telegram не прошла
// проверку (см. client.ts:toApiError), повторять тот же запрос бессмысленно,
// пока приложение не откроют заново из Telegram; 403 — пилот не в списке
// допущенных, повтор тоже ничего не изменит.
import type { ApiError } from "../api/client"

type ErrorBoxProps = {
  error: ApiError
  onRetry: () => void
}

export function ErrorBox({ error, onRetry }: ErrorBoxProps) {
  const canRetry = error.status !== 401 && error.status !== 403
  return (
    <div className="empty">
      <b>Не получилось</b>
      {error.userMessage}
      {canRetry && (
        <div>
          <button type="button" onClick={onRetry}>Повторить</button>
        </div>
      )}
    </div>
  )
}
