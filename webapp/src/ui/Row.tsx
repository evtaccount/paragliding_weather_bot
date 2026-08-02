// Строка списка настроек/старта. Структура и классы — из макета
// (miniapp/prototype.html: .row/.row__m/.row__t/.row__s/.row__v,
// строки 302-311; разметка строк — renderSet, например строки 1372-1379,
// 1423-1431). Заголовок и необязательный подзаголовок идут в .row__m;
// произвольное содержимое справа (текст, переключатель, степпер) — как
// value. Без onClick строка не кликабельна (div), с onClick — кнопка,
// как строки старта/модели в макете.
import type { ReactNode } from "react"

type RowProps = {
  title: string
  subtitle?: string
  value?: ReactNode
  onClick?: () => void
}

export function Row({ title, subtitle, value, onClick }: RowProps) {
  const content = (
    <>
      <div className="row__m">
        <div className="row__t">{title}</div>
        {subtitle !== undefined && <div className="row__s">{subtitle}</div>}
      </div>
      {value}
    </>
  )
  if (onClick) {
    return (
      <button type="button" className="row" onClick={onClick}>
        {content}
      </button>
    )
  }
  return <div className="row">{content}</div>
}
