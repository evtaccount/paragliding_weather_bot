// Иконки маркеров — L.divIcon с инлайновым цветом из palette.ts вместо
// штатных PNG-иконок Leaflet: те ищут файлы по относительному URL (см.
// leaflet.Icon.Default.imagePath), который под сборкой Vite не резолвится
// (известная проблема связки Leaflet+Vite) — в проде маркер рисуется
// сломанной картинкой. divIcon с цветным кружком полностью обходит проблему
// и не требует новых файлов-ассетов (глобальное ограничение задачи — новых
// зависимостей не добавлять).
//
// Цвет различает точку маршрута (перетаскиваемую) и старт (справочную,
// неподвижную); обводка и тень — свои, отдельные константы. Все четыре
// цвета берутся только из palette.ts (PIN_RING/PIN_SHADOW заведены там же
// специально ради этого — своих hex здесь нет ни одного).
import L from "leaflet"
import { PIN_RING, PIN_SHADOW, TERRAIN, WIND } from "../charts/palette"

function dot(color: string, size: number, extraClass: string): L.DivIcon {
  return L.divIcon({
    className: `pgbot-pin ${extraClass}`,
    html: `<span style="display:block;width:${size}px;height:${size}px;border-radius:50%;background:${color};border:2px solid ${PIN_RING};box-shadow:0 0 2px ${PIN_SHADOW}"></span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  })
}

// Точка маршрута — перетаскиваемый маркер (см. MapView: onDragPoint).
export function routePointIcon(): L.DivIcon {
  return dot(WIND, 16, "pgbot-pin--point")
}

// Старт — справочная точка на карте, сама не двигается.
export function siteIcon(): L.DivIcon {
  return dot(TERRAIN, 12, "pgbot-pin--site")
}
