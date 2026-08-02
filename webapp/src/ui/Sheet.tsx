// Шторка — модальная панель снизу экрана. Поведение и структура повторяют
// openSheet/closeSheet из miniapp/prototype.html:1469-1485: заголовок,
// кнопка закрытия с доступным именем «Закрыть», прокручиваемое тело,
// затемнение фона (скрим), закрытие по клику на скрим.
//
// Открытие/закрытие здесь не анимируется (в отличие от макета, где
// closeSheet выставляет transform и ждёт transition через setTimeout):
// Sheet монтируется React'ом ровно тогда, когда шторка открыта, и
// размонтируется при закрытии — переходной анимации монтирования без
// отдельной анимационной библиотеки (которых нельзя добавлять) не сделать
// корректно, поэтому от неё отказались.
//
// Клавиша Escape и кнопка «назад» Telegram закрывают шторку тоже, но эта
// логика — на уровне стека (App.tsx), а не здесь: если каждый экземпляр
// Sheet сам слушает Escape на document, при стеке из нескольких шторок
// одно нажатие Escape закрыло бы все разом (у каждой свой обработчик).
import { useEffect, useRef } from "react"
import type { ReactNode } from "react"

type SheetProps = {
  title: string
  onClose: () => void
  children: ReactNode
}

export function Sheet({ title, onClose, children }: SheetProps) {
  const closeRef = useRef<HTMLButtonElement>(null)

  // Фокус уходит на кнопку закрытия при открытии — как $("#sheetX").focus()
  // в макете (openSheet, строка 1478).
  useEffect(() => {
    closeRef.current?.focus()
  }, [])

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title">
        <div className="sheet__h">
          <div className="sheet__grab" aria-hidden="true" />
          <b id="sheet-title">{title}</b>
          <button type="button" ref={closeRef} className="sheet__x" aria-label="Закрыть" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="sheet__b">{children}</div>
      </aside>
    </>
  )
}
