// Posición del recorte del brazo/mano sobre el cuerpo (robot-body.png, 1129x970).
// El cuerpo tiene ese hueco siempre transparente: una capa de brazo lo cubre
// por completo, así nunca se asoma un brazo "fantasma" detrás. Lo usan el
// robot animado de la app (RobotGreeter) y la portada del PDF del ADR (adrPrint).
export const ROBOT_ASPECT_RATIO = '1129 / 970'
export const ARM_STYLE = {
  left: '62.0%',
  top: '19.6%',
  width: '32.8%',
  height: '32.0%',
}
