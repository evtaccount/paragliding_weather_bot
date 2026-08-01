// Индикатор загрузки. У макета его нет — прототип статичен и не показывает
// состояния загрузки; класс .spinner заведён отдельно в styles.css, цвет
// берётся из тех же переменных темы (--rule/--ink), без литералов здесь.
export function Spinner() {
  return <span className="spinner" role="status" aria-label="Загрузка" />
}
