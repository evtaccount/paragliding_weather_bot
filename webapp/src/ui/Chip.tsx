// Мелкий информационный ярлык. Класс и модификатор — из макета
// (miniapp/prototype.html: .chip/.chip--live, строки 115-117; кнопка модели
// в шапке — строка 423). Без onClick рендерится как span (например для
// значений, которые пока никуда не ведут), с onClick — как кнопка (так в
// макете сделаны и модельный чип в шапке, и чипы времени вылета маршрута,
// строка 1160).
import type { ReactNode } from "react"

type ChipProps = {
  children: ReactNode
  live?: boolean
  onClick?: () => void
  // Открывает ли нажатие шторку. Чипы бывают и без неё (время вылета на
  // «Маршруте» просто переключает выбор), поэтому это отдельный признак, а не
  // следствие onClick: обещать диалог там, где его нет, — та же неправда, что
  // и промолчать о нём там, где он есть.
  opensSheet?: boolean
}

export function Chip({ children, live, onClick, opensSheet }: ChipProps) {
  const className = live ? "chip chip--live" : "chip"
  if (onClick) {
    return (
      <button type="button" className={className} aria-haspopup={opensSheet ? "dialog" : undefined} onClick={onClick}>
        {children}
      </button>
    )
  }
  return <span className={className}>{children}</span>
}
